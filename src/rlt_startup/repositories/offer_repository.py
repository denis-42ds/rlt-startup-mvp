from typing import Protocol
from uuid import UUID

from rlt_startup.models.offer import Offer


class OfferAlreadyExistsError(ValueError):
    """Offer with this ID already exists."""


class OfferRepository(Protocol):
    def add(self, offer: Offer) -> None:
        """Save an offer. Raise OfferAlreadyExistsError for duplicate IDs."""

    def get(self, offer_id: UUID) -> Offer | None:
        """Return an offer by ID, or None if it does not exist."""


class InMemoryOfferRepository:
    def __init__(self) -> None:
        self._offers: dict[UUID, Offer] = {}

    def add(self, offer: Offer) -> None:
        if offer.id in self._offers:
            raise OfferAlreadyExistsError(
                f"Offer already exists: {offer.id}"
            )

        self._offers[offer.id] = offer.model_copy(deep=True)

    def get(self, offer_id: UUID) -> Offer | None:
        offer = self._offers.get(offer_id)
        if offer is None:
            return None

        return offer.model_copy(deep=True)
