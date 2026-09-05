"""Tests for analysis.phases.

Success criteria:
  label_of: the label is built from the flags, so 'I/II' cannot end up on a
    trial that is not flagged for both
  phase_mix: one row per recognised design in ladder order -- never sorted by
    size, because phase is ordinal and the order is the reader's prior; every
    trial counted exactly once, so the shares really do sum to 100%; and
    combinations the ladder has no name for are folded into one marked row
    that says how many they are
  early_phase_by_year: phase I means the flag is set, so a I/II trial counts;
    the overall rate is the two subgroups pooled, not their average, which is
    what lets the chart show a crude rate being dragged by one of them
  figures: only the folded row is hatched, the bars keep phase order, and the
    three lines carry their end values
  phase_by_area: shares are of that area's own trials, columns count
    involvement so a row may exceed 100%, and the corpus baseline is the
    last row rather than one of the areas
  heatmap: two period panels on one shared colour scale, refusing to draw
    if their rows disagree; a blank row separating the baseline from the
    areas; cell values in ink or surface by the cell's own darkness; and the
    biggest area at the top of a bottom-up axis
  against the database: 11,834 trials over 8 rows, and the oncology split
    that the second chart's headline rests on
"""

import sqlite3
import unittest
from pathlib import Path

from analysis import volume
from analysis.phases import (
    ALL_TRIALS,
    CANCER,
    DESIGNS,
    Year,
    early_phase_by_year,
    early_phase_figure,
    heatmap_figure,
    label_of,
    mix_figure,
    phase_by_area,
    phase_mix,
)
from tests.test_loader import LoaderTestCase

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "trials.db"

requires_database = unittest.skipUnless(
    DB_PATH.exists(),
    "data/trials.db is a build artifact; run `python run_pipeline.py build`")

FLAGS = ("faseUno", "faseDos", "faseTres", "faseCuatro")


class PhaseLoaderTestCase(LoaderTestCase):
    def con_with(self, studies):
        """studies: [(date, (f1, f2, f3, f4), cancer?)]."""
        records = []
        for index, (date, flags, cancer) in enumerate(studies):
            record = self.study(
                "study{}".format(index),
                calendario={"fechaAutorizacionAEMPS": date},
                proposito={name: str(flag)
                           for name, flag in zip(FLAGS, flags)})
            record["areasTerapeuticas"] = {"area": [{
                "eutct": CANCER if cancer else "999999000431",
                "nombre_es": "Area", "nombre_en": "Area"}]}
            records.append(record)
        self.write_year(2019, records)
        con, _ = self.load()
        return con


class TestLabelOf(unittest.TestCase):
    def test_a_single_flag_is_its_numeral(self):
        self.assertEqual(label_of((0, 0, 1, 0)), "III")

    def test_two_flags_join_in_phase_order(self):
        self.assertEqual(label_of((1, 1, 0, 0)), "I/II")
        self.assertEqual(label_of((0, 0, 1, 1)), "III/IV")

    def test_a_gap_is_kept_rather_than_smoothed_over(self):
        # 16 real trials are flagged I and III and not II. Whatever that
        # means, it is not 'I/II/III'.
        self.assertEqual(label_of((1, 0, 1, 0)), "I/III")


