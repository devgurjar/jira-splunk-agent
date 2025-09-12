from splunk_tool import splunk_search_tool

def test_query():
    #query = 'index="dx_aem_engineering" sourcetype=aemerror level=ERROR aem_envType=prod aem_tier=publish (*guideContainer.af.submit.jsp* OR *FormSubmitActionManagerServiceImpl*) aem_service=cm-p154411-e1620520 earliest="06/29/2025:00:00:00" latest="06/29/2025:23:59:59"'
    query = 'index=dx_aem_engineering level=ERROR sourcetype=aemerror aem_envType=prod aem_tier=publish (*guideContainer.af.submit.jsp* OR *FormSubmitActionManagerServiceImpl*) aem_service=cm-p154411-e1620520 earliest="06/28/2025:18:30:00" latest="06/29/2025:18:30:00"'
    print(f"Query: {query}")
    result = splunk_search_tool(query)
    print("Splunk Response:\n", result)

# Call the function
if __name__ == "__main__":
    test_query()
