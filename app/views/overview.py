"""How big the landscape is: the four counts and the date they stop at."""

import streamlit as st

from analysis import overview
from analysis.volume import COVERAGE_START
from app.session import open_database


@st.cache_data
def corpus_totals(_con, since=COVERAGE_START):
    """Cached passthrough to analysis.overview.

    The leading underscore is Streamlit's opt-out from hashing an argument: a
    connection is not hashable and is not part of the cache key. `since` has
    no underscore and is, so a different coverage floor is a different entry
    rather than a stale hit.
    """
    return overview.corpus_totals(_con, since)


def page():
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
