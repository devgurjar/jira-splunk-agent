import os
import sys
from dotenv import load_dotenv
from jira_tool import jira_query_tool

# Load environment variables from .env file
load_dotenv()

def main():
    jira_key = sys.argv[1] if len(sys.argv) > 1 else 'SKYSI-62786'
    jql = f'issue = {jira_key}'
    print(f"Querying Jira for: {jira_key}")
    result = jira_query_tool(jql)
    if not isinstance(result, dict):
        print("Unexpected result type from jira_query_tool.")
        print(result)
        return
    if 'error' in result:
        print("Jira API error:")
        print(result['error'])
        return
    issues = result.get('issues', [])
    if not issues:
        print("No issues found. Full response:")
        print(result)
        return
    issue = issues[0]
    key = issue.get('key')
    fields = issue.get('fields', {})
    summary = fields.get('summary')
    description = fields.get('description')
    print(f"Fetched: {key}")
    print(f"Summary: {summary}")
    print("Description:\n")
    print(description or "<no description>")

if __name__ == "__main__":
    main()