from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    unit_price: Decimal = Field(gt=0)
    line_total: Decimal = Field(gt=0)


class CommercialOfferDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["commercial_offer"] = "commercial_offer"
    status: Literal["draft"] = "draft"
    source_order_id: UUID
    buyer_organization_id: UUID
    supplier_organization_id: UUID
    items: list[DocumentLineItem] = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    total_amount: Decimal = Field(gt=0)
    valid_until: datetime
    generated_at: datetime


class OrderDocumentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["order"] = "order"
    status: Literal["draft"] = "draft"
    source_order_id: UUID
    buyer_organization_id: UUID
    supplier_organization_id: UUID
    items: list[DocumentLineItem] = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    total_amount: Decimal = Field(gt=0)
    buyer_confirmed_at: datetime
    supplier_confirmed_at: datetime
    generated_at: datetime


class ShippingSpecificationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["shipping_specification"] = "shipping_specification"
    status: Literal["draft"] = "draft"
    source_order_id: UUID
    buyer_organization_id: UUID
    supplier_organization_id: UUID
    items: list[DocumentLineItem] = Field(min_length=1)
    generated_at: datetime


class DocumentDraftBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commercial_offer: CommercialOfferDraft
    order: OrderDocumentDraft
    shipping_specification: ShippingSpecificationDraft

