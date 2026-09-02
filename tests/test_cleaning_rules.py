"""Tests for db.cleaning_rules (steps 1-3: placeholders, sentinels, routes, names).

Two layers, deliberately. The unit tests are pure and always run. The
corpus-backed tests re-measure each rule against all 11,847 cached studies and
skip when the cache is absent -- they are what turns a comment like "4,762
placeholder acronyms" from an assertion into something that fails when a
refresh changes the data underneath it.

Success criteria:
  fold: casefolds, strips accents, collapses whitespace, drops edge
    punctuation; None and blank fold to ""
  is_placeholder: matches the enumerated set case- and accent-insensitively;
    treats a punctuation-only value as a placeholder without enumerating every
    run of dashes and dots; and does NOT treat blank as one, because "the
    registry wrote NA" and "wrote nothing" are different facts even though
    both load as NULL
  large totals: only the one value a rule acts on is data; it is checked by
    what the study is (a phase I trial) rather than by the number being big
  routes: every one of the 129 raw values is covered by exactly one of the two
    maps, with no fallthrough and no dead entries -- an unmapped value must be
    a visible failure, never a silent drop; the misspellings and the undecoded
    HTML entity still merge; distinct routes stay distinct; a dosage form is
    not guessed into a route; and a value naming several routes becomes
    `multiple routes` rather than whichever is written first. There is no
    coarse grouping to test -- the canonical routes are the grouping
  clean_text: reverses damage and only damage -- markup (including the ten
    doubly-escaped centre names), invisible format characters, and spacing --
    while case, accents and punctuation survive, because this is the form that
    gets displayed; blank becomes None
  match_key: destroys on purpose, so markup, case, accent and apostrophe-style
    variants of one organisation reach one key, while two organisations that
    differ by a letter do not
  clean_flag / clean_total: null only the enumerated sentinels, and pass an
    unexpected representation through so the schema rejects it rather than the
    rule quietly absorbing it
  resolve_postcode: recovers the missing digit from the corpus rather than
    assuming it was the leading zero -- the same centre first, then the same
    locality, then the province as a last resort; a tie or a contradicted
    province changes nothing, and a broken postcode never votes on another
  corpus: the placeholder set still covers the acronimo, funder and centre
    reference counts it was built from; -1 still appears in exactly the 12
    flags listed and no others; total is still 0 in 2,201 records; the four
    impossible-date studies still exist and still have an end before their
    authorisation; no cleaned value still holds markup; the merge counts hold;
    the 290 four-digit postcodes still resolve through the same tiers in the
    same proportions; every recovered postcode is still exactly one deletion
    from what the registry sent; and the one row where triangulation and
    zero-padding disagree is still that one row
"""

import json
import re
import unittest
from collections import Counter
from pathlib import Path

from db.cleaning_rules import (
    FLAG_UNKNOWN,
    FLAGS_WITH_UNKNOWN,
    IMPOSSIBLE_DATE_STUDIES,
    PLACEHOLDERS,
    ROUTE_CANONICAL,
    ROUTE_NOT_A_ROUTE,
    TOTAL_NOT_A_COUNT,
    TOTAL_UNKNOWN,
    build_postcode_evidence,
    clean_flag,
    clean_text,
    clean_total,
    fold,
    is_placeholder,
    match_key,
    organisation_key,
    postcode_candidates,
    resolve_postcode,
    route_key,
)

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "detalle"

requires_corpus = unittest.skipUnless(
    RAW_DIR.exists() and any(RAW_DIR.glob("*.jsonl")),
    "data/raw/detalle is gitignored; corpus checks need a local cache")


class TestFold(unittest.TestCase):
    def test_casefolds_and_strips_accents(self):
        self.assertEqual(fold("Oncología"), fold("ONCOLOGIA"))

    def test_collapses_whitespace(self):
        self.assertEqual(fold("  no   aplica  "), "no aplica")

    def test_drops_edge_punctuation(self):
        self.assertEqual(fold("N.A."), "n.a")

    def test_none_and_blank_fold_to_empty(self):
        self.assertEqual(fold(None), "")
        self.assertEqual(fold("   "), "")


