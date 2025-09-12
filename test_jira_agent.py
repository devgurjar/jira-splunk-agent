import os
from dotenv import load_dotenv
from jira_tool import jira_query_tool, create_jira_issue, add_jira_comment

load_dotenv()

# Test create_jira_issue
summary = "[UPS Unified Site][p55671] Test bug from API"
description = "1. program: UPS Unified Site\n2. env_type: prod\n3. component: forms\n4. cluster: ethos20-prod-va7\n5. aem_service: cm-p55671-e392469"
issue_key = create_jira_issue(
    project="FORMS",
    issue_type="Bug",
    component="Adaptive Forms - Runtime",
    summary=summary,
    description=description
)
print("Created Jira Issue Key:", issue_key)

# Test add_jira_comment
if issue_key:
    comment = "This is a test comment added by the API."
    success = add_jira_comment(issue_key, comment)
    print(f"Comment added: {success}")

jql = 'issue = SKYSI-62786'  # Replace with a real Jira ID if needed
result = jira_query_tool(jql)
print("Jira Agent Result:", result) 