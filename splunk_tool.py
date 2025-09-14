import requests
from urllib3.exceptions import InsecureRequestWarning
import urllib3
from typing import Any
from splunk_agent_config import get_config
import xml.etree.ElementTree as ET
import json

# Suppress only the single InsecureRequestWarning from urllib3 needed for self-signed certs
urllib3.disable_warnings(category=InsecureRequestWarning)

def extract_fields_from_log_with_llm(raw_log: str, llm) -> dict:
    prompt = f"""
Extract the following fields from this log and return as JSON:
- pod_name
- aem_envType
- aem_tier
- cluster
- aem_program_id
- namespace
- aem_release_id
- aem_service
- msg
- event_time (the timestamp of the event, e.g., '6/18/25 11:50:17.564 PM' or similar, if present)

Log:
{raw_log}
"""
    content = llm.call(prompt)
    import json, re
    try:
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            return json.loads(match.group(0))
        else:
            return {"error": "No JSON found in LLM response.", "raw": content}
    except Exception as e:
        return {"error": f"Failed to parse JSON: {e}", "raw": content}

def splunk_search_tool(query: str, llm=None, use_llm: bool = False):
    config = get_config()
    url = f"https://{config['splunk_host']}:{config['splunk_port']}/services/search/jobs"
    auth = (config['splunk_username'], config['splunk_password'])
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    print(f"Splunk search is invoked with query")
    data = {
        "search": f"search {query}",
        "exec_mode": "blocking"
    }
    try:
        response = requests.post(url, auth=auth, headers=headers, data=data, verify=False)
        if response.status_code in (200, 201):
            sid = None
            # Try to get sid from JSON
            try:
                sid = response.json().get("sid")
            except Exception:
                pass
            # If not found, try to parse sid from XML
            if not sid:
                try:
                    root = ET.fromstring(response.text)
                    sid_elem = root.find(".//sid")
                    if sid_elem is not None:
                        sid = sid_elem.text
                except Exception:
                    sid = None
            if not sid:
                return f"Splunk search started but no sid found. Raw response: {response.text}"
            # Fetch results using sid
            results_url = f"https://{config['splunk_host']}:{config['splunk_port']}/services/search/jobs/{sid}/results?output_mode=json"
            results_response = requests.get(results_url, auth=auth, headers={"Accept": "application/json"}, verify=False)
            if results_response.status_code == 200:
                try:
                    data = results_response.json()
                    results = data.get("results", [])
                    extracted = []
                    print(f"Splunk results")
                    for result in results[:10]:
                        raw = result.get("_raw", "")
                        if not use_llm:
                            # Default: try to parse _raw as JSON, fallback to top-level
                            raw_json = {}
                            if raw:
                                try:
                                    raw_json = json.loads(raw)
                                except Exception:
                                    raw_json = {}
                            def get_field(field):
                                return raw_json.get(field) or result.get(field, "")
                            msg = get_field("msg")
                            if msg:
                                msg_lines = msg.splitlines()
                                if len(msg_lines) > 10:
                                    msg = '\n'.join(msg_lines[:10]) + '\n... (truncated)'
                                else:
                                    msg = '\n'.join(msg_lines)
                            extracted_fields = {
                                "pod_name": get_field("pod_name"),
                                "aem_envType": get_field("aem_envType"),
                                "aem_tier": get_field("aem_tier"),
                                "cluster": get_field("cluster"),
                                "aem_program_id": get_field("aem_program_id"),
                                "namespace": get_field("namespace"),
                                "aem_release_id": get_field("aem_release_id"),
                                "aem_service": get_field("aem_service"),
                                "msg": msg,
                            }
                        else:
                            # Optional LLM path (disabled by default)
                            extracted_fields = {}
                            if raw:
                                try:
                                    extracted_fields = extract_fields_from_log_with_llm(raw, llm)
                                except Exception:
                                    extracted_fields = {}
                            msg = extracted_fields.get("msg", "")
                            if msg:
                                msg_lines = msg.splitlines()
                                if len(msg_lines) > 10:
                                    msg = '\n'.join(msg_lines[:10]) + '\n... (truncated)'
                                else:
                                    msg = '\n'.join(msg_lines)
                                extracted_fields["msg"] = msg
                        extracted.append(extracted_fields)
                        print("Extracted fields: ", extracted_fields)
                    return extracted
                except Exception as e:
                    return f"Error parsing Splunk results: {e}\nRaw: {results_response.text}"
            else:
                return f"Splunk search job started, but failed to fetch results: {results_response.text}"
        else:
            return f"Splunk search failed: {response.text}"
    except Exception as e:
        return f"Error querying Splunk: {e}"

