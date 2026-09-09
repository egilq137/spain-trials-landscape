"""Tests for the dot map's half of analysis.geography, and analysis.registry.

Success criteria:
  normalise_postcode repairs the three documented defects -- trailing
    punctuation, digit separators, a dropped leading zero -- and refuses
    everything else. The refusal is the load-bearing part: stripping letters
    would place a Dutch postcode in Alicante
  place_sites reports what it could not place, twice: centres lost, and the
    trials those centres carried. A map that quietly drops sites claims a
    coverage it does not have
  site_activity counts distinct trials per centre in the window, and a centre
    with nothing in the window is absent rather than zero
  the window has two ends: `until` is inclusive of that year, so 2015..2015 is
    one year and not none
  studies_at returns the studies behind a dot, so what a click shows is the
    same set the dot was sized by
  registry: the identifier's format picks the register, and the two URL
    patterns are the ones verified against the live registers
"""

import sqlite3
import unittest
from pathlib import Path

from analysis import registry
from analysis.geography import (Site, load_postcodes, normalise_postcode,
                                place_sites, site_activity, studies_at)
from tests.test_loader import LoaderTestCase

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "trials.db"
POSTCODES = Path(__file__).resolve().parents[1] / "data" / "geo" / "postcodes.csv"

requires_database = unittest.skipUnless(
    DB_PATH.exists(),
    "data/trials.db is a build artifact; run `python run_pipeline.py build`")


class TestNormalisePostcode(unittest.TestCase):
    def test_a_clean_postcode_is_itself(self):
        self.assertEqual(normalise_postcode("28046"), "28046")

    def test_it_strips_trailing_punctuation(self):
        self.assertEqual(normalise_postcode("28006,"), "28006")
        self.assertEqual(normalise_postcode("08006."), "08006")

    def test_it_removes_digit_separators(self):
        self.assertEqual(normalise_postcode("28.223"), "28223")

    def test_it_restores_a_dropped_leading_zero(self):
        # Four digits is the documented defect, and the reason 8214 is
        # Barcelona rather than nothing.
        self.assertEqual(normalise_postcode("8214"), "08214")

    def test_it_refuses_anything_holding_a_letter(self):
        # The one that matters: '3584 AE' is Utrecht. Stripping the letters
        # would make it 03584, which is a real postcode in Alicante, and the
        # hospital would appear on the wrong side of a border.
        self.assertIsNone(normalise_postcode("3584 AE"))
        self.assertIsNone(normalise_postcode("48993 Vizc"))
        self.assertIsNone(normalise_postcode("Madrid"))

    def test_it_refuses_wrong_lengths_rather_than_padding_them(self):
        self.assertIsNone(normalise_postcode("09"))
        self.assertIsNone(normalise_postcode("082008"))

    def test_it_refuses_the_empty_string(self):
        self.assertIsNone(normalise_postcode(""))


class TestPlaceSites(unittest.TestCase):
    POSTCODES = {"28046": (40.46, -3.69), "08035": (41.42, 2.14)}

    def rows(self):
        return [
            (1, "La Paz", "Madrid", "Madrid", "28046", 500),
            (2, "Vall d'Hebron", "Barcelona", "Barcelona", "8035", 400),
            (3, "Nowhere", "?", None, "Madrid", 7),
            (4, "Also nowhere", "?", None, "", 3),
        ]

    def test_it_places_what_it_can(self):
        placed, _, _ = place_sites(self.rows(), self.POSTCODES)
        self.assertEqual([site.name for site in placed],
                         ["La Paz", "Vall d'Hebron"])
        self.assertEqual(placed[0], Site(1, "La Paz", "Madrid", "Madrid",
                                         500, 40.46, -3.69))

    def test_it_normalises_on_the_way_in(self):
        # '8035' only finds Barcelona because the leading zero is restored.
        placed, _, _ = place_sites(self.rows(), self.POSTCODES)
        self.assertEqual((placed[1].lat, placed[1].lon), (41.42, 2.14))

    def test_it_reports_both_what_it_lost_and_what_that_cost(self):
        # Two centres lost, carrying ten trials between them. One number
        # would let a hundred tiny sites and two huge ones look the same.
        _, sites, trials = place_sites(self.rows(), self.POSTCODES)
        self.assertEqual((sites, trials), (2, 10))

    def test_biggest_first(self):
        placed, _, _ = place_sites(self.rows(), self.POSTCODES)
        self.assertEqual([site.trials for site in placed], [500, 400])


