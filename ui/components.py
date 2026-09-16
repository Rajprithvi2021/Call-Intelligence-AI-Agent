"""Shared helpers for the Streamlit UI: API client, cached reads, styling and HTML fragments.

All text coming from calls or models goes through `esc()` before it is placed in HTML.
"""
import html
import os
import re
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
API = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
SAMPLES = ROOT / "data" / "samples"

DOMAINS = ["debt_collection", "sales", "support", "standup"]
DOMAIN_LABEL = {"debt_collection": "Debt collection", "sales": "Sales", "support": "Support",
                "standup": "Standup", "other": "Other", None: "Pending"}
RISK_LABEL = {
    "cease_and_desist": "Stop contact", "legal": "Legal threat", "bankruptcy": "Bankruptcy",
    "wrong_number": "Wrong party", "pii": "Sensitive data", "consent_refused": "Recording refused",
    "consent_unclear": "Consent unclear", "other": "Other risk",
}
PROCESSING = ("queued", "transcribing", "analyzing", "reviewing", "indexing")


# --------------------------------------------------------------------------- API

class ApiError(RuntimeError):
    pass


def api(method: str, path: str, **kw):
    try:
        r = requests.request(method, f"{API}{path}", timeout=60, **kw)
    except requests.RequestException:
        raise ApiError(f"Cannot reach the API at {API}.")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text[:200]
        raise ApiError(f"API error {r.status_code}: {detail}")
    return r.json()


def call_api(method: str, path: str, **kw):
    """api() for page code: shows the error and stops the page instead of raising."""
    try:
        return api(method, path, **kw)
    except ApiError as exc:
        st.error(str(exc), icon=":material/cloud_off:")
        st.stop()


@st.cache_data(ttl=60, show_spinner=False)
def health() -> dict | None:
    try:
        return api("GET", "/health")
    except ApiError:
        return None


@st.cache_data(ttl=5, show_spinner=False)
def calls() -> list[dict]:
    return api("GET", "/calls")


@st.cache_data(ttl=5, show_spinner=False)
def call(call_id: str) -> dict:
    return api("GET", f"/calls/{call_id}")


@st.cache_data(ttl=5, show_spinner=False)
def reviews(status: str) -> list[dict]:
    return api("GET", "/review", params={"status": status})


def refresh() -> None:
    """Drop cached reads after a write."""
    calls.clear()
    call.clear()
    reviews.clear()


def resolve_review(review_id: str, status: str, note: str | None = None) -> None:
    call_api("POST", f"/review/{review_id}", json={
        "status": status, "resolver": st.session_state.get("reviewer") or None, "note": note or None})
    refresh()
    st.toast(f"Review item {status}", icon=":material/task_alt:")


# --------------------------------------------------------------------------- navigation

def open_call(call_id: str) -> None:
    from nav import CALL_PAGE
    st.switch_page(CALL_PAGE, query_params={"id": call_id})


# --------------------------------------------------------------------------- HTML fragments

def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def pill(label: str, tone: str = "gray", icon: str = "") -> str:
    return f'<span class="ci-pill ci-{tone}">{icon}{esc(label)}</span>'


SEVERITY_TONE = {"high": "red", "medium": "amber", "low": "gray"}
RATING_TONE = {"RED": "red", "YELLOW": "amber", "GREEN": "green"}
VERDICT_TONE = {"supported": "green", "unsupported": "red", "needs_human": "amber"}
SENTIMENT_TONE = {"positive": "green", "neutral": "gray", "negative": "red"}
STATUS_TONE = {"done": "green", "failed": "red"}


def status_pill(status: str) -> str:
    if status.startswith("waiting"):
        return pill("retrying (model busy)", "amber", '<span class="ci-dot"></span>')
    if status in PROCESSING:
        return pill(status, "blue", '<span class="ci-dot"></span>')
    return pill(status, STATUS_TONE.get(status, "gray"))


def verdict_pill(judgement: dict | None) -> str:
    if not judgement:
        return ""
    label = {"supported": "Verified", "unsupported": "Unsupported", "needs_human": "Needs human"}[judgement["verdict"]]
    return pill(label, VERDICT_TONE[judgement["verdict"]])


def confidence_bar(value: float) -> str:
    pct = max(0, min(100, round(value * 100)))
    tone = "green" if pct >= 80 else "amber" if pct >= 60 else "red"
    return (f'<span class="ci-conf" title="confidence {pct}%"><span class="ci-conf-bar ci-bg-{tone}" '
            f'style="width:{pct}%"></span></span><span class="ci-muted">{pct}%</span>')