class TestPhaseMix(PhaseLoaderTestCase):
    def test_rows_are_in_ladder_order_not_size_order(self):
        # Phase III here is the biggest and still sits fifth. Sorting by
        # count would throw away an ordering the reader already has.
        con = self.con_with([("04-03-2015", (0, 0, 1, 0), False)] * 3
                            + [("04-03-2015", (1, 0, 0, 0), False)])
        self.assertEqual([bar.label for bar in phase_mix(con)][:5],
                         ["I", "I/II", "II", "II/III", "III"])

    def test_a_design_nobody_ran_is_a_zero_row_not_a_missing_one(self):
        con = self.con_with([("04-03-2015", (1, 0, 0, 0), False)])
        rows = {bar.label: bar.trials for bar in phase_mix(con)}
        self.assertEqual(rows["I"], 1)
        self.assertEqual(rows["IV"], 0)

    def test_a_combined_trial_gets_its_own_row_not_two_halves(self):
        con = self.con_with([("04-03-2015", (1, 1, 0, 0), False)])
        rows = {bar.label: bar.trials for bar in phase_mix(con)}
        self.assertEqual((rows["I"], rows["I/II"], rows["II"]), (0, 1, 0))

    def test_an_unnamed_combination_is_folded_and_counted(self):
        # I/III and II/IV are combinations the ladder has no name for. The
        # label says how many distinct ones went in, so a reader can see the
        # row is a fold and not a design.
        con = self.con_with([("04-03-2015", (1, 0, 1, 0), False),
                             ("04-03-2015", (0, 1, 0, 1), False)])
        folded = phase_mix(con)[-1]
        self.assertEqual((folded.label, folded.trials, folded.design),
                         ("Other combinations (2)", 2, False))

    def test_nothing_folded_means_no_extra_row(self):
        con = self.con_with([("04-03-2015", (0, 1, 0, 0), False)])
        self.assertEqual(len(phase_mix(con)), len(DESIGNS))

    def test_every_trial_is_counted_exactly_once(self):
        # The property that makes these shares sum to 100%, and the one the
        # four-flag source does not give for free.
        con = self.con_with([("04-03-2015", (1, 1, 0, 0), False),
                             ("04-03-2016", (0, 0, 1, 0), False),
                             ("04-03-2017", (1, 0, 1, 0), False)])
        self.assertEqual(sum(bar.trials for bar in phase_mix(con)), 3)

    def test_since_uses_the_same_floor_as_every_other_chart(self):
        con = self.con_with([("12-05-2011", (1, 0, 0, 0), False),
                             ("04-03-2013", (1, 0, 0, 0), False)])
        self.assertEqual(sum(bar.trials for bar in phase_mix(con)), 1)


class TestEarlyPhaseByYear(PhaseLoaderTestCase):
    def test_a_combined_trial_counts_as_phase_one(self):
        # 977 of the 2,698 early-phase trials are I/II. Counting only trials
        # that are phase I and nothing else would drop the modern seamless
        # designs, which are most of what the trend is about.
        con = self.con_with([("04-03-2015", (1, 1, 0, 0), False),
                             ("04-03-2015", (0, 0, 1, 0), False)])
        self.assertEqual(early_phase_by_year(con),
                         [Year(2015, 50.0, None, 50.0)])

    def test_the_two_groups_are_measured_separately(self):
        con = self.con_with([("04-03-2015", (1, 0, 0, 0), True),
                             ("04-03-2015", (0, 0, 1, 0), True),
                             ("04-03-2015", (0, 0, 1, 0), False)])
        year, = early_phase_by_year(con)
        self.assertEqual((year.cancer, year.other), (50.0, 0.0))

    def test_the_overall_rate_is_pooled_and_not_the_average_of_the_two(self):
        # Three cancer trials all phase I, one other trial that is not: the
        # pooled rate is 75%, while averaging the two subgroup rates would
        # say 50%. Pooling is what makes a big subgroup able to drag the
        # total, which is the whole point of the chart.
        con = self.con_with([("04-03-2015", (1, 0, 0, 0), True)] * 3
                            + [("04-03-2015", (0, 0, 1, 0), False)])
        year, = early_phase_by_year(con)
        self.assertEqual((year.overall, year.cancer, year.other),
                         (75.0, 100.0, 0.0))

    def test_an_empty_subgroup_is_undefined_and_not_zero(self):
        # No cancer trials in 2015 means there is no cancer phase I rate for
        # 2015. Zero would draw the line to the axis and claim a collapse in
        # something that was never measured; None leaves a gap.
        con = self.con_with([("04-03-2015", (1, 0, 0, 0), False)])
        year, = early_phase_by_year(con)
        self.assertIsNone(year.cancer)
        self.assertEqual((year.overall, year.other), (100.0, 100.0))

    def test_a_line_that_ends_undefined_carries_no_end_label(self):
        figure = early_phase_figure([Year(2015, 100.0, None, 100.0)])
        self.assertEqual([note.text for note in figure.layout.annotations],
                         ["100%", "100%"])

    def test_one_row_per_year_in_order(self):
        con = self.con_with([("04-03-2016", (1, 0, 0, 0), False),
                             ("04-03-2015", (1, 0, 0, 0), False)])
        self.assertEqual([year.year for year in early_phase_by_year(con)],
                         [2015, 2016])


