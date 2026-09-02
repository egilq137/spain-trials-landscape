"""Tests for db.transform.

Success criteria per function:
  iso_date: 'DD-MM-YYYY' -> ISO; blank -> None; anything unconvertible passes
    through UNCHANGED rather than becoming None, so the column's GLOB check
    reports it instead of it looking like an ordinary missing date
  flag: '0'/'1' -> 0/1; '-1' and any other value pass through unchanged, so
    the CHECK rejects them rather than the transform hiding them; absent -> None
  integer: digits -> int; blank and non-numeric pass through unchanged
  acronym: placeholders -> None; case and internal punctuation survive,
    because this is the display form and not the match key
  sponsor_name: organismo.promotor cleaned for display -- markup decoded,
    spacing collapsed, case and accents kept; blank or absent -> None so the
    NOT NULL catches it rather than a '' row being created
  sponsor_key: markup, case and spacing variants of one company collapse to
    one key, while two companies in one group stay two keys
  the two kinds of change: structural conversion never repairs an unexpected
    value, and every value that DOES change is changed by a named rule in
    db/cleaning_rules.py -- '-1' as a string still reaches the schema and fails,
    because that is not the representation the rule was measured against
  funders: the pipe-delimited field splits whether or not it ends with a
    separator; placeholders create no funder at all, because absence of a
    bridge row already means "none recorded"; and one funder named twice in
    one study under two spellings yields one entry, since the bridge's
    composite key would refuse the second
  therapeutic_area_rows: every area in the list comes through with its code
    and both names, in order, with nothing deduplicated -- no study repeats a
    code, and 442 extra memberships across 363 studies are the reason this is
    a bridge rather than a column
  route_name: 129 raw spellings reach 53 canonical routes; a value naming no
    route and an absent field both give None; an unmapped value passes through
    instead of vanishing, so a refresh that adds a spelling is visible
  substances: pipe-split, placeholders dropped, deduplicated by identity --
    the same rule as funders, on the field where it merges most (20.7%)
  intervention_rows: one row per element with NO deduplication, because an
    intervention belongs to its study; placeholder names and blank orphan
    flags become NULL; route and substances are both optional, since the
    source swapped one for the other at the CTIS transition
  study_row: every calendario/poblacion/proposito field lands in its column
    under the snake_case name; sponsor_id is the one passed in, never looked
    up; and NOTHING is derived from the calendario dates -- censoring and
    duration are analysis/'s job, because the estimand is contested (see
    PROJECT_SPEC 3.2c), so this must not quietly reintroduce them
"""

import unittest

from db.transform import (
    CALENDARIO_DATES,
    POBLACION_FLAGS,
    PROPOSITO_FLAGS,
    flag,
    funders,
    integer,
    intervention_rows,
    iso_date,
    route_name,
    sponsor_key,
    sponsor_name,
    study_row,
    substances,
    therapeutic_area_rows,
)


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

    def test_decodes_markup_for_display(self):
        # The most frequent RAW spelling of the largest sponsor is the escaped
        # one, so a display column taken from the raw mode ships '&amp;'.
        record = raw_record(organismo={"promotor": "Merck Sharp &amp; Dohme LLC"})
        self.assertEqual(sponsor_name(record), "Merck Sharp & Dohme LLC")

    def test_keeps_case_and_accents(self):
        record = raw_record(organismo={"promotor": "Novartis Farmacéutica, S.A."})
        self.assertEqual(sponsor_name(record), "Novartis Farmacéutica, S.A.")

    def test_blank_or_absent_becomes_none(self):
        self.assertIsNone(sponsor_name(raw_record(organismo={"promotor": "   "})))
        self.assertIsNone(sponsor_name({}))


