"""HTTP API.

    uvicorn app.api:app --reload
"""
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from google.genai import errors
from pydantic import BaseModel

from app import llm, pipeline
from app.config import settings
from app.store import get_store

log = logging.getLogger("app.api")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
JOB_RETRY_PAUSES = [20, 60]  # seconds between whole-job retries when every model is overloaded
_job_slots = threading.BoundedSemaphore(settings.job_concurrency)
DomainParam = Literal["debt_collection", "sales", "support", "standup"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    store = get_store()  # connects and creates tables when DATABASE_URL is set
    log.info("store: %s", store.kind)
    # Background jobs don't survive a restart; surface them as retryable failures.
    for call in store.list_calls():
        if call["status"] not in ("done", "failed"):
            store.set_status(call["id"], "failed", "Interrupted: the server restarted while this call was processing. Retry it.")
    yield


app = FastAPI(title="Call Intelligence API", version="0.1.0", lifespan=lifespan)


def _process(call_id: str, source: str, payload: str, meeting_date: date,
             domain: str | None, participants: str | None) -> None:
    # Jobs wait here (status stays "queued") so a rate-limited key isn't hit by several calls at once.
    with _job_slots:
        _process_now(call_id, source, payload, meeting_date, domain, participants)


def _process_now(call_id: str, source: str, payload: str, meeting_date: date,
                 domain: str | None, participants: str | None) -> None:
    store = get_store()

    def status(s: str) -> None:
        store.set_status(call_id, s)

    try:
        kw = dict(domain=domain, participants=participants, on_status=status)
        for attempt, pause in enumerate(JOB_RETRY_PAUSES + [None], start=1):
            try:
                if source == "audio":
                    result = pipeline.process_audio(Path(payload), meeting_date, **kw)
                else:
                    result = pipeline.process_text(payload, meeting_date, **kw)
                break
            except errors.APIError as exc:
                if pause is None or not llm.is_transient(exc) or llm.is_daily_quota(exc):
                    raise
                log.warning("call %s: models overloaded (attempt %d), retrying in %ds", call_id, attempt, pause)
                status(f"waiting to retry ({exc.code})")
                time.sleep(pause)
        status("indexing")
        vectors = llm.embed([f"{l.speaker}: {l.text}" for l in result.transcript])
        store.save_result(call_id, result, vectors)
        status("done")
    except Exception as exc:  # the job must always end in a visible state
        log.exception("processing call %s failed", call_id)
        store.set_status(call_id, "failed", f"{type(exc).__name__}: {exc}"[:1000])


@app.get("/health")
def health():
    return {
        "status": "ok",
        "store": get_store().kind,
        "transcription": f"{settings.transcription_provider}:{settings.transcription_model}",
        "analyst_model": settings.analyst_model,
        "judge_model": settings.judge_model,
        "fallback_models": list(settings.fallback_models),
        "embeddings": settings.embed_model if settings.embed_enabled else "disabled",
    }


@app.post("/calls", status_code=202)
async def create_call(
    background: BackgroundTasks,
    meeting_date: date = Form(...),
    title: str = Form(""),
    domain: DomainParam | None = Form(None),
    participants: str | None = Form(None),
    transcript: str | None = Form(None),
    file: UploadFile | None = File(None),
):
    """Submit a recording (audio file) or a transcript (text field or .txt file)."""
    has_text = bool(transcript and transcript.strip())
    if has_text == bool(file and file.filename):
        raise HTTPException(422, "Provide either an audio/.txt file or transcript text, not both.")

    if file and file.filename:
        ext = Path(file.filename).suffix.lower()
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File too large (limit 200 MB).")
        if ext in (".txt", ".md"):
            source, payload = "text", data.decode("utf-8", errors="replace")
        elif ext in pipeline.AUDIO_EXTS:
            settings.upload_dir.mkdir(parents=True, exist_ok=True)
            dest = settings.upload_dir / f"{uuid.uuid4().hex}{ext}"
            dest.write_bytes(data)
            source, payload = "audio", str(dest)
        else:
            raise HTTPException(415, f"Unsupported file type {ext!r}.")
        title = title or Path(file.filename).stem
    else:
        source, payload = "text", transcript
        title = title or f"Call {meeting_date.isoformat()}"

    call_id = get_store().create_call(title, domain, meeting_date, source, participants, payload)
    background.add_task(_process, call_id, source, payload, meeting_date, domain, participants)
    return {"id": call_id, "status": "queued"}


@app.get("/calls")
def list_calls():
    return get_store().list_calls()


@app.get("/calls/{call_id}")
def get_call(call_id: str):
    call = get_store().get_call(call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    return call


@app.post("/calls/{call_id}/retry", status_code=202)
def retry_call(call_id: str, background: BackgroundTasks):
    """Re-run a failed call from its stored input."""
    store = get_store()
    call = store.get_input(call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    if call["status"] != "failed":
        raise HTTPException(409, f"Only failed calls can be retried (status is {call['status']}).")
    if not call.get("input"):
        raise HTTPException(409, "The original input for this call was not stored.")
    store.set_status(call_id, "queued")
    meeting_date = call["meeting_date"]
    if isinstance(meeting_date, str):
        meeting_date = date.fromisoformat(meeting_date)
    background.add_task(_process, call_id, call["source"], call["input"], meeting_date,
                        call.get("domain"), call.get("participants"))
    return {"id": call_id, "status": "queued"}


@app.get("/review")
def list_reviews(status: Literal["open", "approved", "rejected", "edited"] | None = "open", call_id: str | None = None):
    return get_store().list_reviews(status=status, call_id=call_id)


class ReviewUpdate(BaseModel):
    status: Literal["approved", "rejected", "edited"]
    resolver: str | None = None
    note: str | None = None


@app.post("/review/{review_id}")
def resolve_review(review_id: str, body: ReviewUpdate):
    item = get_store().resolve_review(review_id, body.status, body.resolver, body.note)
    if not item:
        raise HTTPException(404, "Review item not found")
    return item


@app.get("/search")
def search(
    q: str = "",
    domain: DomainParam | None = None,
    flag: str | None = None,
    sentiment: Literal["positive", "neutral", "negative"] | None = None,
    limit: int = 20,
):
    qvec = None
    if q.strip():
        vecs = llm.embed([q], query=True)
        qvec = vecs[0] if vecs else None
    results = get_store().search(q, qvec, domain, flag, sentiment, min(max(limit, 1), 100))
    return {"query": q, "semantic": qvec is not None, "results": results}
