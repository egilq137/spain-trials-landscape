"""Tests for analysis.geography.

Success criteria:
  the corrections: every entry is keyed on a centre that actually exists, so
    a typo in a hand-written table is caught rather than silently doing
    nothing; and applying them moves exactly the trials it should, at both
    grains
  region_pairs / province_pairs: the same centres read at two grains; a
    centre with no place drops out of the pairs but not out of the corpus,
    and a corrected centre reports its corrected place
  participation: a trial counts once per place however many sites it has
    there, and in every place it reaches; the share denominator is all
    trials, so the ones nobody could place do not flatter the rest
  NUTS and INE: every name REEC uses has a code, every code is in the
    geometry, and the INE table agrees with the postcode prefixes -- which
    is what turns a hand-written table into a checked one
  figure: two traces sharing one colour scale, display names from the
    geometry rather than REEC's index spellings, and the attribution the
    boundary licence requires
"""

import collections
import sqlite3
import unittest
from pathlib import Path

from analysis import volume
from analysis.geography import (
    CENTER_CORRECTIONS,
    CHECKED_UNCHANGED,
    INE,
    NUTS,
    Place,
    figure,
    load_geometry,
    names_in,
    participation,
    province_pairs,
    region_pairs,
    subtitle,
    unlocated,
)
from tests.test_loader import LoaderTestCase

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "trials.db"
REGIONS = ROOT / "data" / "geo" / "spain-ccaa.geojson"
PROVINCES = ROOT / "data" / "geo" / "spain-provinces.geojson"

requires_database = unittest.skipUnless(
    DB_PATH.exists(),
    "data/trials.db is a build artifact; run `python run_pipeline.py build`")


def centre(**overrides):
    entry = {"referencia": "ORG-1", "nombre": "Hospital A",
             "localidad": "Madrid", "codPostal": "28046",
             "provincia": "MADRID", "ccaa": "MADRID, COMUNIDAD DE"}
    entry.update(overrides)
    return entry


class GeographyLoaderTestCase(LoaderTestCase):
    def con_with(self, studies):
        """studies: [[centro dict, ...]] -- one list of centres per study."""
        self.write_year(2019, [
            self.study("study{}".format(index),
                       calendario={"fechaAutorizacionAEMPS": "04-03-2015"},
                       centros={"centro": centres})
            for index, centres in enumerate(studies)])
        con, _ = self.load()
        return con


class TestPairs(GeographyLoaderTestCase):
    def test_one_pair_per_study_and_centre_at_both_grains(self):
        con = self.con_with([[centre(), centre(
            referencia="ORG-2", nombre="Hospital B", localidad="Barcelona",
            codPostal="08001", provincia="BARCELONA", ccaa="CATALUÑA")]])
        self.assertEqual(sorted(code for _, code in region_pairs(con)),
                         ["ES30", "ES51"])
        self.assertEqual(sorted(code for _, code in province_pairs(con)),
                         ["08", "28"])

    def test_a_centre_with_no_place_drops_out(self):
        # Out of the pairs, not out of the corpus: the study stays in the
        # denominator and turns up in unlocated().
        con = self.con_with([[centre(ccaa="", provincia="")]])
        self.assertEqual(region_pairs(con), [])
        self.assertEqual(unlocated(region_pairs(con), trials=1), 1)

    def test_the_two_grains_can_disagree_about_what_is_placeable(self):
        # A centre with a region and no province is on one map and not the
        # other, which is why unlocated() is computed per grain.
        con = self.con_with([[centre(provincia="")]])
        self.assertEqual(len(region_pairs(con)), 1)
        self.assertEqual(province_pairs(con), [])

    def test_a_corrected_centre_reports_its_corrected_place(self):
        # The real row: VISSUM Alicante, filed under Murcia.
        con = self.con_with([[centre(
            referencia=None, nombre="Clinica Oftalmológica VISSUM Alicante",
            localidad="Alicante", codPostal="03016", provincia="MURCIA",
            ccaa="MURCIA, REGIÓN DE")]])
        self.assertEqual([code for _, code in region_pairs(con)], ["ES52"])
        self.assertEqual([code for _, code in province_pairs(con)], ["03"])

    def test_since_uses_the_same_floor_as_every_other_chart(self):
        con = self.con_with([[centre()]])
        self.assertEqual(len(region_pairs(con, since=2016)), 0)


