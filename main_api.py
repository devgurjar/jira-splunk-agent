import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from crewai import LLM, Agent, Task, Crew
from jira_tool import jira_query_tool, create_jira_issue, add_jira_comment, link_jira_issues, get_linked_forms_jira, get_jira_comments, get_jira_status, search_skysi_by_aem_service
from aem_extractor_tool import extract_aem_fields_from_description
from splunk_tool import splunk_search_tool, get_last_error_paths
from datetime import datetime, timedelta
from flask_cors import CORS

load_dotenv()

llm = LLM(
    model="azure/gpt-4.1",
)

app = Flask(__name__)
CORS(app)

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

        # 1) First, fetch unique paths and their last error times from aemaccess
        paths = get_last_error_paths(
            aem_fields.get("aem_service", ""),
            aem_fields.get("env_type", ""),
            aem_fields.get("aem_tier", ""),
            earliest=baseline_earliest,
            latest=baseline_latest
        )
        print(f"Access paths: {paths}")

        # 2) For each path, search error logs in ±1 minute window and collect unique messages per path (max 4 per path)
        all_results = []
        def fmt(dt):
            return dt.strftime('%m/%d/%Y:%H:%M:%S')
        for p in paths:
            t_str = (p.get("LastErrorTime") or "").replace(" UTC", "")
            if not t_str:
                continue
            try:
                t = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            e = fmt(t - timedelta(seconds=30))
            l = fmt(t + timedelta(seconds=30))
            query = build_splunk_query(aem_fields, date_created="", user_earliest=e, user_latest=l)
            print(f"Splunk per-path query: {query}")
            res = splunk_search_tool(query, llm=llm)
            if isinstance(res, list):
                seen_msgs_path = set()
                added_for_path = 0
                for r in res:
                    r.setdefault("path", p.get("path"))
                    msg = (r.get("msg", "") or "").strip()
                    if not msg:
                        continue
                    if msg in seen_msgs_path:
                        continue
                    all_results.append(r)
                    seen_msgs_path.add(msg)
                    added_for_path += 1
                    if added_for_path >= 4:
                        break

        # Fallback: if access pass returned nothing, use the original broader query
        if not all_results:
            query = build_splunk_query(aem_fields, date_created, user_earliest, user_latest)
            print(f"Splunk fallback query: {query}")
            return splunk_search_tool(query, llm=llm)
        return all_results
    splunk_result = run_splunk((aem_fields, jira_result))
    print(f"Splunk Result: {splunk_result}")
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
    if not aem_service:
        return jsonify({"error": "Missing aem_service"}), 400
    result = search_skysi_by_aem_service(aem_service)
    return jsonify(result), 200

if __name__ == "__main__":
    app.run(debug=True, port=8000) 