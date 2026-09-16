"""Data contracts.

Two layers:
  * Draft*  - what the LLM agents return. Evidence is only a list of line numbers,
              kept flat so it fits Gemini's response_schema subset.
  * Final   - what the system stores and serves. Evidence carries the verbatim
              transcript text, filled in by code (grounding.py), never by the model.
"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Domain = Literal["debt_collection", "sales", "support", "standup", "other"]
Rating = Literal["RED", "YELLOW", "GREEN"]
Severity = Literal["low", "medium", "high"]
SentimentLabel = Literal["positive", "neutral", "negative"]
Role = Literal["agent", "customer", "participant", "unknown"]
RiskType = Literal[
    "cease_and_desist", "legal", "bankruptcy", "wrong_number",
    "pii", "consent_refused", "consent_unclear", "other",
]
Verdict = Literal["supported", "unsupported", "needs_human"]
DateStatus = Literal["resolved", "vague", "none"]


# --------------------------------------------------------------------------- transcript

class TranscriptLine(BaseModel):
    n: int
    speaker: str
    role: Role = "unknown"
    start: float | None = None
    end: float | None = None
    text: str


class Segment(BaseModel):
    """One diarized utterance returned by a transcriber."""
    speaker: str
    start_s: float
    end_s: float
    text: str


class TranscriptionOutput(BaseModel):
    segments: list[Segment]


# --------------------------------------------------------------------------- LLM drafts

class SpeakerRole(BaseModel):
    speaker: str = Field(description="Speaker label exactly as it appears in the transcript")
    name: str = Field(description="Person's name if stated in the call, else empty string")
    role: Role


class DraftItem(BaseModel):
    text: str
    lines: list[int]
    confidence: float


class DraftActionItem(BaseModel):
    description: str
    owner: str = Field(description="Name of the person who committed. Empty string if nobody clearly owns it")
    owner_role: Role
    start_date_phrase: str = Field(description="Exact words used for the start date, or empty string")
    due_date_phrase: str = Field(description="Exact words used for the deadline, or empty string")
    due_date_guess: str = Field(description="Your YYYY-MM-DD reading of the deadline, or empty string")
    lines: list[int]
    confidence: float


class DraftCompliance(BaseModel):
    rule_id: str
    observation: str
    rating: Rating
    lines: list[int]
    confidence: float


class DraftRisk(BaseModel):
    type: RiskType
    description: str
    lines: list[int]
    confidence: float


class DraftSentiment(BaseModel):
    overall: SentimentLabel
    customer_angry: bool
    profanity: bool
    lines: list[int]


class DraftReview(BaseModel):
    item_ref: str = Field(description="Id of the item this concerns (e.g. A1), or 'call' for the whole call")
    reason: str
    category: str
    severity: Severity
    lines: list[int]


class AnalystDraft(BaseModel):
    tag: str
    summary: str
    domain: Domain
    speaker_roles: list[SpeakerRole]
    decisions: list[DraftItem]
    action_items: list[DraftActionItem]
    blockers: list[DraftItem]
    next_steps: list[DraftItem]
    compliance: list[DraftCompliance]
    sentiment: DraftSentiment
    risk_flags: list[DraftRisk]
    review_items: list[DraftReview]
    overall_confidence: float


class JudgeVerdict(BaseModel):
    item_id: str
    verdict: Verdict
    confidence: float
    reason: str


class ReviewerOutput(BaseModel):
    verdicts: list[JudgeVerdict]
    additional_review_items: list[DraftReview]


# --------------------------------------------------------------------------- final output

class Evidence(BaseModel):
    line: int
    speaker: str
    text: str


class Judgement(BaseModel):
    verdict: Verdict
    confidence: float
    reason: str


class NoteItem(BaseModel):
    id: str
    text: str
    evidence: list[Evidence]
    confidence: float
    judgement: Judgement | None = None


class ActionItem(BaseModel):
    id: str
    description: str
    owner: str | None
    owner_role: Role
    start_date: date | None = None
    due_date: date | None = None
    due_date_phrase: str = ""
    date_status: DateStatus = "none"
    date_note: str = ""
    evidence: list[Evidence]
    confidence: float
    judgement: Judgement | None = None


class ComplianceItem(BaseModel):
    id: str
    rule_id: str
    observation: str
    rating: Rating
    evidence: list[Evidence]
    confidence: float
    judgement: Judgement | None = None


class RiskFlag(BaseModel):
    id: str
    type: RiskType
    description: str
    source: Literal["rule", "llm", "rule+llm"]
    evidence: list[Evidence]


class Sentiment(BaseModel):
    overall: SentimentLabel = "neutral"
    customer_angry: bool = False
    profanity: bool = False
    evidence: list[Evidence] = []


class ReviewItem(BaseModel):
    id: str | None = None
    item_ref: str
    reason: str
    category: str
    severity: Severity
    source: Literal["rule", "analyst", "reviewer", "escalation", "grounding"]
    evidence: list[Evidence] = []
    status: Literal["open", "approved", "rejected", "edited"] = "open"
    resolver: str | None = None
    resolution_note: str | None = None


class CallNotes(BaseModel):
    meeting_date: date
    tag: str
    summary: str
    domain: Domain
    speaker_roles: list[SpeakerRole] = []
    decisions: list[NoteItem] = []
    action_items: list[ActionItem] = []
    blockers: list[NoteItem] = []
    next_steps: list[NoteItem] = []
    compliance: list[ComplianceItem] = []
    sentiment: Sentiment = Sentiment()
    risk_flags: list[RiskFlag] = []
    review_items: list[ReviewItem] = []
    overall_confidence: float = 0.0
    models: dict[str, str] = {}


class ProcessedCall(BaseModel):
    notes: CallNotes
    transcript: list[TranscriptLine]