def splunk_search_rows(query: str):
    config = get_config()
    url = f"https://{config['splunk_host']}:{config['splunk_port']}/services/search/jobs"
    auth = (config['splunk_username'], config['splunk_password'])
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"search": f"search {query}", "exec_mode": "blocking"}
    response = requests.post(url, auth=auth, headers=headers, data=data, verify=False)
    if response.status_code not in (200, 201):
        return []
    sid = None
    try:
        sid = response.json().get("sid")
    except Exception:
        pass
    if not sid:
        try:
            root = ET.fromstring(response.text)
            sid_elem = root.find(".//sid")
            if sid_elem is not None:
                sid = sid_elem.text
        except Exception:
            sid = None
    if not sid:
        return []
    results_url = f"https://{config['splunk_host']}:{config['splunk_port']}/services/search/jobs/{sid}/results?output_mode=json"
    results_response = requests.get(results_url, auth=auth, headers={"Accept": "application/json"}, verify=False)
    if results_response.status_code != 200:
        return []
    try:
        data = results_response.json()
        return data.get("results", [])
    except Exception:
        return []

def get_last_error_paths(aem_service: str, env_type: str, aem_tier: str, earliest: str = None, latest: str = None):
    terms = ['index=dx_aem_engineering', 'sourcetype=aemaccess']
    if aem_service:
        terms.append(f'aem_service={aem_service}')
    if env_type:
        terms.append(f'aem_envType={env_type}')
    if aem_tier:
        terms.append(f'aem_tier={aem_tier}')
    terms.append('(path="/adobe/forms/af/submit*" OR path="*guideContainer.af.submit.jsp")')
    terms.append('code>=500')
    base = ' '.join(terms)
    if earliest and latest:
        base += f' earliest="{earliest}" latest="{latest}"'
    query = (
        f'{base} '
        '| stats latest(_time) as LastErrorTime by path '
        '| eval LastErrorTime=strftime(LastErrorTime, "%Y-%m-%d %H:%M:%S %Z") '
        '| table path, LastErrorTime'
    )
    print(f"Splunk query for last error paths: {query}")
    rows = splunk_search_rows(query)
    out = []
    for r in rows:
        path = r.get('path', '')
        last = r.get('LastErrorTime', '')
        if path and last:
            out.append({"path": path, "LastErrorTime": last})
    return out

def list_services_with_errors(earliest: str = None, latest: str = None):
    terms = [
        'index=dx_aem_engineering',
        'sourcetype=aemaccess',
        'aem_tier="publish"',
        '(path="/adobe/forms/af/submit*" OR path="*guideContainer.af.submit.jsp")',
        'aem_envType=prod',
        'aem_program_id IN (*)',
        'namespace="*"',
        'code>=500'
    ]
    base = ' '.join(terms)
    if earliest and latest:
        base += f' earliest="{earliest}" latest="{latest}"'
    query = (
        f'{base} '
        '| lookup skyline_program_id_to_program_name program_id as aem_program_id OUTPUT program_name '
        '| fillnull program_name value="<unknown program name>" '
        '| stats count as ErrorCount by aem_service, program_name '
        '| sort - ErrorCount'
    )
    print(f"Splunk query for list services with errors: {query}")
    rows = splunk_search_rows(query)
    out = []
    for r in rows:
        svc = r.get('aem_service') or r.get('TenantID') or ''
        prog = r.get('program_name') or r.get('ProgramName') or ''
        try:
            cnt = int(r.get('ErrorCount', '0'))
        except Exception:
            cnt = 0
        if svc:
            out.append({
                'aem_service': svc,
                'program_name': prog,
                'error_count': cnt,
            })
    return out

