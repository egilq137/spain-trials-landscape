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
