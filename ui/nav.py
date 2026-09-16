"""Page registry, importable from any view (for st.switch_page)."""
import streamlit as st

from views import calls, dashboard, process, review, search

DASHBOARD = st.Page(dashboard.render, title="Dashboard", icon=":material/space_dashboard:", url_path="dashboard", default=True)
PROCESS = st.Page(process.render, title="New analysis", icon=":material/add_circle:", url_path="new")
CALLS = st.Page(calls.render_list, title="Calls", icon=":material/call:", url_path="calls")
CALL_PAGE = st.Page(calls.render_detail, title="Call", icon=":material/description:", url_path="call", visibility="hidden")
REVIEW = st.Page(review.render, title="Review queue", icon=":material/fact_check:", url_path="review")
SEARCH = st.Page(search.render, title="Search", icon=":material/search:", url_path="search")

PAGES = [DASHBOARD, PROCESS, CALLS, REVIEW, SEARCH, CALL_PAGE]
