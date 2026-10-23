from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

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
        headers={"Authorization": (f"Bearer {client.app.state.test_orchestrator_token}")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["preparations"][str(supplier_id)]["ready"] is True
    assert data["preparations"][str(supplier_id)]["offer"] is not None
    assert len(data["comparisons"]) == 1
    assert data["comparisons"][0]["eligible"] is True
    assert Decimal(data["comparisons"][0]["total_price"]) == Decimal("15000")

    offer_data = data["preparations"][str(supplier_id)]["offer"]
    offer_id = UUID(offer_data["id"])

    stored_offer = client.app.state.offer_repository.get(offer_id)

    assert stored_offer is not None
    assert stored_offer.id == offer_id
    assert stored_offer.rfq_id == UUID(rfq_id)
    assert stored_offer.supplier_organization_id == supplier_id


def test_seller_workflow_returns_404_for_unknown_rfq(client) -> None:
    response = client.post(
        f"/rfqs/{uuid4()}/seller-offer-workflow",
        json={"supplier_ids": [str(uuid4())]},
        headers={"Authorization": (f"Bearer {client.app.state.test_orchestrator_token}")},
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
        headers={"Authorization": (f"Bearer {client.app.state.test_orchestrator_token}")},
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
        json={"supplier_ids": [str(supplier_id), str(supplier_id)]},
        headers={"Authorization": (f"Bearer {client.app.state.test_orchestrator_token}")},
    )

    assert response.status_code == 422


def test_create_rfq_requires_authentication(client):
    response = client.post(
        "/rfqs",
        headers={"Authorization": ""},
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

    assert response.status_code == 401


def test_create_rfq_rejects_supplier_role(client):
    response = client.post(
        "/rfqs",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_supplier_token}"
            )
        },
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

    assert response.status_code == 403


def test_create_rfq_uses_organization_from_token(client):
    response = client.post(
        "/rfqs",
        json={
            "buyer_organization_id": str(
                client.app.state.test_other_buyer_org_id
            ),
            "items": [
                {
                    "product_name": "Стальной лист",
                    "quantity": "100",
                    "unit": "кг",
                }
            ],
        },
    )

    assert response.status_code == 201
    assert (
        response.json()["buyer_organization_id"]
        == str(client.app.state.test_buyer_org_id)
    )


def _create_rfq_and_offer(client):
    """Создать RFQ и получить сохранённое предложение через API."""
    supplier_id = client.app.state.test_supplier_org_id
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
                source="order-api-test",
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

    rfq_response = client.post(
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
    assert rfq_response.status_code == 201
    rfq_id = rfq_response.json()["id"]

    workflow_response = client.post(
        f"/rfqs/{rfq_id}/seller-offer-workflow",
        json={"supplier_ids": [str(supplier_id)]},
        headers={"Authorization": f"Bearer {client.app.state.test_orchestrator_token}"},
    )
    assert workflow_response.status_code == 200

    offer_data = workflow_response.json()["preparations"][
        str(supplier_id)
    ]["offer"]
    assert offer_data is not None

    return rfq_id, offer_data


def test_create_order_from_saved_offer(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)
    offer_id = offer_data["id"]

    response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_id},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["rfq_id"] == rfq_id
    assert data["offer_id"] == offer_id
    assert data["status"] == "pending_buyer_confirmation"
    assert Decimal(data["total_amount"]) == Decimal("15000")
    assert data["currency"] == "RUB"

    order_id = UUID(data["id"])
    stored_order = client.app.state.order_repository.get(order_id)
    assert stored_order is not None
    assert stored_order.id == order_id
    assert stored_order.offer_id == UUID(offer_id)

    events = client.app.state.audit_log.list_events(order_id=order_id)

    assert [event.event_type for event in events] == ["order_created"]
    assert events[0].outcome == "success"


def test_create_order_requires_authentication(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)

    response = client.post(
        f"/rfqs/{rfq_id}/orders",
        headers={"Authorization": ""},
        json={"offer_id": offer_data["id"]},
    )

    assert response.status_code == 401


def test_create_order_rejects_supplier_role(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)

    response = client.post(
        f"/rfqs/{rfq_id}/orders",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_supplier_token}"
            )
        },
        json={"offer_id": offer_data["id"]},
    )

    assert response.status_code == 403


