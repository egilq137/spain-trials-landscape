"""Tests for db.centers.

Success criteria per function:
  read_entry: identity is the reference when there is a real one and the
    normalised name otherwise, so the 2,695 entries without a reference and
    the 119 saying 'NR' do not all collapse together; an entry that names no
    site at all returns None rather than a row with an empty key
  evidence_key: drops the postcode, because that is the field being repaired,
    and keeps the locality, because without it one reference's two campuses
    would vote on each other's postcodes
  build_center_index: only well-formed postcodes vote, so a broken value can
    never confirm another; blanks never vote on a region, so a site recorded
    once and blank 400 times keeps the region it was recorded with
  center_row: every field is resolved over the whole site, not taken from the
    entry, so two entries for one site produce identical rows and the second
    is a no-op; the site key groups on FOLDED locality so MADRID and Madrid
    are one site, while a second locality or postcode under one reference is
    a second site -- the case that keeps 545 trials in Madrid
  '' versus NULL: localidad and cod_postal are '' when unknown because they
    are part of the UNIQUE key and SQL counts every NULL as distinct;
    provincia and ccaa are NULL, which is the honest value for "never
    reported"
  against the corpus: the resolutions reproduce the counts in PROJECT_SPEC
    3.2c -- 3,360 sites, and 283 postcodes recovered in the tier order the
    triangulation rule claims
"""

import json
import unittest
from pathlib import Path

from db.centers import (
    build_center_index,
    center_row,
    evidence_key,
    read_entry,
    study_centers,
)
from db.manifest import Manifest

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "detalle"

requires_corpus = unittest.skipUnless(
    RAW_DIR.exists() and any(RAW_DIR.glob("*.jsonl")),
    "data/raw/detalle is gitignored; corpus checks need a local cache")


def raw_center(**overrides):
    """A centro dict shaped like the real ones."""
    entry = {
        "referencia": "ORG-100007650",
        "nombre": "Clínica Universidad de Navarra",
        "localidad": "Pamplona",
        "codPostal": "31008",
        "provincia": "Navarra",
        "ccaa": "Comunidad Foral de Navarra",
        "departamento": "Oncología",
        "situacion": "2",
    }
    entry.update(overrides)
    return entry


def index_of(*entries):
    return build_center_index(entries)


def row_for(entry, index):
    return center_row(entry, index)[1]


class TestReadEntry(unittest.TestCase):
    def test_identity_is_the_reference_when_there_is_one(self):
        self.assertEqual(read_entry(raw_center()).identity, "ORG-100007650")

    def test_identity_falls_through_to_the_name_without_a_reference(self):
        # 2,695 entries have none, covering 1,460 distinct names.
        entry = read_entry(raw_center(referencia="", nombre="Clinica Mon Salut"))
        self.assertEqual(entry.identity, "clinica mon salut")
        self.assertIsNone(entry.referencia)

    def test_a_placeholder_reference_is_treated_as_absent(self):
        # 'NR' appears in 119 entries covering 103 distinct hospitals, so
        # keying on it would merge a hundred hospitals into one centre.
        a = read_entry(raw_center(referencia="NR", nombre="Hospital A"))
        b = read_entry(raw_center(referencia="NR", nombre="Hospital B"))
        self.assertNotEqual(a.identity, b.identity)
        self.assertIsNone(a.referencia)

    def test_an_entry_naming_no_site_is_dropped(self):
        # 5 entries of 85,410: three blank in every field but situacion, and
        # two whose name is punctuation only.
        for nombre in ("", "  ", "-", "."):
            with self.subTest(nombre=nombre):
                self.assertIsNone(
                    read_entry(raw_center(referencia="", nombre=nombre)))

    def test_names_are_cleaned_on_the_way_in(self):
        entry = read_entry(
            raw_center(referencia="", nombre="Institut Català  D&amp;#39;oncologia"))
        self.assertEqual(entry.nombre, "Institut Català D'oncologia")


class TestEvidenceKey(unittest.TestCase):
    def test_two_campuses_of_one_reference_do_not_share_a_key(self):
        # Without the locality, Pamplona's postcodes would vote on Madrid's.
        pamplona = evidence_key(read_entry(raw_center()))
        madrid = evidence_key(read_entry(
            raw_center(localidad="Madrid", codPostal="28027")))
        self.assertNotEqual(pamplona, madrid)

    def test_the_postcode_is_not_part_of_the_key(self):
        # It is the field being recovered: a broken row must land in the same
        # group as its centre's good rows, which is where the evidence is.
        good = evidence_key(read_entry(raw_center()))
        broken = evidence_key(read_entry(raw_center(codPostal="3108")))
        self.assertEqual(good, broken)

    def test_locality_spelling_does_not_split_the_group(self):
        self.assertEqual(evidence_key(read_entry(raw_center())),
                         evidence_key(read_entry(raw_center(localidad="PAMPLONA"))))


