from datetime import date
from pathlib import Path

import pytest

from app import transcript

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
MEETING = date(2026, 7, 1)  # a Wednesday


@pytest.fixture
def debt_lines():
    return transcript.parse_text((SAMPLES / "debt_collection_2026-07-01.txt").read_text(encoding="utf-8"))
