"""Deterministic pre-scan for high-stakes, phrase-shaped signals.

These run before (and independently of) the LLM so a cease-and-desist or an
attorney mention is never missed just because the model overlooked it. Every
hit carries its line number.
"""
import re
from dataclasses import dataclass

from app.schemas import TranscriptLine

# Signals that only matter when the customer/consumer says them.
CUSTOMER_ONLY = {"cease_and_desist", "legal", "bankruptcy", "wrong_number", "anger", "consent_refused"}
# Signals that become risk flags (the rest feed sentiment or compliance checks).
RISK_TYPES = {"cease_and_desist", "legal", "bankruptcy", "wrong_number", "pii", "consent_refused"}

_I = re.IGNORECASE
PATTERNS: dict[str, list[re.Pattern]] = {
    "cease_and_desist": [
        re.compile(r"\bstop (calling|contacting|bothering|harassing)\b", _I),
        re.compile(r"\b(don'?t|do not|never)\s+(ever\s+)?(call|contact|bother|phone|text|email)\s+(me|us|this number|here)\b", _I),
        re.compile(r"\b(take|remove|get)\s+(me|my (name|number))\s+(off|out of|from)\b.*\b(list|system|database)\b", _I),
        re.compile(r"\btold (you|you guys|y'?all|your company)\s+(not to|to stop)\b", _I),
        re.compile(r"\bdo[- ]not[- ]call\b", _I),
        re.compile(r"\b(leave me alone|quit calling|cease and desist)\b", _I),
    ],
    "legal": [
        re.compile(r"\b(i'?ll|i will|i'?m going to|i am going to|gonna)\s+(sue|take (you|this) to court|file a (lawsuit|complaint))", _I),
        re.compile(r"\bsue (you|your company|y'?all)\b", _I),
        re.compile(r"\b(my|an|contact my|call my|talk to my|speak (to|with) my)\s+(attorney|lawyer|legal counsel)\b", _I),
        re.compile(r"\b(lawsuit|legal action|small claims)\b", _I),
        re.compile(r"\b(cfpb|attorney general|better business bureau)\b", _I),
    ],
    "bankruptcy": [
        re.compile(r"\bbankrupt(cy)?\b", _I),
        re.compile(r"\bchapter\s+(7|11|13|seven|eleven|thirteen)\b", _I),
    ],
    "wrong_number": [
        re.compile(r"\bwrong (number|person)\b", _I),
        re.compile(r"\b(no one|nobody|no-one)\s+(here\s+)?(by|with|named)\s+that name\b", _I),
        re.compile(r"\b(doesn'?t|does not|don'?t|do not)\s+(live|work)\s+here\b", _I),
        re.compile(r"\bnever heard of (him|her|them|that person)\b", _I),
        re.compile(r"\byou('ve| have|'ve got| got) the wrong\b", _I),
        re.compile(r"\bi'?m not (him|her|that person)\b", _I),
    ],
    "consent_refused": [
        re.compile(r"\b(don'?t|do not)\s+(want (to be|this call)|consent to (be|being))\s+record", _I),
        re.compile(r"\bstop recording\b", _I),
    ],
    "recording_disclosure": [
        re.compile(r"\b(call|conversation)\s+(is|may be|will be|is being|might be)\s+(recorded|monitored)\b", _I),
        re.compile(r"\brecord(ed|ing)\s+(this|the)\s+call\b", _I),
    ],
    "pii": [
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        re.compile(r"\bsocial security\b|\bssn\b", _I),
        re.compile(r"\b(date of birth|routing number|account number|card number|cvv|security code)\b", _I),
        re.compile(r"\bcard ending( in)?\s+\d{4}\b", _I),
    ],
    "profanity": [
        re.compile(r"\b(fuck\w*|shit\w*|bullshit|damn\w*|goddamn\w*|bitch\w*|asshole\w*|bastard\w*|crap|piss(ed)? off|wtf|screw you)\b", _I),
        re.compile(r"\b[fs]\*{2,}\w*", _I),
    ],
    "anger": [
        re.compile(r"\b(ridiculous|unacceptable|outrageous|furious|fed up|sick of|sick and tired|pissed)\b", _I),
        re.compile(r"\b(i'?m|i am) (so |really |very )?(angry|mad|upset|frustrated)\b", _I),
        re.compile(r"\bthis is (a )?(joke|scam|harassment)\b", _I),
    ],
}

_LONG_DIGITS = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


@dataclass(frozen=True)
class RuleHit:
    type: str
    line: int
    speaker: str
    match: str


def scan(lines: list[TranscriptLine]) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for line in lines:
        for kind, patterns in PATTERNS.items():
            for pat in patterns:
                m = pat.search(line.text)
                if m:
                    hits.append(RuleHit(kind, line.n, line.speaker, m.group(0)))
                    break
        for m in _LONG_DIGITS.finditer(line.text):
            digits = re.sub(r"\D", "", m.group(0))
            if _luhn_ok(digits):
                hits.append(RuleHit("pii", line.n, line.speaker, "possible card number"))
    return hits


def describe(hits: list[RuleHit]) -> str:
    """Compact listing handed to the Analyst as hints."""
    if not hits:
        return "(none)"
    return "\n".join(f"- line {h.line}: {h.type} ({h.match!r})" for h in hits)
