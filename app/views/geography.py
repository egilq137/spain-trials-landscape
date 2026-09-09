"""Where Spanish trials run, at two grains.

The maps measure **participation**, not ownership: a trial with sites in nine
regions is counted in all nine, so the regions overlap and their shares sum to
roughly 390% rather than to 100%. That is a property of the question, not an
error, and `geography.subtitle` states it on the figure itself.

The denominator comes from `analysis.overview.corpus_totals`, the same
function the KPI cards read, so the map and the card at the top of the
dashboard cannot quote different corpus sizes.
"""

import streamlit as st

from analysis import geography
from analysis.volume import COVERAGE_START
from app import charts
from app.session import GEO_DIR, open_database
from app.views.overview import corpus_totals

GRAINS = {
    "region": (GEO_DIR / "spain-ccaa.geojson",
               "Where Spanish trials run: regional participation since {}"),
    "province": (GEO_DIR / "spain-provinces.geojson",
                 "Where Spanish trials run: participation by province "
                 "since {}"),
}


@st.cache_data
def participation_map(_con, grain, trials):
    """The finished figure for one grain.

    Mirrors run_analysis.write_map's assembly rather than importing it: that
    function's job is to write a file, this one's is to return a figure, and
    the two entrypoints share the analysis functions instead of sharing a
    third thing that would have to serve both.

    `trials` is passed in rather than counted here so that it stays hashable
    and part of the cache key -- the denominator changing has to invalidate
    the map, because the map is drawn in percentages of it.
    """
    geometry_path, title = GRAINS[grain]
    pairs = (geography.region_pairs(_con) if grain == "region"
             else geography.province_pairs(_con))
    places = geography.participation(pairs, trials)
    geometry = geography.load_geometry(geometry_path)
    unplaced = geography.unlocated(pairs, trials)
    return geography.figure(
        places, geometry, title.format(COVERAGE_START),
        geography.subtitle(places, geometry, unplaced, grain))


def page():
    con = open_database()
    trials = corpus_totals(con).trials

    st.title("Geography")
    st.caption(
        "A region's number is *trials with at least one site here*. Trials "
        "run at about 3.9 regions each, so a trial is counted in every region "
        "it reaches and the shares deliberately sum to more than 100%."
    )

    regions, provinces = st.tabs(["Regions (CCAA)", "Provinces"])
    with regions:
        charts.render_fixed(participation_map(con, "region", trials))
    with provinces:
        charts.render_fixed(participation_map(con, "province", trials))
        st.caption(
            "Provinces are not a NUTS level: the Balearics are three NUTS 3 "
            "units and the Canaries seven, so ten polygons merge into three "
            "provinces. One more trial is unplaceable here than at region "
            "grain, because a centre can carry a region and no province."
        )
