from plancheck.core.layers import bucket_for, normalise, summarise


def test_xref_prefix_normalise():
    raw = "21-039_XREF Floor Plans - CFS|WALL-STUD-LOADBEARING"
    assert normalise(raw) == "WALL-STUD-LOADBEARING"
    assert bucket_for(raw) == "wall"


def test_unknown_goes_to_unmapped():
    summary = summarise(["ANNO-FOO", "21-039|ANNO-FOO", "WALL"])
    assert summary.unmapped["ANNO-FOO"] == 2
    assert summary.buckets["wall"] == 1
    assert summary.buckets["unmapped"] == 2


def test_excluded_buckets():
    summary = summarise(["FURNITURE", "WALL-INSUL", "DOOR"])
    assert summary.excluded["furniture"] == 1
    assert summary.excluded["wall_hatch"] == 1
    assert summary.buckets["door"] == 1
