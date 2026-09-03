"""Which conditions dominate Spanish trial activity.

The coded field does the work that would otherwise be text mining: REEC ships
`areasTerapeuticas.area[]` with an EUTCT id and a MeSH-shaped name, so an area
is a key, not a phrase to be matched. 55 areas cover all 11,834 studies from
2013 -- there is no unclassified remainder to apologise for.

Three things decide what the ranking means.

**A trial can list more than one area, and 363 do.** There is no primary-area
flag in the source and no basis for inventing one, so a trial is counted once
in each area it lists. The bars therefore sum to 12,276 over 11,834 trials,
and a share is "of trials", not "of bars" -- the shares add up to 103.7%. The
alternative, splitting a trial 0.5 into each of two areas, would make every
bar a number no record anywhere contains.

**The names carry a two-level hierarchy** -- `Diseases [C] - Cancer [C04]`.
The top level is useless as a grouping here: branch C holds 11,066 of the
12,276 memberships, so collapsing to it draws one bar. The leaf is the level
with the variation, and the branch prefix is dropped from the label because
repeating "Diseases" on twelve of fourteen bars is ink that separates nothing.

**Two codes are absence statements**, not areas: `Not specified [CCC]` (144)
and `Not possible to specify` (103). They are merged into one bar and marked,
for the same reason the loader maps 'NA' to NULL rather than storing it as a
name -- both say the registry does not know, and two spellings of that are
still one fact. Merged and shown, never dropped: 247 trials is 2% of the
corpus and the reader is entitled to see it.
"""

import collections

import plotly.graph_objects as go

from analysis.volume import COVERAGE_START, GRID, INK, MUTED, SERIES, SURFACE

# The two EUTCT codes that state an absence rather than name an area.
# Enumerated, like db.cleaning_rules.PLACEHOLDERS: they are exactly the two
# names in the vocabulary that do not have the 'Branch [X] - Leaf [Yn]' shape,
# which is what makes the pair checkable rather than a guess.
UNSPECIFIED = ("999999000486", "999999999999")
UNSPECIFIED_LABEL = "Not specified"

Area = collections.namedtuple("Area", "label trials substantive")


def trials_per_area(con, since=COVERAGE_START):
    """[(eutct_code, name_en, trials)] descending, over studies from `since`.

    count(*) is a count of studies: (study_id, eutct_code) is the bridge's
    primary key, so a study cannot appear twice in one area.

    The English names are the ones parsed and displayed. Both languages are
    stored and the Spanish is what a Spanish audience would want, but its C23
    entry reads 'Enfermadades[C] -' -- a source typo, in the field this module
    would have to split on. Repairing a display string to parse it is the kind
    of quiet fix that hides a data problem; the English column is clean.
    """
    return con.execute(
        """SELECT ta.eutct_code, ta.nombre_en, count(*) AS trials
             FROM study_therapeutic_areas sta
             JOIN studies st ON st.identificador = sta.study_id
             JOIN therapeutic_areas ta ON ta.eutct_code = sta.eutct_code
            WHERE st.fecha_autorizacion_aemps >= ?
         GROUP BY ta.eutct_code, ta.nombre_en
         ORDER BY trials DESC, ta.eutct_code""",
        ("{}-01-01".format(since),)).fetchall()


def leaf(name):
    """'Diseases [C] - Cancer [C04]' -> 'Cancer [C04]'.

    The leaf code is kept: it is how the area is looked up in EUTCT, and two
    leaves can read alike in prose ('Immune System Diseases' [C20] against
    'Immune System' [G12], a disease and a physiological process).

    A name with no branch prefix is returned whole rather than treated as an
    error -- the two that have none are the absence statements above.
    """
    branch, separator, rest = name.partition(" - ")
    return rest if separator else branch


def ranked_areas(rows, top=12):
    """The bars, in order: the top areas, then Not specified, then Other.

    The two folds sit at the bottom whatever their size, because neither is an
    area and a reader ranking areas should not have to notice that rank 13 is
    a different kind of thing. Both are marked `substantive=False` so the
    chart can draw them as what they are.
    """
    areas = [row for row in rows if row[0] not in UNSPECIFIED]
    unspecified = sum(trials for code, _, trials in rows
                      if code in UNSPECIFIED)

    bars = [Area(leaf(name), trials, True) for _, name, trials in areas[:top]]
    if unspecified:
        bars.append(Area(UNSPECIFIED_LABEL, unspecified, False))
    tail = areas[top:]
    if tail:
        bars.append(Area("Other ({} areas)".format(len(tail)),
                         sum(trials for _, _, trials in tail), False))
    return bars


