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
from rlt_startup.repositories.offer_repository import (
    InMemoryOfferRepository,
    OfferAlreadyExistsError,
    OfferRepository,
)
from rlt_startup.models.order import Order, OrderParty
from rlt_startup.repositories.order_repository import (
    InMemoryOrderRepository,
    OrderAlreadyExistsError,
    OrderRepository,
)
from rlt_startup.services.document_generation import (
    DocumentGenerationError,
    generate_document_drafts,
)
from rlt_startup.services.offer_validation import OfferValidationError
from rlt_startup.services.order_workflow import (
    OrderWorkflowError,
    buyer_confirm_order,
    create_order_from_offer,
    reject_order,
    supplier_confirm_order,
)

app = FastAPI(
    title="RLT.Startup API",
    description="B2B marketplace coordinated by AI agents",
    version="0.1.0",
)

app.state.rfq_repository = InMemoryRFQRepository()
app.state.offer_repository = InMemoryOfferRepository()
app.state.order_repository = InMemoryOrderRepository()
app.state.supplier_adapters = {}


class SellerOfferWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_ids: list[UUID] = Field(min_length=1)


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: UUID

class RejectOrderRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    reason: str = Field(min_length=1, max_length=2000)


def get_order_repository(request: Request) -> OrderRepository:
    return request.app.state.order_repository


def get_rfq_repository(request: Request) -> RFQRepository:
    return request.app.state.rfq_repository


def get_offer_repository(request: Request) -> OfferRepository:
    return request.app.state.offer_repository


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
    offer_repository: OfferRepository = Depends(get_offer_repository),
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

    result = run_seller_offer_workflow(
        rfq=rfq,
        supplier_ids=payload.supplier_ids,
        adapters=adapters,
    )

    for preparation in result.preparations.values():
        if preparation.ready and preparation.offer is not None:
            try:
                offer_repository.add(preparation.offer)
            except OfferAlreadyExistsError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Offer with this ID already exists",
                ) from exc

    return result

@app.post(
    "/rfqs/{rfq_id}/orders",
    response_model=Order,
    status_code=status.HTTP_201_CREATED,
    tags=["orders"],
)
def create_order(
    rfq_id: UUID,
    payload: CreateOrderRequest,
    rfq_repository: RFQRepository = Depends(get_rfq_repository),
    offer_repository: OfferRepository = Depends(get_offer_repository),
    order_repository: OrderRepository = Depends(get_order_repository),
) -> Order:
    rfq = rfq_repository.get(rfq_id)
    if rfq is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RFQ not found",
        )

    offer = offer_repository.get(payload.offer_id)
    if offer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offer not found",
        )

    try:
        order = create_order_from_offer(rfq, offer)
    except (OrderWorkflowError, OfferValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    try:
        order_repository.add(order)
    except OrderAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order with this ID already exists",
        ) from exc

    return order


@app.post(
    "/orders/{order_id}/buyer-confirmation",
    response_model=Order,
    tags=["orders"],
)
def confirm_order_by_buyer(
    order_id: UUID,
    repository: OrderRepository = Depends(get_order_repository),
) -> Order:
    order = repository.get(order_id)

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    try:
        updated_order = buyer_confirm_order(order)
    except OrderWorkflowError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    # Сохраняем переход состояния в репозитории.
    # Для in-memory реализации заменяем сохранённую запись.
    repository.update(updated_order)

    return updated_order


@app.post(
    "/orders/{order_id}/supplier-confirmation",
    response_model=Order,
    tags=["orders"],
)
def confirm_order_by_supplier(
    order_id: UUID,
    repository: OrderRepository = Depends(get_order_repository),
    adapters: dict[UUID, CatalogPolicyAdapter] = Depends(
        get_supplier_adapters
    ),
) -> Order:
    order = repository.get(order_id)

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    adapter = adapters.get(order.supplier_organization_id)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Supplier adapter is not configured",
        )

    try:
        updated_order = supplier_confirm_order(order, adapter)
    except OrderWorkflowError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    repository.update(updated_order)

    return updated_order

@app.post("/orders/{order_id}/buyer-rejection")
def buyer_rejection(
    order_id: UUID,
    payload: RejectOrderRequest,
    repository: OrderRepository = Depends(get_order_repository),
):
    order = repository.get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    try:
        updated_order = reject_order(
            order,
            party=OrderParty.BUYER,
            reason=payload.reason,
        )
    except OrderWorkflowError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    repository.update(updated_order)
    return updated_order


@app.post("/orders/{order_id}/supplier-rejection")
def supplier_rejection(
    order_id: UUID,
    payload: RejectOrderRequest,
    repository: OrderRepository = Depends(get_order_repository),
):
    order = repository.get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    try:
        updated_order = reject_order(
            order,
            party=OrderParty.SUPPLIER,
            reason=payload.reason,
        )
    except OrderWorkflowError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    repository.update(updated_order)
    return updated_order


@app.get("/orders/{order_id}/documents", tags=["orders"])
def get_order_documents(
    order_id: UUID,
    repository: OrderRepository = Depends(get_order_repository),
):
    order = repository.get(order_id)

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    try:
        return generate_document_drafts(order)
    except DocumentGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

