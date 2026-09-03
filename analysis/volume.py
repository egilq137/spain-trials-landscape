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

import plotly.graph_objects as go

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


# --- the chart -------------------------------------------------------------
#
# Colour by role, not by hex used inline. One series means one colour: a
# darker-where-bigger ramp would encode bar height twice and spend the only
# free channel on something the bars already say.
SERIES = "#2a78d6"
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e8e7e3"
SURFACE = "#fcfcfb"

# The mandate sits between two bars, not on one: CTIS became compulsory on
# 2023-01-31, so the boundary the eye should read is the gap after 2022.
CTIS_MANDATE_BOUNDARY = 2022.5


def figure(series, cover):
    """A bar per year, with the two things the series cannot say for itself.

    Takes the rows and the coverage note rather than a connection, so the
    chart can be built from any series -- a test's five bars included -- and
    nothing in here can quietly run a different query than the caller thinks.

    The final bar is hatched, not recoloured. A second colour would read as a
    second category; the hatch reads as "this bar is not like the others",
    which is what a year with eight months in it is. Both departures from the
    plain series -- that bar and the excluded studies -- are stated in the
    subtitle as well, because a texture is a hint and a sentence is not.
    """
    years = [year for year, _ in series]
    studies = [count for _, count in series]
    partial = int(cover.data_cut[:4])
    # Hatch only the partial year. A list of per-bar patterns keeps this a
    # property of the bar rather than a second trace, so the hover, the gap
    # and the corner radius stay identical across all of them.
    patterns = ["/" if year == partial else "" for year in years]

    fig = go.Figure(go.Bar(
        x=years, y=studies,
        marker=dict(color=SERIES, cornerradius=4,
                    pattern=dict(shape=patterns, solidity=0.55,
                                 fgcolor=SURFACE, size=6)),
        hovertemplate="%{x}<br>%{y:,} trials authorised<extra></extra>"))

    # Both labels live inside the plot area. Plotly's own vline annotation
    # sits above it, where it collided with the subtitle -- the kind of thing
    # only rendering the chart and looking at it shows.
    fig.add_vline(x=CTIS_MANDATE_BOUNDARY, line_width=1, line_color=MUTED)
    top = max(studies)
    fig.add_annotation(x=CTIS_MANDATE_BOUNDARY, y=top, yshift=26, xshift=6,
                       text="CTIS mandatory", showarrow=False, xanchor="left",
                       font=dict(size=11, color=MUTED))
    fig.add_annotation(x=partial, y=studies[-1], yshift=12, text="partial",
                       showarrow=False, font=dict(size=11, color=MUTED))

    fig.update_layout(
        title=dict(
            text="Clinical trials authorised in Spain, {}-{}".format(
                years[0], years[-1]),
            subtitle=dict(text=subtitle(cover), font=dict(size=12, color=MUTED)),
            font=dict(size=17, color=INK)),
        # 14 bars in ~700px: a gap of half the band leaves each bar around
        # 24px, which is the cap, and the leftover is air rather than fill.
        bargap=0.52,
        showlegend=False,  # one series; the title already names it
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        margin=dict(t=90, r=30, b=50, l=60), width=760, height=440)
    fig.update_xaxes(dtick=1, tickangle=0, showgrid=False,
                     linecolor=GRID, ticks="outside", tickcolor=GRID)
    fig.update_yaxes(title_text="trials authorised", rangemode="tozero",
                     gridcolor=GRID, griddash="solid", zeroline=False,
                     separatethousands=True)
    return fig


def subtitle(cover):
    """What the reader has to know before reading the bars.

    Both facts are exclusions the chart would otherwise make silently: a
    final year that is not a full year, and studies that are not on it at all.
    """
    return ("Counted on the AEMPS authorisation date, not the date the record "
            "was registered.<br>{} is partial, to {}. Excludes {} trials "
            "authorised before {}, where REEC's coverage begins.".format(
                cover.data_cut[:4], cover.data_cut, cover.excluded,
                COVERAGE_START))
