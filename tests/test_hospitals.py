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
  verdicts: four outcomes, not two. A catalogue of hospitals is supposed to
    refuse a research institute, and that refusal is an answer -- it must not
    be reported in the same breath as a hospital the rule failed to follow
  against the database: the 324 rows carrying a CODCNH are the calibration
    set, and the accuracy measured on them is pinned here so a change to the
    synonym table or the thresholds cannot quietly trade it away
"""

import collections
import re
import sqlite3
import unittest
from pathlib import Path

from analysis import hospitals
from analysis.hospitals import (ACCEPT, AMBIGUOUS, MATCHED, NEAR,
                                ambiguous_cases, ambiguous_page,
                                NEAR_MISS, NO_CANDIDATE, Index,
                                load_hospitals, match, similarity, tokens)

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

    def test_a_company_that_renamed_itself_is_still_one_company(self):
        # Quirón became Quirónsalud in 2016; the 2024 catalogue uses the new
        # name and REEC rows still carry the old one.
        self.assertEqual(similarity("Hospital Quiron Zaragoza",
                                    "Hospital Quironsalud Zaragoza"), 1.0)


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
        # Two catalogue entries the name cannot separate. Both score well, so
        # the floor lets them through and only the margin stops the matcher
        # picking one at random.
        #
        # The real shape is Institut Català d'Oncologia, listed once per
        # campus -- but this fixture must not *be* it. A name a decision
        # covers never reaches the scoring path at all, so writing one here
        # would leave a test that passes while measuring nothing. It has
        # happened: this test used the ICO name until ICO Badalona was
        # decided, and then it stopped testing the margin.
        index = Index([
            hospital(codcnh="080001", nombre="Institut Oncològic Comarcal",
                     municipio="Badalona", cod_postal="08916"),
            hospital(codcnh="080002", nombre="Institut Oncològic Comarcal",
                     municipio="Badalona", cod_postal="08916"),
        ])
        result = match(index, "Institut Oncologic Comarcal", "Badalona",
                       "08916")
        self.assertGreaterEqual(result.score, ACCEPT)
        self.assertIsNone(result.hospital)
        self.assertEqual(result.verdict, AMBIGUOUS)

    def test_a_decision_naming_a_missing_code_is_reported_not_raised(self):
        """`index` is injected, so a caller can hand `match` a catalogue that
        does not hold the hospital a decision names -- this fixture is one.

        The row comes back undecided with the code in `why`, rather than
        taking the process down or silently falling back to the score.
        """
        key = next(key for key, answer in hospitals.ANSWERS.items()
                   if answer.codcnh is not None)
        nombre, localidad = key[0], key[1]
        result = match(self.index, nombre, localidad, "08916")
        self.assertIsNone(result.hospital)
        self.assertEqual(result.verdict, NO_CANDIDATE)
        self.assertIn(hospitals.ANSWERS[key].codcnh, result.why)

    def test_it_refuses_what_is_not_a_hospital(self):
        result = match(self.index, "CAP Balafia-Pardinyes", "Madrid", "28046")
        self.assertIsNone(result.hospital)
        self.assertEqual(result.verdict, NO_CANDIDATE)

    def test_a_near_miss_is_not_filed_as_an_absence(self):
        # IRYCIS shares two words with the hospital it sits inside and
        # nothing else: 0.29, above NEAR and under ACCEPT. That band is
        # where a hospital under an unfamiliar name hides, so it is a
        # verdict of its own and not part of the no-candidate count.
        result = match(self.index,
                       "Instituto Ramón y Cajal de Investigación Sanitaria",
                       "Madrid", "28001")
        self.assertIsNone(result.hospital)
        self.assertEqual(result.verdict, NEAR_MISS)
        self.assertGreaterEqual(result.score, NEAR)
        self.assertLess(result.score, ACCEPT)

    def test_a_match_says_so(self):
        result = match(self.index, "HOSPITAL UNIVERSITARIO LA PAZ", "Madrid",
                       "28046")
        self.assertEqual(result.verdict, MATCHED)

    def test_a_refusal_still_names_the_closest(self):
        # A rejection a reader cannot see the near-miss for is one they
        # cannot judge.
        result = match(self.index, "CAP Balafia-Pardinyes", "Madrid", "28046")
        self.assertIsNotNone(result.closest)

    def test_nowhere_to_look_is_its_own_answer(self):
        result = match(self.index, "Hospital", "", "")
        self.assertIsNone(result.hospital)
        self.assertEqual(result.verdict, NO_CANDIDATE)
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

    def test_every_decision_points_at_a_hospital_that_exists(self):
        """The same guarantee ALIASES has, for the two decision tables.

        A decision naming a code the catalogue does not hold is a decision
        that cannot be carried out, and `match` reaches for it by key.
        """
        for table in (hospitals.ANSWERS, hospitals.PROPOSED):
            for key, answer in table.items():
                if answer.codcnh is None:
                    continue
                with self.subTest(key=key):
                    self.assertIn(answer.codcnh, self.index.by_code)
                    self.assertTrue(answer.why.strip())

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

    def test_the_refusals_are_two_different_answers(self):
        """The reason the verdict exists.

        Most refusals are the catalogue correctly not listing something that
        is not a hospital; a much smaller pile is worth reading. If a change
        ever collapses that split -- everything landing in one bucket -- the
        page goes back to implying thousands of rows of pending work.
        """
        verdicts = collections.Counter(
            match(self.index, nombre, localidad, cod_postal).verdict
            for nombre, localidad, cod_postal in self.con.execute(
                "SELECT nombre, localidad, cod_postal FROM centers"))
        self.assertGreater(verdicts[NO_CANDIDATE], verdicts[NEAR_MISS])
        self.assertGreater(verdicts[NEAR_MISS], 0)
        self.assertGreater(verdicts[AMBIGUOUS], 0)
        # Note what this does *not* assert. Counted by centre, the rows with
        # no plausible candidate outnumber the matches -- REEC's long tail is
        # institutes and health centres. Matching dominates by trial-site
        # link, not by row, and the review page has to say which it means.
        self.assertGreater(verdicts[MATCHED], verdicts[NEAR_MISS])


if __name__ == "__main__":
    unittest.main()


@requires_database
class TestAmbiguousCases(unittest.TestCase):
    """The form the undecidable rows get decided on."""

    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(
            "file:{}?mode=ro".format(DB_PATH.as_posix()), uri=True)
        cls.index = Index(load_hospitals(CATALOGUE))
        cls.cases = ambiguous_cases(cls.con, cls.index)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_a_question_is_asked_once(self):
        """REEC spells Institut Català d'Oncologia several ways in Badalona.
        Asked twice, a form gets two chances to be answered differently."""
        keys = [(" ".join(hospitals.fold(case.nombre)), case.localidad)
                for case in self.cases]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_ambiguous_row_reaches_the_form(self):
        rows = [row for row in hospitals.match_centres(self.con, self.index)
                if row[4].verdict == AMBIGUOUS]
        self.assertEqual(sum(case.rows for case in self.cases), len(rows))
        self.assertEqual(sum(case.trials for case in self.cases),
                         sum(row[3] for row in rows))

    def test_the_busiest_case_is_first(self):
        # The page is read from the top, so the rows that matter are there.
        trials = [case.trials for case in self.cases]
        self.assertEqual(trials, sorted(trials, reverse=True))

    def test_every_suggestion_states_a_reason(self):
        """A pre-ticked radio nobody can disagree with is not a question."""
        for case in self.cases:
            with self.subTest(nombre=case.nombre):
                self.assertEqual(bool(case.suggested), bool(case.reason))

    def test_a_suggestion_is_either_read_or_the_only_one_in_town(self):
        for case in self.cases:
            if not case.suggested:
                continue
            with self.subTest(nombre=case.nombre):
                key = (" ".join(hospitals.fold(case.nombre)),
                       hospitals._town(case.localidad))
                if key in hospitals.PROPOSED:
                    self.assertEqual(
                        case.suggested,
                        hospitals.PROPOSED[key].codcnh or "NONE")
                else:
                    self.assertEqual(
                        case.suggested, hospitals._same_town(case.candidates,
                                                             case.localidad))

    def test_a_proposal_changes_nothing_until_it_is_confirmed(self):
        """The whole reason PROPOSED is a second table.

        Every key in it is still an unanswered question, so the matcher must
        still refuse those rows -- a proposal that quietly behaved like a
        decision would be a decision nobody made.
        """
        self.assertTrue(hospitals.PROPOSED)
        for case in self.cases:
            key = (" ".join(hospitals.fold(case.nombre)),
                   hospitals._town(case.localidad))
            if key not in hospitals.PROPOSED:
                continue
            with self.subTest(nombre=case.nombre):
                self.assertEqual(
                    match(self.index, case.nombre, case.localidad,
                          case.cod_postal).verdict, AMBIGUOUS)

    def test_no_decision_is_written_twice(self):
        """A duplicate key in a dict literal loses silently: Python keeps the
        last one and nothing complains, so a decision can be overwritten by
        another without anybody seeing it. It has happened once -- stripping
        the leading article made two spellings of the dental hospital's town
        into one key. Read from the source, because by the time the module is
        imported the evidence is gone."""
        import ast

        source = ast.parse(
            (ROOT / "analysis" / "hospitals.py").read_text(encoding="utf-8"))
        for node in ast.walk(source):
            if not isinstance(node, ast.Assign):
                continue
            name = getattr(node.targets[0], "id", "")
            if name not in ("ANSWERS", "PROPOSED"):
                continue
            with self.subTest(table=name):
                keys = [ast.literal_eval(key) for key in node.value.keys]
                self.assertEqual(len(keys), len(set(keys)))

    def test_a_key_survives_its_own_normaliser(self):
        """Both tables are keyed on `normalise_town`'s output, so a change to
        that function silently invalidates every key written before it.

        It has happened once: stripping the leading article turned
        `l'hospitalet de llobregat` into `hospitalet de llobregat` and the
        ICO decision, 1,316 trial-links of it, stopped applying. Nothing
        errored; the rows simply went back to being ambiguous.
        """
        from analysis.geography import normalise_town

        for table in (hospitals.ANSWERS, hospitals.PROPOSED):
            for name, town in table:
                with self.subTest(town=town):
                    self.assertEqual(normalise_town(town), town)

    def test_the_answers_are_reachable(self):
        """A key that matches no row is a decision that does nothing.

        Both tables are keyed on a folded name and a normalised town, and
        either of those can be retyped wrong or go stale when the pipeline
        is rebuilt. This is how that gets noticed.
        """
        rows = {(" ".join(hospitals.fold(nombre)), hospitals._town(localidad))
                for nombre, localidad in self.con.execute(
                    "SELECT nombre, localidad FROM centers")}
        for table in (hospitals.ANSWERS, hospitals.PROPOSED):
            for key in table:
                with self.subTest(key=key):
                    self.assertIn(key, rows)

    def test_a_decision_overrules_both_the_score_and_the_town(self):
        """Ribera Salud runs the Alzira hospital; REEC files the row in
        Valencia. Neither the name nor the geography gets there, which is
        what a read decision is for."""
        result = match(self.index, "Hospital Ribera Salud", "Valencia",
                       "46600")
        self.assertEqual(result.verdict, MATCHED)
        self.assertEqual(result.hospital.codcnh, "460351")
        self.assertEqual(result.hospital.municipio, "Alzira")
        self.assertIn("read:", result.why)

    def test_the_page_offers_every_candidate_and_the_two_ways_out(self):
        page = ambiguous_page(self.cases[:3])
        for case in self.cases[:3]:
            for _, hospital in case.candidates:
                self.assertIn("value='{}'".format(hospital.codcnh), page)
        self.assertIn("value='NONE'", page)
        self.assertIn("value='UNSURE'", page)

    def test_the_page_never_shows_the_score_without_its_candidate(self):
        # A radio with no label is a decision made blind.
        page = ambiguous_page(self.cases)
        self.assertEqual(page.count("<input type='radio'"),
                         sum(len(case.candidates) + 2 for case in self.cases))
