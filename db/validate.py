"""Check real REEC records against the schema without keeping the result.

Why this is its own step rather than error handling inside the loader: a
loader stops at the first bad row, so problems arrive one at a time, in file
order, with no sense of whether a given one affects three studies or three
thousand. This runs the whole corpus, collects every constraint the data
violates, and reports them grouped with counts -- so the decisions get made
once, against evidence, rather than reactively.

It does NOT have its own copy of the insert order. It calls db.loader.load
against an in-memory database, passing an Observer that records failures
instead of raising, so "validated" means "went through the code that loads
it". A validator with its own INSERT sequence could only ever check the
sequence it happened to share with the loader.

The schema comes from db/schema.sql, so the rules enforced ARE the schema's
rules; nothing here restates them and the two cannot drift apart.

It is also the dry run for the loader. The same CleaningRulesTally the loader
would fill is filled here, so a run reports what a real load WOULD change --
'this would null 4,763 placeholder acronyms and recover 283 postcodes' --
before anything is written to a file.

Usage:
    python -m db.validate            # whole corpus
    python -m db.validate 2019 2024  # named years only
"""

import itertools
import sqlite3
import sys
from collections import Counter, defaultdict

from db import loader
from db.cleaning_rules_tally import CleaningRulesTally

DEFAULT_RAW_DIR = loader.DEFAULT_RAW_DIR
DEFAULT_SCHEMA = loader.DEFAULT_SCHEMA

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
        # Excluded by a declared rule before any insert, which is not the same
        # as refused by the schema.
        self.dropped = 0
        # (column, repr(value)) -> {"count", "years", "studies"}
        self.anomalies = defaultdict(
            lambda: {"count": 0, "years": Counter(), "studies": []})
        # column -> Counter of year -> number of NULLs
        self.nulls = defaultdict(Counter)
        self.unattributed = []
        # table -> rows built. Reported because "no violations" over an empty
        # table is not a clean run, it is an unexercised one.
        self.rows = {}
        # What the cleaning rules would change if this were a real load.
        self.tally = CleaningRulesTally()

    def record_anomaly(self, column, value, year, study_id):
        entry = self.anomalies[(column, repr(value))]
        entry["count"] += 1
        entry["years"][year] += 1
        if len(entry["studies"]) < 5:
            entry["studies"].append(study_id)


class _Collect(loader.Observer):
    """The failure policy that turns a load into a validation run.

    Records what the default Observer would raise on, and keeps the first
    accepted studies row as the template the per-column probe needs.
    """

    def __init__(self, report):
        self.report = report
        self.template = None
        self.deferred = []

    def record_seen(self, year, record):
        self.report.checked += 1

    def planned(self, table, row, year, study_id):
        if table == "studies":
            for column, value in row.items():
                if value is None:
                    self.report.nulls[column][year] += 1

    def written(self, table, row, year, study_id):
        if table == "studies":
            self.report.accepted += 1
            if self.template is None:
                self.template = dict(row)

    def skipped(self, year, study_id, reason):
        self.report.dropped += 1

    def failed(self, label, value, year, study_id, row, error):
        # A study that cannot load is deferred: which of its columns are at
        # fault takes a template row, and none exists until something has
        # been accepted.
        if label == "studies":
            self.report.rejected += 1
            self.deferred.append((year, study_id, row))
            return
        # A sponsor that will not load takes its study with it, since
        # studies.sponsor_id is NOT NULL. Anything else is a child row: the
        # study loaded, and only the child is missing.
        if label == "sponsors.promotor":
            self.report.rejected += 1
        self.report.record_anomaly(label, value, year, study_id)


def open_schema(schema_path=DEFAULT_SCHEMA):
    """An empty in-memory database with the real schema applied."""
    return loader.open_database(":memory:", schema_path)


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
            con.execute(
                "INSERT INTO studies ({}) VALUES ({})".format(
                    ", ".join(candidate), ", ".join("?" * len(candidate))),
                list(candidate.values()))
        except sqlite3.DatabaseError:
            bad.append((column, value))
        finally:
            con.execute("ROLLBACK TO probe")
            con.execute("RELEASE probe")
    return bad


def validate(raw_dir=DEFAULT_RAW_DIR, schema_path=DEFAULT_SCHEMA, years=None):
    """Run a load into a throwaway database and report what it could not do."""
    con = open_schema(schema_path)
    report = Report()
    collect = _Collect(report)

    report.rows = loader.load(con, raw_dir=raw_dir, years=years,
                              tally=report.tally, observer=collect)

    # Probing needs a row known to satisfy every constraint, which only exists
    # once something has been accepted -- hence the second pass.
    for year, study_id, row in collect.deferred:
        bad = _probe(con, row, collect.template) if collect.template else []
        if not bad:
            report.unattributed.append((year, study_id))
        for column, value in bad:
            report.record_anomaly(column, value, year, study_id)

    con.close()
    return report


def print_report(report, stream=sys.stdout):
    def out(text=""):
        print(text, file=stream)

    out("checked {} studies: {} accepted, {} rejected, {} dropped by rule"
        .format(report.checked, report.accepted, report.rejected,
                report.dropped))
    out()

    # The dry run: what a real load would change, from the same code path that
    # would change it. Printed before the violations because the two answer
    # different questions -- this one is "what did we do to the data", the
    # other is "what did the data do to the schema".
    out(report.tally.report())
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
