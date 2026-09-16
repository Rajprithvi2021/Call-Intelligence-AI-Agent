"""Deterministic escalation policy.

Applies the judge's verdicts, merges rule hits, and decides what a human must
look at. The judge can add review items, but it can never remove a
rule-based or policy-based escalation.
"""
import re

from app.config import settings
from app.rules import CUSTOMER_ONLY, RISK_TYPES, RuleHit
from app.schemas import (
    CallNotes, Evidence, Judgement, JudgeVerdict, ReviewItem, RiskFlag, TranscriptLine,
)

CUSTOMER_FACING = {"debt_collection", "sales", "support"}
VAGUE_OWNERS = {"", "unknown", "unclear", "someone", "somebody", "team", "the team", "we", "us", "they", "tbd", "n/a"}
AUTHORITY = re.compile(
    r"\b(approv\w*|supervisor|manager|sign[- ]?off|waiv\w*|exception|discount|refund|settlement|"
    r"credit|write[- ]?off|escalat\w*|legal review|payment plan|split)\b",
    re.IGNORECASE,
)
RISK_SEVERITY = {
    "cease_and_desist": "high", "legal": "high", "bankruptcy": "high", "wrong_number": "high",
    "consent_refused": "high", "consent_unclear": "medium", "pii": "medium", "other": "medium",
}
RISK_REASON = {
    "cease_and_desist": "Customer asked to stop contact. Confirm and update contact preferences before any further outreach.",
    "legal": "Legal threat or attorney mention. Route to legal/compliance; confirm whether contact must go through counsel.",
    "bankruptcy": "Bankruptcy mentioned. Collection activity may need to pause; verify status.",
    "wrong_number": "Possible wrong party. Verify identity and stop disclosing account details.",
    "consent_refused": "Customer objected to recording.",
    "consent_unclear": "Recording consent is unclear.",
    "pii": "Sensitive personal or financial data was spoken. Check handling and redaction.",
    "other": "Risk flagged by the analyst.",
}


def _add(items: list[ReviewItem], item: ReviewItem) -> None:
    key = (item.item_ref, item.category)
    if not any((r.item_ref, r.category) == key for r in items):
        items.append(item)


def _evidence(lines_by_n: dict[int, TranscriptLine], nums: list[int]) -> list[Evidence]:
    return [Evidence(line=n, speaker=lines_by_n[n].speaker, text=lines_by_n[n].text)
            for n in sorted(set(nums)) if n in lines_by_n]


def apply_verdicts(notes: CallNotes, verdicts: list[JudgeVerdict]) -> None:
    """Attach judgements. Unsupported items are removed from the notes and queued instead."""
    by_id = {v.item_id: v for v in verdicts}
    for attr in ("decisions", "action_items", "blockers", "next_steps", "compliance"):
        kept = []
        for item in getattr(notes, attr):
            v = by_id.get(item.id)
            if v:
                item.judgement = Judgement(verdict=v.verdict, confidence=v.confidence, reason=v.reason)
            if v and v.verdict == "unsupported":
                text = getattr(item, "text", None) or getattr(item, "description", None) or item.observation
                notes.review_items.append(ReviewItem(
                    item_ref=item.id, reason=f"Reviewer found no support; removed from notes: {text}. {v.reason}",
                    category="unsupported_by_reviewer", severity="medium", source="reviewer", evidence=item.evidence,
                ))
                continue
            kept.append(item)
        setattr(notes, attr, kept)


