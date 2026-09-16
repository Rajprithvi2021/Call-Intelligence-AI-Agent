"""Turn raw transcripts (plain text or diarized segments) into numbered lines."""
import re

from app.schemas import Segment, SpeakerRole, TranscriptLine

# Optional "7:" / "[7]" / "L7 |" line number, optional "[00:12]" timestamp, then "Speaker: text".
_LINE_RE = re.compile(
    r"""^\s*
    (?:(?:\[|L)?(?P<n>\d{1,5})(?:\]|\s*[:.)|])\s*)?          # line number
    (?:\[?(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]?\s*)?            # timestamp
    (?P<speaker>[A-Za-z][\w .'\-]{0,40}?)                     # speaker label
    (?:\s*\((?P<ts2>\d{1,2}:\d{2}(?::\d{2})?)\))?             # "Speaker (00:12)"
    \s*:\s+(?P<text>.+?)\s*$
    """,
    re.VERBOSE,
)


def _seconds(ts: str | None) -> float | None:
    if not ts:
        return None
    total = 0
    for part in ts.split(":"):
        total = total * 60 + int(part)
    return float(total)


def parse_text(text: str) -> list[TranscriptLine]:
    """Parse "Speaker: text" transcripts. Lines without a speaker continue the previous line.

    Explicit line numbers are kept when every line has one and they strictly increase,
    so references like "line 8" stay meaningful; otherwise lines are numbered 1..N.
    """
    parsed: list[dict] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = _LINE_RE.match(raw)
        if m:
            parsed.append({
                "n": int(m["n"]) if m["n"] else None,
                "speaker": m["speaker"].strip(),
                "start": _seconds(m["ts"] or m["ts2"]),
                "text": m["text"],
            })
        elif parsed:
            parsed[-1]["text"] += " " + raw.strip()
        else:
            parsed.append({"n": None, "speaker": "Unknown", "start": None, "text": raw.strip()})

    numbers = [p["n"] for p in parsed]
    keep = all(n is not None for n in numbers) and all(a < b for a, b in zip(numbers, numbers[1:]))
    return [
        TranscriptLine(n=p["n"] if keep else i, speaker=p["speaker"], start=p["start"], text=p["text"])
        for i, p in enumerate(parsed, start=1)
    ]


def from_segments(segments: list[Segment]) -> list[TranscriptLine]:
    lines: list[TranscriptLine] = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        # Merge consecutive fragments from the same speaker into one line.
        if lines and lines[-1].speaker == seg.speaker and seg.start_s - (lines[-1].end or 0) < 1.0:
            lines[-1].text += " " + text
            lines[-1].end = seg.end_s
            continue
        lines.append(TranscriptLine(n=len(lines) + 1, speaker=seg.speaker, start=seg.start_s, end=seg.end_s, text=text))
    return lines


def render(lines: list[TranscriptLine]) -> str:
    """Numbered form shown to the agents: `[8] Agent: text`."""
    return "\n".join(f"[{l.n}] {l.speaker}: {l.text}" for l in lines)


_ROLE_HINTS = {
    "agent": "agent", "rep": "agent", "representative": "agent", "collector": "agent",
    "salesperson": "agent", "support": "agent", "host": "agent",
    "consumer": "customer", "customer": "customer", "debtor": "customer",
    "caller": "customer", "client": "customer", "prospect": "customer",
}


def apply_roles(lines: list[TranscriptLine], roles: list[SpeakerRole]) -> None:
    """Set line roles from the Analyst's mapping, falling back to obvious speaker labels."""
    by_speaker = {r.speaker.strip().lower(): r.role for r in roles}
    for line in lines:
        key = line.speaker.strip().lower()
        line.role = by_speaker.get(key) or _ROLE_HINTS.get(key.split()[0], "unknown")