class TestIsPlaceholder(unittest.TestCase):
    def test_matches_regardless_of_case_accent_or_spacing(self):
        for variant in ("NA", "na", " N/A ", "N.A.", "No Aplica", "no  aplica",
                        "NO APLICABLE", "NR", "Not Available"):
            with self.subTest(variant=variant):
                self.assertTrue(is_placeholder(variant))

    def test_punctuation_only_values_need_no_enumeration(self):
        # '-' alone is 1,922 intervention names. Enumerating every run of
        # dashes and dots would be endless; folding to nothing covers them.
        for variant in ("-", "--", ".", "..", " - "):
            with self.subTest(variant=variant):
                self.assertTrue(is_placeholder(variant))

    def test_blank_is_not_a_placeholder(self):
        for variant in (None, "", "   "):
            with self.subTest(variant=variant):
                self.assertFalse(is_placeholder(variant))

    def test_real_values_are_untouched(self):
        for variant in ("KEYTRUDA", "Nano", "NA-1000", "Roche AG", "Anakinra"):
            with self.subTest(variant=variant):
                self.assertFalse(is_placeholder(variant))

    def test_the_set_is_stored_already_folded(self):
        # Otherwise an entry could never match: lookups are done on folded text.
        for entry in PLACEHOLDERS:
            with self.subTest(entry=entry):
                self.assertEqual(fold(entry), entry)


class TestRouteMaps(unittest.TestCase):
    def test_keys_are_stored_folded(self):
        # Lookups happen on folded text, so an unfolded key could never match.
        for key in list(ROUTE_CANONICAL) + list(ROUTE_NOT_A_ROUTE):
            with self.subTest(key=key):
                self.assertEqual(fold(key), key)

    def test_the_two_maps_do_not_overlap(self):
        self.assertEqual(set(ROUTE_CANONICAL) & set(ROUTE_NOT_A_ROUTE), set())

    def test_misspellings_merge_into_intravenous(self):
        # 517 rows. A naive match on "intravenous" misses both.
        for typo in ("intravenious infusion", "intravenus use"):
            with self.subTest(typo=typo):
                self.assertEqual(ROUTE_CANONICAL[typo], "intravenous")

    def test_an_entity_encoded_value_still_merges(self):
        # The registry sends 'INFUSI&Oacute;N INTRAVENOSA' 20 times. The map
        # is keyed on route_key, which decodes before folding, so the entity
        # and the decoded spelling reach the same entry. Keying it as the raw
        # entity text -- as an earlier version did, on the reasoning that
        # nothing decoded it -- made the entry dead once the loader ran
        # clean_text, and those 20 rows became a 54th route.
        self.assertEqual(ROUTE_CANONICAL[route_key("INFUSI&Oacute;N INTRAVENOSA")],
                         "intravenous")
        self.assertEqual(ROUTE_CANONICAL[route_key("Infusión intravenosa")],
                         "intravenous")

    def test_phrasing_variants_merge(self):
        self.assertEqual(ROUTE_CANONICAL["oral"], ROUTE_CANONICAL["oral use"])
        self.assertEqual(ROUTE_CANONICAL["subcutaneous"],
                         ROUTE_CANONICAL["subcutaneous injection"])

    def test_compound_values_are_not_forced_into_one_route(self):
        for compound in ("oral and iv", "intravenous (iv) or subcutaneous (sc)",
                         "intravenous/subcutaneous/intramuscular"):
            with self.subTest(compound=compound):
                self.assertEqual(ROUTE_CANONICAL[route_key(compound)],
                                 "multiple routes")

    def test_a_route_written_twice_is_not_compound(self):
        self.assertEqual(ROUTE_CANONICAL["iv injection, iv infusion"],
                         "intravenous")

    def test_a_dosage_form_is_not_guessed_into_a_route(self):
        # 'solution for injection' names a form. It could be IV, IM or SC, so
        # it says so rather than picking one.
        self.assertEqual(ROUTE_CANONICAL["solution for injection"],
                         "injection, route unspecified")

    def test_distinct_routes_are_not_merged(self):
        for a, b in (("oral", "intravenous"),
                     ("subcutaneous", "intramuscular"),
                     ("intrathecal", "intravitreal")):
            with self.subTest(pair=(a, b)):
                self.assertNotEqual(ROUTE_CANONICAL[a + " use"],
                                    ROUTE_CANONICAL[b + " use"])


