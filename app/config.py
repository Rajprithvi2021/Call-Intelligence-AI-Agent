"""Runtime settings, read once from the environment (.env is loaded automatically)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")

    transcription_provider: str = os.getenv("TRANSCRIPTION_PROVIDER", "gemini")
    transcription_model: str = os.getenv("TRANSCRIPTION_MODEL", "gemini-3.6-flash")
    deepgram_api_key: str = os.getenv("DEEPGRAM_API_KEY", "")

    analyst_model: str = os.getenv("ANALYST_MODEL", "gemini-3.6-flash")
    judge_model: str = os.getenv("JUDGE_MODEL", "gemini-3.6-flash")
    fallback_models: tuple[str, ...] = tuple(
        m.strip() for m in os.getenv("LLM_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3.7-flash,gemini-3.8-flash,gemini-flash-latest").split(",") if m.strip()
    )
    analyst_thinking: str = os.getenv("ANALYST_THINKING_LEVEL", "HIGH")
    judge_thinking: str = os.getenv("JUDGE_THINKING_LEVEL", "MEDIUM")

    embed_enabled: bool = _bool("EMBED_ENABLED", True)
    embed_model: str = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
    embed_dim: int = int(os.getenv("EMBED_DIM", "768"))
    search_max_distance: float = float(os.getenv("SEARCH_MAX_DISTANCE", "0.36"))  # tuned on the sample calls
    search_semantic_top_k: int = int(os.getenv("SEARCH_SEMANTIC_TOP_K", "10"))

    database_url: str = os.getenv("DATABASE_URL", "")
    local_store_dir: Path = ROOT / os.getenv("LOCAL_STORE_DIR", "data/store")
    upload_dir: Path = ROOT / "data" / "uploads"
    policies_dir: Path = ROOT / "policies"

    job_concurrency: int = int(os.getenv("JOB_CONCURRENCY", "1"))
    review_threshold: float = float(os.getenv("REVIEW_THRESHOLD", "0.7"))


settings = Settings()
