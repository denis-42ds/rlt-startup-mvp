from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from rlt_startup.models.supplier_data import (
    InventorySnapshot,
    SupplierCatalogItem,
    SupplierPolicy,
)
from rlt_startup.services.catalog_policy import (
    InMemoryCatalogPolicyAdapter,
)


def make_catalog_item(supplier_id=None, item_id=None):
    return SupplierCatalogItem(
        id=item_id or uuid4(),
        supplier_organization_id=supplier_id or uuid4(),
        product_name="Кабель силовой",
        unit="м",
        unit_price="145.50",
        currency="RUB",
    )


def test_catalog_is_filtered_by_supplier():
    supplier_a = uuid4()
    supplier_b = uuid4()
    item_a = make_catalog_item(supplier_id=supplier_a)
    item_b = make_catalog_item(supplier_id=supplier_b)

    adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[item_a, item_b],
    )

    result = adapter.list_catalog_items(supplier_a)

    assert [item.id for item in result] == [item_a.id]


def test_missing_inventory_is_not_treated_as_zero():
    item = make_catalog_item()
    adapter = InMemoryCatalogPolicyAdapter(catalog_items=[item])

    assert adapter.get_inventory(item.id) is None


def test_unknown_quantity_is_preserved():
    item = make_catalog_item()
    snapshot = InventorySnapshot(
        catalog_item_id=item.id,
        available_quantity=None,
        source="demo",
    )
    adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[item],
        inventory_snapshots=[snapshot],
    )

    result = adapter.get_inventory(item.id)

    assert result is not None
    assert result.available_quantity is None


def test_known_inventory_quantity_is_preserved():
    item = make_catalog_item()
    snapshot = InventorySnapshot(
        catalog_item_id=item.id,
        available_quantity="250",
        source="demo",
    )
    adapter = InMemoryCatalogPolicyAdapter(
        inventory_snapshots=[snapshot],
    )

    result = adapter.get_inventory(item.id)

    assert result is not None
    assert result.available_quantity == Decimal("250")


def test_supplier_policy_can_be_retrieved():
    supplier_id = uuid4()
    policy = SupplierPolicy(
        supplier_organization_id=supplier_id,
        currency="RUB",
        minimum_order_value="5000",
        max_offer_validity_days=10,
    )
    adapter = InMemoryCatalogPolicyAdapter(policies=[policy])

    result = adapter.get_policy(supplier_id)

    assert result is not None
    assert result.minimum_order_value == Decimal("5000")
    assert result.max_offer_validity_days == 10


def test_missing_policy_returns_none():
    adapter = InMemoryCatalogPolicyAdapter()

    assert adapter.get_policy(uuid4()) is None


def test_duplicate_catalog_item_id_is_rejected():
    item = make_catalog_item()

    with pytest.raises(ValueError, match="Duplicate catalog item ID"):
        InMemoryCatalogPolicyAdapter(catalog_items=[item, item])


def test_duplicate_inventory_snapshot_is_rejected():
    item = make_catalog_item()
    first = InventorySnapshot(
        catalog_item_id=item.id,
        available_quantity="10",
        source="demo",
    )
    second = InventorySnapshot(
        catalog_item_id=item.id,
        available_quantity="20",
        source="demo",
    )

    with pytest.raises(ValueError, match="Duplicate inventory snapshot"):
        InMemoryCatalogPolicyAdapter(
            inventory_snapshots=[first, second],
        )


def test_inventory_timestamp_requires_timezone():
    with pytest.raises(ValidationError):
        InventorySnapshot(
            catalog_item_id=uuid4(),
            available_quantity="10",
            observed_at=datetime(2026, 10, 11, 12, 0),
            source="demo",
        )


def test_catalog_rejects_non_positive_price():
    with pytest.raises(ValidationError):
        make_catalog_item().__class__(
            supplier_organization_id=uuid4(),
            product_name="Кабель",
            unit="м",
            unit_price="0",
            currency="RUB",
        )

