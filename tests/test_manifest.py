"""Tests for db.manifest and the counting wired into db.transform.

Success criteria:
  Manifest: counts by (field, rule); tracks records seen separately from
    changes made, so the report has a denominator; an empty manifest reports
    that nothing changed rather than an empty report
  counting is driven by the rule's OUTPUT, not by re-testing its condition --
    the one thing a manifest must never do is drift from the rule it claims to
    describe, so a record with nothing to change must produce no counts at all
  the two total sentinels are counted APART: "the registry declined to report"
    and "this is not a count" are different facts that both load as NULL
  corpus: every number the manifest reports is the number db/rules.py claims,
    field for field -- this is the test that makes the manifest trustworthy,
    because a manifest that quietly disagrees with the rules is worse than no
    manifest at all
"""

import json
import unittest
from pathlib import Path

from db.manifest import Manifest
from db.rules import FLAGS_WITH_UNKNOWN
from db.transform import POBLACION_FLAGS, PROPOSITO_FLAGS, sponsor_name, study_row

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "detalle"

requires_corpus = unittest.skipUnless(
    RAW_DIR.exists() and any(RAW_DIR.glob("*.jsonl")),
    "data/raw/detalle is gitignored; corpus checks need a local cache")


def raw_record(**overrides):
    record = {
        "identificador": "2019-002321-29",
        "acronimo": "SPRINT",
        "enfermedadRara": "0",
        "calendario": {},
        "organismo": {"promotor": "Bayer AG"},
        "poblacion": dict.fromkeys(POBLACION_FLAGS, 0) | {"total": 120},
        "proposito": dict.fromkeys(PROPOSITO_FLAGS, 0),
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(record.get(key), dict):
            record[key] = record[key] | value
        else:
            record[key] = value
    return record


class TestManifest(unittest.TestCase):
    def test_counts_by_field_and_rule(self):
        manifest = Manifest()
        manifest.applied("studies.acronimo", "placeholder -> NULL")
        manifest.applied("studies.acronimo", "placeholder -> NULL")
        manifest.applied("studies.urgencia", "-1 (unknown) -> NULL")
        self.assertEqual(manifest.counts(), {
            ("studies.acronimo", "placeholder -> NULL"): 2,
            ("studies.urgencia", "-1 (unknown) -> NULL"): 1,
        })
        self.assertEqual(manifest.total(), 3)

    def test_records_seen_is_separate_from_changes_made(self):
        # A count without a denominator cannot be read. 4,763 placeholders
        # means one thing in 11,847 records and another in 20,000.
        manifest = Manifest()
        for _ in range(5):
            manifest.saw_record()
        manifest.applied("studies.acronimo", "placeholder -> NULL")
        self.assertEqual(manifest.records, 5)
        self.assertEqual(manifest.total(), 1)

    def test_an_empty_manifest_says_so(self):
        manifest = Manifest()
        manifest.saw_record()
        self.assertIn("nothing changed", manifest.report())

    def test_the_report_names_every_field_and_rule_it_counted(self):
        manifest = Manifest()
        manifest.saw_record()
        manifest.applied("studies.poblacion_total", "0 (not reported) -> NULL")
        report = manifest.report()
        for expected in ("studies.poblacion_total", "0 (not reported) -> NULL",
                         "total changes", "1"):
            with self.subTest(expected=expected):
                self.assertIn(expected, report)


class TestTransformCounting(unittest.TestCase):
    def counts(self, **overrides):
        manifest = Manifest()
        record = raw_record(**overrides)
        sponsor_name(record, manifest)
        study_row(record, 1, manifest)
        return manifest

    def test_a_clean_record_produces_no_counts(self):
        # The drift guard. If counting re-tested the rules' conditions instead
        # of reading their output, an over-broad condition would show up here.
        manifest = self.counts()
        self.assertEqual(manifest.counts(), {})
        self.assertEqual(manifest.records, 1)

    def test_a_placeholder_acronym_is_counted(self):
        self.assertEqual(
            self.counts(acronimo="NA").counts(),
            {("studies.acronimo", "placeholder -> NULL"): 1})

    def test_a_cleaned_acronym_is_counted_differently_from_a_dropped_one(self):
        # Both changed the value; only one removed it.
        self.assertEqual(
            self.counts(acronimo="  SPRINT  HF ").counts(),
            {("studies.acronimo", "markup or spacing cleaned"): 1})

    def test_a_minus_one_flag_is_counted_under_its_own_column(self):
        self.assertEqual(
            self.counts(poblacion={"urgencia": -1}).counts(),
            {("studies.urgencia", "-1 (unknown) -> NULL"): 1})

    def test_the_two_total_sentinels_are_counted_apart(self):
        # Same NULL, different facts: one is the registry declining to report,
        # the other is a value that was never a participant count.
        self.assertEqual(
            self.counts(poblacion={"total": 0}).counts(),
            {("studies.poblacion_total", "0 (not reported) -> NULL"): 1})
        self.assertEqual(
            self.counts(poblacion={"total": 999999}).counts(),
            {("studies.poblacion_total", "not a count -> NULL"): 1})

    def test_markup_in_a_sponsor_name_is_counted(self):
        self.assertEqual(
            self.counts(organismo={"promotor": "Merck &amp; Co"}).counts(),
            {("sponsors.promotor", "markup or spacing cleaned"): 1})

    def test_the_manifest_is_optional(self):
        # The transform has to stay usable on its own.
        record = raw_record(acronimo="NA")
        self.assertIsNone(study_row(record, 1)["acronimo"])
        self.assertEqual(sponsor_name(record), "Bayer AG")

    def test_a_value_the_rules_do_not_touch_is_not_counted(self):
        # An unexpected representation reaches the schema instead, and the
        # manifest must not claim to have handled it.
        manifest = self.counts(poblacion={"urgencia": "-1"})
        self.assertEqual(manifest.counts(), {})


@requires_corpus
class TestManifestAgainstCorpus(unittest.TestCase):
    """The manifest must report exactly what db/rules.py claims."""

    @classmethod
    def setUpClass(cls):
        records = []
        for path in sorted(RAW_DIR.glob("*.jsonl")):
            if ".failures." in path.name:
                continue
            with path.open(encoding="utf-8") as handle:
                records.extend(json.loads(line) for line in handle)
        cls.manifest = Manifest()
        for record in records:
            sponsor_name(record, cls.manifest)
            study_row(record, 1, cls.manifest)

    def test_it_saw_every_record(self):
        self.assertEqual(self.manifest.records, 11847)

    def test_the_flag_counts_are_the_ones_rules_py_declares(self):
        # Not "roughly the same" -- the same dict. If a refresh adds a -1 to a
        # thirteenth flag, this fails and FLAGS_WITH_UNKNOWN gets updated
        # alongside the NOT NULL constraints that depend on it.
        counted = {}
        for (field, rule), count in self.manifest.counts().items():
            if rule.startswith("-1"):
                counted[field[len("studies."):]] = count
        columns = {POBLACION_FLAGS[k]: v for k, v in FLAGS_WITH_UNKNOWN.items()}
        self.assertEqual(counted, columns)
        self.assertEqual(sum(counted.values()), 54)

    def test_the_placeholder_and_sentinel_counts_match_the_rules(self):
        counts = self.manifest.counts()
        self.assertEqual(
            counts[("studies.acronimo", "placeholder -> NULL")], 4763)
        self.assertEqual(
            counts[("studies.poblacion_total", "0 (not reported) -> NULL")], 2201)
        self.assertEqual(
            counts[("studies.poblacion_total", "not a count -> NULL")], 1)

    def test_the_report_is_readable_and_totals_correctly(self):
        report = self.manifest.report()
        self.assertIn("11,847 records", report)
        self.assertIn("{:,}".format(self.manifest.total()), report)


if __name__ == "__main__":
    unittest.main()