def get_top_error_times(aem_service: str, env_type: str, aem_tier: str, earliest: str = None, latest: str = None, limit: int = 10):
    # Use access logs with per-path streamstats to derive latest failure times
    path_to_times = get_latest_failures_by_path(aem_service, env_type, aem_tier, earliest, latest, per_path_limit=limit)
    flattened = []
    for times in path_to_times.values():
        flattened.extend(times)
    # keep unique in order
    seen = set()
    uniq = []
    for t in flattened:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq

def get_latest_failures_by_path(aem_service: str, env_type: str, aem_tier: str, earliest: str = None, latest: str = None, per_path_limit: int = 10):
    terms = [
        'index=dx_aem_engineering',
        'sourcetype=aemaccess'
    ]
    if aem_service:
        terms.append(f'aem_service={aem_service}')
    if env_type:
        terms.append(f'aem_envType={env_type}')
    if aem_tier:
        terms.append(f'aem_tier={aem_tier}')
    terms.append('(path="/adobe/forms/af/submit*" OR path="*guideContainer.af.submit.jsp")')
    terms.append('code>=500')
    base = ' '.join(terms)
    if earliest and latest:
        base += f' earliest="{earliest}" latest="{latest}"'
    query = (
        f'{base} '
        '| sort 0 - _time '
        '| streamstats count as failureCount by path '
        f'| where failureCount <= {per_path_limit} '
        '| eval FailureTime=strftime(_time, "%Y-%m-%d %H:%M:%S") '
        '| table path, FailureTime'
    )
    print(f"Splunk query for latest failures by path: {query}")
    rows = splunk_search_rows(query)
    print(f"Rows of paths with failures: {rows}")
    path_to_times = {}
    for r in rows:
        p = r.get('path') or ''
        t = r.get('FailureTime') or ''
        if not p or not t:
            continue
        path_to_times.setdefault(p, []).append(t)
    return path_to_times

def build_multi_window_error_query(aem_service: str, env_type: str, aem_tier: str, window_times: list[str], label_prefix: str = "") -> str:
    # window_times are strings in format YYYY-MM-DD HH:MM:SS; we will create [time, time+10s] windows
    terms = [
        'index=dx_aem_engineering',
        'level=ERROR',
        'sourcetype=aemerror'
    ]
    if aem_service:
        terms.append(f'aem_service={aem_service}')
    if env_type:
        terms.append(f'aem_envType={env_type}')
    if aem_tier:
        terms.append(f'aem_tier={aem_tier}')
    terms.append('(*guideContainer.af.submit.jsp* OR *FormSubmitActionManagerServiceImpl* OR *AdaptiveFormSubmitServlet*)')
    base = ' '.join(terms)

    evals = []
    cases = []
    for idx, center in enumerate(window_times, start=1):
        # Build start/end using start = center, end = center + 10 seconds
        evals.append(
            f'| eval in_window{idx}=if(_time>=strptime("{center}","%Y-%m-%d %H:%M:%S") AND _time<=strptime("{center}","%Y-%m-%d %H:%M:%S")+10,1,0)'
        )
        # Window label shows HH:MM range around center
        cases.append(f'in_window{idx}=1,"{label_prefix}#{idx}"')
    case_expr = ', '.join(cases) + ', 1=1,"Other"'
    query = base + ' ' + ' '.join(evals) + f' | eval Window=case({case_expr}) | search Window!="Other" | table Window, _time, msg | sort Window, _time'
    return query
 