"""Generate the demo invoices (PDF + 'phone photo' JPGs) and their offline fixtures.

HTML → headless Chrome (proper Hindi/Tamil shaping) → PDF, or PNG → Pillow 'photo' effects → JPG.
Run:  python -m seed.make_invoices
"""

import html
import json
import random
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

from app.config import BASE_DIR, settings
from app.utils.gst import inr
from seed.data import INVOICES, V, invoice_values

OUT = BASE_DIR.parent / "sample_invoices"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

LABELS = {
    "en": dict(title="TAX INVOICE", no="Invoice No", date="Invoice Date", po="PO Ref", bill="Bill To", desc="Description of Goods",
               qty="Qty", rate="Rate", amt="Taxable Value", sub="Taxable Total", total="Grand Total", bank="Bank Details", sign="Authorised Signatory"),
    "hi": dict(title="कर बीजक / TAX INVOICE", no="बीजक संख्या", date="दिनांक", po="क्रय आदेश सं.", bill="प्राप्तकर्ता (Bill To)", desc="माल का विवरण",
               qty="मात्रा", rate="दर", amt="कर योग्य मूल्य", sub="कुल कर योग्य राशि", total="कुल देय राशि", bank="बैंक विवरण", sign="अधिकृत हस्ताक्षरकर्ता"),
    "ta": dict(title="வரி விலைப்பட்டியல் / TAX INVOICE", no="விலைப்பட்டியல் எண்", date="தேதி", po="கொள்முதல் ஆணை", bill="பெறுநர் (Bill To)",
               desc="பொருள் விவரம்", qty="அளவு", rate="விலை", amt="வரிக்குரிய மதிப்பு", sub="மொத்த வரிக்குரிய மதிப்பு", total="மொத்தம்",
               bank="வங்கி விவரம்", sign="அங்கீகரிக்கப்பட்ட கையொப்பம்"),
}


def rs(x):
    return inr(x).replace("₹", "Rs. ")


