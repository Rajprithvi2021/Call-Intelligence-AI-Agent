"""Submit a recording or transcript and follow its progress."""
import time
from datetime import date
from pathlib import Path

import streamlit as st

import components as ui

STEPS = [
    ("queued", "Queued", "Waiting for a free processing slot"),
    ("transcribing", "Transcribing", "Speech to text with speaker separation (audio only)"),
    ("analyzing", "Analyst agent", "Reads the transcript with your policy knowledge base"),
    ("reviewing", "Reviewer agent", "Independently checks every claim against the transcript"),
    ("indexing", "Indexing", "Stores notes and makes the call searchable"),
]
AUDIO_TYPES = ["wav", "mp3", "m4a", "aac", "ogg", "flac", "webm"]


def _sample_defaults(name: str) -> tuple[str, date, str | None]:
    stem = Path(name).stem
    when = date.today()
    for part in stem.split("_"):
        try:
            when = date.fromisoformat(part)
        except ValueError:
            continue
    prefix = {"debt": "debt_collection", "collections": "debt_collection", "sales": "sales",
              "support": "support", "standup": "standup"}.get(stem.split("_")[0])
    return stem.replace("_", " ").capitalize(), when, prefix


def _how_it_works() -> None:
    steps = [
        ("Transcript", "Audio is transcribed with speakers; text is split into numbered lines."),
        ("Rule scan", "Stop-contact, legal, bankruptcy, wrong-party and sensitive-data phrases are flagged."),
        ("Analyst", "Drafts decisions, action items, blockers and compliance findings, citing line numbers."),
        ("Grounding", "Code checks every cited line, copies quotes verbatim and resolves dates."),
        ("Reviewer", "A second agent verifies each claim; unsupported items are pulled."),
        ("Human review", "Anything unclear, risky or needing authority lands in the review queue."),
    ]
    items = "".join(
        f'<div class="ci-step"><div class="ci-step-n">{i}</div><div><div class="ci-step-t">{ui.esc(t)}</div>'
        f'<div class="ci-muted">{ui.esc(d)}</div></div></div>'
        for i, (t, d) in enumerate(steps, start=1)
    )
    st.html(ui.card(f'<div class="ci-card-title">How it works</div>{items}'))


def _track(call_id: str) -> None:
    """Poll the call until it finishes, showing the pipeline stage."""
    order = [s[0] for s in STEPS]
    with st.status("Processing call…", expanded=True) as box:
        line = st.empty()
        current = 0
        for _ in range(240):
            try:
                c = ui.api("GET", f"/calls/{call_id}")
            except ui.ApiError as exc:
                box.update(label=str(exc), state="error")
                return
            status = c["status"]
            if status == "done":
                box.update(label="Analysis complete", state="complete", expanded=False)
                ui.refresh()
                ui.open_call(call_id)
            if status == "failed":
                box.update(label="Processing failed", state="error")
                st.error(c.get("error") or "Unknown error")
                if st.button("Open call", icon=":material/arrow_forward:"):
                    ui.open_call(call_id)
                return
            if status in order:
                current = order.index(status)  # while retrying, keep showing the last active step
            rows = []
            for i, (key, label, desc) in enumerate(STEPS):
                if key == "transcribing" and c["source"] != "audio":
                    continue
                if i < current:
                    mark = ":green[:material/check_circle:]"
                elif i == current:
                    mark = ":blue[:material/progress_activity:]"
                else:
                    mark = ":gray[:material/radio_button_unchecked:]"
                rows.append(f"{mark} **{label}** — {desc}")
            if status.startswith("waiting"):
                rows.append(":orange[:material/schedule:] **Gemini is busy** — the model returned a "
                            "temporary overload error, so the job will retry automatically in a moment.")
            line.markdown("\n\n".join(rows))
            time.sleep(2)
        box.update(label="Still processing. Check the Calls page later.", state="running")


def render() -> None:
    ui.page_header("New analysis", "Upload a call recording or paste a transcript.", eyebrow="Process")

    if pending := st.session_state.pop("tracking", None):
        _track(pending)
        return

    left, right = st.columns([3, 2], gap="large")
    with right:
        samples = sorted(p.name for p in ui.SAMPLES.glob("*.txt"))
        with st.container(border=True):
            st.markdown("**Try a sample**")
            sample = st.selectbox("Sample transcript", ["—"] + samples, label_visibility="collapsed",
                                  help="Fills in the form with a ready-made call")
        _how_it_works()

    title_default, date_default, domain_default = ("", date.today(), None)
    sample_text = ""
    if sample != "—":
        title_default, date_default, domain_default = _sample_defaults(sample)
        sample_text = (ui.SAMPLES / sample).read_text(encoding="utf-8")

    with left:
        with st.form("new-call", border=True):
            st.markdown("**Call details**")
            a, b = st.columns(2)
            title = a.text_input("Title", value=title_default, placeholder="e.g. Settlement call — J. Carter")
            meeting_date = b.date_input("Meeting date", value=date_default,
                                        help="Relative dates like “Friday” are resolved from this date")
            c, d = st.columns(2)
            domain_options = ["Auto-detect"] + ui.DOMAINS
            domain = c.selectbox("Domain", domain_options,
                                 index=domain_options.index(domain_default) if domain_default else 0,
                                 format_func=lambda x: ui.DOMAIN_LABEL.get(x, x),
                                 help="Chooses which compliance policy is applied")
            participants = d.text_input("Participants", placeholder="Marcus (agent), James Carter (consumer)")

            st.markdown("**Input**")
            tab_text, tab_file = st.tabs([":material/notes: Paste transcript", ":material/upload_file: Upload file"])
            with tab_text:
                text = st.text_area("Transcript", value=sample_text, height=300, label_visibility="collapsed",
                                    placeholder="One line per turn, e.g.\nAgent: Hi, this is Marcus…\nConsumer: Yes, this is James.",
                                    key=f"transcript-{sample}")
            with tab_file:
                upload = st.file_uploader("Recording or .txt transcript", type=AUDIO_TYPES + ["txt"],
                                          help="Audio is transcribed with Gemini. Max 200 MB.")
                st.caption("If a file is uploaded, it is used instead of the pasted text.")
            submitted = st.form_submit_button("Analyze call", type="primary", icon=":material/auto_awesome:",
                                              width="stretch")

    if not submitted:
        return
    data = {"meeting_date": meeting_date.isoformat(), "title": title.strip()}
    if domain != "Auto-detect":
        data["domain"] = domain
    if participants.strip():
        data["participants"] = participants.strip()
    files = None
    if upload is not None:
        files = {"file": (upload.name, upload.getvalue(), upload.type or "application/octet-stream")}
    elif text.strip():
        data["transcript"] = text
    else:
        left.warning("Paste a transcript or upload a file first.", icon=":material/warning:")
        return
    created = ui.call_api("POST", "/calls", data=data, files=files)
    ui.refresh()
    st.session_state["tracking"] = created["id"]
    st.rerun()
