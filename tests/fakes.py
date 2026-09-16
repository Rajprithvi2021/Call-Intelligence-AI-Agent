"""Hand-written agent outputs for the spec's debt-collection example (no API calls)."""
from app.schemas import (
    AnalystDraft, DraftActionItem, DraftCompliance, DraftItem, DraftReview, DraftRisk,
    DraftSentiment, JudgeVerdict, ReviewerOutput, SpeakerRole,
)


def debt_draft(**overrides) -> AnalystDraft:
    data = dict(
        tag="Settlement split request",
        summary="James asked to split a $1,400 settlement into two $700 payments. "
                "Marcus took the first payment and needs supervisor approval for the split.",
        domain="debt_collection",
        speaker_roles=[SpeakerRole(speaker="Agent", name="Marcus", role="agent"),
                       SpeakerRole(speaker="Consumer", name="James", role="customer")],
        decisions=[DraftItem(text="First $700 payment taken today", lines=[12], confidence=0.9)],
        action_items=[
            DraftActionItem(description="Consumer to pay second $700 installment", owner="James",
                            owner_role="customer", start_date_phrase="",
                            due_date_phrase="on the 15th of next month", due_date_guess="2026-08-15",
                            lines=[8], confidence=0.85),
            DraftActionItem(description="Follow up on supervisor approval for the settlement split",
                            owner="Marcus", owner_role="agent", start_date_phrase="",
                            due_date_phrase="by Friday", due_date_guess="2026-07-03", lines=[8], confidence=0.9),
            DraftActionItem(description="Waive the remaining fees", owner="Marcus", owner_role="agent",
                            start_date_phrase="", due_date_phrase="", due_date_guess="", lines=[99],
                            confidence=0.6),
        ],
        blockers=[DraftItem(text="Settlement split needs supervisor approval before it is final",
                            lines=[8], confidence=0.9)],
        next_steps=[DraftItem(text="Update contact preferences to cell phone only", lines=[9, 10], confidence=0.8)],
        compliance=[
            DraftCompliance(rule_id="DC-02", observation="Mini-Miranda given", rating="GREEN",
                            lines=[3], confidence=0.95),
            DraftCompliance(rule_id="DC-08", observation="Split settlement offered before approval",
                            rating="YELLOW", lines=[8], confidence=0.8),
        ],
        sentiment=DraftSentiment(overall="neutral", customer_angry=False, profanity=False, lines=[7]),
        risk_flags=[DraftRisk(type="cease_and_desist", description="Asked not to be called at work",
                              lines=[9], confidence=0.8)],
        review_items=[DraftReview(item_ref="B1",
                                  reason="Settlement split is beyond standard terms and needs a supervisor's sign-off",
                                  category="authority", severity="medium", lines=[8])],
        overall_confidence=0.85,
    )
    data.update(overrides)
    return AnalystDraft(**data)


def debt_verdicts() -> ReviewerOutput:
    def v(item_id, verdict, reason, confidence=0.9):
        return JudgeVerdict(item_id=item_id, verdict=verdict, confidence=confidence, reason=reason)

    return ReviewerOutput(
        verdicts=[
            v("D1", "supported", "Line 12."),
            v("A1", "supported", "Line 8."),
            v("A2", "supported", "Line 8."),
            v("B1", "supported", "Line 8."),
            v("N1", "unsupported", "Not agreed.", 0.8),
            v("C1", "supported", "Line 3."),
            v("C2", "needs_human", "Supervisor must decide.", 0.7),
        ],
        additional_review_items=[
            DraftReview(item_ref="call", reason="Card details spoken on the call", category="pii",
                        severity="medium", lines=[11]),
        ],
    )
