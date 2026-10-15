from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from rlt_startup.models.supplier_data import (
    InventorySnapshot,
    SupplierCatalogItem,
    SupplierPolicy,
)
from rlt_startup.services.catalog_policy import InMemoryCatalogPolicyAdapter


def test_seller_workflow_prepares_and_compares_offers(client) -> None:
    supplier_id = uuid4()
    catalog_item = SupplierCatalogItem(
        supplier_organization_id=supplier_id,
        product_name="Стальной лист",
        unit="кг",
        unit_price="150",
        currency="RUB",
    )
    adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[catalog_item],
        inventory_snapshots=[
            InventorySnapshot(
                catalog_item_id=catalog_item.id,
                available_quantity="200",
                observed_at=datetime.now(timezone.utc)
                - timedelta(minutes=5),
                source="api-test",
            )
        ],
        policies=[
            SupplierPolicy(
                supplier_organization_id=supplier_id,
                currency="RUB",
                minimum_order_value="0",
                max_offer_validity_days=7,
            )
        ],
    )

    client.app.state.supplier_adapters = {supplier_id: adapter}

    create_response = client.post(
        "/rfqs",
        json={
            "buyer_organization_id": str(uuid4()),
            "currency": "RUB",
            "max_unit_price": "200",
            "items": [
                {
                    "product_name": "Стальной лист",
                    "quantity": "100",
                    "unit": "кг",
                }
            ],
        },
    )
    assert create_response.status_code == 201
    rfq_id = create_response.json()["id"]

    response = client.post(
        f"/rfqs/{rfq_id}/seller-offer-workflow",
        json={"supplier_ids": [str(supplier_id)]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["preparations"][str(supplier_id)]["ready"] is True
    assert data["preparations"][str(supplier_id)]["offer"] is not None
    assert len(data["comparisons"]) == 1
    assert data["comparisons"][0]["eligible"] is True
    assert Decimal(data["comparisons"][0]["total_price"]) == Decimal("15000")


def test_seller_workflow_returns_404_for_unknown_rfq(client) -> None:
    response = client.post(
        f"/rfqs/{uuid4()}/seller-offer-workflow",
        json={"supplier_ids": [str(uuid4())]},
    )

    assert response.status_code == 404


def test_seller_workflow_reports_missing_supplier_adapter(client) -> None:
    supplier_id = uuid4()

    create_response = client.post(
        "/rfqs",
        json={
            "buyer_organization_id": str(uuid4()),
            "currency": "RUB",
            "items": [
                {
                    "product_name": "Стальной лист",
                    "quantity": "100",
                    "unit": "кг",
                }
            ],
        },
    )
    assert create_response.status_code == 201

    response = client.post(
        f"/rfqs/{create_response.json()['id']}/seller-offer-workflow",
        json={"supplier_ids": [str(supplier_id)]},
    )

    assert response.status_code == 200
    data = response.json()
    preparation = data["preparations"][str(supplier_id)]

    assert preparation["ready"] is False
    assert preparation["offer"] is None
    assert "адаптер" in preparation["reasons"][0].lower()
    assert data["comparisons"] == []


def test_seller_workflow_rejects_duplicate_supplier_ids(client) -> None:
    supplier_id = uuid4()

    create_response = client.post(
        "/rfqs",
        json={
            "buyer_organization_id": str(uuid4()),
            "items": [
                {
                    "product_name": "Стальной лист",
                    "quantity": "100",
                    "unit": "кг",
                }
            ],
        },
    )
    assert create_response.status_code == 201

    response = client.post(
        f"/rfqs/{create_response.json()['id']}/seller-offer-workflow",
        json={
            "supplier_ids": [str(supplier_id), str(supplier_id)]
        },
    )

    assert response.status_code == 422
