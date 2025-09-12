from fastapi import FastAPI

def create_app():
    app = FastAPI(
        title="Splunk Agent API",
        description="Standalone or orchestrated Splunk agent.",
        version="1.0.0"
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # Add your other endpoints here

    return app