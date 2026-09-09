"""Where trials happen: participation by region and by province.

**The map measures participation, not ownership.** A trial runs at many sites
in many regions -- 45,319 (trial, region) pairs over 11,653 located trials,
about 3.9 regions each, and only 19.5% of trials run in a single region. So a
place's number is "trials with at least one site here", and the numbers sum
to far more than the corpus. Cataluña taking part in 79% of Spanish trials is
a statement about participation; nothing here says a trial *belongs* to a
region, and REEC records nothing that would.

**Two grains, and the province one is where the errors bite.**
`centers.ccaa` is a clean vocabulary of 19 values matching Eurostat's NUTS
level 2 one for one. `centers.provincia` is a clean vocabulary of 52 with
wrong assignments in it (CENTER_CORRECTIONS below). At region grain the whole
correction table moves **one trial**: Murcia 960 to 959, Comunitat Valenciana
5,181 to 5,182. Every other corrected centre belongs to a trial that already
had a site in the right region, so the region was counted anyway -- multi-site
participation absorbs per-centre error. At province grain there is less to
absorb it, because a trial with sites in nine regions may still have only one
site in Girona.

**What is not on the maps.** 181 studies from 2013 have no located centre: 149
report no centre at all and 32 report only centres whose place REEC never
recorded. They are counted in the denominator and named in the subtitle, not
quietly dropped -- a map would otherwise imply a coverage it does not have.
"""

import collections
import csv
import json

from analysis.volume import COVERAGE_START, GRID, INK, MUTED, SERIES, SURFACE


def _first_of(year):
    """January 1st of `year`, as the stored ISO text. See volume.january_first
    for why the comparison is against a date rather than a substring."""
    return "{}-01-01".format(year)

# ---------------------------------------------------------------------------
# The seven centres whose province disagrees with their postcode
# ---------------------------------------------------------------------------
# Found by asking which centres disagree with the majority province of every
# centre sharing their postcode prefix: 7 of the 3,006 that have both a
# well-formed postcode and a province. The schema comment on centers.provincia
# used to say to derive the province from the postcode prefix instead. Reading
# the seven says otherwise -- **in three of them the postcode is the wrong
# field, not the province** -- so that rule would have fixed four rows and
# broken three, one of them worth 193 trials.
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
# map moves. On the province map it is 193 trials, and it is the whole
# argument against the postcode rule.
CHECKED_UNCHANGED = {("ORG-100030394", "Girona", "08908")}

# ---------------------------------------------------------------------------
# REEC's place names to the codes the geometry is drawn with
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

# Provinces are keyed by their INE code, which is also the postcode prefix --
# so this table is checkable rather than merely asserted, and
# tests/test_geography.py checks it: for every code, the most common province
# among centres whose postcode starts with those two digits is the province
# named here. All 52 agree.
#
# REEC writes the Castilian forms (GERONA, LÉRIDA, VIZCAYA/BIZKAIA); the
# geometry carries the official ones (Girona, Lleida, Bizkaia). Same places,
# and the code is what joins them.
INE = {
    "ALAVA": "01", "ALBACETE": "02", "ALICANTE": "03", "ALMERÍA": "04",
    "AVILA": "05", "BADAJOZ": "06", "BALEARES": "07", "BARCELONA": "08",
    "BURGOS": "09", "CÁCERES": "10", "CÁDIZ": "11", "CASTELLÓN": "12",
    "CIUDAD REAL": "13", "CÓRDOBA": "14", "CORUÑA": "15", "CUENCA": "16",
    "GERONA": "17", "GRANADA": "18", "GUADALAJARA": "19", "GUIPÚZCOA": "20",
    "HUELVA": "21", "HUESCA": "22", "JAÉN": "23", "LEÓN": "24",
    "LÉRIDA": "25", "LA RIOJA": "26", "LUGO": "27", "MADRID": "28",
    "MÁLAGA": "29", "MURCIA": "30", "NAVARRA": "31", "OURENSE": "32",
    "ASTURIAS": "33", "PALENCIA": "34", "LAS PALMAS": "35",
    "PONTEVEDRA": "36", "SALAMANCA": "37", "STA. CRUZ DE TENERIFE": "38",
    "CANTABRIA": "39", "SEGOVIA": "40", "SEVILLA": "41", "SORIA": "42",
    "TARRAGONA": "43", "TERUEL": "44", "TOLEDO": "45", "VALENCIA": "46",
    "VALLADOLID": "47", "VIZCAYA/BIZKAIA": "48", "ZAMORA": "49",
    "ZARAGOZA": "50", "CEUTA": "51", "MELILLA": "52",
}

