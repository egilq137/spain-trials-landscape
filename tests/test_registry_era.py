"""What kind of variable studies.es_ctis is.

Not a test of a module -- there is no module. es_ctis is a GENERATED column
in db/schema.sql, and this file pins down what it does and does not mean, so
that no analysis reaches for it as a regime marker. It is a characterisation
test: it asserts the shape the data actually has, and it fails when a cache
refresh changes that shape, which is exactly when the reading below needs
re-checking.

The evidence and the reasoning are in PROJECT_SPEC 3.2d; this is the same
evidence as executable code.

Success criteria:
  what it is: es_ctis is identifier length and nothing else -- 14 chars
    EudraCT, 17 chars CTIS. It is a property of the register the record lives
    in today.
  what it is not: it does not mark the regime a trial was authorised under.
    1,679 studies authorised before the January 2023 CTIS mandate carry a
    CTIS identifier, and 86 authorised after it still carry a EudraCT one.
  why they disagree: 1,620 of those 1,679 were registered AFTER their own
    authorisation date -- old trials whose records were migrated into CTIS
    during the EU CTR transition window, keeping the original authorisation.
    The remaining 59 were registered BEFORE authorisation, in 2022: genuine
    submissions through CTIS while it was still voluntary.
  the other direction: the 86 post-2023 EudraCT records are old submissions
    (identifier years 2020-2022) authorised late, not new EudraCT trials.
"""

import sqlite3
import unittest
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "trials.db"

requires_database = unittest.skipUnless(
    DB_PATH.exists(),
    "data/trials.db is a build artifact; run `python run_pipeline.py build`")

# The mandate date, as a string, because every date in the schema is ISO text.
CTIS_MANDATE = "2023-01-01"


@requires_database
class TestEsCtis(unittest.TestCase):
    """Re-measures what PROJECT_SPEC 3.2d claims about es_ctis."""

    @classmethod
    def setUpClass(cls):
        # Read-only: a test has no business writing to the build artifact.
        cls.con = sqlite3.connect(
            "file:{}?mode=ro".format(DB_PATH.as_posix()), uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def rows(self, sql):
        return self.con.execute(sql).fetchall()

    def count(self, where):
        return self.con.execute(
            "SELECT count(*) FROM studies WHERE " + where).fetchone()[0]

    def test_es_ctis_is_identifier_length_and_nothing_else(self):
        # If this ever returns more than two pairs, the column has stopped
        # being a clean partition and every reading below is suspect.
        self.assertEqual(
            self.rows("SELECT es_ctis, length(identificador), count(*) "
                      "FROM studies GROUP BY 1, 2 ORDER BY 1"),
            [(0, 14, 6839), (1, 17, 5004)])

    def test_it_does_not_mark_the_authorisation_regime(self):
        # Both directions, because either one alone could be read as an edge
        # case. Together they say the two variables measure different things.
        self.assertEqual(
            self.count("es_ctis = 1 AND fecha_autorizacion_aemps < '{}'"
                       .format(CTIS_MANDATE)), 1679)
        self.assertEqual(
            self.count("es_ctis = 0 AND fecha_autorizacion_aemps >= '{}'"
                       .format(CTIS_MANDATE)), 86)

    def test_most_pre_mandate_ctis_records_were_migrated(self):
        # Registered after the trial was already authorised: the record moved
        # register, the trial did not change regime. Their identifiers are
        # all issued in the transition window, never contemporaneous with the
        # authorisation they carry -- one is authorised in 2009.
        migrated = ("es_ctis = 1 AND fecha_autorizacion_aemps < '{}' "
                    "AND fecha_registro > fecha_autorizacion_aemps"
                    .format(CTIS_MANDATE))
        self.assertEqual(self.count(migrated), 1620)
        self.assertEqual(
            self.rows("SELECT min(substr(identificador, 1, 4)), "
                      "       max(substr(identificador, 1, 4)), "
                      "       min(fecha_autorizacion_aemps) "
                      "FROM studies WHERE " + migrated),
            [("2022", "2025", "2009-03-04")])

    def test_the_rest_are_voluntary_ctis_before_the_mandate(self):
        # Registered BEFORE authorisation, so the trial really was submitted
        # through CTIS -- while it was still optional. CTIS opened on
        # 2022-01-31; the earliest of these registers three weeks later.
        early = ("es_ctis = 1 AND fecha_autorizacion_aemps < '{}' "
                 "AND fecha_registro <= fecha_autorizacion_aemps"
                 .format(CTIS_MANDATE))
        self.assertEqual(self.count(early), 59)
        self.assertEqual(
            self.rows("SELECT min(fecha_registro), min(fecha_autorizacion_aemps) "
                      "FROM studies WHERE " + early),
            [("2022-02-24", "2022-05-27")])

    def test_the_post_mandate_eudract_records_are_old_submissions(self):
        # The mirror image: nothing new entered EudraCT after the mandate,
        # these are 2020-2022 submissions that took until 2023+ to authorise.
        self.assertEqual(
            self.rows("SELECT substr(identificador, 1, 4), count(*) "
                      "FROM studies "
                      "WHERE es_ctis = 0 AND fecha_autorizacion_aemps >= '{}' "
                      "GROUP BY 1 ORDER BY 1".format(CTIS_MANDATE)),
            [("2020", 7), ("2021", 21), ("2022", 58)])


if __name__ == "__main__":
    unittest.main()
