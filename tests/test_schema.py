"""Tests for db/schema.sql -- slice 1, sponsors and studies.

Every constraint is asserted to REJECT its bad value. A test that only runs
the script proves the SQL parses, which is not what the constraints are for:
the schema is the last line of defence between a mis-transformed record and
the analysis, so each rule has to be shown refusing something.

Success criteria:
  sponsors: a sponsor is identified by promotor_key, so two spellings that
    normalise alike cannot both load; and neither name column may be blank,
    because '' is what an unapplied cleaning rule leaves behind
  identificador: only the two real formats load -- EudraCT (14 chars) and
    CTIS (17). Nothing unrecognised appeared in 11,847 records, so anything
    else is a transform fault, not new data
  es_ctis: derived from the identifier by the database, never inserted, so it
    cannot disagree with the id it is read from
  sponsor_id: a study cannot reference a sponsor that does not exist, and a
    sponsor with studies cannot be deleted out from under them
  dates: ISO-8601 only. The source ships 'DD-MM-YYYY', and that is exactly
    the value that must not load silently -- it parses as a date to a reader
    and sorts wrongly to SQLite
  no survival columns: censored/survival_start/survival_end must stay absent.
    The estimand is contested and belongs in analysis/ (PROJECT_SPEC 3.2c)
  flags: 0/1 only, and -1 is rejected everywhere. The 12 flags that carry the
    sentinel accept NULL because the loader maps it; the other 6 and all 16
    proposito flags do not, because -1 never occurs in them
  poblacion_total: NULL or a positive count. 0 means "not reported" and is
    mapped by the loader, so a stored 0 is a bug rather than a small trial
  dropped columns: the 8 data-source flags stay out. Inserting one must fail,
    so the block cannot creep back in unnoticed
  STRICT: declared types are enforced -- text that is not a number cannot
    land in an integer column
"""

import sqlite3
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "db" / "schema.sql"

# The 12 poblacion flags that carry -1 in the corpus. The loader maps it to
# NULL, so these columns are nullable; the CHECK still rejects a stored -1.
NULLABLE_FLAGS = (
    "mujer_usa", "mujer_no_usa", "embarazadas", "lactancia", "urgencia",
    "incapaces", "intrauteros", "prematuros", "recien_nacido", "preescolar",
    "ninos", "adolescentes",
)

# The 6 poblacion flags that never carry it, plus all 16 kept proposito flags.
NOT_NULL_FLAGS = (
    "voluntarios_sanos", "pacientes", "pob_vulnerable",
    "adultos", "ancianos", "menores",
    "fase_uno", "fase_dos", "fase_tres", "fase_cuatro",
    "diagnostico", "profilaxis", "tratamiento",
    "seguridad", "eficacia", "farmacocinetica", "farmacodinamica",
    "bioequivalencia", "dosis", "farmacogenetica", "farmacogenomica",
    "farmacoeconomica",
)

DATES_NOT_NULL = ("fecha_autorizacion_aemps", "fecha_registro")

DATES_NULLABLE = (
    "fecha_inicio_prevista", "fecha_inicio_real", "fecha_fin_real_espana",
    "fecha_fin_real_global", "fecha_interrupcion", "fecha_reinicio",
    "fecha_fin_prematuro",
)

# Seven are constant 0 across the corpus; otras_fuentes varies but means
# "other" relative to seven categories nobody ticks.
DROPPED_COLUMNS = (
    "atencion_primaria", "atencion_personalizada", "hospitalizacion",
    "medico", "farmaceutico", "historial_clinico", "bases_datos",
    "otras_fuentes", "censored", "survival_start", "survival_end",
)


def valid_study(**overrides):
    """A row every constraint accepts, so one changed value is the only fault."""
    row = {
        "identificador": "2019-000302-29",
        "sponsor_id": 1,
        "acronimo": "RECOVERY",
        "enfermedad_rara": 0,
        "poblacion_total": 180,
    }
    for column in DATES_NOT_NULL + DATES_NULLABLE:
        row[column] = "2019-12-18"
    for column in NULLABLE_FLAGS + NOT_NULL_FLAGS:
        row[column] = 0
    row.update(overrides)
    return row


