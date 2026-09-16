"""Streamlit front end for the Call Intelligence API.

    streamlit run ui/streamlit_app.py
"""
import json
import os
import time
from datetime import date
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
API = os.getenv("API_URL", "http://127.0.0.1:8000")
SAMPLES = ROOT / "data" / "samples"
DOMAINS = ["auto-detect", "debt_collection", "sales", "support", "standup"]
RISK_TYPES = ["cease_and_desist", "legal", "bankruptcy", "wrong_number", "pii", "consent_refused", "consent_unclear"]
PAGES = ["Process call", "Calls", "Review queue", "Search"]
RATING_COLOR = {"RED": "red", "YELLOW": "orange", "GREEN": "green"}
SEVERITY_COLOR = {"high": "red", "medium": "orange", "low": "gray"}
VERDICT_COLOR = {"supported": "green", "unsupported": "red", "needs_human": "orange"}

st.set_page_config(page_title="Call Intelligence", page_icon="📞", layout="wide")


# --------------------------------------------------------------------------- helpers

def api(method: str, path: str, **kw):
    try:
        r = requests.request(method, f"{API}{path}", timeout=60, **kw)
    except requests.ConnectionError:
        st.error(f"Cannot reach the API at {API}. Start it with `uvicorn app.api:app`.")
        st.stop()
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        st.error(f"API error {r.status_code}: {detail}")
        st.stop()
    return r.json()


def esc(text: str) -> str:
    """Escape characters Streamlit markdown would interpret ($ starts LaTeX)."""
    for ch in "\\$*_[]`<>#":
        text = text.replace(ch, "\\" + ch)
    return text


def badge(label: str, color: str) -> str:
    return f":{color}-background[{esc(label)}]"


def go(page: str, call_id: str | None = None) -> None:
    st.session_state.nav = page  # applied before the page radio is created on the next run
    if call_id:
        st.session_state.call_id = call_id
    st.rerun()


def evidence_md(evidence: list[dict]) -> str:
    return "\n".join(f"> **L{e['line']}** · {esc(e['speaker'])}: {esc(e['text'])}  " for e in evidence)


# --------------------------------------------------------------------------- review actions

def review_card(r: dict, key: str, show_call: bool = False) -> None:
    with st.container(border=True):
        head = f"{badge(r['severity'].upper(), SEVERITY_COLOR[r['severity']])} **{esc(r['category'])}** · item `{r['item_ref']}` · via {r['source']}"
        if show_call:
            head += f" · {esc(r.get('call_title') or '')} ({r.get('meeting_date')})"
        st.markdown(head)
        st.markdown(esc(r["reason"]))
        if r.get("evidence"):
            st.markdown(evidence_md(r["evidence"]))
        if r["status"] != "open":
            st.caption(f"{r['status']} by {r.get('resolver') or 'unknown'}: {r.get('resolution_note') or ''}")
            return
        note = st.text_input("Note", key=f"note-{key}", label_visibility="collapsed", placeholder="Resolution note (optional)")
        cols = st.columns([1, 1, 1, 5])
        for col, status, label in zip(cols, ["approved", "rejected", "edited"], ["✅ Approve", "❌ Reject", "✏️ Edited"]):
            if col.button(label, key=f"{status}-{key}"):
                api("POST", f"/review/{r['id']}", json={
                    "status": status, "resolver": st.session_state.get("reviewer") or None, "note": note or None})
                st.toast(f"Marked {status}")
                st.rerun()
        if show_call and cols[3].button("Open call", key=f"open-{key}"):
            go("Calls", r["call_id"])


# --------------------------------------------------------------------------- call view

def item_line(item: dict) -> str:
    j = item.get("judgement")
    verdict = f" {badge(j['verdict'], VERDICT_COLOR[j['verdict']])}" if j else ""
    return f"conf {item['confidence']:.2f}{verdict}"


