"""Tests for analysis.geography.

Success criteria:
  the corrections: every entry is keyed on a centre that actually exists, so
    a typo in a hand-written table is caught rather than silently doing
    nothing; and applying them moves exactly the trials it should
  located_pairs: a centre with no region drops out of the pairs but not out
    of the corpus, and a corrected centre reports its corrected region
  trials_per_region: a trial counts once per region however many sites it
    has there, and in every region it reaches; the share denominator is all
    trials, so the ones nobody could place do not flatter the rest
  unlocated: says how many trials the map cannot show
  NUTS: every region name REEC uses has a code, and every code is in the
    geometry -- a missing pair is a region silently absent from the map
  figure: two traces sharing one colour scale, display names from the
    geometry rather than REEC's index spellings, and the attribution the
    boundary licence requires
"""

import sqlite3
import unittest
from pathlib import Path

from analysis import volume
from analysis.geography import (
    CENTER_CORRECTIONS,
    CHECKED_UNCHANGED,
    NUTS,
    Region,
    figure,
    load_geometry,
    located_pairs,
    trials_per_region,
    unlocated,
)
from tests.test_loader import LoaderTestCase

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "trials.db"
GEOMETRY_PATH = ROOT / "data" / "geo" / "spain-ccaa.geojson"

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


class TestLocatedPairs(GeographyLoaderTestCase):
    def test_one_pair_per_study_and_centre(self):
        con = self.con_with([[centre(), centre(
            referencia="ORG-2", nombre="Hospital B", localidad="Barcelona",
            codPostal="08001", provincia="BARCELONA", ccaa="CATALUÑA")]])
        self.assertEqual(sorted(region for _, region in located_pairs(con)),
                         ["CATALUÑA", "MADRID, COMUNIDAD DE"])

    def test_a_centre_with_no_region_drops_out(self):
        # Out of the pairs, not out of the corpus: the study stays in the
        # denominator and turns up in unlocated().
        con = self.con_with([[centre(ccaa="")]])
        self.assertEqual(located_pairs(con), [])
        self.assertEqual(unlocated(located_pairs(con), trials=1), 1)

    def test_a_corrected_centre_reports_its_corrected_region(self):
        # The real row: VISSUM Alicante, filed under Murcia.
        con = self.con_with([[centre(
            referencia=None, nombre="Clinica Oftalmológica VISSUM Alicante",
            localidad="Alicante", codPostal="03016", provincia="MURCIA",
            ccaa="MURCIA, REGIÓN DE")]])
        self.assertEqual([region for _, region in located_pairs(con)],
                         ["COMUNITAT VALENCIANA"])

    def test_since_uses_the_same_floor_as_every_other_chart(self):
        con = self.con_with([[centre()]])
        self.assertEqual(len(located_pairs(con, since=2016)), 0)


class TestTrialsPerRegion(unittest.TestCase):
    PAIRS = [("s1", "CATALUÑA"), ("s1", "MADRID, COMUNIDAD DE"),
             ("s2", "CATALUÑA"), ("s2", "CATALUÑA"), ("s3", "GALICIA")]

    def test_a_trial_counts_once_per_region_however_many_sites(self):
        # s2 has two Cataluña sites and is one Catalan trial.
        regions = dict((region.name, region.trials)
                       for region in trials_per_region(self.PAIRS, trials=4))
        self.assertEqual(regions["CATALUÑA"], 2)

    def test_a_trial_counts_in_every_region_it_reaches(self):
        # s1 is in both, and the totals therefore exceed the corpus. This is
        # the property that makes these shares overlap rather than add up.
        regions = trials_per_region(self.PAIRS, trials=4)
        self.assertEqual(sum(region.trials for region in regions), 4)
        self.assertGreater(sum(region.trials for region in regions), 3)

    def test_the_share_denominator_is_every_trial(self):
        # 2 of 4, not 2 of the 3 that could be placed: dropping the
        # unplaceable from the denominator would inflate every region.
        cataluna, = [region for region in trials_per_region(self.PAIRS, 4)
                     if region.name == "CATALUÑA"]
        self.assertEqual(cataluna.share, 50.0)

    def test_regions_come_back_biggest_first_with_their_nuts_code(self):
        regions = trials_per_region(self.PAIRS, trials=4)
        self.assertEqual(regions[0].name, "CATALUÑA")
        self.assertEqual(regions[0].nuts_id, "ES51")

    def test_unlocated_counts_the_trials_with_no_pair(self):
        self.assertEqual(unlocated(self.PAIRS, trials=5), 2)


