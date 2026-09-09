"""Tests for app.theme's colour derivation.

app/ is otherwise untested by design -- Streamlit's execution model makes
those tests near-worthless, and the way that stays honest is by keeping app/
thin. This module is the exception because it imports no Streamlit: it is
arithmetic on hex strings, and the property it promises is one an eye cannot
reliably check.

Success criteria:
  monotone lightness: every step of the ramp is darker than the one before,
    for any accent. A sequential scale that gets lighter in the middle has
    stopped encoding magnitude, and that is exactly what interpolating in RGB
    does -- the reason this is built in HLS
  hue is the accent's: the ramp is one hue at many lightnesses, so a second
    hue would imply a second thing being measured
  any accent works: the palette is meant to be changed by editing one line of
    .streamlit/config.toml, so the ramp cannot be tuned to teal
  mix: the endpoints are the inputs, so a derived colour cannot drift off the
    two it is derived from
  config is the source: the module's constants are the file's values, not a
    second copy of them
"""

import colorsys
import unittest

from app import theme


def lightness(hex_colour):
    return colorsys.rgb_to_hls(*theme._hex_to_rgb(hex_colour))[1]


def hue(hex_colour):
    return colorsys.rgb_to_hls(*theme._hex_to_rgb(hex_colour))[0]


def contrast(one, other):
    """WCAG contrast ratio, 1:1 to 21:1."""
    def luminance(hex_colour):
        channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                    for c in theme._hex_to_rgb(hex_colour)]
        return (0.2126 * channels[0] + 0.7152 * channels[1]
                + 0.0722 * channels[2])
    lighter, darker = sorted([luminance(one), luminance(other)], reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def hue_gap(one, other):
    """Degrees between two hues, the short way round the circle.

    Circular because hue wraps: a wine accent sits at 349 degrees and its
    palest step can round to 2, which is three degrees away and not 347.
    """
    gap = abs(hue(one) - hue(other)) * 360
    return min(gap, 360 - gap)


# The accents offered in the palette picker, plus two far from them. If the
# construction only works for blue-greens it is not a palette system.
ACCENTS = ["#2f6f6b", "#2a78d6", "#7a3b46", "#43684a", "#2e4266", "#a9762f"]


class TestSequential(unittest.TestCase):
    def test_it_returns_the_number_of_steps_asked_for(self):
        self.assertEqual(len(theme.sequential("#2f6f6b")), 7)
        self.assertEqual(len(theme.sequential("#2f6f6b", steps=5)), 5)

    def test_every_step_is_darker_than_the_one_before(self):
        # The property the whole HLS construction exists to guarantee.
        for accent in ACCENTS:
            with self.subTest(accent=accent):
                ramp = theme.sequential(accent)
                lightnesses = [lightness(step) for step in ramp]
                self.assertEqual(lightnesses, sorted(lightnesses, reverse=True))

    def test_the_ramp_spans_the_configured_range(self):
        ramp = theme.sequential("#2f6f6b")
        self.assertAlmostEqual(lightness(ramp[0]), theme.LIGHTEST, places=2)
        self.assertAlmostEqual(lightness(ramp[-1]), theme.DARKEST, places=2)

    def test_it_keeps_the_accent_hue(self):
        # Within a few degrees rather than exactly: the ramp is built in HLS
        # and then written as hex, and rounding three channels to 8 bits moves
        # the hue that comes back out by a degree or two -- most at the pale
        # end, where there is least chroma to carry it.
        for accent in ACCENTS:
            with self.subTest(accent=accent):
                for step in theme.sequential(accent):
                    self.assertLess(hue_gap(step, accent), 4)

    def test_every_step_is_a_hex_colour(self):
        for step in theme.sequential("#2f6f6b"):
            self.assertRegex(step, r"^#[0-9a-f]{6}$")


class TestMix(unittest.TestCase):
    def test_the_endpoints_are_the_inputs(self):
        self.assertEqual(theme.mix("#000000", "#ffffff", 0), "#000000")
        self.assertEqual(theme.mix("#000000", "#ffffff", 1), "#ffffff")

    def test_halfway_is_halfway(self):
        self.assertEqual(theme.mix("#000000", "#ffffff", 0.5), "#808080")


class TestConfiguredPalette(unittest.TestCase):
    """The constants are the config file's values, not a second copy."""

    def test_it_reads_the_streamlit_theme(self):
        configured = theme._configured()
        self.assertEqual(theme.ACCENT, configured["primaryColor"])
        self.assertEqual(theme.SURFACE, configured["backgroundColor"])
        self.assertEqual(theme.GRID, configured["secondaryBackgroundColor"])
        self.assertEqual(theme.INK, configured["textColor"])

    def test_the_derived_colours_follow_the_accent(self):
        # If this fails, something has gone back to hardcoding a ramp and a
        # palette change would silently leave it behind.
        self.assertEqual(theme.ACCENT_RAMP, theme.sequential(theme.ACCENT))
        self.assertEqual(theme.MUTED,
                         theme.mix(theme.INK, theme.SURFACE, 0.35))

    def test_muted_sits_between_the_ink_and_the_surface(self):
        self.assertLess(lightness(theme.INK), lightness(theme.MUTED))
        self.assertLess(lightness(theme.MUTED), lightness(theme.SURFACE))

    def test_muted_stays_readable_on_the_surface(self):
        # It is text, and it is derived, so a future palette could quietly
        # push it into the background. WCAG AA for body-sized text is 4.5:1.
        self.assertGreaterEqual(contrast(theme.MUTED, theme.SURFACE), 4.5)

    def test_the_ink_is_readable_too(self):
        self.assertGreaterEqual(contrast(theme.INK, theme.SURFACE), 4.5)


if __name__ == "__main__":
    unittest.main()
