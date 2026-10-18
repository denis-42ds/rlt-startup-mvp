from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4
from fastapi.testclient import TestClient
import pytest

from rlt_startup.api import app
from rlt_startup.models.order import (
    Order,
    OrderItem,
    OrderParty,
    OrderStatus,
)
from rlt_startup.services.document_generation import (
    DocumentGenerationError,
    generate_document_drafts,
)
from rlt_startup.repositories.order_repository import (
    InMemoryOrderRepository,
)

def make_order(status: OrderStatus = OrderStatus.CONFIRMED) -> Order:
    now = datetime.now(timezone.utc)

    buyer_confirmed_at = None
    supplier_confirmed_at = None
    rejected_by = None
    rejection_reason = None

    if status == OrderStatus.PENDING_SUPPLIER_CONFIRMATION:
        buyer_confirmed_at = now
    elif status == OrderStatus.CONFIRMED:
        buyer_confirmed_at = now
        supplier_confirmed_at = now
    elif status == OrderStatus.REJECTED:
        rejected_by = OrderParty.BUYER
        rejection_reason = "Тестовый отказ"

    return Order(
        rfq_id=uuid4(),
        offer_id=uuid4(),
        buyer_organization_id=uuid4(),
        supplier_organization_id=uuid4(),
        items=[
            OrderItem(
                rfq_item_id=uuid4(),
                catalog_item_id=uuid4(),
                product_name="Стальной лист",
                quantity=Decimal("100"),
                unit="кг",
                unit_price=Decimal("145.50"),
            )
        ],
        currency="RUB",
        total_amount=Decimal("14550.00"),
        offer_valid_until=now + timedelta(days=365),
        status=status,
        buyer_confirmed_at=buyer_confirmed_at,
        supplier_confirmed_at=supplier_confirmed_at,
        rejected_by=rejected_by,
        rejection_reason=rejection_reason,
        created_at=now,
        updated_at=now,
    )


def test_generates_three_drafts_from_confirmed_order():
    order = make_order()

    bundle = generate_document_drafts(order)

    assert bundle.commercial_offer.status == "draft"
    assert bundle.order.status == "draft"
    assert bundle.shipping_specification.status == "draft"

    assert bundle.commercial_offer.source_order_id == order.id
    assert bundle.order.source_order_id == order.id
    assert bundle.shipping_specification.source_order_id == order.id

    assert bundle.commercial_offer.total_amount == Decimal("14550.00")
    assert bundle.order.total_amount == Decimal("14550.00")

    assert bundle.commercial_offer.items[0].line_total == Decimal("14550.00")
    assert bundle.order.items[0].unit_price == Decimal("145.50")


@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.PENDING_BUYER_CONFIRMATION,
        OrderStatus.PENDING_SUPPLIER_CONFIRMATION,
        OrderStatus.REJECTED,
    ],
)
def test_documents_cannot_be_generated_for_unconfirmed_order(status):
    order = make_order(status)

    with pytest.raises(DocumentGenerationError):
        generate_document_drafts(order)


def test_document_generation_does_not_modify_order():
    order = make_order()
    original_data = order.model_dump()

    generate_document_drafts(order)

    assert order.model_dump() == original_data


def test_api_generates_documents_for_confirmed_order():
    original_repository = app.state.order_repository
    repository = InMemoryOrderRepository()
    order = make_order()
    repository.add(order)
    app.state.order_repository = repository

    try:
        with TestClient(app) as client:
            response = client.get(f"/orders/{order.id}/documents")

        assert response.status_code == 200

        data = response.json()
        assert data["commercial_offer"]["document_type"] == "commercial_offer"
        assert data["order"]["document_type"] == "order"
        assert (
            data["shipping_specification"]["document_type"]
            == "shipping_specification"
        )

        assert data["commercial_offer"]["status"] == "draft"
        assert data["order"]["total_amount"] == "14550.00"
    finally:
        app.state.order_repository = original_repository


@pytest.mark.parametrize(
    "order_status",
    [
        OrderStatus.PENDING_BUYER_CONFIRMATION,
        OrderStatus.PENDING_SUPPLIER_CONFIRMATION,
        OrderStatus.REJECTED,
    ],
)
def test_api_rejects_documents_for_unconfirmed_order(order_status):
    original_repository = app.state.order_repository
    repository = InMemoryOrderRepository()
    order = make_order(order_status)
    repository.add(order)
    app.state.order_repository = repository

    try:
        with TestClient(app) as client:
            response = client.get(f"/orders/{order.id}/documents")

        assert response.status_code == 422
    finally:
        app.state.order_repository = original_repository


def test_api_returns_404_for_unknown_order_documents():
    original_repository = app.state.order_repository
    app.state.order_repository = InMemoryOrderRepository()

    try:
        with TestClient(app) as client:
            response = client.get(f"/orders/{uuid4()}/documents")

        assert response.status_code == 404
    finally:
        app.state.order_repository = original_repository


def test_api_document_generation_does_not_modify_order():
    original_repository = app.state.order_repository
    repository = InMemoryOrderRepository()
    order = make_order()
    repository.add(order)
    original_data = repository.get(order.id).model_dump()
    app.state.order_repository = repository

    try:
        with TestClient(app) as client:
            response = client.get(f"/orders/{order.id}/documents")

        assert response.status_code == 200
        assert repository.get(order.id).model_dump() == original_data
    finally:
        app.state.order_repository = original_repository

