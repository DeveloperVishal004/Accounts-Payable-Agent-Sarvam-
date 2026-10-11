"""Single source of truth for demo data: ERP master data + the 8 demo invoice scenarios."""

from datetime import date, timedelta

from app.config import settings
from app.utils.gst import make_gstin

TODAY = date.today()


def d(days_ago: int) -> date:
    return TODAY - timedelta(days=days_ago)


VENDORS = [
    dict(key="bharat", name="Bharat Office Supplies", state_code="07", pan="AAGFB4821K", bank_account="50200012345678", ifsc="HDFC0001234",
         payment_terms_days=30, preferred_language="hi-IN", msme=True, email="accounts@bharatoffice.in",
         address="14, Nehru Place, New Delhi 110019"),
    dict(key="technova", name="TechNova Electronics Pvt Ltd", state_code="29", pan="AACCT5678L", bank_account="912010045678123", ifsc="UTIB0000247",
         payment_terms_days=45, preferred_language="en-IN", msme=False, email="ar@technova.co.in",
         address="88, Electronic City Phase 1, Bengaluru 560100"),
    dict(key="kaveri", name="Kaveri Textiles", state_code="33", pan="AAFFK9012M", bank_account="6123456789", ifsc="IOBA0001580",
         payment_terms_days=30, preferred_language="ta-IN", msme=True, email="billing@kaveritex.in",
         address="21, Avinashi Road, Coimbatore 641018"),
    dict(key="gujchem", name="Gujarat Chemicals Ltd", state_code="24", pan="AABCG3456P", bank_account="00981100004567", ifsc="SBIN0000981",
         payment_terms_days=60, preferred_language="gu-IN", msme=False, email="finance@gujchem.com",
         address="Plot 45, GIDC Ankleshwar, Gujarat 393002"),
    dict(key="ganesh", name="Shree Ganesh Packaging", state_code="27", pan="AAPFS7788Q", bank_account="37281900012", ifsc="MAHB0000412",
         payment_terms_days=30, preferred_language="mr-IN", msme=True, email="sales@ganeshpack.in",
         address="Gala 7, Bhiwandi Industrial Estate, Thane 421302"),
]
for v in VENDORS:
    v["gstin"] = make_gstin(v["state_code"], v["pan"])

# po_number, vendor_key, days_ago, lines: (description, hsn, qty, unit_price, tax_rate), received qty per line
POS = [
    dict(po="PO-2026-0101", vendor="bharat", days_ago=25, lines=[("A4 Copier Paper 75 GSM (Ream)", "4802", 50, 280.0, 18), ("Heavy Duty Stapler", "8472", 10, 150.0, 18)], received=[50, 10]),
    dict(po="PO-2026-0102", vendor="technova", days_ago=30, lines=[("Dell Latitude 5450 Laptop", "8471", 5, 52000.0, 18), ("Dell 24 inch Monitor P2425", "8528", 5, 11000.0, 18)], received=[5, 5]),
    dict(po="PO-2026-0103", vendor="kaveri", days_ago=28, lines=[("Cotton Poplin Fabric 58 inch (metre)", "5208", 500, 180.0, 5)], received=[400]),
    dict(po="PO-2026-0104", vendor="gujchem", days_ago=35, lines=[("Isopropyl Alcohol 99% (200L drum)", "2905", 4, 9500.0, 18)], received=[4]),
    dict(po="PO-2026-0105", vendor="ganesh", days_ago=20, lines=[("5-Ply Corrugated Box 18x12x12", "4819", 1000, 22.0, 18)], received=[1000]),
    dict(po="PO-2026-0106", vendor="ganesh", days_ago=18, lines=[("Bubble Wrap Roll 1m x 100m", "3923", 40, 450.0, 18)], received=[40]),
    dict(po="PO-2026-0107", vendor="bharat", days_ago=15, lines=[("HP 88A Toner Cartridge", "8443", 6, 3200.0, 18)], received=[6]),
]

V = {v["key"]: v for v in VENDORS}

