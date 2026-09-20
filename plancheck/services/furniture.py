"""Default furniture catalog and room-layout placement for the assistant."""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import Point, Polygon

from plancheck.core.building import Building, PlacedObject, Room
from plancheck.services.commands import uid

_CLEAR = 0.35
_SKIP_CATEGORIES = {
    "bathroom", "wc", "restroom", "toilet", "ensuite", "powder", "washroom",
    "lavatory", "circulation", "corridor", "lobby", "landing", "foyer", "hall",
    "stair", "stairs", "core", "mechanical", "utility", "storage", "closet", "service",
}
_LIVING = {"living", "living_room", "lounge", "family", "great_room", "sitting"}
_BEDROOM = {"bedroom", "guestroom", "bed", "suite", "master"}
_DINING = {"dining", "dining_room", "eat_in"}
_KITCHEN = {"kitchen", "pantry", "scullery"}
_OFFICE = {"office", "study", "studio", "den", "library", "work"}
_ENTRY = {"entry", "entryway", "vestibule", "mudroom"}
_FURNISH_RE = re.compile(
    r"\b(furnish|furniture|furnishing|decorate|sofa|couch|armchair|ottoman|"
    r"nightstand|bookshelf|bookcase|credenza|sideboard|loveseat|"
    r"coffee\s+table|dining\s+table|place\s+(?:a\s+)?(?:bed|desk|chair|table)|"
    r"add\s+(?:a\s+)?(?:sofa|couch|bed|desk|chair|table|ottoman))\b",
    re.I,
)
_REPLACE_RE = re.compile(r"\b(refurnish|redecorate|replace|clear|remove|start over)\b", re.I)
_KITS: dict[str, list[str]] = {
    "living": ["sofa", "chair", "chair", "coffee_table", "side_table", "tv", "shelves", "ottoman"],
    "bedroom": ["bed", "nightstand", "nightstand", "dresser", "chair"],
    "dining": ["dining_table", "dining_chair", "dining_chair", "dining_chair", "dining_chair", "cabinet"],
    "kitchen": ["stool", "stool", "range", "cart"],
    "office": ["desk", "desk_chair", "shelves", "chair"],
    "entry": ["console", "mirror", "bench"],
    "other": ["sofa", "coffee_table", "chair", "shelves"],
}


def _catalog_path() -> Path:
    here = Path(__file__).resolve()
    repo = here.parents[2]
    for path in (
        here.parents[1] / "data" / "furniture_catalog.json",
        repo / "apps" / "desktop" / "src" / "renderer" / "furniture-catalog.json",
    ):
        if path.is_file():
            return path
    raise FileNotFoundError("furniture catalog is missing")


@lru_cache(maxsize=1)
def furniture_catalog() -> list[dict[str, Any]]:
    payload = json.loads(_catalog_path().read_text(encoding="utf-8"))
    return [item for item in payload if isinstance(item, dict) and item.get("id")]


def furniture_brief() -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "label": item.get("label") or item["id"],
            "role": item.get("role") or "",
            "width_ft": item.get("width"),
            "depth_ft": item.get("depth"),
            "height_ft": item.get("height"),
            "rooms": list(item.get("rooms") or []),
        }
        for item in furniture_catalog()
    ]


def furniture_by_id(asset_id: str) -> dict[str, Any] | None:
    key = (asset_id or "").strip()
    for item in furniture_catalog():
        if item["id"] == key:
            return item
    return None


def is_furnish_request(message: str) -> bool:
    return bool(_FURNISH_RE.search(message or ""))


def wants_refurnish(message: str) -> bool:
    return bool(_REPLACE_RE.search(message or ""))


def match_catalog_assets(message: str) -> list[dict[str, Any]]:
    text = (message or "").lower()
    found: list[dict[str, Any]] = []
    for item in furniture_catalog():
        tokens = {
            str(item.get("label") or "").lower(),
            item["id"].replace("_", " ").lower(),
            str(item.get("role") or "").replace("_", " ").lower(),
        }
        if any(token and token in text for token in tokens if len(token) > 2):
            found.append(item)
    return found


def _room_kind(room: Room) -> str | None:
    hay = f"{room.category} {room.name}".lower().replace("-", "_")
    tokens = set(re.split(r"[\s/_]+", hay))
    if room.category in _SKIP_CATEGORIES or tokens & _SKIP_CATEGORIES:
        return None
    if tokens & _LIVING or "living" in hay:
        return "living"
    if tokens & _BEDROOM or "bedroom" in hay or "guest" in hay:
        return "bedroom"
    if tokens & _DINING or "dining" in hay:
        return "dining"
    if tokens & _KITCHEN or "kitchen" in hay:
        return "kitchen"
    if tokens & _OFFICE:
        return "office"
    if tokens & _ENTRY:
        return "entry"
    return "other"


