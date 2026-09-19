"""Drawing scale.

The scale is printed in the title block of every sheet ("3/16\" = 1'-0\""), so
it is read rather than derived. Deriving it from repeated dimension strings is
kept as a *validator* that catches a misread, not as the primary method — that
removes the largest failure mode in the extraction pipeline.

This module is real, not stubbed. It is pure arithmetic with no PDF dependency,
so it is correct before E1 exists and E1 can lean on it from day one.
"""

from __future__ import annotations

import re
from fractions import Fraction

#: PDF user space is 72 points to the inch, by definition.
POINTS_PER_INCH = 72.0

#: Matches `3/16" = 1'-0"`, `1/4"=1'-0"`, `1/16" = 1'-0"` and spacing variants.
SCALE_RE = re.compile(
    r"""(?P<paper>\d+(?:\s*/\s*\d+)?)\s*"?\s*=\s*
        (?P<feet>\d+)\s*'\s*-\s*(?P<inches>\d+)\s*"?""",
    re.VERBOSE,
)

#: Architectural scales that legitimately appear in a hotel arch set. Anything
#: outside this table is a misread, and the caller should fail loudly.
STANDARD_SCALES: dict[str, float] = {
    '1/16"=1\'-0"': POINTS_PER_INCH * (1 / 16),  # 4.5   whole floor plans
    '3/32"=1\'-0"': POINTS_PER_INCH * (3 / 32),  # 6.75
    '1/8"=1\'-0"': POINTS_PER_INCH * (1 / 8),  # 9.0
    '3/16"=1\'-0"': POINTS_PER_INCH * (3 / 16),  # 13.5  enlarged plans
    '1/4"=1\'-0"': POINTS_PER_INCH * (1 / 4),  # 18.0  unit plans
    '3/8"=1\'-0"': POINTS_PER_INCH * (3 / 8),  # 27.0
    '1/2"=1\'-0"': POINTS_PER_INCH * (1 / 2),  # 36.0  details
    '3/4"=1\'-0"': POINTS_PER_INCH * (3 / 4),  # 54.0
    '1"=1\'-0"': POINTS_PER_INCH,  # 72.0
}

#: How far a derived scale may drift from the printed one before it's a misread.
SCALE_TOLERANCE = 0.02


class ScaleError(ValueError):
    """The printed scale could not be read, or is not a real architectural scale."""


def parse_scale_label(label: str) -> float:
    """Convert a printed scale into PDF points per foot.

    >>> round(parse_scale_label('3/16" = 1\\'-0"'), 3)
    13.5
    >>> round(parse_scale_label('1/16"=1\\'-0"'), 3)
    4.5
    """
    match = SCALE_RE.search(label)
    if match is None:
        raise ScaleError(f"Unrecognised scale label: {label!r}")

    paper_inches = float(Fraction(match["paper"].replace(" ", "")))
    real_feet = int(match["feet"]) + int(match["inches"]) / 12.0
    if real_feet <= 0:
        raise ScaleError(f"Scale label has a zero real-world length: {label!r}")

    return POINTS_PER_INCH * paper_inches / real_feet


def is_standard_scale(pts_per_ft: float, tolerance: float = SCALE_TOLERANCE) -> bool:
    """True when the value matches a scale an architect would actually use."""
    return any(
        abs(pts_per_ft - known) <= tolerance * known for known in STANDARD_SCALES.values()
    )


def verify_scale(printed_pts_per_ft: float, derived_pts_per_ft: float) -> bool:
    """Cross-check the printed scale against one derived from the drawing.

    Derivation uses a repeated dimension string: on a validated page, three
    `31'-3"` tokens sit a fixed number of points apart, which gives points per
    foot independently of the title block.
    """
    if printed_pts_per_ft <= 0:
        return False
    drift = abs(derived_pts_per_ft - printed_pts_per_ft) / printed_pts_per_ft
    return drift <= SCALE_TOLERANCE


def points_to_feet(points: float, pts_per_ft: float) -> float:
    if pts_per_ft <= 0:
        raise ScaleError("pts_per_ft must be positive")
    return points / pts_per_ft


def sqft_to_m2(sqft: float) -> float:
    return sqft * 0.09290304


def m2_to_sqft(m2: float) -> float:
    return m2 / 0.09290304


def ft_to_m(ft: float) -> float:
    return ft * 0.3048
