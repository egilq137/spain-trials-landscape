"""Tests for analysis.therapeutic.

Success criteria:
  trials_per_area: one row per area, counting studies, ordered; a trial that
    lists two areas is counted in both, because the source names no primary
    one -- this is the reason the bars out-total the trials, so it is tested
    rather than assumed
  since: the same coverage floor the volume chart uses, so the two charts
    cannot quote different denominators
  leaf: drops the branch prefix and keeps the leaf code; a name with no
    prefix survives whole, which is what the two absence statements need
  ranked_areas: folds the tail into one Other bar, merges both absence codes
    into one Not specified bar, and puts both below the areas whatever their
    size -- rank 13 should not silently be a different kind of thing
  figure: hatches exactly the non-area bars, labels every tip, and leaves
    room for the longest label instead of clipping it
  top_areas: the biggest real areas, absence statements never among them
  area_counts_by_year: years come back as ints, so they match the volume
    query's keys -- the first draft plotted four flat lines at 0% because
    '2013' never matched 2013 and every share fell through to a zero default
  area_trends: shares are of the year's trials, the denominator is the volume
    chart's own, and an area with no trials in a year is 0% not a hole
  trend_figure: one line per area in fixed palette order, a dot on the last
    point only, a legend, and a value at the end of every line
  yearly_shares: one frame per year, the same bars in the same order in
    every frame, shares of that year's trials; the Other label counts the
    same areas in every frame, so it does not flicker as the animation runs
  race_figure: a frame per year named by it, a fixed x range so the bars are
    comparable across frames, and the year on the chart
  against the database: 55 areas, 12,276 memberships over 11,834 trials, and
    mental health on the chart rather than swept into Other
"""

import sqlite3
import unittest
from pathlib import Path

from analysis.therapeutic import (
    PALETTE,
    TOP_AREAS,
    Area,
    Share,
    Trend,
    area_counts_by_year,
    area_trends,
    figure,
    leaf,
    race_figure,
    ranked_areas,
    top_areas,
    trend_figure,
    trials_per_area,
    yearly_shares,
)
from analysis import volume
from tests.test_loader import LoaderTestCase

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "trials.db"

requires_database = unittest.skipUnless(
    DB_PATH.exists(),
    "data/trials.db is a build artifact; run `python run_pipeline.py build`")


def area(code, name):
    return {"eutct": code, "nombre_es": name, "nombre_en": name}


class AreaLoaderTestCase(LoaderTestCase):
    """A database built through the loader from (date, areas) fixtures."""

    def con_with(self, studies):
        """studies: [(authorisation date, [(code, name), ...])]."""
        self.write_year(2019, [
            self.study("{}{}".format(date, index),
                       calendario={"fechaAutorizacionAEMPS": date},
                       areasTerapeuticas={"area": [area(*a) for a in areas]})
            for index, (date, areas) in enumerate(studies)])
        con, _ = self.load()
        return con


class TestTrialsPerArea(AreaLoaderTestCase):
    def test_counts_studies_per_area_most_first(self):
        con = self.con_with([
            ("04-03-2015", [("C04", "Cancer")]),
            ("04-03-2016", [("C04", "Cancer")]),
            ("04-03-2017", [("C14", "Cardiovascular")])])
        self.assertEqual(trials_per_area(con),
                         [("C04", "Cancer", 2), ("C14", "Cardiovascular", 1)])

    def test_a_trial_in_two_areas_is_counted_in_both(self):
        # The whole reason the bars out-total the trials. One study, two
        # rows of one: no primary area exists to pick.
        con = self.con_with([
            ("04-03-2015", [("C04", "Cancer"), ("C14", "Cardiovascular")])])
        self.assertEqual([trials for _, _, trials in trials_per_area(con)],
                         [1, 1])

    def test_since_uses_the_same_floor_as_the_volume_chart(self):
        con = self.con_with([
            ("12-05-2011", [("C04", "Cancer")]),
            ("04-03-2013", [("C14", "Cardiovascular")])])
        self.assertEqual(trials_per_area(con),
                         [("C14", "Cardiovascular", 1)])
        self.assertEqual(len(trials_per_area(con, since=2011)), 2)


