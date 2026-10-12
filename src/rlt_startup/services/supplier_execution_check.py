from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from rlt_startup.models.order import Order, SupplierExecutionCheck
from rlt_startup.services.catalog_policy import CatalogPolicyAdapter


def check_order_executability(
    order: Order,
    adapter: CatalogPolicyAdapter,
    *,
    now: datetime | None = None,
    inventory_max_age: timedelta = timedelta(hours=24),
) -> SupplierExecutionCheck:
    """Проверить актуальные данные поставщика перед его подтверждением."""
    checked_at = now or datetime.now(timezone.utc)

    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("now must include a timezone")
    if inventory_max_age < timedelta(0):
        raise ValueError("inventory_max_age cannot be negative")

    reasons: list[str] = []

    if order.offer_valid_until <= checked_at:
        reasons.append("Срок действия предложения истёк")

    policy = adapter.get_policy(order.supplier_organization_id)
    if policy is None:
        reasons.append("Не найдена коммерческая политика поставщика")
    else:
        if policy.currency != order.currency:
            reasons.append("Валюта политики поставщика не совпадает с заказом")
        if order.total_amount < policy.minimum_order_value:
            reasons.append("Сумма заказа ниже минимальной суммы поставщика")

    catalog = adapter.list_catalog_items(order.supplier_organization_id)

    # Группируем позиции заказа по точному ID каталога.
    required_by_catalog_id: dict[UUID, Decimal] = {}

    for order_item in order.items:
        matches = [
            item for item in catalog
            if item.id == order_item.catalog_item_id
        ]

        if not matches:
            reasons.append(
                f"Товар отсутствует в каталоге поставщика: "
                f"{order_item.product_name}"
            )
            continue

        if len(matches) > 1:
            reasons.append(
                f"ID товара неоднозначен в каталоге: "
                f"{order_item.catalog_item_id}"
            )
            continue

        catalog_item = matches[0]

        if catalog_item.supplier_organization_id != order.supplier_organization_id:
            reasons.append(
                f"Товар принадлежит другому поставщику: "
                f"{order_item.product_name}"
            )
            continue

        if catalog_item.unit != order_item.unit:
            reasons.append(
                f"Единица измерения товара изменилась: "
                f"{order_item.product_name}"
            )
            continue

        if catalog_item.currency != order.currency:
            reasons.append(
                f"Валюта товара не совпадает с заказом: "
                f"{order_item.product_name}"
            )
            continue

        # Цена каталога не заменяет зафиксированную цену заказа.
        required_by_catalog_id[catalog_item.id] = (
            required_by_catalog_id.get(catalog_item.id, Decimal("0"))
            + order_item.quantity
        )

    for catalog_item_id, required_quantity in required_by_catalog_id.items():
        snapshot = adapter.get_inventory(catalog_item_id)

        if snapshot is None:
            reasons.append(
                f"Нет данных об остатке товара: {catalog_item_id}"
            )
            continue

        age = checked_at - snapshot.observed_at

        if age < timedelta(0):
            reasons.append(
                f"Время снимка остатка находится в будущем: {catalog_item_id}"
            )
            continue

        if age > inventory_max_age:
            reasons.append(
                f"Данные об остатке устарели: {catalog_item_id}"
            )
            continue

        if snapshot.available_quantity is None:
            reasons.append(
                f"Остаток товара неизвестен: {catalog_item_id}"
            )
            continue

        if snapshot.available_quantity < required_quantity:
            reasons.append(
                f"Недостаточно товара на складе: {catalog_item_id}"
            )

    return SupplierExecutionCheck(
        allowed=not reasons,
        reasons=reasons,
        checked_at=checked_at,
    )
