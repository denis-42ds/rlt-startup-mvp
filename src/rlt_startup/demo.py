"""Воспроизводимые демонстрационные данные для MVP RLT.Startup."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from rlt_startup.models.supplier_data import (
    InventorySnapshot,
    SupplierCatalogItem,
    SupplierPolicy,
)
from rlt_startup.services.catalog_policy import (
    CatalogPolicyAdapter,
    InMemoryCatalogPolicyAdapter,
)

SUPPLIER_A_ID = UUID("10000000-0000-4000-8000-000000000001")
SUPPLIER_B_ID = UUID("10000000-0000-4000-8000-000000000002")
SUPPLIER_C_ID = UUID("10000000-0000-4000-8000-000000000003")

SUPPLIER_A_ITEM_ID = UUID("20000000-0000-4000-8000-000000000001")
SUPPLIER_B_ITEM_ID = UUID("20000000-0000-4000-8000-000000000002")
SUPPLIER_C_ITEM_ID = UUID("20000000-0000-4000-8000-000000000003")


def create_demo_adapters() -> dict[UUID, CatalogPolicyAdapter]:
    """Создаёт три поставщика: два с подходящим остатком, один — без него."""

    observed_at = datetime.now(timezone.utc) - timedelta(minutes=5)

    supplier_data = [
        {
            "supplier_id": SUPPLIER_A_ID,
            "item_id": SUPPLIER_A_ITEM_ID,
            "price": "145.50",
            "quantity": "250",
        },
        {
            "supplier_id": SUPPLIER_B_ID,
            "item_id": SUPPLIER_B_ITEM_ID,
            "price": "160.00",
            "quantity": "180",
        },
        {
            "supplier_id": SUPPLIER_C_ID,
            "item_id": SUPPLIER_C_ITEM_ID,
            "price": "135.00",
            "quantity": "50",
        },
    ]

    adapters: dict[UUID, CatalogPolicyAdapter] = {}

    for data in supplier_data:
        supplier_id = data["supplier_id"]

        item = SupplierCatalogItem(
            id=data["item_id"],
            supplier_organization_id=supplier_id,
            product_name="Стальной лист",
            unit="кг",
            unit_price=data["price"],
            currency="RUB",
        )

        inventory = InventorySnapshot(
            catalog_item_id=item.id,
            available_quantity=data["quantity"],
            observed_at=observed_at,
            source="demo-seed",
        )

        policy = SupplierPolicy(
            supplier_organization_id=supplier_id,
            currency="RUB",
            minimum_order_value="0",
            max_offer_validity_days=7,
        )

        adapters[supplier_id] = InMemoryCatalogPolicyAdapter(
            catalog_items=[item],
            inventory_snapshots=[inventory],
            policies=[policy],
        )

    return adapters
