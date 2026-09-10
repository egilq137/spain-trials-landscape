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
from analysis.geography import (BASE_LAYER, Site, display_name,
                                load_postcodes, normalise_postcode,
                                only_provinces, place_sites,
                                provinces_with_sites, site_activity,
                                sites_figure, studies_at)
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


class TestDisplayName(unittest.TestCase):
    """One consistent case, so a list of centres stops looking like two lists.

    It never changes which centre a name belongs to: the two spellings below
    stay two rows, because centres sharing a key are sometimes one
    organisation at several addresses and sometimes unrelated clinics under a
    placeholder name, and no merge can be right for both.
    """

    def test_it_settles_the_two_spellings_on_one(self):
        # Catalan elides its article and keeps it lowercase: d'Hebron.
        self.assertEqual(display_name("HOSPITAL UNIVERSITARI VALL D'HEBRON"),
                         "Hospital Universitari Vall d'Hebron")
        self.assertEqual(display_name("Clínica privada"), "Clínica Privada")
        self.assertEqual(display_name("CLÍNICA PRIVADA"), "Clínica Privada")

    def test_particles_stay_lowercase_inside_a_name(self):
        self.assertEqual(display_name("HOSPITAL 12 DE OCTUBRE"),
                         "Hospital 12 de Octubre")
        self.assertEqual(display_name("VIRGEN DE LAS NIEVES"),
                         "Virgen de las Nieves")
        # Catalan `i` is "and", not an initial.
        self.assertEqual(display_name("GERMANS TRIAS I PUJOL"),
                         "Germans Trias i Pujol")

    def test_a_leading_particle_is_still_capitalised(self):
        self.assertEqual(display_name("DE LA PAZ"), "De la Paz")

    def test_an_article_opening_a_name_keeps_its_capital(self):
        # `La Paz` and `La Fe` are what the hospitals are called; lowercasing
        # the article reads as a typo to anyone who knows them. An article
        # following a connector is a different thing and stays down.
        self.assertEqual(display_name("HOSPITAL UNIVERSITARIO LA PAZ"),
                         "Hospital Universitario La Paz")
        self.assertEqual(display_name("HOSPITAL VIRGEN DE LAS NIEVES"),
                         "Hospital Virgen de las Nieves")

    def test_acronyms_survive(self):
        self.assertEqual(display_name("CAE Oroitu"), "CAE Oroitu")
        self.assertEqual(display_name("HOSPITAL DE CANARIAS (H.U.C)"),
                         "Hospital de Canarias (H.U.C)")

    def test_a_short_word_is_not_an_acronym_just_for_being_short(self):
        # The name around it is the evidence: everything here is uppercase
        # because the whole string is, so PAZ is a word and not an initialism.
        self.assertEqual(display_name("HOSPITAL DE LA PAZ"),
                         "Hospital de la Paz")
        self.assertEqual(display_name("HOSPITAL DEL MAR"), "Hospital del Mar")

    def test_titles_are_not_acronyms(self):
        self.assertEqual(display_name("HOSPITAL DR. PESET"),
                         "Hospital Dr. Peset")

    def test_apostrophes_and_hyphens_capitalise_both_parts(self):
        self.assertEqual(display_name("INSTITUTO GÓMEZ-ULLA"),
                         "Instituto Gómez-Ulla")

    def test_an_already_tidy_name_is_left_as_it_is(self):
        for name in ["Instituto Oftalmológico Gómez-Ulla",
                     "Corporació Sanitària Parc Taulí"]:
            self.assertEqual(display_name(name), name)


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
            # The province and region spellings are REEC's own, uppercase and
            # inverted -- the vocabularies in geography.py are keyed on them.
            return dict(centros={"centro": [
                {"referencia": "ORG-" + hospital, "nombre": hospital,
                 "localidad": "Madrid", "codPostal": postcode,
                 "provincia": "MADRID", "ccaa": "MADRID, COMUNIDAD DE"}]},
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


class TestFilters(SiteQueryTestCase):
    """The area filter, and the province filter's correction hazard."""

    def areas_corpus(self):
        def study(label, area_code, date):
            return self.study(
                label,
                areasTerapeuticas={"area": [
                    {"eutct": area_code, "nombre_es": area_code,
                     "nombre_en": area_code}]},
                centros={"centro": [
                    {"referencia": "ORG-1", "nombre": "La Paz",
                     "localidad": "Madrid", "codPostal": "28046",
                     "provincia": "MADRID",
                     "ccaa": "MADRID, COMUNIDAD DE"}]},
                calendario={"fechaAutorizacionAEMPS": date})

        self.write_year(2019, [study("a", "C04", "04-03-2015"),
                               study("b", "C04", "02-06-2019"),
                               study("c", "C14", "02-06-2019")])
        con, _ = self.load()
        return con

    def test_the_area_filter_narrows_the_count(self):
        con = self.areas_corpus()
        self.assertEqual(site_activity(con)[0][5], 3)
        self.assertEqual(site_activity(con, area="C04")[0][5], 2)
        self.assertEqual(site_activity(con, area="C14")[0][5], 1)

    def test_an_area_nobody_ran_leaves_no_sites(self):
        self.assertEqual(site_activity(self.areas_corpus(), area="C99"), [])

    def test_the_drill_down_counts_what_the_mark_counts(self):
        # If the dot says 2 and the list runs to 3, one of them is lying.
        con = self.areas_corpus()
        centre, trials = site_activity(con, area="C04")[0][0], 2
        self.assertEqual(len(studies_at(con, centre, area="C04")), trials)

    def test_provinces_filters_on_the_corrected_value(self):
        rows = site_activity(self.areas_corpus())
        self.assertEqual(len(only_provinces(rows, ["MADRID"])), 1)
        self.assertEqual(len(only_provinces(rows, ["BARCELONA"])), 0)

    def test_no_provinces_named_means_all_of_them(self):
        rows = site_activity(self.areas_corpus())
        self.assertEqual(only_provinces(rows, []), rows)
        self.assertEqual(only_provinces(rows, None), rows)


class TestProvincesWithSites(SiteQueryTestCase):
    def test_it_names_the_provinces_with_something_in_the_window(self):
        # Every fixture centre is in Madrid, INE 28.
        self.assertEqual(provinces_with_sites(self.corpus()), {"28"})

    def test_an_empty_window_names_nothing(self):
        self.assertEqual(
            provinces_with_sites(self.corpus(), since=2020, until=2021), set())

    def test_it_takes_every_filter_the_marks_take(self):
        # The backdrop must not shade a province the dots are not in: with a
        # province filter on, the filled provinces are the filtered ones.
        con = self.corpus()
        self.assertEqual(provinces_with_sites(con, provinces=["MADRID"]),
                         {"28"})
        self.assertEqual(provinces_with_sites(con, provinces=["BARCELONA"]),
                         set())


class TestSitesFigure(unittest.TestCase):
    GEOMETRY = {"features": [
        {"id": "28", "properties": {"name": "Madrid"}},
        {"id": "08", "properties": {"name": "Barcelona"}},
    ]}
    SITES = [Site(1, "La Paz", "Madrid", "Madrid", 500, 40.46, -3.69)]

    def figure(self, active=("28",)):
        return sites_figure(self.SITES, self.GEOMETRY, set(active), "T", "S")

    def test_the_backdrop_is_drawn_before_the_dots(self):
        # Plotly draws in order, so a backdrop drawn last covers what it backs.
        self.assertEqual([trace.type for trace in self.figure().data],
                         ["choropleth", "choropleth",
                          "scattergeo", "scattergeo"])

    def test_the_backdrop_is_named_so_the_theme_can_find_it(self):
        base = [trace for trace in self.figure().data
                if trace.type == "choropleth"]
        self.assertTrue(all(trace.name == BASE_LAYER for trace in base))

    def test_a_province_is_filled_only_if_it_ran_something(self):
        base = self.figure(active=["28"]).data[0]
        self.assertEqual(dict(zip(base.locations, base.z)), {"28": 1, "08": 0})

    def test_the_backdrop_carries_no_colour_bar(self):
        # It measures nothing; a scale bar would say it did.
        self.assertFalse(self.figure().data[0].showscale)

    def test_marks_are_sized_by_area(self):
        # Radius-sizing would draw four times the trials as sixteen times
        # the ink.
        dots = self.figure().data[2]
        self.assertEqual(dots.marker.sizemode, "area")


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
