from rlt_startup.models.offer import Offer
from rlt_startup.models.rfq import RFQ


class OfferValidationError(ValueError):
    """Предложение не соответствует запросу покупателя."""


def validate_offer_against_rfq(offer: Offer, rfq: RFQ) -> None:
    """Проверяет связи предложения с запросом и его позициями."""

    if offer.rfq_id != rfq.id:
        raise OfferValidationError(
            "offer.rfq_id does not match rfq.id"
        )

    rfq_item_ids = {item.id for item in rfq.items}
    offered_item_ids = [item.rfq_item_id for item in offer.items]

    if len(offered_item_ids) != len(set(offered_item_ids)):
        raise OfferValidationError(
            "An RFQ item cannot appear more than once in an offer"
        )

    unknown_item_ids = set(offered_item_ids) - rfq_item_ids

    if unknown_item_ids:
        raise OfferValidationError(
            "Offer contains items that do not belong to the RFQ"
        )