class SchemaTestCase(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.addCleanup(self.con.close)
        self.con.executescript(SCHEMA.read_text(encoding="utf-8"))
        # Connection-scoped: SQLite ignores foreign keys without it, and
        # executescript's PRAGMA does not survive into this connection's use.
        self.con.execute("PRAGMA foreign_keys = ON")
        self.add_sponsor()

    def add_sponsor(self, key="astrazeneca ab", name="AstraZeneca AB"):
        return self.con.execute(
            "INSERT INTO sponsors (promotor_key, promotor) VALUES (?, ?)",
            (key, name)).lastrowid

    def insert_study(self, **overrides):
        row = valid_study(**overrides)
        self.con.execute(
            "INSERT INTO studies ({}) VALUES ({})".format(
                ", ".join(row), ", ".join("?" * len(row))),
            list(row.values()))

    def assertRejected(self, **overrides):
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_study(**overrides)


class SponsorsTestCase(SchemaTestCase):
    def test_a_valid_sponsor_loads_and_is_given_an_id(self):
        sponsor_id = self.add_sponsor("pfizer inc", "Pfizer Inc.")
        self.assertEqual(
            self.con.execute(
                "SELECT promotor FROM sponsors WHERE sponsor_id = ?",
                (sponsor_id,)).fetchone()[0],
            "Pfizer Inc.")

    def test_two_spellings_of_one_identity_cannot_both_load(self):
        # The whole point of keying on the normalised form: 427 values across
        # 315 sponsors are formatting variants of a name already present.
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_sponsor("astrazeneca ab", "Astrazeneca AB")

    def test_display_name_may_repeat_because_only_identity_is_unique(self):
        # Two genuinely different keys sharing a display spelling is allowed;
        # only promotor_key carries UNIQUE.
        self.add_sponsor("astrazeneca ab uk", "AstraZeneca AB")

    def test_neither_name_may_be_null(self):
        for column in ("promotor_key", "promotor"):
            with self.subTest(column=column), \
                    self.assertRaises(sqlite3.IntegrityError):
                self.con.execute(
                    "INSERT INTO sponsors ({}) VALUES (?)".format(column),
                    ("something",))

    def test_neither_name_may_be_blank(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_sponsor("", "AstraZeneca AB")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_sponsor("astrazeneca ab uk", "")


class StudiesIdentityTestCase(SchemaTestCase):
    def test_both_real_identifier_formats_load(self):
        self.insert_study(identificador="2019-000302-29")
        self.insert_study(identificador="2023-506669-70-00")
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM studies").fetchone()[0], 2)

    def test_anything_but_those_two_formats_is_rejected(self):
        for bad in ("", "not-an-id", "2019-000302", "2019-000302-2",
                    "2019-000302-2X", "2019-000302-29-00-00",
                    " 2019-000302-29"):
            with self.subTest(identificador=bad):
                self.assertRejected(identificador=bad)

    def test_identifier_is_unique(self):
        self.insert_study()
        self.assertRejected()

    def test_identifier_may_not_be_null(self):
        self.assertRejected(identificador=None)

    def test_es_ctis_is_read_off_the_identifier(self):
        self.insert_study(identificador="2019-000302-29")
        self.insert_study(identificador="2023-506669-70-00")
        self.assertEqual(
            dict(self.con.execute(
                "SELECT identificador, es_ctis FROM studies").fetchall()),
            {"2019-000302-29": 0, "2023-506669-70-00": 1})

    def test_es_ctis_cannot_be_written(self):
        # Generated, so a loader cannot set it to something the id contradicts.
        with self.assertRaises(sqlite3.OperationalError):
            self.insert_study(es_ctis=1)

    def test_acronym_is_optional_but_never_blank(self):
        # Blanks and placeholders load as NULL; '' means a rule was skipped.
        self.insert_study(identificador="2020-000302-29", acronimo=None)
        self.assertRejected(acronimo="")

    def test_rare_disease_flag_takes_only_zero_or_one(self):
        for bad in (None, -1, 2, "yes"):
            with self.subTest(enfermedad_rara=bad):
                self.assertRejected(enfermedad_rara=bad)


class StudiesSponsorTestCase(SchemaTestCase):
    def test_a_study_cannot_name_a_sponsor_that_does_not_exist(self):
        self.assertRejected(sponsor_id=999)

    def test_sponsor_is_required(self):
        self.assertRejected(sponsor_id=None)

    def test_a_sponsor_with_studies_cannot_be_deleted(self):
        # ON DELETE RESTRICT: a study without a sponsor is not a fact REEC has.
        self.insert_study()
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("DELETE FROM sponsors WHERE sponsor_id = 1")


class StudiesDatesTestCase(SchemaTestCase):
    def test_the_source_date_format_is_rejected(self):
        # 'DD-MM-YYYY' is what the API sends. It looks like a date and sorts
        # wrongly, which is the failure the GLOB exists to prevent.
        for column in DATES_NOT_NULL + DATES_NULLABLE:
            with self.subTest(column=column):
                self.assertRejected(**{column: "18-12-2019"})

    def test_malformed_dates_are_rejected(self):
        for bad in ("", "2019-12-1", "2019-1-18", "2019/12/18", "2019-12-18T00:00",
                    "not a date"):
            with self.subTest(value=bad):
                self.assertRejected(fecha_autorizacion_aemps=bad)

    def test_the_two_always_present_dates_are_required(self):
        for column in DATES_NOT_NULL:
            with self.subTest(column=column):
                self.assertRejected(**{column: None})

    def test_the_other_seven_may_be_null(self):
        self.insert_study(**{column: None for column in DATES_NULLABLE})

    def test_no_survival_or_censoring_columns_exist(self):
        columns = {row[1] for row in
                   self.con.execute("PRAGMA table_info(studies)")}
        self.assertEqual(
            columns & {"censored", "survival_start", "survival_end"}, set())


class StudiesFlagsTestCase(SchemaTestCase):
    def test_every_flag_rejects_the_sentinel_and_any_other_value(self):
        # -1 must be mapped by the loader, not stored: averaging it silently
        # corrupts every proportion computed from these columns.
        for column in NULLABLE_FLAGS + NOT_NULL_FLAGS:
            for bad in (-1, 2, "yes"):
                with self.subTest(column=column, value=bad):
                    self.assertRejected(**{column: bad})

    def test_the_twelve_sentinel_carrying_flags_accept_null(self):
        self.insert_study(**{column: None for column in NULLABLE_FLAGS})

    def test_the_other_flags_reject_null(self):
        for column in NOT_NULL_FLAGS:
            with self.subTest(column=column):
                self.assertRejected(**{column: None})

    def test_phase_is_four_independent_columns(self):
        # 1,436 studies set two flags; an enum would mangle 12.1% of the corpus.
        self.insert_study(fase_dos=1, fase_tres=1)
        self.assertEqual(
            self.con.execute(
                "SELECT fase_uno, fase_dos, fase_tres, fase_cuatro "
                "FROM studies").fetchone(),
            (0, 1, 1, 0))


class StudiesTotalTestCase(SchemaTestCase):
    def test_a_planned_total_of_zero_is_rejected(self):
        # 0 means "not reported" in 2,201 records and loads as NULL.
        self.assertRejected(poblacion_total=0)

    def test_negative_totals_are_rejected(self):
        self.assertRejected(poblacion_total=-1)

    def test_null_is_accepted(self):
        self.insert_study(poblacion_total=None)

    def test_a_genuinely_large_total_is_accepted(self):
        # 114,011: a pragmatic influenza-vaccine trial across Galicia. Checked
        # against the record rather than judged by size.
        self.insert_study(poblacion_total=114011)


class StudiesDroppedColumnsTestCase(SchemaTestCase):
    def test_dropped_columns_do_not_exist(self):
        for column in DROPPED_COLUMNS:
            with self.subTest(column=column), \
                    self.assertRaises(sqlite3.OperationalError):
                self.insert_study(**{column: 0})


class StrictTypingTestCase(SchemaTestCase):
    def test_a_non_numeric_string_cannot_land_in_an_integer_column(self):
        # STRICT is why this raises; without it SQLite would store 'many'.
        self.assertRejected(poblacion_total="many")

    def test_the_two_indexes_the_joins_depend_on_exist(self):
        names = {row[0] for row in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
        self.assertIn("idx_studies_sponsor_id", names)
        self.assertIn("idx_studies_fecha_autorizacion", names)


if __name__ == "__main__":
    unittest.main()
