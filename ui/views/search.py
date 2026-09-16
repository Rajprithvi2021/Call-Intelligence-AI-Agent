"""Keyword + semantic search across transcripts."""
from itertools import groupby

import streamlit as st

import components as ui

SUGGESTIONS = ["attorney", "stop calling", "supervisor approval", "refund", "wrong number", "blocked"]


def _use_suggestion() -> None:
    if choice := st.session_state.get("search-pills"):
        st.session_state["search-q"] = choice
    st.session_state["search-pills"] = None


def render() -> None:
    ui.page_header("Search", "Find what was said across every call, by keyword or by meaning.", eyebrow="Explore")

    with st.form("search", border=True):
        a, b = st.columns([5, 1], vertical_alignment="bottom")
        q = a.text_input("Query", key="search-q", label_visibility="collapsed", icon=":material/search:",
                         placeholder='Try "they will take us to court" or "attorney"')
        b.form_submit_button("Search", type="primary", width="stretch")
        c1, c2, c3 = st.columns(3)
        domain = c1.selectbox("Domain", ["any"] + ui.DOMAINS,
                              format_func=lambda d: "Any domain" if d == "any" else ui.DOMAIN_LABEL[d])
        flag = c2.selectbox("Risk flag", ["any"] + list(ui.RISK_LABEL),
                            format_func=lambda f: "Any risk flag" if f == "any" else ui.RISK_LABEL[f])
        sentiment = c3.selectbox("Sentiment", ["any", "positive", "neutral", "negative"],
                                 format_func=lambda s: "Any sentiment" if s == "any" else s.capitalize())

    st.pills("Suggestions", SUGGESTIONS, label_visibility="collapsed", key="search-pills", on_change=_use_suggestion)

    filters = {k: v for k, v in (("domain", domain), ("flag", flag), ("sentiment", sentiment)) if v != "any"}
    if not q.strip() and not filters:
        ui.empty_state("Search your calls", "Type a phrase or pick a filter. Paraphrases work too.", "manage_search")
        return

    res = ui.call_api("GET", "/search", params={"q": q, **filters, "limit": 40})
    results = res["results"]
    mode = "keyword + semantic" if res["semantic"] else "keyword"
    st.caption(f"{len(results)} result(s) · {mode} search")
    if not results:
        ui.empty_state("No matches", "Try different words or remove a filter.", "search_off")
        return

    order = list(dict.fromkeys(r["call_id"] for r in results))
    grouped = {k: list(v) for k, v in groupby(sorted(results, key=lambda r: order.index(r["call_id"])),
                                              key=lambda r: r["call_id"])}
    for call_id in order:
        hits = grouped[call_id]
        first = hits[0]
        with st.container(border=True):
            head, btn = st.columns([6, 1], vertical_alignment="center")
            head.html(f'<div class="ci-card-title" style="margin:0">{ui.esc(first["title"])}</div>'
                      f'<div class="ci-muted">{ui.esc(first.get("tag") or "")} · {len(hits)} match(es)</div>')
            if btn.button("Open", key=f"search-open-{call_id}", icon=":material/arrow_forward:", width="stretch"):
                ui.open_call(call_id)
            rows = "".join(
                f'<div class="ci-quote"><span class="ci-ln">{"L" + str(h["line"]) if h["line"] else "—"}</span>'
                f'<span class="ci-spk">{ui.esc(h["speaker"] or "Summary")}</span>{ui.highlight_terms(h["text"], q)}</div>'
                for h in sorted(hits, key=lambda h: h["line"] or 0)
            )
            st.html(f'<div class="ci-quotes">{rows}</div>')
