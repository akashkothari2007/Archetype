from __future__ import annotations

import pymupdf

from plancheck.geometry import (
    PageTransform,
    clean_segments,
    cluster_boxes,
    merge_collinear,
    path_segments,
    snap_to_axis,
)

#: Reference sheets are A1 landscape with /Rotate 270.
ROTATED = PageTransform(matrix=pymupdf.Matrix(0, -1, 1, 0, 0, 1684), height=1684, width=2384)
UPRIGHT = PageTransform(matrix=pymupdf.Matrix(1, 0, 0, 1, 0, 0), height=1000, width=800)


class TestTransform:
    def test_y_is_flipped_to_point_up(self) -> None:
        assert UPRIGHT.point((10, 0)) == (10, 1000)
        assert UPRIGHT.point((10, 1000)) == (10, 0)

    def test_rotation_is_applied_before_the_flip(self) -> None:
        """A rotated page's raw y can exceed page height.

        Raw coordinates live in mediabox space (1684 x 2384). Flipping without
        rotating first would put this point at y = 1684 - 2162 = -478.
        """
        x, y = ROTATED.point((83.6, 2162.6))
        assert 0 <= x <= 2384
        assert 0 <= y <= 1684

    def test_whole_rotated_page_lands_inside_the_sheet(self) -> None:
        for raw in [(0, 0), (1684, 0), (0, 2384), (1684, 2384)]:
            x, y = ROTATED.point(raw)
            assert -0.01 <= x <= 2384.01
            assert -0.01 <= y <= 1684.01

    def test_bbox_stays_ordered_after_the_flip(self) -> None:
        x0, y0, x1, y1 = ROTATED.bbox(pymupdf.Rect(100, 200, 300, 500))
        assert x0 < x1 and y0 < y1

    def test_plumber_top_flips_without_rotation(self) -> None:
        assert ROTATED.flip_top(0) == 1684
        assert ROTATED.flip_top(1684) == 0


class TestSnapping:
    def test_near_horizontal_is_squared_up(self) -> None:
        assert snap_to_axis(((0, 10.0), (50, 10.4))) == ((0, 10.2), (50, 10.2))

    def test_near_vertical_is_squared_up(self) -> None:
        assert snap_to_axis(((10.0, 0), (10.3, 50))) == ((10.15, 0), (10.15, 50))

    def test_a_real_diagonal_is_left_alone(self) -> None:
        diagonal = ((0.0, 0.0), (50.0, 50.0))
        assert snap_to_axis(diagonal) == diagonal


class TestMerging:
    def test_touching_collinear_segments_become_one(self) -> None:
        merged = merge_collinear([((0, 5), (10, 5)), ((10, 5), (25, 5))])
        assert merged == [((0, 5), (25, 5))]

    def test_a_real_gap_is_preserved(self) -> None:
        merged = merge_collinear([((0, 5), (10, 5)), ((40, 5), (60, 5))])
        assert len(merged) == 2

    def test_parallel_offset_lines_do_not_merge(self) -> None:
        """Two faces of one wall must stay two lines."""
        merged = merge_collinear([((0, 5), (10, 5)), ((0, 11), (10, 11))])
        assert len(merged) == 2

    def test_a_wide_gap_bridges_a_dashed_line(self) -> None:
        """Grid lines are dashed; the longest single dash is about 20pt."""
        dashes = [((x, 100), (x + 8, 100)) for x in range(0, 200, 20)]
        assert len(merge_collinear(dashes)) > 1
        bridged = merge_collinear(dashes, gap=24.0)
        assert len(bridged) == 1
        assert bridged[0][0][0] == 0 and bridged[0][1][0] == 188

    def test_diagonals_pass_through_untouched(self) -> None:
        diagonal = ((0.0, 0.0), (50.0, 50.0))
        assert diagonal in merge_collinear([diagonal])


class TestCleanSegments:
    def test_short_noise_is_dropped(self) -> None:
        assert clean_segments([((0, 0), (1.0, 0))]) == []

    def test_snapping_happens_before_merging(self) -> None:
        """Sub-point drift must not stop two collinear pieces from joining."""
        merged = clean_segments([((0, 10.0), (10, 10.2)), ((10, 10.1), (25, 10.0))])
        assert len(merged) == 1


class TestPathFlattening:
    def test_a_line_item_becomes_one_segment(self) -> None:
        items = [("l", pymupdf.Point(0, 0), pymupdf.Point(10, 0))]
        assert len(path_segments(items, UPRIGHT)) == 1

    def test_a_rectangle_becomes_four_segments(self) -> None:
        items = [("re", pymupdf.Rect(0, 0, 10, 20))]
        assert len(path_segments(items, UPRIGHT)) == 4

    def test_a_curve_is_reduced_to_its_chord(self) -> None:
        items = [
            (
                "c",
                pymupdf.Point(0, 0),
                pymupdf.Point(3, 5),
                pymupdf.Point(7, 5),
                pymupdf.Point(10, 0),
            )
        ]
        segments = path_segments(items, UPRIGHT)
        assert len(segments) == 1
        assert segments[0][0][0] == 0 and segments[0][1][0] == 10

    def test_an_unknown_item_type_does_not_crash(self) -> None:
        assert path_segments([("zz", None)], UPRIGHT) == []


class TestClusterBoxes:
    def test_adjacent_glyph_strokes_group_into_one_label(self) -> None:
        """Outlined text arrives as one path per stroke."""
        strokes = [[x, 0.0, x + 1.2, 7.0] for x in range(0, 20, 2)]
        clusters = cluster_boxes(strokes, pad=2.0)
        assert len(clusters) == 1
        assert clusters[0][0] == 0.0 and clusters[0][2] == 19.2

    def test_separated_labels_stay_separate(self) -> None:
        left = [[x, 0.0, x + 1.2, 7.0] for x in range(0, 10, 2)]
        right = [[x, 0.0, x + 1.2, 7.0] for x in range(200, 210, 2)]
        assert len(cluster_boxes(left + right, pad=2.0)) == 2

    def test_empty_input(self) -> None:
        assert cluster_boxes([], pad=2.0) == []