class TestLeaf(unittest.TestCase):
    def test_drops_the_branch_and_keeps_the_leaf_code(self):
        self.assertEqual(leaf("Diseases [C] - Cancer [C04]"), "Cancer [C04]")

    def test_a_name_without_a_branch_survives_whole(self):
        # 'Not possible to specify' has no prefix to strip, and losing it
        # would leave a bar with no label.
        self.assertEqual(leaf("Not possible to specify"),
                         "Not possible to specify")

    def test_only_the_first_separator_splits(self):
        self.assertEqual(leaf("Diseases [C] - Wounds - and Injuries [C21]"),
                         "Wounds - and Injuries [C21]")


class TestRankedAreas(unittest.TestCase):
    ROWS = [("C04", "Diseases [C] - Cancer [C04]", 40),
            ("C10", "Diseases [C] - Nervous System Diseases [C10]", 30),
            ("999999000486", "Not specified [CCC]", 9),
            ("C14", "Diseases [C] - Cardiovascular Diseases [C14]", 5),
            ("999999999999", "Not possible to specify", 4),
            ("C08", "Diseases [C] - Respiratory Tract Diseases [C08]", 3)]

    def test_the_top_areas_come_first_labelled_by_leaf(self):
        self.assertEqual(ranked_areas(self.ROWS, top=2)[:2],
                         [Area("Cancer [C04]", 40, True),
                          Area("Nervous System Diseases [C10]", 30, True)])

    def test_both_absence_codes_become_one_marked_bar(self):
        bars = ranked_areas(self.ROWS, top=2)
        self.assertIn(Area("Not specified", 13, False), bars)

    def test_the_tail_folds_into_one_other_bar_that_counts_its_areas(self):
        # Two areas are left over -- C14 and C08 -- and the absence codes are
        # not among them, or the label would count them as areas.
        self.assertEqual(ranked_areas(self.ROWS, top=2)[-1],
                         Area("Other (2 areas)", 8, False))

    def test_neither_fold_ever_outranks_a_real_area(self):
        # Not specified holds 13 trials against C14's 5 and C08's 3, and
        # still sits below both: rank 3 should not quietly be a different
        # kind of thing. (top=4 takes every area, so there is no Other bar.)
        bars = ranked_areas(self.ROWS, top=4)
        self.assertEqual([bar.label for bar in bars][-3:],
                         ["Cardiovascular Diseases [C14]",
                          "Respiratory Tract Diseases [C08]", "Not specified"])
        self.assertEqual([bar.substantive for bar in bars],
                         [True, True, True, True, False])

    def test_nothing_left_over_means_no_other_bar(self):
        rows = [row for row in self.ROWS if row[0].startswith("C")]
        self.assertEqual([bar.label for bar in ranked_areas(rows, top=4)],
                         ["Cancer [C04]", "Nervous System Diseases [C10]",
                          "Cardiovascular Diseases [C14]",
                          "Respiratory Tract Diseases [C08]"])

    def test_every_trial_membership_survives_the_folding(self):
        self.assertEqual(sum(bar.trials for bar in ranked_areas(self.ROWS, 2)),
                         sum(trials for _, _, trials in self.ROWS))


class TestFigure(unittest.TestCase):
    BARS = [Area("Cancer [C04]", 4000, True),
            Area("Nervous [C10]", 900, True),
            Area("Not specified", 200, False),
            Area("Other (41 areas)", 1900, False)]

    def setUp(self):
        self.fig = figure(self.BARS, trials=11834)

    def test_bars_run_longest_at_the_top(self):
        # Plotly draws a horizontal category axis bottom-up, so the order is
        # reversed on the way in; this is the assertion that catches it being
        # reversed twice or not at all.
        self.assertEqual(list(self.fig.data[0].y)[-1], "Cancer [C04]")
        self.assertEqual(list(self.fig.data[0].x)[-1], 4000)

    def test_exactly_the_non_areas_are_hatched(self):
        self.assertEqual(self.fig.data[0].marker.pattern.shape,
                         ("/", "/", "", ""))

    def test_every_bar_carries_its_value(self):
        self.assertEqual(self.fig.data[0].text,
                         ("1,900", "200", "900", "4,000"))

    def test_the_longest_label_has_room_outside_the_bar(self):
        # An outside tip label is drawn past the bar's end, and Plotly does
        # not widen the range for it -- at the default range the longest
        # bar's value was clipped.
        self.assertGreater(self.fig.layout.xaxis.range[1], 4000)

    def test_one_series_carries_no_legend(self):
        self.assertFalse(self.fig.layout.showlegend)


