"""Call list and the call detail view."""
import json
import time

import streamlit as st

import components as ui
from views.review import review_card


# --------------------------------------------------------------------------- list

def render_list() -> None:
    ui.page_header("Calls", "Every analysed call. Select one to see its notes, evidence and review items.",
                   eyebrow="Library")
    try:
        all_calls = ui.calls()
    except ui.ApiError as exc:
        st.error(str(exc), icon=":material/cloud_off:")
        return
    if not all_calls:
        ui.empty_state("No calls yet", "Process a call on the New analysis page.", "call")
        return

    f1, f2, f3 = st.columns([3, 2, 2], vertical_alignment="bottom")
    query = f1.text_input("Filter", placeholder="Title or topic", label_visibility="collapsed",
                          icon=":material/filter_list:")
    domains = f2.multiselect("Domain", ui.DOMAINS, format_func=ui.DOMAIN_LABEL.get, placeholder="All domains",
                             label_visibility="collapsed")
    status = f3.segmented_control("Status", ["All", "Done", "Processing", "Failed"], default="All",
                                  label_visibility="collapsed")

    def keep(c: dict) -> bool:
        text = f"{c['title']} {c.get('tag') or ''}".lower()
        if query and query.lower() not in text:
            return False
        if domains and c.get("domain") not in domains:
            return False
        if status == "Done":
            return c["status"] == "done"
        if status == "Failed":
            return c["status"] == "failed"
        if status == "Processing":
            return c["status"] not in ("done", "failed")
        return True

    shown = [c for c in all_calls if keep(c)]
    if not shown:
        st.info("No calls match these filters.")
        return
    st.caption(f"{len(shown)} of {len(all_calls)} calls · click a title to open it")
    ui.call_rows(shown)


# --------------------------------------------------------------------------- detail

def _back() -> None:
    if st.button("All calls", icon=":material/arrow_back:", type="tertiary"):
        from nav import CALLS
        st.switch_page(CALLS)


def _hero(c: dict, notes: dict, open_count: int) -> None:
    s = notes["sentiment"]
    chips = [ui.pill(ui.DOMAIN_LABEL.get(notes["domain"], notes["domain"]), "indigo"),
             ui.pill(f"Sentiment: {s['overall']}", ui.SENTIMENT_TONE[s["overall"]])]
    if s["customer_angry"]:
        chips.append(ui.pill("Angry customer", "red"))
    if s["profanity"]:
        chips.append(ui.pill("Profanity", "red"))
    chips += [ui.pill(ui.RISK_LABEL.get(f["type"], f["type"]), "red") for f in notes["risk_flags"]]
    chips.append(ui.pill(f"{open_count} to review", "amber" if open_count else "green"))
    models = notes.get("models") or {}
    meta = (f'{ui.esc(c["title"])} · {ui.esc(c["meeting_date"])} · {ui.esc(c["source"])} · '
            f'analyst {ui.esc(models.get("analyst", "—"))} · reviewer {ui.esc(models.get("judge", "—"))}')
    st.html(
        f'<div class="ci-hero"><div class="ci-eyebrow">Call summary</div>'
        f'<div class="ci-hero-tag">{ui.esc(notes["tag"])}</div>'
        f'<div>{"".join(chips)}</div>'
        f'<div class="ci-summary">{ui.esc(notes["summary"])}</div>'
        f'<div class="ci-muted" style="margin-top:10px">{meta}</div></div>'
    )


def _show_button(call_id: str, item_id: str, lines: list[int]) -> None:
    key = f"hl-{call_id}"
    active = st.session_state.get(key, (None, []))[0] == item_id
    label = "Showing in transcript" if active else "Show in transcript"
    if st.button(label, key=f"show-{call_id}-{item_id}", icon=":material/my_location:",
                 type="primary" if active else "secondary", disabled=not lines):
        st.session_state[key] = (None, []) if active else (item_id, lines)
        st.rerun()


def _item_card(call_id: str, item: dict, title: str, meta: str = "", locate: bool = True) -> None:
    with st.container(border=True):
        st.html(
            f'<div class="ci-row" style="justify-content:space-between">'
            f'<span class="ci-pill ci-gray">{ui.esc(item["id"])}</span>'
            f'<span>{ui.verdict_pill(item.get("judgement"))} {ui.confidence_bar(item["confidence"])}</span></div>'
            f'<div class="ci-card-title" style="margin-top:6px">{ui.esc(title)}</div>'
            + (f'<div class="ci-row">{meta}</div>' if meta else "")
        )
        a, b = st.columns([1, 1]) if locate else (st.container(), None)
        with a:
            with st.popover("Evidence", icon=":material/format_quote:", width="stretch"):
                st.html(ui.evidence_html(item["evidence"]))
                if item.get("judgement"):
                    st.caption(f"Reviewer: {item['judgement']['reason']}")
        if b is not None:
            with b:
                _show_button(call_id, item["id"], [e["line"] for e in item["evidence"]])