def _polygon(room: Room) -> Polygon | None:
    if not room.polygon or len(room.polygon) < 3:
        return None
    poly = Polygon([(float(x), float(y)) for x, y in room.polygon])
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.geom_type != "Polygon" or poly.area < 16:
        return None
    return poly


def _inward_normal(poly: Polygon, a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float] | None:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 0.4:
        return None
    nx, ny = -dy / length, dx / length
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    probe = Point(mid[0] + nx * 0.4, mid[1] + ny * 0.4)
    if poly.contains(probe) or poly.covers(probe):
        return nx, ny
    return -nx, -ny


def _edges(poly: Polygon) -> list[tuple[float, tuple[float, float], tuple[float, float], tuple[float, float]]]:
    coords = list(poly.exterior.coords)
    edges = []
    for a, b in zip(coords, coords[1:]):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        normal = _inward_normal(poly, a, b)
        if not normal or length < 1.5:
            continue
        edges.append((length, a, b, normal))
    edges.sort(key=lambda item: item[0], reverse=True)
    return edges


def _rotation(normal: tuple[float, float]) -> float:
    angle = math.degrees(math.atan2(normal[0], normal[1]))
    return (angle + 360) % 360


def _footprint(x: float, y: float, width: float, depth: float, rotation_deg: float) -> Polygon:
    rad = math.radians(rotation_deg)
    hx, hy = width / 2, depth / 2
    corners = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    world = []
    for lx, ly in corners:
        world.append((x + lx * cos_a + ly * sin_a, y - lx * sin_a + ly * cos_a))
    return Polygon(world)


def _fits(poly: Polygon, occupied: list[Polygon], footprint: Polygon, pad: float = 0.12) -> bool:
    grown = footprint.buffer(pad)
    if not poly.contains(grown.centroid):
        return False
    interior = poly.buffer(-0.15)
    if interior.is_empty or not interior.contains(footprint.centroid):
        return False
    if footprint.difference(poly).area > footprint.area * 0.08:
        return False
    for other in occupied:
        if grown.intersects(other):
            return False
    return True


def _pick(role: str, used: set[str], room_kind: str) -> dict[str, Any] | None:
    preferred = []
    fallback = []
    for item in furniture_catalog():
        if item["id"] in used or item.get("role") != role:
            continue
        rooms = set(item.get("rooms") or [])
        (preferred if not rooms or room_kind in rooms else fallback).append(item)
    pool = preferred or fallback
    return pool[0] if pool else None


def _place_against_wall(
    poly: Polygon,
    occupied: list[Polygon],
    item: dict[str, Any],
    edge: tuple[float, tuple[float, float], tuple[float, float], tuple[float, float]],
    along_t: float = 0.5,
) -> dict[str, float] | None:
    length, a, b, normal = edge
    width = float(item["width"])
    depth = float(item["depth"])
    if length < width + 0.8:
        return None
    t = min(max(along_t, (width / 2 + 0.4) / length), 1 - (width / 2 + 0.4) / length)
    px = a[0] + (b[0] - a[0]) * t
    py = a[1] + (b[1] - a[1]) * t
    inset = depth / 2 + _CLEAR
    x, y = px + normal[0] * inset, py + normal[1] * inset
    rotation = _rotation(normal)
    footprint = _footprint(x, y, width, depth, rotation)
    if not _fits(poly, occupied, footprint):
        for extra in (0.3, 0.6, 0.9):
            x2, y2 = px + normal[0] * (inset + extra), py + normal[1] * (inset + extra)
            footprint = _footprint(x2, y2, width, depth, rotation)
            if _fits(poly, occupied, footprint):
                x, y = x2, y2
                break
        else:
            return None
    return {"x": round(x, 3), "y": round(y, 3), "rotation_deg": round(rotation, 2)}


def _place_center(poly: Polygon, occupied: list[Polygon], item: dict[str, Any], offset: tuple[float, float] = (0, 0)) -> dict[str, float] | None:
    centroid = poly.centroid
    x, y = centroid.x + offset[0], centroid.y + offset[1]
    width, depth = float(item["width"]), float(item["depth"])
    for rotation in (0, 90, 180, 270):
        footprint = _footprint(x, y, width, depth, rotation)
        if _fits(poly, occupied, footprint, pad=0.2):
            return {"x": round(x, 3), "y": round(y, 3), "rotation_deg": rotation}
    return None


def _occupied(poly: Polygon, objects: Iterable[PlacedObject]) -> list[Polygon]:
    found = []
    for obj in objects:
        footprint = _footprint(obj.x, obj.y, obj.width_ft, obj.depth_ft, obj.rotation_deg).buffer(0.08)
        if footprint.intersects(poly):
            found.append(footprint)
    return found