def figure(bars, trials):
    """Ranked horizontal bars, longest at the top.

    Horizontal because fourteen area names are unreadable rotated under a
    column. The value rides each bar's tip and the x axis is gone with it:
    one or the other carries the numbers, and both is duplicated ink.
    """
    labels = [bar.label for bar in bars][::-1]
    counts = [bar.trials for bar in bars][::-1]
    # Same convention as the partial year in analysis.volume: a hatch says
    # "not like the others", where a second colour would say "another
    # category".
    patterns = ["" if bar.substantive else "/" for bar in bars][::-1]

    fig = go.Figure(go.Bar(
        x=counts, y=labels, orientation="h",
        marker=dict(color=SERIES, cornerradius=4,
                    pattern=dict(shape=patterns, solidity=0.55,
                                 fgcolor=SURFACE, size=6)),
        text=["{:,}".format(count) for count in counts],
        textposition="outside", textfont=dict(size=11, color=MUTED),
        hovertemplate="%{y}<br>%{x:,} trials (%{customdata:.1f}% of trials)"
                      "<extra></extra>",
        customdata=[100 * count / trials for count in counts]))

    fig.update_layout(
        title=dict(
            text="Therapeutic areas in Spanish clinical trials, since {}"
                 .format(COVERAGE_START),
            subtitle=dict(text=subtitle(bars, trials),
                          font=dict(size=12, color=MUTED)),
            font=dict(size=17, color=INK)),
        bargap=0.42, showlegend=False,
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        margin=dict(t=90, r=70, b=40, l=290), width=760,
        height=110 + 30 * len(bars))
    # The values are on the bars, so the axis they would be read off is noise.
    # The range is widened by hand because the tip label of the longest bar
    # is drawn outside the bar and Plotly does not reserve room for it: at
    # the default range Cancer's 4,239 was clipped to '4,2'.
    fig.update_xaxes(visible=False, range=[0, max(counts) * 1.12])
    fig.update_yaxes(showgrid=False, linecolor=GRID, ticks="")
    return fig


def subtitle(bars, trials):
    """The two things that make the bars not add up, said out loud."""
    memberships = sum(bar.trials for bar in bars)
    return ("A trial is counted in every area it lists, so the bars total "
            "{:,} over {:,} trials.<br>The two hatched bars are not "
            "therapeutic areas.".format(memberships, trials))


# --- how the mix shifts ----------------------------------------------------
#
# Categorical slots 1-4 of the reference palette, in that fixed order, mapped
# to the series in rank order. Validated as a set rather than eyeballed:
#   worst adjacent CVD dE 9.1 (protan), normal-vision dE 22.9, both above the
#   floors; aqua and yellow fall below 3:1 against the surface, which obliges
#   the visible end-labels this chart draws anyway.
PALETTE = (SERIES, "#eb6834", "#1baf7a", "#eda100")

Trend = collections.namedtuple("Trend", "label years shares")


def top_areas(rows, count=4):
    """[(code, name)] -- the biggest real areas, absence statements excluded.

    Four, because four is where the accessibility rules and the data agree: a
    fifth line would forfeit direct labelling, and cardiovascular (628) sits
    within 1% of the fourth (633) while telling the same flat story.
    """
    return [(code, name) for code, name, _ in rows
            if code not in UNSPECIFIED][:count]


def area_counts_by_year(con, codes=None, since=COVERAGE_START):
    """[(year, eutct_code, trials)], year as an int. `codes=None` is all areas.

    The cast is not cosmetic. substr() returns TEXT, analysis.volume returns
    int years, and area_trends looks the two up in one dict: the first draft
    of this chart plotted four flat lines at 0% because '2013' never matched
    2013 and every share fell through to the zero default.
    """
    restriction = ""
    parameters = ["{}-01-01".format(since)]
    if codes is not None:
        restriction = " AND sta.eutct_code IN ({})".format(
            ", ".join("?" * len(codes)))
        parameters += list(codes)
    return [(int(year), code, trials) for year, code, trials in con.execute(
        """SELECT substr(st.fecha_autorizacion_aemps, 1, 4) AS year,
                  sta.eutct_code, count(*)
             FROM study_therapeutic_areas sta
             JOIN studies st ON st.identificador = sta.study_id
            WHERE st.fecha_autorizacion_aemps >= ?{}
         GROUP BY year, sta.eutct_code""".format(restriction), parameters)]


