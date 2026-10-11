"""GST helpers: GSTIN format + checksum, state codes, tax slabs, Indian number parsing."""

import re

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GST_SLABS = {0.0, 0.25, 3.0, 5.0, 12.0, 18.0, 28.0}

STATE_CODES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh",
    "23": "Madhya Pradesh", "24": "Gujarat", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
    "32": "Kerala", "33": "Tamil Nadu", "36": "Telangana", "37": "Andhra Pradesh",
}


def gstin_check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = _CHARSET.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _CHARSET[(36 - total % 36) % 36]


def make_gstin(state_code: str, pan: str, entity: str = "1") -> str:
    """Build a checksum-valid GSTIN (used by seed data)."""
    body = f"{state_code}{pan}{entity}Z"
    return body + gstin_check_char(body)


def gstin_format_ok(gstin: str) -> bool:
    return bool(GSTIN_RE.match(gstin or ""))


def gstin_valid(gstin: str) -> bool:
    gstin = (gstin or "").strip().upper()
    return gstin_format_ok(gstin) and gstin_check_char(gstin[:14]) == gstin[14]


def state_of(gstin: str | None) -> str | None:
    return gstin[:2] if gstin and len(gstin) >= 2 else None


def parse_amount(value) -> float | None:
    """Parse '₹1,25,000.50', '1 25 000', 125000 → 125000.5."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(cleaned) if cleaned not in {"", ".", "-"} else None
    except ValueError:
        return None


def inr(amount: float | None) -> str:
    """Format in Indian digit grouping: 1250000 → ₹12,50,000.00"""
    if amount is None:
        return "—"
    neg = amount < 0
    whole, frac = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        whole = f"{head},{tail}"
    return f"{'-' if neg else ''}₹{whole}.{frac}"