def evidence_html(evidence: list[dict]) -> str:
    if not evidence:
        return '<div class="ci-muted">No transcript lines cited.</div>'
    rows = "".join(
        f'<div class="ci-quote"><span class="ci-ln">L{e["line"]}</span>'
        f'<span class="ci-spk">{esc(e["speaker"])}</span>{esc(e["text"])}</div>'
        for e in evidence
    )
    return f'<div class="ci-quotes">{rows}</div>'


def highlight_terms(text: str, query: str) -> str:
    """Escape text and wrap query words in <mark>."""
    out = esc(text)
    words = sorted({w for w in re.findall(r"[\w']+", query.lower()) if len(w) > 2}, key=len, reverse=True)
    for w in words:
        out = re.sub(rf"(?i)\b({re.escape(esc(w))}\w*)", r"<mark>\1</mark>", out)
    return out


def transcript_html(lines: list[dict], speaker_roles: list[dict], highlight: set[int] | None = None,
                    query: str = "") -> str:
    roles = {r["speaker"]: r for r in speaker_roles or []}
    highlight = highlight or set()
    parts = []
    for l in lines:
        info = roles.get(l["speaker"], {})
        role = l.get("role") or info.get("role") or "unknown"
        side = "agent" if role == "agent" else "other"
        name = info.get("name") or ""
        who = esc(l["speaker"]) + (f' <span class="ci-muted">· {esc(name)}</span>'
                                   if name and name.lower() != l["speaker"].lower() else "")
        ts = ""
        if l.get("start") is not None:
            m, s = divmod(int(l["start"]), 60)
            ts = f'<span class="ci-muted">{m:02d}:{s:02d}</span>'
        text = highlight_terms(l["text"], query) if query else esc(l["text"])
        cls = f"ci-msg ci-{side}" + (" ci-hl" if l["n"] in highlight else "")
        parts.append(
            f'<div class="{cls}" id="line-{l["n"]}"><div class="ci-msg-head">'
            f'<span class="ci-ln">{l["n"]}</span><b>{who}</b>'
            f'<span class="ci-role">{esc(role)}</span>{ts}</div>'
            f'<div class="ci-msg-body">{text}</div></div>'
        )
    return f'<div class="ci-transcript">{"".join(parts)}</div>'


def bars_html(counts: list[tuple[str, int]], tone: str = "red") -> str:
    """Horizontal bar chart in plain HTML (no chart libraries)."""
    top = max((n for _, n in counts), default=0) or 1
    rows = "".join(
        f'<div class="ci-bar-row"><span class="ci-bar-label">{esc(label)}</span>'
        f'<span class="ci-bar-track"><span class="ci-bar ci-bg-{tone}" style="width:{round(100 * n / top)}%"></span></span>'
        f'<span class="ci-bar-n">{n}</span></div>'
        for label, n in counts
    )
    return f'<div class="ci-bars">{rows}</div>'


def call_rows(items: list[dict]) -> None:
    """Call list as rows; the title links to the call page."""
    from nav import CALL_PAGE

    head = st.columns([4, 2, 1.4, 1.3, 1.3, 1.1], vertical_alignment="center")
    for col, label in zip(head, ["Call", "Domain", "Date", "Status", "Sentiment", "Reviews"]):
        col.html(f'<span class="ci-th">{label}</span>')
    for c in items:
        with st.container(border=True):
            row = st.columns([4, 2, 1.4, 1.3, 1.3, 1.1], vertical_alignment="center")
            with row[0]:
                st.page_link(CALL_PAGE, label=c["title"], icon=":material/call:",
                             query_params={"id": c["id"]}, width="stretch")
                if c.get("tag"):
                    st.html(f'<div class="ci-muted" style="margin:-6px 0 0 30px">{esc(c["tag"])}</div>')
            row[1].html(pill(DOMAIN_LABEL.get(c.get("domain"), c.get("domain") or "—"), "indigo"))
            row[2].html(f'<span class="ci-muted">{esc(c["meeting_date"])}</span>')
            row[3].html(status_pill(c["status"]))
            s = c.get("sentiment")
            row[4].html(pill(s.capitalize(), SENTIMENT_TONE.get(s, "gray")) if s else '<span class="ci-muted">—</span>')
            n = c.get("open_reviews") or 0
            row[5].html(pill(str(n), "amber") if n else pill("0", "green"))


