"""Section 16 conditions as plain, deterministic functions. No LLM is involved here.

Each check returns (passed, detail). `run_section16` maps them to rule-pack IDs and to the label a failure
produces (from rules/cgst_16.yaml), so the outcome of a failed check is data, not code.

Dates used:
- `as_of`: last day of the tax period. The 180-day rule and goods receipt are judged on this date.
- `claim_date`: the date credit is taken, i.e. the GSTR-3B due date for the period (20th of next month).
"""
from __future__ import annotations

import re
from datetime import date

from itc.periods import financial_year_end, period_bounds
from itc.rulepack import ConditionPack
from itc.schemas import CheckResult, ClientProfile, Gstr2bRecord, Invoice, Payment

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAYMENT_DAYS = 180


def normalise_invoice_no(raw: str) -> str:
    """'INV/23-24/001', 'inv-2324-001' and 'INV 2023-24 001' all become 'INV2324001'.

    Leading zeros are kept on purpose: '001' and '1' are different documents to a supplier.
    """
    s = raw.upper().strip()
    s = re.sub(r"(?<!\d)20(\d{2})[-/](\d{2})(?!\d)", r"\1\2", s)  # 2023-24 -> 2324
    return re.sub(r"[^A-Z0-9]", "", s)


def fy_label(d: date) -> str:
    end = financial_year_end(d)
    return f"{end.year - 1}-{str(end.year)[2:]}"


def check_invoice_fields(inv: Invoice) -> tuple[bool, str]:
    missing = []
    if not inv.supplier_gstin:
        missing.append("supplier GSTIN")
    elif not GSTIN_RE.match(inv.supplier_gstin):
        missing.append(f"valid supplier GSTIN (got {inv.supplier_gstin!r})")
    if not inv.invoice_no:
        missing.append("invoice number")
    if inv.invoice_date is None:
        missing.append("invoice date")
    if not inv.items or any(i.taxable_value <= 0 for i in inv.items):
        missing.append("positive taxable value")
    if missing:
        return False, "Missing or invalid: " + ", ".join(missing)
    return True, "Mandatory invoice fields present"


def match_gstr2b(inv: Invoice, records: list[Gstr2bRecord]) -> tuple[bool, str]:
    if not inv.supplier_gstin or not inv.invoice_no:
        return False, "Cannot match: invoice has no supplier GSTIN or number"
    key = normalise_invoice_no(inv.invoice_no)
    for r in records:
        if r.supplier_gstin == inv.supplier_gstin and normalise_invoice_no(r.invoice_no) == key:
            how = "exact" if r.invoice_no == inv.invoice_no else f"normalised ({r.invoice_no!r} = {inv.invoice_no!r})"
            return True, f"Found in GSTR-2B, {how} match"
    return False, "Not in GSTR-2B for this period (supplier has not reported it yet)"


def check_receipt(inv: Invoice, as_of: date) -> tuple[bool, str]:
    if inv.received_on is None:
        return False, "No receipt recorded for goods/services"
    if inv.received_on > as_of:
        return False, f"Received {inv.received_on}, after the period end {as_of}"
    return True, f"Received on {inv.received_on}"


def amount_paid(inv: Invoice, payments: list[Payment], as_of: date) -> float:
    key = normalise_invoice_no(inv.invoice_no or "")
    return round(
        sum(
            p.amount
            for p in payments
            if p.supplier_gstin == inv.supplier_gstin
            and normalise_invoice_no(p.invoice_no) == key
            and p.paid_on <= as_of
        ),
        2,
    )


def check_180_days(inv: Invoice, payments: list[Payment], as_of: date) -> tuple[bool, str]:
    """Day N = as_of - invoice_date. Day 180 still passes; from day 181 an unpaid invoice fails.

    A paid invoice passes whenever it was paid: payment after day 180 means re-availment (third proviso).
    """
    if inv.reverse_charge:
        return True, "Reverse-charge supply: 180-day rule does not apply"
    if inv.invoice_date is None:
        return False, "No invoice date; cannot count 180 days"
    day = (as_of - inv.invoice_date).days
    paid = amount_paid(inv, payments, as_of)
    if paid >= inv.total - 0.5:  # rupee rounding tolerance
        return True, f"Paid in full (Rs. {paid:,.2f}) by {as_of}; day {day}"
    if day <= PAYMENT_DAYS:
        return True, f"Day {day} of {PAYMENT_DAYS}; Rs. {inv.total - paid:,.2f} unpaid but still within time"
    return False, (
        f"Day {day}: Rs. {inv.total - paid:,.2f} unpaid beyond {PAYMENT_DAYS} days. "
        "Reverse with interest now; re-avail on payment."
    )


def section16_4_deadline(invoice_date: date, annual_return_filed_on: date | None = None) -> date:
    """30 November after the end of the invoice's FY, or the annual return date if that is earlier."""
    nov30 = date(financial_year_end(invoice_date).year, 11, 30)
    if annual_return_filed_on is not None and annual_return_filed_on < nov30:
        return annual_return_filed_on
    return nov30


def check_time_limit(inv: Invoice, profile: ClientProfile, claim_date: date) -> tuple[bool, str]:
    if inv.invoice_date is None:
        return False, "No invoice date; cannot apply the s.16(4) time limit"
    fy = fy_label(inv.invoice_date)
    annual_return = profile.annual_returns_filed.get(fy)
    deadline = section16_4_deadline(inv.invoice_date, annual_return)
    basis = "annual return filing date" if deadline == annual_return else "30 November"
    if claim_date <= deadline:
        return True, f"Claim on {claim_date} is within the s.16(4) deadline {deadline} ({basis}, FY {fy})"
    return False, f"Time-barred: claim on {claim_date} is after the s.16(4) deadline {deadline} ({basis}, FY {fy})"


def claim_date_for(period: str, gstr3b_due_day: int = 20) -> date:
    _, end = period_bounds(period)
    return date(end.year + (end.month == 12), end.month % 12 + 1, gstr3b_due_day)


def run_section16(
    inv: Invoice,
    gstr2b: list[Gstr2bRecord],
    payments: list[Payment],
    profile: ClientProfile,
    period: str,
    pack: ConditionPack,
) -> list[CheckResult]:
    _, as_of = period_bounds(period)
    claim_date = claim_date_for(period)
    outcomes = {
        "S16_2_A": check_invoice_fields(inv),
        "S16_2_AA": match_gstr2b(inv, gstr2b),
        "S16_2_B": check_receipt(inv, as_of),
        "S16_2_PROVISO_180": check_180_days(inv, payments, as_of),
        "S16_4": check_time_limit(inv, profile, claim_date),
    }
    return [
        CheckResult(rule_id=rid, passed=ok, outcome_on_fail=pack.get(rid).outcome_on_fail, detail=detail)
        for rid, (ok, detail) in outcomes.items()
    ]
