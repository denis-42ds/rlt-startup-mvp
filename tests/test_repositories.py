from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from rlt_startup.models.offer import Offer, OfferItem
from rlt_startup.models.order import Order
from rlt_startup.models.rfq import RFQ, RFQItem
from rlt_startup.services.order_workflow import create_order_from_offer
from rlt_startup.repositories.offer_repository import (
    InMemoryOfferRepository,
    OfferAlreadyExistsError,
)
from rlt_startup.repositories.order_repository import (
    InMemoryOrderRepository,
    OrderAlreadyExistsError,
)


NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def make_offer() -> Offer:
    rfq = RFQ(
        buyer_organization_id=uuid4(),
        items=[
            RFQItem(
                product_name="Steel bolts",
                quantity=Decimal("2"),
                unit="pcs",
            )
        ],
        currency="USD",
    )

    return Offer(
        rfq_id=rfq.id,
        supplier_organization_id=uuid4(),
        items=[
            OfferItem(
                rfq_item_id=rfq.items[0].id,
                catalog_item_id=uuid4(),
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


def make_order() -> Order:
    offer = make_offer()

    # Создаём RFQ, соответствующий предложению.
    rfq = RFQ(
        id=offer.rfq_id,
        buyer_organization_id=uuid4(),
        items=[
            RFQItem(
                id=offer.items[0].rfq_item_id,
                product_name="Steel bolts",
                quantity=Decimal("2"),
                unit="pcs",
            )
        ],
        currency="USD",
    )

    return create_order_from_offer(rfq, offer, now=NOW)


def test_offer_repository_returns_independent_copies() -> None:
    repository = InMemoryOfferRepository()
    offer = make_offer()
    repository.add(offer)

    loaded = repository.get(offer.id)

    assert loaded == offer
    assert loaded is not offer

    assert loaded is not None
    loaded.items.clear()

    reloaded = repository.get(offer.id)
    assert reloaded is not None
    assert len(reloaded.items) == 1


def test_offer_repository_rejects_duplicate_id() -> None:
    repository = InMemoryOfferRepository()
    offer = make_offer()
    repository.add(offer)

    with pytest.raises(OfferAlreadyExistsError):
        repository.add(offer)

    assert repository.get(offer.id) == offer


def test_offer_repository_returns_none_for_unknown_id() -> None:
    repository = InMemoryOfferRepository()

    assert repository.get(uuid4()) is None


def test_order_repository_returns_independent_copies() -> None:
    repository = InMemoryOrderRepository()
    order = make_order()
    repository.add(order)

    loaded = repository.get(order.id)

    assert loaded == order
    assert loaded is not order

    assert loaded is not None
    loaded.items.clear()

    reloaded = repository.get(order.id)
    assert reloaded is not None
    assert len(reloaded.items) == 1


def test_order_repository_rejects_duplicate_id() -> None:
    repository = InMemoryOrderRepository()
    order = make_order()
    repository.add(order)

    with pytest.raises(OrderAlreadyExistsError):
        repository.add(order)

    assert repository.get(order.id) == order


def test_order_repository_returns_none_for_unknown_id() -> None:
    repository = InMemoryOrderRepository()

    assert repository.get(uuid4()) is None
