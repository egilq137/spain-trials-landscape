"""Phase I-IV: the mix, and who is actually driving the change in it.

**Phase is four flags, not one field.** REEC ships `faseUno`..`faseCuatro` as
independent booleans because a trial can run two phases at once -- a
first-in-human dose escalation that rolls straight into expansion is a phase
I/II trial, and 958 of them say so. Collapsing that to a single "phase" would
have to pick one and lose the other.

**So the combinations are the categories.** All 11,834 trials from 2013 set at
least one flag -- there is no unknown-phase bucket to apologise for -- and 12
distinct combinations appear. Seven of them are recognised trial designs and
get their own row; the remaining five, 22 trials between them, are folded into
one marked row. The result is **mutually exclusive and exhaustive**, so unlike
the therapeutic and geographic charts these shares really do sum to 100%. That
is worth stating on the chart, because the last three said the opposite.

**The rows are ordered by the phase ladder, not by size.** Phase is ordinal:
I comes before II because that is what the words mean, and sorting the bars by
count would throw away an ordering the reader already has.

**Phase I involvement means the flag is set**, so a I/II trial counts as phase
I. The alternative -- counting only trials that are phase I and nothing else
-- would drop 977 of the 2,698 early-phase trials, most of them the modern
seamless designs the trend is about.
"""

import collections

import plotly.graph_objects as go

from analysis.geography import BLUE_RAMP
from analysis.therapeutic import leaf
from analysis.volume import COVERAGE_START, GRID, INK, MUTED, SERIES, SURFACE

PHASE_COLUMNS = ("fase_uno", "fase_dos", "fase_tres", "fase_cuatro")
NUMERALS = ("I", "II", "III", "IV")

# The seven combinations that are recognised trial designs, in ladder order.
# Enumerated rather than derived: 'I/III' is mechanically a combination too,
# and it is 16 trials of something the phase ladder does not have a name for.
# What the list decides is which combinations are worth a row, and the rest
# are counted and shown rather than dropped.
DESIGNS = ("I", "I/II", "II", "II/III", "III", "III/IV", "IV")
OTHER = "Other combinations"

# The EUTCT code for cancer, from therapeutic_areas. A constant because the
# oncology split below is the whole point of the second chart, and a test
# checks the code still names the area it is claimed to name.
CANCER = "999999000425"

Bar = collections.namedtuple("Bar", "label trials design")
Year = collections.namedtuple("Year", "year overall cancer other")


def label_of(flags):
    """(1, 1, 0, 0) -> 'I/II'. Built from the flags, so it cannot disagree."""
    return "/".join(numeral for numeral, flag in zip(NUMERALS, flags) if flag)


def phase_mix(con, since=COVERAGE_START):
    """[Bar] in phase order, one row per design plus the folded remainder.

    Counts trials, not flags: every trial appears exactly once, which is what
    lets these bars be read as a share of the corpus.
    """
    counts = collections.Counter()
    for row in con.execute(
            """SELECT {}, count(*)
                 FROM studies
                WHERE fecha_autorizacion_aemps >= ?
             GROUP BY {}""".format(", ".join(PHASE_COLUMNS),
                                   ", ".join(PHASE_COLUMNS)),
            ("{}-01-01".format(since),)):
        counts[label_of(row[:4])] += row[4]

    bars = [Bar(design, counts.pop(design, 0), True) for design in DESIGNS]
    if counts:
        bars.append(Bar("{} ({})".format(OTHER, len(counts)),
                        sum(counts.values()), False))
    return bars


def early_phase_by_year(con, since=COVERAGE_START):
    """[Year] -- % of trials involving phase I, overall and split on oncology.

    The split is the point. A crude rate can move because its subgroups moved,
    because the mix of subgroups moved, or because one large subgroup moved
    and dragged the total; only stratifying tells them apart. Here the answer
    is the third, and the overall line is kept on the chart so the reader can
    see it sitting between two lines that explain it.

    A subgroup with no trials in a year gets None rather than 0%.
    """
    rows = con.execute(
        """SELECT substr(st.fecha_autorizacion_aemps, 1, 4) AS year,
                  sta.study_id IS NOT NULL AS oncology,
                  count(*), sum(st.fase_uno)
             FROM studies st
             LEFT JOIN study_therapeutic_areas sta
                    ON sta.study_id = st.identificador
                   AND sta.eutct_code = ?
            WHERE st.fecha_autorizacion_aemps >= ?
         GROUP BY year, oncology
         ORDER BY year""", (CANCER, "{}-01-01".format(since)))

    totals = collections.defaultdict(lambda: collections.defaultdict(int))
    for year, oncology, trials, early in rows:
        totals[int(year)][bool(oncology)] += trials
        totals[int(year)][("early", bool(oncology))] += early

    def share(counts, group):
        """None, not 0.0, when the subgroup is empty that year.

        A year with no cancer trials has no cancer phase I rate. Returning
        zero would draw the line down to the axis and say the rate collapsed,
        which is a claim about trials that do not exist. Plotly breaks a line
        at None, which is the honest picture: nothing measured here.
        """
        if not counts[group]:
            return None
        return 100.0 * counts[("early", group)] / counts[group]

    return [Year(year,
                 100.0 * (counts[("early", True)] + counts[("early", False)])
                 / (counts[True] + counts[False]),
                 share(counts, True), share(counts, False))
            for year, counts in sorted(totals.items())]


