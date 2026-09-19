from __future__ import annotations

import pytest

from plancheck.scale import parse_dimension, parse_scale_text


@pytest.mark.parametrize(
    ("text", "pts_per_ft"),
    [
        ('1/4" = 1\'-0"', 18.0),  # unit plans
        ('3/16" = 1\'-0"', 13.5),  # enlarged plans
        ('1/16"=1\'-0"', 4.5),  # whole floor plans
        ('1/8"  =  1\'-0"', 9.0),  # tolerant of title-block spacing
        ('1/2" = 1\'-0"', 36.0),  # details
    ],
)
def test_parse_scale_text(text: str, pts_per_ft: float) -> None:
    result = parse_scale_text(text)
    assert result is not None
    assert result[1] == pytest.approx(pts_per_ft)


def test_scale_normalises_its_own_text() -> None:
    result = parse_scale_text('  3/16"  =  1\'-0"  ')
    assert result is not None
    assert result[0] == '3/16" = 1\'-0"'


def test_missing_scale_is_none_not_an_error() -> None:
    assert parse_scale_text("NOT TO SCALE") is None


def test_metric_bracket_is_preferred_over_imperial() -> None:
    # The imperial half is mangled; the bracket is clean. The bracket wins.
    assert parse_dimension("31'-212 [9.53m]") == (9.53, "metric_bracket")


@pytest.mark.parametrize(
    ("token", "metres"),
    [
        ("31'-212", (31 + 2.5 / 12) * 0.3048),  # 31'-2 1/2"
        ("10'-414", (10 + 4.25 / 12) * 0.3048),  # 10'-4 1/4"
    ],
)
def test_imperial_fraction_repair(token: str, metres: float) -> None:
    """Both fraction digits survived, only the solidus was dropped."""
    result = parse_dimension(token)
    assert result is not None
    assert result[0] == pytest.approx(metres, abs=1e-4)
    assert result[1] == "imperial_repaired"


@pytest.mark.parametrize("token", ["2'-43", "7'-23", "2'-51", "21'-43"])
def test_ambiguous_imperial_drops_the_fraction_rather_than_guessing(token: str) -> None:
    """Only the numerator survived, so the fraction cannot be reconstructed.

    "23" is 2 3/8" on one sheet and 2 3/4" on another. The value is reported
    without the fraction and flagged, never guessed.
    """
    result = parse_dimension(token)
    assert result is not None
    assert result[1] == "imperial_ambiguous"

    feet, inches = token.split("'-")
    expected = (int(feet) + int(inches[:-1]) / 12) * 0.3048
    assert result[0] == pytest.approx(expected, abs=1e-4)


def test_plain_imperial_is_not_treated_as_mangled() -> None:
    result = parse_dimension("6'-5\"")
    assert result is not None
    assert result[1] == "imperial"
    assert result[0] == pytest.approx((6 + 5 / 12) * 0.3048, abs=1e-4)


def test_non_dimension_text_is_none() -> None:
    assert parse_dimension("STUDIO KING") is None
