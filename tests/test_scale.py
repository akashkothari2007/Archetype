import pytest

from plancheck.core.scale import find_scale, parse_scale


@pytest.mark.parametrize(
    "text, expected",
    [
        ('1/4" = 1\'-0"', 18.0),
        ('3/16" = 1\'-0"', 13.5),
        ('1/16" = 1\'-0"', 4.5),
        ('1/8" = 1\'-0"', 9.0),
    ],
)
def test_parse_scale(text, expected):
    assert parse_scale(text) == pytest.approx(expected)


def test_find_scale_embedded():
    text, pts = find_scale('SCALE: 1/4" = 1\'-0"  NORTH')
    assert text == '1/4" = 1\'-0"'
    assert pts == pytest.approx(18.0)


def test_find_scale_missing():
    assert find_scale("no scale here") == (None, None)