class TestParticipation(unittest.TestCase):
    PAIRS = [("s1", "ES51"), ("s1", "ES30"),
             ("s2", "ES51"), ("s2", "ES51"), ("s3", "ES11")]

    def test_a_trial_counts_once_per_place_however_many_sites(self):
        # s2 has two Cataluña sites and is one Catalan trial.
        places = {place.code: place.trials
                  for place in participation(self.PAIRS, trials=4)}
        self.assertEqual(places["ES51"], 2)

    def test_a_trial_counts_in_every_place_it_reaches(self):
        # s1 is in both, so the totals exceed the trials. This is the
        # property that makes these shares overlap rather than add up.
        places = participation(self.PAIRS, trials=3)
        self.assertEqual(sum(place.trials for place in places), 4)

    def test_the_share_denominator_is_every_trial(self):
        # 2 of 4, not 2 of the 3 that could be placed: dropping the
        # unplaceable from the denominator would inflate every place.
        cataluna, = [place for place in participation(self.PAIRS, 4)
                     if place.code == "ES51"]
        self.assertEqual(cataluna.share, 50.0)

    def test_places_come_back_biggest_first(self):
        self.assertEqual(participation(self.PAIRS, trials=4)[0].code, "ES51")

    def test_unlocated_counts_the_trials_with_no_pair(self):
        self.assertEqual(unlocated(self.PAIRS, trials=5), 2)


class TestCodeTables(unittest.TestCase):
    def test_every_region_code_exists_in_the_region_geometry(self):
        # A name mapped to a code the map does not draw is a place that
        # silently disappears, which is the failure this module is trying
        # not to commit.
        self.assertEqual(set(NUTS.values()),
                         set(names_in(load_geometry(REGIONS))))

    def test_every_province_code_exists_in_the_province_geometry(self):
        self.assertEqual(set(INE.values()),
                         set(names_in(load_geometry(PROVINCES))))

    def test_both_mappings_are_one_to_one(self):
        # 19 to 19 and 52 to 52: a rename, not a reclassification.
        self.assertEqual((len(NUTS), len(set(NUTS.values()))), (19, 19))
        self.assertEqual((len(INE), len(set(INE.values()))), (52, 52))

    def test_the_provinces_merged_from_islands_are_whole(self):
        # Provinces are not a NUTS level: the Balearics are three NUTS 3
        # units and the Canaries seven, so ten polygons merge into three
        # provinces. If a merge were dropped, a province would be missing
        # islands and nothing else would complain.
        geometry = {feature["id"]: feature
                    for feature in load_geometry(PROVINCES)["features"]}
        for code, least in (("07", 3), ("35", 3), ("38", 4)):
            with self.subTest(province=code):
                self.assertGreaterEqual(
                    len(geometry[code]["geometry"]["coordinates"]), least)


class TestFigure(unittest.TestCase):
    PLACES = [Place("ES51", 9346, 79.0), Place("ES30", 8895, 75.2),
              Place("ES70", 979, 8.3)]

    def setUp(self):
        self.geometry = load_geometry(REGIONS)
        self.fig = figure(self.PLACES, self.geometry, "Title", "Subtitle")

    def test_the_canaries_are_drawn_on_their_own_axis(self):
        mainland, inset = self.fig.data
        self.assertEqual(list(mainland.locations), ["ES51", "ES30"])
        self.assertEqual(list(inset.locations), ["ES70"])
        self.assertEqual((mainland.geo, inset.geo), ("geo", "geo2"))

    def test_both_traces_share_one_colour_scale(self):
        # Left to normalise itself, the inset would paint the Canaries the
        # darkest place in Spain: 8.3% is its own maximum.
        mainland, inset = self.fig.data
        self.assertEqual((mainland.zmin, mainland.zmax),
                         (inset.zmin, inset.zmax))
        self.assertEqual(mainland.zmax, 79.0)
        self.assertFalse(inset.showscale)

    def test_names_come_from_the_geometry_not_from_reec(self):
        # 'Comunidad de Madrid', not 'Madrid, Comunidad De'.
        self.assertEqual(list(self.fig.data[0].text),
                         ["Cataluña", "Comunidad de Madrid"])

    def test_the_boundary_licence_is_credited_on_the_map(self):
        # Required by the EuroGeographics terms; see data/geo/README.md.
        notes = " ".join(note.text for note in self.fig.layout.annotations)
        self.assertIn("EuroGeographics", notes)

    def test_the_subtitle_names_the_leader_and_the_unplaced(self):
        text = subtitle(self.PLACES, self.geometry, 181, "region")
        self.assertIn("Cataluña", text)
        self.assertIn("181", text)
        self.assertIn("region", text)