def test_create_order_rejects_foreign_buyer_organization(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)

    response = client.post(
        f"/rfqs/{rfq_id}/orders",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_other_buyer_token}"
            )
        },
        json={"offer_id": offer_data["id"]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "RFQ not found"


def test_create_order_returns_404_for_unknown_rfq(client) -> None:
    response = client.post(
        f"/rfqs/{uuid4()}/orders",
        json={"offer_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "RFQ not found"


def test_create_order_returns_404_for_unknown_offer(client) -> None:
    rfq_response = client.post(
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
    assert rfq_response.status_code == 201

    response = client.post(
        f"/rfqs/{rfq_response.json()['id']}/orders",
        json={"offer_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Offer not found"


def test_create_order_rejects_offer_from_another_rfq(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)

    another_rfq_response = client.post(
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
    assert another_rfq_response.status_code == 201
    another_rfq_id = another_rfq_response.json()["id"]

    response = client.post(
        f"/rfqs/{another_rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )

    assert response.status_code == 422


def test_create_order_rejects_client_supplied_price(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)

    response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={
            "offer_id": offer_data["id"],
            "unit_price": "1",
        },
    )

    assert response.status_code == 422


def test_buyer_can_confirm_order(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)

    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201
    order_id = create_response.json()["id"]

    response = client.post(
        f"/orders/{order_id}/buyer-confirmation",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending_supplier_confirmation"
    assert data["buyer_confirmed_at"] is not None
    assert data["supplier_confirmed_at"] is None

    stored_order = client.app.state.order_repository.get(UUID(order_id))
    assert stored_order is not None
    assert stored_order.status.value == "pending_supplier_confirmation"


def test_buyer_confirmation_returns_404_for_unknown_order(client) -> None:
    response = client.post(
        f"/orders/{uuid4()}/buyer-confirmation",
    )

    assert response.status_code == 404


def test_buyer_cannot_confirm_order_twice(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)

    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201
    order_id = create_response.json()["id"]

    first_response = client.post(
        f"/orders/{order_id}/buyer-confirmation",
    )
    assert first_response.status_code == 200

    second_response = client.post(
        f"/orders/{order_id}/buyer-confirmation",
    )
    assert second_response.status_code == 422

    events = client.app.state.audit_log.list_events(
        order_id=UUID(order_id)
    )

    assert [event.event_type for event in events] == [
        "order_created",
        "buyer_confirmed",
    ]


def test_supplier_can_confirm_after_buyer(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)

    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201
    order_id = create_response.json()["id"]

    buyer_response = client.post(
        f"/orders/{order_id}/buyer-confirmation",
    )
    assert buyer_response.status_code == 200

    supplier_response = client.post(
        f"/orders/{order_id}/supplier-confirmation",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_supplier_token}"
                )
            },
    )

    assert supplier_response.status_code == 200
    data = supplier_response.json()
    assert data["status"] == "order_confirmed"
    assert data["buyer_confirmed_at"] is not None
    assert data["supplier_confirmed_at"] is not None

    stored_order = client.app.state.order_repository.get(UUID(order_id))
    assert stored_order is not None
    assert stored_order.status.value == "order_confirmed"

    events = client.app.state.audit_log.list_events(
        order_id=UUID(order_id)
    )

    assert [event.event_type for event in events] == [
        "order_created",
        "buyer_confirmed",
        "supplier_confirmed",
    ]
    assert all(event.outcome == "success" for event in events)


def test_supplier_confirmation_rejected_when_stock_becomes_insufficient(client):
    rfq_id, offer_data = _create_rfq_and_offer(client)

    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201
    order_data = create_response.json()
    order_id = order_data["id"]

    buyer_response = client.post(
        f"/orders/{order_id}/buyer-confirmation",
    )
    assert buyer_response.status_code == 200

    supplier_id = UUID(offer_data["supplier_organization_id"])
    adapter = client.app.state.supplier_adapters[supplier_id]
    catalog_item_id = UUID(order_data["items"][0]["catalog_item_id"])

    old_snapshot = adapter.get_inventory(catalog_item_id)
    assert old_snapshot is not None

    adapter._inventory[catalog_item_id] = old_snapshot.model_copy(
        update={"available_quantity": Decimal("1")}
    )

    response = client.post(
        f"/orders/{order_id}/supplier-confirmation",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_supplier_token}"
            )
        },
    )
    assert response.status_code == 422
    assert "Недостаточно товара на складе" in response.json()["detail"]

    stored_order = client.app.state.order_repository.get(UUID(order_id))
    assert stored_order is not None
    assert stored_order.status.value == "pending_supplier_confirmation"
    assert stored_order.supplier_confirmed_at is None

    events = client.app.state.audit_log.list_events(
        order_id=UUID(order_id)
    )

    assert [event.event_type for event in events] == [
        "order_created",
        "buyer_confirmed",
        "policy_check_blocked",
    ]
    assert events[-1].outcome == "blocked"
    assert events[-1].reason_code == "supplier_execution_check_failed"
    assert "supplier_confirmed" not in [
        event.event_type for event in events
    ]


def test_supplier_confirmation_rejected_when_inventory_is_stale(client):
    rfq_id, offer_data = _create_rfq_and_offer(client)

    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201
    order_data = create_response.json()
    order_id = order_data["id"]

    buyer_response = client.post(
        f"/orders/{order_id}/buyer-confirmation",
    )
    assert buyer_response.status_code == 200

    supplier_id = UUID(offer_data["supplier_organization_id"])
    adapter = client.app.state.supplier_adapters[supplier_id]
    catalog_item_id = UUID(order_data["items"][0]["catalog_item_id"])

    old_snapshot = adapter.get_inventory(catalog_item_id)
    assert old_snapshot is not None

    adapter._inventory[catalog_item_id] = old_snapshot.model_copy(
        update={
            "observed_at": datetime.now(timezone.utc) - timedelta(days=2)
        }
    )

    response = client.post(
        f"/orders/{order_id}/supplier-confirmation",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_supplier_token}"
            )
        },
    )
    assert response.status_code == 422
    assert "Данные об остатке устарели" in response.json()["detail"]

    stored_order = client.app.state.order_repository.get(UUID(order_id))
    assert stored_order is not None
    assert stored_order.status.value == "pending_supplier_confirmation"
    assert stored_order.supplier_confirmed_at is None


