from app import transcript
from app.schemas import Segment


def test_keeps_explicit_line_numbers(debt_lines):
    assert [l.n for l in debt_lines] == list(range(1, 14))
    assert debt_lines[7].n == 8 and debt_lines[7].speaker == "Agent"
    assert debt_lines[7].text.startswith("Let me note that")


def test_numbers_plain_lines_and_timestamps():
    lines = transcript.parse_text("[00:05] Agent: Hello\n[01:02] Customer: Hi there\ncontinued text\n")
    assert [(l.n, l.speaker, l.start) for l in lines] == [(1, "Agent", 5.0), (2, "Customer", 62.0)]
    assert lines[1].text == "Hi there continued text"


def test_segments_merge_same_speaker():
    segs = [Segment(speaker="Speaker 1", start_s=0, end_s=2, text="Hi"),
            Segment(speaker="Speaker 1", start_s=2.3, end_s=4, text="there."),
            Segment(speaker="Speaker 2", start_s=4.5, end_s=6, text="Hello.")]
    lines = transcript.from_segments(segs)
    assert [(l.n, l.text) for l in lines] == [(1, "Hi there."), (2, "Hello.")]