class TestTopAreas(unittest.TestCase):
    def test_takes_the_biggest_real_areas_in_order(self):
        self.assertEqual(top_areas(TestRankedAreas.ROWS, count=2),
                         [("C04", "Diseases [C] - Cancer [C04]"),
                          ("C10", "Diseases [C] - Nervous System Diseases "
                                  "[C10]")])

    def test_an_absence_code_is_never_picked(self):
        # 'Not specified' outranks two real areas in these rows; a line for
        # it would be a line for "the registry did not say".
        picked = dict(top_areas(TestRankedAreas.ROWS, count=4))
        self.assertNotIn("999999000486", picked)
        self.assertNotIn("999999999999", picked)
        self.assertEqual(len(picked), 4)


class TestAreaCountsByYear(AreaLoaderTestCase):
    def test_years_are_ints_so_they_match_the_volume_query(self):
        # The regression: substr() returns TEXT, analysis.volume returns int
        # years, and area_trends looks both up in one dict. A mismatch here
        # does not raise -- it silently draws every line at zero.
        con = self.con_with([("04-03-2015", [("C04", "Cancer")])])
        self.assertEqual(area_counts_by_year(con, ["C04"]),
                         [(2015, "C04", 1)])

    def test_no_codes_means_every_area(self):
        con = self.con_with([
            ("04-03-2015", [("C04", "Cancer"), ("C14", "Cardiovascular")])])
        self.assertEqual(sorted(area_counts_by_year(con)),
                         [(2015, "C04", 1), (2015, "C14", 1)])

    def test_it_counts_only_the_areas_asked_for(self):
        con = self.con_with([
            ("04-03-2015", [("C04", "Cancer"), ("C14", "Cardiovascular")])])
        self.assertEqual(area_counts_by_year(con, ["C14"]),
                         [(2015, "C14", 1)])

    def test_the_shares_come_out_of_the_end_of_the_real_pipeline(self):
        # End to end against a database, because that is the only place the
        # year types of the two queries meet.
        con = self.con_with([
            ("04-03-2015", [("C04", "Cancer")]),
            ("18-12-2015", [("C14", "Cardiovascular")])])
        trends = area_trends(area_counts_by_year(con, ["C04"]),
                             volume.trials_per_year(con),
                             [("C04", "Diseases [C] - Cancer [C04]")])
        self.assertEqual(trends, [Trend("Cancer [C04]", [2015], [50.0])])


class TestAreaTrends(unittest.TestCase):
    TOTALS = [(2013, 200), (2014, 100)]
    AREAS = [("C04", "Diseases [C] - Cancer [C04]"),
             ("C10", "Diseases [C] - Nervous System Diseases [C10]")]

    def test_shares_are_of_the_years_trials(self):
        rows = [(2013, "C04", 50), (2014, "C04", 40)]
        self.assertEqual(area_trends(rows, self.TOTALS, self.AREAS)[0],
                         Trend("Cancer [C04]", [2013, 2014], [25.0, 40.0]))

    def test_a_year_without_the_area_is_zero_not_a_hole(self):
        # The year happened and the area was available to choose, so 0% is
        # the honest value and a gap in the line would not be.
        rows = [(2014, "C10", 10)]
        self.assertEqual(area_trends(rows, self.TOTALS, self.AREAS)[1].shares,
                         [0.0, 10.0])

    def test_the_order_is_the_one_the_caller_asked_for(self):
        # Colour is assigned by position, so this order is what decides which
        # area is blue. It must not depend on what the SQL happened to return.
        trends = area_trends([], self.TOTALS, self.AREAS[::-1])
        self.assertEqual([trend.label for trend in trends],
                         ["Nervous System Diseases [C10]", "Cancer [C04]"])