def mix_figure(bars, trials):
    """The phase ladder, top to bottom, with each design's share of trials."""
    labels = [bar.label for bar in bars][::-1]
    counts = [bar.trials for bar in bars][::-1]
    # Only the folded row is hatched: the combined-phase designs are real
    # designs, and marking them would say they are not.
    patterns = ["" if bar.design else "/" for bar in bars][::-1]

    fig = go.Figure(go.Bar(
        x=counts, y=labels, orientation="h",
        marker=dict(color=SERIES, cornerradius=4,
                    pattern=dict(shape=patterns, solidity=0.55,
                                 fgcolor=SURFACE, size=6)),
        text=["{:,}".format(count) for count in counts],
        textposition="outside", textfont=dict(size=11, color=MUTED),
        customdata=[100.0 * count / trials for count in counts],
        hovertemplate="Phase %{y}<br>%{x:,} trials (%{customdata:.1f}%)"
                      "<extra></extra>"))

    fig.update_layout(
        title=dict(
            text="Trial phases in Spain since {}".format(COVERAGE_START),
            subtitle=dict(
                text="Every trial is in exactly one row, so these shares do "
                     "sum to 100%: {:,} trials.<br>A trial running two phases "
                     "at once has its own row rather than being counted "
                     "twice.".format(trials),
                font=dict(size=12, color=MUTED)),
            font=dict(size=17, color=INK)),
        bargap=0.42, showlegend=False,
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        margin=dict(t=95, r=70, b=40, l=170), width=760,
        height=110 + 34 * len(bars))
    # Values ride the bars, so the axis they would be read off is noise. The
    # range is widened by hand because an outside tip label is drawn past the
    # end of the bar and Plotly reserves no room for it.
    fig.update_xaxes(visible=False, range=[0, max(counts) * 1.12])
    fig.update_yaxes(showgrid=False, linecolor=GRID, ticks="")
    return fig


# Cancer and everything else take categorical slots 1 and 2. The overall rate
# is drawn in ink rather than a third hue: it is not a third population, it is
# the other two averaged, and colouring it like a series would say otherwise.
CANCER_COLOUR = SERIES
OTHER_COLOUR = "#eb6834"


def early_phase_figure(years):
    """Phase I share per year, overall and split on oncology."""
    fig = go.Figure()
    for name, values, colour, width in (
            ("Cancer trials", [year.cancer for year in years],
             CANCER_COLOUR, 2),
            ("Everything else", [year.other for year in years],
             OTHER_COLOUR, 2),
            ("All trials", [year.overall for year in years], MUTED, 1)):
        last = len(years) - 1
        fig.add_trace(go.Scatter(
            x=[year.year for year in years], y=values, name=name,
            mode="lines+markers", line=dict(color=colour, width=width),
            marker=dict(color=colour, size=[0] * last + [8],
                        line=dict(color=SURFACE, width=2)),
            hovertemplate="%{y:.1f}%<extra>" + name + "</extra>"))
        # No end label for a line that ends in an empty subgroup: there is
        # no value to write, and a label at the axis would invent one.
        if values[-1] is not None:
            fig.add_annotation(x=years[-1].year, y=values[-1], xshift=12,
                               text="{:.0f}%".format(values[-1]),
                               showarrow=False, xanchor="left",
                               font=dict(size=11, color=MUTED))

    fig.update_layout(
        title=dict(
            text="The rise in early-phase research is an oncology story",
            subtitle=dict(
                text="Share of each year's trials involving phase I. A "
                     "phase I/II trial counts as phase I.<br>The overall rate "
                     "rises because cancer trials do; everything else is "
                     "flat.",
                font=dict(size=12, color=MUTED)),
            font=dict(size=17, color=INK)),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0,
                    font=dict(size=11, color=MUTED)),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        margin=dict(t=95, r=70, b=90, l=60), width=760, height=470)
    fig.update_xaxes(dtick=1, showgrid=False, linecolor=GRID,
                     ticks="outside", tickcolor=GRID)
    fig.update_yaxes(title_text="trials involving phase I", rangemode="tozero",
                     ticksuffix="%", gridcolor=GRID, zeroline=False)
    return fig


# --- phase against therapeutic area ----------------------------------------
#
# The two charts above answer "what phases" and "when". This one answers "who
# runs which", and it is where the oncology finding stops being a trend and
# becomes a structure: cancer is the only large area weighted toward phase I,
# and the only one with almost no phase IV.
#
# Columns count **involvement**, not the exclusive designs of the mix chart: a
# I/II trial appears under both I and II, so a row does not sum to 100%. The
# question here is "what share of this area's trials reach phase I", and a
# seamless I/II trial reaches both. Said on the chart, since the mix chart
# says the opposite about itself.
AreaPhases = collections.namedtuple("AreaPhases", "label trials shares counts")

