"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { SeverityPill, sevBox, StatusBadge } from "@/components/ui";
import { API, api, inr, InvoiceDetail, LANG, post, PROCESSING } from "@/lib/api";

const FIELDS: { key: string; label: string; money?: boolean }[] = [
  { key: "vendor_name", label: "Vendor" },
  { key: "vendor_gstin", label: "Vendor GSTIN" },
  { key: "invoice_number", label: "Invoice no." },
  { key: "invoice_date", label: "Invoice date" },
  { key: "po_number", label: "PO ref" },
  { key: "buyer_gstin", label: "Buyer GSTIN" },
  { key: "subtotal", label: "Taxable value", money: true },
  { key: "cgst", label: "CGST", money: true },
  { key: "sgst", label: "SGST", money: true },
  { key: "igst", label: "IGST", money: true },
  { key: "total", label: "Total", money: true },
  { key: "bank_account", label: "Bank a/c" },
  { key: "ifsc", label: "IFSC" },
];

const OUTCOME_STYLE: Record<string, string> = {
  AUTO_APPROVED: "border-emerald-300 bg-emerald-50",
  PENDING_APPROVAL: "border-amber-300 bg-amber-50",
  ON_HOLD: "border-red-300 bg-red-50",
};

const LINE_STATUS: Record<string, string> = {
  matched: "bg-emerald-100 text-emerald-700",
  price_variance: "bg-red-100 text-red-700",
  qty_exceeds_received: "bg-red-100 text-red-700",
  over_billing: "bg-red-100 text-red-700",
  unmatched: "bg-slate-200 text-slate-700",
};

