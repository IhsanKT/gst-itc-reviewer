from datetime import date, timedelta

import pytest

from itc.rulepack import load_packs
from itc.schemas import ClientProfile, Gstr2bRecord, Invoice, InvoiceItem, Payment
from itc.section16 import (
    check_180_days,
    check_invoice_fields,
    check_receipt,
    check_time_limit,
    claim_date_for,
    fy_label,
    match_gstr2b,
    normalise_invoice_no,
    run_section16,
    section16_4_deadline,
)

GSTIN = "29AABCT1332L1ZT"
AS_OF = date(2026, 10, 31)


def make_invoice(**over):
    base = dict(
        supplier_gstin=GSTIN,
        supplier_name="Test Supplier",
        invoice_no="INV/25-26/001",
        invoice_date=date(2026, 10, 5),
        received_on=date(2026, 10, 6),
        items=[InvoiceItem(line_id="T1", description="x", taxable_value=1000, gst_rate=18, tax_amount=180)],
    )
    base.update(over)
    return Invoice(**base)


PROFILE = ClientProfile(
    client_id="T", legal_name="T", gstin=GSTIN, business_activity="software", outward_supplies=["software"]
)


# ---------------------------------------------------------------- invoice number normalisation

@pytest.mark.parametrize(
    "a,b",
    [
        ("INV/23-24/001", "INV-2324-001"),
        ("inv/23-24/001", "INV 23 24 001"),
        ("INV/2023-24/001", "INV-2324-001"),
        ("A.B/7", "ab7"),
    ],
)
def test_normalise_equal(a, b):
    assert normalise_invoice_no(a) == normalise_invoice_no(b)


@pytest.mark.parametrize("a,b", [("INV-2324-001", "INV-2324-01"), ("INV-2324-001", "INV-2425-001")])
def test_normalise_keeps_distinct_documents_distinct(a, b):
    assert normalise_invoice_no(a) != normalise_invoice_no(b)


# ---------------------------------------------------------------- 16(2)(a) invoice fields

def test_fields_present():
    assert check_invoice_fields(make_invoice()) == (True, "Mandatory invoice fields present")


@pytest.mark.parametrize(
    "over,expected",
    [
        ({"supplier_gstin": None}, "supplier GSTIN"),
        ({"supplier_gstin": "29ABC"}, "valid supplier GSTIN"),
        ({"invoice_no": None}, "invoice number"),
        ({"invoice_no": ""}, "invoice number"),
        ({"invoice_date": None}, "invoice date"),
        ({"items": []}, "positive taxable value"),
        ({"items": [InvoiceItem(line_id="T1", description="x", taxable_value=0, gst_rate=18, tax_amount=0)]},
         "positive taxable value"),
    ],
)
def test_fields_missing(over, expected):
    ok, detail = check_invoice_fields(make_invoice(**over))
    assert not ok and expected in detail


# ---------------------------------------------------------------- 16(2)(aa) GSTR-2B

def rec(no, gstin=GSTIN):
    return Gstr2bRecord(supplier_gstin=gstin, invoice_no=no, invoice_date=date(2026, 10, 5),
                        taxable_value=1000, tax_amount=180)


def test_2b_exact_match():
    ok, detail = match_gstr2b(make_invoice(), [rec("INV/25-26/001")])
    assert ok and "exact" in detail


def test_2b_normalised_match():
    ok, detail = match_gstr2b(make_invoice(), [rec("INV-2526-001")])
    assert ok and "normalised" in detail


def test_2b_missing():
    ok, detail = match_gstr2b(make_invoice(), [rec("INV-2526-002")])
    assert not ok and "Not in GSTR-2B" in detail


def test_2b_same_number_other_supplier_does_not_match():
    ok, _ = match_gstr2b(make_invoice(), [rec("INV/25-26/001", gstin="27AAACR5055K1Z5")])
    assert not ok


def test_2b_cannot_match_without_number():
    ok, detail = match_gstr2b(make_invoice(invoice_no=None), [rec("INV/25-26/001")])
    assert not ok and "Cannot match" in detail


# ---------------------------------------------------------------- 16(2)(b) receipt

def test_receipt_ok():
    assert check_receipt(make_invoice(), AS_OF)[0]


def test_receipt_missing():
    ok, detail = check_receipt(make_invoice(received_on=None), AS_OF)
    assert not ok and "No receipt" in detail


def test_receipt_after_period():
    ok, detail = check_receipt(make_invoice(received_on=date(2026, 11, 2)), AS_OF)
    assert not ok and "after the period end" in detail


def test_receipt_on_last_day_ok():
    assert check_receipt(make_invoice(received_on=AS_OF), AS_OF)[0]


# ---------------------------------------------------------------- 180-day proviso

def test_day_180_unpaid_passes():
    inv = make_invoice(invoice_date=AS_OF - timedelta(days=180))
    ok, detail = check_180_days(inv, [], AS_OF)
    assert ok and "Day 180 of 180" in detail