def merge_rule_hits(notes: CallNotes, hits: list[RuleHit], lines: list[TranscriptLine]) -> list[RuleHit]:
    """Fold rule hits into risk flags and sentiment. Returns the hits that were kept."""
    by_n = {l.n: l for l in lines}
    kept = [
        h for h in hits
        if not (h.type in CUSTOMER_ONLY and by_n[h.line].role == "agent")
    ]

    for kind in sorted({h.type for h in kept} & RISK_TYPES):
        nums = [h.line for h in kept if h.type == kind]
        existing = next((f for f in notes.risk_flags if f.type == kind), None)
        if existing:
            existing.source = "rule+llm"
            have = {e.line for e in existing.evidence}
            existing.evidence += [e for e in _evidence(by_n, nums) if e.line not in have]
            existing.evidence.sort(key=lambda e: e.line)
        else:
            matches = sorted({h.match for h in kept if h.type == kind})
            notes.risk_flags.append(RiskFlag(
                id=f"R{len(notes.risk_flags) + 1}", type=kind,
                description=f"Detected by rule: {', '.join(matches)}",
                source="rule", evidence=_evidence(by_n, nums),
            ))

    s = notes.sentiment
    have = {e.line for e in s.evidence}
    for kind in ("profanity", "anger"):
        nums = [h.line for h in kept if h.type == kind]
        if not nums:
            continue
        if kind == "profanity":
            s.profanity = True
        else:
            s.customer_angry = True
            if s.overall == "positive":
                s.overall = "neutral"
        s.evidence += [e for e in _evidence(by_n, nums) if e.line not in have]
        have |= set(nums)
    s.evidence.sort(key=lambda e: e.line)
    return kept


def escalate(notes: CallNotes, hits: list[RuleHit], lines: list[TranscriptLine]) -> None:
    """Add the policy-driven review items to notes.review_items (deduplicated)."""
    items = notes.review_items
    threshold = settings.review_threshold

    for a in notes.action_items:
        if (a.owner or "").strip().lower() in VAGUE_OWNERS:
            _add(items, ReviewItem(item_ref=a.id, reason=f"No clear owner for: {a.description}",
                                   category="missing_owner", severity="medium", source="escalation", evidence=a.evidence))
        if a.date_status == "vague":
            _add(items, ReviewItem(item_ref=a.id, reason=f"Deadline is vague ({a.date_note}): {a.description}",
                                   category="vague_deadline", severity="low", source="escalation", evidence=a.evidence))
        elif a.date_note:
            _add(items, ReviewItem(item_ref=a.id, reason=f"Check the due date: {a.date_note}",
                                   category="date_check", severity="low", source="escalation", evidence=a.evidence))

    for attr in ("decisions", "action_items", "blockers", "next_steps", "compliance"):
        for item in getattr(notes, attr):
            text = getattr(item, "text", None) or getattr(item, "description", None) or item.observation
            j = item.judgement
            if item.confidence < threshold or (j and j.confidence < threshold):
                _add(items, ReviewItem(item_ref=item.id, reason=f"Low confidence: {text}",
                                       category="low_confidence", severity="low", source="escalation", evidence=item.evidence))
            if j and j.verdict == "needs_human":
                _add(items, ReviewItem(item_ref=item.id, reason=f"Reviewer asks for a human check: {j.reason}",
                                       category="reviewer_needs_human", severity="medium", source="reviewer", evidence=item.evidence))
            if attr in ("decisions", "action_items", "blockers") and AUTHORITY.search(text):
                _add(items, ReviewItem(item_ref=item.id, reason=f"May need authority or approval beyond the agent: {text}",
                                       category="authority", severity="medium", source="escalation", evidence=item.evidence))

    for c in notes.compliance:
        if c.rating == "RED":
            _add(items, ReviewItem(item_ref=c.id, reason=f"RED compliance finding ({c.rule_id}): {c.observation}",
                                   category="compliance_red", severity="high", source="escalation", evidence=c.evidence))

    for f in notes.risk_flags:
        _add(items, ReviewItem(item_ref=f.id, reason=RISK_REASON.get(f.type, f.description),
                               category=f"risk_{f.type}", severity=RISK_SEVERITY.get(f.type, "medium"),
                               source="rule" if f.source == "rule" else "escalation", evidence=f.evidence))

    if notes.domain in CUSTOMER_FACING and not any(h.type == "recording_disclosure" for h in hits):
        _add(items, ReviewItem(item_ref="call", reason="No recording disclosure found; recording consent is unclear.",
                               category="risk_consent_unclear", severity="medium", source="rule"))

    if notes.sentiment.customer_angry or notes.sentiment.profanity:
        _add(items, ReviewItem(item_ref="call", reason="Customer anger or profanity detected; check for coaching and follow-up.",
                               category="sentiment", severity="low", source="rule", evidence=notes.sentiment.evidence))

    if notes.overall_confidence < threshold:
        _add(items, ReviewItem(item_ref="call", reason="Analyst's overall confidence in these notes is low.",
                               category="low_confidence", severity="medium", source="escalation"))

    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda r: order[r.severity])
