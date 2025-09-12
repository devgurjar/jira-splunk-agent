#!/usr/bin/env python3
"""
Splunk Agent Standalone Server - Can run independently or be orchestrated
"""

import os
import sys
import asyncio
import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the current directory to Python path for standalone execution
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from api.app import create_app
from config.settings import get_api_config

def main():
    """Main entry point for standalone Splunk Agent"""
    config = get_api_config()
    
    print("🚀 Starting Splunk Agent Standalone Server...")
    print(f"📍 Host: {config['host']}")
    print(f"🔌 Port: {config['port']}")
    print(f"🐛 Debug: {config['debug']}")
    print(f"📚 API Documentation: https://{config['host']}:{config['port']}/docs")
    print(f"🏥 Health Check: https://{config['host']}:{config['port']}/health")
    print("=" * 60)
    
    app = create_app()
    
    uvicorn.run(
        app,
        host=config["host"],
        port=config["port"],
        reload=config["debug"],
        log_level="info"
    )

if __name__ == "__main__":
    main() 