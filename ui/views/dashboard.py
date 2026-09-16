"""Overview: volumes, what needs attention, risk mix, recent calls."""
from collections import Counter

import streamlit as st

import components as ui


def _details(done: list[dict]) -> list[dict]:
    out = []
    for c in done:
        try:
            out.append(ui.call(c["id"]))
        except ui.ApiError:
            continue
    return out


def render() -> None:
    try:
        all_calls = ui.calls()
        open_items = ui.reviews("open")
    except ui.ApiError as exc:
        st.error(str(exc), icon=":material/cloud_off:")
        return

    head, action = st.columns([5, 1], vertical_alignment="bottom")
    with head:
        ui.page_header("Call intelligence", "Grounded notes, compliance checks and a human-review queue for every call.",
                       eyebrow="Overview")
    with action:
        if st.button("New analysis", icon=":material/add:", type="primary", width="stretch"):
            from nav import PROCESS
            st.switch_page(PROCESS)

    if not all_calls:
        ui.empty_state("No calls analysed yet",
                       "Start with a sample transcript or upload a recording on the New analysis page.", "graphic_eq")
        return

    done = [c for c in all_calls if c["status"] == "done"]
    details = _details(done)
    notes = [d["notes"] for d in details if d.get("notes")]
    high = [r for r in open_items if r["severity"] == "high"]
    flagged = sum(1 for n in notes if n["risk_flags"])
    actions = sum(len(n["action_items"]) for n in notes)
    in_flight = sum(1 for c in all_calls if c["status"] in ui.PROCESSING or c["status"].startswith("waiting"))
    failed = sum(1 for c in all_calls if c["status"] == "failed")

    k = st.columns(5)
    k[0].metric("Calls analysed", len(done), help="Completed calls",
                delta=f"{in_flight} in progress" if in_flight else None, delta_color="off")
    k[1].metric("Open reviews", len(open_items), help="Items waiting for a human decision")
    k[2].metric("High severity", len(high), help="Open review items marked high")
    k[3].metric("Risky calls", flagged, help="Stop-contact, legal, bankruptcy, wrong party, sensitive data")
    k[4].metric("Action items", actions, help="Grounded commitments across all calls",
                delta=f"{failed} failed" if failed else None, delta_color="inverse" if failed else "off")

    st.space("small")
    left, right = st.columns([3, 2], gap="large")

    with left:
        st.subheader("Needs attention")
        queue = sorted(open_items, key=lambda r: {"high": 0, "medium": 1, "low": 2}[r["severity"]])[:6]
        if not queue:
            st.success("Nothing is waiting for review.", icon=":material/verified:")
        for r in queue:
            with st.container(border=True):
                a, b = st.columns([6, 1], vertical_alignment="center")
                a.html(
                    f'<div class="ci-row">{ui.pill(r["severity"].upper(), ui.SEVERITY_TONE[r["severity"]])}'
                    f'{ui.pill(r["category"].replace("_", " "), "gray")}'
                    f'<span class="ci-muted">{ui.esc(r.get("call_title"))} · {ui.esc(r.get("meeting_date"))}</span></div>'
                    f'<div style="margin-top:6px">{ui.esc(r["reason"])}</div>'
                )
                if b.button(":material/arrow_forward:", key=f"dash-open-{r['id']}", help="Open call"):
                    ui.open_call(r["call_id"])
        if len(open_items) > len(queue):
            if st.button(f"View all {len(open_items)} open items", icon=":material/fact_check:", type="tertiary"):
                from nav import REVIEW
                st.switch_page(REVIEW)

    with right:
        st.subheader("Risk signals")
        risk = Counter(ui.RISK_LABEL.get(f["type"], f["type"]) for n in notes for f in n["risk_flags"])
        if risk:
            with st.container(border=True):
                st.html(ui.bars_html(sorted(risk.items(), key=lambda kv: -kv[1])))
        else:
            st.caption("No risk flags yet.")

        st.subheader("Sentiment")
        mood = Counter(n["sentiment"]["overall"] for n in notes)
        angry = sum(1 for n in notes if n["sentiment"]["customer_angry"])
        swearing = sum(1 for n in notes if n["sentiment"]["profanity"])
        s = st.columns(3)
        s[0].metric("Positive", mood.get("positive", 0))
        s[1].metric("Neutral", mood.get("neutral", 0))
        s[2].metric("Negative", mood.get("negative", 0))
        st.caption(f"Angry customer on {angry} call(s) · profanity on {swearing} call(s)")

    st.subheader("Recent calls")
    ui.call_rows(all_calls[:8])
    if len(all_calls) > 8:
        from nav import CALLS
        st.page_link(CALLS, label=f"View all {len(all_calls)} calls", icon=":material/arrow_forward:")