class SiteQueryTestCase(LoaderTestCase):
    def corpus(self):
        def at(hospital, postcode, date):
            return dict(centros={"centro": [
                {"referencia": "ORG-" + hospital, "nombre": hospital,
                 "localidad": "Madrid", "codPostal": postcode,
                 "provincia": "Madrid", "ccaa": "Madrid"}]},
                calendario={"fechaAutorizacionAEMPS": date})

        self.write_year(2019, [
            self.study("a", **at("La Paz", "28046", "04-03-2015")),
            self.study("b", **at("La Paz", "28046", "02-06-2019")),
            self.study("c", **at("Clinico", "28040", "02-06-2019")),
        ])
        con, _ = self.load()
        return con


class TestSiteActivity(SiteQueryTestCase):
    def test_it_counts_distinct_trials_per_centre(self):
        rows = site_activity(self.corpus())
        self.assertEqual([(row[1], row[5]) for row in rows],
                         [("La Paz", 2), ("Clinico", 1)])

    def test_the_window_has_two_ends(self):
        rows = site_activity(self.corpus(), since=2015, until=2015)
        self.assertEqual([(row[1], row[5]) for row in rows], [("La Paz", 1)])

    def test_a_centre_with_nothing_in_the_window_is_absent_not_zero(self):
        rows = site_activity(self.corpus(), since=2019)
        self.assertNotIn("La Paz", [row[1] for row in rows if row[5] == 0])
        self.assertEqual(sorted((row[1], row[5]) for row in rows),
                         [("Clinico", 1), ("La Paz", 1)])


class TestStudiesAt(SiteQueryTestCase):
    def test_it_returns_the_studies_behind_the_dot(self):
        con = self.corpus()
        la_paz = site_activity(con)[0][0]
        self.assertEqual(len(studies_at(con, la_paz)), 2)

    def test_it_honours_the_same_window_as_the_dot(self):
        con = self.corpus()
        la_paz = site_activity(con)[0][0]
        self.assertEqual(len(studies_at(con, la_paz, since=2019)), 1)


class TestRegistry(unittest.TestCase):
    def test_a_ctis_identifier_goes_to_ctis(self):
        self.assertEqual(
            registry.public_url("2026-525913-30-00", 1),
            "https://euclinicaltrials.eu/ctis-public/view/2026-525913-30-00")

    def test_a_eudract_identifier_goes_to_the_eu_register(self):
        # /ES because an EudraCT trial has a record per national authority,
        # and the Spanish one is the one naming the AEMPS.
        self.assertEqual(
            registry.public_url("2017-004836-13", 0),
            "https://www.clinicaltrialsregister.eu/ctr-search/trial/"
            "2017-004836-13/ES")

    def test_it_can_name_where_it_is_sending_the_reader(self):
        self.assertEqual(registry.register_of(1), "CTIS")
        self.assertEqual(registry.register_of(0), "EudraCT")


@requires_database
class TestAgainstDatabase(unittest.TestCase):
    """What the real corpus geocodes to."""

    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(
            "file:{}?mode=ro".format(DB_PATH.as_posix()), uri=True)
        cls.postcodes = load_postcodes(POSTCODES)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_the_lookup_covers_the_country(self):
        self.assertEqual(len(self.postcodes), 11150)

    def test_almost_every_centre_lands_somewhere(self):
        placed, lost_sites, _ = place_sites(
            site_activity(self.con), self.postcodes)
        # 3,293 centres; the rest have no postcode at all or one of the 24
        # that no repair can rescue.
        self.assertEqual(len(placed) + lost_sites, 3293)
        self.assertGreater(len(placed) / (len(placed) + lost_sites), 0.92)

    def test_every_point_is_inside_spain(self):
        # Including the Canaries, which is why the longitude floor is -18.2.
        placed, _, _ = place_sites(site_activity(self.con), self.postcodes)
        for site in placed:
            with self.subTest(site=site.name):
                self.assertTrue(27.5 <= site.lat <= 43.9, site.lat)
                self.assertTrue(-18.2 <= site.lon <= 4.4, site.lon)


if __name__ == "__main__":
    unittest.main()