class TestSiteIdentity(unittest.TestCase):
    def test_one_reference_at_two_localities_is_two_sites(self):
        # ORG-100007650 is Pamplona 1,400 times and Madrid 545 times. One site
        # would move 545 trials out of Madrid.
        madrid = raw_center(localidad="Madrid", codPostal="28027",
                            provincia="Madrid", ccaa="Comunidad de Madrid")
        index = index_of(raw_center(), madrid)
        self.assertNotEqual(center_row(raw_center(), index)[0],
                            center_row(madrid, index)[0])

    def test_one_reference_at_two_postcodes_is_two_sites(self):
        other = raw_center(codPostal="31009")
        index = index_of(raw_center(), other)
        self.assertNotEqual(center_row(raw_center(), index)[0],
                            center_row(other, index)[0])

    def test_locality_case_does_not_create_a_second_site(self):
        shouty = raw_center(localidad="PAMPLONA")
        index = index_of(raw_center(), shouty)
        self.assertEqual(center_row(raw_center(), index)[0],
                         center_row(shouty, index)[0])

    def test_two_entries_of_one_site_produce_identical_rows(self):
        # Every field is resolved over the site, so the second insert is a
        # no-op rather than a conflicting row.
        variant = raw_center(nombre="CLINICA UNIVERSIDAD DE NAVARRA",
                             provincia="")
        index = index_of(raw_center(), raw_center(), variant)
        self.assertEqual(row_for(raw_center(), index), row_for(variant, index))


class TestResolution(unittest.TestCase):
    def test_the_most_frequent_name_wins(self):
        # The two commonest values in the whole field are one hospital.
        index = index_of(raw_center(nombre="Hospital Vall d'Hebron"),
                         raw_center(nombre="Hospital Vall d'Hebron"),
                         raw_center(nombre="HOSPITAL VALL D HEBRON"))
        self.assertEqual(row_for(raw_center(), index)["nombre"],
                         "Hospital Vall d'Hebron")

    def test_a_blank_region_does_not_vote(self):
        # 132 of the 149 disagreeing sites differ only because one variant is
        # blank, so a site recorded once and blank many times keeps its value.
        index = index_of(raw_center(provincia=""), raw_center(provincia=""),
                         raw_center(provincia="Navarra"))
        self.assertEqual(row_for(raw_center(), index)["provincia"], "Navarra")

    def test_a_single_typo_loses_to_the_majority(self):
        # ORG-100028551 is Salamanca 1,122 times and Madrid once.
        index = index_of(raw_center(provincia="Salamanca"),
                         raw_center(provincia="Salamanca"),
                         raw_center(provincia="Madrid"))
        self.assertEqual(row_for(raw_center(), index)["provincia"], "Salamanca")

    def test_a_region_never_reported_is_null_not_blank(self):
        index = index_of(raw_center(provincia="", ccaa=""))
        row = row_for(raw_center(provincia="", ccaa=""), index)
        self.assertIsNone(row["provincia"])
        self.assertIsNone(row["ccaa"])

    def test_an_unknown_locality_or_postcode_is_blank_not_null(self):
        # Both are part of the UNIQUE key, and SQL counts every NULL as
        # distinct -- a NULL would duplicate the sites we know least about.
        blank = raw_center(localidad="", codPostal="")
        row = row_for(blank, index_of(blank))
        self.assertEqual((row["localidad"], row["cod_postal"]), ("", ""))

    def test_a_missing_digit_is_recovered_from_the_same_centre(self):
        index = index_of(raw_center(), raw_center(), raw_center(codPostal="3108"))
        self.assertEqual(
            row_for(raw_center(codPostal="3108"), index)["cod_postal"], "31008")

    def test_a_postcode_with_no_evidence_is_left_raw(self):
        lonely = raw_center(codPostal="3108", localidad="Nowhere")
        self.assertEqual(row_for(lonely, index_of(lonely))["cod_postal"], "3108")

    def test_a_broken_postcode_never_votes_on_another(self):
        # One damaged value must not confirm the next.
        a = raw_center(codPostal="3108")
        b = raw_center(codPostal="3100")
        index = index_of(a, b)
        self.assertEqual(row_for(a, index)["cod_postal"], "3108")


@requires_corpus
class TestAgainstCorpus(unittest.TestCase):
    """Re-measures what PROJECT_SPEC 3.2c claims about centres."""

    @classmethod
    def setUpClass(cls):
        cls.entries = []
        for path in sorted(RAW_DIR.glob("*.jsonl")):
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    cls.entries.extend(study_centers(json.loads(line)))
        cls.index = build_center_index(cls.entries)

    def test_entry_count_is_unchanged(self):
        self.assertEqual(len(self.entries), 85410)

    def test_five_entries_name_no_site(self):
        self.assertEqual(
            sum(1 for e in self.entries if read_entry(e) is None), 5)

    def test_the_site_grain_is_still_3360(self):
        # 3,361 in 3.2c, which counted the nameless entries as a site.
        keys = {center_row(e, self.index)[0] for e in self.entries
                if read_entry(e) is not None}
        self.assertEqual(len(keys), 3360)

    def test_postcode_repairs_land_in_the_tiers_the_rule_claims(self):
        manifest = Manifest()
        for entry in self.entries:
            center_row(entry, self.index, manifest)
        self.assertEqual(
            manifest.counts(),
            {("centers.cod_postal", "digit recovered (same centre)"): 226,
             ("centers.cod_postal", "digit recovered (same locality)"): 47,
             ("centers.cod_postal", "digit recovered (province agrees)"): 10,
             ("centers.nombre", "names no site -> no centre"): 5})


if __name__ == "__main__":
    unittest.main()
