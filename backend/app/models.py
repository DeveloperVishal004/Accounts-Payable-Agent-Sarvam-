from datetime import date, datetime
from enum import StrEnum

from pydantic import NaiveDatetime
from sqlmodel import JSON, Column, Field, SQLModel


def utcnow() -> datetime:
    return datetime.now()


class InvoiceStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PARSED = "PARSED"
    EXTRACTED = "EXTRACTED"
    VALIDATED = "VALIDATED"
    MATCHED = "MATCHED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ON_HOLD = "ON_HOLD"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    FAILED = "FAILED"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


# ---------------------------------------------------------------- ERP master data


class Vendor(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    gstin: str = Field(index=True)
    state_code: str
    pan: str
    bank_account: str
    ifsc: str
    payment_terms_days: int = 30
    preferred_language: str = "en-IN"
    msme: bool = False
    email: str = ""


class PurchaseOrder(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    po_number: str = Field(index=True, unique=True)
    vendor_id: int = Field(foreign_key="vendor.id")
    po_date: date
    status: str = "OPEN"
    total: float = 0.0


class POLine(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    po_id: int = Field(foreign_key="purchaseorder.id", index=True)
    line_no: int
    description: str
    hsn: str
    qty: float
    unit_price: float
    tax_rate: float


class GoodsReceipt(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    grn_number: str = Field(index=True, unique=True)
    po_id: int = Field(foreign_key="purchaseorder.id", index=True)
    received_date: date


class GRNLine(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    grn_id: int = Field(foreign_key="goodsreceipt.id", index=True)
    po_line_no: int
    qty_received: float


# ---------------------------------------------------------------- AP documents


class Invoice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    file_name: str
    file_path: str
    file_hash: str = Field(index=True)
    status: InvoiceStatus = InvoiceStatus.UPLOADED
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    processed_at: NaiveDatetime | None = None

    vendor_id: int | None = Field(default=None, foreign_key="vendor.id")
    po_id: int | None = Field(default=None, foreign_key="purchaseorder.id")

    vendor_name: str | None = None
    vendor_gstin: str | None = None
    buyer_gstin: str | None = None
    invoice_number: str | None = Field(default=None, index=True)
    invoice_date: date | None = None
    due_date: date | None = None
    po_number: str | None = None
    subtotal: float | None = None
    cgst: float | None = None
    sgst: float | None = None
    igst: float | None = None
    total: float | None = None
    bank_account: str | None = None
    ifsc: str | None = None
    language: str | None = None

    raw_markdown: str | None = None
    extracted: dict | None = Field(default=None, sa_column=Column(JSON))
    confidence: dict | None = Field(default=None, sa_column=Column(JSON))
    match_result: dict | None = Field(default=None, sa_column=Column(JSON))
    decision: dict | None = Field(default=None, sa_column=Column(JSON))
    explanation: str | None = None
    erp_bill_id: str | None = None
    amount_at_risk: float = 0.0


class InvoiceLine(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoice.id", index=True)
    line_no: int
    description: str
    hsn: str | None = None
    qty: float
    unit_price: float
    tax_rate: float | None = None
    amount: float
    matched_po_line_no: int | None = None


class Issue(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoice.id", index=True)
    code: str
    severity: Severity
    field: str | None = None
    message: str
    expected: str | None = None
    actual: str | None = None


class Approval(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoice.id", index=True)
    level: int
    approver_role: str
    status: str = "PENDING"  # PENDING | APPROVED | REJECTED | WAITING
    comment: str | None = None
    decided_by: str | None = None
    decided_at: NaiveDatetime | None = None


class Payment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoice.id", index=True)
    vendor_id: int = Field(foreign_key="vendor.id")
    amount: float
    scheduled_date: date
    status: str = "SCHEDULED"  # SCHEDULED | PAID
    run_id: str | None = None
    utr: str | None = None
    paid_at: NaiveDatetime | None = None


class AuditEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int | None = Field(default=None, foreign_key="invoice.id", index=True)
    actor: str
    action: str
    detail: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: NaiveDatetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- Sarvam usage guardrails


class ApiUsage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    kind: str  # "doc" | "chat"
    purpose: str  # parse | extract | explain | vendor_email
    invoice_id: int | None = None
    pages: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class DocCache(SQLModel, table=True):
    """Per-file cache so re-uploads / re-processing never spend Sarvam credits twice."""

    file_hash: str = Field(primary_key=True)
    markdown: str | None = None
    extracted: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: NaiveDatetime = Field(default_factory=utcnow)