class TestCleanText(unittest.TestCase):
    def test_decodes_entities(self):
        self.assertEqual(clean_text("Merck Sharp &amp; Dohme LLC"),
                         "Merck Sharp & Dohme LLC")
        self.assertEqual(clean_text("M&aacute;laga"), "Málaga")

    def test_decodes_double_escaping(self):
        # Ten centre names need two passes. One pass leaves '&#39;' visible.
        self.assertEqual(clean_text("Institut Catala D&amp;#39;oncologia"),
                         "Institut Catala D'oncologia")

    def test_decoding_stops_at_a_fixed_point(self):
        # A value with no entities must survive untouched, and a stray '&' is
        # not an entity.
        self.assertEqual(clean_text("R&D Ltd"), "R&D Ltd")

    def test_drops_invisible_characters(self):
        # A byte-order mark arrived glued to a postcode. It is not visible, so
        # it would silently split one value into two rows.
        self.assertEqual(clean_text("﻿09"), "09")
        self.assertEqual(clean_text("Hospital​Clinic"), "HospitalClinic")

    def test_collapses_and_trims_whitespace(self):
        self.assertEqual(clean_text("  Hospital   Vall  d'Hebron "),
                         "Hospital Vall d'Hebron")

    def test_blank_and_none_become_none(self):
        for raw in (None, "", "   ", "﻿"):
            with self.subTest(raw=raw):
                self.assertIsNone(clean_text(raw))

    def test_case_accents_and_punctuation_are_content(self):
        # The line between clean_text and match_key. Damage is reversed;
        # content is not touched.
        for raw in ("Novartis Farmacéutica, S.A.", "PRO-ACT", "L'Hospitalet"):
            with self.subTest(raw=raw):
                self.assertEqual(clean_text(raw), raw)


class TestMatchKey(unittest.TestCase):
    def test_collapses_markup_case_accents_and_spacing(self):
        keys = {match_key(v) for v in (
            "Merck Sharp &amp; Dohme LLC", "Merck Sharp & Dohme LLC",
            "MERCK SHARP & DOHME LLC", " merck  sharp & dohme llc ")}
        self.assertEqual(len(keys), 1)

    def test_unifies_apostrophe_styles(self):
        # U+00B4 is a standalone character, not a combining mark, so NFD
        # leaves it and folding alone cannot merge these.
        self.assertEqual(match_key("Vall d'Hebron"), match_key("Vall d´Hebron"))
        self.assertEqual(match_key("L'Hospitalet"), match_key("L’Hospitalet"))

    def test_distinct_organisations_stay_distinct(self):
        self.assertNotEqual(match_key("Novartis Farmacéutica, S.A."),
                            match_key("Novartis Pharma AG"))
        self.assertNotEqual(match_key("Hospital Clinic de Barcelona"),
                            match_key("Hospital Clinico de Barcelona"))

    def test_blank_and_none_become_none(self):
        for raw in (None, "", "   ", "..."):
            with self.subTest(raw=raw):
                self.assertIsNone(match_key(raw))


class TestSentinelAppliers(unittest.TestCase):
    def test_clean_flag_nulls_only_minus_one(self):
        self.assertIsNone(clean_flag(-1))
        self.assertEqual(clean_flag(0), 0)
        self.assertEqual(clean_flag(1), 1)

    def test_clean_flag_passes_unexpected_values_through(self):
        # So the schema's CHECK rejects and names them.
        for value in ("-1", 2, "si", None):
            with self.subTest(value=value):
                self.assertEqual(clean_flag(value), value)

    def test_clean_total_nulls_zero_and_the_placeholder(self):
        self.assertIsNone(clean_total(0))
        self.assertIsNone(clean_total(999999))

    def test_clean_total_keeps_the_ambiguous_and_the_large_but_real(self):
        # 99999 may be a real open-ended target on a COVID platform trial, and
        # 114011 is a genuine pragmatic vaccine trial. Neither is a rule.
        self.assertEqual(clean_total(99999), 99999)
        self.assertEqual(clean_total(114011), 114011)
        self.assertEqual(clean_total(1), 1)


