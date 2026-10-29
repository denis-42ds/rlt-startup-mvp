from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from rlt_startup.models.offer import Offer, OfferItem
from rlt_startup.models.order import OrderParty, OrderStatus
from rlt_startup.models.rfq import RFQ, RFQItem
from rlt_startup.models.supplier_data import (
    InventorySnapshot,
    SupplierCatalogItem,
    SupplierPolicy,
)
from rlt_startup.services.catalog_policy import InMemoryCatalogPolicyAdapter
from rlt_startup.services.order_workflow import (
    OrderPolicyViolation,
    OrderWorkflowError,
    buyer_confirm_order,
    create_order_from_offer,
    reject_order,
    supplier_confirm_order,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def rfq_and_offer():
    buyer_id = uuid4()
    supplier_id = uuid4()
    catalog_item_id = uuid4()

    rfq = RFQ(
        buyer_organization_id=buyer_id,
        items=[
            RFQItem(
                product_name="Steel bolts",
                quantity=Decimal("2"),
                unit="pcs",
            )
        ],
        max_unit_price=Decimal("10"),
        currency="USD",
    )

    offer = Offer(
        rfq_id=rfq.id,
        supplier_organization_id=supplier_id,
        items=[
            OfferItem(
                rfq_item_id=rfq.items[0].id,
                catalog_item_id=catalog_item_id,
                offered_product_name="Steel bolts",
                unit="pcs",
                available_quantity=Decimal("10"),
                unit_price=Decimal("8"),
            )
        ],
        currency="USD",
        created_at=NOW,
        valid_until=NOW + timedelta(days=2),
    )
    return rfq, offer


@pytest.fixture
def order(rfq_and_offer):
    rfq, offer = rfq_and_offer
    return create_order_from_offer(rfq, offer, now=NOW)


@pytest.fixture
def supplier_adapter(rfq_and_offer):
    _, offer = rfq_and_offer
    supplier_id = offer.supplier_organization_id
    catalog_item = SupplierCatalogItem(
        id=offer.items[0].catalog_item_id,
        supplier_organization_id=supplier_id,
        product_name="Steel bolts",
        unit="pcs",
        unit_price=Decimal("8"),
        currency="USD",
    )
    return InMemoryCatalogPolicyAdapter(
        catalog_items=[catalog_item],
        inventory_snapshots=[
            InventorySnapshot(
                catalog_item_id=catalog_item.id,
                available_quantity=Decimal("10"),
                observed_at=NOW,
                source="test",
            )
        ],
        policies=[
            SupplierPolicy(
                supplier_organization_id=supplier_id,
                currency="USD",
                minimum_order_value=Decimal("10"),
            )
        ],
    )


def test_create_order_snapshots_commercial_terms(rfq_and_offer):
    rfq, offer = rfq_and_offer
    order = create_order_from_offer(rfq, offer, now=NOW)

    assert order.status == OrderStatus.PENDING_BUYER_CONFIRMATION
    assert order.rfq_id == rfq.id
    assert order.offer_id == offer.id
    assert order.buyer_organization_id == rfq.buyer_organization_id
    assert order.supplier_organization_id == offer.supplier_organization_id
    assert order.total_amount == Decimal("16")
    assert order.items[0].unit_price == Decimal("8")
    assert order.buyer_confirmed_at is None
    assert order.supplier_confirmed_at is None


def test_happy_path_requires_both_confirmations(order, supplier_adapter):
    buyer_time = NOW + timedelta(minutes=1)
    supplier_time = NOW + timedelta(minutes=2)

    pending_supplier = buyer_confirm_order(order, now=buyer_time)

    assert pending_supplier.status == OrderStatus.PENDING_SUPPLIER_CONFIRMATION
    assert pending_supplier.buyer_confirmed_at == buyer_time
    assert pending_supplier.supplier_confirmed_at is None

    confirmed = supplier_confirm_order(
        pending_supplier,
        supplier_adapter,
        now=supplier_time,
    )

    assert confirmed.status == OrderStatus.CONFIRMED
    assert confirmed.buyer_confirmed_at == buyer_time
    assert confirmed.supplier_confirmed_at == supplier_time


def test_supplier_cannot_confirm_before_buyer(order, supplier_adapter):
    with pytest.raises(OrderWorkflowError):
        supplier_confirm_order(order, supplier_adapter, now=NOW)


def test_buyer_cannot_confirm_twice(order):
    confirmed_by_buyer = buyer_confirm_order(
        order,
        now=NOW + timedelta(minutes=1),
    )

    with pytest.raises(OrderWorkflowError):
        buyer_confirm_order(
            confirmed_by_buyer,
            now=NOW + timedelta(minutes=2),
        )


def test_expired_offer_cannot_create_order(rfq_and_offer):
    rfq, offer = rfq_and_offer
    expired_at = offer.valid_until + timedelta(seconds=1)

    with pytest.raises(OrderWorkflowError, match="просроченному"):
        create_order_from_offer(rfq, offer, now=expired_at)


def test_price_above_buyer_limit_is_rejected(rfq_and_offer):
    rfq, offer = rfq_and_offer
    offer.items[0].unit_price = Decimal("11")

    with pytest.raises(OrderWorkflowError, match="предельной"):
        create_order_from_offer(rfq, offer, now=NOW)


def test_buyer_can_reject_before_confirmation(order):
    rejected = reject_order(
        order,
        OrderParty.BUYER,
        "Условия больше не актуальны",
        now=NOW + timedelta(minutes=1),
    )

    assert rejected.status == OrderStatus.REJECTED
    assert rejected.rejected_by == OrderParty.BUYER
    assert rejected.rejection_reason == "Условия больше не актуальны"


def test_supplier_can_reject_after_buyer_confirmation(order):
    pending_supplier = buyer_confirm_order(
        order,
        now=NOW + timedelta(minutes=1),
    )
    rejected = reject_order(
        pending_supplier,
        OrderParty.SUPPLIER,
        "Произошло изменение доступного остатка",
        now=NOW + timedelta(minutes=2),
    )

    assert rejected.status == OrderStatus.REJECTED
    assert rejected.rejected_by == OrderParty.SUPPLIER


def test_supplier_rejection_is_not_allowed_before_buyer_confirmation(order):
    with pytest.raises(OrderWorkflowError):
        reject_order(order, OrderParty.SUPPLIER, "Отказ", now=NOW)


def test_insufficient_inventory_does_not_confirm_order(order, supplier_adapter):
    pending_supplier = buyer_confirm_order(
        order,
        now=NOW + timedelta(minutes=1),
    )
    item = supplier_adapter.list_catalog_items(order.supplier_organization_id)[0]

    adapter_with_insufficient_stock = InMemoryCatalogPolicyAdapter(
        catalog_items=[item],
        inventory_snapshots=[
            InventorySnapshot(
                catalog_item_id=item.id,
                available_quantity=Decimal("1"),
                observed_at=NOW + timedelta(minutes=2),
                source="test",
            )
        ],
        policies=[
            SupplierPolicy(
                supplier_organization_id=order.supplier_organization_id,
                currency="USD",
                minimum_order_value=Decimal("10"),
            )
        ],
    )

    with pytest.raises(OrderPolicyViolation, match="Недостаточно товара"):
        supplier_confirm_order(
            pending_supplier,
            adapter_with_insufficient_stock,
            now=NOW + timedelta(minutes=2),
        )

    assert pending_supplier.status == OrderStatus.PENDING_SUPPLIER_CONFIRMATION
    assert pending_supplier.supplier_confirmed_at is None


def test_missing_catalog_item_does_not_confirm_order(order, supplier_adapter):
    pending_supplier = buyer_confirm_order(
        order,
        now=NOW + timedelta(minutes=1),
    )

    adapter_without_order_item = InMemoryCatalogPolicyAdapter(
        catalog_items=[],
        inventory_snapshots=[],
        policies=[
            SupplierPolicy(
                supplier_organization_id=order.supplier_organization_id,
                currency="USD",
                minimum_order_value=Decimal("10"),
            )
        ],
    )

    with pytest.raises(
        OrderPolicyViolation,
        match="Товар отсутствует в каталоге поставщика",
    ):
        supplier_confirm_order(
            pending_supplier,
            adapter_without_order_item,
            now=NOW + timedelta(minutes=2),
        )

    assert pending_supplier.status == OrderStatus.PENDING_SUPPLIER_CONFIRMATION
    assert pending_supplier.supplier_confirmed_at is None

def test_stale_inventory_does_not_confirm_order(order, supplier_adapter):
    pending_supplier = buyer_confirm_order(
        order,
        now=NOW + timedelta(minutes=1),
    )
    item = supplier_adapter.list_catalog_items(order.supplier_organization_id)[0]

    stale_adapter = InMemoryCatalogPolicyAdapter(
        catalog_items=[item],
        inventory_snapshots=[
            InventorySnapshot(
                catalog_item_id=item.id,
                available_quantity=Decimal("10"),
                observed_at=NOW,
                source="test",
            )
        ],
        policies=[
            SupplierPolicy(
                supplier_organization_id=order.supplier_organization_id,
                currency="USD",
                minimum_order_value=Decimal("10"),
            )
        ],
    )

    with pytest.raises(OrderPolicyViolation, match="устарели"):
        supplier_confirm_order(
            pending_supplier,
            stale_adapter,
            now=NOW + timedelta(hours=25),
        )


def test_missing_supplier_policy_blocks_confirmation(order, supplier_adapter):
    pending_supplier = buyer_confirm_order(
        order,
        now=NOW + timedelta(minutes=1),
    )
    items = supplier_adapter.list_catalog_items(order.supplier_organization_id)
    snapshots = [
        InventorySnapshot(
            catalog_item_id=items[0].id,
            available_quantity=Decimal("10"),
            observed_at=NOW,
            source="test",
        )
    ]
    adapter_without_policy = InMemoryCatalogPolicyAdapter(
        catalog_items=items,
        inventory_snapshots=snapshots,
    )

    with pytest.raises(OrderPolicyViolation, match="политика"):
        supplier_confirm_order(
            pending_supplier,
            adapter_without_policy,
            now=NOW + timedelta(minutes=2),
        )


def test_changed_catalog_price_does_not_change_agreed_order_price(
    order,
    supplier_adapter,
):
    pending_supplier = buyer_confirm_order(
        order,
        now=NOW + timedelta(minutes=1),
    )
    old_item = supplier_adapter.list_catalog_items(order.supplier_organization_id)[0]

    updated_item = SupplierCatalogItem(
        id=old_item.id,
        supplier_organization_id=old_item.supplier_organization_id,
        product_name=old_item.product_name,
        unit=old_item.unit,
        unit_price=Decimal("9"),
        currency="USD",
    )
    adapter_with_changed_price = InMemoryCatalogPolicyAdapter(
        catalog_items=[updated_item],
        inventory_snapshots=[
            InventorySnapshot(
                catalog_item_id=updated_item.id,
                available_quantity=Decimal("10"),
                observed_at=NOW + timedelta(minutes=2),
                source="test",
            )
        ],
        policies=[
            SupplierPolicy(
                supplier_organization_id=order.supplier_organization_id,
                currency="USD",
                minimum_order_value=Decimal("10"),
            )
        ],
    )

    confirmed = supplier_confirm_order(
        pending_supplier,
        adapter_with_changed_price,
        now=NOW + timedelta(minutes=2),
    )

    assert confirmed.status == OrderStatus.CONFIRMED
    assert confirmed.items[0].unit_price == Decimal("8")
    assert confirmed.total_amount == Decimal("16")


def test_empty_rejection_reason_is_rejected(order):
    with pytest.raises(OrderWorkflowError, match="причину"):
        reject_order(order, OrderParty.BUYER, "   ", now=NOW)

