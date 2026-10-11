"""Orchestrates parse → extract → validate → match → decide → (auto) schedule, with audit + live progress."""

import asyncio
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, delete, or_, select

from app.config import settings
from app.db import engine
from app.erp.mock_erp import MockERP
from app.models import (
    Approval,
    AuditEvent,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Issue,
    Severity,
)
from app.schemas import ExtractedInvoice, IssueData
from app.services import extraction
from app.services.decision import decide
from app.services.explain import template_summary
from app.services.matching import three_way_match
from app.services.validation import ValidationContext, validate

STEPS = ["parse", "extract", "validate", "match", "decide"]

# invoice_id -> list of progress events (read by the SSE endpoint)
PROGRESS: dict[int, list[dict]] = {}

# At most 2 invoices hit Sarvam at once: protects rate limits, credits and the SQLite connection pool.
_SLOTS = asyncio.Semaphore(2)


def emit(invoice_id: int, step: str, status: str, message: str = "") -> None:
    PROGRESS.setdefault(invoice_id, []).append(
        {"step": step, "status": status, "message": message, "ts": datetime.now().isoformat(timespec="seconds")}
    )


def audit(s: Session, invoice_id: int | None, action: str, actor: str = "agent", **detail) -> None:
    s.add(AuditEvent(invoice_id=invoice_id, actor=actor, action=action, detail=detail or None))


# ---------------------------------------------------------------- entry point


async def process_invoice(invoice_id: int) -> None:
    emit(invoice_id, "queue", "running", "Waiting for a processing slot")
    async with _SLOTS:
        await _process(invoice_id)


async def _process(invoice_id: int) -> None:
    started = time.monotonic()
    with Session(engine) as s:
        inv = s.get(Invoice, invoice_id)
        path = Path(inv.file_path)
        step = "parse"
        try:
            emit(invoice_id, "parse", "running", "Reading document with Sarvam Vision")
            md, cached = await extraction.parse(path, inv.file_hash, invoice_id)
            inv.raw_markdown = md
            inv.status = InvoiceStatus.PARSED
            audit(s, invoice_id, "document_parsed", chars=len(md), cached=cached)
            s.add(inv)
            s.commit()
            emit(invoice_id, "parse", "done", "cached, no credits used" if cached else f"{len(md):,} characters read")

            step = "extract"
            emit(invoice_id, "extract", "running", "Extracting fields with Sarvam-105B")
            ex, cached = await extraction.extract(md, path, inv.file_hash, invoice_id)
            apply_extracted(s, inv, ex)
            audit(s, invoice_id, "fields_extracted", cached=cached, lines=len(ex.line_items))
            s.commit()
            emit(invoice_id, "extract", "done", f"{len(ex.line_items)} line items" + (" (cached)" if cached else ""))

            evaluate(s, inv, ex)
            inv.processed_at = datetime.now()
            audit(s, invoice_id, "processing_complete", seconds=round(time.monotonic() - started, 1))
            s.add(inv)
            s.commit()
        except Exception as err:  # noqa: BLE001  (surface every failure on the invoice, never crash the worker)
            s.rollback()
            inv = s.get(Invoice, invoice_id)
            inv.status = InvoiceStatus.FAILED
            s.add(
                Issue(
                    invoice_id=invoice_id,
                    code="PROCESSING_ERROR",
                    severity=Severity.BLOCKER,
                    message=f"{type(err).__name__}: {err}",
                )
            )
            audit(s, invoice_id, "processing_failed", step=step, error=str(err)[:500])
            s.add(inv)
            s.commit()
            emit(invoice_id, step, "error", str(err)[:300])
    emit(invoice_id, "complete", "done")


# ---------------------------------------------------------------- steps


def apply_extracted(s: Session, inv: Invoice, ex: ExtractedInvoice) -> None:
    inv.extracted = ex.model_dump(mode="json")
    inv.confidence = ex.confidence
    for f in [
        "vendor_name", "vendor_gstin", "buyer_gstin", "invoice_number", "invoice_date", "po_number",
        "subtotal", "cgst", "sgst", "igst", "total", "bank_account", "ifsc", "language",
    ]:
        setattr(inv, f, getattr(ex, f))
    s.exec(delete(InvoiceLine).where(InvoiceLine.invoice_id == inv.id))
    for n, line in enumerate(ex.line_items, start=1):
        s.add(
            InvoiceLine(
                invoice_id=inv.id, line_no=n, description=line.description, hsn=line.hsn, qty=line.qty,
                unit_price=line.unit_price, tax_rate=line.tax_rate, amount=line.amount,
            )
        )
    inv.status = InvoiceStatus.EXTRACTED
    s.add(inv)


