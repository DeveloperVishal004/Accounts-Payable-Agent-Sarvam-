"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Kpi, Meter, StatusBadge } from "@/components/ui";
import { API, api, inr, InvoiceRow, LANG, Payment, post, PROCESSING, Progress, Stats } from "@/lib/api";

const STEPS = ["parse", "extract", "match", "validate", "decide"] as const;
const STEP_LABEL: Record<string, string> = { parse: "Read (Vision)", extract: "Extract (105B)", match: "3-way match", validate: "Checks", decide: "Decision" };

type Live = { id: number; name: string; events: Progress[] };

const FILTERS: { key: string; label: string; statuses?: string }[] = [
  { key: "all", label: "All" },
  { key: "hold", label: "On hold", statuses: "ON_HOLD" },
  { key: "approval", label: "Needs approval", statuses: "PENDING_APPROVAL" },
  { key: "scheduled", label: "Scheduled", statuses: "APPROVED,SCHEDULED" },
  { key: "paid", label: "Paid", statuses: "PAID" },
];

export default function Dashboard() {
  const [rows, setRows] = useState<InvoiceRow[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [live, setLive] = useState<Live[]>([]);
  const [filter, setFilter] = useState("all");
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const f = FILTERS.find((x) => x.key === filter)?.statuses;
      const [r, s, p] = await Promise.all([
        api<InvoiceRow[]>(`/invoices${f ? `?status=${f}` : ""}`),
        api<Stats>("/dashboard/stats"),
        api<Payment[]>("/payments"),
      ]);
      setRows(r);
      setStats(s);
      setPayments(p);
      setErr(null);
    } catch (e) {
      setErr(`Backend not reachable at ${API} (${(e as Error).message})`);
    }
  }, [filter]);

  useEffect(() => {
    refresh();
    const busy = rows.some((r) => PROCESSING.has(r.status)) || live.some((l) => !l.events.some((e) => e.step === "complete"));
    const t = setInterval(refresh, busy ? 1500 : 5000);
    return () => clearInterval(t);
  }, [refresh, rows, live]);

  const onUploaded = (created: { id: number; file_name: string }[]) => {
    setLive((prev) => [...created.map((c) => ({ id: c.id, name: c.file_name, events: [] })), ...prev].slice(0, 8));
    created.forEach((c) => {
      const es = new EventSource(`${API}/invoices/${c.id}/events`);
      es.addEventListener("progress", (ev) => {
        const p = JSON.parse((ev as MessageEvent).data) as Progress;
        setLive((prev) => prev.map((l) => (l.id === c.id ? { ...l, events: [...l.events, p] } : l)));
        if (p.step === "complete") {
          es.close();
          refresh();
        }
      });
      es.onerror = () => es.close();
    });
    refresh();
  };

  const runPayments = async () => {
    const r = await post<{ run_id: string; count: number; amount: number }>("/payments/run");
    setToast(r.count ? `Payment run ${r.run_id}: paid ${r.count} invoice(s), ${inr(r.amount)}` : "Nothing scheduled to pay");
    setTimeout(() => setToast(null), 5000);
    refresh();
  };

  const scheduled = payments.filter((p) => p.status === "SCHEDULED");

  return (
    <div className="space-y-6">
      {err && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{err}</div>}
      {toast && <div className="fixed bottom-6 right-6 z-20 rounded-lg bg-slate-900 px-4 py-3 text-sm text-white shadow-lg">{toast}</div>}

      <section className="grid gap-4 lg:grid-cols-3">
        <Uploader onUploaded={onUploaded} />
        <div className="card p-5 lg:col-span-1">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Sarvam usage</h2>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${stats?.usage.mode === "live" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
              {stats?.usage.mode === "live" ? "● LIVE API" : "OFFLINE"}
            </span>
          </div>
          {stats && (
            <div className="mt-4 space-y-3">
              <Meter label="Chat tokens (Sarvam-105B)" used={stats.usage.tokens_used} total={stats.usage.token_budget} />
              <Meter label="Pages (Sarvam Vision)" used={stats.usage.pages_used} total={stats.usage.page_budget} />
              <p className="text-xs text-slate-500">
                {stats.usage.calls} API calls. Results are cached per file, so re-uploads and re-processing are free. Hard caps are set in backend/.env.
              </p>
            </div>
          )}
        </div>
      </section>

      {live.length > 0 && (
        <section className="card divide-y divide-slate-100">
          {live.map((l) => (
            <LiveRow key={l.id} l={l} />
          ))}
        </section>
      )}

      {stats && (
        <section className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
          <Kpi label="Invoices" value={String(stats.total)} hint={stats.avg_processing_seconds ? `avg ${stats.avg_processing_seconds}s each` : undefined} />
          <Kpi label="Auto-approved" value={`${stats.auto_approval_rate}%`} hint="zero-touch rate" tone="good" />
          <Kpi label="On hold" value={String(stats.on_hold)} tone={stats.on_hold ? "bad" : "default"} />
          <Kpi label="Outstanding" value={inr(stats.pending_amount)} />
          <Kpi label="Paid" value={inr(stats.paid_amount)} />
          <Kpi label="Leakage stopped" value={inr(stats.money_saved)} hint="duplicates, overbilling, fraud" tone="good" />
        </section>
      )}

      <section className="grid gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-2">
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
            <h2 className="mr-2 font-semibold">Invoice queue</h2>
            {FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={`rounded-full px-3 py-1 text-xs font-medium ${filter === f.key ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
              >
                {f.label}
                {f.statuses && stats ? ` ${f.statuses.split(",").reduce((n, s) => n + (stats.by_status[s] ?? 0), 0)}` : ""}
              </button>
            ))}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-2">Vendor / Invoice</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2 text-right">Amount</th>
                  <th className="px-4 py-2">Why</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5">
                      <Link href={`/invoices/${r.id}`} className="font-medium text-indigo-700 hover:underline">
                        {r.vendor_name ?? r.file_name}
                      </Link>
                      <div className="text-xs text-slate-500">
                        #{r.id} · {r.invoice_number ?? "…"} {r.language && !r.language.startsWith("en") && <span className="ml-1 rounded bg-orange-50 px-1 text-orange-700">{LANG[r.language] ?? r.language}</span>}
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{inr(r.total)}</td>
                    <td className="max-w-md px-4 py-2.5 text-xs text-slate-600">
                      <span className="line-clamp-2">{r.top_issue ?? (r.status === "PENDING_APPROVAL" ? r.explanation : r.warnings ? `${r.warnings} warning(s)` : PROCESSING.has(r.status) ? "processing…" : "All checks passed")}</span>
                    </td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr>
                    <td colSpan={4} className="px-4 py-10 text-center text-slate-400">
                      No invoices yet. Drop some above (try the files in <code>sample_invoices/</code>).
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-4">
          <div className="card p-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Payment run</h2>
              <button
                onClick={runPayments}
                disabled={!scheduled.length}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
              >
                Pay {scheduled.length ? `${scheduled.length} · ${inr(scheduled.reduce((a, p) => a + p.amount, 0))}` : ""}
              </button>
            </div>
            <ul className="mt-3 space-y-2 text-sm">
              {payments.slice(0, 8).map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate">{p.vendor_name}</div>
                    <div className="text-xs text-slate-500">
                      {p.status === "PAID" ? `UTR ${p.utr}` : `due ${p.scheduled_date}`} · {p.bank_account} {p.msme && <span className="text-orange-600">MSME</span>}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="tabular-nums">{inr(p.amount)}</div>
                    <StatusBadge status={p.status} />
                  </div>
                </li>
              ))}
              {!payments.length && <li className="text-slate-400">No payments yet</li>}
            </ul>
          </div>

          {stats && Object.keys(stats.blockers_by_code).length > 0 && (
            <div className="card p-4">
              <h2 className="font-semibold">What the agent caught</h2>
              <ul className="mt-2 space-y-1 text-sm">
                {Object.entries(stats.blockers_by_code).map(([code, n]) => (
                  <li key={code} className="flex justify-between">
                    <span className="font-mono text-xs text-slate-600">{code}</span>
                    <span className="font-semibold tabular-nums">{n}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function Uploader({ onUploaded }: { onUploaded: (c: { id: number; file_name: string }[]) => void }) {
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const send = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setError(null);
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    try {
      onUploaded(await api("/invoices", { method: "POST", body: fd }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        send(e.dataTransfer.files);
      }}
      onClick={() => input.current?.click()}
      className={`card flex cursor-pointer flex-col items-center justify-center border-2 border-dashed p-8 text-center transition lg:col-span-2 ${drag ? "border-indigo-500 bg-indigo-50" : "border-slate-300 hover:border-indigo-400"}`}
    >
      <input ref={input} type="file" multiple accept=".pdf,.png,.jpg,.jpeg" className="hidden" onChange={(e) => send(e.target.files)} />
      <div className="text-4xl">🧾</div>
      <div className="mt-2 text-lg font-semibold">{busy ? "Uploading…" : "Drop invoices here"}</div>
      <div className="mt-1 text-sm text-slate-500">PDF, scans or phone photos in English, हिन्दी, தமிழ் and more. The agent reads, checks, matches and routes each one.</div>
      {error && <div className="mt-2 text-sm text-red-600">{error}</div>}
    </div>
  );
}

function LiveRow({ l }: { l: Live }) {
  const last: Record<string, Progress> = {};
  l.events.forEach((e) => (last[e.step] = e));
  const done = !!last["complete"];
  const errored = Object.values(last).find((e) => e.status === "error");
  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3">
      <Link href={`/invoices/${l.id}`} className="w-64 truncate text-sm font-medium text-indigo-700 hover:underline">
        {l.name}
      </Link>
      <div className="flex flex-1 flex-wrap items-center gap-1.5">
        {last["queue"] && !last["parse"] && <span className="text-xs text-slate-500">queued…</span>}
        {STEPS.map((s) => {
          const e = last[s];
          const cls = !e ? "bg-slate-100 text-slate-400" : e.status === "error" ? "bg-red-100 text-red-700" : e.status === "done" ? "bg-emerald-100 text-emerald-700" : "animate-pulse bg-indigo-100 text-indigo-700";
          return (
            <span key={s} title={e?.message} className={`rounded-md px-2 py-1 text-xs font-medium ${cls}`}>
              {e?.status === "done" ? "✓ " : ""}
              {STEP_LABEL[s]}
            </span>
          );
        })}
      </div>
      <div className="w-72 truncate text-right text-xs text-slate-600">
        {errored ? <span className="text-red-600">{errored.message}</span> : done ? <b>{last["decide"]?.message}</b> : Object.values(last).at(-1)?.message}
      </div>
    </div>
  );
}
