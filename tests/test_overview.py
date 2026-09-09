"""Tests for analysis.overview.

Success criteria:
  corpus, not tables: every count is of the studies authorised from the
    coverage boundary, so the KPI row cannot quote a bigger corpus than the
    charts drawn beneath it
  the sponsor gap is a mechanism, not a magic number: a sponsor appearing only
    on excluded studies is not counted, which is exactly why the real corpus
    has 2,957 sponsors against 2,959 rows in the table
  bridges: centres and areas are counted through their bridge to studies, so
    they drop out with the studies that used them
  since moves everything together: one floor, five numbers, no card scoped
    differently from its neighbours
  data_cut: delegated to volume.coverage, so the date on the KPI row is the
    same object as the date in every chart subtitle
  against the database: the five headline numbers, and the two places they
    deliberately disagree with run_pipeline.EXPECTED_ROWS
"""

import sqlite3
import unittest
from pathlib import Path

from analysis.overview import Totals, corpus_totals
from tests.test_loader import LoaderTestCase

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "trials.db"

requires_database = unittest.skipUnless(
    DB_PATH.exists(),
    "data/trials.db is a build artifact; run `python run_pipeline.py build`")


class OverviewTestCase(LoaderTestCase):
    """One excluded study and two analysed ones, each with its own everything.

    The excluded study is given a sponsor, a centre and an area that no other
    study shares, so every count has something to lose if the floor stops
    being applied.
    """

    def corpus(self):
        self.write_year(2019, [
            self.study(
                "old",
                calendario={"fechaAutorizacionAEMPS": "12-05-2011"},
                organismo={"promotor": "Old Pharma"},
                centros={"centro": [{"referencia": "ORG-OLD",
                                     "nombre": "Hospital Antiguo",
                                     "localidad": "Soria", "codPostal": "42001",
                                     "provincia": "Soria",
                                     "ccaa": "Castilla y Leon"}]},
                areasTerapeuticas={"area": [{"eutct": "C01",
                                             "nombre_es": "Infecciosas",
                                             "nombre_en": "Infections"}]}),
            self.study(
                "new-one",
                calendario={"fechaAutorizacionAEMPS": "04-03-2015"},
                organismo={"promotor": "New Pharma"}),
            self.study(
                "new-two",
                calendario={"fechaAutorizacionAEMPS": "02-06-2019"},
                organismo={"promotor": "New Pharma"}),
        ])
        con, _ = self.load()
        return con


class TestCorpusTotals(OverviewTestCase):
    def test_it_counts_the_analysed_corpus_and_not_the_tables(self):
        # Three studies are loaded; one is authorised before the boundary.
        con = self.corpus()
        self.assertEqual(con.execute("SELECT count(*) FROM studies"
                                     ).fetchone()[0], 3)
        self.assertEqual(corpus_totals(con).trials, 2)

    def test_a_sponsor_only_on_excluded_studies_is_not_counted(self):
        # The 2,959 / 2,957 gap in miniature. Old Pharma keeps its row and
        # loses its trials, so it is in the table and not in the landscape.
        con = self.corpus()
        self.assertEqual(con.execute("SELECT count(*) FROM sponsors"
                                     ).fetchone()[0], 2)
        self.assertEqual(corpus_totals(con).sponsors, 1)

    def test_centres_and_areas_drop_out_with_their_studies(self):
        # Counted through the bridge, not as table rows -- which is the only
        # reason these two follow the floor at all.
        con = self.corpus()
        self.assertEqual(corpus_totals(con).centres, 1)
        self.assertEqual(corpus_totals(con).areas, 1)

    def test_since_moves_every_count_together(self):
        con = self.corpus()
        self.assertEqual(
            corpus_totals(con, since=2011)[:4], (3, 2, 2, 2))

    def test_data_cut_is_the_latest_authorisation_whatever_the_floor(self):
        # It describes the database, not the slice, so lowering the floor
        # cannot move it.
        con = self.corpus()
        self.assertEqual(corpus_totals(con).data_cut, "2019-06-02")
        self.assertEqual(corpus_totals(con, since=2011).data_cut, "2019-06-02")


@requires_database
class TestAgainstDatabase(unittest.TestCase):
    """The five numbers the dashboard leads with, re-measured."""

    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(
            "file:{}?mode=ro".format(DB_PATH.as_posix()), uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_the_headline_numbers(self):
        self.assertEqual(
            corpus_totals(self.con),
            Totals(trials=11834, sponsors=2957, centres=3293, areas=55,
                   data_cut="2026-08-26"))

    def test_where_it_deliberately_disagrees_with_expected_rows(self):
        # run_pipeline.EXPECTED_ROWS counts loaded rows and has to keep the 9
        # excluded studies; these count the analysed corpus. Both are right
        # about their own question. This test exists so that the day someone
        # "fixes" one to match the other, they have to delete a test that
        # explains why they differ.
        totals = corpus_totals(self.con)
        rows = lambda table: self.con.execute(
            "SELECT count(*) FROM {}".format(table)).fetchone()[0]
        self.assertEqual(rows("studies") - totals.trials, 9)
        self.assertEqual(rows("sponsors") - totals.sponsors, 2)
        # And where they agree, they agree for a reason rather than by luck:
        # no centre and no area is used only by an excluded study.
        self.assertEqual(rows("centers"), totals.centres)
        self.assertEqual(rows("therapeutic_areas"), totals.areas)


if __name__ == "__main__":
    unittest.main()
