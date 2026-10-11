"""SQLite-backed mock ERP. Shares the app database so the demo is a single file."""

import secrets
from datetime import date, datetime

from rapidfuzz import fuzz, process
from sqlmodel import Session, func, select

from app.models import (
    GoodsReceipt,
    GRNLine,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Payment,
    POLine,
    PurchaseOrder,
    Vendor,
)

COMMITTED_STATUSES = [InvoiceStatus.APPROVED, InvoiceStatus.SCHEDULED, InvoiceStatus.PAID]


class MockERP:
    def __init__(self, session: Session):
        self.s = session

    # ------------------------------------------------------------ vendors
    def get_vendor(self, vendor_id: int) -> Vendor | None:
        return self.s.get(Vendor, vendor_id)

    def list_vendors(self) -> list[Vendor]:
        return list(self.s.exec(select(Vendor)))

    def find_vendor(self, gstin: str | None, name: str | None) -> Vendor | None:
        if gstin:
            v = self.s.exec(select(Vendor).where(Vendor.gstin == gstin)).first()
            if v:
                return v
            # GSTIN with one bad char (OCR slip or tampered checksum) → same PAN
            pan = gstin[2:12] if len(gstin) >= 12 else None
            if pan:
                v = self.s.exec(select(Vendor).where(Vendor.pan == pan)).first()
                if v:
                    return v
        if name:
            vendors = self.list_vendors()
            best = process.extractOne(name, {v.id: v.name for v in vendors}, scorer=fuzz.token_set_ratio)
            if best and best[1] >= 85:
                return self.s.get(Vendor, best[2])
        return None

    # ------------------------------------------------------------ POs
    def get_po(self, po_number: str) -> PurchaseOrder | None:
        norm = po_number.strip().upper().replace(" ", "")
        return self.s.exec(select(PurchaseOrder).where(func.upper(PurchaseOrder.po_number) == norm)).first()

    def get_po_lines(self, po_id: int) -> list[POLine]:
        return list(self.s.exec(select(POLine).where(POLine.po_id == po_id).order_by(POLine.line_no)))

    def open_pos_for_vendor(self, vendor_id: int) -> list[PurchaseOrder]:
        q = select(PurchaseOrder).where(PurchaseOrder.vendor_id == vendor_id, PurchaseOrder.status == "OPEN")
        return list(self.s.exec(q))

    def list_pos(self) -> list[PurchaseOrder]:
        return list(self.s.exec(select(PurchaseOrder).order_by(PurchaseOrder.po_number)))

    # ------------------------------------------------------------ receipts / invoiced qty
    def get_grns(self, po_id: int) -> list[tuple[GoodsReceipt, list[GRNLine]]]:
        grns = self.s.exec(select(GoodsReceipt).where(GoodsReceipt.po_id == po_id)).all()
        return [(g, list(self.s.exec(select(GRNLine).where(GRNLine.grn_id == g.id)))) for g in grns]

    def received_qty(self, po_id: int, po_line_no: int) -> float:
        q = (
            select(func.coalesce(func.sum(GRNLine.qty_received), 0.0))
            .join(GoodsReceipt, GoodsReceipt.id == GRNLine.grn_id)
            .where(GoodsReceipt.po_id == po_id, GRNLine.po_line_no == po_line_no)
        )
        return float(self.s.exec(q).one())

    def invoiced_qty(self, po_id: int, po_line_no: int, exclude_invoice_id: int | None = None) -> float:
        q = (
            select(func.coalesce(func.sum(InvoiceLine.qty), 0.0))
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(
                Invoice.po_id == po_id,
                InvoiceLine.matched_po_line_no == po_line_no,
                Invoice.status.in_(COMMITTED_STATUSES),
            )
        )
        if exclude_invoice_id is not None:
            q = q.where(Invoice.id != exclude_invoice_id)
        return float(self.s.exec(q).one())

    # ------------------------------------------------------------ AP postings
    def post_bill(self, invoice: Invoice) -> str:
        return f"BILL-{date.today():%Y%m}-{invoice.id:05d}"

    def schedule_payment(self, invoice: Invoice, pay_on: date) -> Payment:
        payment = Payment(
            invoice_id=invoice.id,
            vendor_id=invoice.vendor_id,
            amount=invoice.total or 0.0,
            scheduled_date=pay_on,
        )
        self.s.add(payment)
        return payment

    def execute_payment_run(self) -> tuple[str, list[Payment]]:
        run_id = f"RUN-{datetime.now():%Y%m%d-%H%M%S}"
        due = list(self.s.exec(select(Payment).where(Payment.status == "SCHEDULED")))
        for p in due:
            p.status = "PAID"
            p.run_id = run_id
            p.utr = f"UTR{secrets.token_hex(6).upper()}"
            p.paid_at = datetime.now()
            self.s.add(p)
        return run_id, due
