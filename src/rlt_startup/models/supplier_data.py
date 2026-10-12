from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SupplierCatalogItem(BaseModel):
    """Товар в нормализованном каталоге поставщика."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    supplier_organization_id: UUID

    product_name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=32)

    unit_price: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class InventorySnapshot(BaseModel):
    """Снимок доступного остатка товара."""

    model_config = ConfigDict(extra="forbid")

    catalog_item_id: UUID
    available_quantity: Decimal | None = Field(default=None, ge=0)
    observed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source: str = Field(min_length=1, max_length=100)

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_include_timezone(
        cls, value: datetime
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class SupplierPolicy(BaseModel):
    """Базовые коммерческие ограничения поставщика."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    supplier_organization_id: UUID
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    minimum_order_value: Decimal = Field(default=Decimal("0"), ge=0)
    max_offer_validity_days: int = Field(default=14, ge=1, le=365)

