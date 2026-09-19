"""E1, the document engine — STUB.

WHAT THE REAL ONE WILL DO
    1. Split the page first:  qpdf src.pdf --pages . N -- page.pdf
       MANDATORY. pdfplumber is OOM-killed (exit 137) on the full file.
    2. pdfplumber extract_words() for positioned text.
    3. Match room labels against a vocabulary, merging vertically stacked
       pairs — "STUDIO" above "KING" is one room, not two.
    4. Read the scale from the title block (app.services.scale), then confirm
       it against a repeated dimension string.
    5. Rasterize:  pdftoppm -r 150 -png
    6. cv2.floodFill from each label coordinate to get room boundaries.
       Expect roughly two thirds clean and one third leaking into closets
       and bathrooms.
    7. Pixels to feet via the scale, then flip Y — pdfplumber and OpenCV are
       both y-down and the output is y-up so the renderer doesn't have to think.
    8. Score confidence from leaks, odd aspect ratios, and areas far from the
       type median.

    LANDMINES
    - Imperial fractions extract mangled: 31'-2 1/2" comes out 31'-212.
      Parse the metric bracket [1.52m] instead; it is clean.
    - Room areas are almost never printed. Across 16 candidate pages there
      were 7 printed areas, all common areas, none on guestrooms. Area must
      be computed from the polygon.

WHAT THIS STUB DOES
    Ignores the PDF entirely and generates a plausible double-loaded corridor
    floor so the viewer, the schema and the whole round trip are exercised.
    `meta.generator` is "stub" and a warning says so on every response.
"""

from __future__ import annotations

from pathlib import Path

from app.models.building import (
    SCHEMA_VERSION,
    BBoxFt,
    Building,
    BuildingDefaults,
    BuildingMeta,
    Dimension,
    Level,
    Metric,
    Opening,
    PointFt,
    Provenance,
    Room,
    SheetSource,
    UnitType,
)
from app.models.sheets import Sheet
from app.services.scale import ft_to_m, sqft_to_m2
from app.services.storage import utcnow

GENERATOR = "stub"

# --- synthetic floor geometry, in feet -------------------------------------
_MARGIN = 4.0
_ROOM_DEPTH = 24.0
_CORRIDOR_WIDTH = 5.0
_ROOM_WIDTH = 13.0
_ROOMS_PER_SIDE = 12
_CORE_WIDTH = 22.0

#: type key, display label, share of the unit mix
_UNIT_MIX: list[tuple[str, str]] = [
    ("guestroom.studio_king", "STUDIO KING"),
    ("guestroom.studio_queen_queen", "STUDIO QQ"),
    ("guestroom.one_bedroom_king", "ONE BEDROOM KING"),
    ("guestroom.studio_king_accessible", "STUDIO KING ACCESSIBLE"),
]


def extract(
    pdf_path: Path,
    pages: list[int],
    sheets: list[Sheet] | None = None,
) -> Building:
    """Build a synthetic building for the requested pages."""
    sheet_by_page = {s.page: s for s in (sheets or [])}
    levels = _levels(pages)
    rooms, openings, dimensions = _floor(levels[0])
    unit_types = _unit_types(rooms, levels[0].id)

    for room in rooms:
        for unit_type in unit_types:
            if room.id in unit_type.member_room_ids:
                room.unit_type_id = unit_type.id

    return Building(
        meta=BuildingMeta(
            schema_version=SCHEMA_VERSION,
            source_pdf=pdf_path.name,
            pages=pages,
            generator=GENERATOR,
            extracted_at=utcnow(),
            bounds_ft=_bounds(rooms),
        ),
        defaults=BuildingDefaults(),
        sheets_used=[_sheet_source(p, sheet_by_page.get(p)) for p in pages],
        levels=levels,
        unit_types=unit_types,
        rooms=rooms,
        openings=openings,
        dimensions=dimensions,
        fixtures=[],
        warnings=[
            "STUB OUTPUT. No PDF was parsed. This geometry is generated, not "
            "extracted, and does not describe the uploaded drawing.",
            "Wall height, wall thickness and level elevations are rendering "
            "conventions. 2D plans carry no elevation data.",
        ],
    )


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def _levels(pages: list[int]) -> list[Level]:
    return [
        Level(
            id="L2",
            name="Typical Floor (2nd & 3rd)",
            index=1,
            elevation_ft=11.0,
            floor_to_floor_ft=10.0,
            elevation_assumed=True,
            source_pages=pages,
        )
    ]


