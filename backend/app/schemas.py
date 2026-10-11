from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.utils.gst import GST_SLABS, parse_amount

# ---------------------------------------------------------------- extraction output


class ExtractedLine(BaseModel):
    description: str
    hsn: str | None = None
    qty: float
    unit_price: float
    tax_rate: float | None = None
    amount: float

    @field_validator("qty", "unit_price", "amount", "tax_rate", mode="before")
    @classmethod
    def _num(cls, v):
        return parse_amount(v)

    @field_validator("tax_rate")
    @classmethod
    def _pct(cls, v):
        # LLMs sometimes return 18% as 0.18
        if v is not None and 0 < v < 1 and round(v * 100, 2) in GST_SLABS:
            return round(v * 100, 2)
        return v

    @field_validator("hsn", mode="before")
    @classmethod
    def _hsn(cls, v):
        return str(v).strip() if v not in (None, "") else None


class ExtractedInvoice(BaseModel):
    vendor_name: str | None = None
    vendor_gstin: str | None = None
    vendor_address: str | None = None
    buyer_gstin: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    po_number: str | None = None
    line_items: list[ExtractedLine] = Field(default_factory=list)
    subtotal: float | None = None
    cgst: float | None = None
    sgst: float | None = None
    igst: float | None = None
    total: float | None = None
    bank_account: str | None = None
    ifsc: str | None = None
    language: str | None = None
    confidence: dict[str, float] = Field(default_factory=dict)

    @field_validator("subtotal", "cgst", "sgst", "igst", "total", mode="before")
    @classmethod
    def _num(cls, v):
        return parse_amount(v)

    @field_validator("vendor_gstin", "buyer_gstin", "ifsc", mode="before")
    @classmethod
    def _upper(cls, v):
        return str(v).strip().upper().replace(" ", "") if v else None

    @field_validator("bank_account", mode="before")
    @classmethod
    def _acct(cls, v):
        return "".join(ch for ch in str(v) if ch.isalnum()) if v else None


# JSON schema handed to Sarvam-105B structured outputs.
EXTRACTION_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "vendor_name": {"type": ["string", "null"]},
        "vendor_gstin": {"type": ["string", "null"], "description": "15-char GSTIN of the seller/supplier"},
        "vendor_address": {"type": ["string", "null"]},
        "buyer_gstin": {"type": ["string", "null"], "description": "GSTIN of the bill-to party"},
        "invoice_number": {"type": ["string", "null"], "description": "Invoice No / बीजक संख्या / விலைப்பட்டியல் எண்"},
        "invoice_date": {"type": ["string", "null"], "description": "Invoice Date / दिनांक / தேதி, as ISO YYYY-MM-DD (printed DD/MM/YYYY), may be handwritten"},
        "po_number": {"type": ["string", "null"], "description": "Purchase order reference if printed"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "hsn": {"type": ["string", "null"]},
                    "qty": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "tax_rate": {"type": ["number", "null"], "description": "GST % e.g. 18"},
                    "amount": {"type": "number", "description": "taxable value = qty * unit_price"},
                },
                "required": ["description", "qty", "unit_price", "amount"],
            },
        },
        "subtotal": {"type": ["number", "null"], "description": "total taxable value before GST"},
        "cgst": {"type": ["number", "null"]},
        "sgst": {"type": ["number", "null"]},
        "igst": {"type": ["number", "null"]},
        "total": {"type": ["number", "null"], "description": "grand total payable"},
        "bank_account": {"type": ["string", "null"]},
        "ifsc": {"type": ["string", "null"]},
        "language": {"type": ["string", "null"], "description": "primary language of the document, BCP-47 like hi-IN"},
        "confidence": {
            "type": "object",
            "description": "0-1 confidence per top-level field name you extracted",
            "additionalProperties": {"type": "number"},
        },
    },
}
# Every key required (nullable) so the model must consider each field instead of silently omitting it.
EXTRACTION_JSON_SCHEMA["required"] = list(EXTRACTION_JSON_SCHEMA["properties"])

# ---------------------------------------------------------------- engine outputs


class IssueData(BaseModel):
    code: str
    severity: str  # info | warning | blocker
    message: str
    field: str | None = None
    expected: str | None = None
    actual: str | None = None
    amount_at_risk: float = 0.0


class LineMatch(BaseModel):
    invoice_line_no: int
    po_line_no: int | None = None
    description: str
    invoice_qty: float
    po_qty: float | None = None
    received_qty: float | None = None
    previously_invoiced_qty: float | None = None
    invoice_price: float
    po_price: float | None = None
    price_variance_pct: float | None = None
    status: str  # matched | price_variance | qty_exceeds_received | over_billing | unmatched


class MatchResult(BaseModel):
    po_number: str | None = None
    po_found: bool = False
    lines: list[LineMatch] = Field(default_factory=list)
    issues: list[IssueData] = Field(default_factory=list)

    @property
    def fully_matched(self) -> bool:
        return self.po_found and bool(self.lines) and all(line.status == "matched" for line in self.lines)


class Decision(BaseModel):
    outcome: str  # AUTO_APPROVED | PENDING_APPROVAL | ON_HOLD
    reasons: list[str]
    approval_chain: list[str] = Field(default_factory=list)
    suggested_action: str | None = None


# ---------------------------------------------------------------- API inputs


class ActionIn(BaseModel):
    actor: str = "ap.manager"
    role: str | None = None
    comment: str | None = None


class FieldPatch(BaseModel):
    fields: dict
    actor: str = "ap.clerk"
