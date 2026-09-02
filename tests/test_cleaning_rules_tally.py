"""Tests for db.cleaning_rules_tally and the counting wired into db.transform.

Success criteria:
  CleaningRulesTally: counts by (field, rule); tracks records seen separately from
    changes made, so the report has a denominator; an empty tally reports
    that nothing changed rather than an empty report
  counting is driven by the rule's OUTPUT, not by re-testing its condition --
    the one thing a tally must never do is drift from the rule it claims to
    describe, so a record with nothing to change must produce no counts at all
  the two total sentinels are counted APART: "the registry declined to report"
    and "this is not a count" are different facts that both load as NULL
  corpus: every number the tally reports is the number db/cleaning_rules.py claims,
    field for field -- this is the test that makes the tally trustworthy,
    because a tally that quietly disagrees with the rules is worse than no
    tally at all
"""

import json
import unittest
from pathlib import Path

from db.cleaning_rules_tally import CleaningRulesTally
from db.cleaning_rules import FLAGS_WITH_UNKNOWN
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


class TestTally(unittest.TestCase):
    def test_counts_by_field_and_rule(self):
        tally = CleaningRulesTally()
        tally.applied("studies.acronimo", "placeholder -> NULL")
        tally.applied("studies.acronimo", "placeholder -> NULL")
        tally.applied("studies.urgencia", "-1 (unknown) -> NULL")
        self.assertEqual(tally.counts(), {
            ("studies.acronimo", "placeholder -> NULL"): 2,
            ("studies.urgencia", "-1 (unknown) -> NULL"): 1,
        })
        self.assertEqual(tally.total(), 3)

    def test_records_seen_is_separate_from_changes_made(self):
        # A count without a denominator cannot be read. 4,763 placeholders
        # means one thing in 11,847 records and another in 20,000.
        tally = CleaningRulesTally()
        for _ in range(5):
            tally.saw_record()
        tally.applied("studies.acronimo", "placeholder -> NULL")
        self.assertEqual(tally.records, 5)
        self.assertEqual(tally.total(), 1)

    def test_an_empty_tally_says_so(self):
        tally = CleaningRulesTally()
        tally.saw_record()
        self.assertIn("nothing changed", tally.report())

    def test_the_report_names_every_field_and_rule_it_counted(self):
        tally = CleaningRulesTally()
        tally.saw_record()
        tally.applied("studies.poblacion_total", "0 (not reported) -> NULL")
        report = tally.report()
        for expected in ("studies.poblacion_total", "0 (not reported) -> NULL",
                         "total changes", "1"):
            with self.subTest(expected=expected):
                self.assertIn(expected, report)


class TestTransformCounting(unittest.TestCase):
    def counts(self, **overrides):
        tally = CleaningRulesTally()
        record = raw_record(**overrides)
        # db.loader owns the record loop, so it owns the denominator: the
        # transforms count changes, not records.
        tally.saw_record()
        sponsor_name(record, tally)
        study_row(record, 1, tally)
        return tally

    def test_a_clean_record_produces_no_counts(self):
        # The drift guard. If counting re-tested the rules' conditions instead
        # of reading their output, an over-broad condition would show up here.
        tally = self.counts()
        self.assertEqual(tally.counts(), {})
        self.assertEqual(tally.records, 1)

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

    def test_the_tally_is_optional(self):
        # The transform has to stay usable on its own.
        record = raw_record(acronimo="NA")
        self.assertIsNone(study_row(record, 1)["acronimo"])
        self.assertEqual(sponsor_name(record), "Bayer AG")

    def test_a_value_the_rules_do_not_touch_is_not_counted(self):
        # An unexpected representation reaches the schema instead, and the
        # tally must not claim to have handled it.
        tally = self.counts(poblacion={"urgencia": "-1"})
        self.assertEqual(tally.counts(), {})


@requires_corpus
class TestTallyAgainstCorpus(unittest.TestCase):
    """The tally must report exactly what db/cleaning_rules.py claims."""

    @classmethod
    def setUpClass(cls):
        records = []
        for path in sorted(RAW_DIR.glob("*.jsonl")):
            if ".failures." in path.name:
                continue
            with path.open(encoding="utf-8") as handle:
                records.extend(json.loads(line) for line in handle)
        cls.tally = CleaningRulesTally()
        for record in records:
            cls.tally.saw_record()
            sponsor_name(record, cls.tally)
            study_row(record, 1, cls.tally)

    def test_it_saw_every_record(self):
        self.assertEqual(self.tally.records, 11847)

    def test_the_flag_counts_are_the_ones_rules_py_declares(self):
        # Not "roughly the same" -- the same dict. If a refresh adds a -1 to a
        # thirteenth flag, this fails and FLAGS_WITH_UNKNOWN gets updated
        # alongside the NOT NULL constraints that depend on it.
        counted = {}
        for (field, rule), count in self.tally.counts().items():
            if rule.startswith("-1"):
                counted[field[len("studies."):]] = count
        columns = {POBLACION_FLAGS[k]: v for k, v in FLAGS_WITH_UNKNOWN.items()}
        self.assertEqual(counted, columns)
        self.assertEqual(sum(counted.values()), 54)

    def test_the_placeholder_and_sentinel_counts_match_the_rules(self):
        counts = self.tally.counts()
        self.assertEqual(
            counts[("studies.acronimo", "placeholder -> NULL")], 4763)
        self.assertEqual(
            counts[("studies.poblacion_total", "0 (not reported) -> NULL")], 2201)
        self.assertEqual(
            counts[("studies.poblacion_total", "not a count -> NULL")], 1)

    def test_the_report_is_readable_and_totals_correctly(self):
        report = self.tally.report()
        self.assertIn("11,847 records", report)
        self.assertIn("{:,}".format(self.tally.total()), report)


if __name__ == "__main__":
    unittest.main()
