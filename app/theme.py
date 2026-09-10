"""Restyling the analysis/ figures to the dashboard's palette.

The figures arrive coloured for the static files in docs/charts/, which stay
on the original blue by decision -- so the theme is applied here, on the way
to the screen, and analysis/ is not touched. The same figure legitimately
looks different in the two places because they are two publications of it.

Only colour is changed. Nothing here moves a mark, relabels an axis or
touches a number: a restyle that could change what a chart claims would be a
counting rule hiding in the presentation layer.

**Changing the palette is editing `.streamlit/config.toml` and nothing else.**
That is the whole design of this module. Streamlit needs the colours in TOML
and the figures need them in Python, so they are read rather than copied; and
everything the config has no slot for -- the sequential ramp, the secondary
text colour -- is derived from what it does, rather than being a second list
of hexes that a palette change would leave stale. The failure this avoids is
the one the project keeps legislating against: two places stating the same
thing, disagreeing, with nothing to catch it.
"""

import colorsys
import tomllib
from pathlib import Path

from analysis.geography import BASE_LAYER

CONFIG = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"


def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(
        *(round(min(max(channel, 0), 1) * 255) for channel in rgb))


def mix(colour, towards, amount):
    """`colour` moved `amount` of the way to `towards`, in sRGB.

    Straight-line blending is the wrong tool for building a scale -- see
    `sequential` -- but it is the right one for a single step between two
    colours that are already close in lightness, which is what the secondary
    text colour is.
    """
    start, end = _hex_to_rgb(colour), _hex_to_rgb(towards)
    return _rgb_to_hex(tuple(a + (b - a) * amount for a, b in zip(start, end)))


# The two ends of the sequential ramp, as lightness. The light end stops well
# short of white so the lowest bin still reads as a value rather than as a
# hole in the map; the dark end stops short of black so the top bin still
# shows its hue.
LIGHTEST, DARKEST = 0.90, 0.17


def sequential(accent, steps=7):
    """A single-hue ramp from `accent`, light to dark.

    Built in HLS rather than by interpolating from the surface colour to the
    accent in RGB, and the difference is the point. A straight line in RGB
    between a warm near-white and a mid teal passes through steps that are
    *lighter* than the one before them, and a sequential scale whose middle is
    not monotonic in lightness has stopped encoding magnitude -- the reader
    can no longer tell "more" from "less" by eye. Walking lightness down makes
    that monotonicity a property of the construction rather than something to
    check by eye each time the accent changes.

    Saturation rises as lightness falls, which is what the published
    sequential scales do: a pale step needs little chroma to read as pale,
    while the dark end needs its hue to survive being dark.
    """
    hue, _, saturation = colorsys.rgb_to_hls(*_hex_to_rgb(accent))
    ramp = []
    for step in range(steps):
        position = step / (steps - 1)
        ramp.append(_rgb_to_hex(colorsys.hls_to_rgb(
            hue,
            LIGHTEST + (DARKEST - LIGHTEST) * position,
            saturation * (0.45 + 0.55 * position))))
    return ramp


def _configured():
    with CONFIG.open("rb") as handle:
        return tomllib.load(handle)["theme"]


_THEME = _configured()

ACCENT = _THEME["primaryColor"]
SURFACE = _THEME["backgroundColor"]
GRID = _THEME["secondaryBackgroundColor"]
INK = _THEME["textColor"]

# Streamlit has no "secondary text" slot, and this is the colour of every
# subtitle, tick label and annotation in the figures. Derived from the two
# colours the config does carry, so a new palette cannot leave it behind.
#
# A third of the way and no further, because this is text. Secondary text
# wants to recede, and the obvious way to make it recede -- keep blending it
# into the background -- is the way to make it unreadable: at halfway it
# lands near #959491, about 2.7:1 against this surface, where 4.5:1 is the
# floor for body-sized text. At a third it holds about 4.9:1 and still reads
# as quieter than the ink.
MUTED = mix(INK, SURFACE, 0.35)

ACCENT_RAMP = sequential(ACCENT)


def apply(figure):
    """Recolour one figure in place, and hand it back.

    In place because the caller holds a copy from `st.cache_data` rather than
    the cached object itself, so there is nothing shared to corrupt.
    """
    figure.update_layout(
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font_color=MUTED,
        title_font_color=INK,
        title_subtitle_font_color=MUTED)
    figure.update_annotations(font_color=MUTED)

    # Choropleths carry the sequential ramp, the polygon borders (drawn in the
    # surface colour so the gaps read as background rather than as ink) and a
    # colour bar with its own two fonts.
    # Two kinds of choropleth, told apart by name rather than by type: the
    # participation maps carry a sequential ramp, and the dot map's backdrop
    # is two flat colours. A selector on the type alone would give the
    # backdrop a magnitude scale it is not measuring anything with.
    figure.update_traces(
        selector=lambda trace: (trace.type == "choropleth"
                                and trace.name != BASE_LAYER),
        colorscale=ACCENT_RAMP,
        marker_line_color=SURFACE,
        colorbar_tickfont_color=MUTED,
        colorbar_title_font_color=MUTED)

    # The backdrop. Provinces that ran something take a tint of the accent
    # pale enough to sit under the marks without competing with them; the
    # rest stay the page's own surface, so an empty province reads as empty
    # rather than as a lighter shade of busy. The borders are the point of
    # the layer, so they are drawn in the secondary text colour rather than
    # the grid colour -- against a tinted fill, grid-on-tint disappears.
    figure.update_traces(
        selector=dict(name=BASE_LAYER),
        colorscale=[[0, SURFACE], [1, mix(SURFACE, ACCENT, 0.16)]],
        marker_line_color=mix(SURFACE, INK, 0.30))

    # Scattergeo carries the dot map. Only the two colours are touched: the
    # marker sizes encode trial counts and are the figure's business, not the
    # palette's.
    figure.update_traces(
        selector=dict(type="scattergeo"),
        marker_color=ACCENT,
        marker_line_color=SURFACE)

    # The land and coastlines under the dots, which the choropleths do not
    # draw because their polygons cover them.
    figure.update_geos(bgcolor=SURFACE, landcolor=SURFACE,
                       countrycolor=GRID, coastlinecolor=GRID)
    return figure
