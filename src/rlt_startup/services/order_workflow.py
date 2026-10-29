from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rlt_startup.models.offer import Offer
from rlt_startup.models.order import (
    Order,
    OrderItem,
    OrderParty,
    OrderStatus,
)
from rlt_startup.models.rfq import RFQ
from rlt_startup.services.catalog_policy import CatalogPolicyAdapter
from rlt_startup.services.offer_validation import validate_offer_against_rfq
from rlt_startup.services.supplier_execution_check import (
    check_order_executability,
)


class OrderWorkflowError(ValueError):
    """Недопустимая операция над заказом."""


class OrderPolicyViolation(OrderWorkflowError):
    """Заказ не прошёл проверку исполнимости или полномочий."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def _get_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return value


def _replace_order(order: Order, **changes: object) -> Order:
    data = order.model_dump(mode="python")
    data.update(changes)
    return Order.model_validate(data)


def create_order_from_offer(
    rfq: RFQ,
    offer: Offer,
    *,
    now: datetime | None = None,
) -> Order:
    now = _get_now(now)
    validate_offer_against_rfq(offer, rfq)

    if offer.valid_until <= now:
        raise OrderWorkflowError("Нельзя создать заказ по просроченному предложению")

    if rfq.currency is not None and offer.currency != rfq.currency:
        raise OrderWorkflowError("Валюта предложения не совпадает с RFQ")

    offered_items = {item.rfq_item_id: item for item in offer.items}
    order_items: list[OrderItem] = []

    for requested in rfq.items:
        offered = offered_items.get(requested.id)
        if offered is None:
            raise OrderWorkflowError(
                f"В предложении отсутствует позиция: {requested.product_name}"
            )
        if offered.unit != requested.unit:
            raise OrderWorkflowError(
                f"Несовпадение единиц измерения: {requested.product_name}"
            )
        if offered.available_quantity < requested.quantity:
            raise OrderWorkflowError(
                f"Недостаточно товара: {requested.product_name}"
            )
        if (
            rfq.max_unit_price is not None
            and offered.unit_price > rfq.max_unit_price
        ):
            raise OrderWorkflowError(
                f"Цена выше предельной: {requested.product_name}"
            )

        order_items.append(
            OrderItem(
                rfq_item_id=requested.id,
                catalog_item_id=offered.catalog_item_id,
                product_name=offered.offered_product_name,
                quantity=requested.quantity,
                unit=offered.unit,
                unit_price=offered.unit_price,
            )
        )

    total_amount = sum(
        (item.quantity * item.unit_price for item in order_items),
        Decimal("0"),
    )

    return Order(
        rfq_id=rfq.id,
        offer_id=offer.id,
        buyer_organization_id=rfq.buyer_organization_id,
        supplier_organization_id=offer.supplier_organization_id,
        items=order_items,
        currency=offer.currency,
        total_amount=total_amount,
        offer_valid_until=offer.valid_until,
        created_at=now,
        updated_at=now,
    )


def buyer_confirm_order(
    order: Order,
    *,
    now: datetime | None = None,
) -> Order:
    now = _get_now(now)

    if order.status != OrderStatus.PENDING_BUYER_CONFIRMATION:
        raise OrderWorkflowError("Заказ не ожидает подтверждения покупателя")
    if order.offer_valid_until <= now:
        raise OrderWorkflowError("Предложение истекло до подтверждения покупателем")

    return _replace_order(
        order,
        status=OrderStatus.PENDING_SUPPLIER_CONFIRMATION,
        buyer_confirmed_at=now,
        updated_at=now,
    )



def supplier_confirm_order(
    order: Order,
    adapter: CatalogPolicyAdapter,
    *,
    now: datetime | None = None,
    inventory_max_age: timedelta = timedelta(hours=24),
    max_check_age: timedelta = timedelta(minutes=15),
) -> Order:
    now = _get_now(now)

    if order.status != OrderStatus.PENDING_SUPPLIER_CONFIRMATION:
        raise OrderWorkflowError("Заказ не ожидает подтверждения поставщика")

    if order.offer_valid_until <= now:
        raise OrderWorkflowError("Предложение истекло до подтверждения поставщиком")

    if max_check_age < timedelta(0):
        raise ValueError("max_check_age cannot be negative")

    # Результат формирует платформа по данным адаптера,
    # а не вызывающий код произвольным значением allowed=True.
    execution_check = check_order_executability(
        order,
        adapter,
        now=now,
        inventory_max_age=inventory_max_age,
    )

    if now - execution_check.checked_at > max_check_age:
        raise OrderWorkflowError("Проверка исполнимости устарела")

    if not execution_check.allowed:
        raise OrderPolicyViolation(execution_check.reasons)

    return _replace_order(
        order,
        status=OrderStatus.CONFIRMED,
        supplier_confirmed_at=now,
        updated_at=now,
    )


def reject_order(
    order: Order,
    party: OrderParty,
    reason: str,
    *,
    now: datetime | None = None,
) -> Order:
    now = _get_now(now)
    reason = reason.strip()

    if not reason:
        raise OrderWorkflowError("Для отказа необходимо указать причину")

    allowed = (
        party == OrderParty.BUYER
        and order.status == OrderStatus.PENDING_BUYER_CONFIRMATION
    ) or (
        party == OrderParty.SUPPLIER
        and order.status == OrderStatus.PENDING_SUPPLIER_CONFIRMATION
    )
    if not allowed:
        raise OrderWorkflowError(
                "Эта сторона не может отклонить заказ в текущем статусе"
                )

    return _replace_order(
        order,
        status=OrderStatus.REJECTED,
        rejected_by=party,
        rejection_reason=reason,
        updated_at=now,
    )

