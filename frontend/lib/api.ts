export const API = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000";

export type Status =
  | "UPLOADED" | "PARSED" | "EXTRACTED" | "VALIDATED" | "MATCHED"
  | "PENDING_APPROVAL" | "ON_HOLD" | "APPROVED" | "REJECTED" | "SCHEDULED" | "PAID" | "FAILED";

export type InvoiceRow = {
  id: number;
  file_name: string;
  status: Status;
  created_at: string;
  vendor_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  po_number: string | null;
  total: number | null;
  amount_at_risk: number;
  language: string | null;
  explanation: string | null;
  blockers: number;
  warnings: number;
  top_issue: string | null;
};

export type Issue = {
  id: number;
  code: string;
  severity: "info" | "warning" | "blocker";
  field: string | null;
  message: string;
  expected: string | null;
  actual: string | null;
};

export type LineMatch = {
  invoice_line_no: number;
  po_line_no: number | null;
  description: string;
  invoice_qty: number;
  po_qty: number | null;
  received_qty: number | null;
  previously_invoiced_qty: number | null;
  invoice_price: number;
  po_price: number | null;
  price_variance_pct: number | null;
  status: string;
};

export type Progress = { step: string; status: string; message: string; ts: string };

export type InvoiceDetail = {
  invoice: InvoiceRow & {
    vendor_gstin: string | null;
    buyer_gstin: string | null;
    subtotal: number | null;
    cgst: number | null;
    sgst: number | null;
    igst: number | null;
    bank_account: string | null;
    ifsc: string | null;
    confidence: Record<string, number> | null;
    extracted: Record<string, unknown> | null;
    match_result: { po_number: string | null; po_found: boolean; lines: LineMatch[] } | null;
    decision: { outcome: string; reasons: string[]; approval_chain: string[]; suggested_action: string | null } | null;
    erp_bill_id: string | null;
    raw_markdown: string | null;
  };
  vendor: { name: string; gstin: string; bank_account: string; ifsc: string; msme: boolean; preferred_language: string } | null;
  lines: { line_no: number; description: string; hsn: string | null; qty: number; unit_price: number; tax_rate: number | null; amount: number }[];
  issues: Issue[];
  approvals: { id: number; level: number; approver_role: string; status: string; comment: string | null; decided_by: string | null }[];
  payments: { amount: number; scheduled_date: string; status: string; utr: string | null; run_id: string | null }[];
  audit: { id: number; actor: string; action: string; detail: Record<string, unknown> | null; created_at: string }[];
  progress: Progress[];
};

export type Stats = {
  total: number;
  by_status: Record<string, number>;
  auto_approval_rate: number;
  on_hold: number;
  pending_amount: number;
  paid_amount: number;
  avg_processing_seconds: number | null;
  money_saved: number;
  blockers_by_code: Record<string, number>;
  usage: { tokens_used: number; token_budget: number; pages_used: number; page_budget: number; calls: number; mode: string };
};

export type Payment = {
  id: number; invoice_id: number; amount: number; scheduled_date: string; status: string;
  utr: string | null; run_id: string | null; invoice_number: string; vendor_name: string; bank_account: string; msme: boolean;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    let msg = `${res.status}`;
    try {
      msg = (await res.json()).detail ?? msg;
    } catch {}
    throw new Error(msg);
  }
  return res.json();
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

export function inr(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export const STATUS_STYLE: Record<string, string> = {
  UPLOADED: "bg-slate-100 text-slate-600",
  PARSED: "bg-sky-50 text-sky-700",
  EXTRACTED: "bg-sky-50 text-sky-700",
  VALIDATED: "bg-sky-50 text-sky-700",
  MATCHED: "bg-sky-50 text-sky-700",
  PENDING_APPROVAL: "bg-amber-100 text-amber-800",
  ON_HOLD: "bg-red-100 text-red-700",
  APPROVED: "bg-emerald-100 text-emerald-700",
  SCHEDULED: "bg-indigo-100 text-indigo-700",
  PAID: "bg-emerald-600 text-white",
  REJECTED: "bg-slate-700 text-white",
  FAILED: "bg-red-600 text-white",
};

export const PROCESSING = new Set(["UPLOADED", "PARSED", "EXTRACTED", "VALIDATED", "MATCHED"]);

export const LANG: Record<string, string> = {
  "hi-IN": "हिन्दी", "ta-IN": "தமிழ்", "en-IN": "EN", "hi-en": "हिन्दी+EN", "mr-IN": "मराठी", "gu-IN": "ગુજરાતી",
};
