from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.routers import invoices, other


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AP Agent · Sarvam", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(invoices.router)
app.include_router(other.router)


@app.get("/health")
def health():
    return {"ok": True, "mode": "mock" if settings.mock_mode else "live", "model": settings.sarvam_chat_model}
