"""Tests for analysis.hospitals.

Success criteria:
  tokens: language variants fold onto one word, so `University Hospital La
    Paz` and `Hospital Universitario La Paz` are the same set. This is the
    whole reason the matcher works across four languages
  similarity: a set measure, so word order cannot matter -- the failure that
    sank the first draft, where the English names scored 0.62
  blocking searches postcode, town and province together, because REEC and
    the catalogue disagree about postcodes and stopping at the first answer
    hid the right hospital behind a wrong one
  match: accepts only above the floor and clear of the runner-up, and says
    why in every other case
  aliases: the hospitals whose official name shares nothing with REEC's
  against the database: the 324 rows carrying a CODCNH are the calibration
    set, and the accuracy measured on them is pinned here so a change to the
    synonym table or the thresholds cannot quietly trade it away
"""

import re
import sqlite3
import unittest
from pathlib import Path

from analysis import hospitals
from analysis.hospitals import (ACCEPT, Index, load_hospitals, match,
                                similarity, tokens)

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "trials.db"
CATALOGUE = ROOT / "data" / "geo" / "hospitals.csv"

requires_database = unittest.skipUnless(
    DB_PATH.exists(),
    "data/trials.db is a build artifact; run `python run_pipeline.py build`")


def hospital(**fields):
    defaults = dict(codcnh="000001", nombre="Hospital", municipio="Madrid",
                    provincia="Madrid", cod_postal="28001", camas="100",
                    clase="Hospitales Generales", dependencia="Privados",
                    complejo="")
    return hospitals.Hospital(**{**defaults, **fields})


class TestTokens(unittest.TestCase):
    def test_language_variants_fold_together(self):
        self.assertEqual(tokens("University Hospital"),
                         tokens("Hospital Universitario"))
        self.assertEqual(tokens("Institut Català"), tokens("Instituto Catalá"))

    def test_connectors_carry_no_identity(self):
        self.assertEqual(tokens("Hospital Clinic of Barcelona"),
                         tokens("Hospital Clinic de Barcelona"))

    def test_accents_and_case_do_not_separate_a_name_from_itself(self):
        self.assertEqual(tokens("HOSPITAL LA PAZ"), tokens("hospital la paz"))


class TestSimilarity(unittest.TestCase):
    def test_word_order_does_not_matter(self):
        # The failure that sank the first draft: a character measure scores
        # this pair 0.62, under any threshold worth having.
        self.assertEqual(
            similarity("University Hospital La Paz",
                       "Hospital Universitario La Paz"), 1.0)

    def test_the_same_hospital_in_two_languages(self):
        self.assertEqual(
            similarity("Hospital Clinic of Barcelona",
                       "Hospital Clinic de Barcelona"), 1.0)

    def test_a_research_institute_is_not_its_hospital(self):
        self.assertLess(
            similarity("Vall d'Hebron Institut de Recerca",
                       "Hospital Universitari Vall d'Hebron"), ACCEPT)

    def test_the_collision_the_catalogue_contains(self):
        # Two real Madrid hospitals, 966 beds and 99.
        self.assertLess(
            similarity("Hospital Universitario La Paz",
                       "Clínica Nuestra Señora de La Paz"), ACCEPT)

    def test_nothing_in_common_scores_nothing(self):
        self.assertEqual(similarity("Hospital del Mar", "Clínica Cemtro"), 0.0)


class TestIndex(unittest.TestCase):
    CATALOGUE = [
        hospital(codcnh="280246", nombre="Hospital Gregorio Marañón",
                 cod_postal="28007"),
        hospital(codcnh="280099", nombre="Hospital Niño Jesús",
                 cod_postal="28009"),
        hospital(codcnh="080291", nombre="Hospital Sant Pau",
                 municipio="Barcelona", cod_postal="08041"),
    ]

    def setUp(self):
        self.index = Index(self.CATALOGUE)

    def test_a_disagreeing_postcode_does_not_hide_the_right_hospital(self):
        # REEC files Gregorio Marañón at 28009; the catalogue says 28007.
        # 28009 holds another hospital, so a search that stopped at the
        # postcode would never look in Madrid and never find it.
        found = self.index.candidates("Madrid", "28009")
        self.assertIn("280246", [h.codcnh for h in found])
        self.assertIn("280099", [h.codcnh for h in found])

    def test_candidates_are_not_repeated(self):
        found = self.index.candidates("Madrid", "28007")
        self.assertEqual(len(found), len({h.codcnh for h in found}))

    def test_a_town_in_another_province_is_not_a_candidate(self):
        found = self.index.candidates("Barcelona", "08041")
        self.assertNotIn("280246", [h.codcnh for h in found])


