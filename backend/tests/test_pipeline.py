"""End-to-end over all 8 demo invoices in offline mode: every planted problem must be caught."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from seed import seed_erp
from seed.data import INVOICES

SAMPLES = Path(__file__).resolve().parents[2] / "sample_invoices"


@pytest.fixture(scope="module")
def client():
    seed_erp.main()
    with TestClient(app) as c:
        yield c


def _wait(client, inv_id):
    for _ in range(100):
        data = client.get(f"/invoices/{inv_id}").json()
        if any(p["step"] == "complete" for p in data["progress"]):
            return data
        time.sleep(0.1)
    raise AssertionError("pipeline did not finish")


def test_all_scenarios(client):
    results = {}
    for spec in INVOICES:  # in order: #4 must see #1 first
        path = next(SAMPLES.glob(spec["file"] + ".*"))
        r = client.post("/invoices", files=[("files", (path.name, path.read_bytes()))])
        assert r.status_code == 201, r.text
        data = _wait(client, r.json()[0]["id"])
        results[spec["file"]] = (data["invoice"]["status"], {i["code"] for i in data["issues"]})

    expected = {
        "01_bharat_clean": ("SCHEDULED", None),
        "02_technova_price_variance": ("ON_HOLD", "PRICE_VARIANCE"),
        "03_kaveri_tamil_short_receipt": ("ON_HOLD", "QTY_EXCEEDS_RECEIVED"),
        "04_bharat_duplicate_resend": ("ON_HOLD", "DUPLICATE"),
        "05_gujchem_bad_gstin": ("ON_HOLD", "INVALID_GSTIN"),
        "06_ganesh_wrong_tax": ("ON_HOLD", "WRONG_TAX_TYPE"),
        "07_ganesh_bank_change": ("ON_HOLD", "BANK_CHANGE"),
        "08_bharat_hindi_scan": ("PENDING_APPROVAL", "LOW_CONFIDENCE"),
    }
    for name, (status, code) in expected.items():
        got_status, got_codes = results[name]
        assert got_status == status, f"{name}: {got_status} {got_codes}"
        if code:
            assert code in got_codes, f"{name}: {got_codes}"
    print(json.dumps({k: [v[0], sorted(v[1])] for k, v in results.items()}, indent=1))


def test_fix_field_then_approve_and_pay(client):
    hindi = next(i for i in client.get("/invoices").json() if i["file_name"].startswith("08_"))
    fixed = client.patch(f"/invoices/{hindi['id']}/fields", json={"fields": {"invoice_date": hindi["invoice_date"]}}).json()
    assert fixed["invoice"]["status"] == "SCHEDULED"  # human verified the date → clean & under limit → auto

    variance = next(i for i in client.get("/invoices").json() if i["file_name"].startswith("02_"))
    assert client.post(f"/invoices/{variance['id']}/approve", json={}).status_code == 400  # override needs a comment
    ok = client.post(f"/invoices/{variance['id']}/approve", json={"comment": "Price revision agreed by procurement"}).json()
    assert ok["invoice"]["status"] == "SCHEDULED"

    run = client.post("/payments/run").json()
    assert run["count"] == 3
    stats = client.get("/dashboard/stats").json()
    assert stats["money_saved"] > 0 and stats["usage"]["tokens_used"] == 0


def test_real_world_invoice_unknown_vendor_to_payment(client):
    """A real upload from a supplier we've never seen: onboard vendor → retro PO → approved."""
    from app.utils.gst import make_gstin

    inv = next(i for i in client.get("/invoices").json() if i["file_name"].startswith("07_"))
    new_gstin = make_gstin("27", "AAKCN4455R")
    d = client.patch(f"/invoices/{inv['id']}/fields", json={"fields": {"vendor_name": "Navkar Traders", "vendor_gstin": new_gstin, "po_number": "VERBAL-ORDER"}}).json()
    codes = {i["code"] for i in d["issues"]}
    assert d["invoice"]["status"] == "ON_HOLD" and {"UNKNOWN_VENDOR", "NO_PO"} <= codes

    assert client.post(f"/invoices/{inv['id']}/retro-po", json={}).status_code == 400  # vendor first
    d = client.post(f"/invoices/{inv['id']}/onboard-vendor", json={"actor": "ap.clerk"}).json()
    assert "UNKNOWN_VENDOR" not in {i["code"] for i in d["issues"]} and d["vendor"]["gstin"] == new_gstin

    d = client.post(f"/invoices/{inv['id']}/retro-po", json={"actor": "ap.clerk"}).json()
    assert d["invoice"]["po_number"].startswith("PO-RETRO-")
    assert d["invoice"]["status"] == "SCHEDULED", [i["code"] for i in d["issues"]]
