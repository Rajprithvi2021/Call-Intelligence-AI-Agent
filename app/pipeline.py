"""End-to-end processing of one call.

    audio -> transcribe -> numbered lines -> rule pre-scan -> Analyst -> grounding
          -> Reviewer (judge) -> escalation -> ProcessedCall

Run from the command line:
    python -m app.pipeline data/samples/debt_collection_2026-07-01.txt --date 2026-07-01
"""
import argparse
import logging
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

from app import escalation, grounding, rules, stt, transcript
from app.agents import analyst, reviewer
from app.schemas import ProcessedCall, ReviewItem, TranscriptLine

log = logging.getLogger(__name__)
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".webm", ".aiff"}
StatusFn = Callable[[str], None]


def process_lines(
    lines: list[TranscriptLine],
    meeting_date: date,
    domain: str | None = None,
    participants: str | None = None,
    use_judge: bool = True,
    on_status: StatusFn = lambda s: None,
) -> ProcessedCall:
    if not lines:
        raise ValueError("Transcript is empty")

    hits = rules.scan(lines)

    on_status("analyzing")
    draft, analyst_model = analyst.run(lines, meeting_date, domain, participants, hits)
    models = {"analyst": analyst_model, "judge": "off"}
    transcript.apply_roles(lines, draft.speaker_roles)
    notes = grounding.ground(draft, lines, meeting_date)

    if use_judge:
        on_status("reviewing")
        verdict, models["judge"] = reviewer.run(notes, lines)
        escalation.apply_verdicts(notes, verdict.verdicts)
        g = grounding.Grounder(lines)
        notes.review_items += [
            ReviewItem(item_ref=r.item_ref, reason=r.reason, category=r.category, severity=r.severity,
                       source="reviewer", evidence=g.evidence(r.lines))
            for r in verdict.additional_review_items
        ]

    kept_hits = escalation.merge_rule_hits(notes, hits, lines)
    escalation.escalate(notes, kept_hits, lines)
    notes.models = models
    return ProcessedCall(notes=notes, transcript=lines)


def process_text(text: str, meeting_date: date, **kw) -> ProcessedCall:
    return process_lines(transcript.parse_text(text), meeting_date, **kw)


def process_audio(path: Path, meeting_date: date, on_status: StatusFn = lambda s: None, **kw) -> ProcessedCall:
    on_status("transcribing")
    segments = stt.get_transcriber().transcribe(path)
    return process_lines(transcript.from_segments(segments), meeting_date, on_status=on_status, **kw)


def process_file(path: Path, meeting_date: date, **kw) -> ProcessedCall:
    if path.suffix.lower() in AUDIO_EXTS:
        return process_audio(path, meeting_date, **kw)
    return process_text(path.read_text(encoding="utf-8"), meeting_date, **kw)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Process one call transcript or recording.")
    ap.add_argument("file", type=Path)
    ap.add_argument("--date", required=True, type=date.fromisoformat, help="meeting date, YYYY-MM-DD")
    ap.add_argument("--domain", choices=["debt_collection", "sales", "support", "standup"])
    ap.add_argument("--participants", help='e.g. "Marcus (agent), James (consumer)"')
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--out", type=Path, help="write JSON here instead of stdout")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    result = process_file(
        args.file, args.date, domain=args.domain, participants=args.participants,
        use_judge=not args.no_judge, on_status=lambda s: log.info("status: %s", s),
    )
    payload = result.model_dump_json(indent=2)
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
        log.info("wrote %s", args.out)
    else:
        sys.stdout.buffer.write(payload.encode("utf-8") + b"\n")


if __name__ == "__main__":
    main()
