from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RFQStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "rfq_submitted"


class RFQItem(BaseModel):
    """Одна товарная позиция в запросе покупателя."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    product_name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    description: str | None = Field(default=None, max_length=2000)


class RFQ(BaseModel):
    """Типизированный запрос покупателя на коммерческое предложение."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    buyer_organization_id: UUID
    items: list[RFQItem] = Field(min_length=1)

    max_unit_price: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    delivery_destination: str | None = Field(default=None, max_length=500)
    desired_delivery_date: date | None = None
    response_deadline: datetime | None = None

    constraints: list[str] = Field(default_factory=list)
    status: RFQStatus = RFQStatus.DRAFT
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("response_deadline")
    @classmethod
    def deadline_must_include_timezone(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("response_deadline must include a timezone")
        return value

    @model_validator(mode="after")
    def price_requires_currency(self) -> Self:
        if self.max_unit_price is not None and self.currency is None:
            raise ValueError(
                "currency is required when max_unit_price is specified"
            )
        return self