def test_supplier_cannot_confirm_before_buyer(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)

    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201
    order_id = create_response.json()["id"]

    response = client.post(
        f"/orders/{order_id}/supplier-confirmation",
        headers={"Authorization": (f"Bearer {client.app.state.test_supplier_token}")},
    )

    assert response.status_code == 422

    stored_order = client.app.state.order_repository.get(UUID(order_id))
    assert stored_order is not None
    assert stored_order.status.value == "pending_buyer_confirmation"


def test_supplier_confirmation_returns_404_for_unknown_order(client) -> None:
    response = client.post(
        f"/orders/{uuid4()}/supplier-confirmation",
    )

    assert response.status_code == 404


def test_supplier_confirmation_requires_adapter(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)

    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201
    order_id = create_response.json()["id"]

    client.app.state.supplier_adapters = {}

    buyer_response = client.post(
        f"/orders/{order_id}/buyer-confirmation",
    )
    assert buyer_response.status_code == 200

    response = client.post(
        f"/orders/{order_id}/supplier-confirmation",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_supplier_token}"
            )
        },
    )
    assert response.status_code == 422

    stored_order = client.app.state.order_repository.get(UUID(order_id))
    assert stored_order is not None
    assert stored_order.status.value == "pending_supplier_confirmation"


def test_supplier_can_confirm_order_after_catalog_price_changes(client):
    rfq_id, offer_data = _create_rfq_and_offer(client)

    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201

    order_data = create_response.json()
    order_id = order_data["id"]
    original_total = Decimal(order_data["total_amount"])
    original_price = Decimal(order_data["items"][0]["unit_price"])

    supplier_id = UUID(offer_data["supplier_organization_id"])
    adapter = client.app.state.supplier_adapters[supplier_id]
    catalog_item_id = UUID(order_data["items"][0]["catalog_item_id"])

    catalog_item = next(
        item
        for item in adapter.list_catalog_items(supplier_id)
        if item.id == catalog_item_id
    )

    adapter._catalog_items[catalog_item_id] = catalog_item.model_copy(
        update={"unit_price": catalog_item.unit_price + Decimal("50")}
    )

    buyer_response = client.post(
        f"/orders/{order_id}/buyer-confirmation",
    )
    assert buyer_response.status_code == 200

    supplier_response = client.post(
        f"/orders/{order_id}/supplier-confirmation",
        headers={"Authorization": (f"Bearer {client.app.state.test_supplier_token}")},
    )

    assert supplier_response.status_code == 200

    confirmed_order = supplier_response.json()
    assert confirmed_order["status"] == "order_confirmed"
    assert Decimal(confirmed_order["total_amount"]) == original_total
    assert Decimal(confirmed_order["items"][0]["unit_price"]) == original_price


def test_buyer_confirmation_requires_authentication(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)
    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201

    response = client.post(
        f"/orders/{create_response.json()['id']}/buyer-confirmation",
        headers={"Authorization": ""},
    )

    assert response.status_code == 401


def test_supplier_cannot_use_buyer_confirmation(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)
    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201

    response = client.post(
        f"/orders/{create_response.json()['id']}/buyer-confirmation",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_supplier_token}"
            )
        },
    )

    assert response.status_code == 403


def test_other_buyer_cannot_confirm_foreign_order(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)
    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201

    response = client.post(
        f"/orders/{create_response.json()['id']}/buyer-confirmation",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_other_buyer_token}"
            )
        },
    )

    assert response.status_code == 404


def test_buyer_cannot_use_supplier_rejection(client) -> None:
    rfq_id, offer_data = _create_rfq_and_offer(client)
    create_response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert create_response.status_code == 201

    response = client.post(
        f"/orders/{create_response.json()['id']}/supplier-rejection",
        json={"reason": "Тест авторизации"},
    )

    assert response.status_code == 403


