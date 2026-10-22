import os
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
from rlt_startup.services.rfq_extraction import (
    RFQExtraction,
    RFQModelResponseError,
    RFQModelUnavailableError,
    extract_rfq,
)
from rlt_startup.services.authentication import (
    Identity,
    authenticate_token,
    load_demo_credentials,
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

try:
    app.state.demo_credentials = load_demo_credentials(
        os.environ.get("RLT_DEMO_CREDENTIALS")
    )
except ValueError as exc:
    raise RuntimeError(
        "Invalid RLT_DEMO_CREDENTIALS configuration"
    ) from exc

class SellerOfferWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_ids: list[UUID] = Field(min_length=1)


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: UUID


class RFQExtractionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    text: str = Field(min_length=1, max_length=10000)


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


def get_current_identity(request: Request) -> Identity:
    return authenticate_token(
        request.headers.get("Authorization"),
        request.app.state.demo_credentials,
    )


def require_role(identity: Identity, allowed_role: str) -> None:
    if identity.role != allowed_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )


def require_order_party(
    identity: Identity,
    order: Order,
    party: OrderParty,
) -> None:
    if party == OrderParty.BUYER:
        require_role(identity, "buyer")
        organization_id = order.buyer_organization_id
    else:
        require_role(identity, "supplier")
        organization_id = order.supplier_organization_id

    if identity.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
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
def create_rfq(
    rfq: RFQ,
    identity: Identity = Depends(get_current_identity),
    repository: RFQRepository = Depends(get_rfq_repository),
) -> RFQ:
    require_role(identity, "buyer")

    # Организация определяется сервером, а не клиентским запросом.
    rfq = rfq.model_copy(
        update={"buyer_organization_id": identity.organization_id}
    )

    try:
        repository.add(rfq)
    except RFQAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="RFQ with this ID already exists",
        ) from exc

    return rfq


@app.post(
    "/rfqs/extract",
    response_model=RFQExtraction,
    tags=["rfqs"],
)
def extract_rfq_from_text(
    payload: RFQExtractionRequest,
    identity: Identity = Depends(get_current_identity),
) -> RFQExtraction:
    """Извлекает поля RFQ из текста без создания заявки."""
    require_role(identity, "buyer")

    try:
        result = extract_rfq(payload.text)
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except RFQModelUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Локальная модель временно недоступна",
        ) from exc
    except RFQModelResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Не удалось безопасно обработать ответ локальной модели",
        ) from exc


@app.get("/rfqs/{rfq_id}", response_model=RFQ, tags=["rfqs"])
def get_rfq(
    rfq_id: UUID,
    identity: Identity = Depends(get_current_identity),
    repository: RFQRepository = Depends(get_rfq_repository),
) -> RFQ:
    require_role(identity, "buyer")

    rfq = repository.get(rfq_id)

    if rfq is None or rfq.buyer_organization_id != identity.organization_id:
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
    adapters: dict[UUID, CatalogPolicyAdapter] = Depends(get_supplier_adapters),
    identity: Identity = Depends(get_current_identity),
) -> SellerOfferWorkflowResult:

    require_role(identity, "orchestrator")
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
    identity: Identity = Depends(get_current_identity),
    rfq_repository: RFQRepository = Depends(get_rfq_repository),
    offer_repository: OfferRepository = Depends(get_offer_repository),
    order_repository: OrderRepository = Depends(get_order_repository),
) -> Order:
    require_role(identity, "buyer")

    rfq = rfq_repository.get(rfq_id)
    if rfq is None or rfq.buyer_organization_id != identity.organization_id:
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
    identity: Identity = Depends(get_current_identity),
) -> Order:
    order = repository.get(order_id)

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    require_order_party(identity, order, OrderParty.BUYER)
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
    identity: Identity = Depends(get_current_identity),
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

    require_order_party(identity, order, OrderParty.SUPPLIER)
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
    identity: Identity = Depends(get_current_identity),
):
    order = repository.get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    require_order_party(identity, order, OrderParty.BUYER)
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
    identity: Identity = Depends(get_current_identity),
):
    order = repository.get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    require_order_party(identity, order, OrderParty.SUPPLIER)
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
    identity: Identity = Depends(get_current_identity),
):
    order = repository.get(order_id)

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    # Заказ доступен только его покупателю или поставщику.
    if identity.role == "buyer":
        if identity.organization_id != order.buyer_organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )
    elif identity.role == "supplier":
        if identity.organization_id != order.supplier_organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role is not allowed to access order documents",
        )

    try:
        return generate_document_drafts(order)
    except DocumentGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
