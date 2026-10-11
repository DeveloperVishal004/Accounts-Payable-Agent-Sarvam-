"""3-way match: invoice lines vs PO lines vs goods received (GRN)."""

from rapidfuzz import fuzz

from app.config import settings
from app.erp.base import ERPAdapter
from app.models import POLine, PurchaseOrder, Vendor
from app.schemas import ExtractedInvoice, ExtractedLine, IssueData, LineMatch, MatchResult
from app.utils.gst import inr

MIN_LINE_SCORE = 55.0


def _line_score(inv_line: ExtractedLine, po_line: POLine) -> float:
    score = fuzz.token_set_ratio(inv_line.description.lower(), po_line.description.lower()) * 0.6
    if inv_line.hsn and inv_line.hsn == po_line.hsn:
        score += 30
    if po_line.unit_price:
        diff = abs(inv_line.unit_price - po_line.unit_price) / po_line.unit_price
        score += 10 * max(0.0, 1 - diff * 5)
    return score


def assign_lines(inv_lines: list[ExtractedLine], po_lines: list[POLine]) -> dict[int, POLine]:
    """Greedy best-score assignment. Returns {invoice_line_index: po_line}."""
    pairs = sorted(
        ((_line_score(il, pl), i, pl) for i, il in enumerate(inv_lines) for pl in po_lines),
        key=lambda p: p[0],
        reverse=True,
    )
    assigned: dict[int, POLine] = {}
    used: set[int] = set()
    for score, i, pl in pairs:
        if score < MIN_LINE_SCORE:
            break
        if i in assigned or pl.line_no in used:
            continue
        assigned[i] = pl
        used.add(pl.line_no)
    return assigned


def _find_po(inv: ExtractedInvoice, vendor: Vendor | None, erp: ERPAdapter) -> tuple[PurchaseOrder | None, list[IssueData]]:
    issues: list[IssueData] = []
    if inv.po_number:
        po = erp.get_po(inv.po_number)
        if po:
            if vendor and po.vendor_id != vendor.id:
                issues.append(
                    IssueData(
                        code="PO_VENDOR_MISMATCH",
                        severity="blocker",
                        message=f"PO {po.po_number} was issued to a different vendor.",
                        field="po_number",
                        actual=inv.po_number,
                    )
                )
            return po, issues
        issues.append(
            IssueData(
                code="PO_NOT_FOUND",
                severity="warning",
                message=f"PO '{inv.po_number}' quoted on the invoice does not exist in the ERP.",
                field="po_number",
                actual=inv.po_number,
            )
        )
    if vendor:
        best: tuple[float, PurchaseOrder | None] = (0.0, None)
        for po in erp.open_pos_for_vendor(vendor.id):
            lines = erp.get_po_lines(po.id)
            hits = assign_lines(inv.line_items, lines)
            score = len(hits) / max(1, len(inv.line_items))
            if score > best[0]:
                best = (score, po)
        if best[1] and best[0] >= 0.5:
            issues.append(
                IssueData(
                    code="PO_INFERRED",
                    severity="info",
                    message=f"No PO number was quoted. Matched to open PO {best[1].po_number} by line items.",
                    field="po_number",
                )
            )
            return best[1], issues
    return None, issues


def three_way_match(inv: ExtractedInvoice, vendor: Vendor | None, erp: ERPAdapter, invoice_id: int | None = None) -> MatchResult:
    po, issues = _find_po(inv, vendor, erp)
    if po is None:
        issues.append(
            IssueData(
                code="NO_PO",
                severity="blocker",
                message="No matching purchase order was found, so this purchase was never authorised.",
                field="po_number",
                amount_at_risk=inv.total or 0.0,
            )
        )
        lines = [
            LineMatch(
                invoice_line_no=i,
                description=line.description,
                invoice_qty=line.qty,
                invoice_price=line.unit_price,
                status="unmatched",
            )
            for i, line in enumerate(inv.line_items, start=1)
        ]
        return MatchResult(po_found=False, lines=lines, issues=issues)

    po_lines = erp.get_po_lines(po.id)
    assigned = assign_lines(inv.line_items, po_lines)
    out: list[LineMatch] = []

    for idx, line in enumerate(inv.line_items):
        n = idx + 1
        pl = assigned.get(idx)
        if pl is None:
            out.append(LineMatch(invoice_line_no=n, description=line.description, invoice_qty=line.qty, invoice_price=line.unit_price, status="unmatched"))
            issues.append(
                IssueData(
                    code="UNMATCHED_LINE",
                    severity="blocker",
                    message=f"Line {n} '{line.description}' is not on PO {po.po_number}.",
                    field=f"line_items[{n}]",
                    amount_at_risk=line.amount,
                )
            )
            continue

        received = erp.received_qty(po.id, pl.line_no)
        prev = erp.invoiced_qty(po.id, pl.line_no, exclude_invoice_id=invoice_id)
        var_pct = round((line.unit_price - pl.unit_price) / pl.unit_price * 100, 2) if pl.unit_price else 0.0
        status = "matched"

        if var_pct > settings.price_tolerance_pct:
            status = "price_variance"
            issues.append(
                IssueData(
                    code="PRICE_VARIANCE",
                    severity="blocker",
                    message=f"Line {n} '{line.description}': billed at {inr(line.unit_price)}, PO price is {inr(pl.unit_price)} (+{var_pct:g}%).",
                    field=f"line_items[{n}].unit_price",
                    expected=f"{pl.unit_price:.2f}",
                    actual=f"{line.unit_price:.2f}",
                    amount_at_risk=round((line.unit_price - pl.unit_price) * line.qty, 2),
                )
            )
        if line.qty > received + settings.qty_tolerance:
            status = "qty_exceeds_received"
            issues.append(
                IssueData(
                    code="QTY_EXCEEDS_RECEIVED",
                    severity="blocker",
                    message=f"Line {n} '{line.description}': billed {line.qty:g} units but only {received:g} were received (GRN).",
                    field=f"line_items[{n}].qty",
                    expected=f"<= {received:g}",
                    actual=f"{line.qty:g}",
                    amount_at_risk=round((line.qty - received) * line.unit_price, 2),
                )
            )
        elif prev + line.qty > pl.qty + settings.qty_tolerance:
            status = "over_billing"
            issues.append(
                IssueData(
                    code="OVER_BILLING",
                    severity="blocker",
                    message=f"Line {n} '{line.description}': {prev:g} already invoiced + {line.qty:g} now exceeds the PO quantity {pl.qty:g}.",
                    field=f"line_items[{n}].qty",
                    expected=f"<= {max(0.0, pl.qty - prev):g}",
                    actual=f"{line.qty:g}",
                    amount_at_risk=round((prev + line.qty - pl.qty) * line.unit_price, 2),
                )
            )

        out.append(
            LineMatch(
                invoice_line_no=n,
                po_line_no=pl.line_no,
                description=line.description,
                invoice_qty=line.qty,
                po_qty=pl.qty,
                received_qty=received,
                previously_invoiced_qty=prev,
                invoice_price=line.unit_price,
                po_price=pl.unit_price,
                price_variance_pct=var_pct,
                status=status,
            )
        )

    return MatchResult(po_number=po.po_number, po_found=True, lines=out, issues=issues)
