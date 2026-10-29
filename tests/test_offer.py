
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from rlt_startup.models.offer import Offer, OfferItem


def valid_offer_data() -> dict:
    return {
        "rfq_id": str(uuid4()),
        "supplier_organization_id": str(uuid4()),
        "items": [
            {
                "rfq_item_id": str(uuid4()),
                "catalog_item_id": str(uuid4()),  # добавлено 12.10.26 13:33
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
        "delivery_date": "2026-11-15",
    }


def test_create_offer_with_valid_data():
    offer = Offer.model_validate(valid_offer_data())

    assert offer.version == 1
    assert offer.currency == "RUB"
    assert len(offer.items) == 1
    assert offer.items[0].unit_price == Decimal("145.50")
    assert offer.items[0].available_quantity == Decimal("500")


def test_offer_item_has_its_own_id():
    item = OfferItem(
        rfq_item_id=uuid4(),
        catalog_item_id=uuid4(),  # добавлено 12.10.26 13:33
        offered_product_name="Кабель",
        unit="м",
        available_quantity="100",
        unit_price="50.25",
    )

    assert item.id != item.rfq_item_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit_price", "0"),
        ("unit_price", "-1"),
        ("available_quantity", "0"),
        ("available_quantity", "-10"),
    ],
)
def test_offer_item_rejects_non_positive_values(field, value):
    data = {
        "rfq_item_id": uuid4(),
        "catalog_item_id": uuid4(),  # добавлено 12.10.26 13:33
        "offered_product_name": "Кабель",
        "unit": "м",
        "available_quantity": "100",
        "unit_price": "50",
    }
    data[field] = value

    with pytest.raises(ValidationError):
        OfferItem.model_validate(data)


def test_offer_requires_at_least_one_item():
    data = valid_offer_data()
    data["items"] = []

    with pytest.raises(ValidationError):
        Offer.model_validate(data)


def test_offer_requires_valid_currency():
    data = valid_offer_data()
    data["currency"] = "руб"

    with pytest.raises(ValidationError):
        Offer.model_validate(data)


def test_offer_requires_timezone_in_valid_until():
    data = valid_offer_data()
    data["valid_until"] = datetime.now() + timedelta(days=1)

    with pytest.raises(ValidationError):
        Offer.model_validate(data)


def test_offer_expiry_must_be_after_creation():
    data = valid_offer_data()
    data["created_at"] = "2026-10-10T12:00:00+00:00"
    data["valid_until"] = "2026-10-10T11:00:00+00:00"

    with pytest.raises(ValidationError):
        Offer.model_validate(data)


def test_offer_version_must_be_positive():
    data = valid_offer_data()
    data["version"] = 0

    with pytest.raises(ValidationError):
        Offer.model_validate(data)


def test_offer_serializes_to_json():
    offer = Offer.model_validate(valid_offer_data())

    data = offer.model_dump(mode="json")

    assert data["id"] == str(offer.id)
    assert data["items"][0]["rfq_item_id"] == str(
        offer.items[0].rfq_item_id
    )
    assert data["items"][0]["unit_price"] == "145.50"

