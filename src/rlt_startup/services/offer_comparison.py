from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from rlt_startup.models.offer import Offer
from rlt_startup.models.rfq import RFQ
from rlt_startup.services.offer_validation import (
    validate_offer_against_rfq,
)


class OfferComparison(BaseModel):
    """Результат проверки коммерческого предложения."""

    model_config = ConfigDict(extra="forbid")

    offer_id: str
    supplier_organization_id: str
    currency: str
    eligible: bool
    total_price: Decimal | None
    reasons: list[str]


def compare_offer(offer: Offer, rfq: RFQ) -> OfferComparison:
    """Проверяет выполнимость предложения и рассчитывает его стоимость."""

    validate_offer_against_rfq(offer, rfq)

    now = datetime.now(timezone.utc)
    reasons: list[str] = []
    total_price = Decimal("0")

    if offer.valid_until <= now:
        reasons.append("Предложение просрочено")

    offered_items = {
        item.rfq_item_id: item
        for item in offer.items
    }

    for rfq_item in rfq.items:
        offered_item = offered_items.get(rfq_item.id)

        if offered_item is None:
            reasons.append(
                f"Нет предложения по позиции: {rfq_item.product_name}"
            )
            continue

        if offered_item.unit != rfq_item.unit:
            reasons.append(
                f"Несовпадение единиц измерения: "
                f"{rfq_item.product_name}"
            )
            continue

        if offered_item.available_quantity < rfq_item.quantity:
            reasons.append(
                f"Недостаточно количества: {rfq_item.product_name}"
            )
            continue

        total_price += rfq_item.quantity * offered_item.unit_price

    eligible = not reasons

    return OfferComparison(
        offer_id=str(offer.id),
        supplier_organization_id=str(offer.supplier_organization_id),
        currency=offer.currency,
        eligible=eligible,
        total_price=total_price if eligible else None,
        reasons=reasons,
    )


def compare_offers(
    offers: list[Offer],
    rfq: RFQ,
) -> list[OfferComparison]:
    """Сравнивает предложения и группирует результаты по валюте."""

    results = [compare_offer(offer, rfq) for offer in offers]

    return sorted(
        results,
        key=lambda result: (
            result.currency,
            not result.eligible,
            result.total_price
            if result.total_price is not None
            else Decimal("0"),
        ),
    )