Place = collections.namedtuple("Place", "code trials share")


def _pairs(con, region_column, codes, since):
    """[(study_id, code)] for one geographic grain, corrections applied.

    The corrections are applied here, in Python, rather than as a CASE in the
    SQL: six rows of hand-checked judgement do not belong inside a query, and
    a query that carries them cannot be read without reading them too.

    Every (study, centre) pair is fetched -- 82,795 of them -- because a
    correction changes which place a pair lands in, and aggregating first
    would put the corrected ones in the wrong bucket before the fix applied.

    A centre whose place REEC never recorded drops out of the pairs. It does
    not drop out of the corpus: the study stays in the denominator and turns
    up in unlocated().
    """
    pairs = []
    for study_id, key, localidad, postcode, region, province in con.execute(
            """SELECT sc.study_id, c.center_key, c.localidad, c.cod_postal,
                      c.ccaa, c.provincia
                 FROM study_centers sc
                 JOIN centers c ON c.center_id = sc.center_id
                 JOIN studies st ON st.identificador = sc.study_id
                WHERE st.fecha_autorizacion_aemps >= ?""",
            ("{}-01-01".format(since),)):
        correction = CENTER_CORRECTIONS.get((key, localidad, postcode))
        if correction is not None:
            region, province = correction.ccaa, correction.provincia
        name = region if region_column else province
        if name is not None:
            pairs.append((study_id, codes[name]))
    return pairs


def region_pairs(con, since=COVERAGE_START):
    """[(study_id, NUTS 2 code)]."""
    return _pairs(con, True, NUTS, since)


def province_pairs(con, since=COVERAGE_START):
    """[(study_id, INE province code)]."""
    return _pairs(con, False, INE, since)


def participation(pairs, trials):
    """[Place] descending -- distinct trials with at least one site in each.

    A trial is counted once per place however many sites it has there, and in
    every place it reaches. `share` is of all trials in the window, so the
    181 with no located centre are in the denominator: a place's share is the
    fraction of Spanish trials it takes part in, and inflating it by dropping
    the trials nobody could place would flatter everywhere.
    """
    studies = collections.defaultdict(set)
    for study_id, code in pairs:
        studies[code].add(study_id)
    return sorted((Place(code, len(ids), 100.0 * len(ids) / trials)
                   for code, ids in studies.items()),
                  key=lambda place: -place.trials)


def unlocated(pairs, trials):
    """How many trials a map cannot place. Reported, never hidden."""
    return trials - len({study_id for study_id, _ in pairs})


# ---------------------------------------------------------------------------
# Sites as points: the dot map
# ---------------------------------------------------------------------------
# A different question from the choropleths above, and a different unit. The
# maps answer "which regions take part"; this answers "where are the sites".
#
# **The dots are centres, not trials.** A trial has no location -- its sites
# do, 7.2 of them on average and up to 93 -- so a dot per trial would be a
# dot per (trial, site) pair, about 6,000 marks stacked on the ~500 places
# that actually exist in a year. The mark is the hospital; the trial count is
# what it carries.
#
# Coordinates come from the postcode, so **every centre sharing a postcode
# shares a point**. In a dense district several large hospitals land exactly
# on top of each other. That is stated on the chart rather than jittered
# apart: jitter would invent a precision the postcode does not have, and put
# hospitals on streets they are not on.