def _duplicates(s: Session, inv: Invoice, ex: ExtractedInvoice) -> list[str]:
    conds = [Invoice.file_hash == inv.file_hash]
    if inv.vendor_id and ex.invoice_number:
        conds.append((Invoice.vendor_id == inv.vendor_id) & (Invoice.invoice_number == ex.invoice_number))
    if inv.vendor_id and ex.total and ex.invoice_date:
        conds.append(
            (Invoice.vendor_id == inv.vendor_id)
            & (Invoice.total == ex.total)
            & (Invoice.invoice_date.between(ex.invoice_date - timedelta(days=3), ex.invoice_date + timedelta(days=3)))
        )
    q = select(Invoice).where(Invoice.id < inv.id, Invoice.status != InvoiceStatus.FAILED, or_(*conds))
    return [f"invoice #{d.id} ({d.invoice_number}, {d.status})" for d in s.exec(q)]


def evaluate(s: Session, inv: Invoice, ex: ExtractedInvoice) -> None:
    """Validate + match + decide. Re-run whenever a human corrects a field."""
    erp = MockERP(s)
    vendor = erp.find_vendor(ex.vendor_gstin, ex.vendor_name)
    inv.vendor_id = vendor.id if vendor else None

    emit(inv.id, "match", "running", "3-way matching against PO and GRN")
    match = three_way_match(ex, vendor, erp, invoice_id=inv.id)
    po = erp.get_po(match.po_number) if match.po_number else None
    inv.po_id = po.id if po else None
    if po and not inv.po_number:
        inv.po_number = po.po_number

    emit(inv.id, "validate", "running", "Running GST, arithmetic, duplicate and fraud checks")
    ctx = ValidationContext(vendor=vendor, duplicate_of=_duplicates(s, inv, ex), po_date=po.po_date if po else None)
    issues: list[IssueData] = validate(ex, ctx) + match.issues
    inv.status = InvoiceStatus.VALIDATED
    emit(inv.id, "validate", "done", f"{sum(i.severity == 'blocker' for i in issues)} blocker(s), {sum(i.severity == 'warning' for i in issues)} warning(s)")

    for lm in match.lines:
        line = s.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id, InvoiceLine.line_no == lm.invoice_line_no)).first()
        if line:
            line.matched_po_line_no = lm.po_line_no
            s.add(line)
    inv.match_result = match.model_dump(mode="json")
    inv.status = InvoiceStatus.MATCHED
    emit(inv.id, "match", "done", f"PO {match.po_number}: {sum(line.status == 'matched' for line in match.lines)}/{len(match.lines)} lines matched" if match.po_found else "No PO found")

    s.exec(delete(Issue).where(Issue.invoice_id == inv.id))
    for i in issues:
        s.add(Issue(invoice_id=inv.id, **i.model_dump(exclude={"amount_at_risk"})))
    inv.amount_at_risk = round(min(inv.total or 0.0, sum(i.amount_at_risk for i in issues if i.severity == "blocker")), 2)

    # due date: vendor terms, capped at 45 days for MSME suppliers
    if ex.invoice_date:
        terms = vendor.payment_terms_days if vendor else 30
        if vendor and vendor.msme:
            terms = min(terms, settings.msme_max_payment_days)
        inv.due_date = ex.invoice_date + timedelta(days=terms)

    decision = decide(issues, match, ex.total)
    inv.decision = decision.model_dump()
    s.exec(delete(Approval).where(Approval.invoice_id == inv.id))
    audit(s, inv.id, "decision", outcome=decision.outcome, reasons=decision.reasons)

    if decision.outcome == "AUTO_APPROVED":
        inv.status = InvoiceStatus.APPROVED
        audit(s, inv.id, "auto_approved", limit=settings.auto_approve_limit)
        schedule(s, inv, actor="agent")
    elif decision.outcome == "PENDING_APPROVAL":
        inv.status = InvoiceStatus.PENDING_APPROVAL
        for level, role in enumerate(decision.approval_chain, start=1):
            s.add(Approval(invoice_id=inv.id, level=level, approver_role=role, status="PENDING" if level == 1 else "WAITING"))
    else:
        inv.status = InvoiceStatus.ON_HOLD

    s.flush()
    inv.explanation = template_summary(inv, list(s.exec(select(Issue).where(Issue.invoice_id == inv.id))))
    s.add(inv)
    emit(inv.id, "decide", "done", decision.outcome.replace("_", " ").title())


