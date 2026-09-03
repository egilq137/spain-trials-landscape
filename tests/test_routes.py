"""Tests for analysis.routes (coarse groups over the canonical routes).

Success criteria:
  coverage: every canonical route produced by db.cleaning_rules has exactly
    one group, and the map has no entry for a route that no longer exists --
    the two failures that would quietly change a total, in either direction
  no smuggled defaults: an unknown route raises rather than becoming "other"
  the judgement calls the module documents are the ones it actually makes, so
    editing a comment without editing the map fails
  corpus: the group totals quoted in the module match the loaded database,
    and skip when it is absent
"""

import os
import sqlite3
import unittest

from analysis.routes import ROUTE_GROUP, route_group
from db.cleaning_rules import ROUTE_CANONICAL

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "trials.db")

# The totals the module's comments claim, per group.
EXPECTED_TOTALS = {
    "oral": 7285,
    "intravenous": 6182,
    "subcutaneous": 1782,
    "intramuscular": 356,
    "parenteral, unspecified": 298,
    "respiratory": 255,
    "skin": 196,
    "ocular": 152,
    "central nervous system": 87,
    "other parenteral": 54,
    "local or regional": 175,
    "multiple routes": 147,
}


class TestRouteGroups(unittest.TestCase):
    def test_every_canonical_route_has_a_group(self):
        missing = set(ROUTE_CANONICAL.values()) - set(ROUTE_GROUP)
        self.assertEqual(missing, set(), "canonical routes with no group")

    def test_no_dead_entries(self):
        # A group for a route the cleaning rules no longer produce is dead
        # weight that hides the fact that the route left.
        orphans = set(ROUTE_GROUP) - set(ROUTE_CANONICAL.values())
        self.assertEqual(orphans, set(), "grouped routes that no longer exist")

    def test_an_unknown_route_raises(self):
        with self.assertRaises(KeyError):
            route_group("intraplanetary")

    def test_the_documented_judgement_calls(self):
        # Each of these is a choice the module argues for in a comment. They
        # are asserted so that changing the map without changing the argument
        # (or the reverse) is a failure.
        self.assertEqual(route_group("sublingual"), "oral")
        self.assertEqual(route_group("buccal"), "oral")
        self.assertEqual(route_group("enteral"), "oral")
        self.assertEqual(route_group("intradermal"), "skin")
        self.assertEqual(route_group("perineural"), "central nervous system")

    def test_unspecified_and_multiple_stay_visible(self):
        # The two groups that exist to show what the source did NOT say. If
        # either were folded into a real route, a chart would read as more
        # certain than the data is.
        self.assertEqual(route_group("injection, route unspecified"),
                         "parenteral, unspecified")
        self.assertEqual(route_group("parenteral, route unspecified"),
                         "parenteral, unspecified")
        self.assertEqual(route_group("multiple routes"), "multiple routes")
        self.assertNotIn("multiple routes",
                         {route_group(r) for r in ("intravenous", "oral")})


class TestRouteGroupsAgainstCorpus(unittest.TestCase):
    """Re-measures the row counts the module quotes."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(DB_PATH):
            raise unittest.SkipTest("data/trials.db not built")
        cls.conn = sqlite3.connect(DB_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_group_totals_match_the_documented_counts(self):
        totals = {}
        rows = self.conn.execute("""
            SELECT a.nombre, COUNT(*)
            FROM interventions i
            JOIN administration_routes a ON a.route_id = i.route_id
            GROUP BY a.nombre
        """)
        for name, count in rows:
            totals[route_group(name)] = totals.get(route_group(name), 0) + count
        self.assertEqual(totals, EXPECTED_TOTALS)

    def test_grouping_loses_no_rows(self):
        with_route = self.conn.execute(
            "SELECT COUNT(*) FROM interventions WHERE route_id IS NOT NULL"
        ).fetchone()[0]
        self.assertEqual(sum(EXPECTED_TOTALS.values()), with_route)


if __name__ == "__main__":
    unittest.main()
