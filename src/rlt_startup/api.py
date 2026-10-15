from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status

from rlt_startup.models.rfq import RFQ
from rlt_startup.repositories.rfq_repository import (
    InMemoryRFQRepository,
    RFQAlreadyExistsError,
    RFQRepository,
)

app = FastAPI(
    title="RLT.Startup API",
    description="B2B marketplace coordinated by AI agents",
    version="0.1.0",
)

app.state.rfq_repository = InMemoryRFQRepository()


def get_rfq_repository(request: Request) -> RFQRepository:
    return request.app.state.rfq_repository


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/rfqs",
    response_model=RFQ,
    status_code=status.HTTP_201_CREATED,
    tags=["rfqs"],
)
def create_rfq(
    rfq: RFQ,
    repository: RFQRepository = Depends(get_rfq_repository),
) -> RFQ:
    try:
        repository.add(rfq)
    except RFQAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="RFQ with this ID already exists",
        ) from exc

    return rfq


@app.get("/rfqs/{rfq_id}", response_model=RFQ, tags=["rfqs"])
def get_rfq(
    rfq_id: UUID,
    repository: RFQRepository = Depends(get_rfq_repository),
) -> RFQ:
    rfq = repository.get(rfq_id)

    if rfq is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RFQ not found",
        )

    return rfq

