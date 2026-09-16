"""Analyst agent: transcript + knowledge base + rule hints -> draft notes."""
from datetime import date

from app import kb, llm, rules, transcript
from app.agents.prompts import ANALYST_SYSTEM
from app.config import settings
from app.schemas import AnalystDraft, TranscriptLine


def build_prompt(
    lines: list[TranscriptLine],
    meeting_date: date,
    domain: str | None,
    participants: str | None,
    hits: list[rules.RuleHit],
) -> str:
    return f"""\
Meeting date: {meeting_date.isoformat()} ({meeting_date.strftime('%A')})
Domain: {domain or "unknown - classify it"}
Participants (as provided): {participants or "not provided"}

<policies>
{kb.load_policy(domain)}
</policies>

<rule_hints>
{rules.describe(hits)}
</rule_hints>

<transcript>
{transcript.render(lines)}
</transcript>

Produce the call notes."""


def run(
    lines: list[TranscriptLine],
    meeting_date: date,
    domain: str | None,
    participants: str | None,
    hits: list[rules.RuleHit],
) -> tuple[AnalystDraft, str]:
    prompt = build_prompt(lines, meeting_date, domain, participants, hits)
    draft, model = llm.generate_structured(
        settings.analyst_model, ANALYST_SYSTEM, [prompt], AnalystDraft, settings.analyst_thinking,
    )
    if domain in kb.DOMAINS:
        draft.domain = domain  # the caller's choice wins over the model's classification
    return draft, model
