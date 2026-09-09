"""Streamlit dashboard -- the third composition root.

The siblings are run_pipeline.py (raw files in, database out) and
run_analysis.py (database in, chart files out). Like them, this file is the
only one in its path that knows where the database lives; unlike them, it
renders instead of writing. It does not import run_analysis -- two entrypoints
sharing a connection helper would make the helper a fourth thing to keep in
step, and it is two lines.

app/ is presentation only. No SQL and no counting rule lives here: every
number on the page comes from analysis/, which is where it can be tested.

Run with:
    streamlit run app/main.py
"""

import sqlite3
from pathlib import Path

import streamlit as st

from analysis import overview
from analysis.volume import COVERAGE_START

DEFAULT_DB = Path("data") / "trials.db"


@st.cache_resource
def open_database(path=DEFAULT_DB):
    """One read-only connection for the session.

    Read-only for the same reason run_analysis.py is: a dashboard has no
    business writing to the database, and `mode=ro` makes that a property of
    the connection rather than a promise. Cached because Streamlit re-runs
    this whole file on every widget interaction, and reconnecting each time
    would reopen the file for every click.

    check_same_thread=False because Streamlit serves reruns from a thread
    pool, and the connection outlives the thread that opened it.
    """
    return sqlite3.connect(
        "file:{}?mode=ro".format(Path(path).as_posix()),
        uri=True, check_same_thread=False)


@st.cache_data
def corpus_totals(_con, since=COVERAGE_START):
    """Cached passthrough to analysis.overview.

    The leading underscore is Streamlit's opt-out from hashing an argument: a
    connection is not hashable and is not part of the cache key. `since` has
    no underscore and is, so a different coverage floor is a different entry
    rather than a stale hit.
    """
    return overview.corpus_totals(_con, since)


def main():
    st.set_page_config(page_title="Spain clinical trials landscape",
                       layout="wide")
    totals = corpus_totals(open_database())

    st.title("Spain clinical trials landscape")

    # Unequal widths: the four counts are short, and the data cut is a full
    # ISO date at the same font size. On five equal columns it truncates to
    # "2026-08...", which is a provenance note that no longer states the
    # month it is about.
    cards = st.columns([1, 1, 1, 1.2, 1.5])
    for column, (label, value) in zip(cards, [
            ("Trials", "{:,}".format(totals.trials)),
            ("Sponsors", "{:,}".format(totals.sponsors)),
            ("Centres", "{:,}".format(totals.centres)),
            ("Therapeutic areas", "{:,}".format(totals.areas)),
            ("Data cut", totals.data_cut)]):
        column.metric(label, value)

    # The row states its own counting rule, the same way every chart in
    # docs/charts/ states its subtitle. Without it the four counts read as
    # "what the registry holds", which is a different and larger corpus.
    st.caption(
        "Trials authorised in Spain from {}, REEC's coverage boundary; "
        "earlier records are excluded from every figure here. Sponsors, "
        "centres and therapeutic areas are counted over those trials, not "
        "over the registry's tables.".format(COVERAGE_START))


if __name__ == "__main__":
    main()
