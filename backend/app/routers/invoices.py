import asyncio
import hashlib
import json
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.db import get_session
from app.models import Approval, AuditEvent, Invoice, InvoiceLine, Issue, Payment, Vendor
from app.schemas import ActionIn, FieldPatch
from app.services import explain, pipeline
from app.services.usage import BudgetExceeded

router = APIRouter(prefix="/invoices", tags=["invoices"])

ALLOWED = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_BYTES = 20 * 1024 * 1024


def _get(s: Session, invoice_id: int) -> Invoice:
    inv = s.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


MAX_FILES_PER_UPLOAD = 10


def _create(s: Session, background: BackgroundTasks, filename: str, data: bytes, actor: str = "user") -> dict:
    name = re.sub(r"[^\w.\-]", "_", filename or "invoice")
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED:
        raise HTTPException(400, f"{filename}: only PDF, PNG and JPG are supported")
    if len(data) > MAX_BYTES:
        raise HTTPException(400, f"{filename}: file larger than 20 MB")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    path = settings.upload_dir / f"{digest[:12]}__{name}"
    path.write_bytes(data)
    inv = Invoice(file_name=filename or name, file_path=str(path), file_hash=digest)
    s.add(inv)
    s.commit()
    s.refresh(inv)
    pipeline.audit(s, inv.id, "uploaded", actor=actor, file=inv.file_name, sha256=digest)
    s.commit()
    pipeline.emit(inv.id, "upload", "done", inv.file_name)
    background.add_task(pipeline.process_invoice, inv.id)
    return {"id": inv.id, "file_name": inv.file_name}


@router.post("", status_code=201)
async def upload(files: list[UploadFile], background: BackgroundTasks, s: Session = Depends(get_session)):
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(400, f"At most {MAX_FILES_PER_UPLOAD} files per upload")
    return [_create(s, background, f.filename or "invoice", await f.read()) for f in files]


@router.post("/demo", status_code=201)
def load_demo(background: BackgroundTasks, s: Session = Depends(get_session)):
    """Queue the 8 bundled sample invoices. Their Sarvam results are pre-cached, so this spends no credits."""
    files = sorted(p for p in settings.samples_dir.iterdir() if p.suffix.lower() in ALLOWED)
    return [_create(s, background, p.name, p.read_bytes(), actor="demo") for p in files]


@router.get("")
def list_invoices(status: str | None = None, s: Session = Depends(get_session)):
    q = select(Invoice).order_by(Invoice.id.desc())
    if status:
        q = q.where(Invoice.status.in_(status.split(",")))
    out = []
    for inv in s.exec(q):
        issues = s.exec(select(Issue).where(Issue.invoice_id == inv.id)).all()
        out.append(
            {
                **inv.model_dump(exclude={"raw_markdown", "extracted", "confidence", "match_result", "file_path"}),
                "blockers": sum(i.severity == "blocker" for i in issues),
                "warnings": sum(i.severity == "warning" for i in issues),
                "top_issue": next((i.message for i in issues if i.severity == "blocker"), None),
            }
        )
    return out


@router.get("/{invoice_id}")
def get_invoice(invoice_id: int, s: Session = Depends(get_session)):
    inv = _get(s, invoice_id)
    vendor = s.get(Vendor, inv.vendor_id) if inv.vendor_id else None
    return {
        "invoice": inv.model_dump(exclude={"file_path"}),
        "vendor": vendor.model_dump() if vendor else None,
        "lines": s.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.line_no)).all(),
        "issues": s.exec(select(Issue).where(Issue.invoice_id == invoice_id)).all(),
        "approvals": s.exec(select(Approval).where(Approval.invoice_id == invoice_id).order_by(Approval.level)).all(),
        "payments": s.exec(select(Payment).where(Payment.invoice_id == invoice_id)).all(),
        "audit": s.exec(select(AuditEvent).where(AuditEvent.invoice_id == invoice_id).order_by(AuditEvent.id)).all(),
        "progress": pipeline.PROGRESS.get(invoice_id, []),
    }


@router.get("/{invoice_id}/file")
def get_file(invoice_id: int, s: Session = Depends(get_session)):
    inv = _get(s, invoice_id)
    return FileResponse(inv.file_path, filename=inv.file_name, content_disposition_type="inline")


