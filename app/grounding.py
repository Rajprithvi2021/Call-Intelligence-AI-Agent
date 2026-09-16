"""Turn the Analyst's draft into grounded notes.

The model only gives line numbers. Here we check they exist and copy the
verbatim transcript text, so quotes can never be paraphrased or invented.
A claim with no valid line is not asserted: it goes to the review queue.
"""
from datetime import date

from app import dates
from app.schemas import (
    ActionItem, AnalystDraft, CallNotes, ComplianceItem, DraftItem, Evidence,
    NoteItem, ReviewItem, RiskFlag, Sentiment, TranscriptLine,
)


class Grounder:
    def __init__(self, lines: list[TranscriptLine]):
        self.by_n = {l.n: l for l in lines}
        self.review: list[ReviewItem] = []

    def evidence(self, nums: list[int]) -> list[Evidence]:
        return [
            Evidence(line=n, speaker=self.by_n[n].speaker, text=self.by_n[n].text)
            for n in sorted(set(nums)) if n in self.by_n
        ]

    def check(self, item_id: str, kind: str, claim: str, nums: list[int]) -> list[Evidence] | None:
        """Return evidence, or queue the claim for review and return None if nothing is valid."""
        ev = self.evidence(nums)
        if ev:
            return ev
        cited = ", ".join(map(str, nums)) or "none"
        self.review.append(ReviewItem(
            item_ref=item_id,
            reason=f"Unverified {kind} not included in notes (cited lines: {cited}): {claim}",
            category="ungrounded",
            severity="medium",
            source="grounding",
        ))
        return None


def _note_items(g: Grounder, prefix: str, kind: str, items: list[DraftItem]) -> list[NoteItem]:
    out = []
    for i, it in enumerate(items, start=1):
        item_id = f"{prefix}{i}"
        ev = g.check(item_id, kind, it.text, it.lines)
        if ev is not None:
            out.append(NoteItem(id=item_id, text=it.text, evidence=ev, confidence=it.confidence))
    return out


def ground(draft: AnalystDraft, lines: list[TranscriptLine], meeting_date: date) -> CallNotes:
    g = Grounder(lines)

    actions = []
    for i, a in enumerate(draft.action_items, start=1):
        item_id = f"A{i}"
        ev = g.check(item_id, "action item", a.description, a.lines)
        if ev is None:
            continue
        due, status, note = dates.reconcile(a.due_date_phrase, a.due_date_guess, meeting_date)
        start, _ = dates.resolve(a.start_date_phrase, meeting_date)
        owner = a.owner.strip() or None
        actions.append(ActionItem(
            id=item_id, description=a.description, owner=owner, owner_role=a.owner_role,
            start_date=start, due_date=due, due_date_phrase=a.due_date_phrase,
            date_status=status, date_note=note, evidence=ev, confidence=a.confidence,
        ))

    compliance = []
    for i, c in enumerate(draft.compliance, start=1):
        item_id = f"C{i}"
        # A GREEN "nothing happened" observation may legitimately have no line; only RED/YELLOW need proof.
        ev = g.evidence(c.lines)
        if not ev and c.rating != "GREEN":
            g.check(item_id, f"{c.rating} compliance finding", c.observation, c.lines)
            continue
        compliance.append(ComplianceItem(
            id=item_id, rule_id=c.rule_id, observation=c.observation, rating=c.rating,
            evidence=ev, confidence=c.confidence,
        ))

    risks = []
    for i, r in enumerate(draft.risk_flags, start=1):
        item_id = f"R{i}"
        ev = g.check(item_id, f"{r.type} risk flag", r.description, r.lines)
        if ev is not None:
            risks.append(RiskFlag(id=item_id, type=r.type, description=r.description, source="llm", evidence=ev))

    s = draft.sentiment
    sentiment = Sentiment(
        overall=s.overall, customer_angry=s.customer_angry, profanity=s.profanity, evidence=g.evidence(s.lines),
    )

    analyst_reviews = [
        ReviewItem(item_ref=r.item_ref, reason=r.reason, category=r.category, severity=r.severity,
                   source="analyst", evidence=g.evidence(r.lines))
        for r in draft.review_items
    ]

    return CallNotes(
        meeting_date=meeting_date,
        tag=draft.tag,
        summary=draft.summary,
        domain=draft.domain,
        speaker_roles=draft.speaker_roles,
        decisions=_note_items(g, "D", "decision", draft.decisions),
        action_items=actions,
        blockers=_note_items(g, "B", "blocker", draft.blockers),
        next_steps=_note_items(g, "N", "next step", draft.next_steps),
        compliance=compliance,
        sentiment=sentiment,
        risk_flags=risks,
        review_items=analyst_reviews + g.review,
        overall_confidence=draft.overall_confidence,
    )
