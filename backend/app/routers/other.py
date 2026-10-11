from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.erp.mock_erp import MockERP
from app.models import Approval, AuditEvent, Invoice, InvoiceStatus, Issue, Payment, Vendor
from app.services import usage
from app.services.pipeline import audit

router = APIRouter(tags=["workflow"])


@router.get("/approvals")
def approvals(role: str | None = None, s: Session = Depends(get_session)):
    q = select(Approval, Invoice).join(Invoice, Invoice.id == Approval.invoice_id).where(Approval.status == "PENDING")
    if role:
        q = q.where(Approval.approver_role == role)
    return [
        {"approval": a, "invoice": inv.model_dump(include={"id", "vendor_name", "invoice_number", "total", "due_date", "explanation", "status"})}
        for a, inv in s.exec(q)
    ]


@router.get("/payments")
def payments(s: Session = Depends(get_session)):
    rows = s.exec(
        select(Payment, Invoice, Vendor)
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .join(Vendor, Vendor.id == Payment.vendor_id)
        .order_by(Payment.id.desc())
    )
    return [
        {
            **p.model_dump(),
            "invoice_number": inv.invoice_number,
            "vendor_name": v.name,
            "bank_account": "XXXX" + v.bank_account[-4:],
            "ifsc": v.ifsc,
            "msme": v.msme,
        }
        for p, inv, v in rows
    ]


@router.post("/payments/run")
def run_payments(s: Session = Depends(get_session)):
    run_id, paid = MockERP(s).execute_payment_run()
    for p in paid:
        inv = s.get(Invoice, p.invoice_id)
        inv.status = InvoiceStatus.PAID
        s.add(inv)
        audit(s, inv.id, "paid", actor="erp", run_id=run_id, utr=p.utr, amount=p.amount)
    s.commit()
    return {"run_id": run_id, "count": len(paid), "amount": round(sum(p.amount for p in paid), 2)}


@router.get("/dashboard/stats")
def stats(s: Session = Depends(get_session)):
    invs = list(s.exec(select(Invoice)))
    by_status: dict[str, int] = {}
    for i in invs:
        by_status[i.status] = by_status.get(i.status, 0) + 1
    decided = [i for i in invs if i.decision]
    auto = sum(1 for i in decided if i.decision.get("outcome") == "AUTO_APPROVED")
    times = [(i.processed_at - i.created_at).total_seconds() for i in invs if i.processed_at]
    # money saved = blocker amount-at-risk on invoices that did not get paid as billed
    saved = sum(i.amount_at_risk for i in invs if i.status in (InvoiceStatus.ON_HOLD, InvoiceStatus.REJECTED))
    issue_counts: dict[str, int] = {}
    for iss in s.exec(select(Issue).where(Issue.severity == "blocker")):
        issue_counts[iss.code] = issue_counts.get(iss.code, 0) + 1
    return {
        "total": len(invs),
        "by_status": by_status,
        "processed_today": sum(1 for i in invs if i.created_at.date() == date.today()),
        "auto_approval_rate": round(auto / len(decided) * 100, 1) if decided else 0.0,
        "on_hold": by_status.get(InvoiceStatus.ON_HOLD, 0),
        "pending_amount": round(
            sum(i.total or 0 for i in invs if i.status in (InvoiceStatus.PENDING_APPROVAL, InvoiceStatus.ON_HOLD, InvoiceStatus.SCHEDULED)), 2
        ),
        "paid_amount": round(sum(i.total or 0 for i in invs if i.status == InvoiceStatus.PAID), 2),
        "avg_processing_seconds": round(sum(times) / len(times), 1) if times else None,
        "money_saved": round(saved, 2),
        "blockers_by_code": dict(sorted(issue_counts.items(), key=lambda kv: -kv[1])),
        "usage": usage.totals(s),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


@router.get("/usage")
def get_usage(s: Session = Depends(get_session)):
    return usage.totals(s)


@router.get("/erp/vendors")
def vendors(s: Session = Depends(get_session)):
    return MockERP(s).list_vendors()


@router.get("/erp/pos")
def pos(s: Session = Depends(get_session)):
    erp = MockERP(s)
    out = []
    for po in erp.list_pos():
        lines = erp.get_po_lines(po.id)
        out.append(
            {
                **po.model_dump(),
                "vendor_name": s.get(Vendor, po.vendor_id).name,
                "lines": [
                    {**pl.model_dump(), "received": erp.received_qty(po.id, pl.line_no), "invoiced": erp.invoiced_qty(po.id, pl.line_no)}
                    for pl in lines
                ],
            }
        )
    return out


@router.get("/audit")
def recent_audit(limit: int = 50, s: Session = Depends(get_session)):
    return s.exec(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)).all()


@router.post("/demo/reset")
def reset_demo():
    """Wipe invoices and reseed the ERP. Sarvam cache and usage are kept, so the budget stays honest."""
    from app.services.pipeline import PROGRESS
    from seed import seed_erp

    seed_erp.main()
    PROGRESS.clear()
    return {"ok": True}
