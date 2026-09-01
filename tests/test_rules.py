"""Tests for db.rules (step 1: placeholders and sentinels).

Two layers, deliberately. The unit tests are pure and always run. The
corpus-backed tests re-measure each rule against all 11,847 cached studies and
skip when the cache is absent -- they are what turns a comment like "4,762
placeholder acronyms" from an assertion into something that fails when a
refresh changes the data underneath it.

Success criteria:
  fold: casefolds, strips accents, collapses whitespace, drops edge
    punctuation; None and blank fold to ""
  is_placeholder: matches the enumerated set case- and accent-insensitively;
    treats a punctuation-only value as a placeholder without enumerating every
    run of dashes and dots; and does NOT treat blank as one, because "the
    registry wrote NA" and "wrote nothing" are different facts even though
    both load as NULL
  clean_text: trims, and returns None for blank or placeholder
  clean_flag: passes 0 and 1 through, maps -1 to None, and leaves anything
    unexpected alone so the schema rejects and names it rather than this
    guessing
  clean_total: maps only 0 to None; the three large outliers stay raw
  corpus: the placeholder set still covers the acronimo, funder and centre
    reference counts it was built from; -1 still appears in exactly the 12
    flags listed and no others; total is still 0 in 2,201 records; the four
    impossible-date studies still exist and still have an end before their
    authorisation
"""

import json
import unittest
from pathlib import Path

from db.rules import (
    FLAG_UNKNOWN,
    FLAGS_WITH_UNKNOWN,
    IMPOSSIBLE_DATE_STUDIES,
    PLACEHOLDERS,
    TOTAL_OUTLIERS,
    TOTAL_UNKNOWN,
    clean_flag,
    clean_text,
    clean_total,
    fold,
    is_placeholder,
)

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "detalle"

requires_corpus = unittest.skipUnless(
    RAW_DIR.exists() and any(RAW_DIR.glob("*.jsonl")),
    "data/raw/detalle is gitignored; corpus checks need a local cache")


class TestFold(unittest.TestCase):
    def test_casefolds_and_strips_accents(self):
        self.assertEqual(fold("Oncología"), fold("ONCOLOGIA"))

    def test_collapses_whitespace(self):
        self.assertEqual(fold("  no   aplica  "), "no aplica")

    def test_drops_edge_punctuation(self):
        self.assertEqual(fold("N.A."), "n.a")

    def test_none_and_blank_fold_to_empty(self):
        self.assertEqual(fold(None), "")
        self.assertEqual(fold("   "), "")


class TestIsPlaceholder(unittest.TestCase):
    def test_matches_regardless_of_case_accent_or_spacing(self):
        for variant in ("NA", "na", " N/A ", "N.A.", "No Aplica", "no  aplica",
                        "NO APLICABLE", "NR", "Not Available"):
            with self.subTest(variant=variant):
                self.assertTrue(is_placeholder(variant))

    def test_punctuation_only_values_need_no_enumeration(self):
        # '-' alone is 1,922 intervention names. Enumerating every run of
        # dashes and dots would be endless; folding to nothing covers them.
        for variant in ("-", "--", ".", "..", " - "):
            with self.subTest(variant=variant):
                self.assertTrue(is_placeholder(variant))

    def test_blank_is_not_a_placeholder(self):
        for variant in (None, "", "   "):
            with self.subTest(variant=variant):
                self.assertFalse(is_placeholder(variant))

    def test_real_values_are_untouched(self):
        for variant in ("KEYTRUDA", "Nano", "NA-1000", "Roche AG", "Anakinra"):
            with self.subTest(variant=variant):
                self.assertFalse(is_placeholder(variant))

    def test_the_set_is_stored_already_folded(self):
        # Otherwise an entry could never match: lookups are done on folded text.
        for entry in PLACEHOLDERS:
            with self.subTest(entry=entry):
                self.assertEqual(fold(entry), entry)


class TestCleanText(unittest.TestCase):
    def test_trims(self):
        self.assertEqual(clean_text("  SPRINT  "), "SPRINT")

    def test_blank_and_placeholder_both_become_none(self):
        for variant in (None, "", "   ", "NA", "no aplica", "-"):
            with self.subTest(variant=variant):
                self.assertIsNone(clean_text(variant))


