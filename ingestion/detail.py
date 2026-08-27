"""Per-study detail enrichment from the REEC detalle endpoint (Phase 1.3).

The list endpoints (see fetch.py) don't carry trial phase, purpose, population
or therapeutic area -- those exist only on detalle/{identificador}, one call per
study. With ~12k studies cached from the backfill that's a multi-hour job, so
this module is built to be run in short sittings and resumed:

  - records append to data/raw/detalle/{year}.jsonl as they arrive, so a run can
    be interrupted at any point and lose at most the study in flight
  - a re-run diffs the list cache against what's already on disk and fetches only
    the difference -- the same command works every day, no arguments
  - each run stops when the current year completes or the time budget expires

Endpoint quirk (verified live, not documented): an unknown identifier returns
HTTP 200 with the plain-text body "El ensayo no existe en el sistema", not a 404
and not JSON. Missing studies are therefore an expected data issue detected from
the body, kept separate from real failures (error pages, network errors).
"""

import datetime as dt
import json
import time
from pathlib import Path

import requests

from ingestion.cache import DEFAULT_RAW_DIR, load_year

DETALLE_URL = "https://reec.aemps.es/reec-services/json/detalle"
NOT_FOUND_BODY = "El ensayo no existe en el sistema"

REQUEST_DELAY = 1.0
REQUEST_TIMEOUT = 30
CONSECUTIVE_FAILURE_LIMIT = 5
DEFAULT_MAX_MINUTES = 60


class StudyNotFound(Exception):
    """The registry has no detail record for this identifier (expected)."""


class DetailFetchError(Exception):
    """Unexpected response: network error, error page, or malformed JSON."""


def detail_path(year: int, raw_dir: Path = DEFAULT_RAW_DIR) -> Path:
    return raw_dir / "detalle" / f"{year}.jsonl"


def failures_path(year: int, raw_dir: Path = DEFAULT_RAW_DIR) -> Path:
    return raw_dir / "detalle" / f"{year}.failures.jsonl"


def cached_years(raw_dir: Path = DEFAULT_RAW_DIR) -> list[int]:
    """Years present in the list cache, newest first."""
    years = [int(p.stem) for p in raw_dir.glob("*.json") if p.stem.isdigit()]
    return sorted(years, reverse=True)


def _recorded_ids(path: Path) -> set[str]:
    """Identifiers already written to a jsonl file, ignoring a truncated tail."""
    if not path.exists():
        return set()
    ids = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                ids.add(json.loads(line)["identificador"])
            except (json.JSONDecodeError, KeyError):
                continue
    return ids


def pending_ids(year: int, raw_dir: Path = DEFAULT_RAW_DIR) -> list[str]:
    """Study ids from the year's list cache with no detail record yet.

    Failed ids count as done here -- retrying them is the job of a separate
    retry pass, not of the next ordinary run.
    """
    done = _recorded_ids(detail_path(year, raw_dir)) | _recorded_ids(
        failures_path(year, raw_dir)
    )
    listed = [s["identificador"] for s in load_year(year, raw_dir).get("estudio", [])]
    return [i for i in listed if i not in done]


def fetch_detail(identificador: str, session: requests.Session) -> dict:
    """Fetch one study's detail record.

    Raises StudyNotFound if the registry has no such study, DetailFetchError if
    the response isn't something we can interpret at all.
    """
    url = f"{DETALLE_URL}/{identificador}"
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DetailFetchError(str(exc)) from exc

    if response.text.strip() == NOT_FOUND_BODY:
        raise StudyNotFound(identificador)
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise DetailFetchError(
            f"unparseable body ({len(response.content)} bytes)"
        ) from exc


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _record_failure(identificador: str, reason: str, path: Path) -> None:
    _append_jsonl(
        path,
        {
            "identificador": identificador,
            "reason": reason,
            "at": dt.datetime.now().isoformat(timespec="seconds"),
        },
    )


