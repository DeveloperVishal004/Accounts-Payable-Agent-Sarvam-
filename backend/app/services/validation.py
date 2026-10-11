"""Deterministic invoice validation. Each rule is a pure function: (invoice, ctx) -> list[IssueData]."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.config import settings
from app.models import Vendor
from app.schemas import ExtractedInvoice, IssueData
from app.utils.gst import GST_SLABS, gstin_valid, inr, state_of


@dataclass
class ValidationContext:
    vendor: Vendor | None
    buyer_gstin: str = settings.buyer_gstin
    duplicate_of: list[str] = field(default_factory=list)  # human refs of earlier matching invoices
    po_date: date | None = None
    today: date = field(default_factory=date.today)


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _blocker(code, msg, **kw) -> IssueData:
    return IssueData(code=code, severity="blocker", message=msg, **kw)


def _warning(code, msg, **kw) -> IssueData:
    return IssueData(code=code, severity="warning", message=msg, **kw)


# ---------------------------------------------------------------- rules

REQUIRED = {
    "invoice_number": "Invoice number",
    "invoice_date": "Invoice date",
    "vendor_gstin": "Supplier GSTIN",
    "total": "Invoice total",
}


def rule_required(inv: ExtractedInvoice, ctx: ValidationContext) -> list[IssueData]:
    issues = [
        _blocker("MISSING_FIELD", f"{label} could not be read from the document.", field=name)
        for name, label in REQUIRED.items()
        if getattr(inv, name) in (None, "")
    ]
    if not inv.line_items:
        issues.append(_blocker("MISSING_FIELD", "No line items could be read from the document.", field="line_items"))
    return issues


def rule_low_confidence(inv: ExtractedInvoice, ctx: ValidationContext) -> list[IssueData]:
    return [
        _warning(
            "LOW_CONFIDENCE",
            f"'{name}' was extracted with low confidence ({score:.0%}). Please verify against the document.",
            field=name,
            actual=str(getattr(inv, name, "")),
        )
        for name, score in sorted(inv.confidence.items())
        if score < settings.low_confidence_threshold
    ]


def rule_gstin(inv: ExtractedInvoice, ctx: ValidationContext) -> list[IssueData]:
    issues: list[IssueData] = []
    if inv.vendor_gstin and not gstin_valid(inv.vendor_gstin):
        issues.append(
            _blocker(
                "INVALID_GSTIN",
                "Supplier GSTIN fails the GST checksum. It may be mistyped or fake, and input tax credit would be at risk.",
                field="vendor_gstin",
                actual=inv.vendor_gstin,
                expected=ctx.vendor.gstin if ctx.vendor else None,
                amount_at_risk=(inv.cgst or 0) + (inv.sgst or 0) + (inv.igst or 0),
            )
        )
    if ctx.vendor is None:
        issues.append(
            _blocker(
                "UNKNOWN_VENDOR",
                "Supplier is not in the vendor master. Onboard and verify the vendor before paying.",
                field="vendor_name",
                actual=inv.vendor_name,
            )
        )
    elif inv.vendor_gstin and gstin_valid(inv.vendor_gstin) and inv.vendor_gstin != ctx.vendor.gstin:
        issues.append(
            _blocker(
                "GSTIN_MISMATCH",
                "Supplier GSTIN on the invoice differs from the vendor master.",
                field="vendor_gstin",
                expected=ctx.vendor.gstin,
                actual=inv.vendor_gstin,
            )
        )
    if inv.buyer_gstin and inv.buyer_gstin != ctx.buyer_gstin:
        issues.append(
            _warning(
                "BUYER_GSTIN_MISMATCH",
                "Invoice is billed to a different GSTIN than ours, so input tax credit cannot be claimed.",
                field="buyer_gstin",
                expected=ctx.buyer_gstin,
                actual=inv.buyer_gstin,
            )
        )
    return issues


def rule_arithmetic(inv: ExtractedInvoice, ctx: ValidationContext) -> list[IssueData]:
    issues: list[IssueData] = []
    tol = settings.line_amount_tolerance_abs
    for i, line in enumerate(inv.line_items, start=1):
        calc = round(line.qty * line.unit_price, 2)
        if not _close(calc, line.amount, tol):
            issues.append(
                _blocker(
                    "LINE_MATH",
                    f"Line {i}: {line.qty:g} × {inr(line.unit_price)} = {inr(calc)}, but the invoice shows {inr(line.amount)}.",
                    field=f"line_items[{i}].amount",
                    expected=f"{calc:.2f}",
                    actual=f"{line.amount:.2f}",
                    amount_at_risk=max(0.0, line.amount - calc),
                )
            )
    if inv.line_items and inv.subtotal is not None:
        lines_sum = round(sum(line.amount for line in inv.line_items), 2)
        if not _close(lines_sum, inv.subtotal, tol):
            issues.append(
                _blocker(
                    "SUBTOTAL_MISMATCH",
                    f"Line items add up to {inr(lines_sum)}, but the subtotal is {inr(inv.subtotal)}.",
                    field="subtotal",
                    expected=f"{lines_sum:.2f}",
                    actual=f"{inv.subtotal:.2f}",
                    amount_at_risk=max(0.0, inv.subtotal - lines_sum),
                )
            )
    if inv.subtotal is not None and inv.total is not None:
        calc_total = round(inv.subtotal + (inv.cgst or 0) + (inv.sgst or 0) + (inv.igst or 0), 2)
        if not _close(calc_total, inv.total, tol):
            issues.append(
                _blocker(
                    "TOTAL_MISMATCH",
                    f"Subtotal + GST = {inr(calc_total)}, but the invoice total is {inr(inv.total)}.",
                    field="total",
                    expected=f"{calc_total:.2f}",
                    actual=f"{inv.total:.2f}",
                    amount_at_risk=max(0.0, inv.total - calc_total),
                )
            )
    return issues


def rule_tax(inv: ExtractedInvoice, ctx: ValidationContext) -> list[IssueData]:
    issues: list[IssueData] = []
    seller_state = state_of(inv.vendor_gstin) or (ctx.vendor.state_code if ctx.vendor else None)
    buyer_state = state_of(ctx.buyer_gstin)
    cgst, sgst, igst = inv.cgst or 0, inv.sgst or 0, inv.igst or 0

    if seller_state and buyer_state:
        intra = seller_state == buyer_state
        if intra and igst > 0:
            issues.append(
                _blocker(
                    "WRONG_TAX_TYPE",
                    "Supplier and buyer are in the same state, so CGST + SGST applies, but IGST was charged.",
                    field="igst",
                    expected="CGST + SGST",
                    actual=f"IGST {inr(igst)}",
                )
            )
        if not intra and (cgst > 0 or sgst > 0):
            issues.append(
                _blocker(
                    "WRONG_TAX_TYPE",
                    "This is an inter-state supply, so IGST applies, but CGST/SGST was charged.",
                    field="cgst",
                    expected="IGST",
                    actual=f"CGST {inr(cgst)} + SGST {inr(sgst)}",
                )
            )
    if cgst and sgst and not _close(cgst, sgst, 1.0):
        issues.append(_warning("CGST_SGST_UNEQUAL", "CGST and SGST should be equal.", expected=f"{cgst:.2f}", actual=f"{sgst:.2f}"))

    for i, line in enumerate(inv.line_items, start=1):
        if line.tax_rate is not None and line.tax_rate not in GST_SLABS:
            issues.append(_warning("INVALID_TAX_RATE", f"Line {i}: {line.tax_rate:g}% is not a valid GST slab.", field=f"line_items[{i}].tax_rate"))

    if inv.line_items and all(line.tax_rate is not None for line in inv.line_items):
        expected_tax = round(sum(line.amount * line.tax_rate / 100 for line in inv.line_items), 2)
        actual_tax = round(cgst + sgst + igst, 2)
        if not _close(expected_tax, actual_tax, settings.line_amount_tolerance_abs):
            issues.append(
                _blocker(
                    "TAX_AMOUNT_MISMATCH",
                    f"GST should be {inr(expected_tax)} at the stated rates, but {inr(actual_tax)} was charged.",
                    field="tax",
                    expected=f"{expected_tax:.2f}",
                    actual=f"{actual_tax:.2f}",
                    amount_at_risk=max(0.0, actual_tax - expected_tax),
                )
            )
    return issues


def rule_duplicate(inv: ExtractedInvoice, ctx: ValidationContext) -> list[IssueData]:
    if not ctx.duplicate_of:
        return []
    return [
        _blocker(
            "DUPLICATE",
            f"Possible duplicate of {', '.join(ctx.duplicate_of)}. Paying it would pay the same bill twice.",
            field="invoice_number",
            actual=inv.invoice_number,
            amount_at_risk=inv.total or 0.0,
        )
    ]


def rule_dates(inv: ExtractedInvoice, ctx: ValidationContext) -> list[IssueData]:
    issues: list[IssueData] = []
    if inv.invoice_date and inv.invoice_date > ctx.today:
        issues.append(_blocker("FUTURE_DATED", "Invoice is dated in the future.", field="invoice_date", actual=str(inv.invoice_date)))
    if inv.invoice_date and ctx.po_date and inv.invoice_date < ctx.po_date:
        issues.append(
            _warning(
                "INVOICE_BEFORE_PO",
                "Invoice is dated before the purchase order was raised.",
                field="invoice_date",
                expected=f">= {ctx.po_date}",
                actual=str(inv.invoice_date),
            )
        )
    if ctx.vendor and ctx.vendor.msme:
        issues.append(
            IssueData(
                code="MSME_VENDOR",
                severity="info",
                message=f"MSME supplier: payment must be made within {settings.msme_max_payment_days} days (MSMED Act, Sec 43B(h)).",
            )
        )
    return issues


def rule_bank(inv: ExtractedInvoice, ctx: ValidationContext) -> list[IssueData]:
    if not ctx.vendor or not inv.bank_account:
        return []
    if inv.bank_account != ctx.vendor.bank_account or (inv.ifsc and inv.ifsc != ctx.vendor.ifsc):
        return [
            _blocker(
                "BANK_CHANGE",
                "Bank details on the invoice differ from the verified vendor master. This is a classic payment-fraud "
                "signal, so confirm with the vendor by phone before paying.",
                field="bank_account",
                expected=f"{ctx.vendor.bank_account} / {ctx.vendor.ifsc}",
                actual=f"{inv.bank_account} / {inv.ifsc or '—'}",
                amount_at_risk=inv.total or 0.0,
            )
        ]
    return []


RULES: list[Callable[[ExtractedInvoice, ValidationContext], list[IssueData]]] = [
    rule_required,
    rule_low_confidence,
    rule_gstin,
    rule_arithmetic,
    rule_tax,
    rule_duplicate,
    rule_dates,
    rule_bank,
]


def validate(inv: ExtractedInvoice, ctx: ValidationContext) -> list[IssueData]:
    return [issue for rule in RULES for issue in rule(inv, ctx)]