# ---------------------------------------------------------------- human workflow


class WorkflowError(ValueError):
    pass


def schedule(s: Session, inv: Invoice, actor: str) -> None:
    erp = MockERP(s)
    inv.erp_bill_id = erp.post_bill(inv)
    pay_on = max(inv.due_date or date.today(), date.today())
    erp.schedule_payment(inv, pay_on)
    inv.status = InvoiceStatus.SCHEDULED
    audit(s, inv.id, "bill_posted", actor=actor, bill_id=inv.erp_bill_id)
    audit(s, inv.id, "payment_scheduled", actor=actor, pay_on=str(pay_on), amount=inv.total)


def approve(s: Session, inv: Invoice, actor: str, role: str | None, comment: str | None) -> None:
    if inv.status == InvoiceStatus.ON_HOLD:
        if not comment:
            raise WorkflowError("Overriding a hold requires a comment explaining why.")
        audit(s, inv.id, "hold_overridden", actor=actor, comment=comment)
        inv.status = InvoiceStatus.APPROVED
        schedule(s, inv, actor)
        return
    if inv.status != InvoiceStatus.PENDING_APPROVAL:
        raise WorkflowError(f"Invoice is {inv.status}; it cannot be approved.")

    pending = s.exec(select(Approval).where(Approval.invoice_id == inv.id, Approval.status == "PENDING")).first()
    if pending is None:
        raise WorkflowError("No pending approval step.")
    if role and role != pending.approver_role:
        raise WorkflowError(f"This step needs approval from {pending.approver_role}.")
    pending.status, pending.decided_by, pending.comment, pending.decided_at = "APPROVED", actor, comment, datetime.now()
    s.add(pending)
    audit(s, inv.id, "approved", actor=actor, level=pending.level, role=pending.approver_role, comment=comment)

    nxt = s.exec(select(Approval).where(Approval.invoice_id == inv.id, Approval.status == "WAITING").order_by(Approval.level)).first()
    if nxt:
        nxt.status = "PENDING"
        s.add(nxt)
    else:
        inv.status = InvoiceStatus.APPROVED
        schedule(s, inv, actor)


def reject(s: Session, inv: Invoice, actor: str, comment: str | None) -> None:
    if inv.status in (InvoiceStatus.SCHEDULED, InvoiceStatus.PAID):
        raise WorkflowError(f"Invoice is already {inv.status}.")
    inv.status = InvoiceStatus.REJECTED
    for a in s.exec(select(Approval).where(Approval.invoice_id == inv.id, Approval.status.in_(["PENDING", "WAITING"]))):
        a.status = "REJECTED" if a.status == "PENDING" else "CANCELLED"
        a.decided_by, a.decided_at, a.comment = actor, datetime.now(), comment
        s.add(a)
    audit(s, inv.id, "rejected", actor=actor, comment=comment)


def hold(s: Session, inv: Invoice, actor: str, comment: str | None) -> None:
    if inv.status in (InvoiceStatus.SCHEDULED, InvoiceStatus.PAID, InvoiceStatus.REJECTED):
        raise WorkflowError(f"Invoice is already {inv.status}.")
    inv.status = InvoiceStatus.ON_HOLD
    audit(s, inv.id, "put_on_hold", actor=actor, comment=comment)


EDITABLE = {InvoiceStatus.ON_HOLD, InvoiceStatus.PENDING_APPROVAL, InvoiceStatus.MATCHED, InvoiceStatus.VALIDATED, InvoiceStatus.EXTRACTED}