class TestStudyRow(unittest.TestCase):
    def row(self, **overrides):
        return study_row(raw_record(**overrides), 7)

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

    def test_acronym_placeholders_become_null(self):
        # This test used to assert the opposite: ' NA ' stayed 'NA', because
        # deciding that 'NA' means "no acronym" belonged in a named, documented
        # normalisation step rather than hidden inside a trim. That step now
        # exists -- cleaning_rules.PLACEHOLDERS, with the count that justifies it and a
        # corpus test behind it -- so the promise is kept, not broken.
        self.assertIsNone(self.row()["acronimo"])
        self.assertIsNone(self.row(acronimo="   ")["acronimo"])
        self.assertEqual(self.row(acronimo="SPRINT")["acronimo"], "SPRINT")

    def test_acronym_keeps_its_case_and_punctuation(self):
        # clean_text repairs damage; it is not the match key. 'PRO-ACT' must
        # not arrive as 'pro-act'.
        self.assertEqual(self.row(acronimo="PRO-ACT")["acronimo"], "PRO-ACT")

    def test_derives_nothing_from_the_dates(self):
        # Guards the 3.2c decision. Reintroducing a survival_start here would
        # bake one estimand into the database, where it cannot be varied or
        # explained -- and would silently pick a start date that is not the
        # trial's start.
        row = self.row(calendario={"fechaFinRealEspana": "31-03-2022"})
        for derived in ("censored", "survival_start", "survival_end"):
            self.assertNotIn(derived, row)

    def test_stores_the_end_date_as_recorded(self):
        row = self.row(calendario={"fechaFinRealEspana": "31-03-2022"})
        self.assertEqual(row["fecha_fin_real_espana"], "2022-03-31")

    def test_the_minus_one_sentinel_becomes_null(self):
        # The corpus sends these as JSON integers.
        self.assertIsNone(self.row(poblacion={"urgencia": -1})["urgencia"])

    def test_a_minus_one_in_an_unexpected_representation_still_reaches_the_schema(self):
        # The string '-1' is not what the source sends. flag leaves it alone
        # because it is neither '0' nor '1', and clean_flag leaves it alone
        # because it is not the integer -1, so it arrives at the CHECK and
        # fails loudly. That is the wanted outcome: a rule should cover the
        # data it was measured against, and a change in representation should
        # be a visible failure rather than something quietly absorbed.
        self.assertEqual(self.row(poblacion={"urgencia": "-1"})["urgencia"], "-1")

    def test_a_zero_total_becomes_null(self):
        # 0 planned participants is "not reported" in 2,201 records. Left as 0
        # it would drag every mean enrolment down.
        self.assertIsNone(self.row(poblacion={"total": "0"})["poblacion_total"])

    def test_a_real_total_survives(self):
        self.assertEqual(self.row(poblacion={"total": "1"})["poblacion_total"], 1)


class TestSponsorKey(unittest.TestCase):
    def test_markup_and_case_variants_reach_the_same_key(self):
        variants = ("Merck Sharp &amp; Dohme LLC", "Merck Sharp & Dohme LLC",
                    "MERCK SHARP & DOHME LLC", "  Merck  Sharp & Dohme  LLC ")
        keys = {sponsor_key(raw_record(organismo={"promotor": v}))
                for v in variants}
        self.assertEqual(len(keys), 1)

    def test_distinct_legal_entities_keep_distinct_keys(self):
        # Not entity resolution: same group, different companies, two rows.
        a = sponsor_key(raw_record(organismo={"promotor": "Novartis Farmacéutica, S.A."}))
        b = sponsor_key(raw_record(organismo={"promotor": "Novartis Pharma AG"}))
        self.assertNotEqual(a, b)

    def test_blank_or_absent_becomes_none(self):
        self.assertIsNone(sponsor_key(raw_record(organismo={"promotor": " "})))
        self.assertIsNone(sponsor_key({}))


