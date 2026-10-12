from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from rlt_startup.models.offer import Offer
from rlt_startup.models.rfq import RFQ
from rlt_startup.services.offer_validation import (
    OfferValidationError,
    validate_offer_against_rfq,
)


def make_rfq() -> RFQ:
    return RFQ.model_validate({
        "buyer_organization_id": str(uuid4()),
        "items": [
            {
                "product_name": "Кабель силовой",
                "quantity": "120",
                "unit": "м",
            },
            {
                "product_name": "Автоматический выключатель",
                "quantity": "10",
                "unit": "шт",
            },
        ],
    })


def make_offer(rfq: RFQ) -> Offer:
    return Offer.model_validate({
        "rfq_id": str(rfq.id),
        "supplier_organization_id": str(uuid4()),
        "items": [
            {
                "rfq_item_id": str(rfq.items[0].id),
                "catalog_item_id": str(uuid4()),
                "offered_product_name": "Кабель силовой",
                "unit": "м",
                "available_quantity": "500",
                "unit_price": "145.50",
            }
        ],
        "currency": "RUB",
        "valid_until": (
            datetime.now(timezone.utc) + timedelta(days=7)
        ).isoformat(),
    })


def test_valid_offer_matches_rfq():
    rfq = make_rfq()
    offer = make_offer(rfq)

    assert validate_offer_against_rfq(offer, rfq) is None


def test_offer_must_reference_correct_rfq():
    rfq = make_rfq()
    offer = make_offer(rfq)
    offer.rfq_id = uuid4()

    with pytest.raises(
        OfferValidationError,
        match="offer.rfq_id",
    ):
        validate_offer_against_rfq(offer, rfq)


def test_offer_cannot_reference_unknown_rfq_item():
    rfq = make_rfq()
    offer = make_offer(rfq)
    offer.items[0].rfq_item_id = uuid4()

    with pytest.raises(
        OfferValidationError,
        match="do not belong to the RFQ",
    ):
        validate_offer_against_rfq(offer, rfq)


def test_offer_cannot_repeat_rfq_item():
    rfq = make_rfq()
    offer = make_offer(rfq)
    duplicate_item = offer.items[0].model_copy(deep=True)
    duplicate_item.id = uuid4()
    offer.items.append(duplicate_item)

    with pytest.raises(
        OfferValidationError,
        match="more than once",
    ):
        validate_offer_against_rfq(offer, rfq)

