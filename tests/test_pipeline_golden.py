"""The spec's debt-collection example end to end, with both agents stubbed."""
from datetime import date

from app import pipeline
from app.agents import analyst, reviewer
from tests.conftest import MEETING, SAMPLES
from tests.fakes import debt_draft, debt_verdicts


def test_debt_collection_golden(monkeypatch):
    monkeypatch.setattr(analyst, "run", lambda *a, **k: (debt_draft(), "stub-analyst"))
    monkeypatch.setattr(reviewer, "run", lambda *a, **k: (debt_verdicts(), "stub-judge"))

    result = pipeline.process_file(SAMPLES / "debt_collection_2026-07-01.txt", MEETING, domain="debt_collection")
    notes = result.notes
    cats = {r.category for r in notes.review_items}

    a1, a2 = notes.action_items
    assert (a1.description, a1.owner, a1.due_date, a1.date_status) == (
        "Consumer to pay second $700 installment", "James", date(2026, 8, 15), "resolved")
    assert (a2.owner, a2.due_date) == ("Marcus", date(2026, 7, 3))
    assert [e.line for e in a1.evidence] == [8] and [e.line for e in a2.evidence] == [8]
    assert a1.judgement.verdict == "supported"

    assert notes.blockers[0].text.startswith("Settlement split needs supervisor approval")
    assert [e.line for e in notes.blockers[0].evidence] == [8]

    reasons = " | ".join(r.reason for r in notes.review_items)
    assert "Settlement split is beyond standard terms" in reasons
    assert "Waive" in reasons                          # ungrounded claim held back
    assert notes.next_steps == []                      # the judge rejected it
    assert any(r.category == "pii" and r.source == "reviewer" for r in notes.review_items)
    assert {"risk_pii", "risk_cease_and_desist"} <= cats  # DOB/card rule hits, "don't call me at work"
    assert "risk_consent_unclear" not in cats          # disclosure is on line 1

    assert {l.speaker: l.role for l in result.transcript} == {"Agent": "agent", "Consumer": "customer"}
