from datetime import datetime, timezone

from rlt_startup.models.documents import (
    CommercialOfferDraft,
    DocumentDraftBundle,
    DocumentLineItem,
    OrderDocumentDraft,
    ShippingSpecificationDraft,
)
from rlt_startup.models.order import Order, OrderStatus


class DocumentGenerationError(ValueError):
    """Нельзя сформировать документы по текущему состоянию заказа."""


def generate_document_drafts(
    order: Order,
    *,
    generated_at: datetime | None = None,
) -> DocumentDraftBundle:
    """Сформировать черновики документов из подтверждённого заказа."""
    timestamp = generated_at or datetime.now(timezone.utc)

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must include a timezone")

    if order.status != OrderStatus.CONFIRMED:
        raise DocumentGenerationError(
            "Документы можно сформировать только по подтверждённому заказу"
        )

    if order.buyer_confirmed_at is None or order.supplier_confirmed_at is None:
        raise DocumentGenerationError(
            "Для формирования документов нужны подтверждения обеих сторон"
        )

    items = [
        DocumentLineItem(
            product_name=item.product_name,
            quantity=item.quantity,
            unit=item.unit,
            unit_price=item.unit_price,
            line_total=item.quantity * item.unit_price,
        )
        for item in order.items
    ]

    common = {
        "source_order_id": order.id,
        "buyer_organization_id": order.buyer_organization_id,
        "supplier_organization_id": order.supplier_organization_id,
    }

    return DocumentDraftBundle(
        commercial_offer=CommercialOfferDraft(
            **common,
            items=items,
            currency=order.currency,
            total_amount=order.total_amount,
            valid_until=order.offer_valid_until,
            generated_at=timestamp,
        ),
        order=OrderDocumentDraft(
            **common,
            items=items,
            currency=order.currency,
            total_amount=order.total_amount,
            buyer_confirmed_at=order.buyer_confirmed_at,
            supplier_confirmed_at=order.supplier_confirmed_at,
            generated_at=timestamp,
        ),
        shipping_specification=ShippingSpecificationDraft(
            **common,
            items=items,
            generated_at=timestamp,
        ),
    )

