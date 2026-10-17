from typing import Protocol
from uuid import UUID

from rlt_startup.models.order import Order


class OrderAlreadyExistsError(ValueError):
    """Order with this ID already exists."""


class OrderRepository(Protocol):
    def add(self, order: Order) -> None:
        """Save an order. Raise OrderAlreadyExistsError for duplicate IDs."""

    def get(self, order_id: UUID) -> Order | None:
        """Return an order by ID, or None if it does not exist."""

    def update(self, order: Order) -> None:
        """Update an existing order. Raise KeyError if it does not exist."""


class InMemoryOrderRepository:
    def __init__(self) -> None:
        self._orders: dict[UUID, Order] = {}

    def add(self, order: Order) -> None:
        if order.id in self._orders:
            raise OrderAlreadyExistsError(
                f"Order already exists: {order.id}"
            )

        self._orders[order.id] = order.model_copy(deep=True)

    def get(self, order_id: UUID) -> Order | None:
        order = self._orders.get(order_id)
        if order is None:
            return None

        return order.model_copy(deep=True)

    def update(self, order: Order) -> None:
        if order.id not in self._orders:
            raise KeyError(f"Order not found: {order.id}")

        self._orders[order.id] = order.model_copy(deep=True)