class TestFunders(unittest.TestCase):
    def funders_of(self, financiador):
        return funders(raw_record(organismo={"promotor": "Someone",
                                             "financiador": financiador}))

    def test_splits_with_or_without_a_trailing_separator(self):
        # 5,280 values end with '|' and 1,563 do not.
        for raw in ("ISCIII|Pfizer|", "ISCIII|Pfizer"):
            with self.subTest(raw=raw):
                self.assertEqual([name for _, name in self.funders_of(raw)],
                                 ["ISCIII", "Pfizer"])

    def test_a_single_funder_needs_no_separator_handling(self):
        self.assertEqual([name for _, name in self.funders_of("ISCIII|")],
                         ["ISCIII"])

    def test_placeholders_create_no_funder(self):
        # 'NA' is the most frequent funder name in the source. Kept, it would
        # be an organisation that funded 572 trials.
        self.assertEqual(self.funders_of("NA|"), [])
        self.assertEqual(self.funders_of("N/A|Not available|"), [])

    def test_a_placeholder_does_not_suppress_a_real_funder(self):
        self.assertEqual([name for _, name in self.funders_of("NA|ISCIII|")],
                         ["ISCIII"])

    def test_one_funder_named_twice_yields_one_entry(self):
        # 12 studies do this. The bridge's PRIMARY KEY would refuse the second,
        # and deduplicating on the raw string would not catch the respelling.
        self.assertEqual(
            [name for _, name in self.funders_of("ISCIII|isciii|")],
            ["ISCIII"])

    def test_identity_and_display_are_the_two_different_forms(self):
        [(key, name)] = self.funders_of("  Merck Sharp &amp; Dohme  |")
        self.assertEqual(name, "Merck Sharp & Dohme")
        self.assertEqual(key, "mercksharp&dohme")

    def test_blank_and_absent_yield_nothing(self):
        self.assertEqual(self.funders_of(""), [])
        self.assertEqual(self.funders_of("|||"), [])
        self.assertEqual(funders({}), [])


class TestTherapeuticAreaRows(unittest.TestCase):
    AREA = {"eutct": "999999000429",
            "nombre_es": "Enfermedades [C] - Tracto respiratorio [C08]",
            "nombre_en": "Diseases [C] - Respiratory Tract Diseases [C08]"}

    def test_each_area_keeps_its_code_and_both_names(self):
        rows = therapeutic_area_rows(
            raw_record(areasTerapeuticas={"area": [self.AREA]}))
        self.assertEqual(rows, [(self.AREA["eutct"], self.AREA["nombre_es"],
                                 self.AREA["nombre_en"])])

    def test_several_areas_all_come_through(self):
        # 363 studies list more than one; a column would lose 442 memberships.
        second = dict(self.AREA, eutct="999999000431")
        rows = therapeutic_area_rows(
            raw_record(areasTerapeuticas={"area": [self.AREA, second]}))
        self.assertEqual([code for code, _, _ in rows],
                         ["999999000429", "999999000431"])

    def test_a_missing_block_yields_nothing(self):
        self.assertEqual(therapeutic_area_rows({}), [])
        self.assertEqual(
            therapeutic_area_rows(raw_record(areasTerapeuticas={"area": []})),
            [])


class TestRouteName(unittest.TestCase):
    def test_phrasing_and_misspellings_reach_one_route(self):
        for raw in ("ORAL", "oral use", "Oral Use"):
            with self.subTest(raw=raw):
                self.assertEqual(route_name(raw), "oral")
        for raw in ("INTRAVENOUS USE", "iv infusion", "intravenious infusion"):
            with self.subTest(raw=raw):
                self.assertEqual(route_name(raw), "intravenous")

    def test_an_entity_encoded_value_reaches_the_same_route(self):
        # 20 rows. The map is keyed after decoding, so this is not a special
        # case -- it goes through the same normalisation as every other value.
        self.assertEqual(route_name("INFUSI&Oacute;N INTRAVENOSA"),
                         "intravenous")

    def test_a_value_naming_no_route_is_none(self):
        # 299 rows. Not the same as absent, but both mean no route to point at.
        for raw in ("unknown use", "OTHER USE",
                    "route of administration not applicable"):
            with self.subTest(raw=raw):
                self.assertIsNone(route_name(raw))

    def test_absent_is_none(self):
        # 13,678 of 30,946 elements: the field only exists from 2022.
        self.assertIsNone(route_name(None))
        self.assertIsNone(route_name("  "))

    def test_a_compound_value_is_not_forced_into_one_route(self):
        self.assertEqual(route_name("oral and iv"), "multiple routes")

    def test_a_dosage_form_is_not_guessed_into_a_route(self):
        self.assertEqual(route_name("solution for injection"),
                         "injection, route unspecified")

    def test_an_unmapped_value_passes_through_rather_than_vanishing(self):
        # It then shows up as an extra administration_routes row, which is how
        # a refresh that adds a spelling becomes visible instead of silent.
        self.assertEqual(route_name("teleportation use"), "teleportation use")


