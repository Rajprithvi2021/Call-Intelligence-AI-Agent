"""Reviewer agent (LLM-as-judge).

It sees only the transcript and the list of claims, not the Analyst's
reasoning, so it can't just agree with it.
"""
from app import llm, transcript
from app.agents.prompts import REVIEWER_SYSTEM
from app.config import settings
from app.schemas import CallNotes, ReviewerOutput, TranscriptLine


def _claims(notes: CallNotes) -> str:
    rows = []
    for d in notes.decisions:
        rows.append(f"{d.id} | decision | {d.text}")
    for a in notes.action_items:
        due = a.due_date_phrase or "none stated"
        rows.append(f"{a.id} | action item | {a.description} | owner: {a.owner or 'NONE'} | deadline words: {due}")
    for b in notes.blockers:
        rows.append(f"{b.id} | blocker | {b.text}")
    for n in notes.next_steps:
        rows.append(f"{n.id} | proposed next step | {n.text}")
    for c in notes.compliance:
        rows.append(f"{c.id} | compliance {c.rating} ({c.rule_id}) | {c.observation}")
    return "\n".join(rows)


def _cited(notes: CallNotes) -> dict[str, list[int]]:
    out = {}
    for attr in ("decisions", "action_items", "blockers", "next_steps", "compliance"):
        for item in getattr(notes, attr):
            out[item.id] = [e.line for e in item.evidence]
    return out


def run(notes: CallNotes, lines: list[TranscriptLine]) -> tuple[ReviewerOutput, str]:
    claims = _claims(notes) or "(no claims)"
    cited = "\n".join(f"{k}: lines {v}" for k, v in _cited(notes).items())
    prompt = f"""\
Meeting date: {notes.meeting_date.isoformat()} ({notes.meeting_date.strftime('%A')})
Domain: {notes.domain}

<transcript>
{transcript.render(lines)}
</transcript>

<claims>
id | type | claim
{claims}
</claims>

<cited_lines>
{cited}
</cited_lines>

Judge every claim and list any additional review items."""
    return llm.generate_structured(
        settings.judge_model, REVIEWER_SYSTEM, [prompt], ReviewerOutput, settings.judge_thinking,
    )