export default function InvoicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [d, setD] = useState<InvoiceDetail | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [comment, setComment] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [emailLang, setEmailLang] = useState<string>("");
  const [showOcr, setShowOcr] = useState(false);

  const load = useCallback(async () => setD(await api<InvoiceDetail>(`/invoices/${id}`)), [id]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (!d || !PROCESSING.has(d.invoice.status)) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [d, load]);
  useEffect(() => {
    if (d?.vendor && !emailLang) setEmailLang(d.vendor.preferred_language);
  }, [d, emailLang]);

  const act = async (name: string, fn: () => Promise<unknown>, okText?: string) => {
    setBusy(name);
    setMsg(null);
    try {
      const r = await fn();
      if (r && typeof r === "object" && "invoice" in r) setD(r as InvoiceDetail);
      else await load();
      if (okText) setMsg({ ok: true, text: okText });
      return r;
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  if (!d) return <div className="text-slate-500">Loading…</div>;
  const inv = d.invoice;
  const conf = inv.confidence ?? {};
  const decision = inv.decision;
  const isImage = /\.(png|jpe?g)$/i.test(inv.file_name);
  const canAct = inv.status === "PENDING_APPROVAL" || inv.status === "ON_HOLD";
  const pendingStep = d.approvals.find((a) => a.status === "PENDING");
  const editable = ["ON_HOLD", "PENDING_APPROVAL"].includes(inv.status);
  const realIssues = d.issues.filter((i) => i.severity !== "info");

  const saveEdits = () =>
    act(
      "save",
      () =>
        api(`/invoices/${id}/fields`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            fields: Object.fromEntries(
              Object.entries(edits).map(([k, v]) => [k, FIELDS.find((f) => f.key === k)?.money ? (v === "" ? null : Number(v)) : v || null]),
            ),
          }),
        }),
      "Fields corrected. Checks and matching were re-run (no AI credits used).",
    ).then(() => setEdits({}));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href="/" className="text-sm text-slate-500 hover:underline">
            ← Queue
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            {inv.vendor_name ?? inv.file_name}{" "}
            {inv.language && !inv.language.startsWith("en") && <span className="ml-1 rounded bg-orange-50 px-1.5 py-0.5 align-middle text-sm text-orange-700">{LANG[inv.language] ?? inv.language}</span>}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-sm text-slate-600">
            <span>Invoice {inv.invoice_number ?? "—"}</span>
            <span>· PO {inv.po_number ?? "—"}</span>
            <span>· due {inv.due_date ?? "—"}</span>
            {d.vendor?.msme && <span className="rounded bg-orange-100 px-1.5 text-xs font-semibold text-orange-700">MSME · 45-day rule</span>}
            <StatusBadge status={inv.status} />
          </div>
        </div>
        <div className="text-right">
          <div className="text-3xl font-semibold tabular-nums">{inr(inv.total)}</div>
          {inv.amount_at_risk > 0 && <div className="text-sm font-medium text-red-600">{inr(inv.amount_at_risk)} at risk</div>}
        </div>
      </div>

      {msg && <div className={`rounded-lg px-4 py-2 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"}`}>{msg.text}</div>}

      <div className="grid gap-5 lg:grid-cols-5">
        {/* Document */}
        <div className="card overflow-hidden lg:col-span-2">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2 text-sm">
            <span className="font-medium">{showOcr ? "What Sarvam Vision read" : "Original document"}</span>
            <button onClick={() => setShowOcr(!showOcr)} className="text-xs text-indigo-700 hover:underline">
              {showOcr ? "Show document" : "Show OCR text"}
            </button>
          </div>
          {showOcr ? (
            <pre className="max-h-[720px] overflow-auto whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed text-slate-700">
              {(inv.raw_markdown ?? "—").replace(/!\[[^\]]*\]\(data:[^)]*\)/g, "[image]")}
            </pre>
          ) : isImage ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`${API}/invoices/${id}/file`} alt="invoice" className="w-full" />
          ) : (
            <iframe src={`${API}/invoices/${id}/file#toolbar=0&view=FitH`} className="h-[720px] w-full" title="invoice" />
          )}
        </div>

        <div className="space-y-5 lg:col-span-3">
          {/* Verdict */}
          {PROCESSING.has(inv.status) ? (
            <div className="card animate-pulse p-5 text-slate-500">Agent is processing this invoice…</div>
          ) : (
            decision && (
              <div className={`rounded-xl border-2 p-5 ${OUTCOME_STYLE[decision.outcome] ?? "border-slate-200 bg-white"}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-xs font-bold uppercase tracking-wider text-slate-500">Agent decision</div>
                  <div className="text-sm font-bold">{decision.outcome.replace("_", " ")}</div>
                </div>
                <p className="mt-2 text-[15px] leading-relaxed">{inv.explanation}</p>
                {decision.suggested_action && (
                  <p className="mt-2 text-sm">
                    <b>Next step:</b> {decision.suggested_action}
                  </p>
                )}
                {decision.approval_chain.length > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                    <b>Approval chain:</b>
                    {d.approvals.map((a) => (
                      <span key={a.id} className={`rounded-full px-2 py-0.5 ${a.status === "APPROVED" ? "bg-emerald-100 text-emerald-700" : a.status === "PENDING" ? "bg-amber-200 text-amber-900" : "bg-slate-100 text-slate-500"}`}>
                        {a.level}. {a.approver_role} · {a.status.toLowerCase()}
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    onClick={() => act("explain", () => post(`/invoices/${id}/explain`), "Explanation generated by Sarvam-105B")}
                    disabled={!!busy}
                    className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium hover:bg-slate-50 disabled:opacity-50"
                  >
                    {busy === "explain" ? "Thinking…" : "✨ Explain with Sarvam-105B"}
                  </button>
                  {realIssues.length > 0 && (
                    <span className="flex items-center gap-1">
                      <select value={emailLang} onChange={(e) => setEmailLang(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs">
                        {["en-IN", "hi-IN", "ta-IN", "mr-IN", "gu-IN", "te-IN", "kn-IN", "bn-IN"].map((l) => (
                          <option key={l} value={l}>
                            {l}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={async () => {
                          const r = (await act("email", () => post<{ email: string }>(`/invoices/${id}/vendor-email?lang=${emailLang}`))) as { email: string } | undefined;
                          if (r?.email) setEmail(r.email);
                        }}
                        disabled={!!busy}
                        className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium hover:bg-slate-50 disabled:opacity-50"
                      >
                        {busy === "email" ? "Drafting…" : "✉️ Draft vendor email"}
                      </button>
                    </span>
                  )}
                </div>
                {email && <pre className="mt-3 whitespace-pre-wrap rounded-lg bg-white p-3 text-sm leading-relaxed">{email}</pre>}
              </div>
            )
          )}

          {/* Actions */}
          {canAct && (
            <div className="card p-4">
              <div className="text-sm font-semibold">
                {inv.status === "ON_HOLD" ? "Resolve hold" : `Your approval${pendingStep ? ` (${pendingStep.approver_role})` : ""}`}
              </div>
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder={inv.status === "ON_HOLD" ? "Comment (required to override a hold), e.g. 'price revision agreed by procurement'" : "Comment (optional)"}
                className="mt-2 w-full rounded-lg border border-slate-300 p-2 text-sm"
                rows={2}
              />
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  onClick={() => act("approve", () => post(`/invoices/${id}/approve`, { actor: "you", role: pendingStep?.approver_role, comment: comment || null }), "Approved")}
                  disabled={!!busy}
                  className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  {inv.status === "ON_HOLD" ? "Override & approve" : "Approve"}
                </button>
                <button
                  onClick={() => act("reject", () => post(`/invoices/${id}/reject`, { actor: "you", comment: comment || null }), "Rejected")}
                  disabled={!!busy}
                  className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-900 disabled:opacity-50"
                >
                  Reject
                </button>
                {inv.status !== "ON_HOLD" && (
                  <button onClick={() => act("hold", () => post(`/invoices/${id}/hold`, { actor: "you", comment: comment || null }), "Put on hold")} disabled={!!busy} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold hover:bg-slate-50">
                    Hold
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Issues */}
          {d.issues.length > 0 && (
            <div className="card p-4">
              <h2 className="font-semibold">Findings</h2>
              <ul className="mt-3 space-y-2">
                {d.issues.map((i) => (
                  <li key={i.id} className={`rounded-lg border p-3 text-sm ${sevBox[i.severity]}`}>
                    <div className="flex items-center gap-2">
                      <SeverityPill severity={i.severity} />
                      <span className="font-mono text-xs opacity-70">{i.code}</span>
                    </div>
                    <div className="mt-1">{i.message}</div>
                    {(i.expected || i.actual) && (
                      <div className="mt-1 font-mono text-xs">
                        {i.expected && <span>expected {i.expected}</span>} {i.actual && <span className="ml-2">got {i.actual}</span>}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 3-way match */}
          {inv.match_result && (
            <div className="card overflow-hidden">
              <div className="border-b border-slate-100 px-4 py-3 font-semibold">
                3-way match {inv.match_result.po_found ? <span className="font-normal text-slate-500">· invoice vs {inv.match_result.po_number} vs GRN</span> : <span className="text-red-600">· no PO</span>}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-3 py-2 text-left">Item</th>
                      <th className="px-3 py-2 text-right">Billed qty</th>
                      <th className="px-3 py-2 text-right">PO qty</th>
                      <th className="px-3 py-2 text-right">Received</th>
                      <th className="px-3 py-2 text-right">Billed rate</th>
                      <th className="px-3 py-2 text-right">PO rate</th>
                      <th className="px-3 py-2">Result</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 tabular-nums">
                    {inv.match_result.lines.map((l) => (
                      <tr key={l.invoice_line_no}>
                        <td className="px-3 py-2">{l.description}</td>
                        <td className={`px-3 py-2 text-right ${l.received_qty !== null && l.invoice_qty > l.received_qty ? "font-bold text-red-600" : ""}`}>{l.invoice_qty}</td>
                        <td className="px-3 py-2 text-right">{l.po_qty ?? "—"}</td>
                        <td className="px-3 py-2 text-right">{l.received_qty ?? "—"}</td>
                        <td className={`px-3 py-2 text-right ${(l.price_variance_pct ?? 0) > 2 ? "font-bold text-red-600" : ""}`}>{inr(l.invoice_price)}</td>
                        <td className="px-3 py-2 text-right">
                          {inr(l.po_price)}
                          {l.price_variance_pct ? <span className="ml-1 text-xs text-slate-500">({l.price_variance_pct > 0 ? "+" : ""}{l.price_variance_pct}%)</span> : null}
                        </td>
                        <td className="px-3 py-2">
                          <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${LINE_STATUS[l.status] ?? ""}`}>{l.status.replaceAll("_", " ")}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Extracted fields */}
          {inv.extracted && (
            <div className="card p-4">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Extracted fields</h2>
                <span className="text-xs text-slate-500">amber = low confidence, so please verify</span>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {FIELDS.map((f) => {
                  const v = inv[f.key as keyof typeof inv] as string | number | null;
                  const c = conf[f.key];
                  const low = c !== undefined && c < 0.75;
                  return (
                    <label key={f.key} className="block">
                      <span className="flex justify-between text-xs text-slate-500">
                        {f.label}
                        {c !== undefined && <span className={low ? "font-semibold text-amber-600" : ""}>{Math.round(c * 100)}%</span>}
                      </span>
                      <input
                        disabled={!editable}
                        value={edits[f.key] ?? (v ?? "").toString()}
                        onChange={(e) => setEdits({ ...edits, [f.key]: e.target.value })}
                        className={`mt-0.5 w-full rounded-md border px-2 py-1.5 font-mono text-sm disabled:bg-slate-50 ${low ? "border-amber-400 bg-amber-50" : "border-slate-200"} ${edits[f.key] !== undefined ? "ring-2 ring-indigo-300" : ""}`}
                      />
                    </label>
                  );
                })}
              </div>
              {editable && Object.keys(edits).length > 0 && (
                <button onClick={saveEdits} disabled={!!busy} className="mt-3 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">
                  Save & re-check
                </button>
              )}
              {editable && inv.confidence && Object.values(inv.confidence).some((x) => x < 0.75) && Object.keys(edits).length === 0 && (
                <button
                  onClick={() => {
                    const low = Object.entries(inv.confidence ?? {}).filter(([, x]) => x < 0.75).map(([k]) => k);
                    setEdits(Object.fromEntries(low.map((k) => [k, String(inv[k as keyof typeof inv] ?? "")])));
                  }}
                  className="mt-3 rounded-lg border border-amber-400 bg-amber-50 px-3 py-1.5 text-sm font-medium text-amber-900"
                >
                  I verified the highlighted fields
                </button>
              )}
              <table className="mt-4 w-full text-sm">
                <thead className="text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-1 text-left">#</th>
                    <th className="py-1 text-left">Description</th>
                    <th className="py-1 text-left">HSN</th>
                    <th className="py-1 text-right">Qty</th>
                    <th className="py-1 text-right">Rate</th>
                    <th className="py-1 text-right">GST</th>
                    <th className="py-1 text-right">Amount</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {d.lines.map((l) => (
                    <tr key={l.line_no} className="border-t border-slate-100">
                      <td className="py-1.5">{l.line_no}</td>
                      <td className="py-1.5">{l.description}</td>
                      <td className="py-1.5 font-mono text-xs">{l.hsn}</td>
                      <td className="py-1.5 text-right">{l.qty}</td>
                      <td className="py-1.5 text-right">{inr(l.unit_price)}</td>
                      <td className="py-1.5 text-right">{l.tax_rate ?? "—"}%</td>
                      <td className="py-1.5 text-right">{inr(l.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Payment + audit */}
          {d.payments.length > 0 && (
            <div className="card p-4 text-sm">
              <h2 className="font-semibold">Payment</h2>
              {d.payments.map((p, i) => (
                <div key={i} className="mt-2 flex justify-between">
                  <span>
                    {inv.erp_bill_id} · {p.status === "PAID" ? `paid, UTR ${p.utr}` : `scheduled for ${p.scheduled_date}`}
                  </span>
                  <StatusBadge status={p.status} />
                </div>
              ))}
            </div>
          )}

          <div className="card p-4">
            <h2 className="font-semibold">Audit trail</h2>
            <ol className="mt-3 space-y-2 border-l-2 border-slate-200 pl-4 text-sm">
              {d.audit.map((a) => (
                <li key={a.id} className="relative">
                  <span className={`absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full ${a.actor === "agent" ? "bg-indigo-500" : a.actor === "erp" ? "bg-emerald-500" : "bg-orange-500"}`} />
                  <span className="font-medium">{a.action.replaceAll("_", " ")}</span>{" "}
                  <span className="text-xs text-slate-500">
                    by {a.actor} · {new Date(a.created_at).toLocaleTimeString("en-IN")}
                  </span>
                  {a.detail && (
                    <div className="truncate font-mono text-[11px] text-slate-500">
                      {Object.entries(a.detail)
                        .filter(([k]) => !["reasons", "text", "before", "after"].includes(k))
                        .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`)
                        .join("  ")}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
}
