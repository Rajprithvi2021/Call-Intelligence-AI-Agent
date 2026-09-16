"""Knowledge base: markdown policy files, one per domain.

v0 places the whole relevant policy file in the prompt. The files are small,
so this can't miss a rule the way retrieval could.
"""
from app.config import settings

DOMAINS = ["debt_collection", "sales", "support", "standup"]


def load_policy(domain: str | None) -> str:
    """Policy text for a domain; all policies when the domain is unknown (the Analyst classifies)."""
    names = [domain] if domain in DOMAINS else DOMAINS
    parts = []
    for name in ["general", *names]:
        path = settings.policies_dir / f"{name}.md"
        if path.exists():
            parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(parts)