@requires_database
class TestAgainstDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(
            "file:{}?mode=ro".format(DB_PATH.as_posix()), uri=True)
        cls.trials = sum(count for _, count
                         in volume.trials_per_year(cls.con))
        cls.regions = region_pairs(cls.con)
        cls.provinces = province_pairs(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def raw(self, column, codes):
        """The same pairs with no correction applied."""
        return [(study, codes[name]) for study, name in self.con.execute(
            """SELECT sc.study_id, c.{0}
                 FROM study_centers sc
                 JOIN centers c ON c.center_id = sc.center_id
                 JOIN studies st ON st.identificador = sc.study_id
                WHERE st.fecha_autorizacion_aemps >= '2013-01-01'
                  AND c.{0} IS NOT NULL""".format(column))]

    def counts(self, pairs):
        return {place.code: place.trials
                for place in participation(pairs, self.trials)}

    def test_every_hand_written_key_matches_a_real_centre(self):
        # A hand-written table whose keys match nothing does nothing, and
        # says nothing while it does it. This is the test that catches a
        # typo in the seven.
        for key in list(CENTER_CORRECTIONS) + list(CHECKED_UNCHANGED):
            with self.subTest(centre=key[0]):
                self.assertEqual(
                    self.con.execute(
                        "SELECT count(*) FROM centers WHERE center_key = ? "
                        "AND localidad = ? AND cod_postal = ?", key
                    ).fetchone()[0], 1)

    def test_every_place_reec_records_has_a_code(self):
        for column, table in (("ccaa", NUTS), ("provincia", INE)):
            with self.subTest(column=column):
                recorded = {row[0] for row in self.con.execute(
                    "SELECT DISTINCT {0} FROM centers WHERE {0} IS NOT NULL"
                    .format(column))}
                self.assertEqual(recorded - set(table), set())

    def test_the_province_codes_agree_with_the_postcode_prefixes(self):
        # The INE table is hand-written, and this is what makes it evidence
        # rather than assertion: a province's code is also its postcode
        # prefix, so the most common province among centres whose postcode
        # starts with those digits must be the province the table names.
        # All 52 agree.
        modal = collections.defaultdict(collections.Counter)
        for postcode, province in self.con.execute(
                "SELECT cod_postal, provincia FROM centers "
                "WHERE provincia IS NOT NULL "
                "AND cod_postal GLOB '[0-9][0-9][0-9][0-9][0-9]'"):
            modal[postcode[:2]][province] += 1
        derived = {counter.most_common(1)[0][0]: prefix
                   for prefix, counter in modal.items()}
        self.assertEqual(derived, INE)

    def test_the_regional_leaders_are_cataluna_and_madrid(self):
        counts = self.counts(self.regions)
        self.assertEqual((counts["ES51"], counts["ES30"]), (9346, 8895))
        self.assertEqual(len(counts), 19)

    def test_the_province_leaders_are_barcelona_and_madrid(self):
        counts = self.counts(self.provinces)
        self.assertEqual((counts["08"], counts["28"]), (9240, 8898))
        self.assertEqual(len(counts), 52)

    def test_the_trials_a_map_cannot_place(self):
        # One more province than region: a centre can carry a region and no
        # province, and the count is per grain for exactly that reason.
        self.assertEqual(unlocated(self.regions, self.trials), 181)
        self.assertEqual(unlocated(self.provinces, self.trials), 182)

    def test_the_corrections_move_one_trial_by_region(self):
        # Six corrections, one visible change: VISSUM's trial leaves Murcia
        # for Valencia. The other five belong to trials that already had a
        # site in the right region, so the region was counted anyway --
        # multi-site participation absorbs per-centre error.
        before = self.counts(self.raw("ccaa", NUTS))
        after = self.counts(self.regions)
        self.assertEqual(
            {code: (before[code], after[code]) for code in after
             if before.get(code) != after[code]},
            {"ES62": (960, 959), "ES52": (5181, 5182)})

    def test_the_corrections_move_four_trials_by_province(self):
        # Four rather than one: at the finer grain there is less chance the
        # trial already had another site in the right place.
        before = self.counts(self.raw("provincia", INE))
        after = self.counts(self.provinces)
        self.assertEqual(
            {code: (before[code], after[code]) for code in after
             if before.get(code) != after[code]},
            {"03": (1261, 1262), "05": (50, 51),
             "09": (241, 240), "30": (960, 959)})

    def test_girona_keeps_the_trials_the_postcode_rule_would_take(self):
        # The Institut Català d'Oncologia row, and the reason the postcode
        # rule was rejected: its Girona campus carries L'Hospitalet's
        # postcode. Deriving province from the prefix moves 114 Girona
        # trials to Barcelona -- 15% of the province.
        codes = set(names_in(load_geometry(PROVINCES)))
        by_prefix = [
            (study, postcode[:2]) for study, postcode in self.con.execute(
                """SELECT sc.study_id, c.cod_postal
                     FROM study_centers sc
                     JOIN centers c ON c.center_id = sc.center_id
                     JOIN studies st ON st.identificador = sc.study_id
                    WHERE st.fecha_autorizacion_aemps >= '2013-01-01'
                      AND c.cod_postal GLOB '[0-9][0-9][0-9][0-9][0-9]'""")
            if postcode[:2] in codes]
        self.assertEqual(self.counts(self.provinces)["17"], 747)
        self.assertEqual(self.counts(by_prefix)["17"], 633)


if __name__ == "__main__":
    unittest.main()
