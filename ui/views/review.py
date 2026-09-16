"""Human review queue."""
from collections import Counter

import streamlit as st

import components as ui

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
SOURCE_LABEL = {"rule": "rule", "analyst": "analyst agent", "reviewer": "reviewer agent",
                "escalation": "escalation policy", "grounding": "grounding check"}


def review_card(r: dict, key: str, show_call: bool = False) -> None:
    """One review item with approve / reject / edit actions."""
    tone = ui.SEVERITY_TONE[r["severity"]]
    with st.container(border=True):
        call_ref = (f'<span class="ci-muted">{ui.esc(r.get("call_title"))} · {ui.esc(r.get("meeting_date"))}</span>'
                    if show_call else "")
        st.html(
            f'<div style="border-left:4px solid var(--ci-{tone});padding-left:12px">'
            f'<div class="ci-row">{ui.pill(r["severity"].upper(), tone)}'
            f'{ui.pill(r["category"].replace("_", " "), "gray")}'
            f'<span class="ci-muted">item {ui.esc(r["item_ref"])} · via {ui.esc(SOURCE_LABEL.get(r["source"], r["source"]))}</span>'
            f'{call_ref}</div>'
            f'<div style="margin:8px 0 2px;font-size:.95rem;line-height:1.5">{ui.esc(r["reason"])}</div>'
            f'{ui.evidence_html(r["evidence"]) if r.get("evidence") else ""}</div>'
        )
        if r["status"] != "open":
            who = r.get("resolver") or "unknown reviewer"
            note = f" — “{r['resolution_note']}”" if r.get("resolution_note") else ""
            st.caption(f":material/check_circle: {r['status'].capitalize()} by {who}{note}")
            return

        cols = st.columns([1, 1, 1, 1.2] if show_call else [1, 1, 1, 0.01])
        if cols[0].button("Approve", key=f"ok-{key}", icon=":material/check:", width="stretch"):
            ui.resolve_review(r["id"], "approved")
            st.rerun()
        if cols[1].button("Reject", key=f"no-{key}", icon=":material/close:", width="stretch"):
            ui.resolve_review(r["id"], "rejected")
            st.rerun()
        with cols[2].popover("Edit & note", icon=":material/edit_note:", width="stretch"):
            note = st.text_area("What did you change or decide?", key=f"note-{key}", height=100)
            if st.button("Save", key=f"save-{key}", type="primary", disabled=not note.strip()):
                ui.resolve_review(r["id"], "edited", note)
                st.rerun()
        if show_call and cols[3].button("Open call", key=f"open-{key}", icon=":material/arrow_forward:",
                                        type="tertiary", width="stretch"):
            ui.open_call(r["call_id"])


def render() -> None:
    ui.page_header("Review queue", "Items the system would not assert on its own: check them, then approve, reject or edit.",
                   eyebrow="Human in the loop")
    if not st.session_state.get("reviewer"):
        st.info("Add your name in the sidebar so decisions are signed.", icon=":material/badge:")

    status = st.segmented_control("Status", ["open", "approved", "rejected", "edited"], default="open",
                                  format_func=str.capitalize, label_visibility="collapsed")
    try:
        items = ui.reviews(status or "open")
    except ui.ApiError as exc:
        st.error(str(exc), icon=":material/cloud_off:")
        return

    sev = Counter(r["severity"] for r in items)
    m = st.columns(4)
    m[0].metric("Items", len(items))
    m[1].metric("High", sev.get("high", 0))
    m[2].metric("Medium", sev.get("medium", 0))
    m[3].metric("Low", sev.get("low", 0))

    f1, f2, f3 = st.columns([2, 2, 3], vertical_alignment="bottom")
    severities = f1.pills("Severity", ["high", "medium", "low"], selection_mode="multi",
                          format_func=str.capitalize, default=[])
    categories = sorted({r["category"] for r in items})
    category = f2.selectbox("Category", ["All categories"] + categories,
                            format_func=lambda c: c.replace("_", " ").capitalize())
    text = f3.text_input("Search", placeholder="Search reasons or call titles", icon=":material/search:")

    shown = [
        r for r in items
        if (not severities or r["severity"] in severities)
        and (category == "All categories" or r["category"] == category)
        and (not text or text.lower() in f"{r['reason']} {r.get('call_title', '')}".lower())
    ]
    shown.sort(key=lambda r: (SEVERITY_ORDER[r["severity"]], r.get("meeting_date") or ""))

    if not shown:
        ui.empty_state("All clear" if status == "open" else "Nothing here",
                       "No review items match these filters.", "task_alt")
        return
    st.caption(f"Showing {len(shown)} of {len(items)}")
    for r in shown:
        review_card(r, key=f"queue-{r['id']}", show_call=True)
