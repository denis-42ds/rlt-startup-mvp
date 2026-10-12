from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rlt_startup.models.offer import Offer
from rlt_startup.models.rfq import RFQ
from rlt_startup.services.catalog_policy import CatalogPolicyAdapter
from rlt_startup.services.offer_comparison import (
    OfferComparison,
    compare_offers,
)
from rlt_startup.services.seller_offer_preparation import (
    SellerOfferPreparationResult,
    prepare_seller_offer,
)


class SellerOfferWorkflowResult(BaseModel):
    """Результат подготовки и сравнения предложений по одному RFQ."""

    model_config = ConfigDict(extra="forbid")

    preparations: dict[UUID, SellerOfferPreparationResult]
    comparisons: list[OfferComparison]


def run_seller_offer_workflow(
    rfq: RFQ,
    supplier_ids: list[UUID],
    adapters: dict[UUID, CatalogPolicyAdapter],
    *,
    now: datetime | None = None,
) -> SellerOfferWorkflowResult:
    """Подготавливает предложения поставщиков и сравнивает готовые."""

    if len(supplier_ids) != len(set(supplier_ids)):
        raise ValueError("supplier_ids must not contain duplicates")

    preparations: dict[UUID, SellerOfferPreparationResult] = {}
    offers: list[Offer] = []

    for supplier_id in supplier_ids:
        adapter = adapters.get(supplier_id)

        if adapter is None:
            preparations[supplier_id] = SellerOfferPreparationResult(
                ready=False,
                offer=None,
                reasons=["Не настроен адаптер данных поставщика"],
            )
            continue

        result = prepare_seller_offer(
            rfq,
            supplier_id,
            adapter,
            now=now,
        )
        preparations[supplier_id] = result

        if result.ready and result.offer is not None:
            offers.append(result.offer)

    comparisons = compare_offers(offers, rfq)

    return SellerOfferWorkflowResult(
        preparations=preparations,
        comparisons=comparisons,
    )