def fetch_year_details(
    year: int,
    session: requests.Session,
    raw_dir: Path = DEFAULT_RAW_DIR,
    deadline: float | None = None,
    limit: int | None = None,
    delay: float = REQUEST_DELAY,
) -> dict:
    """Fetch pending detail records for one year, appending as they arrive.

    Stops early when `deadline` (a time.monotonic() value) passes or `limit`
    records have been attempted. Aborts the whole run on too many unexpected
    failures back to back -- that means something is wrong on their end or ours,
    and grinding through thousands more requests would be rude.
    """
    todo = pending_ids(year, raw_dir)
    if limit is not None:
        todo = todo[:limit]
    print(f"{year}: {len(todo)} to fetch")

    stats = {"year": year, "fetched": 0, "missing": 0, "failed": 0, "remaining": 0}
    consecutive_failures = 0

    for position, identificador in enumerate(todo):
        if deadline is not None and time.monotonic() >= deadline:
            stats["remaining"] = len(todo) - position
            print(f"{year}: time budget reached")
            return stats

        try:
            record = fetch_detail(identificador, session)
        except StudyNotFound:
            _record_failure(
                identificador, "not in registry", failures_path(year, raw_dir)
            )
            stats["missing"] += 1
            consecutive_failures = 0
        except DetailFetchError as exc:
            _record_failure(identificador, str(exc), failures_path(year, raw_dir))
            stats["failed"] += 1
            consecutive_failures += 1
            if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                raise DetailFetchError(
                    f"{consecutive_failures} consecutive failures, aborting "
                    f"(last: {exc})"
                )
        else:
            _append_jsonl(detail_path(year, raw_dir), record)
            stats["fetched"] += 1
            consecutive_failures = 0

        if stats["fetched"] and stats["fetched"] % 100 == 0:
            print(f"  {stats['fetched']}/{len(todo)}")
        time.sleep(delay)

    return stats


def coverage(raw_dir: Path = DEFAULT_RAW_DIR) -> list[dict]:
    """Per-year detail coverage against the list cache."""
    rows = []
    for year in cached_years(raw_dir):
        listed = len(load_year(year, raw_dir).get("estudio", []))
        fetched = len(_recorded_ids(detail_path(year, raw_dir)))
        failed = len(_recorded_ids(failures_path(year, raw_dir)))
        rows.append(
            {
                "year": year,
                "listed": listed,
                "fetched": fetched,
                "failed": failed,
                "pending": listed - fetched - failed,
            }
        )
    return rows


def print_coverage(raw_dir: Path = DEFAULT_RAW_DIR) -> None:
    print(f"{'year':>6} {'listed':>8} {'fetched':>8} {'failed':>8} {'pending':>8}")
    for row in coverage(raw_dir):
        print(
            f"{row['year']:>6} {row['listed']:>8} {row['fetched']:>8} "
            f"{row['failed']:>8} {row['pending']:>8}"
        )


def run(
    raw_dir: Path = DEFAULT_RAW_DIR,
    max_minutes: float = DEFAULT_MAX_MINUTES,
    year: int | None = None,
    limit: int | None = None,
    continue_past_year: bool = False,
    delay: float = REQUEST_DELAY,
) -> None:
    """Work through pending detail records, newest year first.

    Stops when the current year finishes or the time budget runs out, whichever
    comes first -- so an interrupted run always leaves a year either complete or
    cleanly partial, never silently half-analysed.
    """
    deadline = time.monotonic() + max_minutes * 60 if max_minutes else None
    years = [year] if year is not None else cached_years(raw_dir)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    for candidate in years:
        if not pending_ids(candidate, raw_dir):
            continue
        stats = fetch_year_details(candidate, session, raw_dir, deadline, limit, delay)
        print(
            f"{candidate}: {stats['fetched']} fetched, {stats['missing']} not in "
            f"registry, {stats['failed']} failed, {stats['remaining']} remaining"
        )
        if stats["remaining"] or limit is not None or not continue_past_year:
            break

    print()
    print_coverage(raw_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch per-study detail records from REEC, resumably."
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=DEFAULT_MAX_MINUTES,
        help="stop after this long; 0 for no limit (default: 60)",
    )
    parser.add_argument("--year", type=int, help="fetch this year only")
    parser.add_argument("--limit", type=int, help="attempt at most N studies (dry run)")
    parser.add_argument(
        "--continue-past-year",
        action="store_true",
        help="keep going into older years until the time budget runs out",
    )
    parser.add_argument("--status", action="store_true", help="print coverage and exit")
    args = parser.parse_args()

    if args.status:
        print_coverage()
    else:
        run(
            max_minutes=args.max_minutes,
            year=args.year,
            limit=args.limit,
            continue_past_year=args.continue_past_year,
        )