ALL_TRIALS = "All trials"


def phase_by_area(con, areas, since=COVERAGE_START):
    """[AreaPhases] per area, biggest first, with an All trials row last.

    The baseline row is what makes the rest readable: 38.7% of cancer trials
    reaching phase I means nothing until you know the corpus figure is 22.8%.
    It is placed last and labelled, not mixed in among the areas -- it is not
    an area, it is the thing they are being compared against.

    `areas` is the same top-16 cut the therapeutic ranking uses, so the two
    charts show the same areas. One casualty of that consistency is worth
    naming: anaesthesia and analgesia [E03] is **61.8% phase IV**, the most
    post-marketing-heavy area in the corpus by a distance, and it sits just
    below the cut at 123 trials. The heatmap's phase IV column therefore
    understates how extreme that end gets.
    """
    sums = ", ".join("sum(st.{})".format(column) for column in PHASE_COLUMNS)
    rows = []
    for code, name in areas:
        trials, *counts = con.execute(
            """SELECT count(*), {}
                 FROM study_therapeutic_areas sta
                 JOIN studies st ON st.identificador = sta.study_id
                WHERE sta.eutct_code = ?
                  AND st.fecha_autorizacion_aemps >= ?""".format(sums),
            (code, "{}-01-01".format(since))).fetchone()
        rows.append(AreaPhases(leaf(name), trials,
                               [100.0 * count / trials for count in counts],
                               counts))

    trials, *counts = con.execute(
        "SELECT count(*), {} FROM studies st "
        "WHERE st.fecha_autorizacion_aemps >= ?".format(sums),
        ("{}-01-01".format(since),)).fetchone()
    rows.append(AreaPhases(ALL_TRIALS, trials,
                           [100.0 * count / trials for count in counts],
                           counts))
    return rows


def heatmap_figure(rows):
    """Areas down, phases across, colour and value = share of the area."""
    # A blank row before the corpus baseline, so it reads as a rule under the
    # table rather than as the seventeenth therapeutic area. An empty z row
    # draws nothing, which is the gap.
    display = []
    for row in rows:
        if row.label == ALL_TRIALS:
            display.append(AreaPhases(" ", 0, [None] * 4, [0] * 4))
        display.append(row)

    # Reversed, because a heatmap's y axis is drawn bottom-up and the biggest
    # area belongs at the top.
    ordered = display[::-1]
    labels = [row.label for row in ordered]
    shares = [row.shares for row in ordered]
    ceiling = max(max(row.shares) for row in rows)

    fig = go.Figure(go.Heatmap(
        z=shares, x=list(NUMERALS), y=labels,
        colorscale=BLUE_RAMP, zmin=0, zmax=ceiling,
        xgap=2, ygap=2,  # the surface doing the separating, as everywhere else
        customdata=[row.counts for row in ordered],
        colorbar=dict(title=dict(text="% of the area's trials", side="top",
                                 font=dict(size=11, color=MUTED)),
                      orientation="h", x=0.5, y=-0.13, xanchor="center",
                      yanchor="bottom", ticksuffix="%", thickness=10,
                      len=0.4, outlinewidth=0,
                      tickfont=dict(size=11, color=MUTED)),
        hovertemplate="%{y}<br>Phase %{x}: %{customdata:,} trials, "
                      "%{z:.1f}% of the area<extra></extra>"))

    # A value in every cell, which a heatmap is allowed: it is a table that
    # has been coloured, not a plot with numbers scattered over it. Ink or
    # surface by the cell's own darkness, so the text clears its background
    # either way.
    for y, row in enumerate(ordered):
        for x, share in enumerate(row.shares):
            if share is None:
                continue
            fig.add_annotation(
                x=x, y=y, text="{:.0f}".format(share), showarrow=False,
                font=dict(size=11,
                          color=SURFACE if share > 0.55 * ceiling else INK))

    fig.update_layout(
        title=dict(
            text="Cancer runs a different kind of research from everything "
                 "else",
            subtitle=dict(
                text="Share of each area's trials reaching each phase. A "
                     "phase I/II trial reaches both,<br>so a row does not sum "
                     "to 100%. The bottom row is the whole corpus, for "
                     "comparison.",
                font=dict(size=12, color=MUTED)),
            font=dict(size=17, color=INK)),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        # The column headers sit on top of the plot, so the top margin has
        # to clear a two-line subtitle as well as the title.
        margin=dict(t=130, r=30, b=110, l=290), width=760,
        height=180 + 26 * len(rows))
    fig.update_xaxes(side="top", showgrid=False, ticks="",
                     tickfont=dict(size=12, color=MUTED))
    fig.update_yaxes(showgrid=False, ticks="",
                     tickfont=dict(size=11, color=MUTED))
    return fig
