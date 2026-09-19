"""Parse architectural scale strings into PDF points per foot.

72 PDF points = 1 inch on paper. For ``1/4" = 1'-0"`` the paper length
representing one real foot is 0.25 in, so points per foot is 0.25 * 72 = 18.0.
"""

from __future__ import annotations

import re

SCALE_RE = re.compile(
    r"""
    (\d+(?:/\d+)?)
    "
    \s*=\s*
    (\d+)'-(\d+)"
    """,
    re.VERBOSE,
)


def parse_fraction(value: str) -> float:
    """``'1/4'`` -> 0.25, ``'3'`` -> 3.0."""
    if "/" in value:
        num, den = value.split("/", 1)
        return float(num) / float(den)
    return float(value)


def parse_scale(text: str) -> float:
    """Return points per foot for the first scale expression in ``text``.

    Raises ``ValueError`` if nothing matches.
    """
    match = SCALE_RE.search(text)
    if match is None:
        raise ValueError(f"No architectural scale found in {text!r}")
    return pts_per_ft_from_match(match)


def find_scale(text: str) -> tuple[str | None, float | None]:
    """Return ``(scale_text, pts_per_ft)`` or ``(None, None)``."""
    match = SCALE_RE.search(text)
    if match is None:
        return None, None
    return match.group(0), pts_per_ft_from_match(match)


def pts_per_ft_from_match(match: re.Match[str]) -> float:
    paper_inches = parse_fraction(match.group(1))
    real_feet = int(match.group(2)) + int(match.group(3)) / 12.0
    if real_feet == 0:
        raise ValueError("Scale real-world length cannot be zero")
    return (paper_inches * 72.0) / real_feet
