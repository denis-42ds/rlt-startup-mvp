from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from rlt_startup.models.rfq import RFQ, RFQItem, RFQStatus


def valid_rfq_data() -> dict:
    return {
        "buyer_organization_id": str(uuid4()),
        "items": [
            {
                "product_name": "Кабель силовой",
                "quantity": "120",
                "unit": "м",
            }
        ],
    }


def test_create_rfq_with_minimal_data():
    rfq = RFQ.model_validate(valid_rfq_data())

    assert rfq.status == RFQStatus.DRAFT
    assert len(rfq.items) == 1
    assert rfq.items[0].quantity == Decimal("120")
    assert rfq.id is not None


def test_quantity_must_be_positive():
    with pytest.raises(ValidationError):
        RFQItem(
            product_name="Кабель",
            quantity=0,
            unit="м",
        )


def test_rfq_must_have_at_least_one_item():
    data = valid_rfq_data()
    data["items"] = []

    with pytest.raises(ValidationError):
        RFQ.model_validate(data)


def test_price_requires_currency():
    data = valid_rfq_data()
    data["max_unit_price"] = "150.00"

    with pytest.raises(ValidationError):
        RFQ.model_validate(data)


def test_price_with_currency_is_valid():
    data = valid_rfq_data()
    data["max_unit_price"] = "150.00"
    data["currency"] = "RUB"

    rfq = RFQ.model_validate(data)

    assert rfq.max_unit_price == Decimal("150.00")
    assert rfq.currency == "RUB"


def test_response_deadline_requires_timezone():
    data = valid_rfq_data()
    data["response_deadline"] = datetime(2026, 10, 15, 12, 0)

    with pytest.raises(ValidationError):
        RFQ.model_validate(data)


def test_submitted_status_can_be_parsed():
    data = valid_rfq_data()
    data["status"] = "rfq_submitted"

    rfq = RFQ.model_validate(data)

    assert rfq.status == RFQStatus.SUBMITTED

def test_rfq_items_have_distinct_ids_even_with_same_product_name():
    data = valid_rfq_data()
    data["items"].append({
        "product_name": "Кабель силовой",
        "quantity": "50",
        "unit": "м",
    })

    rfq = RFQ.model_validate(data)

    assert len(rfq.items) == 2
    assert rfq.items[0].product_name == rfq.items[1].product_name
    assert rfq.items[0].id != rfq.items[1].id