class TestTrendFigure(unittest.TestCase):
    TRENDS = [Trend("Cancer [C04]", [2013, 2014], [25.0, 40.0]),
              Trend("Nervous [C10]", [2013, 2014], [5.0, 6.0])]

    def setUp(self):
        self.fig = trend_figure(self.TRENDS, data_cut="2014-08-26")

    def test_one_line_per_area_in_palette_order(self):
        self.assertEqual([trace.line.color for trace in self.fig.data],
                         list(PALETTE[:2]))

    def test_the_dot_sits_on_the_last_point_only(self):
        # A marker on every point would be a scatter plot of 14 dots per
        # line; the end dot is what the end label attaches to.
        self.assertEqual(self.fig.data[0].marker.size, (0, 8))

    def test_every_line_ends_in_its_value(self):
        # The last year's share, not the first: the label rides the end of
        # the line, which is where the eye leaves it.
        self.assertEqual([note.text for note in self.fig.layout.annotations],
                         ["40%", "6%"])

    def test_two_series_carry_a_legend(self):
        self.assertNotEqual(self.fig.layout.showlegend, False)
        self.assertEqual([trace.name for trace in self.fig.data],
                         ["Cancer [C04]", "Nervous [C10]"])

    def test_the_partial_year_is_named_in_the_subtitle(self):
        self.assertIn("2014", self.fig.layout.title.subtitle.text)


class TestYearlyShares(unittest.TestCase):
    TOTALS = [(2013, 200), (2014, 100)]
    AREAS = [("C04", "Diseases [C] - Cancer [C04]")]
    COUNTS = [(2013, "C04", 50), (2013, "999999000486", 20),
              (2013, "C14", 10), (2013, "C10", 4),
              (2014, "C04", 40), (2014, "999999999999", 3)]

    def frames(self):
        return yearly_shares(self.COUNTS, self.TOTALS, self.AREAS)

    def test_one_frame_per_year_in_year_order(self):
        self.assertEqual([year for year, _ in self.frames()], [2013, 2014])

    def test_the_bars_are_shares_of_that_years_trials(self):
        # 50 of 200 and 40 of 100: the same area, a bigger share of a
        # smaller year. Counting trials instead would show it shrinking.
        self.assertEqual([bars[0] for _, bars in self.frames()],
                         [Share("Cancer [C04]", 25.0, True),
                          Share("Cancer [C04]", 40.0, True)])

    def test_both_absence_codes_land_in_one_bar(self):
        first, second = (bars for _, bars in self.frames())
        self.assertEqual(first[1], Share("Not specified", 10.0, False))
        self.assertEqual(second[1], Share("Not specified", 3.0, False))

    def test_other_gathers_every_area_outside_the_top(self):
        # C14 and C10 in 2013: 14 of 200.
        self.assertEqual(self.frames()[0][1][2],
                         Share("Other (2 areas)", 7.0, False))

    def test_the_other_label_is_the_same_in_every_frame(self):
        # Counted over the whole corpus, not per year. Per year it would
        # read '2 areas' then '0 areas' and flicker as the animation ran.
        self.assertEqual({bars[-1].label for _, bars in self.frames()},
                         {"Other (2 areas)"})

    def test_every_frame_has_the_same_bars_in_the_same_order(self):
        self.assertEqual(*[[bar.label for bar in bars]
                           for _, bars in self.frames()])