def _action_meta(a: dict) -> str:
    owner = (f'<span class="ci-kv">Owner <b>{ui.esc(a["owner"])}</b> ({ui.esc(a["owner_role"])})</span>'
             if a["owner"] else ui.pill("No owner", "red"))
    if a["due_date"]:
        due = f'<span class="ci-kv">Due <b>{ui.esc(a["due_date"])}</b></span>'
        if a["due_date_phrase"]:
            due += f' <span class="ci-muted">“{ui.esc(a["due_date_phrase"])}”</span>'
    elif a["date_status"] == "vague":
        due = ui.pill(f"Vague: {a['due_date_phrase']}", "amber")
    else:
        due = '<span class="ci-kv">Due <b>not stated</b></span>'
    note = f'<span class="ci-muted">Check: {ui.esc(a["date_note"])}</span>' if a.get("date_note") else ""
    return owner + due + note


def _section(title: str, icon: str, count: int) -> None:
    st.markdown(f"#### :material/{icon}: {title} &nbsp;<span class='ci-pill ci-gray'>{count}</span>",
                unsafe_allow_html=True)


def _notes_tab(call_id: str, c: dict, notes: dict) -> None:
    left, right = st.columns([11, 9], gap="large")
    with left:
        _section("Action items", "task_alt", len(notes["action_items"]))
        if not notes["action_items"]:
            st.caption("No commitments were made on this call.")
        for a in notes["action_items"]:
            _item_card(call_id, a, a["description"], _action_meta(a))

        _section("Decisions", "gavel", len(notes["decisions"]))
        if not notes["decisions"]:
            st.caption("No decisions recorded.")
        for d in notes["decisions"]:
            _item_card(call_id, d, d["text"])

        _section("Blockers", "block", len(notes["blockers"]))
        if not notes["blockers"]:
            st.caption("Nothing blocking.")
        for b in notes["blockers"]:
            _item_card(call_id, b, b["text"])

        _section("Suggested next steps", "lightbulb", len(notes["next_steps"]))
        st.caption("Proposals from the analyst. Nobody has committed to these.")
        for n in notes["next_steps"]:
            _item_card(call_id, n, n["text"])

    with right:
        item_id, lines = st.session_state.get(f"hl-{call_id}", (None, []))
        head, clear = st.columns([3, 1], vertical_alignment="center")
        head.markdown("#### :material/forum: Transcript")
        if item_id and clear.button("Clear", key=f"clear-{call_id}", icon=":material/close:", type="tertiary"):
            st.session_state[f"hl-{call_id}"] = (None, [])
            st.rerun()
        if item_id:
            st.info(f"Highlighting evidence for **{item_id}** (lines {', '.join(map(str, lines))})",
                    icon=":material/my_location:")
        with st.container(height=900, border=True):
            st.html(ui.transcript_html(c["transcript"], notes["speaker_roles"], set(lines)))


def _risk_tab(call_id: str, notes: dict) -> None:
    comp = notes["compliance"]
    counts = {r: sum(1 for x in comp if x["rating"] == r) for r in ("RED", "YELLOW", "GREEN")}
    m = st.columns(4)
    m[0].metric("Red findings", counts["RED"])
    m[1].metric("Yellow findings", counts["YELLOW"])
    m[2].metric("Green checks", counts["GREEN"])
    m[3].metric("Risk flags", len(notes["risk_flags"]))

    left, right = st.columns([3, 2], gap="large")
    with left:
        _section("Compliance", "policy", len(comp))
        if not comp:
            st.caption("No policy observations.")
        for x in sorted(comp, key=lambda x: {"RED": 0, "YELLOW": 1, "GREEN": 2}[x["rating"]]):
            _item_card(call_id, x, x["observation"],
                       f'{ui.pill(x["rating"], ui.RATING_TONE[x["rating"]])}'
                       f'<span class="ci-kv">Rule <b>{ui.esc(x["rule_id"])}</b></span>', locate=False)
    with right:
        _section("Risk flags", "warning", len(notes["risk_flags"]))
        if not notes["risk_flags"]:
            st.caption("No stop-contact, legal, bankruptcy, wrong-party or sensitive-data signals.")
        for f in notes["risk_flags"]:
            st.html(ui.card(
                f'<div class="ci-row">{ui.pill(ui.RISK_LABEL.get(f["type"], f["type"]), "red")}'
                f'<span class="ci-muted">detected by {ui.esc(f["source"])}</span></div>'
                f'<div style="margin-top:6px">{ui.esc(f["description"])}</div>{ui.evidence_html(f["evidence"])}',
                accent="red"))

        s = notes["sentiment"]
        _section("Sentiment", "mood", 1)
        st.html(ui.card(
            f'<div class="ci-row">{ui.pill(s["overall"].capitalize(), ui.SENTIMENT_TONE[s["overall"]])}'
            f'{ui.pill("Angry customer", "red") if s["customer_angry"] else ui.pill("Calm customer", "green")}'
            f'{ui.pill("Profanity", "red") if s["profanity"] else ui.pill("No profanity", "green")}</div>'
            f'{ui.evidence_html(s["evidence"])}'))


