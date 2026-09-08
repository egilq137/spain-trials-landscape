"""Tests for analysis.sponsors.

Success criteria:
  classify: the hand list wins over the markers, an industry marker wins over
    a personal title, and anything the two cannot settle is Unclassified
    rather than pushed into whichever answer the chart wanted
  individuals: a person sponsoring their own trial keeps the trial, counts as
    academic, and loses the name -- PROJECT_SPEC 3.2b
  markers: whole-word only, so 'AB' does not match inside ABBOTT and the
    rule keeps meaning something
  share_by_year: three classes summing to 100%, because a trial has exactly
    one sponsor
  phase_four_by_year: phase IV counted within each class, which is what
    separates "the group does less of it" from "the group got smaller"
  against the database: the classification settles 94.6% of trials, and the
    two findings 3.3 quotes
"""

import sqlite3
import unittest
from pathlib import Path

from analysis.sponsors import (
    ACADEMIC,
    CLASSES,
    HAND_CLASSIFIED,
    INDIVIDUAL,
    INDUSTRY,
    UNCLASSIFIED,
    classified_studies,
    classify,
    display_name,
    is_individual,
    phase_four_by_year,
    phase_four_figure,
    share_by_year,
    share_figure,
)

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "trials.db"

requires_database = unittest.skipUnless(
    DB_PATH.exists(),
    "data/trials.db is a build artifact; run `python run_pipeline.py build`")


class TestClassify(unittest.TestCase):
    def test_a_legal_form_makes_it_industry(self):
        for name in ("Novartis Farmacéutica, S.A.", "Pfizer Inc.",
                     "AbbVie Deutschland GmbH & Co. KG", "AstraZeneca AB",
                     "Novo Nordisk A/S", "BioNTech SE"):
            with self.subTest(sponsor=name):
                self.assertEqual(classify(name), INDUSTRY)

    def test_an_institution_makes_it_academic(self):
        for name in ("Hospital Universitario La Paz",
                     "Fundació Clínic per a la Recerca Biomèdica",
                     "Universidad de Navarra", "CIBER de Enfermedades"):
            with self.subTest(sponsor=name):
                self.assertEqual(classify(name), ACADEMIC)

    def test_the_hand_list_beats_the_markers(self):
        # Servier's research arm carries 'Institut' and is still Servier.
        self.assertEqual(classify("Institut de Recherches Internationales "
                                  "Servier"), INDUSTRY)
        # And a name with no marker at all that the list settles.
        self.assertEqual(classify("Unicancer"), ACADEMIC)

    def test_a_name_matching_both_is_unclassified_when_unlisted(self):
        # No tie-break rule: one would decide exactly the sponsors nobody
        # checked, in whichever direction the rule was written.
        self.assertEqual(classify("Something Institute Ltd"), UNCLASSIFIED)

    def test_a_name_matching_neither_is_unclassified(self):
        self.assertEqual(classify("Argenx BVBA Unlisted Variant"),
                         UNCLASSIFIED)

    def test_markers_match_whole_words_only(self):
        # 'AB' inside ABBOTT, 'SE' inside SERVIER: a substring rule would
        # classify half the corpus by accident.
        self.assertEqual(classify("ABBOTT"), UNCLASSIFIED)
        self.assertEqual(classify("Fundacion SERVIER"), ACADEMIC)

    def test_every_hand_entry_is_a_real_class(self):
        self.assertTrue(set(HAND_CLASSIFIED.values()) <= {INDUSTRY, ACADEMIC})


class TestIndividuals(unittest.TestCase):
    def test_a_person_is_academic_and_loses_their_name(self):
        name = "Dra. Cristina Avendaño Solá"
        self.assertTrue(is_individual(name))
        self.assertEqual(classify(name), ACADEMIC)
        self.assertEqual(display_name(name), INDIVIDUAL)

    def test_a_company_named_after_a_doctor_is_not_a_person(self):
        # 'Dr. Falk Pharma GmbH' is a German company with 14 trials. The
        # title says how the name begins; the legal form says what it is.
        name = "Dr. Falk Pharma GmbH"
        self.assertFalse(is_individual(name))
        self.assertEqual(classify(name), INDUSTRY)
        self.assertEqual(display_name(name), name)

    def test_an_organisation_keeps_its_name(self):
        self.assertEqual(display_name("Hospital Clínic de Barcelona"),
                         "Hospital Clínic de Barcelona")


class TestShareByYear(unittest.TestCase):
    ROWS = [("s1", 2015, INDUSTRY), ("s2", 2015, INDUSTRY),
            ("s3", 2015, ACADEMIC), ("s4", 2015, UNCLASSIFIED),
            ("s5", 2016, ACADEMIC)]

    def test_the_three_classes_sum_to_100(self):
        # A trial has exactly one sponsor in REEC, which makes this the
        # second chart in the project able to say so.
        for _, shares in share_by_year(self.ROWS):
            with self.subTest(shares=shares):
                self.assertAlmostEqual(sum(shares.values()), 100.0)

    def test_shares_are_of_that_years_trials(self):
        shares = dict(share_by_year(self.ROWS))
        self.assertEqual(shares[2015][INDUSTRY], 50.0)
        self.assertEqual(shares[2016][ACADEMIC], 100.0)

    def test_a_class_with_no_trials_that_year_is_zero(self):
        # Zero here, unlike the phase I subgroup rates, because the class
        # existed and could have sponsored something: the denominator is the
        # year's trials, and it is not empty.
        shares = dict(share_by_year(self.ROWS))
        self.assertEqual(shares[2016][INDUSTRY], 0.0)

    def test_every_class_appears_every_year(self):
        for _, shares in share_by_year(self.ROWS):
            self.assertEqual(set(shares), set(CLASSES))


