from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from rlt_startup.models.supplier_data import (
    InventorySnapshot,
    SupplierCatalogItem,
    SupplierPolicy,
)


class CatalogPolicyAdapter(Protocol):
    """Интерфейс чтения каталога, остатков и политики поставщика."""

    def list_catalog_items(
        self,
        supplier_organization_id: UUID,
    ) -> list[SupplierCatalogItem]:
        ...

    def get_inventory(
        self,
        catalog_item_id: UUID,
    ) -> InventorySnapshot | None:
        ...

    def get_policy(
        self,
        supplier_organization_id: UUID,
    ) -> SupplierPolicy | None:
        ...


class InMemoryCatalogPolicyAdapter:
    """Адаптер для локального MVP и воспроизводимых тестов."""

    def __init__(
        self,
        catalog_items: Iterable[SupplierCatalogItem] = (),
        inventory_snapshots: Iterable[InventorySnapshot] = (),
        policies: Iterable[SupplierPolicy] = (),
    ) -> None:
        self._catalog_items: dict[UUID, SupplierCatalogItem] = {}
        self._inventory: dict[UUID, InventorySnapshot] = {}
        self._policies: dict[UUID, SupplierPolicy] = {}

        for item in catalog_items:
            if item.id in self._catalog_items:
                raise ValueError(f"Duplicate catalog item ID: {item.id}")
            self._catalog_items[item.id] = item

        for snapshot in inventory_snapshots:
            if snapshot.catalog_item_id in self._inventory:
                raise ValueError(
                    "Duplicate inventory snapshot for catalog item: "
                    f"{snapshot.catalog_item_id}"
                )
            self._inventory[snapshot.catalog_item_id] = snapshot

        for policy in policies:
            supplier_id = policy.supplier_organization_id
            if supplier_id in self._policies:
                raise ValueError(f"Duplicate supplier policy: {supplier_id}")
            self._policies[supplier_id] = policy

    def list_catalog_items(
        self,
        supplier_organization_id: UUID,
    ) -> list[SupplierCatalogItem]:
        return [
            item
            for item in self._catalog_items.values()
            if item.supplier_organization_id == supplier_organization_id
        ]

    def get_inventory(
        self,
        catalog_item_id: UUID,
    ) -> InventorySnapshot | None:
        return self._inventory.get(catalog_item_id)

    def get_policy(
        self,
        supplier_organization_id: UUID,
    ) -> SupplierPolicy | None:
        return self._policies.get(supplier_organization_id)

