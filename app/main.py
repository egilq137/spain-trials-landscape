"""Streamlit dashboard -- the third composition root.

The siblings are run_pipeline.py (raw files in, database out) and
run_analysis.py (database in, chart files out). Like them, this file wires the
pieces together and does nothing else; unlike them, it renders instead of
writing. It does not import run_analysis -- two entrypoints sharing a
connection helper would make the helper a fourth thing to keep in step.

app/ is presentation only. No SQL and no counting rule lives here: every
number on every page comes from analysis/, which is where it can be tested.

Pages are declared as callables rather than discovered from a `pages/`
directory. Discovery by filename would mean the navigation order, the page
titles and the module layout are all the same decision, and none of them
would be stated anywhere; this way the page list is a list.

Run with:
    streamlit run app/main.py
"""

import streamlit as st

from app.views import geography, overview


def main():
    st.set_page_config(page_title="Spain clinical trials landscape",
                       layout="wide")
    # url_path is explicit because every view's entry point is called page(),
    # and Streamlit would otherwise infer the same pathname for all of them.
    st.navigation([
        st.Page(overview.page, title="Overview", icon=":material/dashboard:",
                url_path="overview", default=True),
        st.Page(geography.page, title="Geography", icon=":material/map:",
                url_path="geography"),
    ]).run()


if __name__ == "__main__":
    main()
