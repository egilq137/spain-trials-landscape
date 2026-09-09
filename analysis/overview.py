"""The size of the landscape, as the four numbers a dashboard leads with.

Every count here is scoped to the analysed corpus -- studies authorised from
`volume.COVERAGE_START` -- and not to the tables. The distinction is the whole
reason this module exists, because two of the four numbers differ between the
two readings:

    trials    11,843 rows loaded    11,834 authorised from 2013
    sponsors   2,959 rows loaded     2,957 sponsoring a study from 2013
    centres    3,293 rows loaded     3,293
    areas         55 rows loaded        55

The gaps are the same mechanism one level apart. 9 studies are authorised
before REEC's coverage boundary and are excluded from every chart in this
project (PROJECT_SPEC 3.2d); 2 sponsors appear on those studies and nowhere
else, so once the studies go the sponsors sponsor nothing in the analysed
period. They keep their row and lose their trials.

**`run_pipeline.EXPECTED_ROWS` is not the oracle for these numbers**, and the
Phase 5 handoff is wrong to say a card disagreeing with it is wrong. That dict
answers "did the loader write every row it should have", which has to count
the excluded studies -- a row silently vanishing during a load is exactly what
it exists to catch. These functions answer "how big is the thing the charts
describe". Different question, different denominator, and a KPI card that
quoted 11,843 would contradict every chart drawn beneath it on the same page.

Centres and areas are counted through their bridges rather than as table rows
for the same reason, even though today both give the same answer: the number
that stays correct when the corpus is filtered is the one derived from the
corpus, and a count that happens to agree is not the same as a count that
agrees for a reason.
"""

import collections

from analysis.volume import COVERAGE_START, coverage, january_first

Totals = collections.namedtuple("Totals", "trials sponsors centres areas data_cut")

# Each count is its own scalar query rather than one SELECT of four
# subqueries. They are read once per session behind a cache, so the cost is
# nothing and the gain is that each one can be read, and argued with, alone.
_TRIALS = """SELECT count(*) FROM studies
              WHERE fecha_autorizacion_aemps >= ?"""

_SPONSORS = """SELECT count(DISTINCT sponsor_id) FROM studies
                WHERE fecha_autorizacion_aemps >= ?"""

_CENTRES = """SELECT count(DISTINCT sc.center_id)
                FROM study_centers sc
                JOIN studies s ON s.identificador = sc.study_id
               WHERE s.fecha_autorizacion_aemps >= ?"""

_AREAS = """SELECT count(DISTINCT sta.eutct_code)
              FROM study_therapeutic_areas sta
              JOIN studies s ON s.identificador = sta.study_id
             WHERE s.fecha_autorizacion_aemps >= ?"""


def corpus_totals(con, since=COVERAGE_START):
    """The five things the KPI row states, all on the same corpus.

    They come back together rather than as five calls, because the failure
    this guards against is one card being scoped differently from its
    neighbours -- which is invisible on the page and wrong in the same way a
    chart quoting a second denominator is wrong.

    The data cut is delegated to `volume.coverage` rather than re-queried, so
    the date on the KPI row and the date in every chart subtitle cannot drift
    apart.
    """
    floor = january_first(since)
    scalar = lambda sql: con.execute(sql, (floor,)).fetchone()[0]
    return Totals(trials=scalar(_TRIALS),
                  sponsors=scalar(_SPONSORS),
                  centres=scalar(_CENTRES),
                  areas=scalar(_AREAS),
                  data_cut=coverage(con, since).data_cut)