class TestMatch(unittest.TestCase):
    CATALOGUE = [
        hospital(codcnh="280014", nombre="Hospital Universitario La Paz",
                 cod_postal="28046", camas="966"),
        hospital(codcnh="280409", nombre="Clínica Nuestra Señora de La Paz",
                 cod_postal="28046", camas="99"),
        hospital(codcnh="280029", nombre="Hospital Universitario Ramon y "
                                         "Cajal", cod_postal="28001"),
    ]

    def setUp(self):
        self.index = Index(self.CATALOGUE)

    def test_it_matches_the_hospital(self):
        result = match(self.index, "HOSPITAL UNIVERSITARIO LA PAZ",
                       "Madrid", "28046")
        self.assertEqual(result.hospital.codcnh, "280014")

    def test_it_matches_across_a_disagreeing_postcode(self):
        result = match(self.index, "Hospital Ramón y Cajal", "Madrid",
                       "28034")
        self.assertEqual(result.hospital.codcnh, "280029")

    def test_it_refuses_when_the_runner_up_is_close(self):
        # Two catalogue entries the name cannot separate -- the real shape is
        # Institut Català d'Oncologia, which the catalogue lists once per
        # campus. Both score well, so the floor lets them through and only
        # the margin stops the matcher picking one at random.
        index = Index([
            hospital(codcnh="080001", nombre="Institut Català d'Oncologia",
                     municipio="Badalona", cod_postal="08916"),
            hospital(codcnh="080002", nombre="Institut Català d'Oncologia",
                     municipio="Badalona", cod_postal="08916"),
        ])
        result = match(index, "Institut Catala D'oncologia", "Badalona",
                       "08916")
        self.assertGreaterEqual(result.score, ACCEPT)
        self.assertIsNone(result.hospital)
        self.assertIn("too close", result.why)

    def test_it_refuses_what_is_not_a_hospital(self):
        result = match(self.index, "CAP Balafia-Pardinyes", "Madrid", "28046")
        self.assertIsNone(result.hospital)
        self.assertIn("under", result.why)

    def test_a_refusal_still_names_the_closest(self):
        # A rejection a reader cannot see the near-miss for is one they
        # cannot judge.
        result = match(self.index, "CAP Balafia-Pardinyes", "Madrid", "28046")
        self.assertIsNotNone(result.closest)

    def test_nowhere_to_look_is_its_own_answer(self):
        result = match(self.index, "Hospital", "", "")
        self.assertIsNone(result.hospital)
        self.assertIn("no hospital", result.why)


@requires_database
class TestAgainstDatabase(unittest.TestCase):
    """The calibration set: 324 rows whose right answer REEC itself states."""

    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(
            "file:{}?mode=ro".format(DB_PATH.as_posix()), uri=True)
        cls.index = Index(load_hospitals(CATALOGUE))
        codes = set(cls.index.by_code)
        cls.truth = [row for row in cls.con.execute(
            "SELECT nombre, localidad, cod_postal, referencia FROM centers "
            "WHERE referencia GLOB '[0-9]*'")
            if re.fullmatch(r"\d{6}", row[3]) and row[3] in codes]

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_the_catalogue_is_the_one_that_was_calibrated_against(self):
        self.assertEqual(len(self.index.hospitals), 848)
        self.assertEqual(len(self.truth), 324)

    def test_it_never_matches_the_wrong_hospital(self):
        """The measure that matters. Precision before recall: a wrong match
        invents a hospital that does not exist and inflates one that does,
        where a miss costs one dot on a map and lands on a review page."""
        wrong = []
        for nombre, localidad, cod_postal, code in self.truth:
            result = match(self.index, nombre, localidad, cod_postal)
            if result.hospital and result.hospital.codcnh != code:
                wrong.append((nombre, result.hospital.nombre))
        self.assertEqual(wrong, [])

    def test_it_matches_most_of_them(self):
        # 314 of 324 when this was written. Pinned a little below so that an
        # added synonym cannot quietly cost recall, and so that a rebuilt
        # database with a few more centres does not fail the suite.
        matched = sum(1 for nombre, localidad, cod_postal, _ in self.truth
                      if match(self.index, nombre, localidad,
                               cod_postal).hospital)
        self.assertGreaterEqual(matched, 310)

    def test_the_names_the_aliases_exist_for(self):
        for nombre, localidad, cod_postal, expected in [
                ("Parc Tauli Hospital Universitari", "Sabadell", "08208",
                 "080958"),
                ("Hospital Universitario Lucus Augusti", "Lugo", "27003",
                 "270018"),
                ("Centro Oncológico Md Anderson International España",
                 "Madrid", "28033", "281113")]:
            with self.subTest(nombre=nombre):
                result = match(self.index, nombre, localidad, cod_postal)
                self.assertIsNotNone(result.hospital, result.why)
                self.assertEqual(result.hospital.codcnh, expected)

    def test_every_alias_points_at_a_hospital_that_exists(self):
        for word, alias in hospitals.ALIASES.items():
            with self.subTest(word=word):
                self.assertIn(alias.codcnh, self.index.by_code)
                self.assertTrue(alias.why.strip())

    def test_the_rows_read_by_hand_still_come_out_right(self):
        """The second sample: rows carrying no code, labelled by reading.

        The coded rows are the clean population and flattered two rules that
        were wrong -- this is where that was caught, so it is pinned here.
        """
        for nombre, localidad, cod_postal, expected in [
                ("Hospital Ramón y Cajal", "Madrid", "28034", "280029"),
                ("Hospital General Universitario Gregorio Marañón", "Madrid",
                 "28009", "280246"),
                ("Hospital de la Santa Creu i Sant Pau", "Barcelona",
                 "08025", "080291"),
                ("Clinica Universidad de Navarra", "Madrid", "28027",
                 "281393")]:
            with self.subTest(nombre=nombre):
                result = match(self.index, nombre, localidad, cod_postal)
                self.assertIsNotNone(result.hospital, result.why)
                self.assertEqual(result.hospital.codcnh, expected)

    def test_the_things_that_are_not_hospitals_are_refused(self):
        for nombre, localidad, cod_postal in [
                ("Vall D'hebron Institut De Recerca", "Barcelona", "08035"),
                ("CAP Balafia-Pardinyes-Secà de Sant Pere", "Lleida",
                 "25005"),
                ("Centro de Especialidades San Jose Obrero", "Málaga",
                 "29006")]:
            with self.subTest(nombre=nombre):
                self.assertIsNone(
                    match(self.index, nombre, localidad, cod_postal).hospital)


if __name__ == "__main__":
    unittest.main()