Site = collections.namedtuple(
    "Site", "center_id name localidad provincia trials lat lon")


def normalise_postcode(value):
    """A postcode fit to look up, or None. The rule is deliberately narrow.

    Three defects are documented in the schema and all three are repairable
    without guessing: trailing punctuation (`28006,`), digit separators
    (`28.223`), and a dropped leading zero, which is why `8214` is Barcelona
    and not nowhere.

    **Anything still holding a letter is refused rather than repaired**, and
    that refusal is the point of the function. Stripping letters instead
    turns `3584 AE` -- a Dutch postcode, Utrecht -- into `03584`, which is a
    real place in Alicante. A rule that recovers eleven more centres by also
    being able to move a hospital to another country is not worth eleven
    centres.
    """
    digits = value.strip().replace(".", "").replace(",", "")
    if not digits.isdigit():
        return None
    if len(digits) == 4:
        digits = "0" + digits
    return digits if len(digits) == 5 else None


def load_postcodes(path):
    """{postcode: (lat, lon)}. See data/geo/README.md for provenance."""
    with open(path, encoding="utf-8") as handle:
        rows = csv.reader(handle)
        next(rows)
        return {code: (float(lat), float(lon)) for code, lat, lon in rows}


def site_activity(con, since=COVERAGE_START, until=None):
    """[(center_id, name, localidad, provincia, postcode, trials)].

    Counted over trials authorised in the window, so a centre that ran
    nothing in it is absent rather than drawn as a zero -- an empty dot would
    claim the hospital exists on the map and did nothing, when what the data
    says is that it took part in no trial authorised in these years.
    """
    return list(con.execute(
        """SELECT c.center_id, c.nombre, c.localidad, c.provincia,
                  c.cod_postal, count(DISTINCT sc.study_id) AS trials
             FROM centers c
             JOIN study_centers sc ON sc.center_id = c.center_id
             JOIN studies s ON s.identificador = sc.study_id
            WHERE s.fecha_autorizacion_aemps >= ?
              AND s.fecha_autorizacion_aemps < ?
         GROUP BY c.center_id
         ORDER BY trials DESC""",
        (_first_of(since), _first_of((until or 9998) + 1))))


def place_sites(rows, postcodes):
    """([Site] biggest first, unplaced centres, unplaced trial-site links).

    Pure, so the join between a centre and its coordinates can be tested
    without a database or a file.

    Two counts come back rather than one because they answer different
    questions: how many hospitals are missing from the map, and how much
    activity is missing with them. A hundred unplaceable centres that ran one
    trial each is a different map from two that ran a hundred.
    """
    placed, lost_sites, lost_trials = [], 0, 0
    for center_id, name, localidad, provincia, postcode, trials in rows:
        point = postcodes.get(normalise_postcode(postcode or "") or "")
        if point is None:
            lost_sites += 1
            lost_trials += trials
            continue
        placed.append(Site(center_id, name, localidad, provincia, trials,
                           *point))
    return (sorted(placed, key=lambda site: -site.trials),
            lost_sites, lost_trials)


def studies_at(con, center_id, since=COVERAGE_START, until=None):
    """[(identificador, es_ctis, year)] for one centre, newest first.

    What a reader gets after clicking a dot. The identifier is the key to the
    registry that holds the record -- see analysis/registry.py, and note that
    REEC itself publishes no per-study URL to link to.
    """
    return list(con.execute(
        """SELECT s.identificador, s.es_ctis,
                  substr(s.fecha_autorizacion_aemps, 1, 4) AS year
             FROM studies s
             JOIN study_centers sc ON sc.study_id = s.identificador
            WHERE sc.center_id = ?
              AND s.fecha_autorizacion_aemps >= ?
              AND s.fecha_autorizacion_aemps < ?
         ORDER BY s.fecha_autorizacion_aemps DESC""",
        (center_id, _first_of(since), _first_of((until or 9998) + 1))))


