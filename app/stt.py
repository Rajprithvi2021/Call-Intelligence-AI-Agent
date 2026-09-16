"""Speech-to-text behind one interface. v0 uses Gemini; Deepgram is ready as an option."""
import mimetypes
from pathlib import Path
from typing import Protocol

import httpx

from app import llm
from app.config import settings
from app.schemas import Segment, TranscriptionOutput

TRANSCRIBE_SYSTEM = """\
You are a verbatim transcription engine for business phone calls and meetings.
Transcribe the audio exactly as spoken, with speaker diarization.

- Split the audio into segments at every change of speaker (and at long pauses).
- Label speakers consistently throughout as "Speaker 1", "Speaker 2", ... in order of first appearance.
  If a speaker's role is obvious (e.g. the company representative vs. the customer), still use the
  numbered labels; roles are assigned later.
- Keep the words verbatim: include fillers, false starts, profanity and numbers as spoken. Do not
  summarize, correct grammar, translate or censor.
- start_s / end_s are the segment's start and end time in seconds from the beginning of the audio.
- Mark unintelligible audio as [inaudible]. Do not guess missing words.
"""


class Transcriber(Protocol):
    def transcribe(self, path: Path) -> list[Segment]: ...


class GeminiTranscriber:
    def __init__(self, model: str):
        self.model = model

    def transcribe(self, path: Path) -> list[Segment]:
        mime = mimetypes.guess_type(path.name)[0] or "audio/wav"
        uploaded = llm.upload_file(path, mime)
        try:
            out, _ = llm.generate_structured(
                self.model, TRANSCRIBE_SYSTEM,
                [uploaded, "Transcribe this recording."],
                TranscriptionOutput, thinking_level="LOW",
            )
        finally:
            llm.delete_file(uploaded)
        return out.segments


class DeepgramTranscriber:
    """Deepgram Nova-3 prerecorded API. Needs DEEPGRAM_API_KEY. Not exercised in v0."""

    URL = "https://api.deepgram.com/v1/listen"

    def __init__(self, api_key: str):
        if not api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set")
        self.api_key = api_key

    def transcribe(self, path: Path) -> list[Segment]:
        mime = mimetypes.guess_type(path.name)[0] or "audio/wav"
        params = {"model": "nova-3", "diarize": "true", "utterances": "true",
                  "smart_format": "true", "punctuate": "true"}
        with path.open("rb") as fh:
            resp = httpx.post(self.URL, params=params, content=fh.read(), timeout=600,
                              headers={"Authorization": f"Token {self.api_key}", "Content-Type": mime})
        resp.raise_for_status()
        return [
            Segment(speaker=f"Speaker {u['speaker'] + 1}", start_s=u["start"], end_s=u["end"], text=u["transcript"])
            for u in resp.json()["results"]["utterances"]
        ]


def get_transcriber() -> Transcriber:
    provider = settings.transcription_provider.lower()
    if provider == "gemini":
        return GeminiTranscriber(settings.transcription_model)
    if provider == "deepgram":
        return DeepgramTranscriber(settings.deepgram_api_key)
    raise ValueError(f"Unknown TRANSCRIPTION_PROVIDER: {settings.transcription_provider}")
