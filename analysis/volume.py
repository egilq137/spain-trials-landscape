"""Trials authorised per year -- the series, and the two facts that qualify it.

The query is one GROUP BY, and almost all of the thinking here is about what
the chart drawn from it is allowed to claim. Three decisions from
PROJECT_SPEC 3.2d shape it:

The count is on `fecha_autorizacion_aemps`, the date the trial was authorised
in Spain, because that is the only field that answers "when did this trial
start existing". `fecha_registro` answers "when did this record enter the
register", which for 3,207 studies is one afternoon in November 2017.

The series starts in 2013, REEC's coverage boundary. The 9 studies authorised
before it are not a 2009-2012 cohort: 8 are records transitioned into CTIS
that carry a backdated authorisation. Dropping them silently would be the
usual failure, so `coverage()` reports how many were dropped and the chart
says so.

No grouping by `es_ctis`. It marks which register holds the record, not which
regime authorised the trial, and both sides of that split mix two populations
-- see 3.2d and tests/test_registry_era.py. The January 2023 CTIS mandate is
a date, so it belongs on the time axis, not in a legend.
"""

import collections

# PROJECT_SPEC 3.2d. A default, not a constant used inside the SQL: a caller
# asking a different question may legitimately want a different floor, and
# the honest report of what that choice excluded comes back from coverage().
COVERAGE_START = 2013

Coverage = collections.namedtuple("Coverage", "data_cut excluded")


def january_first(year):
    """The year as a full ISO date, so the comparison is on the column.

    Filtering on substr(fecha_autorizacion_aemps, 1, 4) would work and would
    not use idx_studies_fecha_autorizacion: an index cannot help a comparison
    against a function of the column. Comparing the stored text to a date
    does, and ISO-8601 text sorts chronologically, which is the property the
    schema chose that format for.
    """
    return "{}-01-01".format(year)


def trials_per_year(con, since=COVERAGE_START):
    """[(year, studies)] over authorisation year, ascending.

    Years with no authorisations are absent rather than zero -- a GROUP BY
    cannot invent a row for a year nothing happened in. Every year from 2013
    to the data cut is present in the real corpus, so this is a statement
    about the function, not a gap the caller has to fill.
    """
    return [(int(year), studies) for year, studies in con.execute(
        """SELECT substr(fecha_autorizacion_aemps, 1, 4) AS year, count(*)
             FROM studies
            WHERE fecha_autorizacion_aemps >= ?
         GROUP BY year
         ORDER BY year""", (january_first(since),))]


def coverage(con, since=COVERAGE_START):
    """What the chart has to admit: the data cut, and what `since` excluded.

    Both are annotations on the same series and both are read from the same
    column, so they come back together rather than as two calls the caller
    could forget one of.

    data_cut is the latest authorisation date in the database, which makes
    the final year partial. Without it on the chart, a year that is eight
    months long reads as a collapse in activity.
    """
    return Coverage(*con.execute(
        """SELECT max(fecha_autorizacion_aemps),
                  sum(fecha_autorizacion_aemps < ?)
             FROM studies""", (january_first(since),)).fetchone())
