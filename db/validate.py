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

import itertools
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

from db.transform import (
    funders,
    sponsor_key,
    sponsor_name,
    study_row,
    therapeutic_area_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw" / "detalle"
DEFAULT_SCHEMA = REPO_ROOT / "db" / "schema.sql"

# Set by the caller, never derived from the record itself.
SKIP_PROBE_COLUMNS = ("identificador", "sponsor_id")

# The probe needs a fresh primary key per attempt, and it has to satisfy the
# identifier format check like any other row -- year 9999 cannot collide with
# a real EudraCT id, and the shape is the real one.
_PROBE_IDS = itertools.count()


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
        # table -> rows built. Reported because "no violations" over an empty
        # table is not a clean run, it is an unexercised one.
        self.rows = {}

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
        candidate["identificador"] = "9999-{:06d}-99".format(next(_PROBE_IDS))
        con.execute("SAVEPOINT probe")
        try:
            _insert(con, candidate)
        except sqlite3.DatabaseError:
            bad.append((column, value))
        finally:
            con.execute("ROLLBACK TO probe")
            con.execute("RELEASE probe")
    return bad


def _load_children(con, report, record, study_id, year, funder_ids,
                   area_codes):
    """The rows that hang off an accepted study: funders and areas.

    Only reached once the study itself is in, because both bridges reference
    it. Each row is attempted on its own savepoint, so one bad funder is
    reported and skipped rather than taking the study's other children with
    it -- the same reason the study loop does not stop at the first bad
    record.

    A rejected child does NOT count as a rejected study. The study loaded; the
    report says which of its children did not, and `rejected` stays a count of
    studies so it can still be read against `checked`.
    """
    for key, name in funders(record):
        if key not in funder_ids:
            con.execute("SAVEPOINT child")
            try:
                cursor = con.execute(
                    "INSERT INTO funders (nombre_key, nombre) VALUES (?, ?)",
                    (key, name))
            except sqlite3.DatabaseError:
                con.execute("ROLLBACK TO child")
                report.record_anomaly("funders.nombre", name, year, study_id)
                con.execute("RELEASE child")
                continue
            funder_ids[key] = cursor.lastrowid
            con.execute("RELEASE child")
        _insert_bridge(con, report, "study_funders", "funder_id",
                       study_id, funder_ids[key], year)

    for code, nombre_es, nombre_en in therapeutic_area_rows(record):
        if code not in area_codes:
            con.execute("SAVEPOINT child")
            try:
                con.execute("INSERT INTO therapeutic_areas VALUES (?, ?, ?)",
                            (code, nombre_es, nombre_en))
            except sqlite3.DatabaseError:
                con.execute("ROLLBACK TO child")
                report.record_anomaly("therapeutic_areas.eutct_code", code,
                                      year, study_id)
                con.execute("RELEASE child")
                continue
            area_codes.add(code)
            con.execute("RELEASE child")
        _insert_bridge(con, report, "study_therapeutic_areas", "eutct_code",
                       study_id, code, year)


def _insert_bridge(con, report, table, column, study_id, parent, year):
    con.execute("SAVEPOINT bridge")
    try:
        con.execute(
            "INSERT INTO {} (study_id, {}) VALUES (?, ?)".format(table, column),
            (study_id, parent))
    except sqlite3.DatabaseError:
        con.execute("ROLLBACK TO bridge")
        report.record_anomaly(table, parent, year, study_id)
    finally:
        con.execute("RELEASE bridge")


def validate(raw_dir=DEFAULT_RAW_DIR, schema_path=DEFAULT_SCHEMA, years=None):
    """Push every cached record through the schema and report what it rejects."""
    paths = sorted(Path(raw_dir).glob("*.jsonl"))
    if years:
        wanted = {str(y) for y in years}
        paths = [p for p in paths if p.stem in wanted]

    con = open_schema(schema_path)
    report = Report()
    sponsors = {}
    funder_ids = {}
    area_codes = set()
    template = None
    deferred = []

    for path in paths:
        year = path.stem
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                report.checked += 1
                study_id = record.get("identificador")

                # Identity is the normalised key, display is the cleaned name,
                # and the cache is keyed on the same thing the UNIQUE is, so
                # two spellings of one sponsor reuse a row here exactly as
                # they will in the loader.
                promotor = sponsor_name(record)
                key = sponsor_key(record)
                if key not in sponsors:
                    try:
                        cursor = con.execute(
                            "INSERT INTO sponsors (promotor_key, promotor) "
                            "VALUES (?, ?)", (key, promotor))
                        sponsors[key] = cursor.lastrowid
                    except sqlite3.DatabaseError:
                        report.record_anomaly(
                            "sponsors.promotor", promotor, year, study_id)
                        report.rejected += 1
                        continue

                row = study_row(record, sponsors[key])
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
                    _load_children(con, report, record, study_id, year,
                                   funder_ids, area_codes)
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

    tables = [row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    report.rows = {
        table: con.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        for table in tables}

    con.close()
    return report


def print_report(report, stream=sys.stdout):
    def out(text=""):
        print(text, file=stream)

    out("checked {} studies: {} accepted, {} rejected".format(
        report.checked, report.accepted, report.rejected))
    out()

    if report.rows:
        out("rows built (a table at 0 is not validated, it is unexercised)")
        for table, count in sorted(report.rows.items()):
            out("  {:28s} {:>8,}".format(table, count))
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
