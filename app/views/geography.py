"""Where Spanish trials run, at three grains.

The two choropleths measure **participation**: a trial with sites in nine
regions is counted in all nine, so the regions overlap and their shares sum to
roughly 390% rather than to 100%. That is a property of the question, not an
error, and `geography.subtitle` states it on the figure itself.

The dot map is a different unit and says so: **a trial has no location, its
sites do**, so the marks are hospitals sized by the trials authorised there.

The choropleth denominator comes from `analysis.overview.corpus_totals`, the
same function the KPI cards read, so the map and the card at the top of the
dashboard cannot quote different corpus sizes.
"""

import streamlit as st

from analysis import geography, registry
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
POSTCODES = GEO_DIR / "postcodes.csv"


@st.cache_data
def participation_map(_con, grain, trials):
    """The finished figure for one choropleth grain.

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


@st.cache_data
def placed_sites(_con, since, until):
    """([Site], centres lost, trials lost) for a window."""
    return geography.place_sites(
        geography.site_activity(_con, since, until),
        geography.load_postcodes(POSTCODES))


@st.cache_data
def site_map(_con, since, until):
    sites, lost_sites, lost_trials = placed_sites(_con, since, until)
    return geography.sites_figure(
        sites,
        "Sites and their trials, {}–{}".format(since, until),
        geography.sites_subtitle(sites, lost_sites, lost_trials,
                                 since, until))


def dot_map(con, data_cut_year):
    since, until = st.slider(
        "Trials authorised in", COVERAGE_START, data_cut_year,
        (data_cut_year - 2, data_cut_year))
    if until == data_cut_year:
        st.caption(
            "{} is a partial year — the data cut is mid-year, so its marks "
            "are smaller than a full year's.".format(data_cut_year))

    sites, _, _ = placed_sites(con, since, until)
    if not sites:
        st.info("No sites in these years.")
        return

    charts.render_fixed(site_map(con, since, until))
    _site_detail(con, sites, since, until)


def _site_detail(con, sites, since, until):
    """The trials at one hospital, as links to the register holding them.

    A picker rather than a click on the map, for two reasons. Hospitals
    sharing a postcode share a mark, so a click is ambiguous exactly where
    the map is densest -- picking by name is the only way to say which of the
    seven hospitals in one Madrid postcode is meant. And the marks run down
    to three pixels, which is a hard target for a mouse and an impossible one
    without one.

    The map still answers "where and how much" on hover. This answers "which
    trials", which a hover label could not hold anyway: it is a tooltip, not
    part of the document, so a link in it cannot be clicked.
    """
    chosen = st.selectbox(
        "Trials at", sites, index=None,
        placeholder="Choose a hospital to list its trials",
        format_func=lambda site: "{} · {} · {:,} trials".format(
            site.name, site.localidad, site.trials))
    if chosen is None:
        return

    studies = geography.studies_at(con, chosen.center_id, since, until)
    st.caption("{:,} trials authorised {}–{}, newest first.".format(
        len(studies), since, until))
    for identificador, es_ctis, year in studies[:50]:
        st.markdown("- [{}]({}) · {} · {}".format(
            identificador, registry.public_url(identificador, es_ctis),
            year, registry.register_of(es_ctis)))
    if len(studies) > 50:
        st.caption("... and {:,} more.".format(len(studies) - 50))


def page():
    con = open_database()
    totals = corpus_totals(con)
    trials = totals.trials

    st.title("Geography")

    regions, provinces, dots = st.tabs(
        ["Regions (CCAA)", "Provinces", "Sites"])
    with regions:
        st.caption(
            "A region's number is *trials with at least one site here*. "
            "Trials run at about 3.9 regions each, so a trial is counted in "
            "every region it reaches and the shares deliberately sum to more "
            "than 100%.")
        charts.render_fixed(participation_map(con, "region", trials))
    with provinces:
        st.caption(
            "The same count at a finer grain. Provinces are not a NUTS "
            "level: the Balearics are three NUTS 3 units and the Canaries "
            "seven, so ten polygons merge into three provinces.")
        charts.render_fixed(participation_map(con, "province", trials))
    with dots:
        st.caption(
            "One mark per hospital, not per trial — a trial runs at 7.2 "
            "sites on average, so it has no single location. Marks are sized "
            "by area, so twice the ink is twice the trials.")
        dot_map(con, int(totals.data_cut[:4]))