def render_html(spec: dict, val: dict) -> str:
    L = LABELS[spec.get("lang", "en")]
    v = V[spec["vendor"]]
    d = date.fromisoformat(val["invoice_date"]).strftime("%d/%m/%Y")
    date_cell = f'<span class="hand">{d}</span>' if spec.get("handwritten_date") else d
    rows = "".join(
        f"<tr><td>{i}</td><td>{html.escape(line['description'])}</td><td>{line['hsn']}</td><td class=r>{line['qty']:g}</td>"
        f"<td class=r>{rs(line['unit_price'])}</td><td class=r>{line['tax_rate']:g}%</td><td class=r>{rs(line['amount'])}</td></tr>"
        for i, line in enumerate(val["line_items"], start=1)
    )
    tax_rows = (
        f"<tr><td>IGST</td><td class=r>{rs(val['igst'])}</td></tr>"
        if val["igst"]
        else f"<tr><td>CGST</td><td class=r>{rs(val['cgst'])}</td></tr><tr><td>SGST</td><td class=r>{rs(val['sgst'])}</td></tr>"
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 14mm; }}
body {{ font-family: 'Helvetica Neue', 'Kohinoor Devanagari', 'Tamil Sangam MN', sans-serif; color:#1b1b1b; font-size:12.5px; margin:0; padding:24px; background:#fff; width:900px; }}
.top {{ display:flex; justify-content:space-between; border-bottom:3px solid #23395d; padding-bottom:10px; }}
.vname {{ font-size:24px; font-weight:700; color:#23395d; }}
.title {{ font-size:18px; font-weight:700; text-align:right; letter-spacing:1px; }}
table {{ width:100%; border-collapse:collapse; margin-top:12px; }}
th, td {{ border:1px solid #999; padding:6px 8px; text-align:left; vertical-align:top; }}
th {{ background:#e9eef6; }} .r {{ text-align:right; }}
.meta td {{ border:none; padding:3px 0; }}
.tot {{ width:45%; margin-left:auto; }}
.tot tr:last-child td {{ font-weight:700; font-size:15px; background:#e9eef6; }}
.hand {{ font-family:'Bradley Hand','Noteworthy',cursive; font-size:19px; color:#1a3fa8; transform:rotate(-4deg); display:inline-block; }}
.foot {{ display:flex; justify-content:space-between; margin-top:26px; }}
.stamp {{ border:2px solid #b3261e; color:#b3261e; border-radius:50%; width:110px; height:110px; display:flex; align-items:center;
          justify-content:center; text-align:center; font-weight:700; font-size:11px; transform:rotate(-12deg); opacity:.75; }}
</style></head><body>
<div class="top"><div><div class="vname">{html.escape(v['name'])}</div><div>{html.escape(v['address'])}</div>
<div>GSTIN: <b>{val['vendor_gstin']}</b> &nbsp; PAN: {v['pan']}</div><div>{v['email']}</div></div>
<div><div class="title">{L['title']}</div><table class="meta" style="width:auto;margin-left:auto">
<tr><td>{L['no']}:&nbsp;</td><td><b>{val['invoice_number']}</b></td></tr>
<tr><td>{L['date']}:&nbsp;</td><td>{date_cell}</td></tr>
<tr><td>{L['po']}:&nbsp;</td><td>{val['po_number']}</td></tr></table></div></div>
<p><b>{L['bill']}:</b> {settings.buyer_name}, Plot 12, MIDC Andheri East, Mumbai 400093, Maharashtra &nbsp;|&nbsp; GSTIN: {val['buyer_gstin']}
&nbsp;|&nbsp; Place of supply: Maharashtra (27)</p>
<table><tr><th>#</th><th>{L['desc']}</th><th>HSN</th><th class=r>{L['qty']}</th><th class=r>{L['rate']}</th><th class=r>GST</th><th class=r>{L['amt']}</th></tr>{rows}</table>
<table class="tot"><tr><td>{L['sub']}</td><td class=r>{rs(val['subtotal'])}</td></tr>{tax_rows}
<tr><td>{L['total']}</td><td class=r>{rs(val['total'])}</td></tr></table>
<div class="foot"><div><b>{L['bank']}:</b><br>A/c No: {val['bank_account']}<br>IFSC: {val['ifsc']}<br>A/c Name: {html.escape(v['name'])}</div>
<div class="stamp">{html.escape(v['name'].split()[0].upper())}<br>✓ VERIFIED</div>
<div style="text-align:center"><br><br>____________________<br>{L['sign']}</div></div>
</body></html>"""


def chrome(args: list[str]) -> None:
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", *args], check=True, capture_output=True, timeout=60)


def photo_effect(png: Path, jpg: Path, seed: int) -> None:
    rnd = random.Random(seed)
    img = Image.open(png).convert("RGB")
    bbox = Image.eval(img, lambda p: 255 - p).getbbox()  # crop the white canvas to content
    if bbox:
        img = img.crop((0, 0, img.width, min(img.height, bbox[3] + 40)))
    img = ImageEnhance.Color(img).enhance(0.85)
    paper = Image.new("RGB", img.size, (246, 240, 226))
    img = Image.blend(img, paper, 0.18)
    img = img.rotate(rnd.uniform(-3.5, -1.5), resample=Image.BICUBIC, expand=True, fillcolor=(92, 78, 64))
    # uneven lighting: darken one side
    grad = Image.linear_gradient("L").rotate(90).resize(img.size)
    img = Image.composite(img, ImageEnhance.Brightness(img).enhance(0.72), grad)
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    img.save(jpg, "JPEG", quality=68)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    settings.fixtures_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    for i, spec in enumerate(INVOICES):
        val = invoice_values(spec)
        page = tmp / f"{spec['file']}.html"
        page.write_text(render_html(spec, val), encoding="utf-8")
        if spec.get("scan"):
            png = tmp / f"{spec['file']}.png"
            chrome([f"--screenshot={png}", "--window-size=950,1150", page.as_uri()])
            out = OUT / f"{spec['file']}.jpg"
            photo_effect(png, out, seed=i)
        else:
            out = OUT / f"{spec['file']}.pdf"
            chrome(["--no-pdf-header-footer", f"--print-to-pdf={out}", page.as_uri()])

        # Offline fixture = what a perfect read of the document returns
        extracted = json.loads(json.dumps(val))
        for line, en in zip(extracted["line_items"], spec.get("desc_en", []), strict=False):
            line["description"] = en
        conf = {k: 0.97 for k, val_ in extracted.items() if val_ not in (None, [], "") and k != "line_items"}
        conf.update(spec.get("low_conf", {}))
        extracted["confidence"] = conf
        markdown = f"# {val['vendor_name']}\nGSTIN {val['vendor_gstin']}\nInvoice {val['invoice_number']} dated {val['invoice_date']}\n" + "\n".join(
            f"| {line['description']} | {line['qty']} | {line['unit_price']} | {line['amount']} |" for line in val["line_items"]
        ) + f"\nTotal {val['total']}"
        (settings.fixtures_dir / f"{spec['file']}.json").write_text(
            json.dumps({"markdown": markdown, "extracted": extracted, "expect": spec["expect"], "story": spec["story"]}, ensure_ascii=False, indent=2)
        )
        print(f"{out.name:40s} {rs(val['total']):>16s}  expect {spec['expect']}")


if __name__ == "__main__":
    main()