class TestFigures(unittest.TestCase):
    SHARES = [(2013, {INDUSTRY: 76.0, ACADEMIC: 15.2, UNCLASSIFIED: 8.8}),
              (2026, {INDUSTRY: 85.8, ACADEMIC: 11.6, UNCLASSIFIED: 2.7})]
    PHASE_FOUR = [(2013, INDUSTRY, 577, 37), (2013, ACADEMIC, 115, 35),
                  (2026, INDUSTRY, 578, 12), (2026, ACADEMIC, 78, 32)]

    def test_the_share_chart_carries_the_classified_only_line(self):
        # The confound: unclassified shrank over the window, so some of the
        # industry rise is trials becoming classifiable.
        figure = share_figure(self.SHARES)
        self.assertEqual([trace.name for trace in figure.data][-1],
                         "Industry, of classified trials only")
        self.assertAlmostEqual(list(figure.data[-1].y)[0], 83.3, places=0)
        self.assertAlmostEqual(list(figure.data[-1].y)[-1], 88.1, places=1)

    def test_the_phase_four_chart_is_within_class_shares(self):
        figure = phase_four_figure(self.PHASE_FOUR)
        industry, academic = figure.data
        self.assertAlmostEqual(list(academic.y)[0], 100 * 35 / 115, places=1)
        self.assertAlmostEqual(list(industry.y)[-1], 100 * 12 / 578, places=1)

    def test_both_charts_end_every_line_in_its_value(self):
        for figure in (share_figure(self.SHARES),
                       phase_four_figure(self.PHASE_FOUR)):
            with self.subTest(figure=figure.layout.title.text[:20]):
                self.assertEqual(len(figure.layout.annotations),
                                 len(figure.data))


@requires_database
class TestAgainstDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(
            "file:{}?mode=ro".format(DB_PATH.as_posix()), uri=True)
        cls.rows = classified_studies(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def counts(self):
        totals = dict.fromkeys(CLASSES, 0)
        for _, _, sponsor_class in self.rows:
            totals[sponsor_class] += 1
        return totals

    def test_the_classification_covers_the_corpus_it_claims_to(self):
        totals = self.counts()
        self.assertEqual(sum(totals.values()), 11834)
        self.assertEqual(totals[INDUSTRY], 9407)
        self.assertEqual(totals[ACADEMIC], 1783)
        self.assertEqual(totals[UNCLASSIFIED], 644)

    def test_every_hand_written_name_matches_a_real_sponsor(self):
        # A hand table whose keys match nothing does nothing quietly. The
        # same test the centre corrections carry, for the same reason.
        for name in HAND_CLASSIFIED:
            with self.subTest(sponsor=name):
                self.assertEqual(
                    self.con.execute("SELECT count(*) FROM sponsors "
                                     "WHERE promotor = ?", (name,)
                                     ).fetchone()[0], 1)

    def test_no_unclassified_sponsor_is_large_enough_to_matter(self):
        # The hand list is drawn at five trials, so nothing above that may
        # be left unclassified. If a refresh adds one, this fails and the
        # list gets read again rather than quietly drifting.
        big = self.con.execute(
            """SELECT sp.promotor, count(*) n
                 FROM studies st
                 JOIN sponsors sp ON sp.sponsor_id = st.sponsor_id
                WHERE st.fecha_autorizacion_aemps >= '2013-01-01'
             GROUP BY sp.promotor HAVING n >= 5""").fetchall()
        unresolved = sorted(name for name, _ in big
                            if classify(name) == UNCLASSIFIED)
        # MedSIR is left out on purpose: an independent research
        # organisation is neither a pharmaceutical company nor a public
        # institution, and guessing would be worse than saying so.
        self.assertEqual(
            unresolved, ["Medica Scientia Innovation Research (MedSIR)"])

    def test_industry_and_academia_run_different_research(self):
        # The 3.3 finding, and the reason the sponsor split was worth
        # building: a tenfold difference in phase IV, and double in phase I.
        sponsor_class = {study: name for study, _, name in self.rows}
        totals = {name: [0, 0, 0] for name in CLASSES}
        for study, phase_one, phase_four in self.con.execute(
                """SELECT identificador, fase_uno, fase_cuatro FROM studies
                    WHERE fecha_autorizacion_aemps >= '2013-01-01'"""):
            row = totals[sponsor_class[study]]
            row[0] += 1
            row[1] += phase_one
            row[2] += phase_four
        industry, academic = totals[INDUSTRY], totals[ACADEMIC]
        self.assertAlmostEqual(100 * industry[2] / industry[0], 3.5, places=1)
        self.assertAlmostEqual(100 * academic[2] / academic[0], 33.6, places=1)
        self.assertAlmostEqual(100 * industry[1] / industry[0], 25.5, places=1)
        self.assertAlmostEqual(100 * academic[1] / academic[0], 12.3, places=1)

    def test_academic_phase_four_intensity_did_not_fall(self):
        # The hypothesis this chart was built to test, and it fails: the
        # corpus-wide phase IV decline is not academic sponsors doing less
        # phase IV. Their rate is flat; there are simply fewer of them.
        rows = phase_four_by_year(self.con, self.rows)
        academic = [100.0 * phase_four / trials
                    for _, name, trials, phase_four in rows
                    if name == ACADEMIC]
        industry = [100.0 * phase_four / trials
                    for _, name, trials, phase_four in rows
                    if name == INDUSTRY]
        self.assertGreater(academic[-1], academic[0])
        self.assertLess(industry[-1], industry[0] / 2)


if __name__ == "__main__":
    unittest.main()
