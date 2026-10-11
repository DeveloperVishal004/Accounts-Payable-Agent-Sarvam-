# Hisaab: Accounts Payable Agent (Idea #24) on Sarvam

**One flow from start to finish:** drop in an invoice (a PDF, a scan or a phone photo, in English, हिन्दी, தமிழ் and more). The agent then:

1. **reads** it with **Sarvam Vision** (Document Intelligence),
2. **extracts** the fields with **Sarvam-105B** (structured JSON output),
3. **validates** the invoice with fixed rules: GSTIN checksum, arithmetic, CGST/SGST vs IGST, duplicates, bank-detail changes and the MSME 45-day rule,
4. **matches** each line against the PO and the goods receipt (a **3-way match**),
5. **decides** the outcome: auto-approve, send to approval (with the approval chain set by amount), or hold, with a reason,
6. **pays** through an ERP (mocked) payment run, which returns a UTR. Every step is written to an audit trail.

The LLM *reads* and *explains*. It never decides whether money moves; validation, matching and approval routing are plain Python rules, so every decision can be explained and audited.

## Run

```bash
cp backend/.env.example backend/.env   # put your SARVAM_API_KEY in it (never commit it)
./run.sh --setup                       # first time
./run.sh                               # afterwards  ·  ./run.sh --reset for a clean demo
```
Then open http://localhost:3000 and drag the files from `sample_invoices/` onto the dashboard.

Without an API key the backend runs **offline** from `backend/seed/fixtures/`, which is what the tests use.
Tests: `cd backend && .venv/bin/python -m pytest`

## Keeping API usage low (limited credits)

| Guard | Where |
|---|---|
| Hard caps checked **before** every call: `SARVAM_TOKEN_BUDGET`, `SARVAM_PAGE_BUDGET` | `backend/.env`, `app/services/usage.py` |
| Per-file cache (by SHA-256): re-uploads, re-processing and demo resets cost **0** credits | `DocCache` table |
| OCR text compacted before the LLM: embedded images and their auto-captions are dropped (a PDF goes from 17k to under 1k characters) | `extraction._compact` |
| Reasoning off, `max_tokens` capped, temperature 0 | `extraction.py`, `explain.py` |
| AI explanation and vendor email run **only when clicked** | invoice page |
| Live usage meter | dashboard |

The measured cost is about **1,300 tokens + 1 page per invoice**.

## 3-minute demo script

1. Drop all 8 files from `sample_invoices/` at once and watch each one move through Read, Extract, Match, Checks and Decision live.
2. **#1 clean** is auto-approved and scheduled for payment with nobody touching it. **#8 Hindi phone photo** (handwritten date) does the same.
3. Open **#7 bank change** to show the fraud signal: "confirm with the vendor by phone before paying".
4. Open **#2 price variance** and show the 3-way match table with the monitor at +8%. Click **✨ Explain with Sarvam-105B**.
5. Open **#3 Tamil photo**, where the GRN shows a short receipt (400 of 500 received). Click **✉️ Draft vendor email** in `ta-IN`.
6. Show **#4 duplicate** and **#5 fake GSTIN**, and point to the **Leakage stopped** total.
7. On #2, override with the comment "price revision agreed", then click **Pay** on the dashboard. The invoices are paid with UTRs, and the audit trail shows every step.

| File | Planted problem | Agent outcome |
|---|---|---|
| 01_bharat_clean.pdf | none | AUTO-APPROVED → scheduled |
| 02_technova_price_variance.pdf | monitor billed 8% over PO | ON HOLD · PRICE_VARIANCE |
| 03_kaveri_tamil_short_receipt.jpg | Tamil photo, billed 500 m, received 400 m | ON HOLD · QTY_EXCEEDS_RECEIVED |
| 04_bharat_duplicate_resend.pdf | re-sent copy of #1 | ON HOLD · DUPLICATE |
| 05_gujchem_bad_gstin.pdf | GSTIN checksum wrong | ON HOLD · INVALID_GSTIN |
| 06_ganesh_wrong_tax.pdf | IGST on an intra-state supply | ON HOLD · WRONG_TAX_TYPE |
| 07_ganesh_bank_change.pdf | new bank account on the invoice | ON HOLD · BANK_CHANGE |
| 08_bharat_hindi_scan.jpg | Hindi photo, handwritten date | read correctly → auto-approved |

## Layout
```
backend/app/services/  sarvam.py (only Sarvam client) · extraction · validation · matching · decision · pipeline · explain · usage
backend/app/erp/       ERPAdapter protocol + MockERP (swap in a Tally/Zoho connector)
backend/seed/          demo vendors/POs/GRNs + invoice generator (headless Chrome → PDF/photo)
frontend/app/          dashboard (upload, queue, payments) · invoices/[id] (document, verdict, match, fields, audit)
```
