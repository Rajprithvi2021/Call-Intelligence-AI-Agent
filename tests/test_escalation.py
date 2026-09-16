from app import escalation, grounding, rules, transcript
from app.schemas import DraftActionItem, DraftCompliance, JudgeVerdict, TranscriptLine
from tests.conftest import MEETING
from tests.fakes import debt_draft

EMPTY = dict(action_items=[], decisions=[], blockers=[], next_steps=[], compliance=[], risk_flags=[], review_items=[])


def run(lines, draft, verdicts=()):
    transcript.apply_roles(lines, draft.speaker_roles)
    notes = grounding.ground(draft, lines, MEETING)
    escalation.apply_verdicts(notes, list(verdicts))
    hits = escalation.merge_rule_hits(notes, rules.scan(lines), lines)
    escalation.escalate(notes, hits, lines)
    return notes


def cats(notes, ref=None):
    return {r.category for r in notes.review_items if ref is None or r.item_ref == ref}


def action(**kw):
    base = dict(description="Send the report", owner="Kevin", owner_role="participant", start_date_phrase="",
                due_date_phrase="by Friday", due_date_guess="", lines=[1], confidence=0.9)
    return DraftActionItem(**(base | kw))


def test_missing_owner_and_vague_deadline(debt_lines):
    notes = run(debt_lines, debt_draft(action_items=[action(owner=""), action(due_date_phrase="soon")]))
    assert "missing_owner" in cats(notes, "A1")
    assert "vague_deadline" in cats(notes, "A2")


def test_low_confidence(debt_lines):
    notes = run(debt_lines, debt_draft(action_items=[action(confidence=0.4)]))
    assert "low_confidence" in cats(notes, "A1")


def test_judge_unsupported_removes_item_and_needs_human_escalates(debt_lines):
    verdicts = [JudgeVerdict(item_id="A1", verdict="unsupported", confidence=0.9, reason="never agreed"),
                JudgeVerdict(item_id="A2", verdict="needs_human", confidence=0.8, reason="needs supervisor")]
    notes = run(debt_lines, debt_draft(), verdicts)
    assert [a.id for a in notes.action_items] == ["A2"]
    assert "unsupported_by_reviewer" in cats(notes, "A1")
    assert "reviewer_needs_human" in cats(notes, "A2")


def test_red_compliance(debt_lines):
    draft = debt_draft(compliance=[
        DraftCompliance(rule_id="DC-08", observation="Unapproved split", rating="RED", lines=[8], confidence=0.9)])
    notes = run(debt_lines, draft)
    assert "compliance_red" in cats(notes, "C1")
    assert notes.review_items[0].severity == "high"


def test_authority_trigger(debt_lines):
    notes = run(debt_lines, debt_draft())
    assert "authority" in cats(notes, "B1")


def test_rule_hits_become_risk_flags_and_consent_check():
    lines = [
        TranscriptLine(n=1, speaker="Agent", text="Hi, calling about your account."),
        TranscriptLine(n=2, speaker="Consumer",
                       text="I told you guys not to call. Contact my attorney, this is bullshit."),
    ]
    draft = debt_draft(**EMPTY)
    draft.sentiment.lines = []
    notes = run(lines, draft)
    flags = {f.type: f for f in notes.risk_flags}
    assert set(flags) == {"cease_and_desist", "legal"}
    assert flags["legal"].source == "rule" and flags["legal"].evidence[0].line == 2
    assert notes.sentiment.profanity
    assert {"risk_cease_and_desist", "risk_legal", "risk_consent_unclear", "sentiment"} <= cats(notes)


def test_agent_saying_stop_calling_is_not_a_flag():
    lines = [
        TranscriptLine(n=1, speaker="Agent", text="This call is recorded. If you want us to stop calling, just say so."),
        TranscriptLine(n=2, speaker="Consumer", text="No, that is fine."),
    ]
    draft = debt_draft(**EMPTY)
    draft.sentiment.lines = []
    notes = run(lines, draft)
    assert notes.risk_flags == []
    assert "risk_consent_unclear" not in cats(notes)
