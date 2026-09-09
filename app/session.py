"""The one connection the app shares, and the only file that knows where it is.

Split out of main.py so that a view can read the database without importing
the navigation that renders it -- main.py imports views, so a view importing
main.py back would be a cycle.

Nothing else belongs here. Cached query wrappers live beside the view that
asks the question, so that adding a page never means editing a shared file.
"""

import sqlite3
from pathlib import Path

import streamlit as st

DEFAULT_DB = Path("data") / "trials.db"
GEO_DIR = Path("data") / "geo"


@st.cache_resource
def open_database(path=DEFAULT_DB):
    """One read-only connection for the session.

    Read-only for the same reason run_analysis.py is: a dashboard has no
    business writing to the database, and `mode=ro` makes that a property of
    the connection rather than a promise. Cached because Streamlit re-runs the
    script on every widget interaction, and reconnecting per click would
    reopen the file for every click.

    check_same_thread=False because Streamlit serves reruns from a thread
    pool, and the connection outlives the thread that opened it.
    """
    return sqlite3.connect(
        "file:{}?mode=ro".format(Path(path).as_posix()),
        uri=True, check_same_thread=False)