# Each scenario: what the document says. `expect` = the outcome the agent should reach.
INVOICES = [
    dict(file="01_bharat_clean", vendor="bharat", number="BOS/26-27/0412", days_ago=6, po="PO-2026-0101",
         lines=[("A4 Copier Paper 75 GSM (Ream)", "4802", 50, 280.0, 18), ("Heavy Duty Stapler", "8472", 10, 150.0, 18)],
         expect="AUTO_APPROVED → SCHEDULED", story="Clean invoice. 3-way match passes, so it is approved and paid with no human touch."),
    dict(file="02_technova_price_variance", vendor="technova", number="TN-INV-77815", days_ago=5, po="PO-2026-0102",
         lines=[("Dell Latitude 5450 Laptop", "8471", 5, 52000.0, 18), ("Dell 24 inch Monitor P2425", "8528", 5, 11880.0, 18)],
         expect="ON_HOLD: PRICE_VARIANCE", story="Monitor billed 8% above the PO price."),
    dict(file="03_kaveri_tamil_short_receipt", vendor="kaveri", number="KT/1187", days_ago=4, po="PO-2026-0103",
         lines=[("பருத்தி பாப்ளின் துணி 58\" (மீட்டர்) / Cotton Poplin Fabric", "5208", 500, 180.0, 5)], lang="ta", scan=True,
         desc_en=["Cotton Poplin Fabric 58 inch (metre)"],
         expect="ON_HOLD: QTY_EXCEEDS_RECEIVED", story="Tamil-English invoice photo: billed 500 m, but the warehouse GRN shows only 400 m received."),
    dict(file="04_bharat_duplicate_resend", vendor="bharat", number="BOS/26-27/0412", days_ago=6, po="PO-2026-0101",
         lines=[("A4 Copier Paper 75 GSM (Ream)", "4802", 50, 280.0, 18), ("Heavy Duty Stapler", "8472", 10, 150.0, 18)],
         expect="ON_HOLD: DUPLICATE", story="Vendor re-sent invoice #1 by email. Same number, same amount."),
    dict(file="05_gujchem_bad_gstin", vendor="gujchem", number="GCL/2026/3391", days_ago=8, po="PO-2026-0104",
         lines=[("Isopropyl Alcohol 99% (200L drum)", "2905", 4, 9500.0, 18)], gstin_override="CHECKSUM",
         expect="ON_HOLD: INVALID_GSTIN", story="GSTIN fails the checksum, so input tax credit would be lost."),
    dict(file="06_ganesh_wrong_tax", vendor="ganesh", number="SGP-0921", days_ago=3, po="PO-2026-0105",
         lines=[("5-Ply Corrugated Box 18x12x12", "4819", 1000, 22.0, 18)], force_igst=True,
         expect="ON_HOLD: WRONG_TAX_TYPE", story="Intra-state supply (both in Maharashtra), but IGST was charged."),
    dict(file="07_ganesh_bank_change", vendor="ganesh", number="SGP-0934", days_ago=2, po="PO-2026-0106",
         lines=[("Bubble Wrap Roll 1m x 100m", "3923", 40, 450.0, 18)], bank_override=("40123456789012", "ICIC0009911"),
         expect="ON_HOLD: BANK_CHANGE", story="Invoice asks for payment to a NEW bank account, a classic payment-fraud pattern."),
    dict(file="08_bharat_hindi_scan", vendor="bharat", number="BOS/26-27/0466", days_ago=3, po="PO-2026-0107",
         lines=[("HP 88A टोनर कार्ट्रिज", "8443", 6, 3200.0, 18)], lang="hi", scan=True, handwritten_date=True,
         desc_en=["HP 88A Toner Cartridge"], low_conf={"invoice_date": 0.62},
         expect="PENDING_APPROVAL: LOW_CONFIDENCE", story="Hindi invoice, photographed at an angle. The handwritten date is read with low confidence, so it goes to a human."),
]


def invoice_values(spec: dict) -> dict:
    """Compute the printed values of a scenario (what's on the paper)."""
    v = V[spec["vendor"]]
    lines = [dict(description=desc, hsn=hsn, qty=qty, unit_price=price, tax_rate=rate, amount=round(qty * price, 2))
             for desc, hsn, qty, price, rate in spec["lines"]]
    subtotal = round(sum(line["amount"] for line in lines), 2)
    tax = round(sum(line["amount"] * line["tax_rate"] / 100 for line in lines), 2)
    intra = v["state_code"] == settings.buyer_gstin[:2]
    use_igst = spec.get("force_igst") or not intra
    gstin = v["gstin"]
    if spec.get("gstin_override") == "CHECKSUM":
        gstin = gstin[:14] + ("A" if gstin[14] != "A" else "B")
    bank, ifsc = spec.get("bank_override") or (v["bank_account"], v["ifsc"])
    return dict(
        vendor_name=v["name"], vendor_gstin=gstin, vendor_address=v["address"], buyer_gstin=settings.buyer_gstin,
        invoice_number=spec["number"], invoice_date=d(spec["days_ago"]).isoformat(), po_number=spec["po"],
        line_items=lines, subtotal=subtotal,
        cgst=None if use_igst else round(tax / 2, 2), sgst=None if use_igst else round(tax / 2, 2), igst=tax if use_igst else None,
        total=round(subtotal + tax, 2), bank_account=bank, ifsc=ifsc, language={"hi": "hi-IN", "ta": "ta-IN"}.get(spec.get("lang", ""), "en-IN"),
    )
