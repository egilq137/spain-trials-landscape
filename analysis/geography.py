"""Where trials happen: participation by autonomous community.

**The map measures participation, not ownership.** A trial runs at many sites
in many regions -- 45,319 (trial, region) pairs over 11,653 located trials,
about 3.9 regions each, and only 19.5% of trials run in a single region. So a
region's number is "trials with at least one site here", and the numbers sum
to far more than the corpus. Cataluña taking part in 79% of Spanish trials is
a statement about participation; nothing here says a trial *belongs* to a
region, and REEC records nothing that would.

**Regions, not provinces.** `centers.ccaa` is a clean vocabulary of 19 values
-- the 17 communities plus Ceuta and Melilla -- that matches Eurostat's NUTS
level 2 one for one. `centers.provincia` is the field with the known
assignment errors, and at province grain those errors are large (see
CENTER_CORRECTIONS below, where one row carries 193 trials).

At region grain the whole correction table moves **one trial**: Murcia 960 to
959, Comunitat Valenciana 5,181 to 5,182. Every other corrected centre belongs
to a trial that already had a site in the right region, so the region was
already counted and the wrong centre changed nothing. That is what multi-site
participation does to per-centre error -- a trial with sites in nine regions
survives one of them being mislabelled. The corrections are still worth making
and worth keeping: they are right, they are cheap, and the same table is what
a province-level map would need, where the ICO row alone is 193 trials.

**What is not on the map.** 181 studies from 2013 have no located centre: 149
report no centre at all and 32 report only centres whose region REEC never
recorded. They are counted in the denominator and named in the subtitle, not
quietly dropped -- the map would otherwise imply a coverage it does not have.
"""

import collections
import json

from analysis.volume import COVERAGE_START, GRID, INK, MUTED, SURFACE

# ---------------------------------------------------------------------------
# The seven centres whose province disagrees with their postcode
# ---------------------------------------------------------------------------
# Found by asking which centres disagree with the majority province of every
# centre sharing their postcode prefix: 7 of the 3,006 that have both a
# well-formed postcode and a province. The schema comment on centers.provincia
# says to derive the province from the postcode prefix instead. Reading the
# seven says otherwise -- **in three of them the postcode is the wrong field,
# not the province** -- so that rule would have fixed four rows and broken
# three, one of them worth 193 trials.
#
# The locality is what settles every case. It agrees with the name in all
# seven, and with the majority of sibling rows at the same postcode.
#
# Keyed on (center_key, localidad, cod_postal), the schema's UNIQUE, because
# center_id is a rowid handed out at load time and would point at a different
# centre after any change to load order.
Correction = collections.namedtuple("Correction", "provincia ccaa why")

CENTER_CORRECTIONS = {
    ("clinicaoftalmologicavissumalicante", "Alicante", "03016"): Correction(
        "ALICANTE", "COMUNITAT VALENCIANA",
        "Name, locality and postcode all say Alicante; 12 other centres at "
        "03016 say Alicante. VISSUM runs clinics in both provinces and this "
        "entry took the wrong one."),
    ("121351", "ÁVILA RURAL", "05003"): Correction(
        "AVILA", "CASTILLA Y LEÓN",
        "The site is called ÁVILA RURAL and sits at an Ávila postcode. Two "
        "sibling rows at 05003 say Ávila."),
    ("ORL-000011379", "Sant Joan Despí", "08970"): Correction(
        "BARCELONA", "CATALUÑA",
        "Sant Joan Despí is in Barcelona; 9 other centres at 08970 say so. "
        "The row is wrong twice over -- it files Burgos under "
        "Castilla-La Mancha, and Burgos is in Castilla y León."),
    ("ORG-100050057", "Santa Cruz de Tenerife", "38001"): Correction(
        "STA. CRUZ DE TENERIFE", "CANARIAS",
        "Locality and postcode agree on Tenerife; two sibling rows at 38001 "
        "say Santa Cruz."),
    # The next two have the right province already: what is missing is the
    # region, which REEC never sent. Their postcode is the wrong field.
    ("institutonacionaldeneurocienciasaplicadas", "Barcelona", "28006"):
        Correction(
            "BARCELONA", "CATALUÑA",
            "Name, locality and province all say Barcelona. 28006 is a Madrid "
            "postcode and is the odd field out; only the region was missing."),
    ("nuevastecnologiasendiabetesyendocrinologia", "Sevilla", "31003"):
        Correction(
            "SEVILLA", "ANDALUCÍA",
            "Locality and province agree on Sevilla. 31003 is Pamplona; the "
            "centre has no sibling rows to vote with it, and the postcode is "
            "the only field disagreeing."),
}