def test_day_181_unpaid_fails():
    inv = make_invoice(invoice_date=AS_OF - timedelta(days=181))
    ok, detail = check_180_days(inv, [], AS_OF)
    assert not ok and "Day 181" in detail and "re-avail" in detail


def test_day_181_paid_passes():
    inv = make_invoice(invoice_date=AS_OF - timedelta(days=181))
    pay = Payment(supplier_gstin=GSTIN, invoice_no="INV-2526-001", paid_on=date(2026, 6, 1), amount=1180)
    ok, detail = check_180_days(inv, [pay], AS_OF)
    assert ok and "Paid in full" in detail


def test_day_181_partly_paid_fails():
    inv = make_invoice(invoice_date=AS_OF - timedelta(days=181))
    pay = Payment(supplier_gstin=GSTIN, invoice_no="INV/25-26/001", paid_on=date(2026, 6, 1), amount=500)
    ok, detail = check_180_days(inv, [pay], AS_OF)
    assert not ok and "680.00 unpaid" in detail


def test_payment_after_as_of_not_counted():
    inv = make_invoice(invoice_date=AS_OF - timedelta(days=200))
    pay = Payment(supplier_gstin=GSTIN, invoice_no="INV/25-26/001", paid_on=AS_OF + timedelta(days=1), amount=1180)
    assert not check_180_days(inv, [pay], AS_OF)[0]


def test_reverse_charge_exempt_from_180_days():
    inv = make_invoice(invoice_date=AS_OF - timedelta(days=400), reverse_charge=True)
    ok, detail = check_180_days(inv, [], AS_OF)
    assert ok and "Reverse-charge" in detail


def test_180_days_without_date_fails():
    assert not check_180_days(make_invoice(invoice_date=None), [], AS_OF)[0]


# ---------------------------------------------------------------- 16(4) time limit

def test_fy_label():
    assert fy_label(date(2026, 3, 31)) == "2025-26"
    assert fy_label(date(2026, 4, 1)) == "2026-27"


def test_deadline_is_30_nov_after_fy_end():
    assert section16_4_deadline(date(2025, 4, 1)) == date(2026, 11, 30)
    assert section16_4_deadline(date(2026, 3, 31)) == date(2026, 11, 30)
    assert section16_4_deadline(date(2026, 4, 1)) == date(2027, 11, 30)


def test_deadline_is_annual_return_date_if_earlier():
    assert section16_4_deadline(date(2025, 6, 1), date(2026, 9, 15)) == date(2026, 9, 15)


def test_deadline_ignores_annual_return_filed_later():
    assert section16_4_deadline(date(2025, 6, 1), date(2026, 12, 20)) == date(2026, 11, 30)


def test_claim_date_is_3b_due_date():
    assert claim_date_for("2026-10") == date(2026, 11, 20)
    assert claim_date_for("2026-12") == date(2027, 1, 20)


def test_time_limit_within():
    ok, detail = check_time_limit(make_invoice(invoice_date=date(2025, 12, 1)), PROFILE, date(2026, 11, 20))
    assert ok and "30 November" in detail


def test_time_limit_on_deadline_day_passes():
    assert check_time_limit(make_invoice(invoice_date=date(2025, 12, 1)), PROFILE, date(2026, 11, 30))[0]


def test_time_barred_after_30_nov():
    ok, detail = check_time_limit(make_invoice(invoice_date=date(2025, 2, 10)), PROFILE, date(2026, 11, 20))
    assert not ok and "Time-barred" in detail and "FY 2024-25" in detail


def test_time_barred_by_early_annual_return():
    profile = PROFILE.model_copy(update={"annual_returns_filed": {"2025-26": date(2026, 11, 5)}})
    ok, detail = check_time_limit(make_invoice(invoice_date=date(2026, 1, 15)), profile, date(2026, 11, 20))
    assert not ok and "annual return" in detail


def test_time_limit_without_date_fails():
    assert not check_time_limit(make_invoice(invoice_date=None), PROFILE, date(2026, 11, 20))[0]


# ---------------------------------------------------------------- wiring to the rule pack

def test_run_section16_maps_outcomes_from_pack():
    _, pack = load_packs("2026-10")
    inv = make_invoice(invoice_date=date(2025, 2, 10), received_on=None)
    results = {r.rule_id: r for r in run_section16(inv, [], [], PROFILE, "2026-10", pack)}
    assert set(results) == {"S16_2_A", "S16_2_AA", "S16_2_B", "S16_2_PROVISO_180", "S16_4"}
    assert results["S16_2_A"].passed
    assert not results["S16_2_AA"].passed and results["S16_2_AA"].outcome_on_fail == "Deferred"
    assert not results["S16_2_B"].passed
    assert not results["S16_2_PROVISO_180"].passed
    assert not results["S16_4"].passed and results["S16_4"].outcome_on_fail == "Blocked"
