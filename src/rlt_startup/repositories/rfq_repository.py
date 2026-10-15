from typing import Protocol
from uuid import UUID

from rlt_startup.models.rfq import RFQ


class RFQAlreadyExistsError(ValueError):
    """RFQ with this ID already exists."""


class RFQRepository(Protocol):
    def add(self, rfq: RFQ) -> None:
        """Save an RFQ. Raise RFQAlreadyExistsError for duplicate IDs."""

    def get(self, rfq_id: UUID) -> RFQ | None:
        """Return an RFQ by ID, or None if it does not exist."""


class InMemoryRFQRepository:
    def __init__(self) -> None:
        self._rfqs: dict[UUID, RFQ] = {}

    def add(self, rfq: RFQ) -> None:
        if rfq.id in self._rfqs:
            raise RFQAlreadyExistsError(
                f"RFQ already exists: {rfq.id}"
            )

        self._rfqs[rfq.id] = rfq.model_copy(deep=True)

    def get(self, rfq_id: UUID) -> RFQ | None:
        rfq = self._rfqs.get(rfq_id)
        if rfq is None:
            return None

        return rfq.model_copy(deep=True)
