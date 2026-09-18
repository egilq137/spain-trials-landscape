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

from analysis import geography, hospitals, registry, therapeutic
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
HOSPITALS = GEO_DIR / "hospitals.csv"


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
def areas(_con):
    """[(eutct_code, label)] biggest first, for the area filter."""
    return [(code, "{} ({:,})".format(therapeutic.leaf(name), trials))
            for code, name, trials in therapeutic.trials_per_area(_con)]


@st.cache_resource
def hospital_codes(_con):
    """{center_id: codcnh}: which national hospital each centre row is.

    Cached for the session rather than per call: it reads every centre and
    the answer does not depend on any filter, so recomputing it each time a
    year or an area changes would match 3,293 names to redraw one map.

    `cache_resource` and not `cache_data` because the dict is read and never
    mutated, so the copy `cache_data` would make on every hit is waste.
    """
    return hospitals.codes_by_centre(
        _con, hospitals.Index(hospitals.load_hospitals(HOSPITALS)))


@st.cache_data
def placed_sites(_con, since, until, area, provinces):
    """([Site], centres lost, trials lost) for a window and its filters."""
    towns = geography.load_towns(POSTCODES)
    rows = geography.only_provinces(
        geography.site_activity(_con, since, until, area, towns,
                                hospital_codes(_con)),
        provinces)
    return geography.place_sites(rows, geography.load_postcodes(POSTCODES))


@st.cache_data
def site_map(_con, since, until, area, provinces, note):
    sites, _, _ = placed_sites(_con, since, until, area, provinces)
    return geography.sites_figure(
        sites,
        geography.load_geometry(GRAINS["province"][0]),
        geography.provinces_with_sites(_con, since, until, area, provinces),
        "Sites and their trials, {}–{}".format(since, until),
        geography.sites_subtitle(note))


def _window(data_cut_year):
    """From and to as two pickers rather than one slider.

    A range slider over fourteen years puts both handles at the far end of a
    long track, so any change is a drag across the whole width. Two lists are
    two clicks and land exactly on the year meant.

    `To` only offers years at or after `From`, so an inverted range is not
    something to validate afterwards -- it cannot be chosen.
    """
    years = list(range(COVERAGE_START, data_cut_year + 1))
    from_column, to_column = st.columns(2)
    since = from_column.selectbox(
        "From", years, index=len(years) - 3)
    until = to_column.selectbox(
        "To", [year for year in years if year >= since],
        index=len(years) - 1 - years.index(since))
    return since, until


def _filters(con):
    """The area and province pickers, and the note that names their effect."""
    area_column, province_column = st.columns(2)

    options = areas(con)
    labels = dict(options)
    area = area_column.selectbox(
        "Therapeutic area", [code for code, _ in options], index=None,
        placeholder="All areas",
        format_func=lambda code: labels[code])

    provinces = province_column.multiselect(
        "Province", sorted(geography.INE), placeholder="All provinces")
    return area, provinces


def dot_map(con, data_cut_year):
    since, until = _window(data_cut_year)
    area, provinces = _filters(con)

    notes = []
    if area:
        notes.append(dict(areas(con))[area].rsplit(" (", 1)[0])
    if provinces:
        notes.append(", ".join(province.title() for province in provinces))
    note = " · ".join(notes) if notes else None

    sites, lost_sites, lost_trials = placed_sites(
        con, since, until, area, tuple(provinces))
    if not sites:
        st.info("No sites match these filters.")
        return

    charts.render_fixed(
        site_map(con, since, until, area, tuple(provinces), note))

    # Only when there is something to report: "0 sites have no usable
    # postcode" is a sentence about nothing, and it was on the page every
    # time the filters happened to exclude the ones that do.
    if lost_sites:
        st.caption(
            "{:,} more sites have no usable postcode and are not on the map, "
            "nor are the {:,} trials they ran.".format(
                lost_sites, lost_trials))

    _site_detail(con, sites, since, until, area)


def _site_detail(con, sites, since, until, area):
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

    studies = geography.studies_at(con, chosen.center_ids, since, until, area)
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
