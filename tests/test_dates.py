from datetime import date

import pytest

from app.dates import reconcile, resolve
from tests.conftest import MEETING


@pytest.mark.parametrize("phrase, expected", [
    ("Friday", date(2026, 7, 3)),
    ("by Friday", date(2026, 7, 3)),
    ("I'll follow up by Friday", date(2026, 7, 3)),
    ("on the 15th of next month", date(2026, 8, 15)),
    ("$700 on the 15th of next month", date(2026, 8, 15)),
    ("tomorrow", date(2026, 7, 2)),
    ("today", MEETING),
    ("next Friday", date(2026, 7, 10)),
    ("Monday", date(2026, 7, 6)),
    ("by Wednesday", date(2026, 7, 8)),
    ("end of the week", date(2026, 7, 3)),
    ("end of month", date(2026, 7, 31)),
    ("end of next month", date(2026, 8, 31)),
    ("in two weeks", date(2026, 7, 15)),
    ("within 3 business days", date(2026, 7, 6)),
    ("July 20th", date(2026, 7, 20)),
    ("the 20th", date(2026, 7, 20)),
    ("the 10th", date(2026, 7, 10)),
    ("2026-09-01", date(2026, 9, 1)),
    ("March 3rd", date(2027, 3, 3)),
])
def test_resolves(phrase, expected):
    assert resolve(phrase, MEETING) == (expected, "resolved")


@pytest.mark.parametrize("phrase", ["soon", "ASAP", "sometime next week", "next month", "at some point", "later"])
def test_vague(phrase):
    assert resolve(phrase, MEETING) == (None, "vague")


def test_empty_is_none():
    assert resolve("", MEETING) == (None, "none")


def test_reconcile_flags_model_disagreement():
    d, status, note = reconcile("by Friday", "2026-07-10", MEETING)
    assert (d, status) == (date(2026, 7, 3), "resolved")
    assert "2026-07-10" in note


def test_reconcile_never_trusts_date_without_words():
    d, status, note = reconcile("", "2026-07-10", MEETING)
    assert d is None and status == "none" and note