def render_notes(notes: dict) -> list[tuple[str, str, list[int]]]:
    """Render notes; returns (id, label, lines) for the evidence highlighter."""
    index = []

    def simple(title: str, key: str):
        items = notes[key]
        st.markdown(f"#### {title} ({len(items)})")
        if not items:
            st.caption("None")
        for it in items:
            with st.container(border=True):
                st.markdown(f"`{it['id']}` **{esc(it['text'])}**  \n{item_line(it)}")
                with st.expander("Evidence"):
                    st.markdown(evidence_md(it["evidence"]))
            index.append((it["id"], it["text"], [e["line"] for e in it["evidence"]]))

    simple("Decisions", "decisions")

    st.markdown(f"#### Action items ({len(notes['action_items'])})")
    if not notes["action_items"]:
        st.caption("None")
    for a in notes["action_items"]:
        with st.container(border=True):
            owner = esc(a["owner"]) if a["owner"] else badge("no owner", "red")
            if a["due_date"]:
                due = f"**{a['due_date']}**"
                if a["due_date_phrase"]:
                    due += f" (\"{esc(a['due_date_phrase'])}\")"
            elif a["date_status"] == "vague":
                due = badge(f"vague: {a['due_date_phrase']}", "orange")
            else:
                due = "not stated"
            st.markdown(f"`{a['id']}` **{esc(a['description'])}**  \nOwner: {owner} ({a['owner_role']}) · Due: {due}  \n{item_line(a)}")
            if a.get("date_note"):
                st.caption(a["date_note"])
            with st.expander("Evidence"):
                st.markdown(evidence_md(a["evidence"]))
        index.append((a["id"], a["description"], [e["line"] for e in a["evidence"]]))

    simple("Blockers", "blockers")
    simple("Proposed next steps", "next_steps")

    st.markdown(f"#### Compliance ({len(notes['compliance'])})")
    for c in notes["compliance"]:
        with st.container(border=True):
            st.markdown(f"{badge(c['rating'], RATING_COLOR[c['rating']])} `{c['id']}` **{esc(c['rule_id'])}**: "
                        f"{esc(c['observation'])}  \n{item_line(c)}")
            if c["evidence"]:
                with st.expander("Evidence"):
                    st.markdown(evidence_md(c["evidence"]))
        index.append((c["id"], f"{c['rule_id']} {c['observation']}", [e["line"] for e in c["evidence"]]))

    st.markdown(f"#### Risk flags ({len(notes['risk_flags'])})")
    if not notes["risk_flags"]:
        st.caption("None")
    for f in notes["risk_flags"]:
        with st.container(border=True):
            st.markdown(f"{badge(f['type'], 'red')} `{f['id']}` {esc(f['description'])} · source: {f['source']}")
            with st.expander("Evidence"):
                st.markdown(evidence_md(f["evidence"]))
        index.append((f["id"], f["type"], [e["line"] for e in f["evidence"]]))
    return index


def render_call(call_id: str) -> None:
    call = api("GET", f"/calls/{call_id}")
    st.subheader(call["title"])
    meta = f"{call['meeting_date']} · {call.get('domain') or 'domain pending'} · source: {call['source']} · status: **{call['status']}**"
    st.markdown(meta)

    if call["status"] not in ("done", "failed"):
        st.info(f"Processing… ({call['status']})")
        time.sleep(2)
        st.rerun()
    if call["status"] == "failed":
        st.error(call.get("error") or "Processing failed")
        if st.button("Retry", type="primary"):
            api("POST", f"/calls/{call_id}/retry")
            st.rerun()
        return

    notes = call["notes"]
    s = notes["sentiment"]
    chips = [badge(f"sentiment: {s['overall']}", {"positive": "green", "neutral": "gray", "negative": "red"}[s["overall"]])]
    if s["customer_angry"]:
        chips.append(badge("angry customer", "red"))
    if s["profanity"]:
        chips.append(badge("profanity", "red"))
    chips += [badge(f["type"], "red") for f in notes["risk_flags"]]
    open_reviews = [r for r in call["reviews"] if r["status"] == "open"]
    chips.append(badge(f"{len(open_reviews)} open review items", "orange" if open_reviews else "green"))

    st.markdown(f"### {esc(notes['tag'])}")
    st.markdown(" ".join(chips))
    st.markdown(esc(notes["summary"]))
    st.caption(f"overall confidence {notes['overall_confidence']:.2f} · models: {notes.get('models')}")

    tab_notes, tab_review, tab_json = st.tabs(["Notes & transcript", f"Human review ({len(open_reviews)})", "JSON"])
    with tab_notes:
        left, right = st.columns([3, 2], gap="large")
        with left:
            index = render_notes(notes)
        with right:
            st.markdown("#### Transcript")
            options = ["(none)"] + [f"{i} · {label[:60]}" for i, label, _ in index]
            pick = st.selectbox("Highlight evidence for", options)
            highlight = set()
            if pick != "(none)":
                highlight = set(next(lines for i, _, lines in index if pick.startswith(i + " ")))
            roles = {r["speaker"]: f"{r['name']} ({r['role']})" if r["name"] else r["role"] for r in notes["speaker_roles"]}
            with st.container(height=900):
                for l in call["transcript"]:
                    who = esc(l["speaker"])
                    if l["speaker"] in roles and roles[l["speaker"]].lower() != l["speaker"].lower():
                        who += f" · {esc(roles[l['speaker']])}"
                    text = esc(l["text"])
                    if l["n"] in highlight:
                        text = f":orange-background[{text}]"
                    st.markdown(f"`{l['n']:>3}` **{who}**: {text}")
    with tab_review:
        if not call["reviews"]:
            st.success("Nothing needs human review.")
        for r in call["reviews"]:
            review_card(r, key=f"c-{r['id']}")
    with tab_json:
        st.download_button("Download notes JSON", json.dumps(notes, indent=2), file_name=f"call-{call_id}.json")
        st.json(notes, expanded=False)


# --------------------------------------------------------------------------- pages

