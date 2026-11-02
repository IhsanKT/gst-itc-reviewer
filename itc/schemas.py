"""Pydantic schemas for every input file and every structured value that crosses a node boundary."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Label = Literal["Eligible", "Blocked", "Deferred", "Needs CA review"]
FinalLabel = Literal["Eligible", "Blocked", "Deferred"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- inputs

class ClientProfile(_Strict):
    client_id: str
    legal_name: str
    gstin: str
    business_activity: str
    outward_supplies: list[str]
    notes: str = ""
    annual_returns_filed: dict[str, date] = {}  # FY label ("2025-26") -> GSTR-9 filing date


class InvoiceItem(_Strict):
    line_id: str
    description: str
    hsn: str | None = None
    quantity: float | None = None
    unit: str | None = None
    taxable_value: float
    gst_rate: float
    tax_amount: float


class Invoice(_Strict):
    """E-invoice-like purchase document. Header fields may be missing; section16 flags that."""
    supplier_gstin: str | None
    supplier_name: str
    invoice_no: str | None
    invoice_date: date | None
    doc_type: Literal["INV", "BOS", "DBN"] = "INV"  # tax invoice, bill of supply, debit note
    reverse_charge: bool = False
    received_on: date | None = None  # from the client's goods/services receipt register
    items: list[InvoiceItem]

    @property
    def total(self) -> float:
        return round(sum(i.taxable_value + i.tax_amount for i in self.items), 2)


class Gstr2bRecord(_Strict):
    supplier_gstin: str
    invoice_no: str
    invoice_date: date
    taxable_value: float
    tax_amount: float


class Payment(_Strict):
    supplier_gstin: str
    invoice_no: str
    paid_on: date
    amount: float


# ---------------------------------------------------------------- pipeline values

class CheckResult(_Strict):
    rule_id: str
    passed: bool
    outcome_on_fail: Literal["Deferred", "Blocked"]
    detail: str


class LLMLineOutput(_Strict):
    line_id: str
    rule_id: str
    reason: str = Field(max_length=600)


class LLMBatchOutput(_Strict):
    lines: list[LLMLineOutput]


class CADecision(_Strict):
    """Accept keeps the provisional label. Override needs a label and a non-empty reason."""
    action: Literal["accept", "override"]
    label: FinalLabel | None = None
    rule_id: str | None = None
    reason: str = ""
    reviewer: str = "CA"

    @model_validator(mode="after")
    def _override_needs_label_and_reason(self):
        if self.action == "override":
            if self.label is None:
                raise ValueError("override needs a label")
            if not self.reason.strip():
                raise ValueError("override needs a reason")
        return self
