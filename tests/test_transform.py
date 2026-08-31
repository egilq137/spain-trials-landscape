"""Tests for db.transform.

Success criteria per function:
  iso_date: 'DD-MM-YYYY' -> ISO; blank -> None; anything unconvertible passes
    through UNCHANGED rather than becoming None, so the column's GLOB check
    reports it instead of it looking like an ordinary missing date
  flag: '0'/'1' -> 0/1; '-1' and any other value pass through unchanged, so
    the CHECK rejects them rather than the transform hiding them; absent -> None
  integer: digits -> int; blank and non-numeric pass through unchanged
  sponsor_name: organismo.promotor trimmed; blank or absent -> None so the
    NOT NULL catches it rather than a '' row being created
  study_row: every calendario/poblacion/proposito field lands in its column
    under the snake_case name; sponsor_id is the one passed in, never looked
    up; censored is 1 exactly when fechaFinRealEspana is absent, and
    survival_end is then the extraction date rather than NULL
"""

import unittest

from db.transform import (
    CALENDARIO_DATES,
    POBLACION_FLAGS,
    PROPOSITO_FLAGS,
    flag,
    integer,
    iso_date,
    sponsor_name,
    study_row,
)

EXTRACTION = "2026-08-31"


def raw_record(**overrides):
    """A REEC detail record shaped like the real ones."""
    record = {
        "identificador": "2019-002321-29",
        "acronimo": " NA ",
        "enfermedadRara": "0",
        "calendario": {key: "" for key in CALENDARIO_DATES},
        "organismo": {"promotor": "  Merck Sharp & Dohme  "},
        "poblacion": dict.fromkeys(POBLACION_FLAGS, "0") | {"total": "120"},
        "proposito": dict.fromkeys(PROPOSITO_FLAGS, "0"),
    }
    record["calendario"]["fechaAutorizacionAEMPS"] = "18-12-2019"
    record["calendario"]["fechaRegistro"] = "19-12-2019"
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(record.get(key), dict):
            record[key] = record[key] | value
        else:
            record[key] = value
    return record


class TestIsoDate(unittest.TestCase):
    def test_converts_source_format(self):
        self.assertEqual(iso_date("18-12-2019"), "2019-12-18")

    def test_blank_and_absent_become_none(self):
        for raw in ("", "   ", None):
            with self.subTest(raw=raw):
                self.assertIsNone(iso_date(raw))

    def test_unconvertible_passes_through_unchanged(self):
        # Not None: the GLOB check should name the offending value.
        for raw in ("2019-12-18", "18/12/2019", "not a date", "1-2-3"):
            with self.subTest(raw=raw):
                self.assertEqual(iso_date(raw), raw)


class TestFlag(unittest.TestCase):
    def test_converts_zero_and_one(self):
        self.assertEqual(flag("0"), 0)
        self.assertEqual(flag("1"), 1)

    def test_minus_one_passes_through_unchanged(self):
        # The rule this module exists for: no quiet repair of odd values.
        self.assertEqual(flag("-1"), "-1")

    def test_absent_becomes_none(self):
        self.assertIsNone(flag(None))

    def test_other_values_pass_through(self):
        for raw in ("2", "si", ""):
            with self.subTest(raw=raw):
                self.assertEqual(flag(raw), raw)


class TestInteger(unittest.TestCase):
    def test_converts_digits(self):
        self.assertEqual(integer("120"), 120)

    def test_non_numeric_passes_through(self):
        for raw in ("", "unknown", "12.5", "-4"):
            with self.subTest(raw=raw):
                self.assertEqual(integer(raw), raw)


class TestSponsorName(unittest.TestCase):
    def test_trims(self):
        self.assertEqual(sponsor_name(raw_record()), "Merck Sharp & Dohme")

    def test_blank_or_absent_becomes_none(self):
        self.assertIsNone(sponsor_name(raw_record(organismo={"promotor": "   "})))
        self.assertIsNone(sponsor_name({}))


class TestStudyRow(unittest.TestCase):
    def row(self, **overrides):
        return study_row(raw_record(**overrides), 7, EXTRACTION)

    def test_maps_every_source_field_to_its_column(self):
        row = self.row()
        for column in list(CALENDARIO_DATES.values()) + \
                list(POBLACION_FLAGS.values()) + list(PROPOSITO_FLAGS.values()):
            with self.subTest(column=column):
                self.assertIn(column, row)

    def test_uses_the_sponsor_id_it_is_given(self):
        self.assertEqual(self.row()["sponsor_id"], 7)

    def test_converts_dates_and_flags(self):
        row = self.row()
        self.assertEqual(row["fecha_autorizacion_aemps"], "2019-12-18")
        self.assertEqual(row["fase_uno"], 0)
        self.assertEqual(row["poblacion_total"], 120)

    def test_acronym_is_trimmed_but_not_interpreted(self):
        # ' NA ' becomes 'NA', not None. Deciding that 'NA' means "no acronym"
        # is a judgement about meaning, which belongs in a named, documented
        # normalisation step -- not hidden inside a trim. See PROJECT_SPEC.
        self.assertEqual(self.row()["acronimo"], "NA")
        self.assertIsNone(self.row(acronimo="   ")["acronimo"])
        self.assertEqual(self.row(acronimo="SPRINT")["acronimo"], "SPRINT")

    def test_censored_when_spain_has_no_end_date(self):
        row = self.row()
        self.assertEqual(row["censored"], 1)
        self.assertEqual(row["survival_start"], "2019-12-18")
        self.assertEqual(row["survival_end"], EXTRACTION)

    def test_not_censored_when_an_end_date_exists(self):
        row = self.row(calendario={"fechaFinRealEspana": "31-03-2022"})
        self.assertEqual(row["censored"], 0)
        self.assertEqual(row["survival_end"], "2022-03-31")

    def test_does_not_repair_a_minus_one_flag(self):
        self.assertEqual(self.row(poblacion={"urgencia": "-1"})["urgencia"], "-1")


if __name__ == "__main__":
    unittest.main()
