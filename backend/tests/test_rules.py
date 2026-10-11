from datetime import date

from app.models import Vendor
from app.schemas import ExtractedInvoice
from app.services.decision import decide
from app.services.validation import ValidationContext, validate
from app.schemas import MatchResult, LineMatch
from app.utils.gst import gstin_valid, inr, make_gstin, parse_amount

VENDOR = Vendor(id=1, name="Shree Ganesh Packaging", gstin=make_gstin("27", "AAPFS7788Q"), state_code="27", pan="AAPFS7788Q",
                bank_account="37281900012", ifsc="MAHB0000412")


def inv(**kw):
    base = dict(vendor_name=VENDOR.name, vendor_gstin=VENDOR.gstin, buyer_gstin="27AAACA1234A1ZK", invoice_number="X1",
                invoice_date="2026-10-01", line_items=[dict(description="Box", hsn="4819", qty=10, unit_price=100, tax_rate=18, amount=1000)],
                subtotal=1000, cgst=90, sgst=90, total=1180, bank_account="37281900012", ifsc="MAHB0000412")
    base.update(kw)
    return ExtractedInvoice.model_validate(base)


def codes(i, **ctx):
    return {x.code for x in validate(i, ValidationContext(vendor=VENDOR, today=date(2026, 10, 11), **ctx))}


def test_gstin_checksum():
    assert gstin_valid("27AAPFU0939F1ZV")
    assert not gstin_valid("27AAPFU0939F1ZX")
    assert gstin_valid(make_gstin("33", "AAFFK9012M"))


def test_indian_amounts():
    assert parse_amount("₹1,25,000.50") == 125000.5
    assert inr(1250000) == "₹12,50,000.00"


def test_clean_invoice_has_no_issues():
    assert codes(inv()) == set()


def test_rules_fire():
    assert "WRONG_TAX_TYPE" in codes(inv(cgst=None, sgst=None, igst=180))
    assert "TOTAL_MISMATCH" in codes(inv(total=1280))
    assert "LINE_MATH" in codes(inv(line_items=[dict(description="Box", qty=10, unit_price=100, tax_rate=18, amount=1100)], subtotal=1100))
    assert "INVALID_GSTIN" in codes(inv(vendor_gstin=VENDOR.gstin[:14] + "0"))
    assert "BANK_CHANGE" in codes(inv(bank_account="999"))
    assert "DUPLICATE" in codes(inv(), duplicate_of=["invoice #1"])
    assert "FUTURE_DATED" in codes(inv(invoice_date="2027-01-01"))
    assert "LOW_CONFIDENCE" in codes(inv(confidence={"total": 0.4}))


def _match(ok=True):
    return MatchResult(po_number="PO", po_found=True, lines=[LineMatch(invoice_line_no=1, description="x", invoice_qty=1, invoice_price=1, status="matched" if ok else "price_variance")])


def test_decision_policy():
    assert decide([], _match(), 10_000).outcome == "AUTO_APPROVED"
    assert decide([], _match(), 60_000).outcome == "PENDING_APPROVAL"
    assert decide([], _match(), 300_000).approval_chain == ["AP Manager", "Finance Controller"]
    blockers = validate(inv(bank_account="999"), ValidationContext(vendor=VENDOR, today=date(2026, 10, 11)))
    assert decide(blockers, _match(), 1000).outcome == "ON_HOLD"
