"""Check real REEC records against the schema without loading them.

Why this is its own step rather than error handling inside the loader: a
loader stops at the first bad row, so problems arrive one at a time, in file
order, with no sense of whether a given one affects three studies or three
thousand. This walks the whole corpus, collects every constraint the data
violates, and reports them grouped with counts -- so the decisions get made
once, against evidence, rather than reactively.

It inserts into a throwaway in-memory database built from db/schema.sql, so
the rules it enforces ARE the schema's rules. Nothing here restates them, and
the two cannot drift apart.

Usage:
    python -m db.validate            # whole corpus
    python -m db.validate 2019 2024  # named years only
"""

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

from db.transform import sponsor_name, study_row

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw" / "detalle"
DEFAULT_SCHEMA = REPO_ROOT / "db" / "schema.sql"

# Stand-in "today" for censored trials. Passed explicitly so a report is
# reproducible rather than depending on the day it was run.
EXTRACTION_DATE = "2026-08-31"

# Set by the caller, never derived from the record itself.
SKIP_PROBE_COLUMNS = ("identificador", "sponsor_id")


class Report:
    """What the corpus did when pushed through the schema."""

    def __init__(self):
        self.checked = 0
        self.accepted = 0
        self.rejected = 0
        # (column, repr(value)) -> {"count", "years", "studies"}
        self.anomalies = defaultdict(
            lambda: {"count": 0, "years": Counter(), "studies": []})
        # column -> Counter of year -> number of NULLs
        self.nulls = defaultdict(Counter)
        self.unattributed = []

    def record_anomaly(self, column, value, year, study_id):
        entry = self.anomalies[(column, repr(value))]
        entry["count"] += 1
        entry["years"][year] += 1
        if len(entry["studies"]) < 5:
            entry["studies"].append(study_id)


def open_schema(schema_path=DEFAULT_SCHEMA):
    """An empty database with the real schema applied."""
    con = sqlite3.connect(":memory:")
    con.executescript(Path(schema_path).read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _insert(con, row):
    con.execute(
        "INSERT INTO studies ({}) VALUES ({})".format(
            ",".join(row), ",".join("?" * len(row))),
        list(row.values()))


def _probe(con, row, template):
    """Which columns of a rejected row are individually unacceptable?

    SQLite reports only the first constraint a row breaks, so a row with three
    problems looks like a row with one. This retries the row one column at a
    time against a template known to satisfy everything, which finds them all.
    """
    bad = []
    for column, value in row.items():
        if column in SKIP_PROBE_COLUMNS or value == template.get(column):
            continue
        candidate = dict(template)
        candidate[column] = value
        candidate["identificador"] = "__probe__" + column
        con.execute("SAVEPOINT probe")
        try:
            _insert(con, candidate)
        except sqlite3.DatabaseError:
            bad.append((column, value))
        finally:
            con.execute("ROLLBACK TO probe")
            con.execute("RELEASE probe")
    return bad


def validate(raw_dir=DEFAULT_RAW_DIR, schema_path=DEFAULT_SCHEMA, years=None,
             extraction_date=EXTRACTION_DATE):
    """Push every cached record through the schema and report what it rejects."""
    paths = sorted(Path(raw_dir).glob("*.jsonl"))
    if years:
        wanted = {str(y) for y in years}
        paths = [p for p in paths if p.stem in wanted]

    con = open_schema(schema_path)
    report = Report()
    sponsors = {}
    template = None
    deferred = []

    for path in paths:
        year = path.stem
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                report.checked += 1
                study_id = record.get("identificador")

                promotor = sponsor_name(record)
                if promotor not in sponsors:
                    try:
                        cursor = con.execute(
                            "INSERT INTO sponsors (promotor) VALUES (?)",
                            (promotor,))
                        sponsors[promotor] = cursor.lastrowid
                    except sqlite3.DatabaseError:
                        report.record_anomaly(
                            "sponsors.promotor", promotor, year, study_id)
                        report.rejected += 1
                        continue

                row = study_row(record, sponsors[promotor], extraction_date)
                for column, value in row.items():
                    if value is None:
                        report.nulls[column][year] += 1

                con.execute("SAVEPOINT row")
                try:
                    _insert(con, row)
                except sqlite3.DatabaseError:
                    con.execute("ROLLBACK TO row")
                    report.rejected += 1
                    deferred.append((year, study_id, row))
                else:
                    report.accepted += 1
                    if template is None:
                        template = dict(row)
                finally:
                    con.execute("RELEASE row")

    # Probing needs a row known to satisfy every constraint, which only exists
    # once something has been accepted -- hence the second pass.
    for year, study_id, row in deferred:
        bad = _probe(con, row, template) if template else []
        if not bad:
            report.unattributed.append((year, study_id))
        for column, value in bad:
            report.record_anomaly(column, value, year, study_id)

    con.close()
    return report


def print_report(report, stream=sys.stdout):
    def out(text=""):
        print(text, file=stream)

    out("checked {} studies: {} accepted, {} rejected".format(
        report.checked, report.accepted, report.rejected))
    out()

    if report.anomalies:
        out("constraint violations ({} distinct column/value pairs)".format(
            len(report.anomalies)))
        for (column, value), entry in sorted(
                report.anomalies.items(), key=lambda kv: -kv[1]["count"]):
            years = ", ".join("{}x{}".format(y, n)
                              for y, n in sorted(entry["years"].items()))
            out("  {:28s} {:>10s}  x{:<5d} [{}]".format(
                column, value, entry["count"], years))
            out("  {:28s} e.g. {}".format("", ", ".join(entry["studies"])))
    else:
        out("constraint violations: none")

    if report.unattributed:
        out()
        out("rejected but not attributable to one column: {}".format(
            len(report.unattributed)))
        for year, study_id in report.unattributed[:10]:
            out("  {}  {}".format(year, study_id))

    always_null = sorted(c for c, y in report.nulls.items()
                         if sum(y.values()) == report.checked)
    if always_null:
        out()
        out("columns NULL in every record (candidates for dropping):")
        for column in always_null:
            out("  " + column)

    partial = sorted(((c, sum(y.values())) for c, y in report.nulls.items()
                      if c not in always_null),
                     key=lambda kv: -kv[1])
    if partial:
        out()
        out("columns with NULLs (count / share of corpus):")
        for column, count in partial:
            out("  {:28s} {:6d}  {:6.1%}".format(
                column, count, count / report.checked))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    print_report(validate(years=argv or None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