class TestPhaseByArea(PhaseLoaderTestCase):
    AREAS = [(CANCER, "Diseases [C] - Cancer [C04]")]

    def test_shares_are_of_that_areas_own_trials(self):
        # Two cancer trials, one of them phase I, plus a non-cancer trial
        # that must not touch the cancer denominator.
        con = self.con_with([("04-03-2015", (1, 0, 0, 0), True),
                             ("04-03-2015", (0, 0, 1, 0), True),
                             ("04-03-2015", (1, 0, 0, 0), False)])
        cancer = phase_by_area(con, self.AREAS)[0]
        self.assertEqual((cancer.label, cancer.trials), ("Cancer [C04]", 2))
        self.assertEqual(cancer.shares, [50.0, 0.0, 50.0, 0.0])

    def test_a_row_counts_involvement_so_it_can_exceed_100(self):
        # One I/II trial: 100% phase I and 100% phase II, because it reaches
        # both. This is the column definition the mix chart does not use.
        con = self.con_with([("04-03-2015", (1, 1, 0, 0), True)])
        self.assertEqual(phase_by_area(con, self.AREAS)[0].shares,
                         [100.0, 100.0, 0.0, 0.0])

    def test_until_bounds_the_window_at_the_top(self):
        # What lets the same grid be drawn twice and compared. Without it a
        # thirteen-year average stands in for a structure that moved.
        con = self.con_with([("04-03-2015", (1, 0, 0, 0), True),
                             ("04-03-2021", (0, 0, 1, 0), True)])
        early = phase_by_area(con, self.AREAS, until=2019)[0]
        late = phase_by_area(con, self.AREAS, since=2020)[0]
        self.assertEqual((early.trials, early.shares[0]), (1, 100.0))
        self.assertEqual((late.trials, late.shares[2]), (1, 100.0))

    def test_the_baseline_row_is_last_and_covers_the_whole_corpus(self):
        con = self.con_with([("04-03-2015", (1, 0, 0, 0), True),
                             ("04-03-2015", (0, 0, 1, 0), False)])
        rows = phase_by_area(con, self.AREAS)
        self.assertEqual(rows[-1].label, ALL_TRIALS)
        self.assertEqual(rows[-1].trials, 2)
        self.assertEqual(rows[-1].shares, [50.0, 0.0, 50.0, 0.0])


def area_rows(cancer, eye, corpus):
    from analysis.phases import AreaPhases
    return [AreaPhases("Cancer [C04]", 4239, cancer, [1, 2, 3, 4]),
            AreaPhases("Eye Diseases [C11]", 265, eye, [1, 2, 3, 4]),
            AreaPhases(ALL_TRIALS, 11834, corpus, [1, 2, 3, 4])]


