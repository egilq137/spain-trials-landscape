"""Rendering the analysis/ figures, which were authored for files.

Every figure in analysis/ sets an explicit layout width -- 760px, 860 for the
heatmap -- because a standalone .html file has no container to size itself
against. In a browser column that width is not a request, it is a ceiling:
Plotly turns off autosize as soon as a width is set, so a 760px figure in a
700px column is cropped rather than scaled, and the first thing to go is the
right-hand end of the title.

Clearing it here rather than in analysis/ keeps the decision where it belongs.
"How wide is this on this screen" is a presentation question with a different
answer per entrypoint; run_analysis.py's answer is still 760.

The height is left alone. It is an aspect-ratio choice about the drawing --
how much room a map of Spain or a 16-row heatmap needs -- and it does not
change because the column changed.
"""

import streamlit as st

from app import theme


def render(figure, **kwargs):
    """Draw a figure at the width of whatever contains it.

    For charts whose framing survives being reshaped -- bars, lines, the
    heatmap. Their axes re-lay out at any width, so wider is simply better.

    `width="stretch"` is st.plotly_chart's default in Streamlit 1.63; the
    `use_container_width=True` the Phase 5 handoff asks for is the same thing
    under its old name, and passing it now emits a deprecation warning.

    Mutating the figure is safe because the callers hold one from
    `st.cache_data`, which returns a fresh copy per call -- unlike
    `st.cache_resource`, which would hand out the same object every time and
    make this a mutation of the cache.
    """
    figure.update_layout(width=None)
    return st.plotly_chart(theme.apply(figure), **kwargs)


def render_fixed(figure, **kwargs):
    """Draw a figure at the size it was composed at.

    For the maps, and the reason is that a choropleth is not a chart that
    happens to be square. Its framing is a composition at one aspect ratio:
    the projection is pinned to explicit lon/lat ranges, and the Canaries
    inset and both annotations are placed in paper coordinates, so every one
    of them moves when the width:height ratio changes. Stretching the width
    alone re-frames the projection and clips the mainland.

    The fix a cartesian chart gets -- scale the height with the width -- is
    not available here: Streamlit composes the figure on the server and does
    not know the client's column width, so there is no ratio to preserve it
    against. So the map keeps its authored size and `width="content"` tells
    Streamlit to respect it rather than fit it to the column.

    The cost is a floor: a column narrower than the figure's 760px clips it
    rather than shrinking it, which starts happening below roughly a
    1100px-wide window with the sidebar open. Collapsing the sidebar buys it
    back. The alternative -- scaling both dimensions down to some smaller
    fixed size -- would fit more windows and would make the map smaller on
    every window, including the ones where it already fits.
    """
    return st.plotly_chart(theme.apply(figure), width="content", **kwargs)
