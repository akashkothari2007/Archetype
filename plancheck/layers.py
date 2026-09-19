"""CAD layer names -> semantic buckets.

This module is the entire value of the parse. Do not flatten layer information
away downstream.

Layer names carry an xref prefix:
    "21-039_XREF Floor Plans - CFS|WALL-STUD-LOADBEARING"
Always split on "|" and use the last segment.
"""

from __future__ import annotations

# --- semantic buckets ------------------------------------------------------

#: Buckets whose paths are parsed into geometry.
GEOMETRY_BUCKETS = (
    "wall",
    "door",
    "window",
    "fixture",
    "grid",
    "column",
    "stair",
    "elevator",
    "shaft",
    "clear_space",
    "room_tag",
    "dimension",
)

#: Buckets that are counted and then dropped. Hatching is a fill pattern that
#: duplicates the wall it sits inside; furniture is not part of the building.
EXCLUDED_BUCKETS = ("wall_hatch", "furniture")

ALL_BUCKETS = GEOMETRY_BUCKETS + EXCLUDED_BUCKETS

#: Bucket -> normalised layer names.
#:
#: Names beyond the base table were added after auditing every distinct layer
#: on pages 8, 30 and 51 of the reference set. They are what make the bucket
#: totals reconcile exactly with the acceptance figures, e.g. page 51 doors =
#: DOOR (104) + ANNO-TAG-DOOR (84) = 188, and page 8 grid = GRID-96 (2303) +
#: ANNO-GRID (43) = 2346.
LAYER_MAP: dict[str, tuple[str, ...]] = {
    "wall": (
        "WALL",
        "WALL-INTR",
        "WALL-STUD",
        "WALL-STUD-LOADBEARING",
        "WALL-CONC",
        "WALL-EXTR CLAD",
        "WALL-STRU",
    ),
    # Fill patterns drawn inside walls. Counted, then excluded — keeping them
    # would triple the path count and draw nothing a human reads as a wall.
    "wall_hatch": (
        "WALL-INSUL",
        "WALL-HATCH LIGHT",
        "WALL-HATCH-LIGHT",
        "HATCH-CONC. WALL",
    ),
    "door": (
        "DOOR",
        "DOOR-FINE",
        "DOOR-HIDDEN",
        "ANNO-TAG-DOOR",
    ),
    "window": (
        "WINDOW",
        "WINDOW-FINE",
        "WINDOW-FRAME",
        "WINDOW-GLAZING",
        "WINDOW SILL",
        "WINDOW_SILL",
    ),
    "fixture": (
        "PLUMBING FIXTURE",
        "PLMG-FIXTURES",
        "P-SANR-FIXT",
        "A-PLMG-FIXT",
        "NEW-PLUMB",
        "NEW-PMB-DRAINS",
    ),
    "grid": (
        "GRID",
        "GRID-96",
        "ANNO-GRID",
    ),
    "column": (
        "COLUMN",
        "S-COLUMN",
    ),
    "stair": (
        "STAIR",
        "A-STAIRS",
    ),
    "elevator": ("ELEVATOR",),
    "shaft": ("MECH-SHAFT",),
    "clear_space": (
        "FLOOR-CLR SPACE",
        "ANNO-CLEAR SPACE",
    ),
    "room_tag": ("ANNO-ROOM TAG",),
    "dimension": ("ANNO-DIMS",),
    "furniture": (
        "I-FURN",
        "I-FURN-HDLN",
        "FURNITURE",
        "ID FURN",
        "FUR",
        "MILLWORK",
    ),
}

#: Reverse index, built once.
_LAYER_TO_BUCKET: dict[str, str] = {
    layer: bucket for bucket, layers in LAYER_MAP.items() for layer in layers
}

#: Wall layer -> construction class. Anything else is "unknown"; we do not guess.
WALL_CLASS: dict[str, str] = {
    "WALL-STUD-LOADBEARING": "loadbearing",
    "WALL-INTR": "interior",
    "WALL-STUD": "stud",
    "WALL-CONC": "concrete",
    "WALL-STRU": "structural",
    "WALL-EXTR CLAD": "exterior_cladding",
}

#: Layers that mark a sheet as carrying real plan geometry, used by the
#: classifier's sanity check.
WALL_LAYERS = frozenset(LAYER_MAP["wall"])


def normalise(layer: str | None) -> str:
    """Strip the xref prefix. `None` becomes the sentinel "<none>"."""
    if not layer:
        return "<none>"
    return layer.split("|")[-1].strip()


def bucket_for(layer: str | None) -> str | None:
    """Semantic bucket for a raw layer name, or None if unmapped.

    Unmapped is a legitimate answer. Callers must record the layer rather than
    discard the path, so nothing is silently lost.
    """
    return _LAYER_TO_BUCKET.get(normalise(layer))


def wall_class_for(layer: str | None) -> str:
    return WALL_CLASS.get(normalise(layer), "unknown")


def is_excluded(bucket: str | None) -> bool:
    return bucket in EXCLUDED_BUCKETS
