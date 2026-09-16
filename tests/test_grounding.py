from app import grounding
from app.schemas import DraftCompliance
from tests.conftest import MEETING
from tests.fakes import debt_draft


def test_evidence_is_verbatim_and_invalid_lines_are_queued(debt_lines):
    notes = grounding.ground(debt_draft(), debt_lines, MEETING)
    by_n = {l.n: l.text for l in debt_lines}

    for item in notes.decisions + notes.action_items + notes.blockers + notes.next_steps + notes.compliance:
        for ev in item.evidence:
            assert ev.text == by_n[ev.line]

    # "Waive the remaining fees" cited line 99, which does not exist, so it is not asserted.
    assert [a.description for a in notes.action_items] == [
        "Consumer to pay second $700 installment",
        "Follow up on supervisor approval for the settlement split",
    ]
    ungrounded = [r for r in notes.review_items if r.category == "ungrounded"]
    assert len(ungrounded) == 1
    assert "Waive" in ungrounded[0].reason and ungrounded[0].item_ref == "A3"


def test_red_compliance_without_evidence_is_dropped(debt_lines):
    draft = debt_draft(compliance=[
        DraftCompliance(rule_id="DC-09", observation="Threatened arrest", rating="RED", lines=[], confidence=0.5),
        DraftCompliance(rule_id="DC-05", observation="No attorney involved", rating="GREEN", lines=[], confidence=0.9),
    ])
    notes = grounding.ground(draft, debt_lines, MEETING)
    assert [c.rule_id for c in notes.compliance] == ["DC-05"]
    assert any(r.item_ref == "C1" and r.category == "ungrounded" for r in notes.review_items)