def correct_fields(s: Session, inv: Invoice, fields: dict, actor: str) -> None:
    """Human correction of extracted fields → re-validate and re-match (no Sarvam call)."""
    if inv.status not in EDITABLE or not inv.extracted:
        raise WorkflowError(f"Invoice is {inv.status}; fields can no longer be edited.")
    data = dict(inv.extracted)
    before = {k: data.get(k) for k in fields}
    data.update(fields)
    conf = dict(data.get("confidence") or {})
    for k in fields:
        conf[k] = 1.0  # human-verified
    data["confidence"] = conf
    ex = ExtractedInvoice.model_validate(data)
    apply_extracted(s, inv, ex)
    audit(s, inv.id, "fields_corrected", actor=actor, before=before, after=fields)
    evaluate(s, inv, ex)


# ---------------------------------------------------------------- onboarding real-world invoices


def _extracted(inv: Invoice) -> ExtractedInvoice:
    if not inv.extracted:
        raise WorkflowError("Invoice has no extracted data yet.")
    return ExtractedInvoice.model_validate(inv.extracted)


def onboard_vendor(s: Session, inv: Invoice, actor: str) -> None:
    """Add the invoice's supplier to the vendor master (after a human confirms), then re-check."""
    from app.models import Vendor
    from app.utils.gst import gstin_valid

    ex = _extracted(inv)
    if inv.vendor_id:
        raise WorkflowError("Vendor is already in the master.")
    if not ex.vendor_gstin or not gstin_valid(ex.vendor_gstin):
        raise WorkflowError("A valid supplier GSTIN is needed to onboard a vendor. Correct the GSTIN field first.")
    if s.exec(select(Vendor).where(Vendor.gstin == ex.vendor_gstin)).first():
        raise WorkflowError("A vendor with this GSTIN already exists.")
    vendor = Vendor(
        name=ex.vendor_name or ex.vendor_gstin,
        gstin=ex.vendor_gstin,
        state_code=ex.vendor_gstin[:2],
        pan=ex.vendor_gstin[2:12],
        bank_account=ex.bank_account or "",
        ifsc=ex.ifsc or "",
        payment_terms_days=30,
        preferred_language=ex.language if ex.language and "-" in ex.language else "en-IN",
    )
    s.add(vendor)
    s.flush()
    audit(s, inv.id, "vendor_onboarded", actor=actor, vendor_id=vendor.id, gstin=vendor.gstin)
    evaluate(s, inv, ex)


def create_retro_po(s: Session, inv: Invoice, actor: str) -> None:
    """Raise a retrospective PO + GRN mirroring the invoice lines (a human attests the goods arrived), then re-check."""
    from app.models import GoodsReceipt, GRNLine, POLine, PurchaseOrder

    ex = _extracted(inv)
    if not inv.vendor_id:
        raise WorkflowError("Onboard the vendor first.")
    if inv.po_id:
        raise WorkflowError(f"Invoice is already matched to {inv.po_number}.")
    if not ex.line_items:
        raise WorkflowError("No line items to build a PO from.")
    n = len(s.exec(select(PurchaseOrder)).all()) + 1
    po_number = f"PO-RETRO-{n:04d}"
    po = PurchaseOrder(
        po_number=po_number, vendor_id=inv.vendor_id, po_date=ex.invoice_date or date.today(),
        total=ex.total or 0.0, status="OPEN",
    )
    s.add(po)
    s.flush()
    grn = GoodsReceipt(grn_number=f"GRN-RETRO-{n:04d}", po_id=po.id, received_date=date.today())
    s.add(grn)
    s.flush()
    for i, line in enumerate(ex.line_items, start=1):
        s.add(POLine(po_id=po.id, line_no=i, description=line.description, hsn=line.hsn or "", qty=line.qty,
                     unit_price=line.unit_price, tax_rate=line.tax_rate or 0.0))
        s.add(GRNLine(grn_id=grn.id, po_line_no=i, qty_received=line.qty))
    ex.po_number = po_number
    inv.po_number = po_number
    inv.extracted = {**ex.model_dump(mode="json")}
    s.flush()
    audit(s, inv.id, "retro_po_raised", actor=actor, po_number=po_number, grn=grn.grn_number)
    evaluate(s, inv, ex)