class TestNutsMapping(unittest.TestCase):
    def test_every_code_exists_in_the_geometry(self):
        # A name mapped to a code the map does not draw is a region that
        # silently disappears, which is the failure this whole module is
        # trying not to commit.
        geometry = load_geometry(GEOMETRY_PATH)
        drawn = {feature["id"] for feature in geometry["features"]}
        self.assertEqual(set(NUTS.values()), drawn)

    def test_the_mapping_is_one_to_one(self):
        # 19 regions to 19 codes: a rename, not a reclassification.
        self.assertEqual(len(NUTS), 19)
        self.assertEqual(len(set(NUTS.values())), 19)


class TestFigure(unittest.TestCase):
    REGIONS = [Region("ES51", "CATALUÑA", 9346, 79.0),
               Region("ES30", "MADRID, COMUNIDAD DE", 8895, 75.2),
               Region("ES70", "CANARIAS", 979, 8.3)]

    def setUp(self):
        self.geometry = load_geometry(GEOMETRY_PATH)
        self.fig = figure(self.REGIONS, self.geometry, unplaced=181)

    def test_the_canaries_are_drawn_on_their_own_axis(self):
        mainland, inset = self.fig.data
        self.assertEqual(list(mainland.locations), ["ES51", "ES30"])
        self.assertEqual(list(inset.locations), ["ES70"])
        self.assertEqual((mainland.geo, inset.geo), ("geo", "geo2"))

    def test_both_traces_share_one_colour_scale(self):
        # Left to normalise itself, the inset would paint the Canaries the
        # darkest place in Spain: 8.3% is its own maximum.
        mainland, inset = self.fig.data
        self.assertEqual((mainland.zmin, mainland.zmax), (inset.zmin,
                                                          inset.zmax))
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

    def test_the_unplaced_trials_are_named_in_the_subtitle(self):
        self.assertIn("181", self.fig.layout.title.subtitle.text)


@requires_database
class TestAgainstDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(
            "file:{}?mode=ro".format(DB_PATH.as_posix()), uri=True)
        cls.trials = sum(count for _, count
                         in volume.trials_per_year(cls.con))
        cls.pairs = located_pairs(cls.con)
        cls.regions = trials_per_region(cls.pairs, cls.trials)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

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

    def test_every_region_reec_records_has_a_code(self):
        recorded = {row[0] for row in self.con.execute(
            "SELECT DISTINCT ccaa FROM centers WHERE ccaa IS NOT NULL")}
        self.assertEqual(recorded - set(NUTS), set())

    def test_the_leaders_are_cataluna_and_madrid(self):
        self.assertEqual(
            [(region.name, region.trials) for region in self.regions[:2]],
            [("CATALUÑA", 9346), ("MADRID, COMUNIDAD DE", 8895)])

    def test_the_map_covers_all_nineteen_regions(self):
        self.assertEqual(len(self.regions), 19)

    def test_181_trials_cannot_be_placed(self):
        self.assertEqual(unlocated(self.pairs, self.trials), 181)

    def test_the_whole_correction_table_moves_exactly_one_trial(self):
        # Six corrections, one visible change: VISSUM's trial leaves Murcia
        # for Valencia. The other five belong to trials that already had a
        # site in the right region, so the region was counted anyway --
        # multi-site participation absorbs per-centre error. Pinned because
        # it is the honest measure of what this table buys at region grain.
        raw = [(study, region) for study, region in self.con.execute(
            """SELECT sc.study_id, c.ccaa
                 FROM study_centers sc
                 JOIN centers c ON c.center_id = sc.center_id
                 JOIN studies st ON st.identificador = sc.study_id
                WHERE st.fecha_autorizacion_aemps >= '2013-01-01'
                  AND c.ccaa IS NOT NULL""")]
        before = {region.name: region.trials
                  for region in trials_per_region(raw, self.trials)}
        after = {region.name: region.trials for region in self.regions}
        self.assertEqual(
            {name: (before[name], after[name]) for name in after
             if before.get(name) != after[name]},
            {"MURCIA, REGIÓN DE": (960, 959),
             "COMUNITAT VALENCIANA": (5181, 5182)})


if __name__ == "__main__":
    unittest.main()
