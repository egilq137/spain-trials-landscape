"""Tests for db/schema.sql (Phase 2.2 slice 1: sponsors + studies).

Declarative DDL, so the unit under test is each constraint rather than each
function. Success criteria:

  script:      executes clean against an empty database and is re-runnable
               (DROP IF EXISTS), creating exactly sponsors, studies and the
               two indexes
  STRICT:      both tables are STRICT, so a declared type is enforced rather
               than advisory
  studies:     59 columns; the 4 phase flags exist as separate columns, never
               collapsed to one enum
  identificador: rejects NULL (SQLite does not imply NOT NULL from PRIMARY KEY
               on a TEXT column) and rejects a duplicate
  sponsor_id:  rejects a value with no matching sponsor -- but only once the
               connection sets PRAGMA foreign_keys, which is the trap this
               suite pins down
  promotor:    rejects a duplicate, which is what enforces dedup-by-name
  dates:       accept ISO 'YYYY-MM-DD'; reject the source's own 'DD-MM-YYYY'
               and the empty string it uses for missing; nullable date columns
               still accept NULL, the two NOT NULL ones do not
  booleans:    accept 0/1, reject 2, -1 and non-numeric text
  poblacion_total: accepts 0 (means "not yet reported"), rejects negatives
  indexes:     actually used -- a sponsor JOIN and a date range both plan as
               SEARCH, and degrade to SCAN when the indexes are dropped

Slice 2 (funders, therapeutic areas and their bridges):

  bridges:     accept several funders/areas for one study and several studies
               for one funder/area; reject the same pairing twice; reject a
               pairing naming a study, funder or area that does not exist;
               reject NULL on either half of the composite key
  cascade:     deleting a study removes its pairings, and does not remove the
               funder or area themselves
  natural key: therapeutic_areas is keyed on eutct_code directly, so the same
               code cannot be inserted twice
  reverse idx: "studies of this funder" and "studies in this area" plan as
               SEARCH, not SCAN -- the direction the composite PK cannot serve

Slice 3 (centers and the study_centers bridge):

  centers:     identity is conditional -- a duplicate referencia is rejected,
               and two sites with no referencia are rejected on name; but a
               name may repeat freely when the referencias differ, since one
               hospital is spelled several ways across the corpus
  six-part key: the same study+center may repeat under a different department,
               region or postcode, and only an exact repeat of all six is
               rejected. This is the case the ERD's three-column key got
               wrong.
  blank text:  '' and NULL are not interchangeable in the key -- '' collapses
               a repeat as intended, and the columns reject NULL outright so
               the loader cannot substitute one for the other
  geography:   provincia/ccaa live per pairing, so one center can appear in two
               regions across different studies (the Navarra/Madrid case)
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"

BOOL_COLUMNS = (
    "enfermedad_rara censored voluntarios_sanos pacientes pob_vulnerable "
    "mujer_usa mujer_no_usa embarazadas lactancia urgencia incapaces "
    "intrauteros prematuros recien_nacido preescolar ninos adolescentes "
    "adultos ancianos menores fase_uno fase_dos fase_tres fase_cuatro "
    "diagnostico profilaxis tratamiento seguridad eficacia farmacocinetica "
    "farmacodinamica bioequivalencia dosis farmacogenetica farmacogenomica "
    "farmacoeconomica atencion_primaria atencion_personalizada hospitalizacion "
    "medico farmaceutico historial_clinico bases_datos otras_fuentes"
).split()

NULLABLE_DATES = (
    "fecha_inicio_prevista fecha_inicio_real fecha_fin_real_espana "
    "fecha_fin_real_global fecha_interrupcion fecha_reinicio fecha_fin_prematuro"
).split()

REQUIRED_DATES = ["fecha_autorizacion_aemps", "fecha_registro",
                  "survival_start", "survival_end"]


def valid_study(**overrides):
    """A minimal studies row that satisfies every constraint."""
    row = dict.fromkeys(BOOL_COLUMNS, 0)
    row.update(
        identificador="2019-002321-29",
        sponsor_id=1,
        acronimo=None,
        poblacion_total=120,
        survival_start="2019-12-18",
        survival_end="2022-03-31",
        fecha_autorizacion_aemps="2019-12-18",
        fecha_registro="2019-12-19",
    )
    row.update(overrides)
    return row


class SchemaTestCase(unittest.TestCase):
    def setUp(self):
        self.ddl = SCHEMA_PATH.read_text(encoding="utf-8")
        self.con = sqlite3.connect(":memory:")
        self.con.executescript(self.ddl)
        # Redundant on this connection (running the script leaves the pragma
        # on), but issued explicitly because that is what the application must
        # do on every connect -- see the later-connection test below.
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.execute("INSERT INTO sponsors (promotor) VALUES ('Sponsor A')")

    def tearDown(self):
        self.con.close()

    def insert_study(self, **overrides):
        row = valid_study(**overrides)
        placeholders = ",".join("?" * len(row))
        self.con.execute(
            f"INSERT INTO studies ({','.join(row)}) VALUES ({placeholders})",
            list(row.values()),
        )

    def assert_rejected(self, **overrides):
        with self.assertRaises(sqlite3.DatabaseError):
            self.insert_study(**overrides)


class TestScript(SchemaTestCase):
    def test_creates_expected_objects(self):
        names = [r[0] for r in self.con.execute(
            "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
            "ORDER BY name")]
        # A deliberate inventory: extended once per slice, so an object created
        # or renamed by accident shows up as a failure rather than passing by.
        self.assertEqual(names, [
            "centers",
            "funders",
            "idx_centers_nombre_no_ref",
            "idx_centers_referencia",
            "idx_studies_fecha_autorizacion",
            "idx_studies_sponsor_id",
            "idx_study_centers_ccaa",
            "idx_study_centers_center_id",
            "idx_study_funders_funder_id",
            "idx_study_therapeutic_areas_eutct",
            "sponsors", "studies", "study_centers", "study_funders",
            "study_therapeutic_areas", "therapeutic_areas"])

    def test_rerunnable(self):
        self.insert_study()
        self.con.executescript(self.ddl)  # DROP IF EXISTS then recreate
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM studies").fetchone()[0], 0)

    def test_tables_are_strict(self):
        strict = {r[1]: r[5] for r in self.con.execute("PRAGMA table_list")
                  if not r[1].startswith("sqlite_")}
        self.assertEqual(set(strict.values()), {1}, strict)

    def test_studies_column_count_and_phase_flags(self):
        cols = [r[1] for r in self.con.execute(
            "SELECT * FROM pragma_table_info('studies')")]
        self.assertEqual(len(cols), 59)
        for flag in ("fase_uno", "fase_dos", "fase_tres", "fase_cuatro"):
            self.assertIn(flag, cols)


class TestKeys(SchemaTestCase):
    def test_accepts_a_valid_row(self):
        self.insert_study()
        self.assertEqual(
            self.con.execute(
                "SELECT p.promotor FROM studies s JOIN sponsors p "
                "USING (sponsor_id)").fetchone()[0],
            "Sponsor A")

    def test_rejects_null_identificador(self):
        self.assert_rejected(identificador=None)

    def test_rejects_duplicate_identificador(self):
        self.insert_study()
        self.assert_rejected()

    def test_rejects_unknown_sponsor(self):
        self.assert_rejected(sponsor_id=999)

    def test_foreign_keys_unenforced_on_a_later_connection(self):
        # Pins the trap. The pragma in schema.sql applies to the connection
        # that runs the script, but it is connection-scoped and not stored in
        # the file -- so a later connection has it off again and the FK above
        # passes silently. Every connection the application opens must set it.
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "trials.db")
            builder = sqlite3.connect(path)
            builder.executescript(self.ddl)
            builder.execute("INSERT INTO sponsors (promotor) VALUES ('Sponsor A')")
            builder.commit()
            builder.close()

            later = sqlite3.connect(path)
            self.assertEqual(later.execute("PRAGMA foreign_keys").fetchone()[0], 0)
            row = valid_study(sponsor_id=999)
            later.execute(
                f"INSERT INTO studies ({','.join(row)}) "
                f"VALUES ({','.join('?' * len(row))})", list(row.values()))
            self.assertEqual(
                later.execute("SELECT sponsor_id FROM studies").fetchone()[0], 999)
            later.close()

    def test_rejects_duplicate_promotor(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("INSERT INTO sponsors (promotor) VALUES ('Sponsor A')")


class TestDates(SchemaTestCase):
    def test_rejects_source_date_format(self):
        for column in REQUIRED_DATES + NULLABLE_DATES:
            with self.subTest(column=column):
                self.assert_rejected(**{column: "18-12-2019"})

    def test_rejects_empty_string(self):
        for column in REQUIRED_DATES + NULLABLE_DATES:
            with self.subTest(column=column):
                self.assert_rejected(**{column: ""})

    def test_nullable_dates_accept_null(self):
        self.insert_study(**dict.fromkeys(NULLABLE_DATES, None))

    def test_required_dates_reject_null(self):
        for column in REQUIRED_DATES:
            with self.subTest(column=column):
                self.assert_rejected(**{column: None})


class TestFlags(SchemaTestCase):
    def test_accepts_zero_and_one(self):
        self.insert_study(**dict.fromkeys(BOOL_COLUMNS, 1))

    def test_rejects_out_of_range(self):
        for bad in (2, -1):
            for column in BOOL_COLUMNS:
                with self.subTest(column=column, value=bad):
                    self.assert_rejected(**{column: bad})

    def test_rejects_non_numeric_text(self):
        self.assert_rejected(fase_uno="si")

    def test_poblacion_total_allows_zero_rejects_negative(self):
        self.insert_study(poblacion_total=0)
        self.assert_rejected(identificador="other", poblacion_total=-1)


class TestIndexes(SchemaTestCase):
    JOIN_QUERY = ("SELECT COUNT(*) FROM sponsors p JOIN studies s "
                  "USING (sponsor_id) WHERE p.promotor = 'Sponsor A'")
    RANGE_QUERY = ("SELECT COUNT(*) FROM studies WHERE fecha_autorizacion_aemps "
                   "BETWEEN '2023-01-01' AND '2023-12-31'")

    def plan(self, con, query):
        return " ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN " + query))

    def test_indexes_are_used(self):
        self.assertIn("idx_studies_sponsor_id", self.plan(self.con, self.JOIN_QUERY))
        self.assertIn("idx_studies_fecha_autorizacion",
                      self.plan(self.con, self.RANGE_QUERY))

    def test_queries_degrade_to_a_scan_without_them(self):
        # Guards the reason the indexes exist, not merely that they exist.
        con = sqlite3.connect(":memory:", cached_statements=0)
        con.executescript(self.ddl)
        con.execute("DROP INDEX idx_studies_sponsor_id")
        con.execute("DROP INDEX idx_studies_fecha_autorizacion")
        self.assertIn("SCAN", self.plan(con, self.JOIN_QUERY))
        self.assertIn("SCAN", self.plan(con, self.RANGE_QUERY))
        con.close()


class BridgeTestCase(SchemaTestCase):
    """Two studies, two funders and two therapeutic areas already loaded."""

    def setUp(self):
        super().setUp()
        self.insert_study(identificador="study-1")
        self.insert_study(identificador="study-2")
        self.con.executemany("INSERT INTO funders (nombre) VALUES (?)",
                             [("Roche",), ("EORTC",)])
        self.con.executemany(
            "INSERT INTO therapeutic_areas (eutct_code, nombre_es, nombre_en) "
            "VALUES (?, ?, ?)",
            [("999999000429", "Tracto respiratorio", "Respiratory Tract"),
             ("999999000432", "Neoplasias", "Neoplasms")])

    def link_funder(self, study_id, funder_id):
        self.con.execute(
            "INSERT INTO study_funders (study_id, funder_id) VALUES (?, ?)",
            (study_id, funder_id))

    def link_area(self, study_id, eutct_code):
        self.con.execute(
            "INSERT INTO study_therapeutic_areas (study_id, eutct_code) "
            "VALUES (?, ?)", (study_id, eutct_code))


class TestFunderBridge(BridgeTestCase):
    def test_many_to_many_in_both_directions(self):
        self.link_funder("study-1", 1)
        self.link_funder("study-1", 2)   # co-funding: two funders, one study
        self.link_funder("study-2", 1)   # one funder, two studies
        self.assertEqual(
            self.con.execute(
                "SELECT COUNT(*) FROM study_funders WHERE study_id = 'study-1'"
            ).fetchone()[0], 2)
        self.assertEqual(
            self.con.execute(
                "SELECT COUNT(*) FROM study_funders WHERE funder_id = 1"
            ).fetchone()[0], 2)

    def test_rejects_duplicate_pairing(self):
        self.link_funder("study-1", 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.link_funder("study-1", 1)

    def test_rejects_unknown_study_or_funder(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.link_funder("no-such-study", 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.link_funder("study-1", 999)

    def test_rejects_null_in_either_half_of_the_key(self):
        for study_id, funder_id in ((None, 1), ("study-1", None)):
            with self.subTest(study_id=study_id, funder_id=funder_id):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.link_funder(study_id, funder_id)

    def test_deleting_a_study_cascades_to_pairings_only(self):
        self.link_funder("study-1", 1)
        self.link_funder("study-2", 1)
        self.con.execute("DELETE FROM studies WHERE identificador = 'study-1'")
        self.assertEqual(
            self.con.execute("SELECT study_id FROM study_funders").fetchall(),
            [("study-2",)])
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM funders").fetchone()[0], 2)


class TestTherapeuticAreaBridge(BridgeTestCase):
    def test_a_study_can_carry_several_areas(self):
        self.link_area("study-1", "999999000429")
        self.link_area("study-1", "999999000432")
        self.assertEqual(
            self.con.execute(
                "SELECT COUNT(*) FROM study_therapeutic_areas "
                "WHERE study_id = 'study-1'").fetchone()[0], 2)

    def test_rejects_duplicate_pairing(self):
        self.link_area("study-1", "999999000429")
        with self.assertRaises(sqlite3.IntegrityError):
            self.link_area("study-1", "999999000429")

    def test_rejects_unknown_study_or_area(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.link_area("no-such-study", "999999000429")
        with self.assertRaises(sqlite3.IntegrityError):
            self.link_area("study-1", "000000000000")

    def test_eutct_code_is_the_key(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(
                "INSERT INTO therapeutic_areas (eutct_code, nombre_es, nombre_en) "
                "VALUES ('999999000429', 'otro', 'other')")

    def test_deleting_a_study_cascades_to_pairings_only(self):
        self.link_area("study-1", "999999000429")
        self.con.execute("DELETE FROM studies WHERE identificador = 'study-1'")
        self.assertEqual(
            self.con.execute(
                "SELECT COUNT(*) FROM study_therapeutic_areas").fetchone()[0], 0)
        self.assertEqual(
            self.con.execute(
                "SELECT COUNT(*) FROM therapeutic_areas").fetchone()[0], 2)


class TestBridgeIndexes(BridgeTestCase):
    def plan(self, query):
        return " ".join(r[3] for r in self.con.execute("EXPLAIN QUERY PLAN " + query))

    def test_reverse_lookups_use_an_index(self):
        self.assertIn(
            "idx_study_funders_funder_id",
            self.plan("SELECT study_id FROM study_funders WHERE funder_id = 1"))
        self.assertIn(
            "idx_study_therapeutic_areas_eutct",
            self.plan("SELECT study_id FROM study_therapeutic_areas "
                      "WHERE eutct_code = '999999000429'"))

    def test_forward_lookups_use_the_primary_key(self):
        for query in (
            "SELECT funder_id FROM study_funders WHERE study_id = 'study-1'",
            "SELECT eutct_code FROM study_therapeutic_areas "
            "WHERE study_id = 'study-1'",
        ):
            with self.subTest(query=query):
                self.assertNotIn("SCAN", self.plan(query))


class CenterTestCase(BridgeTestCase):
    def add_center(self, referencia="ORG-1", nombre="HOSPITAL A", tipo="0"):
        cur = self.con.execute(
            "INSERT INTO centers (referencia, nombre, tipo) VALUES (?, ?, ?)",
            (referencia, nombre, tipo))
        return cur.lastrowid

    def link_center(self, study_id="study-1", center_id=1, departamento="ONCOLOGY",
                    provincia="BARCELONA", ccaa="CATALUNA", cod_postal="08036"):
        self.con.execute(
            "INSERT INTO study_centers (study_id, center_id, departamento, "
            "provincia, ccaa, cod_postal) VALUES (?, ?, ?, ?, ?, ?)",
            (study_id, center_id, departamento, provincia, ccaa, cod_postal))


class TestCenters(CenterTestCase):
    def test_rejects_duplicate_referencia(self):
        self.add_center(referencia="ORG-1", nombre="HOSPITAL A")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_center(referencia="ORG-1", nombre="Hospital A")

    def test_same_name_allowed_under_different_referencias(self):
        # One hospital spelled several ways is deduplicated by referencia, so
        # the name itself must not be unique.
        self.add_center(referencia="ORG-1", nombre="HOSPITAL A")
        self.add_center(referencia="ORG-2", nombre="HOSPITAL A")
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM centers").fetchone()[0], 2)

    def test_rejects_duplicate_name_when_referencia_is_missing(self):
        self.add_center(referencia=None, nombre="HOSPITAL SIN REF")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_center(referencia=None, nombre="HOSPITAL SIN REF")

    def test_many_sites_may_share_a_null_referencia(self):
        self.add_center(referencia=None, nombre="HOSPITAL X")
        self.add_center(referencia=None, nombre="HOSPITAL Y")
        self.assertEqual(
            self.con.execute(
                "SELECT COUNT(*) FROM centers WHERE referencia IS NULL"
            ).fetchone()[0], 2)


class TestStudyCenters(CenterTestCase):
    def setUp(self):
        super().setUp()
        self.center = self.add_center()
        self.other = self.add_center(referencia="ORG-2", nombre="HOSPITAL B")

    def test_same_center_twice_in_one_study_under_different_departments(self):
        self.link_center(departamento="ENDOCRINOLOGIA")
        self.link_center(departamento="CARDIOLOGIA")
        self.assertEqual(
            self.con.execute(
                "SELECT COUNT(*) FROM study_centers WHERE study_id = 'study-1'"
            ).fetchone()[0], 2)

    def test_one_center_in_two_regions_across_studies(self):
        # The Clinica Universidad de Navarra case: one referencia, two campuses.
        self.link_center(study_id="study-1", provincia="NAVARRA", ccaa="NAVARRA")
        self.link_center(study_id="study-2", provincia="MADRID", ccaa="MADRID")
        self.assertEqual(
            self.con.execute(
                "SELECT COUNT(DISTINCT ccaa) FROM study_centers "
                "WHERE center_id = ?", (self.center,)).fetchone()[0], 2)

    def test_rejects_an_exact_repeat_of_all_six_columns(self):
        self.link_center()
        with self.assertRaises(sqlite3.IntegrityError):
            self.link_center()

    def test_blank_department_collapses_a_repeat(self):
        # The rule the loader must honour: '' behaves as a value, so a second
        # blank-department row for the same site is caught as a duplicate.
        self.link_center(departamento="")
        with self.assertRaises(sqlite3.IntegrityError):
            self.link_center(departamento="")

    def test_key_columns_reject_null(self):
        for column in ("departamento", "provincia", "ccaa", "cod_postal"):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.link_center(**{column: None})

    def test_rejects_unknown_study_or_center(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.link_center(study_id="no-such-study")
        with self.assertRaises(sqlite3.IntegrityError):
            self.link_center(center_id=999)

    def test_deleting_a_study_cascades_to_pairings_only(self):
        self.link_center()
        self.con.execute("DELETE FROM studies WHERE identificador = 'study-1'")
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM study_centers").fetchone()[0], 0)
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM centers").fetchone()[0], 2)

    def test_postcode_keeps_its_leading_zero(self):
        self.link_center(cod_postal="08036")
        self.assertEqual(
            self.con.execute(
                "SELECT cod_postal FROM study_centers").fetchone()[0], "08036")

    def test_reverse_and_region_lookups_use_an_index(self):
        plans = {
            "idx_study_centers_center_id":
                "SELECT study_id FROM study_centers WHERE center_id = 1",
            "idx_study_centers_ccaa":
                "SELECT study_id FROM study_centers WHERE ccaa = 'MADRID'",
        }
        for index, query in plans.items():
            with self.subTest(index=index):
                plan = " ".join(
                    r[3] for r in self.con.execute("EXPLAIN QUERY PLAN " + query))
                self.assertIn(index, plan)


if __name__ == "__main__":
    unittest.main()
