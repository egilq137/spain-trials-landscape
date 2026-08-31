"""Tests for db.profile.

The profiler produces the evidence schema decisions are made from, so a wrong
count here becomes a wrong column later. Success criteria per function:

  walk: follows a dotted path and distinguishes the four JSON facts that are
    easy to conflate -- present, blank string, explicit null, key absent --
    and reports the type of every level it passed through, so an assumption
    like "organismo is always an object" is checked rather than trusted. A
    parent of the wrong type (a list where an object was expected) is absent,
    not a crash
  normalise: the PROJECT_SPEC 3.2c identity rule exactly -- HTML unescape,
    drop accents, casefold, collapse internal whitespace, strip surrounding
    whitespace and punctuation. The unescape step is the one most likely to be
    dropped by accident, and dropping it silently under-reports how many
    sponsor names merge. Idempotent
  FieldProfile: counts statuses per year; counts distinct values exactly and
    after normalisation; measures lengths of present strings only;
    collapsing_groups returns only genuine groups, most frequent first
  profile_field: consumes records without re-reading the corpus per field
  print_profile: lists every value below the cardinality threshold and only
    the top few above it, so a low-cardinality field cannot hide a rogue value
  main: rejects an unknown table name rather than profiling nothing
"""

import io
import unittest
from unittest.mock import patch

from db.profile import (
    ABSENT,
    BLANK,
    LIST_ALL_BELOW,
    NULL,
    PRESENT,
    TABLE_FIELDS,
    main,
    normalise,
    print_profile,
    profile_field,
    walk,
)


class TestWalk(unittest.TestCase):
    def test_present_value(self):
        status, value, containers = walk({"organismo": {"promotor": "Roche"}},
                                         "organismo.promotor")
        self.assertEqual((status, value), (PRESENT, "Roche"))
        self.assertEqual(containers, ["dict", "dict"])

    def test_distinguishes_blank_null_and_absent(self):
        cases = {
            BLANK: {"organismo": {"promotor": "   "}},
            NULL: {"organismo": {"promotor": None}},
            ABSENT: {"organismo": {}},
        }
        for expected, record in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(walk(record, "organismo.promotor")[0], expected)

    def test_missing_parent_is_absent(self):
        self.assertEqual(walk({}, "organismo.promotor")[0], ABSENT)

    def test_parent_of_the_wrong_type_is_absent_not_an_error(self):
        # If organismo ever arrived as a list, the profile must say so rather
        # than raise -- the point is to check the assumption, not assume it.
        status, _, containers = walk({"organismo": [{"promotor": "Roche"}]},
                                     "organismo.promotor")
        self.assertEqual(status, ABSENT)
        self.assertEqual(containers, ["dict", "list"])

    def test_non_string_value_is_present(self):
        self.assertEqual(walk({"a": {"b": 0}}, "a.b"), (PRESENT, 0, ["dict", "dict"]))


class TestNormalise(unittest.TestCase):
    def test_casefolds(self):
        self.assertEqual(normalise("AstraZeneca AB"), normalise("Astrazeneca AB"))

    def test_strips_accents(self):
        self.assertEqual(normalise("Novartis Farmacéutica"),
                         normalise("Novartis Farmaceutica"))

    def test_collapses_internal_whitespace(self):
        self.assertEqual(normalise("Bayer  AG"), normalise("Bayer AG"))

    def test_strips_surrounding_punctuation_and_space(self):
        for variant in ("Pfizer Inc.", " Pfizer Inc ", "Pfizer Inc,"):
            with self.subTest(variant=variant):
                self.assertEqual(normalise(variant), normalise("Pfizer Inc"))

    def test_decodes_html_entities(self):
        # The step most likely to be dropped by accident. Without it the
        # profiler under-reports merges: these are one sponsor, not two.
        self.assertEqual(normalise("Merck Sharp &amp; Dohme LLC"),
                         normalise("Merck Sharp & Dohme LLC"))
        self.assertEqual(normalise("O&#39;Brien Ltd"), normalise("O'Brien Ltd"))

    def test_is_idempotent(self):
        once = normalise("  Sanofi-Aventis Recherche &amp; Développement. ")
        self.assertEqual(normalise(once), once)

    def test_does_not_merge_genuinely_different_names(self):
        self.assertNotEqual(normalise("Novartis Pharma AG"),
                            normalise("Novartis Farmacéutica, S.A."))


