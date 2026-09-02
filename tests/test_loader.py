"""Tests for db.loader.

Success criteria:
  load: fills every table from raw records, parents before children, and
    returns what it wrote per table
  explicit dependencies: the connection and the raw directory are arguments,
    so a load runs against :memory: and a temp directory with no patching
  failure policy is injected: the default Observer raises on the first row the
    database refuses, because by the time a real load runs db/validate.py has
    already been over the same corpus and a failure means something changed;
    an observer that records instead is what turns the same code into the
    validator
  impossible dates: the 4 enumerated studies are dropped before any insert,
    they take their children with them, and the tally says so -- a silent drop
    is the thing this project keeps trying not to do
  identity: two spellings of one sponsor reuse a row, so the loader's cache
    and the schema's UNIQUE agree rather than the second insert failing
  rebuild: opening a database applies the schema, which drops every table, so
    a second load is a rebuild and not an append -- the .db is a build
    artifact and data/raw/ is the durable copy
  years: passing years restricts the scan to those files
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from db import loader
from db.cleaning_rules import IMPOSSIBLE_DATE_STUDIES
from db.cleaning_rules_tally import CleaningRulesTally
from tests.test_transform import raw_record

DROPPED_ID = sorted(IMPOSSIBLE_DATE_STUDIES)[0]


class LoaderTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self._labels = {}

    def study_id(self, label):
        return "2019-{:06d}-29".format(
            self._labels.setdefault(label, len(self._labels) + 1))

    def study(self, label, **overrides):
        record = raw_record(identificador=self.study_id(label), **overrides)
        record.setdefault("areasTerapeuticas", {"area": [
            {"eutct": "C14", "nombre_es": "Cardio", "nombre_en": "Cardio"}]})
        record.setdefault("centros", {"centro": [
            {"referencia": "ORG-1", "nombre": "Hospital A",
             "localidad": "Madrid", "codPostal": "28046",
             "provincia": "Madrid", "ccaa": "Madrid"}]})
        record.setdefault("intervenciones", {"intervencion": [
            {"nombreComercial": "KEYTRUDA", "huerfano": "0",
             "viasAdministracion": "ORAL USE", "sustancias": "PACLITAXEL|"}]})
        return record

    def write_year(self, year, records):
        with (self.raw_dir / "{}.jsonl".format(year)).open(
                "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def load(self, con=None, **kwargs):
        con = con or loader.open_database(":memory:")
        self.addCleanup(con.close)
        rows = loader.load(con, raw_dir=self.raw_dir, **kwargs)
        return con, rows


class TestLoad(LoaderTestCase):
    def test_fills_every_table(self):
        self.write_year(2019, [self.study("a", organismo={
            "promotor": "Sponsor", "financiador": "ISCIII|"})])
        _, rows = self.load()
        for table in ("studies", "sponsors", "funders", "study_funders",
                      "therapeutic_areas", "study_therapeutic_areas",
                      "centers", "study_centers", "interventions",
                      "administration_routes", "substances",
                      "intervention_substances"):
            with self.subTest(table=table):
                self.assertEqual(rows[table], 1)

    def test_children_point_at_their_parents(self):
        self.write_year(2019, [self.study("a")])
        con, _ = self.load()
        # The bridge resolves back to the study through the foreign key, which
        # is the thing an id cache can get wrong without any error.
        self.assertEqual(
            con.execute("SELECT s.identificador FROM study_centers sc "
                        "JOIN studies s ON s.identificador = sc.study_id"
                        ).fetchone()[0],
            self.study_id("a"))

    def test_two_spellings_of_one_sponsor_reuse_a_row(self):
        self.write_year(2019, [
            self.study("a", organismo={"promotor": "AstraZeneca AB"}),
            self.study("b", organismo={"promotor": "Astrazeneca  AB"}),
        ])
        con, rows = self.load()
        self.assertEqual(rows["sponsors"], 1)
        self.assertEqual(rows["studies"], 2)
        self.assertEqual(
            con.execute("SELECT COUNT(DISTINCT sponsor_id) FROM studies"
                        ).fetchone()[0], 1)

    def test_years_restricts_the_scan(self):
        self.write_year(2019, [self.study("a")])
        self.write_year(2020, [self.study("b"), self.study("c")])
        self.assertEqual(self.load(years=["2020"])[1]["studies"], 2)
        self.assertEqual(self.load()[1]["studies"], 3)

    def test_a_second_load_rebuilds_rather_than_appends(self):
        self.write_year(2019, [self.study("a")])
        path = Path(self._tmp.name) / "trials.db"
        for _ in range(2):
            con = loader.open_database(path)
            rows = loader.load(con, raw_dir=self.raw_dir)
            con.close()
        self.assertEqual(rows["studies"], 1)

    def test_foreign_keys_are_enforced_on_the_connection(self):
        # SQLite ignores REFERENCES unless every connection asks for it, so
        # this is a property of open_database, not of the DDL.
        con = loader.open_database(":memory:")
        self.addCleanup(con.close)
        self.assertEqual(
            con.execute("PRAGMA foreign_keys").fetchone()[0], 1)


class TestImpossibleDates(LoaderTestCase):
    def test_the_enumerated_studies_are_dropped_with_their_children(self):
        self.write_year(2019, [self.study("ok"),
                               raw_record(identificador=DROPPED_ID)])
        con, rows = self.load()
        self.assertEqual(rows["studies"], 1)
        self.assertEqual(
            con.execute("SELECT identificador FROM studies").fetchone()[0],
            self.study_id("ok"))

    def test_the_drop_is_counted_not_silent(self):
        self.write_year(2019, [raw_record(identificador=DROPPED_ID)])
        tally = CleaningRulesTally()
        self.load(tally=tally)
        self.assertEqual(
            tally.counts()[("studies",
                            "end precedes authorisation -> dropped")], 1)
        # Seen but not written: the denominator still counts it.
        self.assertEqual(tally.records, 1)


class TestFailurePolicy(LoaderTestCase):
    def bad_study(self, label):
        # -1 survives the transform by design, so the CHECK is what rejects it.
        return self.study(label, poblacion={"urgencia": "-1"})

    def test_the_default_stops_the_load(self):
        self.write_year(2019, [self.bad_study("bad")])
        with self.assertRaises(sqlite3.DatabaseError):
            self.load()

    def test_an_observer_can_record_and_continue(self):
        self.write_year(2019, [self.bad_study("bad"), self.study("ok")])
        seen = []

        class Collect(loader.Observer):
            def failed(self, label, value, year, study_id, row, error):
                seen.append((label, study_id))

        _, rows = self.load(observer=Collect())
        self.assertEqual([label for label, _ in seen], ["studies"])
        self.assertEqual(rows["studies"], 1)

    def test_the_observer_sees_every_record_and_every_written_row(self):
        self.write_year(2019, [self.study("a")])
        records, written = [], []

        class Watch(loader.Observer):
            def record_seen(self, year, record):
                records.append(year)

            def written(self, table, row, year, study_id):
                written.append(table)

        self.load(observer=Watch())
        self.assertEqual(records, ["2019"])
        self.assertEqual(written.count("studies"), 1)
        self.assertIn("study_centers", written)


class TestTally(LoaderTestCase):
    def test_the_tally_is_optional(self):
        self.write_year(2019, [self.study("a")])
        self.load()  # no tally: must not raise

    def test_it_counts_the_rules_that_fired(self):
        self.write_year(2019, [self.study("a", acronimo="NA")])
        tally = CleaningRulesTally()
        self.load(tally=tally)
        self.assertEqual(
            tally.counts()[("studies.acronimo", "placeholder -> NULL")], 1)
        self.assertEqual(tally.records, 1)


if __name__ == "__main__":
    unittest.main()
