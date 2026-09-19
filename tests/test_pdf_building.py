"""PDF → building geometry: room faces, tags, and openings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from plancheck.core.building import Building, Floor, Room, Source, TypeCatalogueEntry
from plancheck.core.schemas import Door, Project, Sheet, SheetGeometry, Wall, Window
from plancheck.core.settings import reset_settings
from plancheck.services.imports import (
    GAP_BRIDGE_FT,
    MAX_ROOM_SQFT,
    MIN_ROOM_AREA_FT2,
    attach_openings,
    build_from_sheets,
    from_segments,
    link_rooms_to_types,
)
from plancheck.services.pdf_extract import (
    EXTRACTOR_VERSION,
    build_room_tags,
    cache_paths,
    is_fallback_room_tag,
    merge_stacked_room_tags,
)

DEFAULT_PDF = (
    Path.home()
    / "Downloads/Information for Akash/Drawings/21-039_Sidney TPS_Arch._IFC.pdf"
)
PDF = Path(os.environ.get("PLANCHECK_TEST_PDF", DEFAULT_PDF))


def test_gap_bridge_closes_doorway():
    assert GAP_BRIDGE_FT == 3.0
    assert MIN_ROOM_AREA_FT2 == 40.0
    segments = [
        ((0, 0), (8.75, 0), "nonstructural"),
        ((11.25, 0), (20, 0), "nonstructural"),
        ((20, 0), (20, 20), "nonstructural"),
        ((20, 20), (0, 20), "nonstructural"),
        ((0, 20), (0, 0), "nonstructural"),
        ((2, 2), (5, 2), "nonstructural"),
        ((5, 2), (5, 5), "nonstructural"),
        ((5, 5), (2, 5), "nonstructural"),
        ((2, 5), (2, 2), "nonstructural"),
    ]
    building = from_segments(segments, "f1", "Test", Source())
    areas = [Polygon(room.polygon).area for room in building.rooms]
    assert areas
    assert max(areas) > 300
    assert all(area >= MIN_ROOM_AREA_FT2 for area in areas)
    assert all(room.needs_review and room.confidence == 0.55 for room in building.rooms)


def test_room_takes_tag_inside_polygon():
    segments = [
        ((0, 0), (20, 0), "nonstructural"),
        ((20, 0), (20, 12), "nonstructural"),
        ((20, 12), (0, 12), "nonstructural"),
        ((0, 12), (0, 0), "nonstructural"),
    ]
    building = from_segments(
        segments,
        "f1",
        "Test",
        Source(),
        room_names=[("VESTIBULE", (10, 6)), ("KING", (10, 6.2))],
        collapse=False,
    )
    names = {room.name for room in building.rooms}
    assert "VESTIBULE" in names or "KING" in names
    assert all(not room.name.startswith("Space ") for room in building.rooms)
    vestibule = next(room for room in building.rooms if room.name == "VESTIBULE")
    assert vestibule.category == "circulation"


def test_oversize_face_is_review_not_a_room():
    segments = [
        ((0, 0), (40, 0), "nonstructural"),
        ((40, 0), (40, 30), "nonstructural"),
        ((40, 30), (0, 30), "nonstructural"),
        ((0, 30), (0, 0), "nonstructural"),
    ]
    building = from_segments(segments, "f1", "Test", Source(), collapse=False, max_room_sqft=MAX_ROOM_SQFT)
    assert building.rooms == []
    assert any("700" in item.message for item in building.review)


def test_small_guestroom_tag_is_not_applied():
    segments = [
        ((0, 0), (8, 0), "nonstructural"),
        ((8, 0), (8, 8), "nonstructural"),
        ((8, 8), (0, 8), "nonstructural"),
        ((0, 8), (0, 0), "nonstructural"),
    ]
    building = from_segments(
        segments, "f1", "Test", Source(), room_names=[("STUDIO KING", (4, 4))], collapse=False
    )
    assert all(room.name != "STUDIO KING" for room in building.rooms)
    assert Polygon(building.rooms[0].polygon).area < 140


def test_nested_fixture_room_inherits_bath_name():
    segments = [
        ((0, 0), (20, 0), "nonstructural"),
        ((20, 0), (20, 20), "nonstructural"),
        ((20, 20), (0, 20), "nonstructural"),
        ((0, 20), (0, 0), "nonstructural"),
        ((2, 2), (9, 2), "nonstructural"),
        ((9, 2), (9, 9), "nonstructural"),
        ((9, 9), (2, 9), "nonstructural"),
        ((2, 9), (2, 2), "nonstructural"),
    ]
    building = from_segments(
        segments,
        "f1",
        "Test",
        Source(),
        room_names=[("STUDIO KING", (14, 14))],
        fixtures=[(5.5, 5.5)],
        collapse=False,
    )
    names = {room.name for room in building.rooms}
    assert "STUDIO KING" in names
    baths = [room for room in building.rooms if room.category == "bathroom"]
    assert baths
    assert any(room.name.endswith("Bath") for room in baths)


def test_named_rooms_share_a_type_ref():
    segments = [
        ((0, 0), (16, 0), "nonstructural"),
        ((16, 0), (16, 22), "nonstructural"),
        ((16, 22), (0, 22), "nonstructural"),
        ((0, 22), (0, 0), "nonstructural"),
        ((20, 0), (36, 0), "nonstructural"),
        ((36, 0), (36, 22), "nonstructural"),
        ((36, 22), (20, 22), "nonstructural"),
        ((20, 22), (20, 0), "nonstructural"),
    ]
    building = from_segments(
        segments,
        "f1",
        "Test",
        Source(),
        room_names=[("STUDIO KING", (8, 11)), ("STUDIO KING", (28, 11))],
        collapse=False,
    )
    named = [room for room in building.rooms if room.name == "STUDIO KING"]
    assert len(named) == 2
    assert named[0].type_ref == named[1].type_ref == "guestroom.studio_king"
    assert named[0].instance_count == 2
    assert named[0].needs_review is False


def test_should_extract_skips_enlarged_before_geometry():
    from plancheck.services.imports import should_extract_sheet, skip_label

    enlarged = Sheet(
        sheet_id="s",
        doc_id="d",
        page=30,
        role="enlarged_plan",
        use=True,
        reason="enlarged",
    )
    floor = Sheet(
        sheet_id="f",
        doc_id="d",
        page=8,
        role="floor_plan",
        use=True,
        reason="plan",
    )
    elevation = Sheet(
        sheet_id="e",
        doc_id="d",
        page=17,
        role="elevation",
        use=False,
        reason="Exterior elevation. No plan geometry.",
    )
    assert should_extract_sheet(floor)
    assert not should_extract_sheet(enlarged)
    assert not should_extract_sheet(elevation)
    assert "enlarged" in skip_label(enlarged)


def test_extractor_cache_key_uses_version(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANCHECK_DATA_DIR", str(tmp_path / "projects"))
    reset_settings()
    json_path, raster_path, thumb = cache_paths("deadbeef", 8)
    assert EXTRACTOR_VERSION in json_path.parts
    assert json_path.name == "8.json"
    assert raster_path.name == "8.raster.png"
    assert thumb.name == "8.thumb.png"


def test_fallback_room_tags_drop_dimensions_and_merge_stack():
    assert is_fallback_room_tag("STUDIO")
    assert is_fallback_room_tag("KING")
    assert not is_fallback_room_tag("8'-11 3 4 \"")
    assert not is_fallback_room_tag("[2.74m]")
    assert not is_fallback_room_tag("W-P6")
    items = [
        {"text": "STUDIO", "xy": [100.0, 50.0]},
        {"text": "KING", "xy": [101.0, 38.0]},
        {"text": "[2.74m]", "xy": [200.0, 40.0]},
    ]
    tags = build_room_tags(items, [])
    texts = [tag.text for tag in tags]
    assert "STUDIO KING" in texts
    assert all(not any(ch.isdigit() or ch == "[" for ch in text) for text in texts)
    stacked = merge_stacked_room_tags(
        [{"text": "STUDIO", "xy": [10.0, 30.0]}, {"text": "KING", "xy": [11.0, 16.0]}]
    )
    assert stacked[0]["text"] == "STUDIO KING"


def test_room_tag_layer_uses_path_bbox():
    items = [
        {"text": "101", "xy": [5.0, 5.0]},
        {"text": "HALL", "xy": [50.0, 50.0]},
    ]
    tags = build_room_tags(items, [[0.0, 0.0, 10.0, 10.0]])
    assert [tag.text for tag in tags] == ["101"]


def test_room_tag_frame_captures_stacked_label():
    bar = [1658.8, 1240.6, 1679.0, 1246.1]
    expanded = [bar[0] - 12, bar[1] - 8, bar[2] + 12, bar[3] + 18]
    items = [
        {"text": "STUDIO", "xy": [1668.7, 1254.4]},
        {"text": "KING", "xy": [1668.6, 1249.1]},
        {"text": "8'-11", "xy": [1700.0, 1300.0]},
    ]
    tags = build_room_tags(items, [expanded])
    assert [tag.text for tag in tags] == ["STUDIO KING"]


def test_openings_snap_to_nearest_wall():
    segments = [
        ((0, 0), (20, 0), "nonstructural"),
        ((20, 0), (20, 10), "nonstructural"),
        ((20, 10), (0, 10), "nonstructural"),
        ((0, 10), (0, 0), "nonstructural"),
    ]
    building = from_segments(segments, "f1", "Test", Source())
    geom = SheetGeometry(
        sheet_id="s",
        page=1,
        size_pt=[100, 100],
        scale_pts_per_ft=1,
        walls=[Wall(id="w", a=[0, 0], b=[20, 0], layer="DOOR", len_ft=20)],
        doors=[Door(id="door-1", xy=[4, 0.2], bbox=[3, 0, 7, 1], width_pt=4, width_ft=3)],
        windows=[Window(id="win-1", a=[12, 0.1], b=[16, 0.1], width_ft=4)],
    )
    attach_openings(building, geom, lambda p: (p[0], p[1]), Source(sheet_id="s"))
    assert len(building.openings) >= 2
    assert {o.kind for o in building.openings} == {"door", "window"}
    assert all(o.offset_ft >= 0 for o in building.openings)


def _plan_sheet(sheet_id, page, role, levels, scale=4.5):
    return Sheet(
        sheet_id=sheet_id,
        doc_id="drw",
        page=page,
        title="FLOOR PLAN",
        role=role,
        scale_pts_per_ft=scale,
        levels=levels,
        use=True,
        reason="test",
    )


def _box_geom(sheet_id, page, scale=4.5, width=16.3, depth=27.5):
    w, d = width * scale, depth * scale
    return SheetGeometry(
        sheet_id=sheet_id,
        page=page,
        doc_id="drw",
        size_pt=[w + 20, d + 20],
        scale_pts_per_ft=scale,
        walls=[
            Wall(id=f"{sheet_id}-w0", a=[10, 10], b=[10 + w, 10], layer="WALL", len_ft=width),
            Wall(id=f"{sheet_id}-w1", a=[10 + w, 10], b=[10 + w, 10 + d], layer="WALL", len_ft=depth),
            Wall(id=f"{sheet_id}-w2", a=[10 + w, 10 + d], b=[10, 10 + d], layer="WALL", len_ft=width),
            Wall(id=f"{sheet_id}-w3", a=[10, 10 + d], b=[10, 10], layer="WALL", len_ft=depth),
        ],
        regions=[
            {
                "id": f"{sheet_id}-region-1",
                "name": "STUDIO KING",
                "bbox_pt": [0, 0, w + 20, d + 20],
                "kind": "unit",
                "scale_pts_per_ft": scale,
            }
        ],
    )


def test_floor_plan_emits_one_floor_per_level():
    sheet = _plan_sheet("s-typical", 8, "floor_plan", ["2", "3"])
    geom = _box_geom("s-typical", 8)
    building = build_from_sheets(Project(project_id="t", name="t", created_at="", sheets=[sheet]), [geom])
    assert [f.id for f in building.floors] == ["level-2", "level-3"]
    assert [f.name for f in building.floors] == ["Level 2", "Level 3"]
    assert [f.elevation_ft for f in building.floors] == [10, 20]
    assert {r.floor_id for r in building.rooms} == {"level-2", "level-3"}


def test_duplicate_level_does_not_add_another_floor():
    sheets = [
        _plan_sheet("s-ground", 7, "floor_plan", ["1"]),
        _plan_sheet("s-repeat", 47, "floor_plan", ["1"]),
    ]
    geoms = [_box_geom("s-ground", 7), _box_geom("s-repeat", 47)]
    building = build_from_sheets(Project(project_id="t", name="t", created_at="", sheets=sheets), geoms)
    assert [f.id for f in building.floors] == ["level-1"]
    assert building.floors[0].name == "Ground"


def test_enlarged_plan_is_skipped():
    sheet = _plan_sheet("s-enl", 33, "enlarged_plan", ["2"], scale=13.5)
    geom = _box_geom("s-enl", 33, scale=13.5)
    building = build_from_sheets(Project(project_id="t", name="t", created_at="", sheets=[sheet]), [geom])
    assert building.floors == []
    assert building.rooms == []


def test_unit_plan_fills_catalogue_not_floors():
    sheet = _plan_sheet("s-unit", 51, "unit_plan", [], scale=18)
    sheet.title = "UNIT PLAN"
    geom = _box_geom("s-unit", 51, scale=18)
    building = build_from_sheets(Project(project_id="t", name="t", created_at="", sheets=[sheet]), [geom])
    assert building.floors == []
    assert len(building.type_catalogue) == 1
    entry = building.type_catalogue[0]
    assert entry.label.startswith("Reference ·")
    assert "STUDIO KING" in entry.name
    assert any("not a building storey" in item.message for item in building.review)


def test_link_rooms_by_area_and_aspect():
    studio = [(0, 0), (16.3, 0), (16.3, 27.5), (0, 27.5)]
    other = [(0, 0), (40, 0), (40, 40), (0, 40)]
    building = Building(
        floors=[Floor(id="level-2", name="Level 2", elevation_ft=10)],
        rooms=[
            Room(id="r1", floor_id="level-2", name="201", category="guestroom", polygon=studio),
            Room(id="r2", floor_id="level-2", name="Hall", category="guestroom", polygon=other),
        ],
        type_catalogue=[
            TypeCatalogueEntry(
                type_ref="guestroom.studio_king",
                name="STUDIO KING",
                label="Reference · STUDIO KING",
                category="guestroom",
                polygon=studio,
                area_sqft=16.3 * 27.5,
                aspect_ratio=27.5 / 16.3,
            )
        ],
    )
    link_rooms_to_types(building)
    assert building.rooms[0].type_ref == "guestroom.studio_king"
    assert building.rooms[1].type_ref == ""
    assert building.type_catalogue[0].instance_count == 1


@pytest.fixture(scope="module")
def page51(tmp_path_factory):
    from plancheck.engines.classify import classify_document
    from plancheck.services.pdf_extract import extract

    _document, sheets = classify_document(PDF, "drw-01")
    sheet = next(s for s in sheets if s.page == 51)
    raster = tmp_path_factory.mktemp("p51") / "raster.png"
    geom = extract(sheet, PDF, raster)
    project = Project(project_id="t", name="t", created_at="", sheets=[sheet])
    building = build_from_sheets(project, [geom])
    return sheet, geom, building


@pytest.mark.skipif(not PDF.is_file(), reason=f"Drawing set not available at {PDF}")
class TestPage51Sidney:
    def test_sheet_identity(self, page51):
        sheet, geom, _building = page51
        assert sheet.sheet_no == "A.801"
        assert sheet.role == "unit_plan"
        assert geom.scale_pts_per_ft == pytest.approx(18.0)

    def test_rooms_close_across_door_gaps(self, page51):
        _sheet, geom, _building = page51
        scale = geom.scale_pts_per_ft
        lines = [
            ((w.a[0] / scale, w.a[1] / scale), (w.b[0] / scale, w.b[1] / scale), "unknown")
            for w in geom.walls
        ]
        building = from_segments(lines, "tmp", "tmp", Source(), collapse=False)
        areas = [Polygon(room.polygon).area for room in building.rooms]
        mid = [area for area in areas if 140 <= area <= 520]
        assert len(mid) >= 7
        assert 2400 <= sum(areas) <= 3000
        near = []
        for room, area in zip(building.rooms, areas):
            if area < 140 or area > 520:
                continue
            xs = [p[0] for p in room.polygon]
            ys = [p[1] for p in room.polygon]
            width, depth = max(xs) - min(xs), max(ys) - min(ys)
            if (abs(width - 16.3) < 2 and abs(depth - 27.5) < 2) or (
                abs(depth - 16.3) < 2 and abs(width - 27.5) < 2
            ):
                near.append(room)
        assert len(near) >= 2

    def test_room_tags_are_names_not_dimensions(self, page51):
        _sheet, geom, _building = page51
        texts = [tag.text for tag in geom.room_tags]
        blob = " ".join(texts)
        assert "STUDIO" in blob
        assert "KING" in blob
        assert all(not any(ch.isdigit() or ch == "[" for ch in text) for text in texts)

    def test_unit_plan_is_catalogue_not_a_storey(self, page51):
        _sheet, _geom, building = page51
        assert building.floors == []
        assert 5 <= len(building.type_catalogue) <= 10
        assert all(entry.label.startswith("Reference ·") for entry in building.type_catalogue)
        assert any("not a building storey" in item.message for item in building.review)
        assert any(entry.area_sqft >= 140 for entry in building.type_catalogue)


@pytest.fixture(scope="module")
def sidney_building(tmp_path_factory):
    from plancheck.engines.classify import classify_document
    from plancheck.services.pdf_extract import extract

    _document, sheets = classify_document(PDF, "drw-01")
    wanted = {7, 8, 51}
    selected = [s for s in sheets if s.page in wanted]
    raster_root = tmp_path_factory.mktemp("sidney")
    geometries = []
    for sheet in selected:
        geom = extract(sheet, PDF, raster_root / f"{sheet.sheet_id}.png")
        geometries.append(geom)
    project = Project(project_id="t", name="t", created_at="", sheets=sheets)
    return sheets, geometries, build_from_sheets(project, geometries)


@pytest.mark.skipif(not PDF.is_file(), reason=f"Drawing set not available at {PDF}")
class TestSidneyFloorMapping:
    def test_three_storeys_and_unit_catalogue(self, sidney_building):
        _sheets, _geometries, building = sidney_building
        assert [floor.id for floor in building.floors] == ["level-1", "level-2", "level-3"]
        assert [floor.name for floor in building.floors] == ["Ground", "Level 2", "Level 3"]
        assert 5 <= len(building.type_catalogue) <= 10
        guests = [
            room
            for room in building.rooms
            if room.floor_id == "level-2" and room.category == "guestroom"
        ]
        assert guests
        linked = [room for room in guests if room.type_ref]
        assert len(linked) / len(guests) >= 0.6
        assert any(entry.instance_count > 0 for entry in building.type_catalogue)

    def test_typical_floor_uses_room_names(self, sidney_building):
        _sheets, _geometries, building = sidney_building
        names = {room.name for room in building.rooms if room.floor_id == "level-2"}
        assert "STUDIO KING" in names
        assert any("QQ" in name for name in names)
        assert any(token in name for name in names for token in ("CORRIDOR", "STAIR", "LOBBY"))
        assert all(not name.startswith("Space ") for name in names)

    def test_room_quality_and_types(self, sidney_building):
        _sheets, _geometries, building = sidney_building
        rooms = building.rooms
        unnamed = sum(1 for room in rooms if room.name == "Unnamed")
        assert unnamed / max(1, len(rooms)) < 0.25
        assert sum(1 for room in rooms if room.category == "bathroom") >= 20
        areas = [Polygon(room.polygon).area for room in rooms]
        assert areas
        assert max(areas) <= 700
        assert 34250 * 0.85 <= sum(areas) <= 34250 * 1.15
        for room in rooms:
            blob = room.name.upper()
            if any(token in blob for token in ("STUDIO", "KING", "QQ")) and "BATH" not in blob and "CLOSET" not in blob:
                assert Polygon(room.polygon).area >= 140
        named = [room for room in rooms if room.name != "Unnamed" and not room.name.startswith("Space ")]
        assert named
        assert all(room.type_ref for room in named)
        kings = [room for room in named if "STUDIO KING" == room.name]
        if kings:
            assert kings[0].instance_count == len(kings)
            assert all(room.type_ref == kings[0].type_ref for room in kings)
        assert sum(1 for room in rooms if room.needs_review) / len(rooms) < 0.40
