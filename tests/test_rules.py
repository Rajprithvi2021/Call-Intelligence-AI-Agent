import pytest

from app import rules
from app.schemas import TranscriptLine


def kinds(text):
    return {h.type for h in rules.scan([TranscriptLine(n=1, speaker="Consumer", text=text)])}


@pytest.mark.parametrize("text, kind", [
    ("I told you guys not to call me.", "cease_and_desist"),
    ("Stop calling me!", "cease_and_desist"),
    ("Don't call me ever again", "cease_and_desist"),
    ("Don't bother me.", "cease_and_desist"),
    ("Take me off from your list", "cease_and_desist"),
    ("Please don't contact me", "cease_and_desist"),
    ("I will sue you", "legal"),
    ("Contact my attorney", "legal"),
    ("I am bankrupt", "bankruptcy"),
    ("I filed chapter 13", "bankruptcy"),
    ("You have the wrong number", "wrong_number"),
    ("There's nobody here by that name", "wrong_number"),
    ("This is bullshit", "profanity"),
    ("What the f*** is this", "profanity"),
    ("This is ridiculous", "anger"),
    ("My SSN is 123-45-6789", "pii"),
    ("Card is 4111 1111 1111 1111", "pii"),
    ("This call is being recorded", "recording_disclosure"),
    ("I don't want to be recorded", "consent_refused"),
])
def test_detects(text, kind):
    assert kind in kinds(text)


@pytest.mark.parametrize("text", [
    "Thanks, I'll call you back on Friday.",
    "The number 1234 5678 9012 3456 is an order id",   # fails Luhn
    "Hello, how are you today?",
])
def test_no_false_positive(text):
    assert not kinds(text) - {"recording_disclosure"}
