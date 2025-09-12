import os
from dotenv import load_dotenv
from crewai import LLM
from jira_tool import jira_query_tool
from aem_extractor_tool import extract_aem_fields_from_description
from splunk_tool import splunk_search_tool

load_dotenv()

llm = LLM(
    model="azure/gpt-4.1",
)

jql = 'issue = SKYSI-62786'  # Replace with a real Jira ID if needed
jira_result = jira_query_tool(jql)
print("Jira Agent Result:", jira_result)

# Extract description and creation date
issues = jira_result.get("issues", [])
if issues:
    fields = issues[0]["fields"]
    description = fields.get("description", "")
    date_created = fields.get("created", "")
    print("Jira Issue Creation Date:", date_created)
else:
    description = ""
    date_created = ""

if not description:
    print("No description found in Jira issue.")
else:
    aem_fields = extract_aem_fields_from_description(description, llm)
    print("Extracted AEM fields:", aem_fields)
    # Build Splunk query
    aem_service = aem_fields.get("aem_service", "")
    env_type = aem_fields.get("env_type", "")
    aem_tier = aem_fields.get("aem_tier", "")
    from datetime import datetime
    if date_created:
        # Parse Jira date and format for Splunk
        dt = datetime.strptime(date_created[:19], "%Y-%m-%dT%H:%M:%S")
        splunk_day = dt.strftime("%m/%d/%Y")
        earliest = f"{splunk_day}:00:00:00"
        latest = f"{splunk_day}:23:59:59"
    else:
        earliest = "-1d"
        latest = "now"
    splunk_query = (
        f'index=dx_aem_engineering '
        f'aem_service={aem_service} '
        f'level=ERROR '
        f'sourcetype=aemerror '
        f'aem_envType={env_type} '
        f'aem_tier={aem_tier} '
        f'*guideContainer.af.submit.jsp* '
        f'earliest="{earliest}" latest="{latest}"'
    )
    print("Splunk Query:", splunk_query)
    splunk_result = splunk_search_tool(splunk_query)
    print("Splunk Agent Result:", splunk_result) 