def build(path="a.b", rows=()):
    """rows: (year, record) pairs."""
    return profile_field(path, records=list(rows))


class TestFieldProfile(unittest.TestCase):
    def test_counts_statuses_and_years(self):
        profile = build(rows=[
            ("2019", {"a": {"b": "x"}}),
            ("2019", {"a": {"b": ""}}),
            ("2020", {"a": {}}),
        ])
        self.assertEqual(profile.records, 3)
        self.assertEqual(profile.status[PRESENT], 1)
        self.assertEqual(profile.status[BLANK], 1)
        self.assertEqual(profile.status[ABSENT], 1)
        self.assertEqual(profile.by_year["2019"][PRESENT], 1)
        self.assertEqual(profile.by_year["2020"][ABSENT], 1)

    def test_records_container_shapes(self):
        profile = build(rows=[("2019", {"a": {"b": "x"}}),
                              ("2019", {"a": ["b"]})])
        self.assertEqual(dict(profile.containers),
                         {"dict > dict": 1, "dict > list": 1})

    def test_distinct_exact_versus_normalised(self):
        profile = build(rows=[("2019", {"a": {"b": v}}) for v in
                              ("Roche AG", "roche ag", "Roche  AG", "Bayer AG")])
        self.assertEqual(profile.distinct, 4)
        self.assertEqual(profile.distinct_normalised, 2)

    def test_lengths_cover_present_strings_only(self):
        profile = build(rows=[("2019", {"a": {"b": "abc"}}),
                              ("2019", {"a": {"b": "  ab  "}}),
                              ("2019", {"a": {"b": ""}}),
                              ("2019", {"a": {}})])
        self.assertEqual(sorted(profile.lengths), [2, 3])

    def test_collapsing_groups_only_returns_real_groups(self):
        profile = build(rows=[("2019", {"a": {"b": v}}) for v in
                              ("Roche AG", "roche ag", "Bayer AG")])
        self.assertEqual(profile.collapsing_groups(),
                         [["Roche AG", "roche ag"]])

    def test_collapsing_groups_are_ordered_by_frequency(self):
        rows = [("2019", {"a": {"b": "Roche AG"}})] * 2
        rows += [("2019", {"a": {"b": "roche ag"}})]
        rows += [("2019", {"a": {"b": "Bayer AG"}})] * 10
        rows += [("2019", {"a": {"b": "bayer ag"}})] * 10
        groups = build(rows=rows).collapsing_groups()
        self.assertEqual([sorted(g) for g in groups],
                         [["Bayer AG", "bayer ag"], ["Roche AG", "roche ag"]])


class TestPrintProfile(unittest.TestCase):
    def render(self, profile):
        stream = io.StringIO()
        print_profile(profile, stream=stream)
        return stream.getvalue()

    def test_lists_every_value_when_cardinality_is_low(self):
        # A low-cardinality field must not be able to hide a rogue value, which
        # is how '-1' stayed invisible in the flags.
        rows = [("2019", {"a": {"b": v}}) for v in ("0", "1", "-1")]
        text = self.render(build(rows=rows))
        self.assertIn("all values", text)
        for value in ("'0'", "'1'", "'-1'"):
            self.assertIn(value, text)

    def test_summarises_when_cardinality_is_high(self):
        rows = [("2019", {"a": {"b": "v{}".format(i)}})
                for i in range(LIST_ALL_BELOW + 5)]
        text = self.render(build(rows=rows))
        self.assertIn("most frequent values", text)
        self.assertIn("occur exactly once", text)

    def test_reports_variant_groups(self):
        rows = [("2019", {"a": {"b": v}}) for v in ("Roche AG", "roche ag")]
        self.assertIn("case/accent/spacing", self.render(build(rows=rows)))

    def test_handles_a_field_that_is_never_present(self):
        text = self.render(build(rows=[("2019", {}), ("2020", {})]))
        self.assertIn("absent", text)
        self.assertIn("distinct values: 0", text)


class TestTableFields(unittest.TestCase):
    def test_sponsors_profiles_the_field_the_table_keeps(self):
        self.assertEqual(TABLE_FIELDS["sponsors"], ["organismo.promotor"])


class TestMain(unittest.TestCase):
    def test_unknown_table_is_rejected(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            self.assertEqual(main(["not_a_table"]), 1)
        self.assertIn("unknown table", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