def card(inner: str, accent: str | None = None, extra_class: str = "") -> str:
    style = f' style="border-left:4px solid var(--ci-{accent})"' if accent else ""
    return f'<div class="ci-card {extra_class}"{style}>{inner}</div>'


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    eb = f'<div class="ci-eyebrow">{esc(eyebrow)}</div>' if eyebrow else ""
    sub = f'<div class="ci-sub">{esc(subtitle)}</div>' if subtitle else ""
    st.html(f'<div class="ci-header">{eb}<h1>{esc(title)}</h1>{sub}</div>')


def empty_state(title: str, text: str, icon: str = "inbox") -> None:
    st.html(f'<div class="ci-empty"><div class="ci-empty-icon">'
            f'<span class="material-symbols-rounded">{icon}</span></div>'
            f'<div class="ci-empty-title">{esc(title)}</div><div class="ci-muted">{esc(text)}</div></div>')


# --------------------------------------------------------------------------- styles

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,500,0,0');

:root {
  --ci-red: #dc2626; --ci-amber: #d97706; --ci-green: #059669; --ci-blue: #2563eb;
  --ci-gray: #64748b; --ci-indigo: #4f46e5; --ci-violet: #7c3aed;
  --ci-border: #e3e6ef; --ci-muted: #6b7280; --ci-card: #ffffff;
}
html, body, .stApp,
.stApp :is(p, div, label, input, textarea, button, li, h1, h2, h3, h4, h5, h6, a, td, th, span):not(
  [data-testid*="Icon"], .material-symbols-rounded, code, pre, code *) {
  font-family: 'Inter', sans-serif;
}
.block-container { padding-top: 4.2rem; padding-bottom: 3rem; max-width: 1320px; }
footer, #MainMenu { visibility: hidden; }
h1, h2, h3, h4 { letter-spacing: -0.01em; }

/* Streamlit bordered containers look like cards */
div[data-testid="stVerticalBlockBorderWrapper"] { background: var(--ci-card); border-radius: 14px; }
div[data-testid="stMetric"] { background: var(--ci-card); border: 1px solid var(--ci-border);
  border-radius: 14px; padding: 14px 18px; box-shadow: 0 1px 2px rgba(16,24,40,.04); }
div[data-testid="stMetricLabel"] p { font-size: .78rem; text-transform: uppercase; letter-spacing: .05em;
  color: var(--ci-muted); font-weight: 600; }
div[data-testid="stMetricValue"] { font-weight: 700; }
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--ci-border); }
.stTabs [data-baseweb="tab"] { padding: 8px 14px; font-weight: 500; }
section[data-testid="stSidebar"] { border-right: 1px solid var(--ci-border); }

.ci-header { margin: 0 0 1.1rem 0; }
.ci-header h1 { font-size: 1.85rem; font-weight: 700; margin: 0; padding: 0; line-height: 1.2; }
.ci-eyebrow { font-size: .75rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
  color: var(--ci-indigo); margin-bottom: .25rem; }
.ci-sub { color: var(--ci-muted); margin-top: .35rem; font-size: .98rem; }
.ci-muted { color: var(--ci-muted); font-size: .85rem; }

.ci-card { background: var(--ci-card); border: 1px solid var(--ci-border); border-radius: 14px;
  padding: 14px 16px; margin-bottom: 10px; box-shadow: 0 1px 2px rgba(16,24,40,.04); }
