import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import json
from crewai import LLM, Agent, Task, Crew
from jira_tool import jira_query_tool, create_jira_issue, add_jira_comment, link_jira_issues, get_linked_forms_jira, get_jira_comments, get_jira_status, search_skysi_by_aem_service
from aem_extractor_tool import extract_aem_fields_from_description
from splunk_tool import splunk_search_tool, splunk_search_rows, get_last_error_paths, list_services_with_errors, get_top_error_times, get_latest_failures_by_path, build_multi_window_error_query, list_services_total_submissions, get_daily_submission_stats, get_daily_counts_for_date
from datetime import datetime, timedelta
from flask_cors import CORS
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, XPreformatted, PageBreak, Table, TableStyle, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm

load_dotenv()

llm = LLM(
    model="azure/gpt-4.1",
)

app = Flask(__name__)
CORS(app)

# In-memory cache for report JSON
REPORT_CACHE = {}
REPORT_CACHE_PATH = os.getenv('REPORT_CACHE_PATH', os.path.join(os.path.dirname(__file__), 'report_cache.json'))

def _resolve_cache_file_path() -> str:
    """Return a writable file path for the report cache.
    - If REPORT_CACHE_PATH is a directory (or has no extension), write report_cache.json inside it.
    - Otherwise treat REPORT_CACHE_PATH as a file path and ensure its parent exists.
    """
    base = REPORT_CACHE_PATH
    try:
        # If explicitly a directory, or no file extension provided, use default filename inside.
        is_dir_like = base.endswith(os.sep) or (os.path.splitext(base)[1] == '')
        if is_dir_like:
            dir_path = base
        else:
            # If exists and is a dir, treat as dir; else parent dir is dirname(base)
            if os.path.isdir(base):
                dir_path = base
            else:
                dir_path = os.path.dirname(base) or os.getcwd()
                # Ensure parent exists for file path
                os.makedirs(dir_path, exist_ok=True)
                return base
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, 'report_cache.json')
    except Exception as e:
        print(f"Failed to resolve cache file path from '{base}': {e}")
        fallback = os.path.join(os.path.dirname(__file__), 'report_cache.json')
        try:
            os.makedirs(os.path.dirname(fallback), exist_ok=True)
        except Exception:
            pass
        return fallback

def _resolve_cache_dir_and_file() -> tuple[str, str]:
    """Return (dir_path, default_file_path)."""
    base = REPORT_CACHE_PATH
    try:
        is_dir_like = base.endswith(os.sep) or (os.path.splitext(base)[1] == '')
        if is_dir_like:
            dir_path = base
        else:
            if os.path.isdir(base):
                dir_path = base
            else:
                dir_path = os.path.dirname(base) or os.getcwd()
                os.makedirs(dir_path, exist_ok=True)
                return (dir_path, base)
        os.makedirs(dir_path, exist_ok=True)
        return (dir_path, os.path.join(dir_path, 'report_cache.json'))
    except Exception:
        dir_path = os.path.dirname(__file__)
        try:
            os.makedirs(dir_path, exist_ok=True)
        except Exception:
            pass
        return (dir_path, os.path.join(dir_path, 'report_cache.json'))

def build_report_data(earliest: str, latest: str, services: list[str] | None = None) -> dict:
    # 1) Top services and counts
    svc_rows = list_services_with_errors(earliest, latest)
    # print(f"Services with errors: {svc_rows}")
    counts_map = {r['aem_service']: r.get('error_count', 0) for r in svc_rows}
    program_map = {r['aem_service']: r.get('program_name', '<unknown program name>') for r in svc_rows}
    jira_base = os.getenv('JIRA_URL', 'https://jira.corp.adobe.com')
    for r in svc_rows:
        aem_service_val = r.get('aem_service', '')
        skysi_key = ''
        try:
            lookup = search_skysi_by_aem_service(aem_service_val) if aem_service_val else {}
            issues = lookup.get('issues') or []
            if issues:
                skysi_key = issues[0].get('key', '')
        except Exception:
            skysi_key = ''
        r['skysi_key'] = skysi_key
        r['skysi_url'] = f"{jira_base}/browse/{skysi_key}" if skysi_key else ''

    if not services:
        services = [r['aem_service'] for r in svc_rows]

    print(f"Services: {services}")

    # 2) Per-service aggregation
    totals_map = list_services_total_submissions(earliest, latest)
    report_items = []
    for aem_service in services:
        failures_by_path = get_latest_failures_by_path(aem_service, "prod", "publish", earliest=earliest, latest=latest, per_path_limit=10)

        base_error = (
            f'index=dx_aem_engineering sourcetype=aemerror level=ERROR '
            f'aem_service={aem_service} aem_envType=prod aem_tier=publish '
            '(*guideContainer.af.submit.jsp* OR *FormSubmitActionManagerServiceImpl* OR *AdaptiveFormSubmitServlet*) '
            f'earliest="{earliest}" latest="{latest}" '
        )
        sub = (
            '[ search index=dx_aem_engineering sourcetype=aemaccess '
            f'aem_service={aem_service} aem_envType=prod aem_tier=publish '
            '(path="/adobe/forms/af/submit*" OR path="*guideContainer.af.submit.jsp") code>=500 '
            f'earliest="{earliest}" latest="{latest}" '
            '| sort 0 - _time '
            '| streamstats count as failCount by path '
            '| where failCount <= 10 '
            '| eval f_start=_time, f_end=_time+10 '
            '| eval query="(_time>=" . f_start . " AND _time<=" . f_end . ")" '
            '| stats values(query) as queries '
            '| eval search="(" . mvjoin(queries," OR ") . ")" '
            '| fields search ] '
        )
        final_query = base_error + sub + '| eval EventTimeFmt=strftime(_time,"%Y-%m-%d %H:%M:%S") | table EventTimeFmt msg'
        rows = splunk_search_rows(final_query) or []
        # print(f"Rows: {rows}")

        from datetime import datetime as _dt
        windows = []
        for p, times in failures_by_path.items():
            for tstr in times:
                try:
                    sdt = _dt.strptime(tstr, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                edt = sdt + timedelta(seconds=10)
                windows.append((p, sdt, edt))

        path_to_msgs = {p: [] for p in failures_by_path.keys()}
        path_to_seen = {p: set() for p in failures_by_path.keys()}
        for r in rows:
            et = (r.get('EventTimeFmt') or '').split('.')[0]
            msg = (r.get('msg') or '').strip()
            if not et or not msg:
                continue
            try:
                evt_dt = _dt.strptime(et, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            matched = None
            for p, sdt, edt in windows:
                if sdt <= evt_dt <= edt:
                    matched = p
                    break
            if matched and msg not in path_to_seen[matched] and len(path_to_msgs[matched]) < 10:
                # Store both time and message so UI can show timestamp next to each message
                path_to_msgs[matched].append({"time": et, "msg": msg})
                path_to_seen[matched].add(msg)

        path_entries = []
        for p, times in failures_by_path.items():
            path_entries.append({
                "path": p,
                "time": ", ".join(times[:10]),
                "messages": path_to_msgs.get(p, [])
            })

        total_forms = totals_map.get(aem_service, 0)
        print(f"Total forms for {aem_service}: {total_forms}")
        report_items.append({
            "aem_service": aem_service,
            "error_count": counts_map.get(aem_service, 0),
            "total_form_submissions": total_forms,
            "failure_rate_pct": round((counts_map.get(aem_service, 0) / total_forms) * 100, 2) if total_forms else 0.0,
            "program_name": program_map.get(aem_service, '<unknown program name>'),
            "paths": path_entries
        })

    from datetime import datetime
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "earliest": earliest,
        "latest": latest,
        "services": services,
        "svc_rows": svc_rows,
        "report_items": report_items,
    }

def render_dashboard_html(svc_rows: list, report_items: list, earliest: str, latest: str) -> str:
    from html import escape as html_escape
    def trunc15(msg: str) -> str:
        _lines = (msg or '').split('\n')
        return ('\n'.join(_lines[:15]) + '\n...') if len(_lines) > 15 else msg
    css = (
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; margin: 24px; }"
        "h1 { color: #0D47A1; }"
        "h2 { color: #1565C0; margin-top: 24px; }"
        ".summary { border-collapse: collapse; width: 100%; margin: 12px 0; }"
        ".summary th { background:#1565C0; color:#fff; padding:6px; text-align:left; }"
        ".summary td { border:1px solid #B0BEC5; padding:6px; }"
        ".path-badge { background:#1976D2; color:#fff; padding:4px 6px; border-radius:4px; display:inline-block; }"
        ".time { color:#546E7A; margin:6px 0; }"
        ".msg-title { color:#37474F; font-weight:600; margin:8px 0 4px; }"
        "pre.msg { background:#ECEFF1; border:1px solid #B0BEC5; padding:4px; white-space:pre-wrap; word-break:break-word; }"
    )
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Daily Forms Submit Errors Dashboard</title>",
        f"<style>{css}</style></head><body>",
        "<h1>Daily Forms Submit Errors Dashboard</h1>",
        f"<div>Range: {html_escape(earliest)} → {html_escape(latest)}</div>",
    ]
    if svc_rows:
        parts.append("<table class='summary'>")
        parts.append("<tr><th>TenantID</th><th>ProgramName</th><th>ErrorCount</th><th>SKYSI</th></tr>")
        for r in svc_rows:
            skysi = r.get('skysi_key')
            skysi_url = r.get('skysi_url')
            skysi_html = f"<a href='{html_escape(skysi_url)}'>{html_escape(skysi)}</a>" if skysi and skysi_url else "-"
            parts.append(
                "<tr>"
                f"<td>{html_escape(r.get('aem_service',''))}</td>"
                f"<td>{html_escape(r.get('program_name','<unknown program name>'))}</td>"
                f"<td>{int(r.get('error_count',0))}</td>"
                f"<td>{skysi_html}</td>"
                "</tr>"
            )
        parts.append("</table>")
    for item in report_items:
        svc_title = (
            f"Service: {item['aem_service']} "
            f"Program Name: {item.get('program_name','<unknown program name>')} "
            f"(Failures: {item.get('error_count', 0)})"
        )
        parts.append(f"<h2>{html_escape(svc_title)}</h2>")
        for pe in item.get('paths', [])[:10]:
            parts.append(f"<div class='path-badge'>Path: {html_escape(pe.get('path',''))}</div>")
            if pe.get('time'):
                parts.append(f"<div class='time'>Time: {html_escape(pe['time'])}</div>")
            msgs = pe.get('messages') or []
            if not msgs:
                parts.append("<div style='color:#B71C1C'>&lt;no messages&gt;</div>")
                continue
            for idx, m in enumerate(msgs, start=1):
                # Support both string messages and {time,msg} objects
                try:
                    text = m if isinstance(m, str) else (m.get('msg', '') if isinstance(m, dict) else str(m))
                except Exception:
                    text = str(m)
                parts.append(f"<div class='msg-title'>Message {idx}</div>")
                parts.append(f"<pre class='msg'>{html_escape(trunc15(text))}</pre>")
    parts.append("</body></html>")
    return ''.join(parts)

