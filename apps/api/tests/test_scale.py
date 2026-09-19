"""Scale arithmetic is real code, not a stub, so it gets real tests."""

from __future__ import annotations

import pytest

from app.services.scale import (
    ScaleError,
    is_standard_scale,
    parse_scale_label,
    verify_scale,
)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ('1/16" = 1\'-0"', 4.5),  # whole floor plans
        ('3/16" = 1\'-0"', 13.5),  # enlarged plans
        ('1/4" = 1\'-0"', 18.0),  # unit plans
        ('1/2"=1\'-0"', 36.0),  # details
        ('1/8"  =  1\'-0"', 9.0),  # tolerant of title-block spacing
    ],
)
def test_parse_scale_label(label: str, expected: float) -> None:
    assert parse_scale_label(label) == pytest.approx(expected)


def test_parse_scale_label_rejects_garbage() -> None:
    with pytest.raises(ScaleError):
        parse_scale_label("NOT TO SCALE")


def test_standard_scales_are_recognised() -> None:
    assert is_standard_scale(13.5)
    # 13.505 is what deriving from a repeated dimension string produces.
    assert is_standard_scale(13.505)
    assert not is_standard_scale(21.0)


def test_verify_scale_accepts_small_drift_and_rejects_a_misread() -> None:
    assert verify_scale(13.5, 13.505)
    assert not verify_scale(13.5, 18.0)
