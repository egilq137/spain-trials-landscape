"""Composition root: wires ingestion -> transform -> db.

The one place that knows how the pieces fit together. Every module below takes
its dependencies as arguments -- a connection, a directory -- and none of them
reaches for a global to find another, so this file is where the decisions
about paths and order live and the only file that has to change when they do.

Usage:
    python run_pipeline.py build          # rebuild data/trials.db from the cache
    python run_pipeline.py build 2019     # one year, for a quick check
    python run_pipeline.py validate       # dry run: what would load, and what would change

Ingestion is deliberately NOT wired in. It takes ~4 hours of API calls and
data/raw/ is the durable copy of the result -- rebuilding the database must
not risk touching it. `python -m ingestion.detail` remains its own command.
"""

import sys

from db import loader, validate
from db.cleaning_rules_tally import CleaningRulesTally

# What the database should contain after a full build. Checked rather than
# trusted: a load that silently drops a table still "succeeds", and this is
# the cheapest thing that notices.
#
# Four of these are one lower than the corresponding figure in PROJECT_SPEC
# 3.2c, and the gap is the impossible-date rule rather than an error. Dropping
# those 4 studies also removes every row that ONLY they referenced: 2 sponsors
# (Ixaka Limited, Vall d'Hebron Institute of Oncology), 1 funder (Ixaka
# Limited again, as its own funder) and 1 centre. 3.2c counts what the cache
# contains; these count what a load keeps.
EXPECTED_ROWS = {
    "studies": 11843,          # 11,847 cached, 4 dropped for impossible dates
    "sponsors": 2983,          # 2,984 in the cache
    "funders": 2230,           # 2,231
    "centers": 3342,           # 3,343
    "therapeutic_areas": 55,
    "administration_routes": 53,
}


def build(years=None, db_path=loader.DEFAULT_DB):
    """Rebuild the database from data/raw/. Returns {table: rows}."""
    print("building {} from {}".format(db_path, loader.DEFAULT_RAW_DIR))
    tally = CleaningRulesTally()
    con = loader.open_database(db_path)
    try:
        rows = loader.load(con, years=years, tally=tally)
    finally:
        con.close()

    print()
    print(tally.report())
    print()
    for table, count in sorted(rows.items()):
        print("  {:28s} {:>8,}".format(table, count))
    return rows


def check(rows, years=None):
    """Do the row counts match what the profiling said they would be?

    Skipped for a partial build: the expected counts describe the whole
    corpus, and a one-year build has no business failing against them.
    """
    if years:
        print("\npartial build: row counts not checked")
        return True
    wrong = {table: (rows.get(table), expected)
             for table, expected in EXPECTED_ROWS.items()
             if rows.get(table) != expected}
    if not wrong:
        print("\nrow counts match PROJECT_SPEC 3.2c")
        return True
    print("\nROW COUNTS DIFFER from PROJECT_SPEC 3.2c:")
    for table, (got, expected) in sorted(wrong.items()):
        print("  {:28s} got {:,}, expected {:,}".format(
            table, got or 0, expected))
    print("\nThe cache may have been refreshed. Re-run the profiler and the "
          "corpus tests before updating these numbers.")
    return False


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command, years = (argv[0] if argv else "build"), argv[1:]

    if command == "validate":
        validate.print_report(validate.validate(years=years or None))
        return 0
    if command == "build":
        return 0 if check(build(years or None), years) else 1
    print("usage: python run_pipeline.py [build|validate] [years...]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
