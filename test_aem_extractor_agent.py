import os
from dotenv import load_dotenv
from crewai import LLM
from aem_extractor_tool import extract_aem_fields_from_description

# Load environment variables
load_dotenv()

llm = LLM(
    model="azure/gpt-4.1",
)

# Sample Jira description (replace with your real example if needed)
jira_description = """
sky use ethos20-prod-va7 ns-team-aem-cm-prd-n49252 cm-p55671-e392469
Publish deployment ns-team-aem-cm-prd-n49252/cm-p55671-e392469 has exceeded the allowed response error SLO burn rate over both the last 1 hour and the last 5 minutes (error ratio > 1.44%). Error ratio over the last 1 hour is 7.608%.
"""

fields = extract_aem_fields_from_description(jira_description, llm)
print("AEM Extractor Agent Result:", fields) 