@app.route('/report-dates', methods=['GET'])
def report_dates():
    """List available dated cache files as YYYY-MM-DD, newest first."""
    try:
        dir_path, default_file = _resolve_cache_dir_and_file()
        names = []
        for fn in os.listdir(dir_path):
            if fn.startswith('report_cache_') and fn.endswith('.json'):
                mid = fn[len('report_cache_'):-len('.json')]
                names.append(mid)
        names = sorted(names, reverse=True)
        return jsonify({"dates": names})
    except Exception as e:
        print(f"Failed to list report dates: {e}")
        return jsonify({"dates": []})

@app.route('/report-refresh', methods=['POST'])
def report_refresh():
    """Compute and cache report JSON (to be triggered by cron)."""
    data = request.json or {}
    earliest = data.get('earliest') or '-1d'
    latest = data.get('latest') or 'now'
    services = data.get('aem_services')

    result = build_report_data(earliest, latest, services)
    REPORT_CACHE['data'] = result
    dated_file = None
    try:
        from datetime import datetime as _dt
        dir_path, default_file = _resolve_cache_dir_and_file()
        # Determine today's dated file name from generated_at (UTC date)
        gen = result.get('generated_at', '')[:10]
        try:
            dt = _dt.strptime(gen, '%Y-%m-%d')
        except Exception:
            dt = _dt.utcnow()
        dated_name = f"report_cache_{dt.strftime('%Y-%m-%d')}.json"
        dated_file = os.path.join(dir_path, dated_name)
        # Write dated file as primary
        with open(dated_file, 'w', encoding='utf-8') as f2:
            json.dump(result, f2, ensure_ascii=False, indent=2)
        # Also write legacy latest snapshot for backward compatibility
        try:
            with open(default_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as _e:
            print(f"Failed to write latest cache file: {_e}")
    except Exception as e:
        print(f"Failed to write report cache file: {e}")
    return jsonify({
        "status": "ok",
        "generated_at": result.get("generated_at"),
        "path": dated_file or _resolve_cache_file_path()
    })

@app.route('/report-data', methods=['GET'])
def report_data():
    """Return cached JSON. Optional query: ?date=YYYY-MM-DD to fetch dated cache."""
    date_arg = request.args.get('date', '').strip()
    try:
        dir_path, default_file = _resolve_cache_dir_and_file()
        target_file = default_file
        if date_arg:
            candidate = os.path.join(dir_path, f'report_cache_{date_arg}.json')
            if os.path.exists(candidate):
                target_file = candidate
        else:
            # No date specified: prefer today's dated cache if present
            from datetime import datetime as _dt
            today = _dt.utcnow().strftime('%Y-%m-%d')
            today_file = os.path.join(dir_path, f'report_cache_{today}.json')
            if os.path.exists(today_file):
                target_file = today_file
        if os.path.exists(target_file):
            with open(target_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            REPORT_CACHE['data'] = data
            return jsonify(data)
    except Exception as e:
        print(f"Failed to read report cache file: {e}")
    if 'data' in REPORT_CACHE:
        return jsonify(REPORT_CACHE['data'])
    return jsonify({"error": "no cached data; POST /report-refresh first"}), 404

@app.route('/report-week', methods=['GET'])
def report_week():
    """Merge daily caches for a Saturday→Friday week and return a weekly report.

    Query params:
      - friday: YYYY-MM-DD (optional). If omitted, uses the most recent Friday (UTC today or earlier).
    """
    from datetime import datetime as _dt, timedelta as _td
    friday_arg = (request.args.get('friday') or '').strip()
    try:
        dir_path, _default_file = _resolve_cache_dir_and_file()
        # Determine target Friday (UTC)
        if friday_arg:
            friday = _dt.strptime(friday_arg, '%Y-%m-%d')
        else:
            today = _dt.utcnow().date()
            # weekday(): Monday=0 ... Sunday=6 → Friday=4
            # If today is before Friday in the week, go back to last Friday
            delta_days = (today.weekday() - 4) % 7
            friday = _dt(today.year, today.month, today.day) - _td(days=delta_days)
        # Build date list Saturday→Friday inclusive
        start = friday - _td(days=6)
        date_list = [(start + _td(days=i)).strftime('%Y-%m-%d') for i in range(7)]

        # Load available daily reports (support both YYYY-MM-DD and YYYY_MM_DD filenames)
        daily_reports = []
        try:
            import re
            files = []
            for fn in os.listdir(dir_path):
                m = re.match(r'^report_cache_(\d{4})[-_](\d{2})[-_](\d{2})\.json$', fn)
                if not m:
                    continue
                y, mo, da = m.groups()
                try:
                    d_obj = _dt(int(y), int(mo), int(da))
                except Exception:
                    continue
                if start.date() <= d_obj.date() <= friday.date():
                    files.append((d_obj.date(), os.path.join(dir_path, fn)))
            # Sort by date ascending
            files.sort(key=lambda t: t[0])
            for _d, fp in files:
                try:
                    with open(fp, 'r', encoding='utf-8') as f:
                        daily_reports.append(json.load(f))
                except Exception as _e:
                    print(f"Failed to read daily cache {fp}: {_e}")
        except Exception as _e:
            print(f"Failed to enumerate daily caches in {dir_path}: {_e}")

        if not daily_reports:
            return jsonify({"error": "No daily caches found for requested week", "week": {"start": start.strftime('%Y-%m-%d'), "friday": friday.strftime('%Y-%m-%d')}}), 404

        # Aggregate per-service
        from collections import defaultdict
        error_count_by_service = defaultdict(int)
        total_submissions_by_service = defaultdict(int)
        program_name_by_service = {}
        skysi_by_service = {}
        # path -> set of msgs (unique by text), also keep (time,msg)
        messages_by_service_and_path = defaultdict(lambda: defaultdict(dict))  # svc->{path->{msg_text: time}}

        for rep in daily_reports:
            items = rep.get('report_items') or []
            svc_rows = rep.get('svc_rows') or []
            # Use svc_rows to capture SKYSI and program name if present
            for r in svc_rows:
                svc = r.get('aem_service') or ''
                if not svc:
                    continue
                program = r.get('program_name')
                if program and svc not in program_name_by_service:
                    program_name_by_service[svc] = program
                skysi_key = r.get('skysi_key')
                skysi_url = r.get('skysi_url')
                if skysi_key and svc not in skysi_by_service:
                    skysi_by_service[svc] = {"skysi_key": skysi_key, "skysi_url": skysi_url}

            for it in items:
                svc = it.get('aem_service') or ''
                if not svc:
                    continue
                error_count_by_service[svc] += int(it.get('error_count') or 0)
                total_submissions_by_service[svc] += int(it.get('total_form_submissions') or 0)
                if svc not in program_name_by_service:
                    pn = it.get('program_name')
                    if pn:
                        program_name_by_service[svc] = pn
                for pe in (it.get('paths') or []):
                    p = pe.get('path') or ''
                    if not p:
                        continue
                    for m in (pe.get('messages') or []):
                        # messages are either string or {time,msg}
                        if isinstance(m, dict):
                            msg_text = (m.get('msg') or '').strip()
                            msg_time = (m.get('time') or '').strip()
                        else:
                            msg_text = str(m).strip()
                            msg_time = ''
                        if not msg_text:
                            continue
                        # store first seen time for this text
                        if msg_text not in messages_by_service_and_path[svc][p]:
                            messages_by_service_and_path[svc][p][msg_text] = msg_time

        # Build weekly structures
        weekly_services = sorted(error_count_by_service.keys(), key=lambda s: error_count_by_service[s], reverse=True)

        weekly_svc_rows = []
        for svc in weekly_services:
            skysi = skysi_by_service.get(svc) or {}
            weekly_svc_rows.append({
                'aem_service': svc,
                'program_name': program_name_by_service.get(svc, '<unknown program name>'),
                'error_count': error_count_by_service[svc],
                'skysi_key': skysi.get('skysi_key', ''),
                'skysi_url': skysi.get('skysi_url', ''),
            })

        weekly_report_items = []
        for svc in weekly_services:
            path_entries = []
            for p, msg_map in messages_by_service_and_path[svc].items():
                # limit to 10 unique messages per path
                limited_msgs = []
                for idx, (txt, tme) in enumerate(msg_map.items()):
                    if idx >= 10:
                        break
                    limited_msgs.append({'time': tme, 'msg': txt} if tme else {'msg': txt})
                # derive up to 3 distinct times for the badge from messages
                times = [m.get('time') for m in limited_msgs if isinstance(m, dict) and m.get('time')]
                times = [t for t in times if t]
                badge_time = ', '.join(times[:10]) if times else ''
                path_entries.append({'path': p, 'time': badge_time, 'messages': limited_msgs})

            total_forms = total_submissions_by_service[svc]
            errs = error_count_by_service[svc]
            failure_pct = round((errs / total_forms) * 100, 2) if total_forms else 0.0
            weekly_report_items.append({
                'aem_service': svc,
                'error_count': errs,
                'total_form_submissions': total_forms,
                'failure_rate_pct': failure_pct,
                'program_name': program_name_by_service.get(svc, '<unknown program name>'),
                'paths': path_entries,
            })

        weekly = {
            'generated_at': _dt.utcnow().isoformat() + 'Z',
            'earliest': start.strftime('%Y-%m-%d 00:00:00'),
            'latest': friday.strftime('%Y-%m-%d 23:59:59'),
            'services': weekly_services,
            'svc_rows': weekly_svc_rows,
            'report_items': weekly_report_items,
            'week': {
                'start': start.strftime('%Y-%m-%d'),
                'friday': friday.strftime('%Y-%m-%d'),
                'dates': date_list,
            }
        }
        return jsonify(weekly)
    except Exception as e:
        print(f"Failed to build weekly report: {e}")
        return jsonify({"error": "Failed to build weekly report"}), 500

@app.route('/report-dashboard-view', methods=['GET'])
def report_dashboard_view():
    """Render dashboard HTML from cached JSON only. Optional ?date=YYYY-MM-DD."""
    cached = None
    date_arg = request.args.get('date', '').strip()
    try:
        dir_path, default_file = _resolve_cache_dir_and_file()
        target_file = default_file
        if date_arg:
            candidate = os.path.join(dir_path, f'report_cache_{date_arg}.json')
            if os.path.exists(candidate):
                target_file = candidate
        else:
            from datetime import datetime as _dt
            today = _dt.utcnow().strftime('%Y-%m-%d')
            today_file = os.path.join(dir_path, f'report_cache_{today}.json')
            if os.path.exists(today_file):
                target_file = today_file
        if os.path.exists(target_file):
            with open(target_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            REPORT_CACHE['data'] = cached
        else:
            cached = REPORT_CACHE.get('data')
    except Exception as e:
        print(f"Failed to read report cache file for dashboard: {e}")
        cached = REPORT_CACHE.get('data')
    if not cached:
        return ("No cached data. Please POST /report-refresh first.", 404, { 'Content-Type': 'text/plain; charset=utf-8' })
    html = render_dashboard_html(cached.get('svc_rows', []), cached.get('report_items', []), cached.get('earliest',''), cached.get('latest',''))
    return (html, 200, { 'Content-Type': 'text/html; charset=utf-8' })

@app.route('/skyops-last7', methods=['GET'])
def skyops_last7():
    """Fetch SKYOPS issues created in the last N days (default 7) filtered by labels and component.

    Query params:
      - days: integer, defaults to 7
    """
    start = (request.args.get('start') or '').strip()  # YYYY-MM-DD
    end = (request.args.get('end') or '').strip()
    fetch_all = (request.args.get('all') or '').strip().lower() in ('1','true','yes')
    try:
        days = int(request.args.get('days', '7'))
    except Exception:
        days = 7
    # Combined JQL: SKYOPS and FORMS (Adaptive Forms components)
    base = (
        '('
        '  ('
        '    project = SKYOPS '
        '    AND labels in ("Adaptive-Forms", "af-submission-errors") '
        '    AND component = "CSME Escalation to Customer"'
        '  ) '
        '  OR '
        '  ('
        '    project = FORMS '
        '    AND component in ("Adaptive Forms - Runtime", "Adaptive Forms - Core Components") '
        '    AND labels = "af-submission-errors"'
        '  )'
        ') '
        'AND status NOT IN (Done, Closed, Resolved) '
    )
    if fetch_all:
        jql = base
    elif start and end:
        # Use DATE-ONLY bounds as requested: yyyy/MM/dd
        def _date_only(s: str) -> str:
            s = (s or '').strip()
            if not s:
                return ''
            s = s[:10]  # YYYY-MM-DD
            return s.replace('-', '/')
        start_q = _date_only(start)
        end_q = _date_only(end)
        jql = base + f'AND created >= "{start_q}" AND created <= "{end_q}"'
    else:
        jql = base + f'AND created >= -{days}d'
    # Limit fields for performance
    result = jira_query_tool(jql, extra_params={
        'fields': 'summary,status,created,assignee',
        'maxResults': 200
    }) or {}
    issues_out = []
    for it in (result.get('issues') or []):
        key = it.get('key')
        fields = it.get('fields') or {}
        issues_out.append({
            'key': key,
            'summary': fields.get('summary', ''),
            'status': (fields.get('status') or {}).get('name', ''),
            'created': fields.get('created', ''),
            'assignee': (fields.get('assignee') or {}).get('displayName', ''),
        })
    # Optional sorting support: sort by status | created | assignee
    sort_by = (request.args.get('sort') or '').strip().lower()
    sort_order = (request.args.get('order') or 'asc').strip().lower()
    reverse = (sort_order == 'desc')
    if sort_by in ('status', 'created', 'assignee'):
        if sort_by == 'status':
            issues_out.sort(key=lambda x: (x.get('status') or '').lower(), reverse=reverse)
        elif sort_by == 'created':
            issues_out.sort(key=lambda x: (x.get('created') or ''), reverse=reverse)
        elif sort_by == 'assignee':
            issues_out.sort(key=lambda x: (x.get('assignee') or '').lower(), reverse=reverse)
    return jsonify({'count': len(issues_out), 'issues': issues_out, 'jql': jql})

@app.route('/csopm-open', methods=['GET'])
def csopm_open():
    """Fetch CSOPM tickets that are open (not closed/done/complete) assigned to specific org members except 'salilt'."""
    jql = (
        'project = CSOPM '
        'AND status in (closed, done, complete) '
        'AND "CSO Severity" not in ("Sev 1", "Sev 2", "Sev 3", "Sev 4") '
        'AND (assignee in (membersOf(ORG-SALILT-ALL), membersOf(ORG-SALILT-ALL-TEMP))) '
        'AND assignee != salilt'
    )
    result = jira_query_tool(jql, extra_params={
        'fields': 'summary,status,created,assignee',
        'maxResults': 200
    }) or {}
    issues_out = []
    for it in (result.get('issues') or []):
        key = it.get('key')
        fields = it.get('fields') or {}
        issues_out.append({
            'key': key,
            'summary': fields.get('summary', ''),
            'status': (fields.get('status') or {}).get('name', ''),
            'created': fields.get('created', ''),
            'assignee': (fields.get('assignee') or {}).get('displayName', ''),
        })
    return jsonify({'count': len(issues_out), 'issues': issues_out, 'jql': jql})

@app.route('/daily-stats-refresh', methods=['POST'])
def daily_stats_refresh():
    """Compute daily submission stats for the past N days and save to JSON in daily-data/daily_stats.json.
    Optional JSON body: {"days": 120}
    """
    try:
        data = request.json or {}
        days = int(data.get('days', 1))
    except Exception:
        days = 120
    # Build date-wise stats using strict 1-day windows to ensure
    # Total, Passed (code<500) and Failed (code>=500) are accurate per day
    from datetime import datetime as _dt, timedelta as _td
    today = _dt.utcnow().date()
    date_list = [ (today - _td(days=i)).strftime('%Y-%m-%d') for i in range(max(1, days)-1, -1, -1) ]
    stats = []
    for d in date_list:
        try:
            stats.append(get_daily_counts_for_date(d))
        except Exception as _e:
            print(f"Failed to compute counts for {d}: {_e}")
    try:
        # Write individual per-day files only
        base_dir = os.path.join(os.path.dirname(__file__), 'submission-count')
        os.makedirs(base_dir, exist_ok=True)
        for item in stats:
            try:
                day = (item.get('day') or '')[:10]
                if not day:
                    continue
                single_payload = {
                    "day": day,
                    "total": int(item.get('total', 0)),
                    "passed": int(item.get('passed', 0)),
                    "failed": int(item.get('failed', 0)),
                }
                # Write only the supported naming style used by the graph aggregator
                fp_counts = os.path.join(base_dir, f'daily_counts_{day}.json')
                with open(fp_counts, 'w', encoding='utf-8') as fpc:
                    json.dump(single_payload, fpc, ensure_ascii=False, indent=2)
            except Exception as _e:
                print(f"Failed to write per-day file: {_e}")
        return jsonify({"status": "ok", "directory": base_dir, "count": len(stats)})
    except Exception as e:
        print(f"Failed to write daily_stats.json: {e}")
        return jsonify({"error": "Failed to write daily stats"}), 500

@app.route('/daily-stats', methods=['GET'])
def daily_stats():
    """Return daily stats JSON if present, else compute ad-hoc for last 60 days."""
    # Prefer new submission-count/daily_counts.json
    new_path = os.path.join(os.path.dirname(__file__), 'submission-count', 'daily_counts.json')
    legacy_path = None
    try:
        dir_path, _default = _resolve_cache_dir_and_file()
        legacy_path = os.path.join(dir_path, 'daily_stats.json')
    except Exception:
        legacy_path = os.path.join(os.path.dirname(__file__), 'daily-data', 'daily_stats.json')
    if os.path.exists(new_path):
        try:
            with open(new_path, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        except Exception:
            pass
    if legacy_path and os.path.exists(legacy_path):
        try:
            with open(legacy_path, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        except Exception:
            pass
    # Fallback: aggregate individual per-day files submission-count/daily_counts_YYYY-MM-DD.json
    try:
        folder = os.path.join(os.path.dirname(__file__), 'submission-count')
        files = []
        if os.path.isdir(folder):
            for fn in os.listdir(folder):
                if fn.startswith('daily_counts_') and fn.endswith('.json'):
                    files.append(os.path.join(folder, fn))
        stats = []
        for fp in files:
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    j = json.load(f)
                day = (j.get('day') or '')[:10]
                total = int(j.get('total', 0))
                passed = int(j.get('passed', 0))
                failed = int(j.get('failed', 0))
                if day:
                    stats.append({'day': day, 'total': total, 'passed': passed, 'failed': failed})
            except Exception:
                continue
        stats.sort(key=lambda x: x['day'])
        if stats:
            return jsonify({"days": len(stats), "stats": stats})
    except Exception as e:
        print(f"Failed to aggregate per-day counts: {e}")
    # fallback compute
    stats = get_daily_submission_stats(days=60)
    return jsonify({"days": 60, "stats": stats})

@app.route('/daily-stats/day', methods=['GET'])
def daily_stats_day():
    """Return counts for a specific day using strict 1-day earliest/latest bounds.
    Query: ?date=YYYY-MM-DD
    """
    date_arg = (request.args.get('date') or '').strip()
    if not date_arg:
        return jsonify({"error": "missing date"}), 400
    try:
        out = get_daily_counts_for_date(date_arg)
        return jsonify(out)
    except Exception as e:
        print(f"Failed to compute daily counts for {date_arg}: {e}")
        return jsonify({"error": "failed to compute"}), 500

class JiraAgent:
    def __init__(self, llm=None, tools=[]):
        self.agent = Agent(
            role="Jira Analyst",
            goal="Fetch Jira ticket and provide its description.",
            backstory="You are an expert at querying Jira.",
            tools=tools,
            llm=llm,
            verbose=True
        )
    def get(self):
        return self.agent

class AEMExtractorAgent:
    def __init__(self, llm=None, tools=[]):
        self.agent = Agent(
            role="AEM Field Extractor",
            goal="Extract AEM fields from Jira description using LLM.",
            backstory="You are an expert at extracting structured fields from unstructured text.",
            tools=tools,
            llm=llm,
            verbose=True
        )
    def get(self):
        return self.agent

class SplunkAgent:
    def __init__(self, llm=None, tools=[]):
        self.agent = Agent(
            role="Splunk Analyst",
            goal="Query Splunk logs using extracted AEM fields.",
            backstory="You are an expert at querying Splunk.",
            tools=tools,
            llm=llm,
            verbose=True
        )
    def get(self):
        return self.agent

class FormsJiraAgent:
    def __init__(self, llm=None, tools=[]):
        self.agent = Agent(
            role="Forms Jira Creator",
            goal="Create a Jira bug in the AEM Forms project with extracted details and Splunk messages as comments.",
            backstory="You are an expert at creating well-structured Jira tickets for AEM Forms issues.",
            tools=tools,
            llm=llm,
            verbose=True
        )
    def get(self):
        return self.agent

def build_splunk_query(aem_fields, date_created, user_earliest=None, user_latest=None):
    aem_service = aem_fields.get("aem_service", "")
    print(f"AEM Service: {aem_service}")
    env_type = aem_fields.get("env_type", "")
    aem_tier = aem_fields.get("aem_tier", "")
    if user_earliest and user_latest:
        # Use the provided MM/DD/YYYY:HH:mm:ss format directly
        earliest = user_earliest
        latest = user_latest
    elif date_created:
        dt = datetime.strptime(date_created[:19], "%Y-%m-%dT%H:%M:%S")
        today = datetime.now().date()
        start_dt = dt - timedelta(days=1)
        if dt.date() == today:
            end_dt = today
        else:
            end_dt = dt + timedelta(days=1)
        earliest = f"{start_dt.strftime('%m/%d/%Y')}:00:00:00"
        latest = f"{end_dt.strftime('%m/%d/%Y')}:23:59:59"
    else:
        earliest = "-1d"
        latest = "now"
    query = f'index=dx_aem_engineering '
    if aem_service and aem_service.lower() != "none":
        query += f'aem_service={aem_service} '
    query += 'level=ERROR '
    query += 'sourcetype=aemerror '
    if env_type and env_type.lower() != "none":
        query += f'aem_envType={env_type} '
    if aem_tier and aem_tier.lower() != "none":
        query += f'aem_tier={aem_tier} '
    query += '(*guideContainer.af.submit.jsp* OR *FormSubmitActionManagerServiceImpl* OR *AdaptiveFormSubmitServlet*) '
    query += f'earliest="{earliest}" latest="{latest}"'
    return query

def generate_summary(program, aem_program_id, splunk_msg, llm):
    prompt = f"""
Write a concise 1-line summary for a Jira bug, prefixed with '[{program}][p{aem_program_id}]'.
Summary should describe the main issue based on this Splunk error message:
{splunk_msg}
"""
    content = llm.call(prompt)
    import re
    match = re.search(r'\[.*?\]\[.*?\].*', content)
    if match:
        return match.group(0)
    return content.strip()

# Helper to check for similar error using LLM
def is_similar_error(new_error, existing_comments, llm):
    prompt = f"""
You are a helpful assistant. Given a new error message and a list of existing Jira comments, determine if the new error message is already present or very similar to any of the comments. If so, respond 'YES'. If not, respond 'NO'.

New error message:
{new_error}

Existing comments:
{chr(10).join(existing_comments)}
"""
    result = llm.call(prompt)
    return "YES" in result.upper()

@app.route('/process', methods=['POST'])
def process():
    data = request.json
    jira_id = data.get("jira_id")
    user_earliest = data.get("earliest")
    user_latest = data.get("latest")
    print(f"Jira ID: {jira_id}")
    if not jira_id:
        return jsonify({"error": "Missing required field: jira_id"}), 400

    # 1. Jira Agent fetches ticket
    jira_agent = JiraAgent(llm=llm).get()
    def fetch_jira():
        return jira_query_tool(f'issue = {jira_id}')
    jira_result = fetch_jira()
    aem_fields = extract_aem_fields_from_description(jira_result["issues"][0]["fields"].get("description", ""), llm) if jira_result.get("issues") else {}
    print(f"AEM Fields: {aem_fields}")
    # Normalize extracted fields to avoid 'None' string or None values
    for key in ["aem_tier", "aem_service", "env_type"]:
        val = aem_fields.get(key, "")
        if val is None or str(val).strip().lower() == "none":
            aem_fields[key] = ""
    # If AEM fields are empty, stop here and return context without proceeding
    if not aem_fields:
        return jsonify({
            "aem_fields": aem_fields,
            "jira_result": jira_result,
            "splunk_result": [],
            "skipped": True,
            "reason": "AEM fields are empty; skipping Splunk analysis."
        }), 200
    # If AEM service is missing, stop as Splunk query depends on it
    if not str(aem_fields.get("aem_service", "")).strip():
        return jsonify({
            "aem_fields": aem_fields,
            "jira_result": jira_result,
            "splunk_result": [],
            "skipped": True,
            "reason": "AEM service is missing; skipping Splunk analysis."
        }), 200
    #print(f"AEM Fields after normalization: {aem_fields}")
    # 2. Splunk Agent queries Splunk
    def run_splunk(aem_fields_and_jira):
        aem_fields, jira_result = aem_fields_and_jira
        issues = jira_result.get("issues", [])
        if issues:
            fields = issues[0]["fields"]
            date_created = fields.get("created", "")
        else:
            date_created = ""
        # Establish a baseline window (for the access-log pass)
        if user_earliest and user_latest:
            baseline_earliest = user_earliest
            baseline_latest = user_latest
        elif date_created:
            dt = datetime.strptime(date_created[:19], "%Y-%m-%dT%H:%M:%S")
            today = datetime.now().date()
            start_dt = dt - timedelta(days=1)
            end_dt = today if dt.date() == today else dt + timedelta(days=1)
            baseline_earliest = f"{start_dt.strftime('%m/%d/%Y')}:00:00:00"
            baseline_latest = f"{end_dt.strftime('%m/%d/%Y')}:23:59:59"
        else:
            baseline_earliest = "-1d"
            baseline_latest = "now"

        # New strategy: use latest top error times and search ±30s windows around each
        times = get_top_error_times(
            aem_fields.get("aem_service", ""),
            aem_fields.get("env_type", ""),
            aem_fields.get("aem_tier", ""),
            earliest=baseline_earliest,
            latest=baseline_latest,
            limit=10
        )
        print(f"Top error times: {times}")

        all_results = []
        def fmt(dt):
            return dt.strftime('%m/%d/%Y:%H:%M:%S')
        def parse_time_str(s: str):
            try:
                return datetime.strptime(s, '%m/%d/%Y:%H:%M:%S')
            except Exception:
                return None
        for t_str in times:
            t = parse_time_str(t_str)
            if not t:
                continue
            e = fmt(t - timedelta(seconds=10))
            l = fmt(t + timedelta(seconds=10))
            query = build_splunk_query(aem_fields, date_created="", user_earliest=e, user_latest=l)
            print(f"Splunk per-time-window query: {query}")
            res = splunk_search_tool(query, llm=llm, use_llm=False)
            if isinstance(res, list):
                seen_msgs_window = set()
                for r in res:
                    r.setdefault("window_center", t_str)
                    msg = (r.get("msg", "") or "").strip()
                    if not msg or msg in seen_msgs_window:
                        continue
                    all_results.append(r)
                    seen_msgs_window.add(msg)
                    if len(seen_msgs_window) >= 4:
                        break

        # Fallback
        if not all_results:
            query = build_splunk_query(aem_fields, date_created, user_earliest, user_latest)
            print(f"Splunk fallback query: {query}")
            return splunk_search_tool(query, llm=llm, use_llm=False)
        return all_results
    splunk_result = run_splunk((aem_fields, jira_result))
    # print(f"Splunk Result: {splunk_result}")
    # For testing: return only Splunk results (skip Forms Jira creation)
    return jsonify({
        "aem_fields": aem_fields,
        "jira_result": jira_result,
        "splunk_result": splunk_result
    }), 200
    # forms_jira_key = get_linked_forms_jira(jira_id)
    # print(f"Forms Jira Key: {forms_jira_key}")
    # if forms_jira_key:
    #     # Check status of linked Forms Jira
    #     forms_status = get_jira_status(forms_jira_key)
    #     #print(f"Forms Jira Status: {forms_status}")
    #     if forms_status.lower() in ["open", "in progress", "new"]:
    #         # Forms Jira is open, in progress, or new, update with unique errors
    #         existing_comments = get_jira_comments(forms_jira_key)
    #         for result in splunk_result:
    #             msg = result.get("msg", "")
    #             time = (
    #                 result.get("orig_time")
    #                 or result.get("_time")
    #                 or result.get("event_time")
    #                 or ""
    #             )
    #             if msg and not is_similar_error(msg, existing_comments, llm):
    #                 add_jira_comment(forms_jira_key, msg, time=time)
    #                 existing_comments.append(msg)
    #     else:
    #         # Forms Jira is not open/in progress/new, create a new one
    #         def create_forms_jira(inputs):
    #             aem_fields, splunk_results = inputs
    #             if not splunk_results or len(splunk_results) == 0:
    #                 return None
    #             program = aem_fields.get("program", "")
    #             aem_program_id = aem_fields.get("aem_program_id", "")
    #             env_type = aem_fields.get("env_type", "")
    #             component = "forms"
    #             cluster = aem_fields.get("cluster", "")
    #             aem_service = aem_fields.get("aem_service", "")
    #             description = f"1. program: {program}\n2. env_type: {env_type}\n3. component: {component}\n4. cluster: {cluster}\n5. aem_service: {aem_service}"
    #             splunk_msg = next((r.get("msg", "") for r in splunk_results if r.get("msg")), "")
    #             summary = generate_summary(program, aem_program_id, splunk_msg, llm)
    #             issue_key = create_jira_issue(
    #                 project="FORMS",
    #                 issue_type="Bug",
    #                 component="Adaptive Forms - Runtime",
    #                 summary=summary,
    #                 description=description
    #             )
    #             existing_comments = []
    #             for result in splunk_results:
    #                 msg = result.get("msg", "")
    #                 time = (
    #                     result.get("orig_time")
    #                     or result.get("_time")
    #                     or result.get("event_time")
    #                     or ""
    #                 )
    #                 if msg and not is_similar_error(msg, existing_comments, llm):
    #                     add_jira_comment(issue_key, msg, time=time)
    #                     existing_comments.append(msg)
    #             return issue_key
    #         forms_jira_key = create_forms_jira((aem_fields, splunk_result))
    #         if forms_jira_key:
    #             link_jira_issues(jira_id, forms_jira_key)
    # else:
    #     # Create new Forms Jira and link
    #     def create_forms_jira(inputs):
    #         aem_fields, splunk_results = inputs
    #         if not splunk_results or len(splunk_results) == 0:
    #             return None
    #         program = aem_fields.get("program", "")
    #         aem_program_id = aem_fields.get("aem_program_id", "")
    #         env_type = aem_fields.get("env_type", "")
    #         component = "forms"
    #         cluster = aem_fields.get("cluster", "")
    #         aem_service = aem_fields.get("aem_service", "")
    #         description = f"1. program: {program}\n2. env_type: {env_type}\n3. component: {component}\n4. cluster: {cluster}\n5. aem_service: {aem_service}"
    #         splunk_msg = next((r.get("msg", "") for r in splunk_results if r.get("msg")), "")
    #         summary = generate_summary(program, aem_program_id, splunk_msg, llm)
    #         issue_key = create_jira_issue(
    #             project="FORMS",
    #             issue_type="Bug",
    #             component="Adaptive Forms - Runtime",
    #             summary=summary,
    #             description=description
    #         )
    #         existing_comments = []
    #         for result in splunk_results:
    #             msg = result.get("msg", "")
    #             time = (
    #                 result.get("orig_time")
    #                 or result.get("_time")
    #                 or result.get("event_time")
    #                 or ""
    #             )
    #             if msg and not is_similar_error(msg, existing_comments, llm):
    #                 add_jira_comment(issue_key, msg, time=time)
    #                 existing_comments.append(msg)
    #         return issue_key
    #     forms_jira_key = create_forms_jira((aem_fields, splunk_result))
    #     if forms_jira_key:
    #         link_jira_issues(jira_id, forms_jira_key)
    # return jsonify({
    #     "aem_fields": aem_fields,
    #     "forms_jira_key": forms_jira_key,
    #     "jira_result": jira_result,
    #     "splunk_result": splunk_result
    # }), 200

@app.route('/find-skysi', methods=['POST'])
def find_skysi():
    data = request.json or {}
    aem_service = data.get('aem_service', '')
    earliest = data.get('earliest')
    latest = data.get('latest')
    if not aem_service:
        return jsonify({"error": "Missing aem_service"}), 400
    result = search_skysi_by_aem_service(aem_service)
    # Log SKYSI ticket id (first match) for quick visibility
    try:
        issues = result.get('issues') or []
        skysi_key = issues[0].get('key') if issues else ''
        if skysi_key:
            print(f"Found SKYSI ticket: {skysi_key}")
        else:
            print("No SKYSI ticket found for given aem_service")
    except Exception:
        print("No SKYSI ticket found for given aem_service")

    # Default date window: last 1 day for quick lookups
    if not earliest:
        earliest = '-1d'
    if not latest:
        latest = 'now'

    # Build per-path multi-window errors using access-derived failure times
    failures_by_path = get_latest_failures_by_path(
        aem_service, 'prod', 'publish', earliest=earliest, latest=latest, per_path_limit=10
    )
    # print(f"Failures by path: {failures_by_path}")
    # Build a single aemerror query with a subsearch that generates OR windows across all failures
    path_details = []
    base_error = (
        f'index=dx_aem_engineering sourcetype=aemerror level=ERROR '
        f'aem_service={aem_service} aem_envType=prod aem_tier=publish '
        '(*guideContainer.af.submit.jsp* OR *FormSubmitActionManagerServiceImpl* OR *AdaptiveFormSubmitServlet*) '
        f'earliest="{earliest}" latest="{latest}" '
    )
    sub = (
        '[ search index=dx_aem_engineering sourcetype=aemaccess '
        f'aem_service={aem_service} aem_envType=prod aem_tier=publish '
        '(path="/adobe/forms/af/submit*" OR path="*guideContainer.af.submit.jsp") code>=500 '
        f'earliest="{earliest}" latest="{latest}" '
        '| sort 0 - _time '
        '| streamstats count as failCount by path '
        '| where failCount <= 10 '
        '| eval f_start=_time, f_end=_time+10 '
        '| eval query="(_time>=" . f_start . " AND _time<=" . f_end . ")" '
        '| stats values(query) as queries '
        '| eval search="(" . mvjoin(queries," OR ") . ")" '
        '| fields search ] '
    )
    final_query = base_error + sub + '| eval EventTimeFmt=strftime(_time,"%Y-%m-%d %H:%M:%S") | table EventTimeFmt msg'
    # print(f"Combined multi-window query: {final_query}")
    rows = splunk_search_rows(final_query) or []

    # print(f"Rows: {rows}")

    # Build time windows per path for mapping: [start, end] (10s)
    from datetime import datetime as _dt
    windows = []
    for p, times in failures_by_path.items():
        for tstr in times:
            try:
                start_dt = _dt.strptime(tstr, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            end_dt = start_dt + timedelta(seconds=10)
            windows.append((p, start_dt, end_dt))

    # Map error rows to paths via EventTimeFmt ∈ [start, end]
    path_to_msgs, path_to_seen = {}, {}
    for p in failures_by_path.keys():
        path_to_msgs[p] = []
        path_to_seen[p] = set()

    for r in rows:
        et = r.get('EventTimeFmt') or ''
        msg = (r.get('msg') or '').strip()
        if not et or not msg:
            continue
        try:
            evt_dt = _dt.strptime(et.split('.')[0], "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        matched = None
        for p, sdt, edt in windows:
            if sdt <= evt_dt <= edt:
                matched = p
                break
        if matched and msg not in path_to_seen[matched]:
            if len(path_to_msgs[matched]) < 10:
                path_to_msgs[matched].append(msg)
                path_to_seen[matched].add(msg)

    for p, times in failures_by_path.items():
        path_details.append({'path': p, 'times': times, 'messages': path_to_msgs.get(p, [])})


    # print(f"Path details: {path_details}")

    return jsonify({
        'skysi': result,
        'aem_service': aem_service,
        'earliest': earliest,
        'latest': latest,
        'paths': path_details
    }), 200

@app.route('/report', methods=['POST'])
def report():
    data = request.json or {}
    earliest = data.get('earliest')
    latest = data.get('latest')
    services = data.get('aem_services')  # optional explicit list

    # Default to last 1 day when not provided
    if not earliest:
        earliest = '-1d'
    if not latest:
        latest = 'now'

    # 1) Get top services and error counts
    svc_rows = list_services_with_errors(earliest, latest)
    counts_map = {r['aem_service']: r.get('error_count', 0) for r in svc_rows}
    # Map of aem_service -> program_name for later title enrichment
    program_map = {r['aem_service']: r.get('program_name', '<unknown program name>') for r in svc_rows}
    # Enrich with SKYSI ticket keys per TenantID
    jira_base = os.getenv('JIRA_URL', 'https://jira.corp.adobe.com')
    for r in svc_rows:
        aem_service_val = r.get('aem_service', '')
        skysi_key = ''
        try:
            lookup = search_skysi_by_aem_service(aem_service_val) if aem_service_val else {}
            issues = lookup.get('issues') or []
            if issues:
                skysi_key = issues[0].get('key', '')
        except Exception:
            skysi_key = ''
        r['skysi_key'] = skysi_key
        if skysi_key:
            r['skysi_url'] = f"{jira_base}/browse/{skysi_key}"
        else:
            r['skysi_url'] = ''
    if not services:
        services = [r['aem_service'] for r in svc_rows]

    # 2) For each service, collect failing paths and errors using the same combined subsearch + time-window mapping as /find-skysi
    report_items = []
    for aem_service in services:
        failures_by_path = get_latest_failures_by_path(aem_service, "prod", "publish", earliest=earliest, latest=latest, per_path_limit=10)
        # print(f"Failures by path for {aem_service}: {failures_by_path}")

        # Single aemerror query with subsearch-generated OR windows across all failures
        base_error = (
            f'index=dx_aem_engineering sourcetype=aemerror level=ERROR '
            f'aem_service={aem_service} aem_envType=prod aem_tier=publish '
            '(*guideContainer.af.submit.jsp* OR *FormSubmitActionManagerServiceImpl* OR *AdaptiveFormSubmitServlet*) '
            f'earliest="{earliest}" latest="{latest}" '
        )
        sub = (
            '[ search index=dx_aem_engineering sourcetype=aemaccess '
            f'aem_service={aem_service} aem_envType=prod aem_tier=publish '
            '(path="/adobe/forms/af/submit*" OR path="*guideContainer.af.submit.jsp") code>=500 '
            f'earliest="{earliest}" latest="{latest}" '
            '| sort 0 - _time '
            '| streamstats count as failCount by path '
            '| where failCount <= 10 '
            '| eval f_start=_time, f_end=_time+10 '
            '| eval query="(_time>=" . f_start . " AND _time<=" . f_end . ")" '
            '| stats values(query) as queries '
            '| eval search="(" . mvjoin(queries," OR ") . ")" '
            '| fields search ] '
        )
        final_query = base_error + sub + '| eval EventTimeFmt=strftime(_time,"%Y-%m-%d %H:%M:%S") | table EventTimeFmt msg'
        # print(f"Combined multi-window query (report) for {aem_service}: {final_query}")
        rows = splunk_search_rows(final_query) or []

        # Map rows back to paths via EventTimeFmt within [FailureTime, FailureTime+10s]
        from datetime import datetime as _dt
        windows = []
        for p, times in failures_by_path.items():
            for tstr in times:
                try:
                    sdt = _dt.strptime(tstr, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                edt = sdt + timedelta(seconds=10)
                windows.append((p, sdt, edt))

        path_to_msgs = {p: [] for p in failures_by_path.keys()}
        path_to_seen = {p: set() for p in failures_by_path.keys()}
        for r in rows:
            et = (r.get('EventTimeFmt') or '').split('.')[0]
            msg = (r.get('msg') or '').strip()
            if not et or not msg:
                continue
            try:
                evt_dt = _dt.strptime(et, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            matched = None
            for p, sdt, edt in windows:
                if sdt <= evt_dt <= edt:
                    matched = p
                    break
            if matched and msg not in path_to_seen[matched] and len(path_to_msgs[matched]) < 10:
                path_to_msgs[matched].append(msg)
                path_to_seen[matched].add(msg)

        path_entries = []
        for p, times in failures_by_path.items():
            path_entries.append({
                "path": p,
                "time": ", ".join(times[:3]),
                "messages": path_to_msgs.get(p, [])
            })

        report_items.append({
            "aem_service": aem_service,
            "error_count": counts_map.get(aem_service, 0),
            "program_name": program_map.get(aem_service, '<unknown program name>'),
            "paths": path_entries
        })

    # 3) Build a formatted PDF (H1/H2/H3, spacing, wrapped stack traces)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    h3 = styles["Heading3"]
    body = styles["BodyText"]
    # Slightly adjust sizes
    h1.fontSize = 18; h1.leading = 22; h1.textColor = colors.HexColor('#0D47A1')
    h2.fontSize = 14; h2.leading = 18; h2.textColor = colors.HexColor('#1565C0')
    h3.fontSize = 12; h3.leading = 16; h3.textColor = colors.HexColor('#1976D2')
    code_style = ParagraphStyle(
        name="Code",
        parent=body,
        fontName="Courier",
        fontSize=8,
        leading=10,
        textColor=colors.black,
    )
    # Paragraph-based code style that wraps long tokens and supports splitting across pages
    code_para_style = ParagraphStyle(
        name="CodePara",
        parent=body,
        fontName="Courier",
        fontSize=7,
        leading=8,
        textColor=colors.black,
        wordWrap='CJK',
        allowWidows=1,
        allowOrphans=1,
        splitLongWords=True,
    )
    msg_title_style = ParagraphStyle(
        name='MsgTitle',
        parent=body,
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#37474F'),
    )

    def header_footer(canv, _doc):
        canv.saveState()
        # Header band
        canv.setFillColor(colors.HexColor('#E3F2FD'))
        canv.rect(0, A4[1]-20, A4[0], 20, stroke=0, fill=1)
        canv.setFillColor(colors.HexColor('#0D47A1'))
        canv.setFont("Helvetica-Bold", 10)
        canv.drawString(36, A4[1]-14, "Daily Forms Submit Errors Report")
        # Footer
        canv.setFillColor(colors.HexColor('#90A4AE'))
        canv.setFont("Helvetica", 8)
        canv.drawRightString(A4[0]-36, 14, f"Page {_doc.page}")
        canv.restoreState()

    def path_badge(path_text: str) -> Table:
        p = Paragraph(path_text, ParagraphStyle(
            name="PathBadge",
            parent=h3,
            textColor=colors.white,
        ))
        t = Table([[p]], colWidths=[A4[0]-72])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#1976D2')),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('ROUNDEDCORNERS', (0,0), (-1,-1), 4),
        ]))
        return t

    def code_block_wrapped(msg: str) -> Table:
        # Escape XML entities for Paragraph
        try:
            from xml.sax.saxutils import escape as _xml_escape
            safe = _xml_escape(msg)
        except Exception:
            safe = msg.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        # Split into lines and create one row per line so the table can paginate across pages
        lines = safe.split('\n')
        rows = []
        for line in lines:
            # Ensure super-long tokens can wrap by inserting zero-width space hints every ~100 chars when no spaces
            if len(line) > 120 and (' ' not in line):
                chunks = [line[i:i+100] for i in range(0, len(line), 100)]
                line = '\u200b'.join(chunks)
            rows.append([Paragraph(line or ' ', code_para_style)])

        t = Table(rows or [[Paragraph(' ', code_para_style)]], colWidths=[A4[0]-72])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#ECEFF1')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#B0BEC5')),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        return t

    story = []
    story.append(Paragraph("Daily Forms Submit Errors Report", h1))
    story.append(Paragraph(f"Range: {earliest or '<auto>'} -> {latest or '<auto>'}", ParagraphStyle(name='sub', parent=body, textColor=colors.HexColor('#455A64'))))
    story.append(Spacer(1, 10))

    # Summary table at top: TenantID, ProgramName, ErrorCount, SKYSI
    if svc_rows:
        header_style = ParagraphStyle(name='tblhdr', parent=body, textColor=colors.white, fontName='Helvetica-Bold')
        cell_style = ParagraphStyle(name='tblcell', parent=body, textColor=colors.black)
        data_rows = [[
            Paragraph('TenantID', header_style),
            Paragraph('ProgramName', header_style),
            Paragraph('ErrorCount', header_style),
            Paragraph('SKYSI', header_style)
        ]]
        for r in svc_rows:
            skysi_key = r.get('skysi_key') or ''
            skysi_url = r.get('skysi_url') or ''
            if skysi_key and skysi_url:
                skysi_cell = Paragraph(f'<link href="{skysi_url}">{skysi_key}</link>', cell_style)
            else:
                skysi_cell = Paragraph('-', cell_style)
            data_rows.append([
                Paragraph(r.get('aem_service',''), cell_style),
                Paragraph(r.get('program_name','<unknown program name>'), cell_style),
                Paragraph(str(r.get('error_count', 0)), cell_style),
                skysi_cell
            ])
        col_widths = [150, A4[0]-72-150-80-90, 80, 90]
        tbl = Table(data_rows, colWidths=col_widths)
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1565C0')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (2,1), (2,-1), 'RIGHT'),
            ('ALIGN', (3,1), (3,-1), 'LEFT'),
            ('GRID', (0,0), (-1,-1), 0.25, colors.HexColor('#B0BEC5')),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        # Zebra striping for readability
        for i in range(1, len(data_rows)):
            if i % 2 == 0:
                tbl.setStyle(TableStyle([
                    ('BACKGROUND', (0,i), (-1,i), colors.HexColor('#ECEFF1')),
                ]))
        story.append(tbl)
        story.append(Spacer(1, 12))

    for item in report_items:
        svc_title = (
            f"Service: {item['aem_service']} "
            f"Program Name: {item.get('program_name', '<unknown program name>')} "
            f"(Failures: {item.get('error_count', 0)})"
        )
        story.append(Paragraph(svc_title, h2))
        story.append(Spacer(1, 6))
        for pe in item['paths'][:10]:
            story.append(path_badge(f"Path: {pe['path']}"))
            story.append(Spacer(1, 6))
            if pe['time']:
                story.append(Paragraph(f"Time: {pe['time']}", ParagraphStyle(name='time', parent=body, textColor=colors.HexColor('#546E7A'))))
                story.append(Spacer(1, 6))
            if not pe['messages']:
                story.append(Paragraph("<no messages>", ParagraphStyle(name='nomsg', parent=body, textColor=colors.HexColor('#B71C1C'))))
                story.append(Spacer(1, 10))
                continue
            for mi, m in enumerate(pe['messages'], start=1):
                # Message heading
                story.append(Paragraph(f"Message {mi}", msg_title_style))
                story.append(Spacer(1, 4))
                # limit to first 20 lines for readability
                _lines = (m or '').split('\n')
                if len(_lines) > 20:
                    m_trunc = '\n'.join(_lines[:20]) + '\n...'
                else:
                    m_trunc = m
                story.append(code_block_wrapped(m_trunc))
                story.append(Spacer(1, 12))
        story.append(Spacer(1, 12))

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    pdf = buf.getvalue()
    buf.close()
    return (pdf, 200, {
        'Content-Type': 'application/pdf',
        'Content-Disposition': 'attachment; filename="daily-forms-errors.pdf"'
    })

@app.route('/report-dashboard', methods=['POST'])
def report_dashboard():
    """HTML dashboard version of /report. Does not modify /report."""
    data = request.json or {}
    earliest = data.get('earliest') or '-1d'
    latest = data.get('latest') or 'now'
    services = data.get('aem_services')  # optional

    # 1) Get top services and error counts
    svc_rows = list_services_with_errors(earliest, latest)
    counts_map = {r['aem_service']: r.get('error_count', 0) for r in svc_rows}
    program_map = {r['aem_service']: r.get('program_name', '<unknown program name>') for r in svc_rows}
    jira_base = os.getenv('JIRA_URL', 'https://jira.corp.adobe.com')
    for r in svc_rows:
        aem_service_val = r.get('aem_service', '')
        skysi_key = ''
        try:
            lookup = search_skysi_by_aem_service(aem_service_val) if aem_service_val else {}
            issues = lookup.get('issues') or []
            if issues:
                skysi_key = issues[0].get('key', '')
        except Exception:
            skysi_key = ''
        r['skysi_key'] = skysi_key
        r['skysi_url'] = f"{jira_base}/browse/{skysi_key}" if skysi_key else ''
    if not services:
        services = [r['aem_service'] for r in svc_rows]

    # 2) Build per-service details (reuse /report logic)
    report_items = []
    for aem_service in services:
        failures_by_path = get_latest_failures_by_path(aem_service, "prod", "publish", earliest=earliest, latest=latest, per_path_limit=10)
        base_error = (
            f'index=dx_aem_engineering sourcetype=aemerror level=ERROR '
            f'aem_service={aem_service} aem_envType=prod aem_tier=publish '
            '(*guideContainer.af.submit.jsp* OR *FormSubmitActionManagerServiceImpl* OR *AdaptiveFormSubmitServlet*) '
            f'earliest="{earliest}" latest="{latest}" '
        )
        sub = (
            '[ search index=dx_aem_engineering sourcetype=aemaccess '
            f'aem_service={aem_service} aem_envType=prod aem_tier=publish '
            '(path="/adobe/forms/af/submit*" OR path="*guideContainer.af.submit.jsp") code>=500 '
            f'earliest="{earliest}" latest="{latest}" '
            '| sort 0 - _time '
            '| streamstats count as failCount by path '
            '| where failCount <= 10 '
            '| eval f_start=_time, f_end=_time+10 '
            '| eval query="(_time>=" . f_start . " AND _time<=" . f_end . ")" '
            '| stats values(query) as queries '
            '| eval search="(" . mvjoin(queries," OR ") . ")" '
            '| fields search ] '
        )
        final_query = base_error + sub + '| eval EventTimeFmt=strftime(_time,"%Y-%m-%d %H:%M:%S") | table EventTimeFmt msg'
        rows = splunk_search_rows(final_query) or []

        from datetime import datetime as _dt
        windows = []
        for p, times in failures_by_path.items():
            for tstr in times:
                try:
                    sdt = _dt.strptime(tstr, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                edt = sdt + timedelta(seconds=10)
                windows.append((p, sdt, edt))

        path_to_msgs = {p: [] for p in failures_by_path.keys()}
        path_to_seen = {p: set() for p in failures_by_path.keys()}
        for r in rows:
            et = (r.get('EventTimeFmt') or '').split('.')[0]
            msg = (r.get('msg') or '').strip()
            if not et or not msg:
                continue
            try:
                evt_dt = _dt.strptime(et, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            matched = None
            for p, sdt, edt in windows:
                if sdt <= evt_dt <= edt:
                    matched = p
                    break
            if matched and msg not in path_to_seen[matched] and len(path_to_msgs[matched]) < 10:
                path_to_msgs[matched].append(msg)
                path_to_seen[matched].add(msg)

        path_entries = []
        for p, times in failures_by_path.items():
            path_entries.append({
                "path": p,
                "time": ", ".join(times[:3]),
                "messages": path_to_msgs.get(p, [])
            })

        report_items.append({
            "aem_service": aem_service,
            "error_count": counts_map.get(aem_service, 0),
            "program_name": program_map.get(aem_service, '<unknown program name>'),
            "paths": path_entries
        })

    # 3) Render HTML
    from html import escape as html_escape
    def trunc15(msg: str) -> str:
        _lines = (msg or '').split('\n')
        return ('\n'.join(_lines[:15]) + '\n...') if len(_lines) > 15 else msg

    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; margin: 24px; }
    h1 { color: #0D47A1; }
    h2 { color: #1565C0; margin-top: 24px; }
    .summary { border-collapse: collapse; width: 100%; margin: 12px 0; }
    .summary th { background:#1565C0; color:#fff; padding:6px; text-align:left; }
    .summary td { border:1px solid #B0BEC5; padding:6px; }
    .path-badge { background:#1976D2; color:#fff; padding:4px 6px; border-radius:4px; display:inline-block; }
    .time { color:#546E7A; margin:6px 0; }
    .msg-title { color:#37474F; font-weight:600; margin:8px 0 4px; }
    pre.msg { background:#ECEFF1; border:1px solid #B0BEC5; padding:4px; white-space:pre-wrap; word-break:break-word; }
    """

    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Daily Forms Submit Errors Dashboard</title>",
        f"<style>{css}</style></head><body>",
        "<h1>Daily Forms Submit Errors Dashboard</h1>",
        f"<div>Range: {html_escape(earliest)} → {html_escape(latest)}</div>",
    ]

    # Summary table
    if svc_rows:
        parts.append("<table class='summary'>")
        parts.append("<tr><th>TenantID</th><th>ProgramName</th><th>ErrorCount</th><th>SKYSI</th></tr>")
        for r in svc_rows:
            skysi = r.get('skysi_key')
            skysi_url = r.get('skysi_url')
            skysi_html = f"<a href='{html_escape(skysi_url)}'>{html_escape(skysi)}</a>" if skysi and skysi_url else "-"
            parts.append(
                "<tr>"
                f"<td>{html_escape(r.get('aem_service',''))}</td>"
                f"<td>{html_escape(r.get('program_name','<unknown program name>'))}</td>"
                f"<td>{int(r.get('error_count',0))}</td>"
                f"<td>{skysi_html}</td>"
                "</tr>"
            )
        parts.append("</table>")

    # Per-service sections
    for item in report_items:
        svc_title = (
            f"Service: {item['aem_service']} "
            f"Program Name: {item.get('program_name','<unknown program name>')} "
            f"(Failures: {item.get('error_count', 0)})"
        )
        parts.append(f"<h2>{html_escape(svc_title)}</h2>")
        for pe in item['paths'][:10]:
            parts.append(f"<div class='path-badge'>Path: {html_escape(pe['path'])}</div>")
            if pe.get('time'):
                parts.append(f"<div class='time'>Time: {html_escape(pe['time'])}</div>")
            msgs = pe.get('messages') or []
            if not msgs:
                parts.append("<div style='color:#B71C1C'>&lt;no messages&gt;</div>")
                continue
            for idx, m in enumerate(msgs, start=1):
                parts.append(f"<div class='msg-title'>Message {idx}</div>")
                parts.append(f"<pre class='msg'>{html_escape(trunc15(m))}</pre>")

    parts.append("</body></html>")
    html = ''.join(parts)
    return (html, 200, { 'Content-Type': 'text/html; charset=utf-8' })

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8000)