class TestHeatmap(unittest.TestCase):
    PANELS = [("2013-2019", area_rows([32.3, 46.9, 33.2, 2.6],
                                      [7.9, 21.9, 51.8, 23.7],
                                      [20.8, 34.4, 42.7, 10.7])),
              ("2020-2026", area_rows([43.8, 48.6, 29.6, 1.5],
                                      [6.6, 33.8, 59.6, 13.2],
                                      [24.5, 41.9, 41.0, 7.9]))]

    def setUp(self):
        self.fig = heatmap_figure(self.PANELS)

    def test_one_panel_per_period_titled_by_it(self):
        self.assertEqual(len(self.fig.data), 2)
        self.assertEqual(
            [note.text for note in self.fig.layout.annotations[:2]],
            ["2013-2019", "2020-2026"])

    def test_the_biggest_area_is_the_top_row_in_both_panels(self):
        # A heatmap's y axis is drawn bottom-up, so rows go in reversed.
        for panel in self.fig.data:
            self.assertEqual(list(panel.y)[-1], "Cancer [C04]")

    def test_the_panels_share_one_colour_scale(self):
        # Scaled apart, a flatter period would look as extreme as a sharper
        # one, and the comparison the chart exists for would be false.
        early, late = self.fig.data
        self.assertEqual((early.zmin, early.zmax), (late.zmin, late.zmax))
        self.assertEqual(early.zmax, 59.6)

    def test_only_the_last_panel_carries_the_colour_bar(self):
        self.assertEqual([panel.showscale for panel in self.fig.data],
                         [False, True])

    def test_panels_whose_rows_disagree_are_refused(self):
        # Read across, a row that means one area on the left and another on
        # the right is worse than no chart at all.
        mismatched = [self.PANELS[0], ("2020-2026", self.PANELS[1][1][:-1])]
        with self.assertRaises(AssertionError):
            heatmap_figure(mismatched)

    def test_a_blank_row_separates_the_baseline_from_the_areas(self):
        # So the corpus reads as a rule under the table rather than as one
        # more therapeutic area.
        rows = list(self.fig.data[0].y)
        self.assertEqual(rows[:2], [ALL_TRIALS, " "])
        self.assertEqual(list(self.fig.data[0].z)[1], [None] * 4)

    def test_the_blank_row_gets_no_cell_labels(self):
        # Two panels of three rows by four columns, plus the two panel
        # titles: the spacer has nothing to say in either.
        self.assertEqual(len(self.fig.layout.annotations), 2 + 2 * 12)

    def test_cell_text_switches_colour_on_dark_cells(self):
        from analysis.phases import INK, SURFACE
        colours = {note.text: note.font.color
                   for note in self.fig.layout.annotations[2:]}
        self.assertEqual(colours["2"], INK)       # 1.5%, the palest cell
        self.assertEqual(colours["60"], SURFACE)  # 59.6%, the darkest

    def test_the_columns_are_the_phase_ladder(self):
        self.assertEqual(list(self.fig.data[0].x), ["I", "II", "III", "IV"])


class TestFigures(unittest.TestCase):
    def setUp(self):
        from analysis.phases import Bar
        self.bars = [Bar("I", 1721, True), Bar("I/II", 958, True),
                     Bar("II", 3212, True), Bar("Other combinations (5)", 22,
                                                False)]
        self.fig = mix_figure(self.bars, trials=11834)
        self.years = [Year(2013, 18.4, 27.3, 14.9),
                      Year(2026, 25.7, 44.6, 13.9)]
        self.lines = early_phase_figure(self.years)

    def test_the_bars_keep_phase_order_top_to_bottom(self):
        # Plotly draws a horizontal category axis bottom-up, so the order is
        # reversed on the way in; this catches it being reversed twice.
        self.assertEqual(list(self.fig.data[0].y)[-1], "I")

    def test_only_the_folded_row_is_hatched(self):
        # The combined-phase designs are real designs; marking them would
        # say they are not.
        self.assertEqual(self.fig.data[0].marker.pattern.shape,
                         ("/", "", "", ""))

    def test_the_mix_subtitle_claims_the_shares_sum_to_100(self):
        self.assertIn("100%", self.fig.layout.title.subtitle.text)

    def test_three_lines_with_the_pooled_rate_in_ink(self):
        from analysis.phases import CANCER_COLOUR, OTHER_COLOUR
        self.assertEqual([trace.name for trace in self.lines.data],
                         ["Cancer trials", "Everything else", "All trials"])
        self.assertEqual([trace.line.color for trace in self.lines.data][:2],
                         [CANCER_COLOUR, OTHER_COLOUR])

    def test_every_line_ends_in_its_value(self):
        self.assertEqual([note.text for note in self.lines.layout.annotations],
                         ["45%", "14%", "26%"])


