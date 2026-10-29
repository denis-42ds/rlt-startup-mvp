from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

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


def test_api_generates_documents_for_confirmed_order(client):
    repository = client.app.state.order_repository
    order = make_order().model_copy(
        update={
            "buyer_organization_id": client.app.state.test_buyer_org_id,
            "supplier_organization_id": client.app.state.test_supplier_org_id,
        }
    )
    repository.add(order)

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


@pytest.mark.parametrize(
    "order_status",
    [
        OrderStatus.PENDING_BUYER_CONFIRMATION,
        OrderStatus.PENDING_SUPPLIER_CONFIRMATION,
        OrderStatus.REJECTED,
    ],
)
def test_api_rejects_documents_for_unconfirmed_order(client, order_status):
    order = make_order(order_status).model_copy(
        update={
            "buyer_organization_id": client.app.state.test_buyer_org_id,
            "supplier_organization_id": client.app.state.test_supplier_org_id,
        }
    )
    client.app.state.order_repository.add(order)

    response = client.get(f"/orders/{order.id}/documents")

    assert response.status_code == 422


def test_api_returns_404_for_unknown_order_documents(client):
    response = client.get(f"/orders/{uuid4()}/documents")

    assert response.status_code == 404


def test_api_document_generation_does_not_modify_order(client):
    repository = client.app.state.order_repository
    order = make_order().model_copy(
        update={
            "buyer_organization_id": client.app.state.test_buyer_org_id,
            "supplier_organization_id": client.app.state.test_supplier_org_id,
        }
    )
    repository.add(order)
    original_data = repository.get(order.id).model_dump()

    response = client.get(f"/orders/{order.id}/documents")

    assert response.status_code == 200
    assert repository.get(order.id).model_dump() == original_data


def test_documents_require_authentication(client):
    order = make_order().model_copy(
        update={
            "buyer_organization_id": client.app.state.test_buyer_org_id,
            "supplier_organization_id": client.app.state.test_supplier_org_id,
        }
    )
    client.app.state.order_repository.add(order)

    response = client.get(
        f"/orders/{order.id}/documents",
        headers={"Authorization": ""},
    )

    assert response.status_code == 401


def test_other_buyer_cannot_access_order_documents(client):
    order = make_order().model_copy(
        update={
            "buyer_organization_id": client.app.state.test_buyer_org_id,
            "supplier_organization_id": client.app.state.test_supplier_org_id,
        }
    )
    client.app.state.order_repository.add(order)

    response = client.get(
        f"/orders/{order.id}/documents",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_other_buyer_token}"
            )
        },
    )

    assert response.status_code == 404


def test_supplier_can_access_own_confirmed_order_documents(client):
    order = make_order().model_copy(
        update={
            "buyer_organization_id": client.app.state.test_buyer_org_id,
            "supplier_organization_id": client.app.state.test_supplier_org_id,
        }
    )
    client.app.state.order_repository.add(order)

    response = client.get(
        f"/orders/{order.id}/documents",
        headers={
            "Authorization": f"Bearer {client.app.state.test_supplier_token}"
        },
    )

    assert response.status_code == 200


def test_supplier_cannot_access_another_suppliers_order_documents(client):
    order = make_order().model_copy(
        update={
            "buyer_organization_id": client.app.state.test_buyer_org_id,
#            "supplier_organization_id": client.app.state.test_other_buyer_org_id,
            "supplier_organization_id": uuid4(),
        }
    )
    client.app.state.order_repository.add(order)

    response = client.get(
        f"/orders/{order.id}/documents",
        headers={
            "Authorization": f"Bearer {client.app.state.test_supplier_token}"
        },
    )

    assert response.status_code == 404


def test_orchestrator_cannot_access_order_documents(client):
    order = make_order().model_copy(
        update={
            "buyer_organization_id": client.app.state.test_buyer_org_id,
            "supplier_organization_id": client.app.state.test_supplier_org_id,
        }
    )
    client.app.state.order_repository.add(order)

    response = client.get(
        f"/orders/{order.id}/documents",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_orchestrator_token}"
            )
        },
    )

    assert response.status_code == 403
