"""Run the real pipeline on the spec's debt-collection example N times and check the expected outputs.

    python scripts/eval_spec_example.py --runs 3

LLM output varies between runs, so this reports a pass rate per check instead of a single pass/fail.
"""
import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import pipeline  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "samples" / "debt_collection_2026-07-01.txt"


def cites(item, line):
    return line in [e.line for e in item.evidence]


CHECKS = {
    "customer pays 2nd $700 (James, 2026-08-15, line 8)": lambda n: any(
        a.owner and "james" in a.owner.lower() and a.due_date == date(2026, 8, 15) and cites(a, 8)
        for a in n.action_items),
    "agent follows up on approval (Marcus, 2026-07-03, line 8)": lambda n: any(
        a.owner and "marcus" in a.owner.lower() and a.due_date == date(2026, 7, 3) and cites(a, 8)
        for a in n.action_items),
    "blocker: supervisor approval (line 8)": lambda n: any(
        "approv" in b.text.lower() and cites(b, 8) for b in n.blockers),
    "review: settlement split needs sign-off": lambda n: any(
        any(w in r.reason.lower() for w in ("split", "settlement")) and
        any(w in r.reason.lower() for w in ("supervisor", "approv", "sign-off", "authority"))
        for r in n.review_items),
    "risk: don't call at work (line 9)": lambda n: any(
        f.type == "cease_and_desist" and cites(f, 9) for f in n.risk_flags),
    "no ungrounded evidence": lambda n: all(
        e.line in range(1, 14)
        for item in n.decisions + n.action_items + n.blockers + n.next_steps + n.compliance
        for e in item.evidence),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    passed = Counter()
    for i in range(1, args.runs + 1):
        result = pipeline.process_file(SAMPLE, date(2026, 7, 1), domain="debt_collection",
                                       participants="Marcus (agent), James Carter (consumer)")
        notes = result.notes
        print(f"\nrun {i} (models: {notes.models})")
        for name, check in CHECKS.items():
            ok = check(notes)
            passed[name] += ok
            print(f"  [{'x' if ok else ' '}] {name}")
    print("\npass rate:")
    for name in CHECKS:
        print(f"  {passed[name]}/{args.runs}  {name}")


if __name__ == "__main__":
    main()
