from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from rlt_startup.models.rfq import RFQ
from rlt_startup.repositories.rfq_repository import (
    InMemoryRFQRepository,
    RFQAlreadyExistsError,
    RFQRepository,
)
from rlt_startup.services.catalog_policy import CatalogPolicyAdapter
from rlt_startup.services.seller_offer_workflow import (
    SellerOfferWorkflowResult,
    run_seller_offer_workflow,
)

app = FastAPI(
    title="RLT.Startup API",
    description="B2B marketplace coordinated by AI agents",
    version="0.1.0",
)

app.state.rfq_repository = InMemoryRFQRepository()
app.state.supplier_adapters = {}


class SellerOfferWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_ids: list[UUID] = Field(min_length=1)


def get_rfq_repository(request: Request) -> RFQRepository:
    return request.app.state.rfq_repository


def get_supplier_adapters(
    request: Request,
) -> dict[UUID, CatalogPolicyAdapter]:
    return request.app.state.supplier_adapters


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


@app.post(
    "/rfqs/{rfq_id}/seller-offer-workflow",
    response_model=SellerOfferWorkflowResult,
    tags=["seller-workflow"],
)
def execute_seller_offer_workflow(
    rfq_id: UUID,
    payload: SellerOfferWorkflowRequest,
    repository: RFQRepository = Depends(get_rfq_repository),
    adapters: dict[UUID, CatalogPolicyAdapter] = Depends(
        get_supplier_adapters
    ),
) -> SellerOfferWorkflowResult:
    rfq = repository.get(rfq_id)

    if rfq is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RFQ not found",
        )

    if len(payload.supplier_ids) != len(set(payload.supplier_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="supplier_ids must not contain duplicates",
        )

    return run_seller_offer_workflow(
        rfq=rfq,
        supplier_ids=payload.supplier_ids,
        adapters=adapters,
    )