class TestCleanFlag(unittest.TestCase):
    def test_passes_zero_and_one_through(self):
        self.assertEqual(clean_flag(0), 0)
        self.assertEqual(clean_flag(1), 1)

    def test_maps_the_unknown_sentinel_to_none(self):
        self.assertIsNone(clean_flag(FLAG_UNKNOWN))

    def test_leaves_unexpected_values_alone(self):
        # So the schema's CHECK rejects and names them, rather than this
        # deciding what a 2 or a "si" was supposed to mean.
        for value in (2, -2, "si", ""):
            with self.subTest(value=value):
                self.assertEqual(clean_flag(value), value)


class TestCleanTotal(unittest.TestCase):
    def test_zero_becomes_none(self):
        self.assertIsNone(clean_total(TOTAL_UNKNOWN))

    def test_real_counts_and_outliers_stay(self):
        for value in (1, 180, *TOTAL_OUTLIERS):
            with self.subTest(value=value):
                self.assertEqual(clean_total(value), value)


@requires_corpus
class TestAgainstCorpus(unittest.TestCase):
    """Re-measures the counts the rules were written from."""

    @classmethod
    def setUpClass(cls):
        cls.records = []
        for path in sorted(RAW_DIR.glob("*.jsonl")):
            with path.open(encoding="utf-8") as handle:
                cls.records.extend(json.loads(line) for line in handle)

    def test_corpus_size_is_unchanged(self):
        self.assertEqual(len(self.records), 11847)

    def test_placeholders_still_cover_the_acronyms_they_were_built_from(self):
        hits = sum(1 for r in self.records if is_placeholder(r.get("acronimo")))
        self.assertEqual(hits, 4763)  # 4,744 'NA' + 19 other forms

    def test_placeholders_still_cover_the_funder_names(self):
        hits = 0
        for record in self.records:
            raw = (record.get("organismo") or {}).get("financiador") or ""
            hits += sum(1 for part in raw.split("|") if is_placeholder(part))
        self.assertEqual(hits, 584)  # 572 'NA' + 12 'None'/'NO APLICA'

    def test_placeholders_still_cover_the_centre_references(self):
        # The one placeholder that changes identity rather than a label: 'NR'
        # spans 103 distinct hospitals, so missing it would merge them.
        hits = hospitals = 0
        names = set()
        for record in self.records:
            for centre in (record.get("centros") or {}).get("centro") or []:
                if is_placeholder(centre.get("referencia")):
                    hits += 1
                    names.add((centre.get("nombre") or "").strip())
        hospitals = len(names)
        self.assertEqual(hits, 119)
        self.assertEqual(hospitals, 103)

    def test_minus_one_appears_in_exactly_the_listed_flags(self):
        found = {}
        for record in self.records:
            for key, value in (record.get("poblacion") or {}).items():
                if key != "total" and value == FLAG_UNKNOWN:
                    found[key] = found.get(key, 0) + 1
            for key, value in (record.get("proposito") or {}).items():
                if value == FLAG_UNKNOWN:
                    found[key] = found.get(key, 0) + 1
        self.assertEqual(found, FLAGS_WITH_UNKNOWN)

    def test_no_flag_field_is_ever_absent_or_blank(self):
        # The invariant that makes -1 -> NULL lossless: with no pre-existing
        # nulls, a NULL in a flag column can only mean the source sent -1.
        for record in self.records:
            for block in ("poblacion", "proposito"):
                values = record.get(block) or {}
                self.assertTrue(values, block)
                for key, value in values.items():
                    self.assertIsNotNone(value, "{}.{}".format(block, key))

    def test_total_is_zero_in_the_expected_number_of_records(self):
        zeros = sum(1 for r in self.records
                    if r["poblacion"]["total"] == TOTAL_UNKNOWN)
        self.assertEqual(zeros, 2201)

    def test_the_impossible_date_studies_still_exist_and_are_still_impossible(self):
        def iso(value):
            day, month, year = value.split("-")
            return "{}-{}-{}".format(year, month, day)

        seen = set()
        for record in self.records:
            if record["identificador"] not in IMPOSSIBLE_DATE_STUDIES:
                continue
            seen.add(record["identificador"])
            calendar = record["calendario"]
            self.assertLess(iso(calendar["fechaFinRealEspana"]),
                            iso(calendar["fechaAutorizacionAEMPS"]),
                            record["identificador"])
        self.assertEqual(seen, set(IMPOSSIBLE_DATE_STUDIES))


if __name__ == "__main__":
    unittest.main()