def _transcript_tab(c: dict, notes: dict) -> None:
    q = st.text_input("Find in transcript", placeholder="Type a word to highlight it",
                      icon=":material/search:", key=f"find-{c['id']}")
    lines = c["transcript"]
    if q:
        hits = [l for l in lines if q.lower() in l["text"].lower()]
        st.caption(f"{len(hits)} matching line(s)")
    st.html(ui.transcript_html(lines, notes["speaker_roles"], query=q))


def _export_tab(c: dict, notes: dict) -> None:
    a, b = st.columns(2)
    a.download_button("Download notes (JSON)", json.dumps(notes, indent=2), file_name=f"call-{c['id']}-notes.json",
                      mime="application/json", icon=":material/data_object:", width="stretch")
    text = "\n".join(f"[{l['n']}] {l['speaker']}: {l['text']}" for l in c["transcript"])
    b.download_button("Download transcript (TXT)", text, file_name=f"call-{c['id']}-transcript.txt",
                      icon=":material/description:", width="stretch")
    st.json(notes, expanded=1)


def render_detail() -> None:
    call_id = st.query_params.get("id")
    _back()
    if not call_id:
        st.info("No call selected.")
        return
    try:
        c = ui.call(call_id)
    except ui.ApiError as exc:
        st.error(str(exc), icon=":material/error:")
        return

    if c["status"] in ui.PROCESSING or c["status"].startswith("waiting"):
        ui.page_header(c["title"], eyebrow="Processing")
        st.html(f'<div class="ci-row">{ui.status_pill(c["status"])}'
                f'<span class="ci-muted">This page refreshes automatically.</span></div>')
        time.sleep(2)
        ui.call.clear()
        st.rerun()

    if c["status"] == "failed":
        ui.page_header(c["title"], eyebrow="Failed")
        st.error(c.get("error") or "Processing failed", icon=":material/error:")
        if st.button("Retry analysis", type="primary", icon=":material/refresh:"):
            ui.call_api("POST", f"/calls/{call_id}/retry")
            ui.refresh()
            st.rerun()
        return

    notes = c["notes"]
    open_reviews = [r for r in c["reviews"] if r["status"] == "open"]
    _hero(c, notes, len(open_reviews))

    m = st.columns(5)
    m[0].metric("Action items", len(notes["action_items"]))
    m[1].metric("Decisions", len(notes["decisions"]))
    m[2].metric("Blockers", len(notes["blockers"]))
    m[3].metric("Open reviews", len(open_reviews))
    m[4].metric("Confidence", f"{round(notes['overall_confidence'] * 100)}%")

    tabs = st.tabs([
        ":material/checklist: Notes",
        ":material/shield: Compliance & risk",
        f":material/fact_check: Review ({len(open_reviews)})",
        ":material/forum: Transcript",
        ":material/download: Export",
    ])
    with tabs[0]:
        _notes_tab(call_id, c, notes)
    with tabs[1]:
        _risk_tab(call_id, notes)
    with tabs[2]:
        if not c["reviews"]:
            st.success("Nothing on this call needs human review.", icon=":material/verified:")
        show = st.segmented_control("Show", ["Open", "Resolved", "All"], default="Open", key=f"rv-filter-{call_id}")
        for r in c["reviews"]:
            if (show == "Open" and r["status"] != "open") or (show == "Resolved" and r["status"] == "open"):
                continue
            review_card(r, key=f"call-{r['id']}")
    with tabs[3]:
        _transcript_tab(c, notes)
    with tabs[4]:
        _export_tab(c, notes)