.ci-card-title { font-weight: 600; font-size: 1rem; margin-bottom: 6px; line-height: 1.4; }
.ci-row { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; font-size: .86rem; }
.ci-kv { color: var(--ci-muted); } .ci-kv b { color: #1c2233; font-weight: 600; }

.ci-pill { display: inline-flex; align-items: center; gap: 5px; padding: 2px 10px; border-radius: 999px;
  font-size: .75rem; font-weight: 600; white-space: nowrap; border: 1px solid transparent; margin: 1px 2px 1px 0; }
.ci-red { background: #fef2f2; color: #b91c1c; border-color: #fecaca; }
.ci-amber { background: #fffbeb; color: #b45309; border-color: #fde68a; }
.ci-green { background: #ecfdf5; color: #047857; border-color: #a7f3d0; }
.ci-blue { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }
.ci-gray { background: #f3f4f6; color: #4b5563; border-color: #e5e7eb; }
.ci-indigo { background: #eef2ff; color: #4338ca; border-color: #c7d2fe; }
.ci-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; animation: ci-pulse 1.2s infinite; }
@keyframes ci-pulse { 0%,100% { opacity: 1 } 50% { opacity: .25 } }

.ci-conf { display: inline-block; width: 64px; height: 6px; background: #e5e7eb; border-radius: 99px;
  overflow: hidden; vertical-align: middle; margin-right: 6px; }
.ci-conf-bar { display: block; height: 100%; border-radius: 99px; }
.ci-bg-green { background: var(--ci-green); } .ci-bg-amber { background: var(--ci-amber); }
.ci-bg-red { background: var(--ci-red); }

.ci-quotes { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.ci-quote { background: #f8f9fc; border: 1px solid var(--ci-border); border-radius: 10px; padding: 7px 10px;
  font-size: .86rem; line-height: 1.45; }
.ci-ln { display: inline-block; min-width: 30px; font-size: .72rem; font-weight: 700; color: var(--ci-indigo);
  background: #eef2ff; border-radius: 6px; padding: 1px 6px; margin-right: 8px; text-align: center; }
.ci-spk { font-weight: 600; margin-right: 6px; }

.ci-hero { background: linear-gradient(135deg, #eef2ff 0%, #f5f3ff 60%, #ffffff 100%);
  border: 1px solid #e0e7ff; border-radius: 18px; padding: 20px 22px; margin-bottom: 14px; }
.ci-hero-tag { font-size: 1.55rem; font-weight: 700; margin: 4px 0 8px 0; line-height: 1.25; }
.ci-summary { font-size: 1rem; line-height: 1.6; margin-top: 10px; }

.ci-transcript { display: flex; flex-direction: column; gap: 8px; }
.ci-msg { max-width: 92%; border-radius: 14px; padding: 8px 12px; border: 1px solid var(--ci-border);
  transition: box-shadow .2s; }
.ci-msg.ci-agent { align-self: flex-start; background: #ffffff; }
.ci-msg.ci-other { align-self: flex-end; background: #f1f5ff; border-color: #dbe4ff; }
.ci-msg.ci-hl { background: #fff7d6; border-color: #f5c542; box-shadow: 0 0 0 3px rgba(245,197,66,.28); }
.ci-msg-head { display: flex; gap: 8px; align-items: center; font-size: .78rem; margin-bottom: 3px; }
.ci-role { font-size: .68rem; text-transform: uppercase; letter-spacing: .05em; color: var(--ci-muted); }
.ci-msg-body { font-size: .92rem; line-height: 1.5; }
mark { background: #fde68a; padding: 0 2px; border-radius: 3px; }

.ci-empty { text-align: center; padding: 48px 12px; border: 1px dashed #cfd5e3; border-radius: 16px;
  background: #fbfbfe; }
.ci-empty-icon .material-symbols-rounded { font-size: 40px; color: #a5b4fc; }
.ci-empty-title { font-weight: 600; font-size: 1.05rem; margin: 6px 0 2px; }

.ci-step { display: flex; gap: 12px; align-items: flex-start; padding: 8px 0; }
.ci-step-n { flex: none; width: 26px; height: 26px; border-radius: 50%; background: #eef2ff; color: var(--ci-indigo);
  font-weight: 700; font-size: .8rem; display: flex; align-items: center; justify-content: center; }
.ci-step-t { font-weight: 600; font-size: .92rem; }
.ci-brand { display: flex; align-items: center; gap: 10px; margin: 2px 0 12px; }
.ci-brand-logo { width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center;
  justify-content: center; color: #fff; background: linear-gradient(135deg, #4f46e5, #7c3aed); }
.ci-brand-name { font-weight: 700; font-size: 1.02rem; line-height: 1.1; }
.ci-bars { display: flex; flex-direction: column; gap: 9px; padding: 4px 2px; }
.ci-bar-row { display: grid; grid-template-columns: 130px 1fr 28px; gap: 10px; align-items: center; font-size: .86rem; }
.ci-bar-track { height: 10px; background: #eef0f5; border-radius: 99px; overflow: hidden; }
.ci-bar { display: block; height: 100%; border-radius: 99px; }
.ci-bar-n { font-weight: 700; text-align: right; }
.ci-th { font-size: .72rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--ci-muted);
  padding-left: 14px; }
div[data-testid="stPageLink"] a p { font-weight: 600; }
.ci-health { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
</style>
"""


def inject_css() -> None:
    st.html(CSS)
