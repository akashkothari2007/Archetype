"""Raw CAD strokes collapse into centerline walls before Building construction."""
from __future__ import annotations

from plancheck.core.building import Source
from plancheck.services.imports import from_segments
from plancheck.services.wall_collapse import (
    DEFAULT_THICKNESS_FT,
    MERGE_GAP_FT,
    MIN_WALL_FT,
    PAIR_OFFSET_MAX_FT,
    PAIR_OFFSET_MIN_FT,
    VERTEX_SNAP_FT,
    collapse_wall_segments,
    filter_short_segments,
    merge_collinear,
    pair_parallel_faces,
    segment_length,
    total_run_length,
)


def test_constants_are_module_level():
    assert MIN_WALL_FT == 1.0
    assert VERTEX_SNAP_FT == 0.05
    assert MERGE_GAP_FT == 0.35
    assert PAIR_OFFSET_MIN_FT == 0.2
    assert PAIR_OFFSET_MAX_FT == 1.2
    assert DEFAULT_THICKNESS_FT == 0.5


def test_short_noise_dropped_jamb_kept():
    segments = [
        ((0, 0), (10, 0), "unknown"),
        ((0, 0.5), (10, 0.5), "unknown"),
        ((10, 0), (10, 0.4), "unknown"),
        ((0.2, 3.0), (0.5, 3.2), "unknown"),
    ]
    kept = filter_short_segments(segments)
    assert len(kept) == 3
    assert any(abs(segment_length(a, b) - 0.4) < 1e-6 for a, b, _ in kept)
    assert all(segment_length(a, b) >= 0.4 for a, b, _ in kept)
    tessellation = [
        ((0, 0), (10, 0), "unknown"),
        ((10.7, 0), (20, 0), "unknown"),
        ((10, 0), (10.7, 0), "unknown"),
    ]
    dropped = filter_short_segments(tessellation)
    assert len(dropped) == 2
    assert all(segment_length(a, b) >= MIN_WALL_FT for a, b, _ in dropped)


def test_collinear_runs_union_across_small_gap():
    segments = [
        ((0, 0), (5, 0), "unknown"),
        ((5.2, 0), (10, 0), "unknown"),
        ((0, 4), (3, 4), "unknown"),
    ]
    merged = merge_collinear(segments)
    horiz = [w for w in merged if abs(w[0][1] - w[1][1]) < 1e-6 and abs(w[0][1]) < 0.1]
    assert len(horiz) == 1
    length = segment_length(horiz[0][0], horiz[0][1])
    assert length == 10


def test_parallel_faces_pair_to_centerline_with_thickness():
    segments = [
        ((0, 0), (12, 0), "loadbearing"),
        ((0, 0.5), (12, 0.5), "loadbearing"),
        ((0, 8), (4, 8), "unknown"),
    ]
    paired = pair_parallel_faces(segments)
    thick = [w for w in paired if not w.assumed]
    assert len(thick) == 1
    assert abs(thick[0].thickness_ft - 0.5) < 1e-6
    assert abs(thick[0].start[1] - 0.25) < 1e-6
    unpaired = [w for w in paired if w.assumed]
    assert unpaired
    assert all(w.thickness_ft == DEFAULT_THICKNESS_FT for w in unpaired)


def test_from_segments_dedupes_snapped_vertices():
    segments = [
        ((0.0, 0.0), (10.0, 0.0), "unknown"),
        ((0.02, 0.0), (0.02, 8.0), "unknown"),
        ((10.01, 0.01), (10.01, 8.0), "unknown"),
        ((0.0, 8.0), (10.0, 8.0), "unknown"),
    ]
    building = from_segments(segments, "f1", "Test", Source())
    assert len(building.vertices) <= 6
    assert all(v.x == round(v.x / VERTEX_SNAP_FT) * VERTEX_SNAP_FT for v in building.vertices)


def test_collapse_preserves_run_length_before_pairing():
    from plancheck.services.wall_collapse import filter_short_segments, merge_collinear

    segments = [
        ((0, 0), (8, 0), "unknown"),
        ((8.2, 0), (16, 0), "unknown"),
        ((0, 0.5), (16, 0.5), "unknown"),
        ((0, 0), (0, 10), "unknown"),
        ((0.5, 0), (0.5, 10), "unknown"),
    ]
    filtered = filter_short_segments(segments)
    merged = merge_collinear(filtered)
    pre = total_run_length(filtered)
    post = total_run_length(merged)
    assert abs(post - pre) / pre <= 0.15
    collapsed = collapse_wall_segments(segments)
    assert 2 <= len(collapsed) <= 4
