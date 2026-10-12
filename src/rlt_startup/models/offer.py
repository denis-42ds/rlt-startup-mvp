from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class OfferItem(BaseModel):
    """Предложение поставщика по одной позиции RFQ."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    rfq_item_id: UUID
    catalog_item_id: UUID

    offered_product_name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=32)

    available_quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(gt=0)


class Offer(BaseModel):
    """Коммерческое предложение поставщика."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    rfq_id: UUID
    supplier_organization_id: UUID

    items: list[OfferItem] = Field(min_length=1)

    currency: str = Field(pattern=r"^[A-Z]{3}$")
    version: int = Field(default=1, ge=1)

    valid_until: datetime
    delivery_date: date | None = None

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("created_at", "valid_until")
    @classmethod
    def datetime_must_include_timezone(
        cls, value: datetime
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must include a timezone")
        return value

    @model_validator(mode="after")
    def validity_period_must_be_positive(self) -> Self:
        if self.valid_until <= self.created_at:
            raise ValueError("valid_until must be later than created_at")
        return self