class TestRaceFigure(unittest.TestCase):
    FRAMES = [(2013, [Share("Cancer [C04]", 25.0, True),
                      Share("Not specified", 10.0, False)]),
              (2014, [Share("Cancer [C04]", 40.0, True),
                      Share("Not specified", 3.0, False)])]

    def setUp(self):
        self.fig = race_figure(self.FRAMES, data_cut="2014-08-26")

    def test_a_frame_per_year_named_by_it(self):
        self.assertEqual([frame.name for frame in self.fig.frames],
                         ["2013", "2014"])

    def test_the_figure_opens_on_the_first_year(self):
        self.assertEqual(self.fig.data[0].text, ("10.0%", "25.0%"))

    def test_the_x_range_is_fixed_across_frames(self):
        # The point of the whole chart. On an autoscaling axis the longest
        # bar fills the width in every frame, and nothing appears to move.
        self.assertAlmostEqual(self.fig.layout.xaxis.range[1], 40.0 * 1.12)
        # No frame overrides it, so the range set above holds all the way
        # through the animation.
        self.assertEqual([frame.layout.xaxis.range
                          for frame in self.fig.frames], [None, None])

    def test_every_frame_carries_its_year(self):
        self.assertEqual([frame.layout.annotations[0].text
                          for frame in self.fig.frames], ["2013", "2014"])

    def test_the_non_areas_stay_hatched_in_every_frame(self):
        for frame in self.fig.frames:
            self.assertEqual(frame.data[0].marker.pattern.shape, ("/", ""))

    def test_it_ships_a_slider_step_per_year_and_a_play_button(self):
        self.assertEqual(
            [step.label for step in self.fig.layout.sliders[0].steps],
            ["2013", "2014"])
        self.assertEqual(
            [button.label for button in self.fig.layout.updatemenus[0].buttons],
            ["Play", "Pause"])


@requires_database
class TestAgainstDatabase(unittest.TestCase):
    """Re-measures the corpus figures the module's docstring quotes."""

    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(
            "file:{}?mode=ro".format(DB_PATH.as_posix()), uri=True)
        cls.rows = trials_per_area(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_every_area_in_the_vocabulary_is_used(self):
        self.assertEqual(len(self.rows), 55)

    def test_the_memberships_out_total_the_trials(self):
        # 12,276 over 11,834: the 442 extra are the multi-area studies, and
        # if these ever match, the bridge has silently become one-to-one.
        self.assertEqual(sum(trials for _, _, trials in self.rows), 12276)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM studies WHERE "
                             "fecha_autorizacion_aemps >= '2013-01-01'")
            .fetchone()[0], 11834)

    def test_cancer_leads_by_a_factor_of_four(self):
        _, name, trials = self.rows[0]
        self.assertEqual((leaf(name), trials), ("Cancer [C04]", 4239))
        self.assertGreater(trials, 4 * self.rows[1][2])

    def test_the_folding_leaves_37_areas_in_the_tail(self):
        bars = ranked_areas(self.rows)
        self.assertEqual(len(bars), TOP_AREAS + 2)
        self.assertEqual(bars[-2:], [Area("Not specified", 247, False),
                                     Area("Other (37 areas)", 1106, False)])

    def test_mental_health_has_a_bar_of_its_own(self):
        # The reason TOP_AREAS is 16. At 12 this area fell into Other and the
        # chart showed no mental health at all, which is a fact about where
        # the cut was drawn and not about Spanish trials. F03 is the whole of
        # psychiatry the chart names: the three other F areas hold 37 trials
        # between them and stay in the tail.
        bars = {bar.label: bar.trials for bar in ranked_areas(self.rows)}
        self.assertEqual(bars["Mental Disorders [F03]"], 170)

    def test_the_trends_hold_the_two_findings_the_spec_quotes(self):
        areas = top_areas(self.rows)
        trends = area_trends(
            area_counts_by_year(self.con, [code for code, _ in areas]),
            volume.trials_per_year(self.con), areas)
        share = {trend.label: dict(zip(trend.years, trend.shares))
                 for trend in trends}
        # COVID: virus trials triple in 2020 and end below where they began.
        self.assertAlmostEqual(share["Virus Diseases [C02]"][2020], 13.6, 1)
        self.assertAlmostEqual(share["Virus Diseases [C02]"][2013], 6.5, 1)
        self.assertLess(share["Virus Diseases [C02]"][2025], 3.5)
        # Immunology: the one line with a trend rather than a spike.
        self.assertAlmostEqual(share["Immune System Diseases [C20]"][2013],
                               4.0, 1)
        self.assertAlmostEqual(share["Immune System Diseases [C20]"][2025],
                               11.4, 1)


if __name__ == "__main__":
    unittest.main()
