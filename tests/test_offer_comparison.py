from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from rlt_startup.models.offer import Offer
from rlt_startup.models.rfq import RFQ
from rlt_startup.services.offer_comparison import (
    compare_offer,
    compare_offers,
)


def make_rfq() -> RFQ:
    return RFQ.model_validate({
        "buyer_organization_id": str(uuid4()),
        "items": [
            {
                "product_name": "Кабель",
                "quantity": "120",
                "unit": "м",
            },
            {
                "product_name": "Автомат",
                "quantity": "10",
                "unit": "шт",
            },
        ],
    })


def make_offer(
    rfq: RFQ,
    cable_price: str = "10",
    automatic_price: str = "100",
) -> Offer:
    return Offer.model_validate({
        "rfq_id": str(rfq.id),
        "supplier_organization_id": str(uuid4()),
        "items": [
            {
                "rfq_item_id": str(rfq.items[0].id),
                "catalog_item_id": str(uuid4()),
                "offered_product_name": "Кабель",
                "unit": "м",
                "available_quantity": "200",
                "unit_price": cable_price,
            },
            {
                "rfq_item_id": str(rfq.items[1].id),
                "catalog_item_id": str(uuid4()),
                "offered_product_name": "Автомат",
                "unit": "шт",
                "available_quantity": "20",
                "unit_price": automatic_price,
            },
        ],
        "currency": "RUB",
        "valid_until": (
            datetime.now(timezone.utc) + timedelta(days=3)
        ).isoformat(),
    })


def test_comparison_calculates_total_price():
    rfq = make_rfq()
    result = compare_offer(make_offer(rfq), rfq)

    assert result.eligible is True
    assert result.total_price == Decimal("2200")
    assert result.currency == "RUB"


def test_comparison_marks_insufficient_quantity():
    rfq = make_rfq()
    offer = make_offer(rfq)
    offer.items[0].available_quantity = Decimal("50")

    result = compare_offer(offer, rfq)

    assert result.eligible is False
    assert result.total_price is None
    assert any("Недостаточно количества" in r for r in result.reasons)


def test_comparison_marks_unit_mismatch():
    rfq = make_rfq()
    offer = make_offer(rfq)
    offer.items[0].unit = "кг"

    result = compare_offer(offer, rfq)

    assert result.eligible is False
    assert any("единиц измерения" in r for r in result.reasons)


def test_comparison_marks_missing_rfq_position():
    rfq = make_rfq()
    offer = make_offer(rfq)
    offer.items.pop()

    result = compare_offer(offer, rfq)

    assert result.eligible is False
    assert any("Нет предложения" in r for r in result.reasons)


def test_comparison_marks_expired_offer():
    rfq = make_rfq()
    offer = make_offer(rfq)
    offer.valid_until = datetime.now(timezone.utc) - timedelta(hours=1)

    result = compare_offer(offer, rfq)

    assert result.eligible is False
    assert result.total_price is None
    assert "Предложение просрочено" in result.reasons


def test_comparison_rejects_offer_for_another_rfq():
    rfq = make_rfq()
    offer = make_offer(rfq)
    offer.rfq_id = uuid4()

    with pytest.raises(ValueError, match="offer.rfq_id"):
        compare_offer(offer, rfq)


def test_offers_are_sorted_by_total_price():
    rfq = make_rfq()
    expensive = make_offer(rfq, "12", "120")
    cheaper = make_offer(rfq, "10", "100")

    results = compare_offers([expensive, cheaper], rfq)

    assert results[0].total_price == Decimal("2200")
    assert results[1].total_price == Decimal("2640")

