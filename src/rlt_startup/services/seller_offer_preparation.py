from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rlt_startup.models.offer import Offer, OfferItem
from rlt_startup.models.rfq import RFQ
from rlt_startup.services.catalog_policy import CatalogPolicyAdapter


class SellerOfferPreparationResult(BaseModel):
    """Результат подготовки предложения поставщика."""

    model_config = ConfigDict(extra="forbid")

    ready: bool
    offer: Offer | None
    reasons: list[str]


def _normalize_name(value: str) -> str:
    """Нормализует пробелы и регистр для точного сопоставления."""
    return " ".join(value.split()).casefold()


def prepare_seller_offer(
    rfq: RFQ,
    supplier_organization_id: UUID,
    adapter: CatalogPolicyAdapter,
    *,
    now: datetime | None = None,
    inventory_max_age: timedelta = timedelta(hours=24),
) -> SellerOfferPreparationResult:
    """Формирует предложение, только если необходимые данные проверены."""

    now = now or datetime.now(timezone.utc)

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    if inventory_max_age < timedelta(0):
        raise ValueError("inventory_max_age cannot be negative")

    policy = adapter.get_policy(supplier_organization_id)
    if policy is None:
        return SellerOfferPreparationResult(
            ready=False,
            offer=None,
            reasons=["Не найдена коммерческая политика поставщика"],
        )

    if policy.currency != rfq.currency and rfq.currency is not None:
        return SellerOfferPreparationResult(
            ready=False,
            offer=None,
            reasons=["Валюта политики поставщика не совпадает с валютой RFQ"],
        )

    catalog = adapter.list_catalog_items(supplier_organization_id)
    reasons: list[str] = []
    offer_items: list[OfferItem] = []
    total_price = Decimal("0")

    for requested in rfq.items:
        matching = [
            item
            for item in catalog
            if _normalize_name(item.product_name)
            == _normalize_name(requested.product_name)
            and item.unit == requested.unit
        ]

        if not matching:
            reasons.append(
                f"Товар не найден в каталоге: {requested.product_name}"
            )
            continue

        if len(matching) > 1:
            reasons.append(
                f"Неоднозначное совпадение товара в каталоге: "
                f"{requested.product_name}"
            )
            continue

        item = matching[0]

        if item.currency != policy.currency:
            reasons.append(
                f"Валюта товара не совпадает с политикой поставщика: "
                f"{requested.product_name}"
            )
            continue

        if (
            rfq.max_unit_price is not None
            and item.unit_price > rfq.max_unit_price
        ):
            reasons.append(
                f"Цена выше предельной цены покупателя: "
                f"{requested.product_name}"
            )
            continue

        snapshot = adapter.get_inventory(item.id)
        if snapshot is None:
            reasons.append(
                f"Нет данных об остатке: {requested.product_name}"
            )
            continue

        age = now - snapshot.observed_at
        if age < timedelta(0):
            reasons.append(
                f"Время снимка остатка находится в будущем: "
                f"{requested.product_name}"
            )
            continue

        if age > inventory_max_age:
            reasons.append(
                f"Данные об остатке устарели: {requested.product_name}"
            )
            continue

        if snapshot.available_quantity is None:
            reasons.append(
                f"Количество товара неизвестно: {requested.product_name}"
            )
            continue

        if snapshot.available_quantity < requested.quantity:
            reasons.append(
                f"Недостаточно товара на складе: {requested.product_name}"
            )
            continue

        offer_items.append(
            OfferItem(
                rfq_item_id=requested.id,
                catalog_item_id=item.id,
                offered_product_name=item.product_name,
                unit=item.unit,
                available_quantity=snapshot.available_quantity,
                unit_price=item.unit_price,
            )
        )
        total_price += requested.quantity * item.unit_price

    if total_price < policy.minimum_order_value:
        reasons.append(
            "Сумма заказа ниже минимальной суммы поставщика"
        )

    if reasons:
        return SellerOfferPreparationResult(
            ready=False,
            offer=None,
            reasons=reasons,
        )

    offer = Offer(
        rfq_id=rfq.id,
        supplier_organization_id=supplier_organization_id,
        items=offer_items,
        currency=policy.currency,
        created_at=now,
        valid_until=now + timedelta(days=policy.max_offer_validity_days),
    )

    return SellerOfferPreparationResult(
        ready=True,
        offer=offer,
        reasons=[],
    )

