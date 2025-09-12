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
 