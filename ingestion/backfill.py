"""Year-by-year historical backfill of REEC study data.

Loops from `start_year` through `end_year` inclusive, fetching each year via
the estudios endpoint (bounded date range) and caching it to disk — skipping
years already cached, so a re-run only fetches what's missing.
"""

from pathlib import Path

from ingestion.cache import DEFAULT_RAW_DIR, is_cached, save_year
from ingestion.fetch import fetch_year


def run_backfill(
    start_year: int, end_year: int, raw_dir: Path = DEFAULT_RAW_DIR
) -> None:
    for year in range(start_year, end_year + 1):
        if is_cached(year, raw_dir):
            continue
        data = fetch_year(year)
        save_year(year, data, raw_dir)
