import os
from typing import Dict, Any

def get_config() -> Dict[str, Any]:
    """Load configuration from environment variables"""
    return {
        # "splunk_host": os.getenv("SPLUNK_HOST", "localhost"),
        # "splunk_port": int(os.getenv("SPLUNK_PORT", "8089")),
        'splunk_host': 'splunk.or1.adobe.net',
        'splunk_port': '8089',
        # "splunk_username": os.getenv("SPLUNK_USERNAME", "admin"),
        # "splunk_password": os.getenv("SPLUNK_PASSWORD", ""),
        'splunk_username': 'dgurjar',
        'splunk_password': 'Radhika@kartik@2009',
        "splunk_app": os.getenv("SPLUNK_APP", "search"),
        "agent_name": os.getenv("AGENT_NAME", "splunk_agent"),
        "agent_model": os.getenv("AGENT_MODEL", "gpt-4o"),
        "knowledge_base_path": os.getenv("KNOWLEDGE_BASE_PATH", "./knowledge_base"),
        "agent_id": os.getenv("AGENT_ID", "splunk_agent"),
        "agent_version": os.getenv("AGENT_VERSION", "1.0.0"),
        # Azure OpenAI Configuration
        "azure_openai_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT"),
        "azure_openai_deployment_name": os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
        "azure_openai_api_version": os.getenv("AZURE_OPENAI_API_VERSION"),
        "azure_openai_api_key": os.getenv("AZURE_OPENAI_API_KEY")
    }

def validate_config(config: Dict[str, Any]) -> bool:
    """Validate required configuration values"""
    required_fields = [
        "splunk_host",
        "splunk_username", 
        "splunk_password"
    ]
    has_azure_openai = all([
        config.get("azure_openai_endpoint"),
        config.get("azure_openai_deployment_name"),
        config.get("azure_openai_api_key")
    ])
    if not has_azure_openai:
        return False
    for field in required_fields:
        if not config.get(field):
            return False
    return True

def get_api_config() -> Dict[str, Any]:
    """Get API-specific configuration"""
    return {
        "host": os.getenv("API_HOST", "0.0.0.0"),
        "port": int(os.getenv("API_PORT", "8000")),
        "debug": os.getenv("API_DEBUG", "false").lower() == "true"
    }

def get_orchestrator_config() -> Dict[str, Any]:
    """Get orchestrator-specific configuration"""
    return {
        "orchestrator_url": os.getenv("ORCHESTRATOR_URL", "http://localhost:9000"),
        "register_with_orchestrator": os.getenv("REGISTER_WITH_ORCHESTRATOR", "false").lower() == "true",
        "heartbeat_interval": int(os.getenv("HEARTBEAT_INTERVAL", "30")),
        "auto_discovery": os.getenv("AUTO_DISCOVERY", "true").lower() == "true"
    }

def get_agent_info() -> Dict[str, Any]:
    """Get agent information for registration"""
    config = get_config()
    return {
        "agent_id": config["agent_id"],
        "agent_name": config["agent_name"],
        "agent_version": config["agent_version"],
        "capabilities": [
            "splunk_query_execution",
            "natural_language_processing", 
            "query_validation",
            "index_management",
            "source_management",
            "data_analysis",
            "knowledge_base_search"
        ],
        "endpoints": {
            "health": "/health",
            "query": "/query",
            "agent_prompt": "/agent/prompt",
            "splunk_indexes": "/splunk/indexes",
            "splunk_sources": "/splunk/sources/{index}",
            "validate_query": "/splunk/validate"
        }
    } 