"""Raw JSONL to a populated SQLite database.

This is the only module that writes rows. db/validate.py does not have its own
copy of the insert order -- it calls `load` against an in-memory database with
an observer that collects failures instead of raising. That matters more than
it looks: a validator with its own INSERT sequence can only ever check the
sequence it happens to share with the loader, and the two drift the first time
one of them learns something. Here, "validated" means "went through the code
that loads it".

The connection and the raw directory are arguments, never module globals, so a
load can be pointed at :memory: and a handful of fixture files. Same
explicit-dependency shape as ingestion/cache.py.

What a load does, in order:

  1. **One pass to build the centre index.** A centre entry cannot describe its
     own site (db/centers.py), so this has to happen before any row is written.
  2. **One pass to write.** Sponsor, then study, then the study's funders,
     areas, sites and interventions -- parents before the rows that reference
     them, which is the whole of the ordering logic.

Failure policy is injected rather than decided here. The default raises on the
first bad row: by the time a real load runs, db/validate.py has already been
over the same corpus, so a failure means something changed and stopping is the
correct response. Passing an observer that records instead of raising is what
turns the same code into the validator.
"""

import json
import sqlite3
from pathlib import Path

from db.centers import build_center_index, center_row, study_centers
from db.cleaning_rules import IMPOSSIBLE_DATE_STUDIES
from db.transform import (
    funders,
    intervention_rows,
    sponsor_key,
    sponsor_name,
    study_row,
    therapeutic_area_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw" / "detalle"
DEFAULT_SCHEMA = REPO_ROOT / "db" / "schema.sql"
DEFAULT_DB = REPO_ROOT / "data" / "trials.db"


class Observer:
    """What to do about things worth knowing. The default: fail loudly.

    Every hook is a no-op except `failed`, which re-raises. db/validate.py
    subclasses this to collect rather than stop; nothing else needs to.
    """

    def record_seen(self, year, record):
        """One raw record read, whatever becomes of it."""

    def planned(self, table, row, year, study_id):
        """A row about to be attempted."""

    def written(self, table, row, year, study_id):
        """A row that went in."""

    def skipped(self, year, study_id, reason):
        """A record a declared rule excluded before any insert."""

    def failed(self, label, value, year, study_id, row, error):
        raise error


def open_database(path=DEFAULT_DB, schema_path=DEFAULT_SCHEMA):
    """A database with the schema applied. `path` may be ':memory:'.

    The file is rebuilt, not migrated: db/schema.sql drops every table before
    creating it, and data/raw/ is the durable copy, so the .db is a build
    artifact that can always be thrown away.
    """
    con = sqlite3.connect(path)
    con.executescript(Path(schema_path).read_text(encoding="utf-8"))
    # Connection-scoped: SQLite ignores foreign keys without it on every
    # connection, so the DDL's REFERENCES clauses would be decorative.
    con.execute("PRAGMA foreign_keys = ON")
    return con


def iter_records(paths):
    """(year, record) over every cached line. Streamed, never materialised.

    The year is the file the record came from, not the trial's own year --
    2026.json contains ids prefixed 2024- and 2025-. It is used to locate a
    problem in the cache, never to derive a column.
    """
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                yield path.stem, json.loads(line)


def year_files(raw_dir=DEFAULT_RAW_DIR, years=None):
    paths = sorted(Path(raw_dir).glob("*.jsonl"))
    if years:
        wanted = {str(y) for y in years}
        paths = [p for p in paths if p.stem in wanted]
    return paths


class _Load:
    """One load's caches and inserts. Created by `load`, not used directly.

    The caches are what keep identity decided in one place: a sponsor is
    looked up by its match_key, so two spellings reuse a row here exactly as
    the schema's UNIQUE would force them to.
    """

    def __init__(self, con, tally, observer, center_index):
        self.con = con
        self.tally = tally
        self.observer = observer
        self.center_index = center_index
        # Prefixed, because the methods below are named for the tables and
        # an instance attribute of the same name would shadow them.
        self._sponsor_ids = {}
        self._funder_ids = {}
        self._area_codes = set()
        self._center_ids = {}
        self._route_ids = {}
        self._substance_ids = {}

    def _insert(self, table, row, year, study_id, label, value):
        """Attempt one row. Returns its rowid, or None if the observer let a
        failure pass.

        The savepoint is what makes a recoverable failure possible at all: a
        failed INSERT inside a transaction leaves the transaction usable, but
        only if the statement can be rolled back on its own.
        """
        self.observer.planned(table, row, year, study_id)
        self.con.execute("SAVEPOINT row")
        try:
            cursor = self.con.execute(
                "INSERT INTO {} ({}) VALUES ({})".format(
                    table, ", ".join(row), ", ".join("?" * len(row))),
                list(row.values()))
        except sqlite3.DatabaseError as error:
            self.con.execute("ROLLBACK TO row")
            self.con.execute("RELEASE row")
            self.observer.failed(label, value, year, study_id, row, error)
            return None
        self.con.execute("RELEASE row")
        self.observer.written(table, row, year, study_id)
        return cursor.lastrowid

    def sponsor_id(self, record, year, study_id):
        key = sponsor_key(record)
        if key in self._sponsor_ids:
            return self._sponsor_ids[key]
        name = sponsor_name(record, self.tally)
        rowid = self._insert("sponsors",
                             {"promotor_key": key, "promotor": name},
                             year, study_id, "sponsors.promotor", name)
        if rowid is not None:
            self._sponsor_ids[key] = rowid
        return rowid

    def study(self, record, sponsor_id, year, study_id):
        row = study_row(record, sponsor_id, self.tally)
        return self._insert("studies", row, year, study_id,
                            "studies", study_id)

    def bridge(self, table, column, study_id, parent, year):
        self._insert(table, {"study_id": study_id, column: parent},
                     year, study_id, table, parent)

    def funders(self, record, year, study_id):
        for key, name in funders(record, self.tally):
            if key not in self._funder_ids:
                rowid = self._insert("funders",
                                     {"nombre_key": key, "nombre": name},
                                     year, study_id, "funders.nombre", name)
                if rowid is None:
                    continue
                self._funder_ids[key] = rowid
            self.bridge("study_funders", "funder_id", study_id,
                        self._funder_ids[key], year)

    def areas(self, record, year, study_id):
        for code, nombre_es, nombre_en in therapeutic_area_rows(record):
            if code not in self._area_codes:
                written = self._insert(
                    "therapeutic_areas",
                    {"eutct_code": code, "nombre_es": nombre_es,
                     "nombre_en": nombre_en},
                    year, study_id, "therapeutic_areas.eutct_code", code)
                if written is None:
                    continue
                self._area_codes.add(code)
            self.bridge("study_therapeutic_areas", "eutct_code", study_id,
                        code, year)

    def centers(self, record, year, study_id):
        # A study can list one site twice -- the same hospital under two
        # departments, and departamento is not stored -- so the bridge is
        # deduplicated per study rather than left to collide.
        seen = set()
        for raw in study_centers(record):
            resolved = center_row(raw, self.center_index, self.tally)
            if resolved is None:
                continue
            key, row = resolved
            if key not in self._center_ids:
                rowid = self._insert("centers", row, year, study_id,
                                     "centers", row["center_key"])
                if rowid is None:
                    continue
                self._center_ids[key] = rowid
            if key in seen:
                continue
            seen.add(key)
            self.bridge("study_centers", "center_id", study_id,
                        self._center_ids[key], year)

    def interventions(self, record, year, study_id):
        for item in intervention_rows(record, self.tally):
            route_id = None
            if item.route is not None:
                route_id = self.vocabulary(
                    "administration_routes", "nombre", item.route,
                    self._route_ids, year, study_id)
                if route_id is None:
                    continue
            rowid = self._insert(
                "interventions",
                {"study_id": study_id,
                 "nombre_comercial": item.nombre_comercial,
                 "codigo": item.codigo, "huerfano": item.huerfano,
                 "route_id": route_id},
                year, study_id, "interventions", item.nombre_comercial)
            if rowid is None:
                continue
            for key, name in item.substances:
                substance_id = self.vocabulary(
                    "substances", "nombre_key", key, self._substance_ids,
                    year, study_id, name)
                if substance_id is None:
                    continue
                self._insert("intervention_substances",
                             {"intervention_id": rowid,
                              "substance_id": substance_id},
                             year, study_id, "intervention_substances", name)

    def vocabulary(self, table, column, value, cache, year, study_id,
                   display=None):
        """The id of a shared lookup row, inserted the first time it is seen."""
        if value in cache:
            return cache[value]
        row = {column: value}
        if display is not None:
            row["nombre"] = display
        rowid = self._insert(table, row, year, study_id, table, value)
        if rowid is not None:
            cache[value] = rowid
        return rowid


def load(con, raw_dir=DEFAULT_RAW_DIR, years=None, tally=None, observer=None):
    """Fill `con` from the JSONL cache. Returns {table: rows written}.

    `tally` is an optional CleaningRulesTally: the load then reports what the
    cleaning rules changed as well as what it wrote. `observer` decides what
    happens to a row the database refuses -- the default stops the load.
    """
    observer = observer or Observer()
    paths = year_files(raw_dir, years)

    # Pass one. Nothing is written until the corpus has been read once,
    # because a site's name, region and postcode are resolved from all of its
    # entries rather than from any one of them.
    index = build_center_index(
        raw for _, record in iter_records(paths) for raw in study_centers(record))

    # One explicit transaction around the whole write pass. Without it the
    # per-row SAVEPOINT is the OUTERMOST savepoint, so every RELEASE commits
    # and every commit fsyncs -- invisible against :memory:, and the
    # difference between seconds and ten minutes against a file.
    con.execute("BEGIN")
    state = _Load(con, tally, observer, index)
    for year, record in iter_records(paths):
        observer.record_seen(year, record)
        if tally is not None:
            tally.saw_record()
        study_id = record.get("identificador")

        # Four studies end before they were authorised, which is a negative
        # duration that Kaplan-Meier cannot take. There is no way to tell
        # which of the two dates is wrong, so the record goes rather than a
        # guess -- an enumerated list in cleaning_rules.py, not a computed
        # test, so the loader cannot quietly start dropping a fifth.
        if study_id in IMPOSSIBLE_DATE_STUDIES:
            if tally is not None:
                tally.applied("studies",
                              "end precedes authorisation -> dropped")
            observer.skipped(year, study_id, "impossible dates")
            continue

        sponsor_id = state.sponsor_id(record, year, study_id)
        if sponsor_id is None:
            continue
        if state.study(record, sponsor_id, year, study_id) is None:
            continue
        state.funders(record, year, study_id)
        state.areas(record, year, study_id)
        state.centers(record, year, study_id)
        state.interventions(record, year, study_id)

    con.commit()
    tables = [row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return {table: con.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in tables}