def area_trends(rows, totals, areas):
    """A share-of-year series per area, in the order `areas` gives.

    `totals` is analysis.volume.trials_per_year's output, so the denominator
    is the same one the volume chart draws and cannot drift from it. The
    numerator counts trials, the denominator counts trials, and a trial in two
    areas is in both numerators -- which is why these lines do not sum to
    100% and must not be stacked.

    A year in which an area saw no trials is 0%, not a hole: the year happened
    and the area was available to choose.
    """
    years = [year for year, _ in totals]
    total = dict(totals)
    counts = {(year, code): trials for year, code, trials in rows}
    return [Trend(leaf(name), years,
                  [100.0 * counts.get((year, code), 0) / total[year]
                   for year in years])
            for code, name in areas]


def trend_figure(trends, data_cut):
    """Share of each year's trials, one line per area."""
    fig = go.Figure()
    for index, trend in enumerate(trends):
        colour = PALETTE[index]
        last = len(trend.years) - 1
        fig.add_trace(go.Scatter(
            x=trend.years, y=trend.shares, name=trend.label, mode="lines+markers",
            line=dict(color=colour, width=2),
            # One dot, on the last point, ringed in the surface colour so it
            # stays legible where two lines nearly meet.
            marker=dict(color=colour, size=[0] * last + [8],
                        line=dict(color=SURFACE, width=2)),
            hovertemplate="%{y:.1f}%<extra>" + trend.label + "</extra>"))
        # The value at the end of the line, in ink rather than in the series
        # colour: the coloured dot beside it carries the identity.
        fig.add_annotation(x=trend.years[-1], y=trend.shares[-1], xshift=12,
                           text="{:.0f}%".format(trend.shares[-1]),
                           showarrow=False, xanchor="left",
                           font=dict(size=11, color=MUTED))

    fig.update_layout(
        title=dict(
            text="How the mix shifts: share of each year's trials",
            subtitle=dict(text=trend_subtitle(data_cut),
                          font=dict(size=12, color=MUTED)),
            font=dict(size=17, color=INK)),
        hovermode="x unified",
        # Below the plot. Above it, the legend ran through the second line
        # of the subtitle -- and a two-line subtitle is not something to
        # shorten to make room for a legend.
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0,
                    font=dict(size=11, color=MUTED)),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        margin=dict(t=95, r=70, b=90, l=60), width=760, height=470)
    fig.update_xaxes(dtick=1, showgrid=False, linecolor=GRID,
                     ticks="outside", tickcolor=GRID)
    fig.update_yaxes(title_text="share of trials authorised", rangemode="tozero",
                     ticksuffix="%", gridcolor=GRID, zeroline=False)
    return fig


def trend_subtitle(data_cut):
    return ("A trial counts in every area it lists, so the lines do not sum "
            "to 100% and must not be stacked.<br>{} is partial, to {}."
            .format(data_cut[:4], data_cut))


# --- the same ranking, one year at a time ----------------------------------
#
# The static ranking answers "what does the corpus look like"; this answers
# "what did it look like in 2016", fourteen times, with a slider. It is the
# line chart's information laid out the other way round: the lines are better
# for reading a trend, this is better for seeing a year's shape whole.
#
# Values are shares, not counts. The corpus is not the same size every year --
# 714 trials in 2014 against 1,027 in 2020 -- so a race on counts would show
# every bar growing in 2020 and shrinking in 2023 for reasons that have
# nothing to do with the mix.
Share = collections.namedtuple("Share", "label share substantive")


def yearly_shares(counts, totals, areas):
    """[(year, [Share, ...])] -- the same bars, in the same order, per year.

    The row order is the overall ranking and does not re-sort per year. A
    true bar-chart race re-ranks every frame, which looks livelier and makes
    the one thing this chart is for -- watching a single area move against a
    fixed backdrop -- harder, because the reader has to re-find the bar
    before they can see it has moved.
    """
    top = [code for code, _ in areas]
    tail = ({code for _, code, _ in counts} - set(top) - set(UNSPECIFIED))
    by_year = collections.defaultdict(dict)
    for year, code, trials in counts:
        by_year[year][code] = trials

    frames = []
    for year, total in totals:
        seen = by_year.get(year, {})

        def share(code_group):
            return 100.0 * sum(seen.get(code, 0) for code in code_group) / total

        bars = [Share(leaf(name), share([code]), True) for code, name in areas]
        bars.append(Share(UNSPECIFIED_LABEL, share(UNSPECIFIED), False))
        bars.append(Share("Other ({} areas)".format(len(tail)),
                          share(tail), False))
        frames.append((year, bars))
    return frames