@router.get("/{invoice_id}/events")
async def events(invoice_id: int):
    async def gen():
        sent = 0
        for _ in range(600):  # ≤ 5 min
            evs = pipeline.PROGRESS.get(invoice_id, [])
            while sent < len(evs):
                yield {"event": "progress", "data": json.dumps(evs[sent])}
                if evs[sent]["step"] == "complete":
                    return
                sent += 1
            await asyncio.sleep(0.5)

    return EventSourceResponse(gen())


@router.patch("/{invoice_id}/fields")
def patch_fields(invoice_id: int, body: FieldPatch, s: Session = Depends(get_session)):
    inv = _get(s, invoice_id)
    try:
        pipeline.correct_fields(s, inv, body.fields, body.actor)
    except (pipeline.WorkflowError, ValueError) as err:
        s.rollback()
        raise HTTPException(400, str(err)) from err
    s.commit()
    return get_invoice(invoice_id, s)


def _action(fn, invoice_id: int, body: ActionIn, s: Session, *args):
    inv = _get(s, invoice_id)
    try:
        fn(s, inv, body.actor, *args, body.comment)
    except pipeline.WorkflowError as err:
        s.rollback()
        raise HTTPException(400, str(err)) from err
    s.add(inv)
    s.commit()
    return get_invoice(invoice_id, s)


@router.post("/{invoice_id}/approve")
def approve(invoice_id: int, body: ActionIn, s: Session = Depends(get_session)):
    return _action(pipeline.approve, invoice_id, body, s, body.role)


@router.post("/{invoice_id}/reject")
def reject(invoice_id: int, body: ActionIn, s: Session = Depends(get_session)):
    return _action(pipeline.reject, invoice_id, body, s)


@router.post("/{invoice_id}/hold")
def hold(invoice_id: int, body: ActionIn, s: Session = Depends(get_session)):
    return _action(pipeline.hold, invoice_id, body, s)


@router.post("/{invoice_id}/onboard-vendor")
def onboard_vendor(invoice_id: int, body: ActionIn, s: Session = Depends(get_session)):
    return _action(lambda s_, inv, actor, _c: pipeline.onboard_vendor(s_, inv, actor), invoice_id, body, s)


@router.post("/{invoice_id}/retro-po")
def retro_po(invoice_id: int, body: ActionIn, s: Session = Depends(get_session)):
    return _action(lambda s_, inv, actor, _c: pipeline.create_retro_po(s_, inv, actor), invoice_id, body, s)


@router.post("/{invoice_id}/reprocess")
def reprocess(invoice_id: int, background: BackgroundTasks, s: Session = Depends(get_session)):
    """Re-run the pipeline. Uses the per-file cache, so no Sarvam credits are spent twice."""
    inv = _get(s, invoice_id)
    pipeline.PROGRESS[invoice_id] = []
    s.exec(Issue.__table__.delete().where(Issue.invoice_id == invoice_id))
    s.commit()
    background.add_task(pipeline.process_invoice, inv.id)
    return {"ok": True}


async def _ai(fn, *args):
    if settings.mock_mode:
        raise HTTPException(400, "AI features need SARVAM_API_KEY (currently in offline mode).")
    try:
        return await fn(*args)
    except BudgetExceeded as err:
        raise HTTPException(429, str(err)) from err
    except Exception as err:  # noqa: BLE001
        raise HTTPException(502, f"Sarvam call failed: {err}") from err


@router.post("/{invoice_id}/explain")
async def ai_explain(invoice_id: int, s: Session = Depends(get_session)):
    inv = _get(s, invoice_id)
    issues = list(s.exec(select(Issue).where(Issue.invoice_id == invoice_id)))
    text = await _ai(explain.ai_explanation, inv, issues)
    inv.explanation = text
    pipeline.audit(s, inv.id, "ai_explanation", text=text)
    s.add(inv)
    s.commit()
    return {"explanation": text}


@router.post("/{invoice_id}/vendor-email")
async def vendor_email(invoice_id: int, lang: str | None = Query(None), s: Session = Depends(get_session)):
    inv = _get(s, invoice_id)
    vendor = s.get(Vendor, inv.vendor_id) if inv.vendor_id else None
    issues = [i for i in s.exec(select(Issue).where(Issue.invoice_id == invoice_id)) if i.severity != "info"]
    if not issues:
        raise HTTPException(400, "Nothing to dispute on this invoice.")
    language = lang or (vendor.preferred_language if vendor else "en-IN")
    text = await _ai(explain.vendor_email, inv, vendor, issues, language)
    pipeline.audit(s, inv.id, "vendor_email_drafted", language=language)
    s.commit()
    return {"language": language, "email": text}