def test_buyer_can_reject_order(client):
    rfq_id, offer_data = _create_rfq_and_offer(client)

    response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert response.status_code == 201
    order_id = response.json()["id"]

    response = client.post(
        f"/orders/{order_id}/buyer-rejection",
        json={"reason": "Изменились потребности покупателя"},
    )

    assert response.status_code == 200
    order = response.json()
    assert order["status"] == "rejected"
    assert order["rejected_by"] == "buyer"
    assert order["rejection_reason"] == "Изменились потребности покупателя"


def test_supplier_can_reject_after_buyer_confirmation(client):
    rfq_id, offer_data = _create_rfq_and_offer(client)

    response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert response.status_code == 201
    order_id = response.json()["id"]

    response = client.post(f"/orders/{order_id}/buyer-confirmation", )
    assert response.status_code == 200

    response = client.post(
        f"/orders/{order_id}/supplier-rejection",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_supplier_token}"
            )
        },
        json={"reason": "Не можем выполнить заказ в срок"},
    )
    assert response.status_code == 200
    order = response.json()
    assert order["status"] == "rejected"
    assert order["rejected_by"] == "supplier"
    assert order["rejection_reason"] == "Не можем выполнить заказ в срок"


def test_rejection_requires_non_empty_reason(client):
    rfq_id, offer_data = _create_rfq_and_offer(client)

    response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert response.status_code == 201
    order_id = response.json()["id"]

    response = client.post(
        f"/orders/{order_id}/buyer-rejection",
        json={"reason": "   "},
    )

    assert response.status_code == 422


def test_supplier_cannot_reject_before_buyer_confirmation(client):
    rfq_id, offer_data = _create_rfq_and_offer(client)

    response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert response.status_code == 201
    order_id = response.json()["id"]

    response = client.post(
        f"/orders/{order_id}/supplier-rejection",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_supplier_token}"
                )
            },
        json={"reason": "Отказ поставщика"},
    )

    assert response.status_code == 422

    order = client.app.state.order_repository.get(UUID(order_id))
    assert order is not None
    assert order.status.value == "pending_buyer_confirmation"


def test_rejected_order_cannot_be_rejected_again(client):
    rfq_id, offer_data = _create_rfq_and_offer(client)

    response = client.post(
        f"/rfqs/{rfq_id}/orders",
        json={"offer_id": offer_data["id"]},
    )
    assert response.status_code == 201
    order_id = response.json()["id"]

    first = client.post(
        f"/orders/{order_id}/buyer-rejection",
        json={"reason": "Первоначальный отказ"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/orders/{order_id}/buyer-rejection",
        json={"reason": "Повторный отказ"},
    )
    assert second.status_code == 422

    order = client.app.state.order_repository.get(UUID(order_id))
    assert order is not None
    assert order.rejection_reason == "Первоначальный отказ"



def test_buyer_can_read_own_rfq(client):
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

    rfq_id = create_response.json()["id"]
    response = client.get(f"/rfqs/{rfq_id}")

    assert response.status_code == 200
    assert response.json()["id"] == rfq_id
    assert (
        response.json()["buyer_organization_id"]
        == str(client.app.state.test_buyer_org_id)
    )


def test_buyer_cannot_read_another_organizations_rfq(client):
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
    rfq_id = create_response.json()["id"]

    response = client.get(
        f"/rfqs/{rfq_id}",
        headers={
            "Authorization": (
                "Bearer "
                f"{client.app.state.test_other_buyer_token}"
            )
        },
    )

    assert response.status_code == 404


def test_read_rfq_requires_authentication(client):
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
    rfq_id = create_response.json()["id"]

    response = client.get(
        f"/rfqs/{rfq_id}",
        headers={"Authorization": ""},
    )

    assert response.status_code == 401


def test_supplier_cannot_read_rfq(client):
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

    rfq_id = create_response.json()["id"]

    response = client.get(
        f"/rfqs/{rfq_id}",
        headers={
            "Authorization": (
                f"Bearer {client.app.state.test_supplier_token}"
            )
        },
    )

    assert response.status_code == 403


def test_read_unknown_rfq_returns_404(client):
    response = client.get(f"/rfqs/{uuid4()}")

    assert response.status_code == 404


def test_seller_workflow_requires_authentication(client) -> None:
    response = client.post(
        f"/rfqs/{uuid4()}/seller-offer-workflow",
        headers={"Authorization": ""},
        json={"supplier_ids": [str(uuid4())]},
    )

    assert response.status_code == 401


def test_seller_workflow_rejects_buyer_role(client) -> None:
    response = client.post(
        f"/rfqs/{uuid4()}/seller-offer-workflow",
        json={"supplier_ids": [str(uuid4())]},
    )

    assert response.status_code == 403