def _share_trace(bars, labels, patterns):
    """One frame's bars. Built the same way for the figure and every frame."""
    return go.Bar(
        x=[bar.share for bar in bars][::-1], y=labels, orientation="h",
        marker=dict(color=SERIES, cornerradius=4,
                    pattern=dict(shape=patterns, solidity=0.55,
                                 fgcolor=SURFACE, size=6)),
        text=["{:.1f}%".format(bar.share) for bar in bars][::-1],
        textposition="outside", textfont=dict(size=11, color=MUTED),
        hovertemplate="%{y}<br>%{x:.1f}% of the year's trials<extra></extra>")


def _year_note(year):
    """The year, large, in the empty space the long bars leave."""
    return dict(x=0.97, y=0.06, xref="paper", yref="paper", text=str(year),
                showarrow=False, xanchor="right",
                font=dict(size=38, color=GRID))


def race_figure(frames, data_cut):
    """The ranking with a year slider and a play button.

    The x axis is fixed across every frame. Letting it autoscale would rescale
    the chart to each year's biggest bar, so cancer would look the same width
    in every frame and the animation would show nothing moving at all.
    """
    labels = [bar.label for bar in frames[0][1]][::-1]
    patterns = ["" if bar.substantive else "/" for bar in frames[0][1]][::-1]
    ceiling = max(bar.share for _, bars in frames for bar in bars) * 1.12

    fig = go.Figure(
        data=[_share_trace(frames[0][1], labels, patterns)],
        frames=[go.Frame(name=str(year),
                         data=[_share_trace(bars, labels, patterns)],
                         layout=go.Layout(annotations=[_year_note(year)]))
                for year, bars in frames])

    fig.update_layout(
        title=dict(
            text="Therapeutic areas, year by year",
            subtitle=dict(
                text="Share of the trials authorised that year. A trial "
                     "counts in every area it lists.<br>Bars keep their "
                     "overall ranking order; {} is partial, to {}.".format(
                         data_cut[:4], data_cut),
                font=dict(size=12, color=MUTED)),
            font=dict(size=17, color=INK)),
        annotations=[_year_note(frames[0][0])],
        bargap=0.42, showlegend=False,
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        margin=dict(t=100, r=70, b=90, l=290), width=760,
        height=150 + 30 * len(labels),
        updatemenus=[play_button()], sliders=[year_slider(frames)])
    fig.update_xaxes(visible=False, range=[0, ceiling])
    fig.update_yaxes(showgrid=False, linecolor=GRID, ticks="")
    return fig


# 900ms a frame: fourteen years take twelve seconds, and a bar that moves two
# points needs long enough on screen to be seen moving rather than blinking.
FRAME_MS = 900


def play_button():
    return dict(
        type="buttons", direction="left", x=0, y=-0.18, xanchor="left",
        showactive=False, pad=dict(t=0, r=8),
        buttons=[
            dict(label="Play", method="animate",
                 args=[None, dict(frame=dict(duration=FRAME_MS, redraw=True),
                                  fromcurrent=True,
                                  transition=dict(duration=300))]),
            dict(label="Pause", method="animate",
                 # A None frame list is Plotly's stop signal; the immediate
                 # mode is what makes it stop on this frame rather than
                 # finishing the queue.
                 args=[[None], dict(frame=dict(duration=0, redraw=False),
                                    mode="immediate")])])


def year_slider(frames):
    return dict(
        active=0, x=0.12, len=0.88, y=-0.12, pad=dict(t=0, b=10),
        # The year is already on the chart, in 38px. Plotly's own readout
        # would be the third place it appears, after that and the ticks.
        currentvalue=dict(visible=False),
        font=dict(size=11, color=MUTED),
        steps=[dict(label=str(year), method="animate",
                    args=[[str(year)],
                          dict(mode="immediate", frame=dict(duration=0,
                                                            redraw=True),
                               transition=dict(duration=0))])
               for year, _ in frames])
