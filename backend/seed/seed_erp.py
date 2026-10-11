"""Reset the demo database and load vendors, POs and GRNs.  Run:  python -m seed.seed_erp"""

import shutil

from sqlmodel import Session, SQLModel, select

from app.config import settings
from app.db import engine, init_db
from app.models import ApiUsage, DocCache, GoodsReceipt, GRNLine, POLine, PurchaseOrder, Vendor
from seed.data import POS, VENDORS, d


def main() -> None:
    # Sarvam usage + result cache survive resets: the budget stays honest and re-running the demo is free.
    keep = {ApiUsage.__tablename__, DocCache.__tablename__}
    SQLModel.metadata.drop_all(engine, tables=[t for name, t in SQLModel.metadata.tables.items() if name not in keep])
    init_db()
    shutil.rmtree(settings.upload_dir, ignore_errors=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    with Session(engine) as s:
        ids = {}
        for v in VENDORS:
            row = Vendor(**{k: v[k] for k in Vendor.model_fields if k in v})
            s.add(row)
            s.flush()
            ids[v["key"]] = row.id
        for n, po in enumerate(POS, start=1):
            lines = [POLine(po_id=0, line_no=i, description=desc, hsn=hsn, qty=qty, unit_price=price, tax_rate=rate)
                     for i, (desc, hsn, qty, price, rate) in enumerate(po["lines"], start=1)]
            row = PurchaseOrder(po_number=po["po"], vendor_id=ids[po["vendor"]], po_date=d(po["days_ago"]),
                                total=round(sum(line.qty * line.unit_price * (1 + line.tax_rate / 100) for line in lines), 2))
            s.add(row)
            s.flush()
            for line in lines:
                line.po_id = row.id
                s.add(line)
            grn = GoodsReceipt(grn_number=f"GRN-2026-{n:04d}", po_id=row.id, received_date=d(po["days_ago"] - 7))
            s.add(grn)
            s.flush()
            for i, qty in enumerate(po["received"], start=1):
                s.add(GRNLine(grn_id=grn.id, po_line_no=i, qty_received=qty))
        s.commit()
        cached = len(s.exec(select(DocCache)).all())
    print(f"Seeded {len(VENDORS)} vendors, {len(POS)} POs (+GRNs); {cached} cached Sarvam results. Buyer GSTIN {settings.buyer_gstin}")
    for v in VENDORS:
        print(f"  {v['name']:32s} {v['gstin']}  state {v['state_code']}  {'MSME' if v['msme'] else ''}")


if __name__ == "__main__":
    main()
