from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from rlt_startup.models.rfq import RFQ, RFQItem
from rlt_startup.models.supplier_data import (
    InventorySnapshot,
    SupplierCatalogItem,
    SupplierPolicy,
)
from rlt_startup.services.catalog_policy import InMemoryCatalogPolicyAdapter
from rlt_startup.services.seller_offer_preparation import prepare_seller_offer


NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def scenario():
    supplier_id = uuid4()
    buyer_id = uuid4()

    requested_item = RFQItem(
        product_name="Кабель силовой",
        quantity="100",
        unit="м",
    )
    rfq = RFQ(
        buyer_organization_id=buyer_id,
        items=[requested_item],
        currency="RUB",
        max_unit_price="200",
    )

    catalog_item = SupplierCatalogItem(
        supplier_organization_id=supplier_id,
        product_name="  КАБЕЛЬ   силовой ",
        unit="м",
        unit_price="145.50",
        currency="RUB",
    )
    inventory = InventorySnapshot(
        catalog_item_id=catalog_item.id,
        available_quantity="250",
        observed_at=NOW - timedelta(hours=1),
        source="demo",
    )
    policy = SupplierPolicy(
        supplier_organization_id=supplier_id,
        currency="RUB",
        minimum_order_value="5000",
        max_offer_validity_days=10,
    )
    adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[catalog_item],
        inventory_snapshots=[inventory],
        policies=[policy],
    )

    return supplier_id, rfq, catalog_item, adapter


def test_prepares_offer_when_all_checks_pass(scenario):
    supplier_id, rfq, _, adapter = scenario

    result = prepare_seller_offer(
        rfq, supplier_id, adapter, now=NOW
    )

    assert result.ready is True
    assert result.reasons == []
    assert result.offer is not None
    assert result.offer.currency == "RUB"
    assert result.offer.items[0].rfq_item_id == rfq.items[0].id
    assert result.offer.items[0].available_quantity == Decimal("250")
    assert result.offer.items[0].unit_price == Decimal("145.50")
    assert result.offer.valid_until == NOW + timedelta(days=10)


def test_missing_policy_prevents_offer(scenario):
    supplier_id, rfq, _, _ = scenario
    adapter = InMemoryCatalogPolicyAdapter()

    result = prepare_seller_offer(rfq, supplier_id, adapter, now=NOW)

    assert not result.ready
    assert result.offer is None
    assert any("политика" in reason for reason in result.reasons)


def test_missing_inventory_prevents_offer(scenario):
    supplier_id, rfq, catalog_item, _ = scenario
    adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[catalog_item],
        policies=[
            SupplierPolicy(
                supplier_organization_id=supplier_id,
                currency="RUB",
                minimum_order_value="0",
            )
        ],
    )

    result = prepare_seller_offer(rfq, supplier_id, adapter, now=NOW)

    assert not result.ready
    assert result.offer is None
    assert any("Нет данных об остатке" in r for r in result.reasons)


def test_unknown_inventory_quantity_prevents_offer(scenario):
    supplier_id, rfq, catalog_item, _ = scenario
    adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[catalog_item],
        inventory_snapshots=[
            InventorySnapshot(
                catalog_item_id=catalog_item.id,
                available_quantity=None,
                observed_at=NOW,
                source="demo",
            )
        ],
        policies=[
            SupplierPolicy(
                supplier_organization_id=supplier_id,
                currency="RUB",
            )
        ],
    )

    result = prepare_seller_offer(rfq, supplier_id, adapter, now=NOW)

    assert not result.ready
    assert result.offer is None
    assert any("неизвестно" in r for r in result.reasons)


def test_insufficient_inventory_prevents_offer(scenario):
    supplier_id, rfq, catalog_item, _ = scenario
    adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[catalog_item],
        inventory_snapshots=[
            InventorySnapshot(
                catalog_item_id=catalog_item.id,
                available_quantity="50",
                observed_at=NOW,
                source="demo",
            )
        ],
        policies=[
            SupplierPolicy(
                supplier_organization_id=supplier_id,
                currency="RUB",
            )
        ],
    )

    result = prepare_seller_offer(rfq, supplier_id, adapter, now=NOW)

    assert not result.ready
    assert result.offer is None
    assert any("Недостаточно" in r for r in result.reasons)


def test_stale_inventory_prevents_offer(scenario):
    supplier_id, rfq, catalog_item, _ = scenario
    adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[catalog_item],
        inventory_snapshots=[
            InventorySnapshot(
                catalog_item_id=catalog_item.id,
                available_quantity="250",
                observed_at=NOW - timedelta(hours=25),
                source="demo",
            )
        ],
        policies=[
            SupplierPolicy(
                supplier_organization_id=supplier_id,
                currency="RUB",
            )
        ],
    )

    result = prepare_seller_offer(rfq, supplier_id, adapter, now=NOW)

    assert not result.ready
    assert result.offer is None
    assert any("устарели" in r for r in result.reasons)


def test_price_above_buyer_limit_prevents_offer(scenario):
    supplier_id, rfq, catalog_item, _ = scenario
    expensive_item = catalog_item.model_copy(
        update={"unit_price": Decimal("250")}
    )
    adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[expensive_item],
        inventory_snapshots=[
            InventorySnapshot(
                catalog_item_id=expensive_item.id,
                available_quantity="250",
                observed_at=NOW,
                source="demo",
            )
        ],
        policies=[
            SupplierPolicy(
                supplier_organization_id=supplier_id,
                currency="RUB",
            )
        ],
    )

    result = prepare_seller_offer(rfq, supplier_id, adapter, now=NOW)

    assert not result.ready
    assert result.offer is None
    assert any("предельной цены" in r for r in result.reasons)

def test_currency_mismatch_prevents_offer(scenario):
    supplier_id, rfq, _, adapter = scenario
    rfq.currency = "USD"

    result = prepare_seller_offer(rfq, supplier_id, adapter, now=NOW)

    assert not result.ready
    assert result.offer is None
    assert any("Валюта" in r for r in result.reasons)


def test_minimum_order_value_is_enforced(scenario):
    supplier_id, rfq, catalog_item, _ = scenario
    policy = SupplierPolicy(
        supplier_organization_id=supplier_id,
        currency="RUB",
        minimum_order_value="20000",
    )
    adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[catalog_item],
        inventory_snapshots=[
            InventorySnapshot(
                catalog_item_id=catalog_item.id,
                available_quantity="250",
                observed_at=NOW,
                source="demo",
            )
        ],
        policies=[policy],
    )

    result = prepare_seller_offer(rfq, supplier_id, adapter, now=NOW)

    assert not result.ready
    assert result.offer is None
    assert any("минимальной суммы" in r for r in result.reasons)

def test_ambiguous_catalog_match_prevents_offer(scenario):
    supplier_id, rfq, catalog_item, _ = scenario
    duplicate = catalog_item.model_copy(
        update={"id": uuid4()}
    )
    adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[catalog_item, duplicate],
        policies=[
            SupplierPolicy(
                supplier_organization_id=supplier_id,
                currency="RUB",
            )
        ],
    )

    result = prepare_seller_offer(rfq, supplier_id, adapter, now=NOW)

    assert not result.ready
    assert result.offer is None
    assert any("Неоднозначное" in r for r in result.reasons)


def test_naive_now_is_rejected(scenario):
    supplier_id, rfq, _, adapter = scenario

    with pytest.raises(ValueError, match="timezone"):
        prepare_seller_offer(
            rfq,
            supplier_id,
            adapter,
            now=datetime(2026, 10, 11, 12, 0),
        )

