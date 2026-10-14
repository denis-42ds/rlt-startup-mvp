from fastapi import FastAPI, status

from rlt_startup.models.rfq import RFQ

app = FastAPI(
    title="RLT.Startup API",
    description="B2B marketplace coordinated by AI agents",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/rfqs",
    response_model=RFQ,
    status_code=status.HTTP_201_CREATED,
    tags=["rfqs"],
)
def create_rfq(rfq: RFQ) -> RFQ:
    return rfq

