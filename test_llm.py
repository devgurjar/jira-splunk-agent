import os
from dotenv import load_dotenv
from crewai import LLM
import traceback

load_dotenv()

print("AZURE_API_KEY:", os.getenv("AZURE_API_KEY"))
print("AZURE_API_BASE:", os.getenv("AZURE_API_BASE"))
print("AZURE_API_VERSION:", os.getenv("AZURE_API_VERSION"))
print("AZURE_OPENAI_DEPLOYMENT_NAME:", os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"))

llm = LLM(
    model="azure/gpt-4.1",
)

prompt = "Say hello from Azure OpenAI!"

try:
    response = llm.call(prompt)
    print("LLM response:", response)
except Exception as e:
    print("Error calling LLM:", e)
    traceback.print_exc() 