# The seventh. Read, and deliberately left alone -- enumerated here so the
# next person to run the disagreement query does not have to work it out
# again. Institut Català d'Oncologia reports Badalona, L'Hospitalet and
# Girona under one registry reference (see the centers DDL); the Girona
# campus carries L'Hospitalet's postcode, 08908. Province GERONA is right,
# the postcode is wrong, and both are in Cataluña, so nothing on a regional
# map moves. 193 trials -- the row that makes the postcode rule expensive.
CHECKED_UNCHANGED = {("ORG-100030394", "Girona", "08908")}

# ---------------------------------------------------------------------------
# REEC's region names to NUTS 2 codes
# ---------------------------------------------------------------------------
# Spain's autonomous communities are exactly NUTS level 2, so this is a
# renaming and not a reclassification: 19 to 19, no region split or merged.
# REEC writes INE's inverted forms ('MADRID, COMUNIDAD DE'); the geometry is
# keyed by code, so the spelling is confined to this table.
NUTS = {
    "ANDALUCÍA": "ES61",
    "ARAGÓN": "ES24",
    "ASTURIAS, PRINCIPADO DE": "ES12",
    "BALEARS, ILLES": "ES53",
    "CANARIAS": "ES70",
    "CANTABRIA": "ES13",
    "CASTILLA-LA MANCHA": "ES42",
    "CASTILLA Y LEÓN": "ES41",
    "CATALUÑA": "ES51",
    "CEUTA": "ES63",
    "COMUNITAT VALENCIANA": "ES52",
    "EXTREMADURA": "ES43",
    "GALICIA": "ES11",
    "MADRID, COMUNIDAD DE": "ES30",
    "MELILLA": "ES64",
    "MURCIA, REGIÓN DE": "ES62",
    "NAVARRA, COMUNIDAD FORAL DE": "ES22",
    "PAÍS VASCO": "ES21",
    "RIOJA, LA": "ES23",
}

Region = collections.namedtuple("Region", "nuts_id name trials share")


def located_pairs(con, since=COVERAGE_START):
    """[(study_id, ccaa)] with the seven corrections applied.

    The corrections are applied here, in Python, rather than as a CASE in the
    SQL: six rows of hand-checked judgement do not belong inside a query, and
    a query that carries them cannot be read without reading them too.

    Every (study, centre) pair is fetched -- 82,795 of them -- because a
    correction changes which region a pair lands in, and aggregating first
    would put four of them in the wrong bucket before the fix could apply.
    """
    pairs = []
    for study_id, key, localidad, postcode, ccaa in con.execute(
            """SELECT sc.study_id, c.center_key, c.localidad, c.cod_postal,
                      c.ccaa
                 FROM study_centers sc
                 JOIN centers c ON c.center_id = sc.center_id
                 JOIN studies st ON st.identificador = sc.study_id
                WHERE st.fecha_autorizacion_aemps >= ?""",
            ("{}-01-01".format(since),)):
        correction = CENTER_CORRECTIONS.get((key, localidad, postcode))
        region = correction.ccaa if correction else ccaa
        if region is not None:
            pairs.append((study_id, region))
    return pairs


def trials_per_region(pairs, trials):
    """[Region] descending -- distinct trials with at least one site in each.

    A trial is counted once per region however many sites it has there, and
    in every region it reaches. `share` is of all trials in the window, so
    the 181 with no located centre are in the denominator: a region's share
    is the fraction of Spanish trials it takes part in, and inflating it by
    dropping the trials nobody could place would flatter every region.
    """
    studies = collections.defaultdict(set)
    for study_id, region in pairs:
        studies[region].add(study_id)
    return sorted(
        (Region(NUTS[region], region, len(ids), 100.0 * len(ids) / trials)
         for region, ids in studies.items()),
        key=lambda region: -region.trials)


def unlocated(pairs, trials):
    """How many trials the map cannot place. Reported, never hidden."""
    return trials - len({study_id for study_id, _ in pairs})