def load_geometry(path):
    """Polygons keyed by code. See data/geo/README.md for provenance."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def names_in(geometry):
    """{code: display name}. The geometry is the authority on spelling."""
    return {feature["id"]: feature["properties"]["name"]
            for feature in geometry["features"]}


# A single hue, light to dark, from the documented sequential ramp: magnitude
# is one quantity and a second hue would imply a second thing being measured.
# The lightest step is allowed to sit near the surface because it means
# "almost none", which is what a sequential ramp's low end is for.
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95",
             "#0d366b"]

# The Canary Islands are 1,000 km off the coast, so a single map containing
# them spends half its canvas on empty Atlantic. Spanish official cartography
# answers this with an inset box, and so does this: the same polygons and the
# same colour scale on a second geo axis at its own scale, with the
# displacement admitted in a caption rather than hidden by quietly moving the
# islands next to Andalucía. One region at NUTS 2; two provinces at INE.
CANARY_CODES = {"ES70", "35", "38"}

# The peninsula, the Balearics, Ceuta and Melilla. The latitude floor is 34.9
# rather than the mainland's 36 because Ceuta and Melilla are on the African
# coast, and a map of Spanish trial sites that cropped two autonomous cities
# would be wrong in the way this whole module is about.
MAINLAND = dict(lonaxis_range=[-9.8, 4.6], lataxis_range=[34.9, 44.0])
CANARIES = dict(lonaxis_range=[-18.3, -13.2], lataxis_range=[27.5, 29.5])


def figure(places, geometry, title, subtitle_text):
    """Participation as a choropleth, with the Canaries inset."""
    import plotly.graph_objects as go

    # Both traces share one scale, so a colour means the same thing in the
    # inset as on the mainland. Left to itself each trace would normalise to
    # its own values, and the islands would come out the darkest place in
    # Spain.
    ceiling = max(place.share for place in places)
    names = names_in(geometry)

    def choropleth(rows, geo, showscale):
        return go.Choropleth(
            geojson=geometry, featureidkey="id", geo=geo,
            locations=[place.code for place in rows],
            z=[place.share for place in rows],
            text=[names[place.code] for place in rows],
            customdata=[place.trials for place in rows],
            colorscale=BLUE_RAMP, zmin=0, zmax=ceiling, showscale=showscale,
            marker=dict(line=dict(color=SURFACE, width=1)),
            colorbar=dict(
                title=dict(text="% of Spanish trials with a site here",
                           side="top", font=dict(size=11, color=MUTED)),
                orientation="h", x=0.5, y=-0.06, xanchor="center",
                yanchor="bottom", ticksuffix="%", thickness=10, len=0.45,
                outlinewidth=0, tickfont=dict(size=11, color=MUTED)),
            hovertemplate="%{text}<br>%{customdata:,} trials, %{z:.1f}% of all"
                          "<extra></extra>")

    fig = go.Figure([
        choropleth([p for p in places if p.code not in CANARY_CODES],
                   "geo", True),
        choropleth([p for p in places if p.code in CANARY_CODES],
                   "geo2", False)])

    fig.update_layout(
        title=dict(text=title,
                   subtitle=dict(text=subtitle_text,
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
                 text="Boundaries © EuroGeographics (Eurostat GISCO, NUTS)")])
    fig.update_geos(visible=False, projection_type="mercator", bgcolor=SURFACE)
    fig.update_layout(
        geo=dict(domain=dict(x=[0, 1], y=[0, 1]), **MAINLAND),
        geo2=dict(domain=dict(x=[0.0, 0.22], y=[0.0, 0.30]),
                  visible=False, bgcolor=SURFACE, **CANARIES))
    return fig


def sites_figure(sites, title, subtitle_text):
    """The dot map: one mark per centre, area proportional to trials.

    **Area, not radius.** Plotly's `sizemode="area"` is what makes a hospital
    with 400 trials read as four times one with 100; sizing the radius by the
    count instead would draw it sixteen times the ink and overstate every
    large site. The eye compares blobs by area whatever the code intended, so
    the encoding has to be the one the eye is already using.

    The Canaries are a second subplot at their own scale, as on the
    choropleths, and sites are split between the two by longitude rather than
    by province, since a point either falls in the inset's window or it does
    not.
    """
    import plotly.graph_objects as go

    biggest = max((site.trials for site in sites), default=1)

    def dots(rows, geo):
        return go.Scattergeo(
            geo=geo, lon=[site.lon for site in rows],
            lat=[site.lat for site in rows],
            text=[site.name for site in rows],
            customdata=[(site.localidad, site.trials) for site in rows],
            mode="markers",
            marker=dict(
                size=[site.trials for site in rows],
                sizemode="area",
                # The largest mark is 34px across; every other follows from
                # it. sizeref is Plotly's units-per-pixel-squared, so it is
                # derived from the biggest value rather than tuned by hand,
                # and a filtered year cannot silently rescale the map.
                sizeref=2.0 * biggest / (34.0 ** 2),
                sizemin=3,
                color=SERIES, opacity=0.65,
                line=dict(width=0.5, color=SURFACE)),
            hovertemplate="<b>%{text}</b><br>%{customdata[0]}"
                          "<br>%{customdata[1]:,} trials<extra></extra>")

    mainland = [site for site in sites if site.lon > -12]
    canaries = [site for site in sites if site.lon <= -12]

    fig = go.Figure([dots(mainland, "geo"), dots(canaries, "geo2")])
    fig.update_layout(
        # y and yanchor are set rather than left to "auto", which puts the
        # title *below* its own two-line subtitle here and overlaps them by
        # eight pixels. Anchoring the block's top to the top of the paper
        # makes the order the reading order whatever the subtitle wraps to.
        title=dict(text=title, x=0, xref="paper", xanchor="left",
                   y=0.98, yref="container", yanchor="top",
                   subtitle=dict(text=subtitle_text,
                                 font=dict(size=12, color=MUTED)),
                   font=dict(size=17, color=INK)),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, showlegend=False,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        margin=dict(t=110, r=10, b=60, l=10), width=760, height=600,
        annotations=[
            dict(x=0.01, y=0.31, xref="paper", yref="paper", xanchor="left",
                 showarrow=False, font=dict(size=10, color=MUTED),
                 text="Canarias, at its own scale"),
            dict(x=0, y=-0.09, xref="paper", yref="paper", xanchor="left",
                 showarrow=False, font=dict(size=10, color=MUTED),
                 text="Boundaries © EuroGeographics (Eurostat GISCO, NUTS). "
                      "Sites placed by postcode (GeoNames, CC BY 4.0)")])
    fig.update_geos(visible=True, projection_type="mercator", bgcolor=SURFACE,
                    showcountries=True, showland=True,
                    landcolor=SURFACE, countrycolor=GRID, coastlinecolor=GRID,
                    showsubunits=False)
    fig.update_layout(
        geo=dict(domain=dict(x=[0, 1], y=[0, 1]), **MAINLAND),
        geo2=dict(domain=dict(x=[0.0, 0.22], y=[0.0, 0.30]), **CANARIES))
    return fig


def sites_subtitle(sites, lost_sites, lost_trials, since, until):
    """What the dots cannot say for themselves.

    Two short lines rather than one long one: the figure is 760px wide and a
    subtitle that runs past it is clipped rather than wrapped.
    """
    return ("Hospitals sharing a postcode share a point.<br>"
            "{:,} sites have no usable postcode and are not here, nor are "
            "the {:,} trials they ran.".format(lost_sites, lost_trials))


def subtitle(places, geometry, unplaced, grain):
    """The two things a reader has to know before reading the colours."""
    leader = places[0]
    return ("A trial counts in every {} it has a site in, so they overlap: "
            "{} alone takes part in {:.0f}% of them.<br>{:,} trials are not "
            "on the map — they report no centre, or none whose {} was "
            "recorded.".format(grain, names_in(geometry)[leader.code],
                               leader.share, unplaced, grain))