class TestPostcodeCandidates(unittest.TestCase):
    def test_a_candidate_is_any_code_one_deletion_away(self):
        # Not just the zero-padded one. This is the correction the whole
        # triangulation rests on: '3010' could be 03010, 30010, 31010, 30100...
        candidates = postcode_candidates("3010")
        for plausible in ("03010", "30010", "31010", "30100", "30101"):
            with self.subTest(plausible=plausible):
                self.assertIn(plausible, candidates)

    def test_every_candidate_really_is_one_deletion_away(self):
        for candidate in postcode_candidates("3010"):
            self.assertEqual(len(candidate), 5)
            reachable = {candidate[:i] + candidate[i + 1:] for i in range(5)}
            self.assertIn("3010", reachable)

    def test_the_zero_padded_value_is_only_one_of_many(self):
        self.assertIn("03010", postcode_candidates("3010"))
        self.assertGreater(len(postcode_candidates("3010")), 40)


class TestResolvePostcode(unittest.TestCase):
    """Hand-built evidence, so each tier can be exercised in isolation."""

    def evidence(self, *entries):
        return build_postcode_evidence(entries)

    def test_the_same_centre_wins(self):
        # Strongest evidence there is: the same physical site, reported
        # correctly on another trial.
        ev = self.evidence(("30008", "vissum", "murcia"),
                           ("03010", "hgu alicante", "alicante"))
        self.assertEqual(resolve_postcode("3008", "vissum", "murcia", ev),
                         ("30008", "same centre"))

    def test_the_locality_is_used_when_the_centre_is_unknown(self):
        ev = self.evidence(("08035", "vall hebron", "barcelona"))
        self.assertEqual(resolve_postcode("8035", "new centre", "barcelona", ev),
                         ("08035", "same locality"))

    def test_the_leading_zero_is_not_assumed(self):
        # The bug this replaced. '1108' in Cádiz is 11008, not 01108 -- and
        # 01108 is Álava. Blind padding moved a clinic 700km.
        ev = self.evidence(*[("11008", "other", "cadiz")] * 7)
        self.assertEqual(resolve_postcode("1108", "lobaton", "cadiz", ev),
                         ("11008", "same locality"))

    def test_a_majority_settles_competing_candidates(self):
        ev = self.evidence(*([("11008", "a", "cadiz")] * 7
                             + [("11408", "b", "cadiz")] * 5))
        self.assertEqual(resolve_postcode("1108", "c", "cadiz", ev).postcode,
                         "11008")

    def test_a_tie_is_not_resolved(self):
        # Two equally supported answers is not evidence for either. Picking one
        # would be the same mistake as assuming the leading zero.
        ev = self.evidence(("11008", "a", "cadiz"), ("11408", "b", "cadiz"))
        self.assertEqual(resolve_postcode("1108", "c", "cadiz", ev),
                         ("1108", None))

    def test_the_province_decides_when_no_candidate_was_ever_seen(self):
        # Weakest tier: 08207 is a real Sabadell postcode that happens to
        # appear nowhere else. The locality's other codes are all 08xxx, so
        # the padded value is at least in the right province.
        ev = self.evidence(("08208", "hospital sabadell", "sabadell"))
        self.assertEqual(resolve_postcode("8207", "concordia", "sabadell", ev),
                         ("08207", "province agrees"))

    def test_a_contradicted_province_is_left_raw(self):
        # '3016' in Murcia would pad to 03016, which is Alicante. Murcia uses
        # 30xxx, so the padding is refused and the broken value survives to
        # fail validation, where somebody will look at it.
        ev = self.evidence(("30008", "a", "murcia"), ("30120", "b", "murcia"))
        self.assertEqual(resolve_postcode("3016", "vissum", "murcia", ev),
                         ("3016", None))

    def test_no_evidence_at_all_changes_nothing(self):
        ev = self.evidence()
        self.assertEqual(resolve_postcode("2260", "x", "fuentealbilla", ev),
                         ("2260", None))

    def test_valid_and_malformed_values_pass_through_untouched(self):
        ev = self.evidence(("28046", "a", "madrid"))
        for raw in ("28046", "09", "280460", "08006.", "3584 AE", "Madrid"):
            with self.subTest(raw=raw):
                self.assertEqual(resolve_postcode(raw, "a", "madrid", ev),
                                 (clean_text(raw), None))

    def test_it_cleans_before_deciding(self):
        ev = self.evidence(("03010", "a", "alicante"))
        self.assertEqual(resolve_postcode(" 3010 ", "b", "alicante", ev).postcode,
                         "03010")
        # A byte-order mark plus two digits is still not a postcode.
        self.assertEqual(resolve_postcode("&#65279;09", "b", "alicante", ev),
                         ("09", None))

    def test_blank_becomes_none(self):
        ev = self.evidence()
        for raw in (None, "", "   "):
            with self.subTest(raw=raw):
                self.assertEqual(resolve_postcode(raw, "a", "b", ev),
                                 (None, None))

    def test_broken_postcodes_do_not_vote_on_the_answer(self):
        # Otherwise one four-digit value could confirm another.
        ev = self.evidence(("3010", "a", "alicante"), ("803", "b", "alicante"))
        self.assertEqual(ev.by_locality, {})
        self.assertEqual(resolve_postcode("3010", "a", "alicante", ev),
                         ("3010", None))


