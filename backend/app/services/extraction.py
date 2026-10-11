"""Document → structured invoice. Sarvam Vision reads the page, Sarvam-105B maps it to our schema.

Credit-saving rules: results are cached per file hash, OCR text is trimmed, reasoning is disabled
(extraction is mechanical), and completion length is capped.
"""

import asyncio
import json
import re
from pathlib import Path

from pydantic import ValidationError

from app.config import settings
from app.schemas import EXTRACTION_JSON_SCHEMA, ExtractedInvoice
from app.services import sarvam, usage

SYSTEM_PROMPT = """You extract data from ONE Indian GST tax invoice for accounts payable.
Input: OCR Markdown (any Indian language or mixed). Output: ONLY a JSON object matching the schema.
Rules:
- Copy values as printed. Never invent values; use null if absent/unreadable.
- Fill EVERY key of the schema (null only if truly absent). Invoice number and date are near the title.
- vendor_* = seller who issued the invoice. buyer_gstin = "Bill To" party.
- Numbers: plain decimals, no symbols/commas ("₹1,25,000.50" → 125000.5). Dates: YYYY-MM-DD (Indian invoices print DD/MM/YYYY).
- Tables arrive as rows of "cell | cell | ...". Use the header row to map columns: qty = quantity column (मात्रा/அளவு/Qty),
  unit_price = rate column, amount = taxable value column. One line_item per data row.
- line_items[].amount = taxable value before GST; tax_rate = GST %; subtotal = taxable total. CGST/SGST/IGST amounts go in top-level fields.
- po_number: "PO No", "P.O.", "Order Ref", "क्रय आदेश" etc.
- bank_account/ifsc: supplier's bank details if printed.
- Translate non-English item descriptions to English.
- confidence: 0-1 per top-level field filled; < 0.7 if blurry, handwritten, overwritten or ambiguous."""


EXTRACT_VERSION = 4  # bump when the prompt/pre-processing changes so cached extractions are refreshed


def _compact(markdown: str) -> str:
    """Shrink OCR output for the LLM while keeping table structure (rows → lines, cells → ' | ')."""
    # Embedded images (base64) and Sarvam Vision's long captions of them (stamps, logos) carry no invoice data.
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)\s*(\*[\s\S]*?[^*]\*(?=[ \t]*(?:\n|$)))?", " ", markdown)
    text = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", " | ", text)
    text = re.sub(r"</?tr[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)  # remaining tags
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[: settings.max_markdown_chars]


async def parse(path: Path, file_hash: str, invoice_id: int | None = None) -> tuple[str, bool]:
    """Returns (markdown, from_cache)."""
    if settings.mock_mode:
        return _fixture(path)["markdown"], False
    cached = usage.cache_get(file_hash)
    if cached and cached.markdown:
        return cached.markdown, True
    md = await sarvam.parse_document(path, invoice_id=invoice_id)
    usage.cache_put(file_hash, markdown=md)
    return md, False


async def extract(markdown: str, path: Path, file_hash: str, invoice_id: int | None = None) -> tuple[ExtractedInvoice, bool]:
    """Returns (invoice, from_cache)."""
    if settings.mock_mode:
        await asyncio.sleep(0.6)  # keep the live progress UI realistic in offline mode
        return ExtractedInvoice.model_validate(_fixture(path)["extracted"]), False

    cached = usage.cache_get(file_hash)
    if cached and cached.extracted and cached.extracted.get("_v") == EXTRACT_VERSION:
        return ExtractedInvoice.model_validate(cached.extracted), True

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _compact(markdown)},
    ]
    kw = dict(purpose="extract", invoice_id=invoice_id, max_tokens=settings.extract_max_tokens, reasoning_effort=None, temperature=0.0)
    raw = await sarvam.chat_json(messages, EXTRACTION_JSON_SCHEMA, **kw)
    try:
        inv = ExtractedInvoice.model_validate(raw)
    except ValidationError as err:
        # One repair round-trip with the validation errors.
        messages += [
            {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
            {"role": "user", "content": f"Fix these validation errors and return corrected JSON only:\n{err}"},
        ]
        raw = await sarvam.chat_json(messages, EXTRACTION_JSON_SCHEMA, **kw)
        inv = ExtractedInvoice.model_validate(raw)

    usage.cache_put(file_hash, extracted={**inv.model_dump(mode="json"), "_v": EXTRACT_VERSION})
    return inv, False


def _fixture(path: Path) -> dict:
    """Offline mode: ground-truth OCR + extraction written by seed/make_invoices.py."""
    stem = path.stem.split("__", 1)[-1]  # uploads are stored as <hash>__<original name>
    fx = settings.fixtures_dir / f"{stem}.json"
    if not fx.exists():
        raise FileNotFoundError(
            f"Offline mode can only process the generated sample invoices; no fixture for '{stem}'."
        )
    return json.loads(fx.read_text())
