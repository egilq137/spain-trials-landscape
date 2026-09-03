"""Tests for analysis.volume.

Success criteria:
  trials_per_year: counts on the authorisation date and not the registration
    date -- the two disagree for a quarter of the corpus, and only one of
    them answers "when did this trial start"
  since: filters, and never filters silently -- coverage() reports how many
    studies the floor excluded, so a chart that starts at 2013 can say what
    it left out rather than the reader assuming nothing was there
  data_cut: the latest authorisation date, so the partial final year can be
    marked. A year eight months long is not a collapse in activity
  gaps: a year nothing was authorised in is absent, not zero -- a GROUP BY
    cannot invent it, and the caller should know that before plotting a line
  against the database: the series reproduces the PROJECT_SPEC 3.2d crosstab
    -- 14 years, 11,834 studies, the 9 pre-2013 records excluded
  figure: draws exactly the series it is handed, hatches only the partial
    year, states both exclusions in words as well as in marks, and puts the
    CTIS mandate on the axis between 2022 and 2023 rather than in a legend
"""

import sqlite3
import unittest
from pathlib import Path

from analysis.volume import Coverage, coverage, figure, trials_per_year
from tests.test_loader import LoaderTestCase

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "trials.db"

requires_database = unittest.skipUnless(
    DB_PATH.exists(),
    "data/trials.db is a build artifact; run `python run_pipeline.py build`")


class VolumeTestCase(LoaderTestCase):
    """Fixtures go in through the loader, so the rows are rows it would write.

    Inserting into `studies` directly would be shorter and would encode this
    test's own idea of the schema; a query tested against rows no loader
    produced is tested against nothing.
    """

    def con_with(self, authorised, registered="19-12-2019"):
        """A database holding one study per authorisation date given."""
        self.write_year(2019, [
            self.study(date, calendario={"fechaAutorizacionAEMPS": date,
                                         "fechaRegistro": registered})
            for date in authorised])
        con, _ = self.load()
        return con


class TestTrialsPerYear(VolumeTestCase):
    def test_counts_the_authorisation_year_not_the_registration_year(self):
        # The whole point of the column choice: three studies registered on
        # one day in 2021, authorised across two earlier years. Grouping on
        # fecha_registro would report a single spike in 2021 -- which is
        # exactly what REEC's 2017-11-02 backload would do to the real data.
        con = self.con_with(["04-03-2015", "18-12-2015", "02-06-2019"],
                            registered="10-05-2021")
        self.assertEqual(trials_per_year(con), [(2015, 2), (2019, 1)])

    def test_since_excludes_earlier_years(self):
        con = self.con_with(["12-05-2011", "04-03-2013"])
        self.assertEqual(trials_per_year(con), [(2013, 1)])
        self.assertEqual(trials_per_year(con, since=2011),
                         [(2011, 1), (2013, 1)])

    def test_a_year_with_no_authorisations_is_absent_not_zero(self):
        # Documented rather than fixed: the chart draws bars, and a missing
        # bar is honest. A line chart would need the zeros filled in first.
        con = self.con_with(["04-03-2013", "04-03-2015"])
        self.assertEqual(trials_per_year(con), [(2013, 1), (2015, 1)])


class TestCoverage(VolumeTestCase):
    def test_it_reports_what_since_excluded(self):
        con = self.con_with(["12-05-2011", "01-02-2012", "04-03-2013"])
        self.assertEqual(coverage(con).excluded, 2)
        self.assertEqual(coverage(con, since=2011).excluded, 0)

    def test_data_cut_is_the_latest_authorisation(self):
        con = self.con_with(["04-03-2013", "26-08-2026", "02-06-2019"])
        self.assertEqual(coverage(con).data_cut, "2026-08-26")

    def test_data_cut_ignores_the_since_floor(self):
        # It describes the database, not the slice: the last date is the last
        # date whichever year the chart happens to start at.
        con = self.con_with(["12-05-2011", "26-08-2026"])
        self.assertEqual(coverage(con, since=2020).data_cut, "2026-08-26")


class TestFigure(unittest.TestCase):
    """The chart is a pure function of the series, so it is testable.

    Nothing here checks that it looks good -- that needs eyes, and it got
    them. These pin the claims the chart makes about the data, which is the
    part that can silently stop being true when the query changes.
    """

    SERIES = [(2021, 90), (2022, 100), (2023, 80), (2024, 40)]
    COVER = Coverage(data_cut="2024-08-26", excluded=7)

    def setUp(self):
        self.fig = figure(self.SERIES, self.COVER)

    def test_it_draws_the_series_it_was_given(self):
        bars, = self.fig.data
        self.assertEqual(list(bars.x), [2021, 2022, 2023, 2024])
        self.assertEqual(list(bars.y), [90, 100, 80, 40])

    def test_only_the_partial_year_is_hatched(self):
        # The hatch is per-bar rather than a second trace, so a shifted data
        # cut cannot leave it on the wrong bar.
        self.assertEqual(self.fig.data[0].marker.pattern.shape,
                         ("", "", "", "/"))

    def test_the_mandate_is_a_line_between_the_two_years(self):
        # Between 2022 and 2023, not on either bar: the boundary is a date,
        # and no bar belongs to both sides of it.
        self.assertEqual([shape.x0 for shape in self.fig.layout.shapes],
                         [2022.5])

    def test_both_exclusions_are_stated_in_words(self):
        # A hatch is a hint; the reader is told in a sentence as well.
        subtitle = self.fig.layout.title.subtitle.text
        self.assertIn("2024-08-26", subtitle)
        self.assertIn("7 trials", subtitle)
        self.assertIn("before 2013", subtitle)

    def test_one_series_carries_no_legend(self):
        self.assertFalse(self.fig.layout.showlegend)


@requires_database
class TestAgainstDatabase(unittest.TestCase):
    """Re-measures what PROJECT_SPEC 3.2d claims about the series."""

    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(
            "file:{}?mode=ro".format(DB_PATH.as_posix()), uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_the_series_is_the_one_3_2d_tabulates(self):
        self.assertEqual(
            trials_per_year(self.con),
            [(2013, 759), (2014, 714), (2015, 804), (2016, 791),
             (2017, 779), (2018, 800), (2019, 831), (2020, 1027),
             (2021, 996), (2022, 922), (2023, 846), (2024, 929),
             (2025, 962), (2026, 674)])

    def test_it_accounts_for_every_loaded_study(self):
        # 11,843 loaded, 9 authorised before the coverage boundary. If these
        # two ever stop adding up, a year has gone missing from the chart.
        total = sum(studies for _, studies in trials_per_year(self.con))
        self.assertEqual(total + coverage(self.con).excluded, 11843)

    def test_the_data_cut_and_the_exclusions_are_reported(self):
        self.assertEqual(coverage(self.con), ("2026-08-26", 9))


if __name__ == "__main__":
    unittest.main()
