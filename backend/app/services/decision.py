"""Approval policy. Deterministic: the LLM never decides whether money moves."""

from app.config import settings
from app.schemas import Decision, IssueData, MatchResult
from app.utils.gst import inr

SUGGESTED_ACTIONS = {
    "DUPLICATE": "Reject as duplicate. No payment needed.",
    "BANK_CHANGE": "Call the vendor on their registered number to confirm the new bank details before releasing payment.",
    "INVALID_GSTIN": "Ask the vendor for a corrected invoice with a valid GSTIN.",
    "GSTIN_MISMATCH": "Ask the vendor for a corrected invoice, or update the vendor master after verification.",
    "WRONG_TAX_TYPE": "Ask the vendor for a credit note and a re-issued invoice with the correct GST type.",
    "TAX_AMOUNT_MISMATCH": "Ask the vendor for a corrected invoice with the right GST amount.",
    "PRICE_VARIANCE": "Ask the vendor for a credit note for the price difference, or have procurement approve a PO amendment.",
    "QTY_EXCEEDS_RECEIVED": "Pay only for the received quantity, or wait for the GRN of the remaining goods.",
    "OVER_BILLING": "Ask the vendor for a credit note for the excess quantity.",
    "UNMATCHED_LINE": "Have procurement confirm the extra item, or ask the vendor to remove it.",
    "NO_PO": "Ask the requester to raise a PO (or a retro-PO with approval) before payment.",
    "UNKNOWN_VENDOR": "Complete vendor onboarding (KYC, GSTIN, bank verification) first.",
    "MISSING_FIELD": "Review the document and fill in the missing fields manually.",
    "LINE_MATH": "Ask the vendor for a corrected invoice. The line arithmetic is wrong.",
    "SUBTOTAL_MISMATCH": "Ask the vendor for a corrected invoice. The subtotal doesn't add up.",
    "TOTAL_MISMATCH": "Ask the vendor for a corrected invoice. The total doesn't add up.",
    "FUTURE_DATED": "Check the invoice date with the vendor.",
    "PO_VENDOR_MISMATCH": "Check the PO reference with the vendor.",
}


def approval_chain(total: float) -> list[str]:
    if total <= settings.single_approver_limit:
        return ["AP Manager"]
    return ["AP Manager", "Finance Controller"]


def decide(issues: list[IssueData], match: MatchResult, total: float | None) -> Decision:
    total = total or 0.0
    blockers = [i for i in issues if i.severity == "blocker"]
    warnings = [i for i in issues if i.severity == "warning"]

    if blockers:
        primary = blockers[0].code
        return Decision(
            outcome="ON_HOLD",
            reasons=[b.message for b in blockers],
            suggested_action=SUGGESTED_ACTIONS.get(primary, "Review the flagged issues."),
        )

    reasons: list[str] = []
    if not match.fully_matched:
        reasons.append("Invoice is not fully matched to a PO and GRN.")
    reasons.extend(w.message for w in warnings)
    if total > settings.auto_approve_limit:
        reasons.append(f"Amount {inr(total)} is above the auto-approval limit of {inr(settings.auto_approve_limit)}.")

    if not reasons:
        return Decision(
            outcome="AUTO_APPROVED",
            reasons=[
                f"3-way match passed, all checks clean, and the amount is within the {inr(settings.auto_approve_limit)} auto-approval limit."
            ],
        )

    return Decision(outcome="PENDING_APPROVAL", reasons=reasons, approval_chain=approval_chain(total))