@requires_corpus
class TestAgainstCorpus(unittest.TestCase):
    """Re-measures the counts the rules were written from."""

    @classmethod
    def setUpClass(cls):
        cls.records = []
        for path in sorted(RAW_DIR.glob("*.jsonl")):
            with path.open(encoding="utf-8") as handle:
                cls.records.extend(json.loads(line) for line in handle)

    def test_corpus_size_is_unchanged(self):
        self.assertEqual(len(self.records), 11847)

    def test_placeholders_still_cover_the_acronyms_they_were_built_from(self):
        hits = sum(1 for r in self.records if is_placeholder(r.get("acronimo")))
        self.assertEqual(hits, 4763)  # 4,744 'NA' + 19 other forms

    def test_placeholders_still_cover_the_funder_names(self):
        hits = 0
        for record in self.records:
            raw = (record.get("organismo") or {}).get("financiador") or ""
            hits += sum(1 for part in raw.split("|") if is_placeholder(part))
        self.assertEqual(hits, 584)  # 572 'NA' + 12 'None'/'NO APLICA'

    def test_placeholders_still_cover_the_centre_references(self):
        # The one placeholder that changes identity rather than a label: 'NR'
        # spans 103 distinct hospitals, so missing it would merge them.
        hits = hospitals = 0
        names = set()
        for record in self.records:
            for centre in (record.get("centros") or {}).get("centro") or []:
                if is_placeholder(centre.get("referencia")):
                    hits += 1
                    names.add((centre.get("nombre") or "").strip())
        hospitals = len(names)
        self.assertEqual(hits, 119)
        self.assertEqual(hospitals, 103)

    def test_minus_one_appears_in_exactly_the_listed_flags(self):
        found = {}
        for record in self.records:
            for key, value in (record.get("poblacion") or {}).items():
                if key != "total" and value == FLAG_UNKNOWN:
                    found[key] = found.get(key, 0) + 1
            for key, value in (record.get("proposito") or {}).items():
                if value == FLAG_UNKNOWN:
                    found[key] = found.get(key, 0) + 1
        self.assertEqual(found, FLAGS_WITH_UNKNOWN)

    def test_no_flag_field_is_ever_absent_or_blank(self):
        # The invariant that makes -1 -> NULL lossless: with no pre-existing
        # nulls, a NULL in a flag column can only mean the source sent -1.
        for record in self.records:
            for block in ("poblacion", "proposito"):
                values = record.get(block) or {}
                self.assertTrue(values, block)
                for key, value in values.items():
                    self.assertIsNotNone(value, "{}.{}".format(block, key))

    def test_every_route_value_is_covered_by_exactly_one_map(self):
        # The test this whole step exists for. An unmapped value must fail
        # here rather than fall through into `other`, which would hide it.
        known = set(ROUTE_CANONICAL) | set(ROUTE_NOT_A_ROUTE)
        seen = set()
        for record in self.records:
            for item in (record.get("intervenciones") or {}).get("intervencion") or []:
                raw = (item.get("viasAdministracion") or "").strip()
                if raw:
                    seen.add(route_key(raw))
        self.assertEqual(seen - known, set(), "unmapped route values")
        self.assertEqual(len(seen), 129)

    def test_no_map_entry_is_dead(self):
        # An entry matching nothing is either a typo or a rule for data that
        # no longer exists; either way it should not sit there unnoticed.
        known = set(ROUTE_CANONICAL) | set(ROUTE_NOT_A_ROUTE)
        seen = set()
        for record in self.records:
            for item in (record.get("intervenciones") or {}).get("intervencion") or []:
                raw = (item.get("viasAdministracion") or "").strip()
                if raw:
                    seen.add(route_key(raw))
        self.assertEqual(known - seen, set(), "map entries matching nothing")

    def test_the_misspellings_still_account_for_the_rows_they_did(self):
        hits = 0
        for record in self.records:
            for item in (record.get("intervenciones") or {}).get("intervencion") or []:
                if fold(item.get("viasAdministracion")) in (
                        "intravenious infusion", "intravenus use"):
                    hits += 1
        self.assertEqual(hits, 517)

    def test_the_not_a_count_value_is_still_a_phase_one_study(self):
        # The only large total that any rule acts on. It is excluded because
        # of what the study is, not because the number is big, so the test
        # checks the study rather than the number.
        for record in self.records:
            if record["poblacion"]["total"] in TOTAL_NOT_A_COUNT:
                self.assertEqual(record["identificador"], "2025-524690-16-00")
                self.assertEqual(record["proposito"]["faseUno"], 1)

    def test_total_is_zero_in_the_expected_number_of_records(self):
        zeros = sum(1 for r in self.records
                    if r["poblacion"]["total"] == TOTAL_UNKNOWN)
        self.assertEqual(zeros, 2201)

    def test_the_impossible_date_studies_still_exist_and_are_still_impossible(self):
        def iso(value):
            day, month, year = value.split("-")
            return "{}-{}-{}".format(year, month, day)

        seen = set()
        for record in self.records:
            if record["identificador"] not in IMPOSSIBLE_DATE_STUDIES:
                continue
            seen.add(record["identificador"])
            calendar = record["calendario"]
            self.assertLess(iso(calendar["fechaFinRealEspana"]),
                            iso(calendar["fechaAutorizacionAEMPS"]),
                            record["identificador"])
        self.assertEqual(seen, set(IMPOSSIBLE_DATE_STUDIES))

    # --- step 3: names and postcodes ---------------------------------------

    def _names(self, kind):
        for record in self.records:
            if kind == "sponsor":
                yield ((record.get("organismo") or {}).get("promotor"))
            elif kind == "centre":
                for centre in (record.get("centros") or {}).get("centro") or []:
                    yield centre.get("nombre")
            elif kind == "funder":
                raw = (record.get("organismo") or {}).get("financiador") or ""
                for part in raw.split("|"):
                    if part.strip():
                        yield part

    def _postcodes(self):
        for record in self.records:
            for centre in (record.get("centros") or {}).get("centro") or []:
                yield centre.get("codPostal"), centre.get("localidad")

    def test_no_cleaned_value_still_contains_markup(self):
        # The fixed-point loop, checked against the data rather than assumed.
        # A single pass would leave ten centre names holding '&#39;'.
        entity = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#\d{1,7});")
        for kind in ("sponsor", "centre", "funder"):
            for raw in self._names(kind):
                cleaned = clean_text(raw)
                if cleaned and entity.search(cleaned):
                    self.fail("{}: {!r} -> {!r}".format(kind, raw, cleaned))

    def test_cleaning_still_merges_the_spellings_it_was_measured_on(self):
        for kind, expected in (("sponsor", 3742), ("centre", 3245),
                               ("funder", 2717)):
            with self.subTest(kind=kind):
                cleaned = {clean_text(v) for v in self._names(kind)}
                cleaned.discard(None)
                self.assertEqual(len(cleaned), expected)

    def test_the_match_key_still_merges_what_it_was_measured_on(self):
        # Sponsors and funders are keyed by organisation_key, which cuts a
        # descriptive clause on top of match_key; centres are not, because a
        # hospital is never described that way.
        for kind, key, expected in (("sponsor", organisation_key, 2984),
                                    ("centre", match_key, 2539),
                                    ("funder", organisation_key, 2233)):
            with self.subTest(kind=kind):
                keys = {key(v) for v in self._names(kind)
                        if not is_placeholder(v)}
                keys.discard(None)
                self.assertEqual(len(keys), expected)

    def test_the_biggest_sponsor_is_still_split_by_markup_alone(self):
        # The finding that made decoding mandatory rather than cosmetic, and
        # the reason the display column is the cleaned mode and not the raw
        # mode: the raw mode is the broken spelling.
        raw = Counter(v for v in self._names("sponsor")
                      if match_key(v) == match_key("Merck Sharp & Dohme LLC"))
        self.assertGreater(len(raw), 1)
        self.assertIn("&amp;", raw.most_common(1)[0][0])

    def _centres(self):
        for record in self.records:
            for centre in (record.get("centros") or {}).get("centro") or []:
                reference = centre.get("referencia")
                if is_placeholder(reference):
                    reference = None
                # The centre key drops the postcode (that is what is being
                # recovered) but KEEPS the locality -- without it, Clínica
                # Universidad de Navarra's Pamplona and Madrid campuses would
                # vote on each other's postcodes.
                yield (centre.get("codPostal"),
                       (fold(clean_text(reference) or centre.get("nombre")),
                        fold(centre.get("localidad"))),
                       centre.get("localidad"))

    def _resolutions(self):
        evidence = build_postcode_evidence(self._centres())
        for postcode, centre_key, locality in self._centres():
            text = clean_text(postcode) or ""
            if text.isdigit() and len(text) == 4:
                yield text, resolve_postcode(postcode, centre_key, locality,
                                             evidence)

    def test_the_four_digit_postcodes_still_resolve_by_the_tiers_measured(self):
        bases = Counter(r.basis for _, r in self._resolutions())
        self.assertEqual(sum(bases.values()), 290)
        self.assertEqual(bases["same centre"], 226)
        self.assertEqual(bases["same locality"], 47)
        self.assertEqual(bases["province agrees"], 10)
        self.assertEqual(bases[None], 7)  # left raw, deliberately

    def test_triangulation_beats_padding_where_the_two_differ(self):
        # The row that justifies the whole rewrite. Zero-padding gives 01108,
        # which is Álava; the corpus says this Cádiz locality uses 11008.
        differ = [(raw, r.postcode) for raw, r in self._resolutions()
                  if r.basis and r.postcode != raw.zfill(5)]
        self.assertEqual(differ, [("1108", "11008")])

    def test_nothing_resolved_is_left_the_wrong_length(self):
        for raw, resolution in self._resolutions():
            if resolution.basis:
                self.assertEqual(len(resolution.postcode), 5, raw)
            else:
                self.assertEqual(resolution.postcode, raw)

    def test_every_resolved_postcode_is_one_deletion_from_the_original(self):
        # The rule may only recover a dropped digit. It must never substitute
        # a different postcode that happens to be common in the locality.
        for raw, resolution in self._resolutions():
            if resolution.basis:
                self.assertIn(resolution.postcode, postcode_candidates(raw))


if __name__ == "__main__":
    unittest.main()
