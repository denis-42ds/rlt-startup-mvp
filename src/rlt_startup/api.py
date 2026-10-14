from fastapi import FastAPI

app = FastAPI(
    title="RLT.Startup API",
    description="B2B marketplace coordinated by AI agents",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
