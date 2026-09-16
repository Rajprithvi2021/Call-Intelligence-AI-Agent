"""Streamlit front end for the Call Intelligence API.

    python scripts/run_ui.py      (or: streamlit run ui/streamlit_app.py)
"""
import streamlit as st

st.set_page_config(page_title="Call Intelligence", page_icon=":material/graphic_eq:", layout="wide")

import components as ui  # noqa: E402
from nav import PAGES  # noqa: E402

ui.inject_css()

with st.sidebar:
    st.html('<div class="ci-brand"><div class="ci-brand-logo">'
            '<span class="material-symbols-rounded">graphic_eq</span></div>'
            '<div><div class="ci-brand-name">Call Intelligence</div>'
            '<div class="ci-muted">Grounded call notes</div></div></div>')
    st.text_input("Reviewer name", key="reviewer", placeholder="Your name",
                  icon=":material/badge:", help="Recorded on every review decision")
    st.divider()
    info = ui.health()
    if info:
        st.html('<div class="ci-row"><span class="ci-health" style="background:#059669"></span>'
                '<b>API connected</b></div>')
        st.caption(
            f"**Storage** {info['store']}  \n"
            f"**Transcription** {info['transcription'].split(':', 1)[-1]}  \n"
            f"**Analyst** {info['analyst_model']}  \n"
            f"**Reviewer** {info['judge_model']}  \n"
            f"**Search** {'keyword + semantic' if info['embeddings'] != 'disabled' else 'keyword'}"
        )
    else:
        st.html('<div class="ci-row"><span class="ci-health" style="background:#dc2626"></span>'
                '<b>API unreachable</b></div>')
        st.caption(f"Expected at `{ui.API}`. Start it with `python -m app.api`.")
    if st.button("Refresh data", icon=":material/refresh:", type="tertiary"):
        ui.health.clear()
        ui.refresh()
        st.rerun()

st.navigation(PAGES, position="top").run()
