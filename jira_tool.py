import os
import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_URL = os.getenv("JIRA_URL")
JIRA_USER = os.getenv("JIRA_USER")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_BEARER_TOKEN = os.getenv("JIRA_BEARER_TOKEN")

def jira_query_tool(query: str) -> dict:
    jira_url = os.getenv("JIRA_URL")
    jira_user = os.getenv("JIRA_USER")
    jira_token = os.getenv("JIRA_API_TOKEN")
    if not jira_url:
        return {"error": "Jira URL not set in environment variables."}
    url = f"{jira_url}/rest/api/2/search"
    params = {"jql": query}
    headers = {"Accept": "application/json"}
    auth = None
    # Prefer Bearer token if present
    if JIRA_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {JIRA_BEARER_TOKEN}"
    else:
        if not all([jira_user, jira_token]):
            return {"error": "Jira credentials not set. Provide JIRA_BEARER_TOKEN or JIRA_USER + JIRA_API_TOKEN."}
        auth = (jira_user, jira_token)
    try:
        response = requests.get(url, headers=headers, params=params, auth=auth, verify=False)
        if response.status_code == 200:
            return response.json()
        return {"error": f"Failed to fetch Jira issues: {response.text}", "status": response.status_code}
    except Exception as e:
        return {"error": f"Error querying Jira: {e}"}

def create_jira_issue(project, issue_type, component, summary, description):
    url = f"{JIRA_URL}/rest/api/2/issue"
    auth = (JIRA_USER, JIRA_API_TOKEN)
    headers = {"Content-Type": "application/json"}
    data = {
        "fields": {
            "project": {"key": project},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
            "components": [{"name": component}],
            "customfield_25700": {"value": "Internal Customer"},  # Type of Problem
            "customfield_27200": {"value": "No"},  # Localization Required
            "labels": ["csme_requested"]
        }
    }
    response = requests.post(url, json=data, auth=auth, headers=headers, verify=False)
    if response.status_code == 201:
        return response.json().get("key")
    else:
        print(f"Failed to create Jira issue: {response.status_code} {response.text}")
        return None

def add_jira_comment(issue_key, comment, time=None):
    url = f"{JIRA_URL}/rest/api/2/issue/{issue_key}/comment"
    auth = (JIRA_USER, JIRA_API_TOKEN)
    headers = {"Content-Type": "application/json"}
    # Format the comment
    body = "Form submission is failing with following reason\n\n"
    if time:
        body += f"{time}\n"
    body += f"{{code}}\n{comment}\n{{code}}"
    data = {"body": body}
    response = requests.post(url, json=data, auth=auth, headers=headers, verify=False)
    if response.status_code == 201:
        return True
    else:
        print(f"Failed to add comment to {issue_key}: {response.status_code} {response.text}")
        return False

def link_jira_issues(blocker_key, blocked_key):
    """
    Create a 'blocks' link from blocker_key (SKYSI) to blocked_key (Forms Jira).
    This means: blocker_key blocks blocked_key.
    """
    url = f"{JIRA_URL}/rest/api/2/issueLink"
    auth = (JIRA_USER, JIRA_API_TOKEN)
    headers = {"Content-Type": "application/json"}
    data = {
        "type": {"name": "Blocks"},
        "inwardIssue": {"key": blocked_key},
        "outwardIssue": {"key": blocker_key},
        "comment": {"body": f"Linked automatically: {blocker_key} blocks {blocked_key}"}
    }
    response = requests.post(url, json=data, auth=auth, headers=headers, verify=False)
    if response.status_code in (200, 201):
        return True
    else:
        print(f"Failed to link {blocker_key} blocks {blocked_key}: {response.status_code} {response.text}")
        return False

def get_linked_forms_jira(skysi_key):
    url = f"{JIRA_URL}/rest/api/2/issue/{skysi_key}"
    auth = (JIRA_USER, JIRA_API_TOKEN)
    headers = {"Accept": "application/json"}
    response = requests.get(url, auth=auth, headers=headers, verify=False)
    if response.status_code == 200:
        issue = response.json()
        for link in issue.get("fields", {}).get("issuelinks", []):
            #print(f"Link: {link}")
            # Check if this issue blocks another (outwardIssue) and is a FORMS ticket
            if link.get("type", {}).get("name") == "Blocks" and "inwardIssue" in link:
                forms_key = link["inwardIssue"]["key"]
                if forms_key.startswith("FORMS-"):
                    return forms_key
    return None

def get_jira_comments(issue_key):
    url = f"{JIRA_URL}/rest/api/2/issue/{issue_key}/comment"
    auth = (JIRA_USER, JIRA_API_TOKEN)
    headers = {"Accept": "application/json"}
    response = requests.get(url, auth=auth, headers=headers, verify=False)
    if response.status_code == 200:
        return [c["body"] for c in response.json().get("comments", [])]
    else:
        print(f"Failed to fetch comments for {issue_key}: {response.status_code} {response.text}")
        return []

def get_jira_status(issue_key):
    url = f"{JIRA_URL}/rest/api/2/issue/{issue_key}"
    auth = (JIRA_USER, JIRA_API_TOKEN)
    headers = {"Accept": "application/json"}
    response = requests.get(url, auth=auth, headers=headers, verify=False)
    if response.status_code == 200:
        issue = response.json()
        return issue.get("fields", {}).get("status", {}).get("name", "")
    else:
        print(f"Failed to fetch status for {issue_key}: {response.status_code} {response.text}")
        return "" 

def search_skysi_by_aem_service(aem_service: str) -> dict:
    """Search SKYSI issues by aem_service, restricted to open/new/in progress and FormSubmitErrors."""
    if not aem_service:
        return {"issues": []}
    # JQL: project = SKYSI AND summary ~ FormSubmitErrors AND status in (Open, "In Progress", New) AND text ~ aem_service
    jql = (
        'project = SKYSI AND issuetype = Incident AND Alert  ~ "FormSubmitErrors" AND '
        'status NOT IN (Resolved) AND '
        f'text ~ "{aem_service}"'
    )
    return jira_query_tool(jql)