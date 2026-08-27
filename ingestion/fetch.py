"""Fetch studies from the REEC API.

Phase 1.1: minimal fetch against getestudios/{fecha} — returns all studies
authorized/modified since the given date, no upper bound.
"""

import datetime as dt

import requests

BASE_URL = "https://reec.aemps.es/reec-services/json/getestudios"


def fetch_since(since: dt.date) -> dict:
    """Fetch all studies authorized/modified since `since` (inclusive).

    Returns the raw parsed response: a dict with a single "estudio" key
    holding the list of studies.
    """
    url = f"{BASE_URL}/{since.strftime('%d-%m-%Y')}"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return response.json()
