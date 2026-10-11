import { STATUS_STYLE } from "@/lib/api";

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS_STYLE[status] ?? "bg-slate-100"}`}>
      {status.replace("_", " ")}
    </span>
  );
}

export function Kpi({ label, value, hint, tone = "default" }: { label: string; value: string; hint?: string; tone?: "default" | "good" | "bad" }) {
  const color = tone === "good" ? "text-emerald-600" : tone === "bad" ? "text-red-600" : "text-slate-900";
  return (
    <div className="card p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function Meter({ label, used, total }: { label: string; used: number; total: number }) {
  const pct = Math.min(100, (used / Math.max(1, total)) * 100);
  const bar = pct > 85 ? "bg-red-500" : pct > 60 ? "bg-amber-500" : "bg-indigo-500";
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-600">
        <span>{label}</span>
        <span className="tabular-nums">
          {used.toLocaleString("en-IN")} / {total.toLocaleString("en-IN")}
        </span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-slate-100">
        <div className={`h-1.5 rounded-full ${bar}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

const SEV = {
  blocker: "border-red-200 bg-red-50 text-red-800",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  info: "border-sky-200 bg-sky-50 text-sky-900",
} as const;

export function SeverityPill({ severity }: { severity: keyof typeof SEV }) {
  return <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${SEV[severity]}`}>{severity}</span>;
}

export const sevBox = SEV;