class TestSubstances(unittest.TestCase):
    def substances_of(self, sustancias):
        return substances({"sustancias": sustancias})

    def test_splits_and_deduplicates_by_identity(self):
        self.assertEqual(
            [name for _, name in self.substances_of("PACLITAXEL|Paclitaxel|")],
            ["PACLITAXEL"])

    def test_several_substances_all_come_through(self):
        # 512 elements list two, 182 three, and one lists 45.
        self.assertEqual(
            [name for _, name in self.substances_of("PACLITAXEL|CISPLATIN|")],
            ["PACLITAXEL", "CISPLATIN"])

    def test_placeholders_create_no_substance(self):
        # 884 of 15,130 mentions.
        self.assertEqual(self.substances_of("N/A|"), [])
        self.assertEqual(self.substances_of("Not available|NA|"), [])

    def test_absent_yields_nothing(self):
        self.assertEqual(self.substances_of(""), [])
        self.assertEqual(substances({}), [])


class TestInterventionRows(unittest.TestCase):
    def rows_for(self, *elements):
        return intervention_rows(
            raw_record(intervenciones={"intervencion": list(elements)}))

    def test_each_element_becomes_a_row_without_deduplication(self):
        # Two arms can name one drug; each is a row, because an intervention
        # belongs to its study rather than being a shared object.
        rows = self.rows_for({"nombreComercial": "KEYTRUDA", "huerfano": "0"},
                             {"nombreComercial": "KEYTRUDA", "huerfano": "0"})
        self.assertEqual(len(rows), 2)

    def test_a_missing_block_yields_nothing(self):
        # ABSENT from 1,514 studies, not blank -- unlike centros.
        self.assertEqual(intervention_rows({}), [])
        self.assertEqual(self.rows_for(), [])

    def test_placeholder_names_become_null(self):
        # '-' appears 1,922 times and 'NA' 283.
        for raw in ("-", "NA", "N/A"):
            with self.subTest(raw=raw):
                self.assertIsNone(
                    self.rows_for({"nombreComercial": raw})[0].nombre_comercial)

    def test_a_blank_orphan_flag_is_null_not_a_rejected_value(self):
        # Blank in 25 of 30,946. Blank means absent; there is no rule here.
        self.assertIsNone(self.rows_for({"huerfano": ""})[0].huerfano)
        self.assertEqual(self.rows_for({"huerfano": "1"})[0].huerfano, 1)

    def test_the_route_and_substances_come_through_resolved(self):
        row = self.rows_for({"viasAdministracion": "ORAL USE",
                             "sustancias": "PACLITAXEL|"})[0]
        self.assertEqual(row.route, "oral")
        self.assertEqual([name for _, name in row.substances], ["PACLITAXEL"])

    def test_the_two_fields_that_never_co_occur_are_both_optional(self):
        # Not one element of 30,946 has both: substances ran to 2021, routes
        # from 2022. A row with neither is the 1.4% that has neither.
        row = self.rows_for({"nombreComercial": "KEYTRUDA"})[0]
        self.assertIsNone(row.route)
        self.assertEqual(row.substances, [])


if __name__ == "__main__":
    unittest.main()
