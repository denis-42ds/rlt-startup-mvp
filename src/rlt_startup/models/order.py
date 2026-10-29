from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OrderStatus(StrEnum):
    PENDING_BUYER_CONFIRMATION = "pending_buyer_confirmation"
    PENDING_SUPPLIER_CONFIRMATION = "pending_supplier_confirmation"
    CONFIRMED = "order_confirmed"
    REJECTED = "rejected"


class OrderParty(StrEnum):
    BUYER = "buyer"
    SUPPLIER = "supplier"


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rfq_item_id: UUID
    catalog_item_id: UUID
    product_name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    unit_price: Decimal = Field(gt=0)


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    rfq_id: UUID
    offer_id: UUID
    buyer_organization_id: UUID
    supplier_organization_id: UUID

    # Снимок коммерческих условий на момент создания заказа.
    items: list[OrderItem] = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    total_amount: Decimal = Field(gt=0)
    offer_valid_until: datetime

    status: OrderStatus = OrderStatus.PENDING_BUYER_CONFIRMATION
    buyer_confirmed_at: datetime | None = None
    supplier_confirmed_at: datetime | None = None
    rejected_by: OrderParty | None = None
    rejection_reason: str | None = Field(default=None, max_length=2000)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator(
        "offer_valid_until",
        "buyer_confirmed_at",
        "supplier_confirmed_at",
        "created_at",
        "updated_at",
    )
    @classmethod
    def datetimes_must_include_timezone(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("datetime must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        expected_total = sum(
            (item.quantity * item.unit_price for item in self.items),
            Decimal("0"),
        )
        if self.total_amount != expected_total:
            raise ValueError("total_amount does not match order items")

        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")

        if self.status == OrderStatus.PENDING_BUYER_CONFIRMATION:
            if self.buyer_confirmed_at or self.supplier_confirmed_at:
                raise ValueError("Pending buyer confirmation cannot have confirmations")
            if self.rejected_by or self.rejection_reason:
                raise ValueError("Pending order cannot have rejection details")

        elif self.status == OrderStatus.PENDING_SUPPLIER_CONFIRMATION:
            if (
                    self.buyer_confirmed_at is None
                    or self.supplier_confirmed_at is not None
                    ):
                raise ValueError("Buyer must confirm before supplier confirmation")
            if self.rejected_by or self.rejection_reason:
                raise ValueError("Pending order cannot have rejection details")

        elif self.status == OrderStatus.CONFIRMED:
            if self.buyer_confirmed_at is None or self.supplier_confirmed_at is None:
                raise ValueError("Confirmed order requires both confirmations")
            if self.rejected_by or self.rejection_reason:
                raise ValueError("Confirmed order cannot have rejection details")

        elif self.status == OrderStatus.REJECTED:
            if self.rejected_by is None or not self.rejection_reason:
                raise ValueError("Rejected order requires party and reason")
            if self.supplier_confirmed_at is not None:
                raise ValueError("Rejected order cannot have supplier confirmation")
            if (
                    self.rejected_by == OrderParty.BUYER
                    and self.buyer_confirmed_at is not None
                    ):
                raise ValueError("Buyer rejection must precede buyer confirmation")
            if (
                    self.rejected_by == OrderParty.SUPPLIER
                    and self.buyer_confirmed_at is None
                    ):
                raise ValueError("Supplier can reject only after buyer confirmation")

        return self


class SupplierExecutionCheck(BaseModel):
    """Результат детерминированной проверки исполнимости заказа."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reasons: list[str] = Field(default_factory=list)
    checked_at: datetime

    @field_validator("checked_at")
    @classmethod
    def check_time_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("checked_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_reasons(self) -> Self:
        if self.allowed and self.reasons:
            raise ValueError("Allowed check cannot contain failure reasons")
        if not self.allowed and not self.reasons:
            raise ValueError("Failed check must explain why")
        return self

