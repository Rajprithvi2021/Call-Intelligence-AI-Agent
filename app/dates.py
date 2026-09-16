"""Resolve spoken date phrases against the meeting date.

The LLM only reports the words that were said ("by Friday"); the arithmetic
happens here so it is exact and testable. Anything we can't pin down is
reported as `vague` and ends up in the review queue.
"""
import calendar
import re
from datetime import date, datetime, timedelta

from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "couple of": 2,
}
_VAGUE = re.compile(
    r"\b(soon|asap|as soon as possible|later|sometime|some time|shortly|when(ever)? possible|"
    r"at some point|eventually|a few|few days|in a bit|next week|next month|this week|this month|"
    r"end of (the )?quarter|next quarter|tbd|when .* ready)\b"
)
_FILLER = re.compile(r"\b(by|on|before|until|no later than|due|around|the|of|at|latest)\b")


def _next_weekday(anchor: date, weekday: int) -> date:
    """Next occurrence strictly after the anchor day."""
    days = (weekday - anchor.weekday()) % 7 or 7
    return anchor + timedelta(days=days)


def _last_day(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _safe_day(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def resolve(phrase: str, anchor: date) -> tuple[date | None, str]:
    """Return (date, status) where status is resolved | vague | none."""
    p = (phrase or "").strip().lower()
    if not p:
        return None, "none"
    p = p.replace("’", "'")

    # Already an ISO date.
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", p)
    if m:
        d = _safe_day(int(m[1]), int(m[2]), int(m[3]))
        return (d, "resolved") if d else (None, "vague")

    if re.search(r"\b(today|tonight|end of (the )?day|eod|close of business|cob)\b", p):
        return anchor, "resolved"
    if re.search(r"\bday after tomorrow\b", p):
        return anchor + timedelta(days=2), "resolved"
    if re.search(r"\btomorrow\b", p):
        return anchor + timedelta(days=1), "resolved"

    # "the 15th of next month", "15th of this month"
    m = re.search(r"\b(\d{1,2})(st|nd|rd|th)?\s+(of\s+)?(next|this|the following)\s+month\b", p)
    if m:
        base = anchor if m[4] == "this" else anchor + relativedelta(months=1)
        d = _safe_day(base.year, base.month, int(m[1]))
        return (d, "resolved") if d else (None, "vague")

    if re.search(r"\bend of (the )?next month\b", p):
        return _last_day(anchor + relativedelta(months=1)), "resolved"
    if re.search(r"\b(end of (the )?month|eom|month[- ]end)\b", p):
        return _last_day(anchor), "resolved"
    if re.search(r"\b(end of (the )?week|eow|week'?s end)\b", p):
        friday = anchor + timedelta(days=(4 - anchor.weekday()) % 7)
        return friday, "resolved"

    # "in 3 days", "in two weeks", "within a month"
    m = re.search(r"\b(in|within)\s+(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple of)\s+(business\s+)?(day|week|month)s?\b", p)
    if m:
        n = int(m[2]) if m[2].isdigit() else _NUMBER_WORDS[m[2]]
        unit = m[4]
        if unit == "day" and m[3]:
            d, left = anchor, n
            while left:
                d += timedelta(days=1)
                if d.weekday() < 5:
                    left -= 1
            return d, "resolved"
        delta = {"day": relativedelta(days=n), "week": relativedelta(weeks=n), "month": relativedelta(months=n)}[unit]
        return anchor + delta, "resolved"

    # Weekdays: "Friday", "by this Friday", "next Tuesday"
    for idx, name in enumerate(WEEKDAYS):
        if re.search(rf"\b{name}\b", p):
            d = _next_weekday(anchor, idx)
            wants_next_week = re.search(rf"\bnext\s+{name}\b|\bnext week\b", p)
            if wants_next_week and d.isocalendar()[1] == anchor.isocalendar()[1]:
                d += timedelta(days=7)  # "next Friday" said on Wednesday = Friday of next week
            return d, "resolved"

    if _VAGUE.search(p):
        return None, "vague"

    # "the 15th" -> next occurrence of that day of month
    m = re.fullmatch(r"(?:by |on |before )?(?:the )?(\d{1,2})(st|nd|rd|th)", p)
    if m:
        day = int(m[1])
        d = _safe_day(anchor.year, anchor.month, day)
        if d is None or d < anchor:
            nxt = anchor + relativedelta(months=1)
            d = _safe_day(nxt.year, nxt.month, day)
        return (d, "resolved") if d else (None, "vague")

    # Explicit calendar dates: "July 15", "15th of July", "7/15/2026"
    cleaned = _FILLER.sub(" ", p)
    if re.search(r"\d", cleaned) and (re.search(r"[a-z]{3,}", cleaned) or re.search(r"\d+[/-]\d+", cleaned)):
        try:
            d = dateparser.parse(cleaned, default=datetime(anchor.year, anchor.month, 1), fuzzy=True).date()
            if not re.search(r"\b\d{4}\b", cleaned) and d < anchor:
                d = d + relativedelta(years=1)
            return d, "resolved"
        except (ValueError, OverflowError):
            pass

    return None, "vague"


def reconcile(phrase: str, model_guess: str, anchor: date) -> tuple[date | None, str, str]:
    """Combine the resolver with the model's own reading. Returns (date, status, note)."""
    resolved, status = resolve(phrase, anchor)
    guess: date | None = None
    if model_guess:
        try:
            guess = date.fromisoformat(model_guess.strip())
        except ValueError:
            guess = None

    if status == "resolved":
        if guess and guess != resolved:
            return resolved, status, f"model read '{phrase}' as {guess}, resolver computed {resolved}"
        return resolved, status, ""
    if status == "vague":
        note = f"'{phrase}' is not a specific date"
        if guess:
            note += f"; model suggested {guess}"
        return None, status, note
    # No phrase at all: never trust a model date that has no words behind it.
    if guess:
        return None, "none", f"model proposed {guess} but no deadline was stated"
    return None, "none", ""