def page_process() -> None:
    st.header("Process a call")
    samples = sorted(p.name for p in SAMPLES.glob("*.txt"))
    sample = st.selectbox("Load a sample transcript (optional)", ["(none)"] + samples)
    sample_text = (SAMPLES / sample).read_text(encoding="utf-8") if sample != "(none)" else ""

    with st.form("process"):
        c1, c2, c3 = st.columns(3)
        title = c1.text_input("Title", value=Path(sample).stem if sample != "(none)" else "")
        meeting_date = c2.date_input("Meeting date", value=_sample_date(sample))
        domain = c3.selectbox("Domain", DOMAINS, index=_sample_domain(sample))
        participants = st.text_input("Participants (optional)", placeholder="Marcus (agent), James Carter (consumer)")
        upload = st.file_uploader("Recording or transcript file",
                                  type=["wav", "mp3", "m4a", "aac", "ogg", "flac", "webm", "txt"])
        text = st.text_area("…or paste a transcript (one `Speaker: text` per line)", value=sample_text, height=260)
        submitted = st.form_submit_button("Process", type="primary")

    if submitted:
        data = {"meeting_date": meeting_date.isoformat(), "title": title}
        if domain != "auto-detect":
            data["domain"] = domain
        if participants:
            data["participants"] = participants
        files = None
        if upload is not None:
            files = {"file": (upload.name, upload.getvalue(), upload.type or "application/octet-stream")}
        elif text.strip():
            data["transcript"] = text
        else:
            st.warning("Upload a file or paste a transcript.")
            return
        created = api("POST", "/calls", data=data, files=files)
        go("Calls", created["id"])


def _sample_date(sample: str) -> date:
    for part in sample.replace(".txt", "").split("_"):
        try:
            return date.fromisoformat(part)
        except ValueError:
            continue
    return date.today()


def _sample_domain(sample: str) -> int:
    prefix = {"debt": "debt_collection", "collections": "debt_collection", "sales": "sales",
              "support": "support", "standup": "standup"}
    return DOMAINS.index(prefix.get(sample.split("_")[0], "auto-detect"))


def page_calls() -> None:
    calls = api("GET", "/calls")
    if not calls:
        st.info("No calls yet. Process one first.")
        return
    labels = {c["id"]: f"{c['title']} · {c['meeting_date']} · {c['status']}"
                        + (f" · {c['open_reviews']} to review" if c.get("open_reviews") else "") for c in calls}
    ids = list(labels)
    current = st.session_state.get("call_id")
    idx = ids.index(current) if current in ids else 0
    with st.sidebar:
        st.markdown("---")
        chosen = st.radio("Calls", ids, index=idx, format_func=labels.get)
    st.session_state.call_id = chosen
    render_call(chosen)


def page_review() -> None:
    st.header("Human review queue")
    status = st.segmented_control("Status", ["open", "approved", "rejected", "edited"], default="open")
    items = api("GET", "/review", params={"status": status or "open"})
    st.caption(f"{len(items)} items")
    for r in items:
        review_card(r, key=f"q-{r['id']}", show_call=True)


def page_search() -> None:
    st.header("Search transcripts")
    c1, c2, c3, c4 = st.columns([4, 2, 2, 2])
    q = c1.text_input("Query", placeholder='e.g. "attorney", "they will take us to court", "stop calling"')
    domain = c2.selectbox("Domain", ["any"] + DOMAINS[1:])
    flag = c3.selectbox("Risk flag", ["any"] + RISK_TYPES)
    sentiment = c4.selectbox("Sentiment", ["any", "positive", "neutral", "negative"])
    if not (q or domain != "any" or flag != "any" or sentiment != "any"):
        st.caption("Keyword + semantic search over every transcript line, with call-level filters.")
        return
    params = {"q": q}
    for k, v in (("domain", domain), ("flag", flag), ("sentiment", sentiment)):
        if v != "any":
            params[k] = v
    res = api("GET", "/search", params=params)
    st.caption(f"{len(res['results'])} results · {'keyword + semantic' if res['semantic'] else 'keyword only'}")
    for i, r in enumerate(res["results"]):
        with st.container(border=True):
            where = f"line {r['line']} · {esc(r['speaker'])}" if r["line"] else "call summary"
            cols = st.columns([6, 1])
            cols[0].markdown(f"**{esc(r['title'])}** · {esc(r.get('tag') or '')} · {where}  \n{esc(r['text'])}")
            if cols[1].button("Open", key=f"s-{i}"):
                go("Calls", r["call_id"])


# --------------------------------------------------------------------------- layout

with st.sidebar:
    st.title("📞 Call Intelligence")
    if "nav" in st.session_state:
        st.session_state.page = st.session_state.pop("nav")
    elif "page" not in st.session_state:
        st.session_state.page = PAGES[0]
    st.radio("Page", PAGES, key="page", label_visibility="collapsed")
    st.text_input("Reviewer name", key="reviewer", placeholder="for review sign-off")
    health = api("GET", "/health")
    st.caption(f"store: {health['store']} · analyst: {health['analyst_model']} · judge: {health['judge_model']} · "
               f"STT: {health['transcription']} · embeddings: {health['embeddings']}")

{"Process call": page_process, "Calls": page_calls, "Review queue": page_review, "Search": page_search}[st.session_state.page]()
