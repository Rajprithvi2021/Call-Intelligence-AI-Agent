"""Persistence behind one interface.

PostgresStore (app/db.py) is the real backend. LocalStore keeps JSON files on
disk so the app runs before a database is set up; it is not meant for production.
"""
import json
import math
import re
import threading
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import settings
from app.schemas import ProcessedCall

RRF_K = 60


class Store(Protocol):
    kind: str
    def create_call(self, title: str, domain: str | None, meeting_date: date, source: str,
                    participants: str | None, input_ref: str) -> str: ...
    def get_input(self, call_id: str) -> dict | None: ...
    def set_status(self, call_id: str, status: str, error: str | None = None) -> None: ...
    def save_result(self, call_id: str, result: ProcessedCall, embeddings: list[list[float]] | None) -> None: ...
    def list_calls(self) -> list[dict]: ...
    def get_call(self, call_id: str) -> dict | None: ...
    def list_reviews(self, status: str | None = None, call_id: str | None = None) -> list[dict]: ...
    def resolve_review(self, review_id: str, status: str, resolver: str | None, note: str | None) -> dict | None: ...
    def search(self, q: str, qvec: list[float] | None, domain: str | None, flag: str | None,
               sentiment: str | None, limit: int = 20) -> list[dict]: ...


def rrf_merge(*rankings: list[str]) -> dict[str, float]:
    """Reciprocal rank fusion of several ranked id lists."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    return scores


_WORD = re.compile(r"[a-z0-9']+")


_SUFFIXES = ("ing", "ed", "es", "s", "ly")
_STOPWORDS = set("""
the and for are but not you your yours with this that these those was were who whom what when where which
why how all any can could would should will just have has had his her him she they them their there here
from into out our ours about been being did does doing don't i'm it's its than then too very some such
only own same also again once over under more most other each few both nor off yes okay
""".split())


def _stems(text: str) -> set[str]:
    """Lowercase content words with common suffixes stripped ("calling" -> "call")."""
    out = set()
    for w in _WORD.findall(text.lower()):
        if (len(w) < 3 and not w.isdigit()) or w in _STOPWORDS:
            continue
        for suf in _SUFFIXES:
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)]
                break
        out.add(w)
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class LocalStore:
    kind = "local"

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def _path(self, call_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{8}", call_id):
            raise KeyError(call_id)
        return self.root / f"{call_id}.json"

    def _load(self, call_id: str) -> dict | None:
        try:
            p = self._path(call_id)
        except KeyError:
            return None
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _save(self, doc: dict) -> None:
        tmp = self._path(doc["call"]["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, default=str), encoding="utf-8")
        tmp.replace(self._path(doc["call"]["id"]))

    def _all(self) -> list[dict]:
        docs = [json.loads(p.read_text(encoding="utf-8")) for p in self.root.glob("*.json")]
        return sorted(docs, key=lambda d: d["call"]["created_at"], reverse=True)

    def create_call(self, title, domain, meeting_date, source, participants, input_ref):
        call_id = uuid.uuid4().hex[:8]
        doc = {"call": {
            "id": call_id, "title": title, "domain": domain, "meeting_date": meeting_date.isoformat(),
            "participants": participants, "source": source, "status": "queued", "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, "input": input_ref, "notes": None, "transcript": [], "embeddings": None, "reviews": []}
        with self.lock:
            self._save(doc)
        return call_id

    def get_input(self, call_id):
        doc = self._load(call_id)
        return {**doc["call"], "input": doc.get("input")} if doc else None

    def set_status(self, call_id, status, error=None):
        with self.lock:
            doc = self._load(call_id)
            doc["call"].update(status=status, error=error)
            self._save(doc)

    def save_result(self, call_id, result, embeddings):
        notes = result.notes.model_dump(mode="json")
        with self.lock:
            doc = self._load(call_id)
            doc["call"]["domain"] = notes["domain"]
            doc["notes"] = notes
            doc["transcript"] = [l.model_dump() for l in result.transcript]
            doc["embeddings"] = embeddings
            doc["reviews"] = [
                {**r, "id": f"{call_id}-{i}", "call_id": call_id}
                for i, r in enumerate(notes["review_items"], start=1)
            ]
            self._save(doc)

    def _summary(self, doc: dict) -> dict:
        notes = doc["notes"] or {}
        return {
            **doc["call"],
            "tag": notes.get("tag"),
            "sentiment": (notes.get("sentiment") or {}).get("overall"),
            "open_reviews": sum(r["status"] == "open" for r in doc["reviews"]),
        }

    def list_calls(self):
        return [self._summary(d) for d in self._all()]

    def get_call(self, call_id):
        doc = self._load(call_id)
        if not doc:
            return None
        return {**self._summary(doc), "notes": doc["notes"], "transcript": doc["transcript"], "reviews": doc["reviews"]}

    def list_reviews(self, status=None, call_id=None):
        out = []
        for doc in self._all():
            if call_id and doc["call"]["id"] != call_id:
                continue
            for r in doc["reviews"]:
                if status is None or r["status"] == status:
                    out.append({**r, "call_title": doc["call"]["title"], "meeting_date": doc["call"]["meeting_date"]})
        return out

    def resolve_review(self, review_id, status, resolver, note):
        call_id = review_id.split("-")[0]
        with self.lock:
            doc = self._load(call_id)
            if not doc:
                return None
            for r in doc["reviews"]:
                if r["id"] == review_id:
                    r.update(status=status, resolver=resolver, resolution_note=note,
                             resolved_at=datetime.now(timezone.utc).isoformat())
                    self._save(doc)
                    return r
        return None

    def search(self, q, qvec, domain, flag, sentiment, limit=20):
        docs = [d for d in self._all() if d["notes"]]
        if domain:
            docs = [d for d in docs if d["notes"]["domain"] == domain]
        if flag:
            docs = [d for d in docs if any(f["type"] == flag for f in d["notes"]["risk_flags"])]
        if sentiment:
            docs = [d for d in docs if d["notes"]["sentiment"]["overall"] == sentiment]

        if not q.strip():
            return [{"call_id": d["call"]["id"], "title": d["call"]["title"], "tag": d["notes"]["tag"],
                     "line": None, "speaker": None, "text": d["notes"]["summary"], "score": 0.0} for d in docs[:limit]]

        rows: dict[str, dict] = {}
        keyword: list[tuple[float, str]] = []
        semantic: list[tuple[float, str]] = []
        q_stems = _stems(q)
        for d in docs:
            vecs = d.get("embeddings") or []
            for i, line in enumerate(d["transcript"]):
                key = f"{d['call']['id']}:{line['n']}"
                rows[key] = {"call_id": d["call"]["id"], "title": d["call"]["title"], "tag": d["notes"]["tag"],
                             "line": line["n"], "speaker": line["speaker"], "text": line["text"]}
                hit = len(q_stems & _stems(line["text"]))
                if hit:
                    keyword.append((hit / len(q_stems), key))
                if qvec and i < len(vecs):
                    sim = _cosine(qvec, vecs[i])
                    if 1 - sim <= settings.search_max_distance:
                        semantic.append((sim, key))
        ranked = [
            [k for _, k in sorted(keyword, reverse=True)[:50]],
            [k for _, k in sorted(semantic, reverse=True)[:settings.search_semantic_top_k]],
        ]
        scores = rrf_merge(*ranked)
        best = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return [{**rows[k], "score": round(s, 4)} for k, s in best]


@lru_cache(maxsize=1)
def get_store() -> Store:
    if settings.database_url:
        from app.db import PostgresStore
        return PostgresStore(settings.database_url)
    return LocalStore(settings.local_store_dir)
