"""Thin wrapper around google-genai: structured generation, file upload, embeddings."""
import logging
import threading
import time
from pathlib import Path
from typing import TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


_client: genai.Client | None = None
_client_lock = threading.Lock()


def client() -> genai.Client:
    """Process-wide client. Created under a lock: a genai.Client that gets garbage-collected
    closes its HTTP connection, which breaks any request still using it."""
    global _client
    with _client_lock:
        if _client is None:
            if not settings.gemini_api_key:
                raise LLMError("GEMINI_API_KEY is not set (add it to .env)")
            _client = genai.Client(
                api_key=settings.gemini_api_key,
                # Retries and model fallback are handled here; the SDK's own backoff would stack on top.
                http_options=types.HttpOptions(timeout=300_000, retry_options=types.HttpRetryOptions(attempts=1)),
            )
        return _client


def is_daily_quota(exc: BaseException) -> bool:
    """429 caused by a per-day quota (e.g. free tier): waiting a few seconds won't help."""
    if not (isinstance(exc, errors.ClientError) and exc.code == 429):
        return False
    details = (getattr(exc, "details", None) or {}).get("error", {}).get("details", [])
    return any("PerDay" in v.get("quotaId", "") for d in details for v in d.get("violations", []))


def is_transient(exc: BaseException) -> bool:
    """Overload or rate limit: worth trying another model."""
    if isinstance(exc, errors.ServerError):
        return True
    return isinstance(exc, errors.ClientError) and exc.code == 429


def _worth_retrying(exc: BaseException) -> bool:
    """Worth retrying the same model after a pause."""
    return is_transient(exc) and not is_daily_quota(exc)


_retry = retry(
    retry=retry_if_exception(_worth_retrying),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)


@_retry
def _generate(model: str, contents, config: types.GenerateContentConfig):
    return client().models.generate_content(model=model, contents=contents, config=config)


def generate_structured(
    model: str,
    system: str,
    contents: list,
    schema: type[T],
    thinking_level: str | None = None,
) -> tuple[T, str]:
    """Generate JSON matching `schema`; returns (result, model that answered).

    If the model stays overloaded (5xx/429 after retries), the fallback models from
    LLM_FALLBACK_MODELS are tried in order.
    """
    candidates = [model] + [m for m in settings.fallback_models if m != model]
    for i, name in enumerate(candidates):
        try:
            return _generate_structured(name, system, contents, schema, thinking_level), name
        except errors.APIError as exc:
            if not is_transient(exc) or i == len(candidates) - 1:
                raise
            reason = "daily quota exhausted" if is_daily_quota(exc) else exc.code
            log.warning("%s unavailable (%s); falling back to %s", name, reason, candidates[i + 1])
    raise AssertionError("unreachable")


def _generate_structured(model, system, contents, schema: type[T], thinking_level) -> T:
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level) if thinking_level else None,
    )
    attempt_contents = list(contents)
    last_error = ""
    for attempt in range(2):
        started = time.monotonic()
        resp = _generate(model, attempt_contents, config)
        usage = resp.usage_metadata
        log.info("%s %s: %.1fs, tokens in=%s out=%s", model, schema.__name__, time.monotonic() - started,
                 getattr(usage, "prompt_token_count", "?"), getattr(usage, "candidates_token_count", "?"))
        if isinstance(resp.parsed, schema):
            return resp.parsed
        text = resp.text or ""
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            last_error = str(exc)[:2000]
            log.warning("invalid %s output (attempt %d): %s", schema.__name__, attempt + 1, last_error)
            attempt_contents = list(contents) + [
                f"Your previous answer did not match the required JSON schema:\n{last_error}\n"
                "Return the complete answer again as valid JSON only."
            ]
    raise LLMError(f"{model} returned invalid {schema.__name__}: {last_error}")


@_retry
def upload_file(path: Path, mime_type: str | None = None) -> types.File:
    cfg = types.UploadFileConfig(mime_type=mime_type) if mime_type else None
    f = client().files.upload(file=path, config=cfg)
    deadline = time.monotonic() + 300
    while f.state == types.FileState.PROCESSING:
        if time.monotonic() > deadline:
            raise LLMError("Timed out waiting for Gemini to process the uploaded file")
        time.sleep(2)
        f = client().files.get(name=f.name)
    if f.state == types.FileState.FAILED:
        raise LLMError(f"Gemini could not process {path.name}")
    return f


def delete_file(f: types.File) -> None:
    try:
        client().files.delete(name=f.name)
    except errors.APIError as exc:  # cleanup only
        log.warning("could not delete uploaded file %s: %s", f.name, exc)


def embed(texts: list[str], query: bool = False) -> list[list[float]] | None:
    """Embeddings, or None when disabled/unavailable (search then falls back to keywords)."""
    if not settings.embed_enabled or not texts:
        return None
    cfg = types.EmbedContentConfig(
        task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT",
        output_dimensionality=settings.embed_dim,
    )
    vectors: list[list[float]] = []
    try:
        for i in range(0, len(texts), 100):
            resp = _embed(texts[i:i + 100], cfg)
            vectors += [e.values for e in resp.embeddings]
    except (errors.APIError, LLMError) as exc:
        log.warning("embedding failed, falling back to keyword search: %s", exc)
        return None
    return vectors


@_retry
def _embed(batch: list[str], cfg: types.EmbedContentConfig):
    return client().models.embed_content(model=settings.embed_model, contents=batch, config=cfg)
