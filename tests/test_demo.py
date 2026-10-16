from decimal import Decimal
from uuid import UUID

from rlt_startup.demo import (
    SUPPLIER_A_ID,
    SUPPLIER_B_ID,
    SUPPLIER_C_ID,
    create_demo_adapters,
)
from rlt_startup.models.rfq import RFQ, RFQItem
from rlt_startup.services.seller_offer_workflow import (
    run_seller_offer_workflow,
)


def test_demo_adapters_prepare_and_rank_offers() -> None:
    rfq = RFQ(
        buyer_organization_id=UUID(
            "30000000-0000-4000-8000-000000000001"
        ),
        items=[
            RFQItem(
                product_name="Стальной лист",
                quantity="100",
                unit="кг",
            )
        ],
        currency="RUB",
        max_unit_price="200",
    )

    adapters = create_demo_adapters()

    result = run_seller_offer_workflow(
        rfq=rfq,
        supplier_ids=[
            SUPPLIER_A_ID,
            SUPPLIER_B_ID,
            SUPPLIER_C_ID,
        ],
        adapters=adapters,
    )

    assert result.preparations[SUPPLIER_A_ID].ready
    assert result.preparations[SUPPLIER_B_ID].ready

    unavailable = result.preparations[SUPPLIER_C_ID]
    assert not unavailable.ready
    assert unavailable.offer is None
    assert any("Недостаточно товара" in reason for reason in unavailable.reasons)

    assert len(result.comparisons) == 2
    assert result.comparisons[0].supplier_organization_id == str(
        SUPPLIER_A_ID
    )
    assert result.comparisons[0].total_price == Decimal("14550.00")
    assert result.comparisons[1].supplier_organization_id == str(
        SUPPLIER_B_ID
    )
    assert result.comparisons[1].total_price == Decimal("16000.00")