def _floor(level: Level) -> tuple[list[Room], list[Opening], list[Dimension]]:
    """A double-loaded corridor: guestrooms down both sides, core at one end."""
    rooms: list[Room] = []
    openings: list[Opening] = []

    corridor_y0 = _MARGIN + _ROOM_DEPTH
    corridor_y1 = corridor_y0 + _CORRIDOR_WIDTH
    run_width = _ROOMS_PER_SIDE * _ROOM_WIDTH

    for index in range(_ROOMS_PER_SIDE):
        x0 = _MARGIN + index * _ROOM_WIDTH
        for side, y0 in (("s", _MARGIN), ("n", corridor_y1)):
            room = _guestroom(index, side, x0, y0, level.id)
            rooms.append(room)
            openings.append(_door(room, corridor_y0 if side == "s" else corridor_y1))

    corridor = _rect_room(
        room_id="R-CORR-1",
        type_="corridor",
        label="CORRIDOR",
        number="200",
        x0=_MARGIN,
        y0=corridor_y0,
        width=run_width + _CORE_WIDTH,
        depth=_CORRIDOR_WIDTH,
        level_id=level.id,
        confidence=0.91,
        page=33,
        sheet_no="A.502a",
        tier="enlarged_plan",
    )
    corridor.metrics["clear_width"] = Metric(
        value=ft_to_m(_CORRIDOR_WIDTH),
        unit="m",
        confidence=0.88,
        source=Provenance(page=33, sheet_no="A.502a", tier="enlarged_plan", method="stub"),
    )
    rooms.append(corridor)

    core_x = _MARGIN + run_width
    rooms.append(
        _rect_room(
            room_id="R-STAIR-1",
            type_="stair",
            label="STAIR 1",
            number="201",
            x0=core_x,
            y0=_MARGIN,
            width=_CORE_WIDTH,
            depth=_ROOM_DEPTH,
            level_id=level.id,
            confidence=0.83,
            page=8,
            sheet_no="A.202",
            tier="floor_plan",
        )
    )
    rooms.append(
        _rect_room(
            room_id="R-ELEV-1",
            type_="elevator",
            label="ELEVATOR LOBBY",
            number="202",
            x0=core_x,
            y0=corridor_y1,
            width=_CORE_WIDTH,
            depth=_ROOM_DEPTH,
            level_id=level.id,
            confidence=0.52,
            page=8,
            sheet_no="A.202",
            tier="floor_plan",
            confidence_notes=[
                "Flood fill leaked into the adjacent service closet.",
                "Area is 38% above the median for this room type.",
            ],
        )
    )

    return rooms, openings, _dimensions(run_width, corridor_y0)


def _guestroom(index: int, side: str, x0: float, y0: float, level_id: str) -> Room:
    type_, label = _UNIT_MIX[index % len(_UNIT_MIX)]
    number = f"2{index + 1:02d}{'a' if side == 'n' else 'b'}"

    # One deliberately poor room so the "needs review" hatching is visible.
    poor = index == 5 and side == "n"

    return _rect_room(
        room_id=f"R-{side.upper()}{index + 1:02d}",
        type_=type_,
        label=label,
        number=number,
        x0=x0,
        y0=y0,
        width=_ROOM_WIDTH,
        depth=_ROOM_DEPTH,
        level_id=level_id,
        confidence=0.41 if poor else 0.87,
        page=51,
        sheet_no="A.801",
        tier="unit_plan",
        confidence_notes=(
            [
                "Flood fill leaked through an unclosed wall into the bathroom.",
                "Aspect ratio is inconsistent with other rooms of this type.",
            ]
            if poor
            else []
        ),
    )


def _rect_room(
    *,
    room_id: str,
    type_: str,
    label: str,
    number: str | None,
    x0: float,
    y0: float,
    width: float,
    depth: float,
    level_id: str,
    confidence: float,
    page: int,
    sheet_no: str,
    tier: str,
    confidence_notes: list[str] | None = None,
) -> Room:
    x1, y1 = x0 + width, y0 + depth
    polygon: list[PointFt] = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    area_sqft = width * depth
    source = Provenance(page=page, sheet_no=sheet_no, tier=tier, method="stub")  # type: ignore[arg-type]

    return Room(
        id=room_id,
        type=type_,
        label=label,
        number=number,
        level_id=level_id,
        polygon_ft=polygon,
        bbox_ft=(x0, y0, x1, y1),
        metrics={
            "area": Metric(
                value=round(sqft_to_m2(area_sqft), 2), unit="m2", confidence=confidence, source=source
            ),
            "width": Metric(
                value=round(ft_to_m(width), 2), unit="m", confidence=confidence, source=source
            ),
            "length": Metric(
                value=round(ft_to_m(depth), 2), unit="m", confidence=confidence, source=source
            ),
        },
        unit_type_id=None,
        confidence=confidence,
        confidence_notes=confidence_notes or [],
        source=source,
        opening_ids=[],
        fixture_ids=[],
        violation_ids=[],
    )


