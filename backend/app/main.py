import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from app.config import settings
from app.db import engine, init_db
from app.models import DocCache, Vendor
from app.routers import invoices, other


def _bootstrap() -> None:
    """Hosted instances start with an empty disk: seed the ERP and preload real Sarvam results for the samples."""
    init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    with Session(engine) as s:
        empty = s.exec(select(Vendor)).first() is None
    if empty:
        from seed import seed_erp

        seed_erp.main()
    if settings.prebuilt_cache.exists():
        with Session(engine) as s:
            for file_hash, row in json.loads(settings.prebuilt_cache.read_text()).items():
                if s.get(DocCache, file_hash) is None:
                    s.add(DocCache(file_hash=file_hash, markdown=row["markdown"], extracted=row["extracted"]))
            s.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    _bootstrap()
    yield


app = FastAPI(title="AP Agent · Sarvam", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(invoices.router)
app.include_router(other.router)


@app.get("/health")
def health():
    return {"ok": True, "mode": "mock" if settings.mock_mode else "live", "model": settings.sarvam_chat_model}