def _command(room: Room, item: dict[str, Any], pose: dict[str, float]) -> dict[str, Any]:
    return {
        "kind": "place_object",
        "target_id": "",
        "params": {
            "id": uid("object"),
            "floor_id": room.floor_id,
            "asset_id": item["id"],
            "kind": "furniture",
            "x": pose["x"],
            "y": pose["y"],
            "rotation_deg": pose["rotation_deg"],
            "width_ft": float(item["width"]),
            "depth_ft": float(item["depth"]),
            "height_ft": float(item["height"]),
        },
    }


def furnish_room(
    room: Room,
    objects: list[PlacedObject],
    *,
    assets: list[dict[str, Any]] | None = None,
    replace: bool = False,
) -> list[dict[str, Any]]:
    poly = _polygon(room)
    kind = _room_kind(room)
    if poly is None or kind is None:
        return []
    room_poly = Polygon(room.polygon)
    existing = [obj for obj in objects if obj.kind == "furniture" and room_poly.contains(Point(obj.x, obj.y))]
    if existing and not replace and not assets:
        return []
    occupied = [] if replace else _occupied(poly, objects)
    used: set[str] = set()
    commands: list[dict[str, Any]] = []
    edges = _edges(poly)
    if not edges:
        return []

    picks: list[dict[str, Any]] = []
    if assets:
        picks = list(assets)
    else:
        for role in _KITS.get(kind) or _KITS["other"]:
            item = _pick(role, used, kind)
            if item:
                used.add(item["id"])
                picks.append(item)

    sofa_pose = None
    edge_index = 0
    along_slots = [0.5, 0.28, 0.72, 0.18, 0.82]
    slot = 0
    for item in picks:
        role = item.get("role") or ""
        pose = None
        if role in {"dining_table", "coffee_table", "ottoman"}:
            offset = (0.0, 0.0)
            if role == "coffee_table" and sofa_pose:
                rad = math.radians(sofa_pose["rotation_deg"])
                offset = (math.sin(rad) * 3.2, math.cos(rad) * 3.2)
            pose = _place_center(poly, occupied, item, offset)
        if pose is None:
            for attempt in range(len(edges)):
                edge = edges[(edge_index + attempt) % len(edges)]
                pose = _place_against_wall(poly, occupied, item, edge, along_slots[slot % len(along_slots)])
                if pose:
                    edge_index += 1
                    slot += 1
                    break
        if pose is None:
            pose = _place_center(poly, occupied, item)
        if not pose:
            continue
        footprint = _footprint(pose["x"], pose["y"], float(item["width"]), float(item["depth"]), pose["rotation_deg"])
        occupied.append(footprint.buffer(0.1))
        if role == "sofa":
            sofa_pose = pose
        commands.append(_command(room, item, pose))
    return commands


def furnish_building(
    building: Building,
    *,
    rooms: list[Room] | None = None,
    message: str = "",
    replace: bool | None = None,
) -> list[dict[str, Any]]:
    targets = rooms if rooms is not None else list(building.rooms)
    whole = bool(re.search(r"\b(furnish|furniture|decorate|refurnish)\b", message or "", re.I))
    replace = wants_refurnish(message) or whole if replace is None else replace
    specific = match_catalog_assets(message)
    use_specific = bool(specific) and not whole
    commands: list[dict[str, Any]] = []
    if replace:
        for room in targets:
            poly = _polygon(room)
            if poly is None:
                continue
            for obj in building.objects:
                if obj.kind != "furniture":
                    continue
                if poly.contains(Point(obj.x, obj.y)):
                    commands.append({"kind": "delete", "target_id": obj.id, "params": {}})
    for room in targets:
        commands.extend(
            furnish_room(
                room,
                building.objects,
                assets=specific if use_specific else None,
                replace=replace,
            )
        )
    return commands[:80]


def target_rooms(building: Building, message: str, selected_ids: list[str], floor_ids: list[str]) -> list[Room]:
    selected = [room for room in building.rooms if room.id in set(selected_ids)]
    if selected:
        return selected
    text = (message or "").lower()
    stop = {"room", "the", "this", "that", "floor", "area", "space", "place", "here", "with", "from", "into"}
    named: list[Room] = []
    for room in building.rooms:
        tokens = {room.name.lower(), room.category.lower(), *re.split(r"[\s/_-]+", room.name.lower())}
        tokens = {token for token in tokens if token and len(token) > 2 and token not in stop}
        if any(token in text for token in tokens):
            named.append(room)
    if named:
        if floor_ids:
            preferred = [room for room in named if room.floor_id in floor_ids]
            if preferred:
                return preferred
        return named
    scoped = [room for room in building.rooms if not floor_ids or room.floor_id in floor_ids]
    return [room for room in scoped if _room_kind(room)]
