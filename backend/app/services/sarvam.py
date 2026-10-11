"""The only module that talks to Sarvam. Docs: https://docs.sarvam.ai

- Document Intelligence (Sarvam Vision): POST /doc-ai/v1/job/digitise → poll /status → GET /download-url (ZIP)
- Chat (Sarvam-105B):                    POST /v1/chat/completions (supports response_format json_schema)

Every call goes through the budget guard in services/usage.py.
"""

import asyncio
import io
import json
import mimetypes
import re
import zipfile
from pathlib import Path

import httpx

from app.config import settings
from app.services import usage

TERMINAL = {"completed", "partially_completed", "failed", "rejected"}


class SarvamError(RuntimeError):
    pass


async def _send(client: httpx.AsyncClient, method: str, url: str, **kw) -> httpx.Response:
    """Retry transient network failures (DNS blips, resets) and 429/5xx, with backoff."""
    for attempt in range(3):
        try:
            resp = await client.request(method, url, **kw)
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                return resp
        except httpx.TransportError:
            if attempt == 2:
                raise
        await asyncio.sleep(1.5 * 2**attempt)
    raise AssertionError("unreachable")


def _headers() -> dict[str, str]:
    return {"api-subscription-key": settings.sarvam_api_key}


def _estimate_pages(path: Path) -> int:
    if path.suffix.lower() != ".pdf":
        return 1
    # Count "/Type /Page" objects. Good enough for a budget pre-check, and avoids a PDF dependency.
    return max(1, len(re.findall(rb"/Type\s*/Page[^s]", path.read_bytes())))


async def parse_document(path: Path, *, invoice_id: int | None = None, language: str | None = None) -> str:
    """Digitise a PDF/image with Sarvam Vision and return its Markdown."""
    est_pages = _estimate_pages(path)
    if est_pages > 10:
        raise SarvamError(f"Document has {est_pages} pages; Sarvam Vision accepts at most 10.")
    usage.ensure_pages(est_pages)

    async with httpx.AsyncClient(base_url=settings.sarvam_base_url, headers=_headers(), timeout=60) as client:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        resp = await _send(
            client, "POST", "/doc-ai/v1/job/digitise",
            files={"file": (path.name, path.read_bytes(), mime)},
            data={"language": language or settings.doc_language, "output_format": "md"},
        )
        _raise_for(resp, "create digitise job")
        job_id = resp.json()["job_id"]

        waited = 0.0
        while True:
            st = await _send(client, "GET", f"/doc-ai/v1/job/{job_id}/status")
            _raise_for(st, "job status")
            body = st.json()
            status = str(body.get("status", "")).lower()
            if status in TERMINAL:
                break
            if waited >= settings.doc_poll_timeout_s:
                raise SarvamError(f"Document job {job_id} timed out (last status: {status})")
            await asyncio.sleep(settings.doc_poll_interval_s)
            waited += settings.doc_poll_interval_s

        pages = int((body.get("usage") or {}).get("pages_processed") or est_pages)
        usage.record("doc", "parse", invoice_id=invoice_id, pages=pages)

        if status not in {"completed", "partially_completed"}:
            raise SarvamError(f"Document job {job_id} ended with status '{status}': {body}")

        dl = await _send(client, "GET", f"/doc-ai/v1/job/{job_id}/download-url")
        _raise_for(dl, "download url")
        url = dl.json()["url"]

    async with httpx.AsyncClient(timeout=120) as raw:
        blob = await _send(raw, "GET", url)
        blob.raise_for_status()
    return _markdown_from_zip(blob.content)


def _markdown_from_zip(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        md_files = sorted(n for n in zf.namelist() if n.endswith(".md"))
        if not md_files:
            raise SarvamError(f"No markdown in digitise output: {zf.namelist()}")
        return "\n\n".join(zf.read(n).decode("utf-8") for n in md_files)


async def chat(
    messages: list[dict],
    *,
    purpose: str,
    invoice_id: int | None = None,
    json_schema: dict | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.1,
    reasoning_effort: str | None = "low",
) -> str:
    prompt_est = usage.estimate_tokens(json.dumps(messages, ensure_ascii=False)) + (
        usage.estimate_tokens(json.dumps(json_schema)) if json_schema else 0
    )
    usage.ensure_tokens(prompt_est + max_tokens)

    body: dict = {
        "model": settings.sarvam_chat_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
    }
    if json_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "invoice", "schema": json_schema, "strict": False},
        }
    async with httpx.AsyncClient(base_url=settings.sarvam_base_url, headers=_headers(), timeout=120) as client:
        resp = await _send(client, "POST", "/v1/chat/completions", json=body)
    _raise_for(resp, "chat completion")
    data = resp.json()

    u = data.get("usage") or {}
    usage.record(
        "chat",
        purpose,
        invoice_id=invoice_id,
        prompt_tokens=int(u.get("prompt_tokens") or prompt_est),
        completion_tokens=int(u.get("completion_tokens") or 0),
    )

    choice = data["choices"][0]
    content = choice["message"].get("content") or ""
    if choice.get("finish_reason") == "length":
        raise SarvamError(f"Sarvam response hit max_tokens={max_tokens} and was cut off; raise the cap for '{purpose}' if this repeats")
    return content


async def chat_json(messages: list[dict], json_schema: dict, **kw) -> dict:
    content = await chat(messages, json_schema=json_schema, **kw)
    return parse_json_loose(content)


def parse_json_loose(content: str) -> dict:
    """Parse JSON even if wrapped in ``` fences or preceded by stray text."""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    elif not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def _raise_for(resp: httpx.Response, what: str) -> None:
    if resp.status_code >= 400:
        raise SarvamError(f"Sarvam {what} failed [{resp.status_code}]: {resp.text[:500]}")