@requires_database
class TestAgainstDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(
            "file:{}?mode=ro".format(DB_PATH.as_posix()), uri=True)
        cls.bars = phase_mix(cls.con)
        cls.years = early_phase_by_year(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_the_cancer_code_still_names_cancer(self):
        # The oncology split is the second chart's headline, and it rests on
        # this one string.
        self.assertEqual(
            self.con.execute("SELECT nombre_en FROM therapeutic_areas "
                             "WHERE eutct_code = ?", (CANCER,)).fetchone()[0],
            "Diseases [C] - Cancer [C04]")

    def test_the_mix_accounts_for_every_trial_the_volume_chart_draws(self):
        # 11,834 either way. If these ever disagree, one of the two charts is
        # quoting a corpus the other does not recognise.
        self.assertEqual(
            sum(bar.trials for bar in self.bars),
            sum(count for _, count in volume.trials_per_year(self.con)))

    def test_the_mix_is_the_one_3_3_quotes(self):
        self.assertEqual([(bar.label, bar.trials) for bar in self.bars],
                         [("I", 1721), ("I/II", 958), ("II", 3212),
                          ("II/III", 369), ("III", 4468), ("III/IV", 88),
                          ("IV", 996), ("Other combinations (5)", 22)])

    def test_only_five_combinations_have_no_name_on_the_ladder(self):
        # 22 trials of 11,834. Small enough to fold, big enough to show.
        folded = self.bars[-1]
        self.assertFalse(folded.design)
        self.assertLess(folded.trials, 0.01 * sum(bar.trials
                                                  for bar in self.bars))

    def test_the_rise_belongs_to_oncology(self):
        # The claim the chart's title makes, held to the data: cancer's
        # phase I share rises by more than 15 points while everything else
        # ends within 2 points of where it started.
        first, last = self.years[0], self.years[-1]
        self.assertGreater(last.cancer - first.cancer, 15)
        self.assertLess(abs(last.other - first.other), 2)
        self.assertGreater(last.overall, first.overall)

    def test_the_heatmap_grid_is_the_one_the_headline_rests_on(self):
        from analysis import therapeutic
        areas = therapeutic.top_areas(therapeutic.trials_per_area(self.con),
                                      therapeutic.TOP_AREAS)
        rows = phase_by_area(self.con, areas)
        cancer, baseline = rows[0], rows[-1]
        self.assertEqual(cancer.label, "Cancer [C04]")
        self.assertEqual([round(share, 1) for share in cancer.shares],
                         [38.7, 47.8, 31.2, 2.0])
        self.assertEqual(baseline.label, ALL_TRIALS)
        self.assertEqual([round(share, 1) for share in baseline.shares],
                         [22.8, 38.4, 41.8, 9.2])
        # The claim in the title: cancer is the only large area weighted
        # toward phase I rather than phase III.
        for row in rows[1:-1]:
            with self.subTest(area=row.label):
                self.assertLess(row.shares[0], row.shares[2])
        self.assertGreater(cancer.shares[0], cancer.shares[2])

    def test_the_two_periods_move_the_way_3_3_says(self):
        from analysis import therapeutic
        areas = therapeutic.top_areas(therapeutic.trials_per_area(self.con),
                                      therapeutic.TOP_AREAS)
        early = {row.label: row for row
                 in phase_by_area(self.con, areas, until=2019)}
        late = {row.label: row for row
                in phase_by_area(self.con, areas, since=2020)}
        # Cancer's early-phase skew deepens: 32.3% to 43.8% phase I.
        self.assertEqual(
            (round(early["Cancer [C04]"].shares[0], 1),
             round(late["Cancer [C04]"].shares[0], 1)), (32.3, 43.8))
        # And the corpus moves too: phase II up, phase IV down.
        self.assertGreater(late[ALL_TRIALS].shares[1],
                           early[ALL_TRIALS].shares[1] + 5)
        self.assertLess(late[ALL_TRIALS].shares[3],
                        early[ALL_TRIALS].shares[3] - 2)

    def test_the_pooled_rate_sits_between_the_two_groups(self):
        # Not a law of arithmetic to be assumed -- a pooled rate lies
        # between its subgroups' rates, and if it ever did not, the grouping
        # would not be a partition.
        for year in self.years:
            with self.subTest(year=year.year):
                self.assertLess(year.other, year.overall)
                self.assertLess(year.overall, year.cancer)


if __name__ == "__main__":
    unittest.main()
