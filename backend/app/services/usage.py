"""Sarvam credit guardrails: hard budgets checked BEFORE every call, usage recorded after."""

from sqlmodel import Session, func, select

from app.config import settings
from app.db import engine
from app.models import ApiUsage, DocCache


class BudgetExceeded(RuntimeError):
    pass


def totals(session: Session | None = None) -> dict:
    own = session is None
    s = session or Session(engine)
    try:
        tokens = s.exec(select(func.coalesce(func.sum(ApiUsage.prompt_tokens + ApiUsage.completion_tokens), 0))).one()
        pages = s.exec(select(func.coalesce(func.sum(ApiUsage.pages), 0))).one()
        calls = s.exec(select(func.count(ApiUsage.id))).one()
    finally:
        if own:
            s.close()
    return {
        "tokens_used": int(tokens),
        "token_budget": settings.sarvam_token_budget,
        "pages_used": int(pages),
        "page_budget": settings.sarvam_page_budget,
        "calls": int(calls),
        "mode": "mock" if settings.mock_mode else "live",
    }


def ensure_tokens(estimated: int) -> None:
    t = totals()
    if t["tokens_used"] + estimated > t["token_budget"]:
        raise BudgetExceeded(
            f"Sarvam token budget reached ({t['tokens_used']:,}/{t['token_budget']:,}). "
            "Raise SARVAM_TOKEN_BUDGET in backend/.env to continue."
        )


def ensure_pages(pages: int) -> None:
    t = totals()
    if t["pages_used"] + pages > t["page_budget"]:
        raise BudgetExceeded(
            f"Sarvam Vision page budget reached ({t['pages_used']}/{t['page_budget']} pages). "
            "Raise SARVAM_PAGE_BUDGET in backend/.env to continue."
        )


def record(kind: str, purpose: str, *, invoice_id: int | None = None, pages: int = 0, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    with Session(engine) as s:
        s.add(ApiUsage(kind=kind, purpose=purpose, invoice_id=invoice_id, pages=pages, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens))
        s.commit()


def estimate_tokens(text: str) -> int:
    # ~3.5 chars/token for English, Indic scripts tokenise denser, so stay conservative
    return len(text) // 3 + 1


# ---------------------------------------------------------------- cache


def cache_get(file_hash: str) -> DocCache | None:
    with Session(engine) as s:
        return s.get(DocCache, file_hash)


def cache_put(file_hash: str, **fields) -> None:
    with Session(engine) as s:
        row = s.get(DocCache, file_hash) or DocCache(file_hash=file_hash)
        for k, v in fields.items():
            setattr(row, k, v)
        s.add(row)
        s.commit()
