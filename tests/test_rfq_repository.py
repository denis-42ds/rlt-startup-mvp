from uuid import uuid4

import pytest

from rlt_startup.models.rfq import RFQ, RFQItem
from rlt_startup.repositories.rfq_repository import (
    InMemoryRFQRepository,
    RFQAlreadyExistsError,
)


def make_rfq() -> RFQ:
    return RFQ(
        buyer_organization_id=uuid4(),
        items=[
            RFQItem(
                product_name="Стальной лист",
                quantity="100",
                unit="кг",
            )
        ],
    )


def test_add_and_get_rfq() -> None:
    repository = InMemoryRFQRepository()
    rfq = make_rfq()

    repository.add(rfq)

    result = repository.get(rfq.id)
    assert result is not None
    assert result.id == rfq.id
    assert result.items[0].product_name == "Стальной лист"


def test_get_unknown_rfq_returns_none() -> None:
    repository = InMemoryRFQRepository()

    assert repository.get(uuid4()) is None


def test_duplicate_rfq_id_is_rejected() -> None:
    repository = InMemoryRFQRepository()
    rfq = make_rfq()

    repository.add(rfq)

    with pytest.raises(RFQAlreadyExistsError):
        repository.add(rfq)
