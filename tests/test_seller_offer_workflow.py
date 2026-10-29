from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from rlt_startup.models.rfq import RFQ, RFQItem
from rlt_startup.models.supplier_data import (
    InventorySnapshot,
    SupplierCatalogItem,
    SupplierPolicy,
)
from rlt_startup.services.catalog_policy import InMemoryCatalogPolicyAdapter
from rlt_startup.services.seller_offer_workflow import (
    run_seller_offer_workflow,
)

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def make_rfq():
    return RFQ(
        buyer_organization_id=uuid4(),
        items=[
            RFQItem(
                product_name="Кабель силовой",
                quantity="100",
                unit="м",
            )
        ],
        currency="RUB",
        max_unit_price="200",
    )


def make_adapter(supplier_id, price, *, quantity="250"):
    item = SupplierCatalogItem(
        supplier_organization_id=supplier_id,
        product_name="Кабель силовой",
        unit="м",
        unit_price=str(price),
        currency="RUB",
    )
    inventory = InventorySnapshot(
        catalog_item_id=item.id,
        available_quantity=quantity,
        observed_at=NOW - timedelta(minutes=5),
        source="integration-test",
    )
    policy = SupplierPolicy(
        supplier_organization_id=supplier_id,
        currency="RUB",
        minimum_order_value="0",
        max_offer_validity_days=7,
    )
    return InMemoryCatalogPolicyAdapter(
        catalog_items=[item],
        inventory_snapshots=[inventory],
        policies=[policy],
    )


def test_workflow_prepares_and_ranks_supplier_offers():
    rfq = make_rfq()
    supplier_a = uuid4()
    supplier_b = uuid4()

    result = run_seller_offer_workflow(
        rfq,
        [supplier_a, supplier_b],
        {
            supplier_a: make_adapter(supplier_a, "160"),
            supplier_b: make_adapter(supplier_b, "145.50"),
        },
        now=NOW,
    )

    assert result.preparations[supplier_a].ready
    assert result.preparations[supplier_b].ready
    assert len(result.comparisons) == 2

    assert all(item.eligible for item in result.comparisons)
    assert result.comparisons[0].supplier_organization_id == str(supplier_b)
    assert result.comparisons[0].total_price == Decimal("14550.00")
    assert result.comparisons[1].supplier_organization_id == str(supplier_a)
    assert result.comparisons[1].total_price == Decimal("16000")


def test_supplier_with_insufficient_inventory_is_not_compared():
    rfq = make_rfq()
    supplier_a = uuid4()
    supplier_b = uuid4()

    result = run_seller_offer_workflow(
        rfq,
        [supplier_a, supplier_b],
        {
            supplier_a: make_adapter(supplier_a, "140", quantity="50"),
            supplier_b: make_adapter(supplier_b, "160"),
        },
        now=NOW,
    )

    assert not result.preparations[supplier_a].ready
    assert result.preparations[supplier_a].offer is None
    assert result.preparations[supplier_b].ready

    assert len(result.comparisons) == 1
    assert result.comparisons[0].supplier_organization_id == str(supplier_b)


def test_missing_adapter_is_reported_without_stopping_workflow():
    rfq = make_rfq()
    supplier_a = uuid4()
    supplier_b = uuid4()

    result = run_seller_offer_workflow(
        rfq,
        [supplier_a, supplier_b],
        {supplier_b: make_adapter(supplier_b, "160")},
        now=NOW,
    )

    assert not result.preparations[supplier_a].ready
    assert any(
        "адаптер" in reason
        for reason in result.preparations[supplier_a].reasons
    )
    assert result.preparations[supplier_b].ready
    assert len(result.comparisons) == 1


def test_duplicate_supplier_ids_are_rejected():
    supplier_id = uuid4()

    try:
        run_seller_offer_workflow(
            make_rfq(),
            [supplier_id, supplier_id],
            {},
            now=NOW,
        )
    except ValueError as exc:
        assert "duplicates" in str(exc)
    else:
        raise AssertionError("Expected duplicate supplier IDs to be rejected")

