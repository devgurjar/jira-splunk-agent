import os

def get_api_config():
    return {
        "host": os.getenv("API_HOST", "0.0.0.0"),
        "port": int(os.getenv("API_PORT", "8000")),
        "debug": os.getenv("API_DEBUG", "false").lower() == "true"
    }

    