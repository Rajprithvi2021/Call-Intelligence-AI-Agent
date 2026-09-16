"""API flow with a temporary local store and stubbed agents (no network)."""
import pytest
from fastapi.testclient import TestClient

from app import api, llm
from app.agents import analyst, reviewer
from app.store import LocalStore
from tests.conftest import SAMPLES
from tests.fakes import debt_draft, debt_verdicts

TEXT = (SAMPLES / "debt_collection_2026-07-01.txt").read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)
    monkeypatch.setattr(api, "get_store", lambda: store)
    monkeypatch.setattr(analyst, "run", lambda *a, **k: (debt_draft(), "stub-analyst"))
    monkeypatch.setattr(reviewer, "run", lambda *a, **k: (debt_verdicts(), "stub-judge"))
    monkeypatch.setattr(llm, "embed", lambda *a, **k: None)  # keyword-only search
    with TestClient(api.app) as c:
        yield c


def submit(client, **extra):
    data = {"meeting_date": "2026-07-01", "domain": "debt_collection", "transcript": TEXT} | extra
    r = client.post("/calls", data=data)
    assert r.status_code == 202
    return r.json()["id"]


def test_process_review_and_search(client):
    call_id = submit(client, title="Spec example")
    call = client.get(f"/calls/{call_id}").json()
    assert call["status"] == "done"
    assert [a["due_date"] for a in call["notes"]["action_items"]] == ["2026-08-15", "2026-07-03"]
    assert len(call["transcript"]) == 13

    queue = client.get("/review").json()
    assert queue and all(r["status"] == "open" for r in queue)
    first = queue[0]
    r = client.post(f"/review/{first['id']}", json={"status": "approved", "resolver": "qa", "note": "ok"})
    assert r.json()["status"] == "approved"
    assert len(client.get("/review").json()) == len(queue) - 1

    hits = client.get("/search", params={"q": "supervisor"}).json()
    assert hits["semantic"] is False
    assert any(h["line"] == 8 for h in hits["results"])
    assert client.get("/search", params={"flag": "cease_and_desist"}).json()["results"]
    assert not client.get("/search", params={"flag": "bankruptcy"}).json()["results"]


def test_failed_call_can_be_retried(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(analyst, "run", boom)
    call_id = submit(client)
    call = client.get(f"/calls/{call_id}").json()
    assert call["status"] == "failed" and "model exploded" in call["error"]

    monkeypatch.setattr(analyst, "run", lambda *a, **k: (debt_draft(), "stub-analyst"))
    assert client.post(f"/calls/{call_id}/retry").status_code == 202
    assert client.get(f"/calls/{call_id}").json()["status"] == "done"
    assert client.post(f"/calls/{call_id}/retry").status_code == 409  # only failed calls


def test_rejects_missing_or_double_input(client):
    assert client.post("/calls", data={"meeting_date": "2026-07-01"}).status_code == 422
    r = client.post("/calls", data={"meeting_date": "2026-07-01", "transcript": "A: hi"},
                    files={"file": ("x.txt", b"B: hello", "text/plain")})
    assert r.status_code == 422
    r = client.post("/calls", data={"meeting_date": "2026-07-01"}, files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415
    assert client.get("/calls/nope").status_code == 404