def _door(room: Room, corridor_edge: float) -> Opening:
    x0, y0, x1, y1 = room.bbox_ft
    opening_id = f"D-{room.id}"
    room.opening_ids.append(opening_id)
    return Opening(
        id=opening_id,
        kind="door",
        tag=room.number,
        connects=(room.id, "R-CORR-1"),
        xy_ft=((x0 + x1) / 2, corridor_edge),
        width_ft=3.0,
        height_ft=6.75,
        height_assumed=True,
        source=Provenance(page=48, sheet_no="A.701", tier="schedule", method="stub"),
    )


def _dimensions(run_width: float, corridor_y: float) -> list[Dimension]:
    source = Provenance(page=33, sheet_no="A.502a", tier="enlarged_plan", method="stub")
    return [
        Dimension(
            text=f"{int(run_width)}'-0\" [{ft_to_m(run_width):.2f}m]",
            feet=run_width,
            metres=round(ft_to_m(run_width), 3),
            xy_ft=(_MARGIN + run_width / 2, 1.5),
            near_room_id=None,
            parsed_from="metric_bracket",
            source=source,
        ),
        Dimension(
            text=f"{int(_CORRIDOR_WIDTH)}'-0\" [{ft_to_m(_CORRIDOR_WIDTH):.2f}m]",
            feet=_CORRIDOR_WIDTH,
            metres=round(ft_to_m(_CORRIDOR_WIDTH), 3),
            xy_ft=(_MARGIN - 2.0, corridor_y + _CORRIDOR_WIDTH / 2),
            near_room_id="R-CORR-1",
            parsed_from="metric_bracket",
            source=source,
        ),
    ]


# ---------------------------------------------------------------------------
# Unit types — geometry from the unit plan, counts from the whole floor plan
# ---------------------------------------------------------------------------


def _unit_types(rooms: list[Room], level_id: str) -> list[UnitType]:
    #: Floors that repeat this plan. The real count comes from the floor plan sheet.
    repeating_floors = 3

    by_type: dict[str, list[Room]] = {}
    for room in rooms:
        if room.type.startswith("guestroom."):
            by_type.setdefault(room.type, []).append(room)

    unit_types: list[UnitType] = []
    for type_key, members in sorted(by_type.items()):
        per_floor = len(members)
        unit_types.append(
            UnitType(
                id=f"UT-{type_key.split('.')[-1]}",
                type=type_key,
                label=members[0].label,
                count=per_floor * repeating_floors,
                count_by_level={level_id: per_floor},
                representative_room_id=members[0].id,
                member_room_ids=[room.id for room in members],
                source=Provenance(page=8, sheet_no="A.202", tier="floor_plan", method="stub"),
            )
        )
    return unit_types


def _sheet_source(page: int, sheet: Sheet | None) -> SheetSource:
    tier = sheet.role if sheet and sheet.role in {
        "floor_plan",
        "enlarged_plan",
        "unit_plan",
        "schedule",
    } else "enlarged_plan"
    return SheetSource(
        page=page,
        sheet_no=sheet.sheet_no if sheet else None,
        title=sheet.title if sheet else None,
        tier=tier,  # type: ignore[arg-type]
        scale_label=sheet.scale if sheet else None,
        scale_pts_per_ft=sheet.scale_pts_per_ft if sheet else None,
        dpi=150,
        scale_verified=False,
    )


def _bounds(rooms: list[Room]) -> BBoxFt:
    xs0 = min(r.bbox_ft[0] for r in rooms)
    ys0 = min(r.bbox_ft[1] for r in rooms)
    xs1 = max(r.bbox_ft[2] for r in rooms)
    ys1 = max(r.bbox_ft[3] for r in rooms)
    return (xs0 - _MARGIN, ys0 - _MARGIN, xs1 + _MARGIN, ys1 + _MARGIN)
