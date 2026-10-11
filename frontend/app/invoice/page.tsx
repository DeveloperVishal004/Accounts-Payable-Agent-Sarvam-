import { Suspense } from "react";
import InvoiceView from "./view";

export default function InvoicePage() {
  return (
    <Suspense fallback={<div className="text-slate-500">Loading…</div>}>
      <InvoiceView />
    </Suspense>
  );
}