def load_geometry(path):
    """The NUTS 2 polygons. See data/geo/README.md for provenance."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# A single hue, light to dark, from the documented sequential ramp: magnitude
# is one quantity and a second hue would imply a second thing being measured.
# The lightest step is allowed to sit near the surface because it means
# "almost none", which is what a sequential ramp's low end is for.
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95",
             "#0d366b"]


# The Canary Islands are 1,000 km off the coast, so a single map that
# contains them spends half its canvas on empty Atlantic. Spanish official
# cartography answers this with an inset box, and so does this: the same
# polygons and the same colour scale, drawn on a second geo axis at its own
# scale, with the displacement made obvious by the box rather than hidden by
# quietly moving the islands next to Andalucía.
CANARIAS = "ES70"


def figure(regions, geometry, unplaced):
    """Participation by region, as a choropleth with a Canaries inset."""
    import plotly.graph_objects as go

    # Both traces share one scale, so a colour means the same thing in the
    # inset as on the mainland. Left to itself each trace would normalise to
    # its own values, and the islands would come out the darkest place in
    # Spain.
    ceiling = max(region.share for region in regions)
    # Display names come from the geometry, not from REEC. REEC writes INE's
    # sort order -- 'MADRID, COMUNIDAD DE', 'RIOJA, LA' -- which is right for
    # an index and wrong on a map, and .title() only turns it into 'Madrid,
    # Comunidad De'. NUTS ships the natural form already.
    names = {feature["id"]: feature["properties"]["name"]
             for feature in geometry["features"]}

    def choropleth(rows, geo, showscale):
        return go.Choropleth(
            geojson=geometry, featureidkey="id", geo=geo,
            locations=[region.nuts_id for region in rows],
            z=[region.share for region in rows],
            text=[names[region.nuts_id] for region in rows],
            customdata=[region.trials for region in rows],
            colorscale=BLUE_RAMP, zmin=0, zmax=ceiling, showscale=showscale,
            marker=dict(line=dict(color=SURFACE, width=1)),
        # Horizontal and under the map: a vertical bar on the right pushed
        # the peninsula into the left half of the canvas.
            colorbar=dict(
                title=dict(text="% of Spanish trials with a site here",
                           side="top", font=dict(size=11, color=MUTED)),
                orientation="h", x=0.5, y=-0.06, xanchor="center",
                yanchor="bottom", ticksuffix="%", thickness=10, len=0.45,
                outlinewidth=0, tickfont=dict(size=11, color=MUTED)),
            hovertemplate="%{text}<br>%{customdata:,} trials, %{z:.1f}% of all"
                          "<extra></extra>")

    fig = go.Figure([
        choropleth([r for r in regions if r.nuts_id != CANARIAS],
                   "geo", True),
        choropleth([r for r in regions if r.nuts_id == CANARIAS],
                   "geo2", False)])

    fig.update_layout(
        title=dict(
            text="Where Spanish trials run: regional participation "
                 "since {}".format(COVERAGE_START),
            subtitle=dict(text=subtitle(regions, unplaced, names),
                          font=dict(size=12, color=MUTED)),
            font=dict(size=17, color=INK)),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        margin=dict(t=95, r=10, b=90, l=10), width=760, height=600,
        # Two notes rather than one line: at one line they ran through the
        # colour bar's tick labels, and the inset needs its caption beside
        # the inset rather than in a credit at the far corner.
        annotations=[
            dict(x=0.01, y=0.31, xref="paper", yref="paper", xanchor="left",
                 showarrow=False, font=dict(size=10, color=MUTED),
                 text="Canarias, at its own scale"),
            dict(x=0, y=-0.12, xref="paper", yref="paper", xanchor="left",
                 showarrow=False, font=dict(size=10, color=MUTED),
                 text="Boundaries © EuroGeographics (Eurostat GISCO, NUTS 2)")])
    fig.update_geos(visible=False, projection_type="mercator", bgcolor=SURFACE)
    # The peninsula, the Balearics, Ceuta and Melilla. The latitude floor is
    # 34.9 rather than the mainland's 36 because Ceuta and Melilla are on the
    # African coast, and a map of Spanish trial sites that cropped two
    # autonomous cities would be wrong in the way this whole module is about.
    fig.update_layout(geo=dict(domain=dict(x=[0, 1], y=[0, 1]),
                               lonaxis_range=[-9.8, 4.6],
                               lataxis_range=[34.9, 44.0]),
                      geo2=dict(domain=dict(x=[0.0, 0.22], y=[0.0, 0.30]),
                                lonaxis_range=[-18.3, -13.2],
                                lataxis_range=[27.5, 29.5],
                                visible=False, bgcolor=SURFACE))
    return fig


def subtitle(regions, unplaced, names):
    """The two things a reader has to know before reading the colours."""
    leader = regions[0]
    return ("A trial counts in every region it has a site in, so the regions "
            "overlap: {} alone takes part in {:.0f}% of them.<br>{:,} trials "
            "are not on the map — they report no centre, or none whose "
            "region was recorded.".format(
                names[leader.nuts_id], leader.share, unplaced))
