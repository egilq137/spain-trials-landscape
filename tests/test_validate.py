"""Tests for db.validate.

Success criteria:
  validate: counts every record as accepted or rejected, and never stops at
    the first bad one -- a bad record early in the corpus must not hide later
    ones
  attribution: a rejected row is reported against the specific column and
    value that the schema refused, not merely as "row failed"
  multiple faults: a row breaking three constraints reports all three. SQLite
    raises on only the first, so this is the behaviour the per-column probe
    exists for and the one most likely to regress
  no false positives: a clean corpus reports no violations
  grouping: the same bad value in many studies collapses to one entry with a
    count, a per-year breakdown and a few example study ids
  nulls: NULLs are counted per column so a column empty across the corpus is
    visible as a candidate for dropping
  years: passing years restricts the scan to those files
  sponsors: a blank promotor is reported against sponsors.promotor rather
    than crashing the run
  schema coupling: the rules enforced come from db/schema.sql, so loosening a
    constraint there changes the report without any edit here
"""

import json
import tempfile
import unittest
from pathlib import Path

from db.validate import DEFAULT_SCHEMA, validate
from tests.test_transform import raw_record


# db/schema.sql was reverted so the source could be profiled before a schema is
# designed from it (PROJECT_SPEC 2.2). These tests validate records *against*
# that schema, so they cannot run until it is rebuilt in 2.3. Skipped rather
# than deleted: the behaviour they pin -- especially reporting every broken
# constraint in a row, not just the first -- is what the rebuilt validator must
# still do.
requires_schema = unittest.skipUnless(
    DEFAULT_SCHEMA.exists(),
    "db/schema.sql not present: awaiting the profiling-first rebuild (2.3)")


@requires_schema
class ValidateTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self._labels = {}

    def write_year(self, year, records):
        path = self.raw_dir / "{}.jsonl".format(year)
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def run_validate(self, **kwargs):
        return validate(raw_dir=self.raw_dir, schema_path=DEFAULT_SCHEMA,
                        **kwargs)

    def study_id(self, label):
        """A valid EudraCT identifier for a readable label.

        The schema accepts only the two real identifier formats, so a fixture
        cannot use 'a' or 'bad' as an id. Labels stay in the test where they
        say what is wrong with a record; this maps each to a distinct valid
        id, stable within one test.
        """
        return "2019-{:06d}-29".format(
            self._labels.setdefault(label, len(self._labels) + 1))

    def study(self, label, **overrides):
        return raw_record(identificador=self.study_id(label), **overrides)


class TestCleanCorpus(ValidateTestCase):
    def test_reports_no_violations(self):
        self.write_year(2019, [self.study("a"), self.study("b")])
        report = self.run_validate()
        self.assertEqual((report.checked, report.accepted, report.rejected),
                         (2, 2, 0))
        self.assertEqual(dict(report.anomalies), {})
        self.assertEqual(report.unattributed, [])


class TestAttribution(ValidateTestCase):
    def test_names_the_column_and_value(self):
        self.write_year(2019, [self.study("ok"),
                               self.study("bad", poblacion={"urgencia": "-1"})])
        report = self.run_validate()
        self.assertEqual(report.rejected, 1)
        entry = report.anomalies[("urgencia", repr("-1"))]
        self.assertEqual(entry["count"], 1)
        self.assertEqual(entry["studies"], [self.study_id("bad")])

    def test_reports_every_broken_constraint_in_one_row(self):
        # SQLite raises on the first constraint only; without the per-column
        # probe this row would be reported as a single problem.
        self.write_year(2019, [
            self.study("ok"),
            self.study("bad",
                       poblacion={"urgencia": "-1", "lactancia": "-1"},
                       calendario={"fechaRegistro": "not-a-date"}),
        ])
        report = self.run_validate()
        self.assertEqual(report.rejected, 1)
        for column, value in (("urgencia", "-1"), ("lactancia", "-1"),
                              ("fecha_registro", "not-a-date")):
            with self.subTest(column=column):
                self.assertIn((column, repr(value)), report.anomalies)

    def test_a_bad_record_does_not_hide_later_ones(self):
        self.write_year(2019, [
            self.study("bad-first", poblacion={"urgencia": "-1"}),
            self.study("ok"),
            self.study("bad-last", poblacion={"incapaces": "-1"}),
        ])
        report = self.run_validate()
        self.assertEqual((report.checked, report.rejected), (3, 2))
        self.assertIn(("urgencia", repr("-1")), report.anomalies)
        self.assertIn(("incapaces", repr("-1")), report.anomalies)


