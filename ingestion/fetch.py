"""Fetch studies from the REEC API.

Two list endpoints, used for different purposes (see PROJECT_SPEC.md 3.1):
  - getestudios/{fecha}: unbounded "since date" fetch, used for incremental
    updates after the initial historical backfill.
  - estudios?fechadesde&fechahasta: bounded date-range fetch (~1yr cap,
    enforced by the API), used for the year-by-year historical backfill.
"""

import datetime as dt

import requests

GETESTUDIOS_URL = "https://reec.aemps.es/reec-services/json/getestudios"
ESTUDIOS_URL = "https://reec.aemps.es/reec-services/estudios"


def fetch_since(since: dt.date) -> dict:
    """Fetch all studies authorized/modified since `since` (inclusive).

    Returns the raw parsed response: a dict with a single "estudio" key
    holding the list of studies.
    """
    url = f"{GETESTUDIOS_URL}/{since.strftime('%d-%m-%Y')}"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_year(year: int) -> dict:
    """Fetch all studies registered in `year` (01/01 through 31/12).

    Returns the raw parsed response: a dict with a single "estudio" key
    holding the list of studies.
    """
    params = {
        "fechadesde": f"01/01/{year}",
        "fechahasta": f"31/12/{year}",
    }
    response = requests.get(
        ESTUDIOS_URL, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=60
    )
    response.raise_for_status()
    return response.json()
