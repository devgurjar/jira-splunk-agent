from crewai import Agent, Task, Crew
from jira_tool import jira_query_tool
from splunk_tool import splunk_search_tool
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- AGENTS ---
jira_agent = Agent(
    role="Jira Analyst",
    goal="Fetch SKYSI Jira tickets and create SKYOPS tickets",
    tools=[jira_query_tool],
    verbose=True
)

splunk_agent = Agent(
    role="Splunk Monitor",
    goal="Execute Splunk queries and extract relevant data",
    tools=[splunk_search_tool],
    verbose=True
)

# --- TASKS ---
def fetch_jira_tickets():
    # Example JQL: fetch SKYSI tickets (customize as needed)
    jql = 'project = SKYSI AND created >= -1d order by created desc'
    result = jira_query_tool(jql)
    # TODO: Parse result to extract aem_service, date_created, aem_tier, aem_envType
    # For now, just return the raw result
    return result

def run_splunk_query(jira_data):
    # TODO: Construct Splunk query using extracted Jira data
    # For now, use a placeholder query
    query = 'index="dx_aem_engineering" sourcetype=aemaccess aem_service=cm-p55671-e392469 aem_envType=prod aem_tier=publish (path="/adobe/forms/af/submit*" OR "guideContainer.af.submit.jsp") code>=500 earliest=-1d latest=now'
    result = splunk_search_tool(query)
    # TODO: Parse result to extract required fields
    return result

def create_skyops_ticket(splunk_data):
    # TODO: Use jira_query_tool to create a SKYOPS ticket with splunk_data
    # For now, just print the data
    print("Creating SKYOPS ticket with the following data:")
    print(splunk_data)
    return "SKYOPS ticket creation simulated."

# Define CrewAI tasks
jira_task = Task(
    description="Fetch SKYSI Jira tickets and extract relevant fields.",
    agent=jira_agent,
    run=fetch_jira_tickets
)

splunk_task = Task(
    description="Run Splunk query using Jira data and extract relevant fields.",
    agent=splunk_agent,
    run=lambda: run_splunk_query(jira_task.result)
)

skyops_task = Task(
    description="Create SKYOPS Jira ticket with Splunk data.",
    agent=jira_agent,
    run=lambda: create_skyops_ticket(splunk_task.result)
)

# --- CREW ---
crew = Crew(
    agents=[jira_agent, splunk_agent],
    tasks=[jira_task, splunk_task, skyops_task],
    verbose=True
)

if __name__ == "__main__":
    crew.kickoff() 