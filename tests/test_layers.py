from __future__ import annotations

from plancheck.layers import (
    EXCLUDED_BUCKETS,
    LAYER_MAP,
    bucket_for,
    is_excluded,
    normalise,
    wall_class_for,
)

XREF = "21-039_XREF Floor Plans - CFS"


def test_xref_prefix_is_stripped() -> None:
    assert normalise(f"{XREF}|WALL-STUD-LOADBEARING") == "WALL-STUD-LOADBEARING"


def test_bare_layer_name_survives() -> None:
    assert normalise("ANNO-DIMS") == "ANNO-DIMS"


def test_missing_layer_becomes_a_sentinel_not_a_crash() -> None:
    assert normalise(None) == "<none>"
    assert bucket_for(None) is None


def test_bucketing_works_through_the_xref_prefix() -> None:
    assert bucket_for(f"{XREF}|WALL-INTR") == "wall"
    assert bucket_for(f"{XREF}|DOOR") == "door"
    assert bucket_for(f"{XREF}|PLUMBING FIXTURE") == "fixture"


def test_unknown_layer_is_unmapped_rather_than_guessed() -> None:
    assert bucket_for(f"{XREF}|Q-CASE") is None
    assert bucket_for("SOME-LAYER-WE-HAVE-NEVER-SEEN") is None


def test_hatching_and_furniture_are_excluded_not_geometry() -> None:
    assert bucket_for(f"{XREF}|WALL-INSUL") == "wall_hatch"
    assert bucket_for(f"{XREF}|I-FURN") == "furniture"
    assert is_excluded("wall_hatch")
    assert is_excluded("furniture")
    assert not is_excluded("wall")


def test_wall_hatch_is_not_counted_as_wall() -> None:
    """The distinction that keeps wall counts honest."""
    for hatch in LAYER_MAP["wall_hatch"]:
        assert hatch not in LAYER_MAP["wall"]


def test_wall_class_comes_from_the_layer() -> None:
    assert wall_class_for(f"{XREF}|WALL-STUD-LOADBEARING") == "loadbearing"
    assert wall_class_for(f"{XREF}|WALL-INTR") == "interior"
    assert wall_class_for(f"{XREF}|WALL-STUD") == "stud"
    # Plain "WALL" carries no construction information, so we do not invent one.
    assert wall_class_for(f"{XREF}|WALL") == "unknown"


def test_no_layer_is_claimed_by_two_buckets() -> None:
    seen: dict[str, str] = {}
    for bucket, names in LAYER_MAP.items():
        for name in names:
            assert name not in seen, f"{name} is in both {seen.get(name)} and {bucket}"
            seen[name] = bucket


def test_excluded_buckets_are_declared() -> None:
    assert set(EXCLUDED_BUCKETS) <= set(LAYER_MAP)
