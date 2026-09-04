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
  against the database: 11,834 trials over 8 rows, and the oncology split
    that the second chart's headline rests on
"""

import sqlite3
import unittest
from pathlib import Path

from analysis import volume
from analysis.phases import (
    CANCER,
    DESIGNS,
    Year,
    early_phase_by_year,
    early_phase_figure,
    label_of,
    mix_figure,
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