class TestGrouping(ValidateTestCase):
    def test_same_value_across_years_collapses_with_counts(self):
        self.write_year(2019, [self.study("ok")] +
                        [self.study("a{}".format(i), poblacion={"urgencia": "-1"})
                         for i in range(3)])
        self.write_year(2020, [self.study("b0", poblacion={"urgencia": "-1"})])
        report = self.run_validate()
        entry = report.anomalies[("urgencia", repr("-1"))]
        self.assertEqual(entry["count"], 4)
        self.assertEqual(dict(entry["years"]), {"2019": 3, "2020": 1})

    def test_keeps_only_a_few_example_studies(self):
        self.write_year(2019, [self.study("ok")] +
                        [self.study("s{}".format(i), poblacion={"urgencia": "-1"})
                         for i in range(20)])
        entry = self.run_validate().anomalies[("urgencia", repr("-1"))]
        self.assertEqual(entry["count"], 20)
        self.assertEqual(len(entry["studies"]), 5)


class TestNulls(ValidateTestCase):
    def test_counts_nulls_per_column(self):
        self.write_year(2019, [self.study("a"), self.study("b")])
        report = self.run_validate()
        # fechaReinicio is blank in the fixture, so it is NULL in both rows.
        self.assertEqual(sum(report.nulls["fecha_reinicio"].values()), 2)
        # fechaAutorizacionAEMPS is always present, so it is never NULL.
        self.assertEqual(sum(report.nulls["fecha_autorizacion_aemps"].values()), 0)


class TestYearFilter(ValidateTestCase):
    def test_restricts_the_scan(self):
        self.write_year(2019, [self.study("a")])
        self.write_year(2020, [self.study("b"), self.study("c")])
        self.assertEqual(self.run_validate(years=["2020"]).checked, 2)
        self.assertEqual(self.run_validate().checked, 3)


class TestSponsors(ValidateTestCase):
    def test_blank_promotor_is_reported_not_raised(self):
        self.write_year(2019, [self.study("ok"),
                               self.study("bad", organismo={"promotor": "   "})])
        report = self.run_validate()
        self.assertEqual(report.rejected, 1)
        self.assertIn(("sponsors.promotor", repr(None)), report.anomalies)


class TestSchemaCoupling(ValidateTestCase):
    def test_report_follows_the_schema_file(self):
        # Loosening the constraint in a copy of the schema must change the
        # result with no edit to the validator -- proof the rules are not
        # restated in Python.
        self.write_year(2019, [self.study("ok"),
                               self.study("bad", poblacion={"urgencia": "-1"})])
        self.assertEqual(self.run_validate().rejected, 1)

        loosened = Path(self._tmp.name) / "loosened.sql"
        ddl = DEFAULT_SCHEMA.read_text(encoding="utf-8").replace(
            "urgencia                    INTEGER          CHECK (urgencia          IN (0, 1))",
            "urgencia                    INTEGER")
        loosened.write_text(ddl, encoding="utf-8")
        self.assertNotEqual(ddl, DEFAULT_SCHEMA.read_text(encoding="utf-8"))

        report = validate(raw_dir=self.raw_dir, schema_path=loosened)
        self.assertEqual(report.rejected, 0)


if __name__ == "__main__":
    unittest.main()
