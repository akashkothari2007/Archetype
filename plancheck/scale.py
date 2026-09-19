"""Drawing scale and dimension-string parsing.

Scale is printed in the title block, so it is read rather than derived.

PDF user space is 72 points to the inch by definition, so
    pts_per_ft = 72 * paper_inches / real_feet
For 1/4" = 1'-0"  ->  72 * 0.25   = 18.0
For 3/16" = 1'-0" ->  72 * 0.1875 = 13.5
For 1/16" = 1'-0" ->  72 * 0.0625 = 4.5
"""

from __future__ import annotations

import re
from fractions import Fraction

POINTS_PER_INCH = 72.0

#: Matches `1/4" = 1'-0"`, `3/16"=1'-0"` and title-block spacing variants.
SCALE_RE = re.compile(
    r"""(?P<paper>\d+(?:\s*/\s*\d+)?)\s*"\s*=\s*(?P<feet>\d+)\s*'\s*-\s*(?P<inches>\d+)\s*"?"""
)

#: Clean and reliable. Imperial text on these sheets is mangled; this is not.
METRIC_BRACKET_RE = re.compile(r"\[\s*([\d.]+)\s*m\s*\]")

#: Imperial fallback, e.g. 31'-3" or the mangled 31'-212.
IMPERIAL_RE = re.compile(r"(\d+)\s*'\s*-\s*(\d+)\s*\"?")

#: Imperial fractions extract MANGLED. Where both digits of the fraction
#: survive and only the solidus was dropped, they can be repaired exactly.
FRACTION_REPAIR: dict[str, float] = {
    "12": 0.5,
    "14": 0.25,
    "34": 0.75,
    "18": 0.125,
    "38": 0.375,
    "58": 0.625,
    "78": 0.875,
}

FEET_PER_METRE = 1 / 0.3048


class ScaleError(ValueError):
    """The scale text is not a recognisable architectural scale."""


def parse_scale_text(text: str) -> tuple[str, float] | None:
    """Find a scale in `text` and return (normalised_text, pts_per_ft).

    Returns None when no scale is present, which is a normal outcome on
    sheets marked "NOT TO SCALE".
    """
    match = SCALE_RE.search(text)
    if match is None:
        return None

    paper_inches = float(Fraction(match["paper"].replace(" ", "")))
    real_feet = int(match["feet"]) + int(match["inches"]) / 12.0
    if paper_inches <= 0 or real_feet <= 0:
        raise ScaleError(f"Degenerate scale: {match.group(0)!r}")

    normalised = f'{match["paper"].replace(" ", "")}" = {match["feet"]}\'-{match["inches"]}"'
    return normalised, POINTS_PER_INCH * paper_inches / real_feet


def parse_dimension(text: str) -> tuple[float, str] | None:
    """Parse a dimension token into (metres, source).

    Prefers the metric bracket, which extracts cleanly. Imperial is a fallback
    only, because it arrives mangled in two different ways:

      * Both fraction digits survive, solidus dropped:
        31'-2 1/2"  ->  "31'-212",  10'-4 1/4"  ->  "10'-414"
      * Only the numerator survives, denominator glyph lost:
        2'-4 3/4"   ->  "2'-43",    2'-5 1/2"   ->  "2'-51"

    The second form is genuinely ambiguous — "23" is 2 3/8" on one sheet and
    2 3/4" on another — so it is reported as `imperial_ambiguous` with the
    fraction dropped rather than guessed. Callers should prefer the bracket.

    >>> parse_dimension('31\\'-3" [9.53m]')
    (9.53, 'metric_bracket')
    >>> parse_dimension("10'-414")
    (3.16052, 'imperial_repaired')
    """
    metric = METRIC_BRACKET_RE.search(text)
    if metric is not None:
        try:
            return float(metric.group(1)), "metric_bracket"
        except ValueError:
            pass

    imperial = IMPERIAL_RE.search(text)
    if imperial is None:
        return None

    feet = int(imperial.group(1))
    token = imperial.group(2)
    source = "imperial"

    if len(token) > 2 and token[-2:] in FRACTION_REPAIR:
        inches = int(token[:-2]) + FRACTION_REPAIR[token[-2:]]
        source = "imperial_repaired"
    elif len(token) > 1 and int(token) >= 12:
        # Not a real inches value. The trailing digit is a surviving fraction
        # numerator whose denominator was lost; drop it rather than invent one.
        inches = float(token[:-1])
        source = "imperial_ambiguous"
    else:
        inches = float(token)

    metres = (feet + inches / 12.0) * 0.3048
    return round(metres, 5), source


def points_to_feet(points: float, pts_per_ft: float) -> float:
    if pts_per_ft <= 0:
        raise ScaleError("pts_per_ft must be positive")
    return points / pts_per_ft
