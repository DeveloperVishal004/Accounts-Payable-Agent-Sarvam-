"""Human-readable explanations. The template summary is free and always on; AI calls are on-demand only."""

from app.config import settings
from app.models import Invoice, Issue, Vendor
from app.services import sarvam
from app.utils.gst import inr

LANG_NAMES = {
    "en-IN": "English", "hi-IN": "Hindi", "ta-IN": "Tamil", "te-IN": "Telugu", "kn-IN": "Kannada",
    "ml-IN": "Malayalam", "mr-IN": "Marathi", "gu-IN": "Gujarati", "bn-IN": "Bengali", "pa-IN": "Punjabi", "od-IN": "Odia",
}


def template_summary(invoice: Invoice, issues: list[Issue]) -> str:
    """Deterministic one-paragraph summary. Costs no tokens."""
    outcome = (invoice.decision or {}).get("outcome", invoice.status)
    blockers = [i for i in issues if i.severity == "blocker"]
    warnings = [i for i in issues if i.severity == "warning"]
    head = f"Invoice {invoice.invoice_number or '?'} from {invoice.vendor_name or 'unknown vendor'} for {inr(invoice.total)}"
    if outcome == "AUTO_APPROVED":
        return f"{head} matched its PO and goods receipt exactly and passed every check, so it was approved automatically."
    if blockers:
        risk = f" Amount at risk: {inr(invoice.amount_at_risk)}." if invoice.amount_at_risk else ""
        return f"{head} is on hold: {blockers[0].message}" + (f" (+{len(blockers) - 1} more blocker(s))." if len(blockers) > 1 else "") + risk
    if warnings:
        return f"{head} needs a human look: {warnings[0].message}"
    return f"{head} needs approval because its amount exceeds the auto-approval limit."


def _issue_lines(issues: list[Issue]) -> str:
    return "\n".join(
        f"- [{i.severity}] {i.code}: {i.message}" + (f" (expected {i.expected}, got {i.actual})" if i.expected or i.actual else "")
        for i in issues
        if i.severity != "info"
    )


def _issue_plain(issues: list[Issue]) -> str:
    """Vendor-facing: plain sentences only, no internal codes or severities."""
    return "\n".join(f"- {i.message}" for i in issues if i.severity != "info")


async def ai_explanation(invoice: Invoice, issues: list[Issue]) -> str:
    """2-3 sentence plain-language explanation for the approver. Never changes the decision."""
    messages = [
        {
            "role": "system",
            "content": "You are an AP analyst. In 2-3 short sentences, explain to a finance manager what is wrong with this "
            "invoice and what to do next. Use ONLY the facts given; do not add numbers. No preamble.",
        },
        {
            "role": "user",
            "content": f"Vendor: {invoice.vendor_name}\nInvoice: {invoice.invoice_number}, total {inr(invoice.total)}\n"
            f"Decision: {(invoice.decision or {}).get('outcome')}\nFindings:\n{_issue_lines(issues) or '- none'}",
        },
    ]
    return (await sarvam.chat(messages, purpose="explain", invoice_id=invoice.id, max_tokens=settings.explain_max_tokens, reasoning_effort=None)).strip()


async def vendor_email(invoice: Invoice, vendor: Vendor | None, issues: list[Issue], language: str) -> str:
    """Draft a polite dispute / clarification email to the vendor in their language."""
    lang = LANG_NAMES.get(language, language)
    messages = [
        {
            "role": "system",
            "content": f"Write a short, polite business email in {lang} from Acme Retail's accounts payable team to a supplier, "
            "asking them to resolve the invoice discrepancies listed. Include a subject line. Use ONLY the facts given. "
            "Never mention internal error codes. Keep invoice numbers, PO numbers, GSTINs and amounts exactly as given.",
        },
        {
            "role": "user",
            "content": f"Supplier: {invoice.vendor_name}\nInvoice: {invoice.invoice_number} dated {invoice.invoice_date}, PO {invoice.po_number}, "
            f"total {inr(invoice.total)}\nDiscrepancies:\n{_issue_plain(issues)}",
        },
    ]
    return (await sarvam.chat(messages, purpose="vendor_email", invoice_id=invoice.id, max_tokens=700, reasoning_effort=None, temperature=0.3)).strip()
