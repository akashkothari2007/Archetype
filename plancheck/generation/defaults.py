"""Per-use heuristics, brief parsing, and the starter requirement packs.

These are design defaults and project requirements, not building code. They are
injected into the prompt so the model does not have to guess, and they seed the
Standards tab so generated geometry is measured the moment it exists.
"""

from __future__ import annotations

import fnmatch
import math
import re
from dataclasses import dataclass, field
from typing import Any

from plancheck.generation.program import USES, BuildingUse

SQFT_PER_SQM = 10.763910416709722
DOOR_WIDTH_FT = 3.0
DOOR_HEIGHT_FT = 7.0
WINDOW_WIDTH_FT = 5.0
WINDOW_HEIGHT_FT = 4.0
WINDOW_SILL_FT = 3.0


@dataclass(frozen=True)
class UseProfile:
    key: BuildingUse
    label: str
    floor_height_ft: float
    corridor_width_ft: float
    aspect: float
    default_area_sqft: float
    default_floors: int
    typical_areas: dict[str, float]
    ordering: tuple[str, ...]
    guidance: tuple[str, ...] = field(default_factory=tuple)


PROFILES: dict[str, UseProfile] = {
    "home": UseProfile(
        key="home",
        label="Home",
        floor_height_ft=10,
        corridor_width_ft=4,
        aspect=1.35,
        default_area_sqft=2400,
        default_floors=2,
        typical_areas={
            "living": 320, "kitchen": 200, "dining": 180, "bedroom": 180,
            "primary_bedroom": 260, "bathroom": 60, "office": 130, "storage": 60,
            "utility": 70, "circulation": 140, "stair": 90, "garage": 400,
        },
        ordering=("living", "kitchen", "dining", "circulation", "stair", "office", "bedroom", "bathroom", "utility", "storage"),
        guidance=(
            "Put living, kitchen and dining together as one open public zone on the entry storey.",
            "Circulation is a compact hall or foyer next to the stair, never a corridor through the house.",
            "Bedrooms cluster on the upper storey when there is more than one; stack bathrooms.",
        ),
    ),
    "office": UseProfile(
        key="office",
        label="Office",
        floor_height_ft=12,
        corridor_width_ft=6,
        aspect=1.5,
        default_area_sqft=8000,
        default_floors=2,
        typical_areas={
            "reception": 300, "open_office": 1600, "office": 140, "meeting": 240,
            "boardroom": 420, "break": 260, "bathroom": 120, "storage": 100,
            "server": 90, "circulation": 320, "stair": 130,
        },
        ordering=("reception", "circulation", "stair", "open_office", "meeting", "boardroom", "office", "break", "bathroom", "server", "storage"),
        guidance=(
            "Reception sits on the entry storey next to the stair core.",
            "A corridor should reach every enclosed room; keep it at least 6 ft wide.",
            "Repeat the stair and washrooms in the same position on every storey.",
        ),
    ),
    "retail": UseProfile(
        key="retail",
        label="Retail",
        floor_height_ft=13,
        corridor_width_ft=6,
        aspect=1.4,
        default_area_sqft=5000,
        default_floors=1,
        typical_areas={
            "sales": 2400, "entry": 200, "fitting": 90, "stock": 500,
            "receiving": 260, "bathroom": 100, "break": 180, "office": 140,
            "circulation": 220, "stair": 120,
        },
        ordering=("entry", "sales", "fitting", "circulation", "stair", "office", "break", "bathroom", "stock", "receiving"),
        guidance=(
            "Give the sales floor the largest single rectangle, facing the street edge.",
            "Stock, receiving and staff rooms line the back of the plan. Do not cut a hallway through the shop floor.",
        ),
    ),
    "mixed": UseProfile(
        key="mixed",
        label="Mixed use",
        floor_height_ft=12,
        corridor_width_ft=6,
        aspect=1.45,
        default_area_sqft=9000,
        default_floors=3,
        typical_areas={
            "lobby": 420, "sales": 1400, "retail": 1400, "open_office": 1400,
            "office": 150, "meeting": 240, "apartment": 700, "living": 300,
            "bedroom": 180, "kitchen": 140, "bathroom": 110, "break": 220,
            "storage": 120, "circulation": 320, "stair": 130,
        },
        ordering=("lobby", "entry", "circulation", "stair", "sales", "retail", "open_office", "living", "kitchen", "meeting", "office", "bedroom", "break", "bathroom", "storage"),
        guidance=(
            "Keep the public uses (lobby, retail) as large rooms on the ground storey, not rooms along a hallway.",
            "Put workplace or residential space above, sharing one stair core.",
        ),
    ),
}

# First matching pattern wins. Longer / more specific kinds come first so
# "home office" and "cafe" inside a hospital brief cannot steal the type.
_KIND_PATTERNS: tuple[tuple[str, str, BuildingUse], ...] = (
    (r"\bmulti[-\s]?use\b|\bmixed\b", "mixed", "mixed"),
    (r"\bhospital\b|\bmedical centre\b|\bmedical center\b|\bhealthcare\b", "hospital", "office"),
    (r"\bclinic\b|\bdental\b", "clinic", "office"),
    (r"\bhotel\b|\bmotel\b|\binn\b", "hotel", "mixed"),
    (r"\bschool\b|\buniversity\b|\bcollege\b|\bcampus\b", "school", "office"),
    (r"\bwarehouse\b|\bfactory\b|\bindustrial\b|\bworkshop\b", "warehouse", "retail"),
    (r"\bmuseum\b|\btheatre\b|\btheater\b|\bgallery\b|\bcivic\b", "civic", "mixed"),
    (r"\bchurch\b|\bmosque\b|\btemple\b|\bsynagogue\b|\bworship\b", "worship", "mixed"),
    (r"\bgym\b|\bstadium\b|\barena\b", "gym", "retail"),
    (r"\blibrary\b", "library", "office"),
    (r"\bapartment\b|\bapartments\b|\bresidential\b", "apartment", "home"),
    (r"\boffice\b|\bworkplace\b|\bcoworking\b", "office", "office"),
    (r"\bstudio\b", "office", "office"),
    (r"\brestaurant\b|\bcafe\b|\bcoffee\b|\bdiner\b", "restaurant", "retail"),
    (r"\bretail\b|\bshop\b|\bstore\b|\bboutique\b|\bshowroom\b|\bsupermarket\b", "retail", "retail"),
    (r"\bhome\b|\bhouse\b|\bvilla\b|\bcabin\b|\bduplex\b|\bdwelling\b", "home", "home"),
)

# category -> typical usable sqft. Used as a size hint when the library has no
# richer room entry, and as a fallback for unknown kinds.
_KIND_AREAS: dict[str, dict[str, float]] = {
    "hospital": {
        "lobby": 800, "cafe": 400, "reception": 300, "waiting": 400, "triage": 240,
        "exam": 140, "ward": 900, "icu": 600, "or": 450, "pharmacy": 220,
        "lab": 280, "radiology": 360, "nurse_station": 180, "office": 140,
        "bathroom": 120, "break": 200, "storage": 160, "circulation": 480, "stair": 160,
    },
    "clinic": {
        "lobby": 320, "reception": 180, "waiting": 280, "exam": 140, "procedure": 220,
        "office": 140, "bathroom": 90, "break": 140, "storage": 100, "circulation": 240, "stair": 130,
    },
    "hotel": {
        "lobby": 600, "reception": 240, "restaurant": 800, "kitchen": 400,
        "guest_room": 320, "suite": 480, "meeting": 300, "laundry": 220,
        "bathroom": 80, "circulation": 360, "stair": 140, "storage": 140,
    },
    "school": {
        "lobby": 400, "classroom": 800, "lab": 700, "library": 900, "office": 160,
        "cafeteria": 1200, "gym": 2400, "bathroom": 140, "circulation": 400, "stair": 150,
    },
    "warehouse": {
        "entry": 200, "warehouse": 6000, "receiving": 500, "office": 180,
        "break": 160, "bathroom": 100, "circulation": 240, "stair": 130,
    },
    "restaurant": {
        "entry": 140, "dining": 1800, "bar": 320, "kitchen": 700, "storage": 220,
        "bathroom": 100, "office": 120, "circulation": 180, "stair": 120,
    },
    "worship": {
        "lobby": 400, "sanctuary": 2400, "ablution": 220, "classroom": 400,
        "office": 160, "bathroom": 110, "storage": 140, "circulation": 280, "stair": 140,
    },
    "gym": {
        "entry": 200, "gym": 4000, "studio": 800, "locker": 400, "office": 140,
        "bathroom": 160, "storage": 180, "circulation": 240, "stair": 130,
    },
    "library": {
        "lobby": 320, "stacks": 1800, "reading": 900, "office": 160, "meeting": 240,
        "bathroom": 110, "storage": 140, "circulation": 280, "stair": 140,
    },
    "apartment": {
        "lobby": 360, "living": 280, "kitchen": 140, "bedroom": 160, "bathroom": 70,
        "storage": 80, "circulation": 220, "stair": 130,
    },
    "civic": {
        "lobby": 500, "gallery": 1600, "auditorium": 2200, "office": 160, "cafe": 320,
        "bathroom": 120, "storage": 180, "circulation": 320, "stair": 150,
    },
}

_KIND_GUIDANCE: dict[str, tuple[str, ...]] = {
    "hospital": (
        "Public lobby, cafe and reception sit on the entry storey.",
        "Group wards, exam rooms and nurse stations off a wide corridor; stack the stair and washrooms.",
        "Do not enumerate every bed. One ward or one operating theatre is a single space.",
    ),
    "clinic": (
        "Waiting and reception on the entry storey; exam rooms line a corridor.",
        "A procedure room is one space, not one space per chair.",
    ),
    "hotel": (
        "Lobby, restaurant and reception on the entry storey; guest rooms above.",
        "A typical guest room is one space, repeated a few times, not one space per key.",
    ),
    "school": (
        "Classrooms line a corridor. Each classroom the brief names is its own space, never a grouped blob.",
        "Shared gym, cafeteria and library can sit on the entry storey.",
    ),
    "warehouse": (
        "Give the warehouse floor the largest rectangle. Offices and staff rooms line one edge.",
        "Do not run a corridor through the warehouse plate.",
    ),
    "restaurant": (
        "Dining faces the street as one large room. Kitchen, storage and staff rooms sit behind.",
        "The dining room is one space, not a table per rectangle. A small entry or bar, not a hallway spine.",
    ),
    "worship": (
        "The sanctuary or prayer hall is the largest space, reached from a compact lobby or narthex.",
        "Ablution, offices and classrooms support it along the edge; do not split the hall into pews or a corridor.",
    ),
    "gym": (
        "The main gym floor takes most of the plate. Lockers and studios line the edge, not a central hallway.",
    ),
    "library": (
        "Stacks and reading rooms sit off a quiet lobby. Staff offices at the back.",
    ),
    "apartment": (
        "A shared lobby and stair on the entry storey; dwelling rooms grouped as units above.",
        "Do not explode every unit into a full house program.",
    ),
    "civic": (
        "A public lobby and the largest gathering room sit on the entry storey.",
        "Staff offices, stores and washrooms support the public rooms along an edge, not a hotel corridor.",
    ),
}

# How the packer draws this kind. The planner sizes circulation to match.
_KIND_LAYOUT: dict[str, str] = {
    "home": "cluster",
    "apartment": "corridor",
    "office": "corridor",
    "hospital": "corridor",
    "clinic": "corridor",
    "hotel": "corridor",
    "school": "corridor",
    "library": "corridor",
    "retail": "edge",
    "warehouse": "hall",
    "restaurant": "hall",
    "worship": "hall",
    "gym": "hall",
    "civic": "hall",
    "mixed": "mixed",
}

_LAYOUT_NOTES: dict[str, tuple[str, ...]] = {
    "cluster": (
        "Circulation is a compact hall, foyer or landing next to the stair — not a corridor through the house.",
        "Living, kitchen and dining share one open public zone. Bedrooms cluster; keep hallways short.",
    ),
    "hall": (
        "One dominant room (sanctuary, gym, dining hall, warehouse) takes most of the plate.",
        "A lobby or narthex leads into it. Support rooms line the back edge, not a central hallway.",
    ),
    "edge": (
        "The sales or warehouse floor is the largest rectangle, facing the street.",
        "Stock, staff and washrooms line the back. Do not cut a hallway through the sales floor.",
    ),
    "corridor": (
        "A double-loaded corridor with rooms on both sides is the right diagram for this kind.",
        "Size the corridor generously so every enclosed room can open onto it.",
    ),
    "mixed": (
        "Public ground-floor rooms (lobby, shop, hall) are large plates, not rooms on a hallway.",
        "Upper workplace or guest-room floors may use a corridor; dwelling floors cluster like a house.",
    ),
}


def layout_scheme(kind: str, use: str = "") -> str:
    """Packer diagram for this building kind: cluster, hall, edge, corridor, or mixed."""
    key = (kind or use or "home").strip().lower()
    if key in _KIND_LAYOUT:
        return _KIND_LAYOUT[key]
    if use == "home":
        return "cluster"
    if use == "retail":
        return "edge"
    if use == "office":
        return "corridor"
    return "mixed"


def layout_notes(kind: str, use: str = "") -> tuple[str, ...]:
    return _LAYOUT_NOTES.get(layout_scheme(kind, use), _LAYOUT_NOTES["mixed"])

# Richer program knowledge than typical_areas: named rooms, why they exist, and
# which storey they usually occupy. Research consults this instead of guessing.
_KIND_LIBRARY: dict[str, dict[str, Any]] = {
    "hospital": {
        "label": "Hospital",
        "blurb": "A clinical building with a public arrival floor and inpatient floors stacked on a corridor core.",
        "source": (
            "Archetype hospital program library",
            "Typical inpatient stacking, department sizes, and what not to enumerate (beds, desks).",
        ),
        "rooms": (
            ("lobby", "Public lobby", "entry", "Arrival and wayfinding for patients and visitors."),
            ("reception", "Reception", "entry", "Check-in next to the lobby."),
            ("cafe", "Cafe", "entry", "Public refreshment on the entry storey."),
            ("waiting", "Waiting", "entry", "Holds people before triage or clinics."),
            ("triage", "Triage", "entry", "First clinical filter off the waiting room."),
            ("ward", "Inpatient ward", "upper", "One grouped ward, not a bed per room."),
            ("or", "Operating theatre", "upper", "A single OR suite as one space."),
            ("icu", "ICU", "upper", "Critical care grouped off the corridor."),
            ("nurse_station", "Nurse station", "every", "Oversight next to wards or exam rooms."),
            ("pharmacy", "Pharmacy", "entry", "Dispensing near the public side."),
            ("radiology", "Radiology", "entry", "Imaging, kept as one department."),
            ("bathroom", "Washrooms", "every", "Repeat per storey rather than one for the building."),
        ),
    },
    "clinic": {
        "label": "Clinic",
        "blurb": "An outpatient building organised around reception, waiting and exam rooms.",
        "source": (
            "Archetype clinic program library",
            "Outpatient exam-room programs and typical support spaces.",
        ),
        "rooms": (
            ("lobby", "Lobby", "entry", "Public arrival."),
            ("reception", "Reception", "entry", "Check-in facing the waiting room."),
            ("waiting", "Waiting", "entry", "Patients wait before being called."),
            ("exam", "Exam room", "any", "Repeat a few exam rooms, not one per chair."),
            ("procedure", "Procedure room", "any", "A larger clinical room off the corridor."),
            ("office", "Consult office", "any", "Clinician workspace."),
            ("bathroom", "Washrooms", "every", "Repeat on each storey."),
        ),
    },
    "hotel": {
        "label": "Hotel",
        "blurb": "Public hospitality on the ground floor with guest rooms stacked above.",
        "source": (
            "Archetype hotel program library",
            "Lobby-and-keys stacking; guest rooms as repeated types, not one space per key.",
        ),
        "rooms": (
            ("lobby", "Lobby", "entry", "Public arrival and sitting."),
            ("reception", "Reception", "entry", "Front desk on the lobby."),
            ("restaurant", "Restaurant", "entry", "Public dining on the entry storey."),
            ("kitchen", "Kitchen", "entry", "Serves the restaurant, back of house."),
            ("guest_room", "Guest room", "upper", "A typical key, repeated a few times."),
            ("suite", "Suite", "upper", "A larger guest type, not every key."),
            ("meeting", "Meeting room", "any", "Conference support."),
            ("laundry", "Laundry", "any", "Housekeeping support."),
            ("bathroom", "Washrooms", "every", "Public washrooms on the entry storey; guest baths live in the rooms."),
        ),
    },
    "school": {
        "label": "School",
        "blurb": "Classrooms along a corridor, with shared gym, cafeteria and library.",
        "source": (
            "Archetype school program library",
            "Classroom-and-corridor plans and shared specialist rooms.",
        ),
        "rooms": (
            ("lobby", "Lobby", "entry", "Arrival and administration."),
            ("classroom", "Classroom", "any", "Each classroom is its own room. Four classrooms means four spaces."),
            ("lab", "Lab", "any", "Specialist teaching."),
            ("library", "Library", "entry", "Shared learning resource."),
            ("cafeteria", "Cafeteria", "entry", "Shared dining."),
            ("gym", "Gym", "entry", "The large shared hall."),
            ("office", "Admin office", "entry", "Staff and administration."),
            ("bathroom", "Washrooms", "every", "Repeat per storey."),
        ),
    },
    "warehouse": {
        "label": "Warehouse",
        "blurb": "A large storage plate with a thin office and receiving edge.",
        "source": (
            "Archetype warehouse program library",
            "Floor-plate programs for storage, receiving and a small staff edge.",
        ),
        "rooms": (
            ("warehouse", "Warehouse floor", "entry", "The dominant storage plate."),
            ("receiving", "Receiving", "entry", "Dock and inbound, at the back."),
            ("office", "Office", "entry", "Staff on the street edge."),
            ("break", "Break room", "entry", "Staff support."),
            ("bathroom", "Washrooms", "entry", "Staff washrooms."),
        ),
    },
    "restaurant": {
        "label": "Restaurant",
        "blurb": "Dining to the street, kitchen and stores behind.",
        "source": (
            "Archetype restaurant program library",
            "Front-of-house dining versus back-of-house kitchen and stores.",
        ),
        "rooms": (
            ("entry", "Entry", "entry", "Arrival and waiting."),
            ("dining", "Dining room", "entry", "The main public room, one large space."),
            ("bar", "Bar", "entry", "Optional service edge on the dining room."),
            ("kitchen", "Kitchen", "entry", "Back of house, largest support room."),
            ("storage", "Dry storage", "entry", "Beside the kitchen."),
            ("bathroom", "Washrooms", "entry", "Public washrooms off the dining room."),
            ("office", "Manager office", "entry", "Small staff room at the back."),
        ),
    },
    "worship": {
        "label": "Place of worship",
        "blurb": "A large sanctuary or prayer hall reached from a lobby, with support rooms around it.",
        "source": (
            "Archetype worship program library",
            "Sanctuary-led plans for mosques, churches, temples and synagogues.",
        ),
        "rooms": (
            ("lobby", "Lobby", "entry", "Gathering before entering the hall."),
            ("sanctuary", "Prayer hall", "entry", "The largest room; do not subdivide into seats."),
            ("ablution", "Ablution / vestry", "entry", "Preparation next to the hall."),
            ("classroom", "Classroom", "any", "Education and community use."),
            ("office", "Office", "any", "Clergy or administration."),
            ("bathroom", "Washrooms", "every", "Repeat per storey."),
        ),
    },
    "gym": {
        "label": "Gym",
        "blurb": "A large activity floor with lockers, studios and a thin staff edge.",
        "source": (
            "Archetype recreation program library",
            "Gym-floor programs with locker and studio support.",
        ),
        "rooms": (
            ("entry", "Entry", "entry", "Arrival and check-in."),
            ("gym", "Gym floor", "entry", "The dominant activity plate."),
            ("studio", "Studio", "any", "A smaller class room."),
            ("locker", "Lockers", "entry", "Changing next to the gym floor."),
            ("bathroom", "Washrooms", "entry", "Public washrooms by the lockers."),
            ("office", "Office", "entry", "Staff at the edge."),
        ),
    },
    "library": {
        "label": "Library",
        "blurb": "Stacks and reading rooms off a quiet public lobby.",
        "source": (
            "Archetype library program library",
            "Public reading, stacks and staff support.",
        ),
        "rooms": (
            ("lobby", "Lobby", "entry", "Arrival and control."),
            ("stacks", "Stacks", "any", "The main collection as one space."),
            ("reading", "Reading room", "any", "Quiet seating next to the stacks."),
            ("meeting", "Meeting room", "any", "Community or staff meeting."),
            ("office", "Staff office", "any", "Workroom at the back."),
            ("bathroom", "Washrooms", "every", "Repeat per storey."),
        ),
    },
    "apartment": {
        "label": "Apartments",
        "blurb": "Shared lobby and stair, with dwelling rooms grouped as units rather than a single house.",
        "source": (
            "Archetype residential program library",
            "Multi-unit stacking: shared core plus a few typical dwellings.",
        ),
        "rooms": (
            ("lobby", "Lobby", "entry", "Shared arrival."),
            ("living", "Living", "upper", "Part of a typical dwelling, not one living room for the block."),
            ("kitchen", "Kitchen", "upper", "Grouped with living in the unit."),
            ("bedroom", "Bedroom", "upper", "Repeat a few bedrooms, not one per resident."),
            ("bathroom", "Bathroom", "every", "In the unit and as a shared washroom on the entry storey."),
        ),
    },
    "civic": {
        "label": "Civic building",
        "blurb": "A public gathering building with a lobby and one large room, offices behind.",
        "source": (
            "Archetype civic program library",
            "Museums, theatres and other public halls: lobby, main room, support.",
        ),
        "rooms": (
            ("lobby", "Lobby", "entry", "Public arrival."),
            ("gallery", "Gallery / hall", "entry", "The principal public room."),
            ("auditorium", "Auditorium", "entry", "Use only if the brief asks for performance."),
            ("cafe", "Cafe", "entry", "Public refreshment."),
            ("office", "Office", "any", "Staff support."),
            ("bathroom", "Washrooms", "every", "Repeat per storey."),
        ),
    },
    "home": {
        "label": "Home",
        "blurb": "A dwelling: open living-kitchen-dining, a short hall by the stair, bedrooms clustered — not a hotel corridor.",
        "source": (
            "Archetype house program library",
            "Living-kitchen-dining together; bedrooms stacked; plumbing shared.",
        ),
        "rooms": (
            ("living", "Living room", "entry", "The main gathering room on the entry storey."),
            ("kitchen", "Kitchen", "entry", "Open to living and dining."),
            ("dining", "Dining", "entry", "Next to the kitchen."),
            ("primary_bedroom", "Primary bedroom", "upper", "The largest bedroom, usually upstairs."),
            ("bedroom", "Bedroom", "upper", "Repeat to match the brief."),
            ("bathroom", "Bathroom", "every", "Stack plumbing; at least one per storey."),
            ("office", "Study", "any", "Only if the brief asks for one."),
            ("garage", "Garage", "entry", "Only if the brief asks for one."),
        ),
    },
    "office": {
        "label": "Office",
        "blurb": "A workplace with reception on the entry storey and work and meeting rooms along a corridor.",
        "source": (
            "Archetype workplace program library",
            "Reception, core, open work and meeting rooms on a corridor.",
        ),
        "rooms": (
            ("reception", "Reception", "entry", "Arrival next to the stair core."),
            ("open_office", "Open work", "any", "The largest workplace plate on each work storey."),
            ("meeting", "Meeting room", "any", "Repeat a few meeting rooms, not one per person."),
            ("office", "Enclosed office", "any", "Private offices as named in the brief."),
            ("break", "Break room", "any", "Staff support."),
            ("bathroom", "Washrooms", "every", "Repeat in the core."),
        ),
    },
    "retail": {
        "label": "Retail",
        "blurb": "A shop with a large sales floor facing the street and stock behind.",
        "source": (
            "Archetype retail program library",
            "Sales-floor-led plans with fitting, stock and staff at the back.",
        ),
        "rooms": (
            ("entry", "Entry", "entry", "Street arrival."),
            ("sales", "Sales floor", "entry", "The dominant public room."),
            ("fitting", "Fitting", "entry", "Only if the brief is apparel."),
            ("stock", "Stock", "entry", "Back of house."),
            ("receiving", "Receiving", "entry", "Goods in, at the rear."),
            ("office", "Office", "entry", "Manager at the back."),
            ("bathroom", "Washrooms", "entry", "Staff and public as needed."),
        ),
    },
    "mixed": {
        "label": "Mixed use",
        "blurb": "Public uses on the ground floor with workplace or dwellings above, sharing one core.",
        "source": (
            "Archetype mixed-use program library",
            "Public ground floor, quieter uses above, one stacked stair.",
        ),
        "rooms": (
            ("lobby", "Lobby", "entry", "Shared public arrival."),
            ("sales", "Retail", "entry", "Public ground-floor use."),
            ("open_office", "Workplace", "upper", "Work above the public floor."),
            ("living", "Living", "upper", "Residential above, only if the brief is dwellings."),
            ("meeting", "Meeting", "upper", "If the upper floors are workplace."),
            ("bathroom", "Washrooms", "every", "Repeat in the core."),
        ),
    },
}


def detect_kind(*texts: str) -> str:
    """Specific building kind (hospital, hotel, home, …) from the brief."""
    for text in texts:
        if not text:
            continue
        for pattern, kind, _use in _KIND_PATTERNS:
            if re.search(pattern, text.lower()):
                return kind
    return "home"


def _match_use(text: str) -> BuildingUse | None:
    lowered = text.lower()
    if re.search(r"\b(retail|shop|store)\b", lowered) and re.search(
        r"\b(office|apartments?|residential|hotel)\b", lowered
    ):
        return "mixed"
    for pattern, _kind, use in _KIND_PATTERNS:
        if re.search(pattern, lowered):
            return use
    return None


def normalise_use(*texts: str) -> BuildingUse:
    """Pick a packer family. First text that names a building type wins.

    Callers should pass building_use, then name, then prompt, then rooms so a
    'home office' or a cafe listed inside a hospital cannot reclassify the job.
    """
    for text in texts:
        found = _match_use(text or "")
        if found:
            return found
    return "home"


def profile(use: str) -> UseProfile:
    return PROFILES.get(use if use in USES else normalise_use(use), PROFILES["home"])


def kind_entry(kind: str, use: str = "") -> dict[str, Any]:
    """Program library row for a specific building kind, falling back to the packer family."""
    key = (kind or use or "home").strip().lower()
    if key in _KIND_LIBRARY:
        return _KIND_LIBRARY[key]
    active = profile(use or key)
    return _KIND_LIBRARY.get(active.key, _KIND_LIBRARY["home"])


def kind_label(kind: str, use: str = "") -> str:
    return str(kind_entry(kind, use).get("label") or (kind or use or "building").replace("_", " ").title())


# Published design-guide pages consulted when researching a building kind.
# These are not building code; they are the external programming references
# the planner is allowed to cite in chat.
_KIND_EXTERNAL: dict[str, tuple[tuple[str, str, str], ...]] = {
    "hospital": (
        ("Whole Building Design Guide — Hospitals",
         "GSA WBDG building-type guidance for hospital departments and public-to-clinical stacking.",
         "https://www.wbdg.org/building-types/health-care-facilities"),
        ("FGI Guidelines for Design and Construction of Hospitals",
         "Industry baseline for clinical space types. Local code still governs the finished building.",
         "https://www.fgiguidelines.org/"),
    ),
    "clinic": (
        ("Whole Building Design Guide — Health care",
         "Outpatient clinic planning notes: reception, waiting, and exam-room suites.",
         "https://www.wbdg.org/building-types/health-care-facilities"),
        ("FGI Guidelines for Outpatient Facilities",
         "Typical exam and procedure room programs for clinics.",
         "https://www.fgiguidelines.org/"),
    ),
    "hotel": (
        ("Whole Building Design Guide — Hospitality",
         "Lobby, food service, and guest-room stacking for hotels.",
         "https://www.wbdg.org/building-types/hospitality-facilities"),
    ),
    "school": (
        ("Whole Building Design Guide — Education facilities",
         "Classroom-and-corridor plans with shared gym, cafeteria and library.",
         "https://www.wbdg.org/building-types/education-facilities"),
    ),
    "warehouse": (
        ("Whole Building Design Guide — Warehouses",
         "Large storage plates with a thin office and receiving edge.",
         "https://www.wbdg.org/building-types/warehouse"),
    ),
    "restaurant": (
        ("Whole Building Design Guide — Food service",
         "Front-of-house dining versus back-of-house kitchen and stores.",
         "https://www.wbdg.org/building-types/community-services"),
    ),
    "worship": (
        ("Whole Building Design Guide — Religious facilities",
         "Sanctuary or prayer hall with lobby, support rooms and education space.",
         "https://www.wbdg.org/building-types/community-services/religious-facilities"),
    ),
    "gym": (
        ("Whole Building Design Guide — Recreation facilities",
         "Activity floors with lockers, studios and a staff edge.",
         "https://www.wbdg.org/building-types/recreation-facilities"),
    ),
    "library": (
        ("Whole Building Design Guide — Libraries",
         "Public lobby, stacks, reading rooms and staff workrooms.",
         "https://www.wbdg.org/building-types/library"),
    ),
    "apartment": (
        ("Whole Building Design Guide — Housing",
         "Shared cores with typical dwelling units rather than a single house plan.",
         "https://www.wbdg.org/building-types/housing"),
    ),
    "civic": (
        ("Whole Building Design Guide — Community services",
         "Public lobby and a principal gathering room, offices behind.",
         "https://www.wbdg.org/building-types/community-services"),
    ),
    "home": (
        ("Whole Building Design Guide — Residential",
         "Open living-kitchen-dining, short halls, bedrooms clustered.",
         "https://www.wbdg.org/building-types/residential"),
    ),
    "office": (
        ("Whole Building Design Guide — Office buildings",
         "Reception, core, open work and meeting rooms on a corridor.",
         "https://www.wbdg.org/building-types/office-buildings"),
    ),
    "retail": (
        ("Whole Building Design Guide — Retail",
         "Sales floor to the street, stock and staff at the back.",
         "https://www.wbdg.org/building-types/retail"),
    ),
    "mixed": (
        ("Whole Building Design Guide — Mixed use",
         "Public ground floor with quieter uses above, sharing one core.",
         "https://www.wbdg.org/space-types"),
    ),
}


def kind_external(kind: str, use: str = "") -> list[dict[str, Any]]:
    """External programming references for this building kind."""
    key = (kind or use or "home").strip().lower()
    rows = _KIND_EXTERNAL.get(key) or _KIND_EXTERNAL.get(profile(use or key).key) or ()
    return [
        {"title": title, "note": note, "url": url, "origin": "External", "external": True}
        for title, note, url in rows
    ]


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "single": 1, "double": 2,
}


def parse_floor_count(*texts: str, default: int = 2) -> int:
    """Read a storey count from '3', 'three floors', 'G+2', 'two-storey'.

    Bare numbers only count when the whole string is a number, so '10 bedrooms'
    cannot become a 10-storey building.
    """
    for text in texts:
        if not text:
            continue
        stripped = text.strip()
        lowered = stripped.lower()
        ground_plus = re.search(r"\bg\s*\+\s*(\d+)\b", lowered)
        if ground_plus:
            return max(1, min(8, int(ground_plus.group(1)) + 1))
        labeled = re.search(
            r"\b(\d{1,2})\s*[-\s]*(?:storey|story|stories|floors?|levels?)\b",
            lowered,
        )
        if labeled:
            return max(1, min(8, int(labeled.group(1))))
        labeled_words = re.search(
            r"\b(" + "|".join(_NUMBER_WORDS) + r")\s*[-\s]*(?:storey|story|stories|floors?|levels?)\b",
            lowered,
        )
        if labeled_words:
            return max(1, min(8, _NUMBER_WORDS[labeled_words.group(1)]))
        if re.fullmatch(r"\d{1,2}", stripped):
            return max(1, min(8, int(stripped)))
        for word, value in _NUMBER_WORDS.items():
            if re.fullmatch(word, lowered):
                return max(1, min(8, value))
    return default


def parse_area_sqft(*texts: str, default: float = 2400) -> float:
    """Read a gross area in square feet from '2,400 sq ft' or '220 m2'."""
    for text in texts:
        if not text:
            continue
        lowered = text.lower().replace(",", "")
        match = re.search(r"(\d+(?:\.\d+)?)\s*(sq\.?\s*m|square\s*met|m2|m²|sqm)", lowered)
        if match:
            return max(200.0, float(match.group(1)) * SQFT_PER_SQM)
        match = re.search(r"(\d+(?:\.\d+)?)\s*(sq\.?\s*f|square\s*f|sf\b|ft2|ft²|sqft)", lowered)
        if match:
            return max(200.0, float(match.group(1)))
        match = re.search(r"\b(\d{3,6}(?:\.\d+)?)\b", lowered)
        if match:
            return max(200.0, float(match.group(1)))
    return default


def footprint_for(area_sqft: float, floors: int, aspect: float) -> tuple[float, float]:
    """Plate proportions for a target gross area spread over N storeys."""
    plate = max(240.0, float(area_sqft) / max(1, floors))
    depth = math.sqrt(plate / aspect)
    return round(depth * aspect, 2), round(depth, 2)


def typical_area(use: str, category: str, fallback: float = 150.0) -> float:
    return profile(use).typical_areas.get(category, fallback)


def _rule(
    rule_id: str,
    applies_to: str,
    metric: str,
    value: float,
    unit: str,
    text: str,
    scope: str = "room",
    operator: str = ">=",
) -> dict:
    return {
        "rule_id": rule_id,
        "applies_to": applies_to,
        "metric": metric,
        "operator": operator,
        "value": value,
        "unit": unit,
        "source_doc": "Archetype starter requirements",
        "source_page": 1,
        "source_text": text,
        "source_section": "Generated project requirements - not building code",
        "source_label": "Starter requirement",
        "extraction": "generated",
        "status": "approved",
        "scope": scope,
        "target_ids": [],
        "qualifiers": [],
        "supported": True,
    }


# Only metrics compliance.py can actually measure: area, min_side, aperture_width.
_PACKS: dict[str, list[dict]] = {
    "home": [
        _rule("GEN-DOOR-001", "door", "aperture_width", 0.9, "m",
              "Modelled door apertures should be at least 0.90 m wide.", scope="opening"),
        _rule("GEN-BED-001", "bedroom", "area", 7.0, "m2",
              "A bedroom should have at least 7.0 m2 of floor area."),
        _rule("GEN-BED-002", "bedroom", "min_side", 2.1, "m",
              "A bedroom should be at least 2.10 m across its narrow dimension."),
        _rule("GEN-BATH-001", "bathroom", "area", 3.3, "m2",
              "A bathroom should have at least 3.30 m2 of floor area."),
    ],
    "office": [
        _rule("GEN-DOOR-001", "door", "aperture_width", 0.9, "m",
              "Modelled door apertures should be at least 0.90 m wide.", scope="opening"),
        _rule("GEN-CORR-001", "circulation", "min_side", 1.5, "m",
              "A corridor should stay at least 1.50 m wide along its length."),
        _rule("GEN-MEET-001", "meeting", "area", 10.0, "m2",
              "A meeting room should have at least 10.0 m2 of floor area."),
        _rule("GEN-WC-001", "bathroom", "area", 2.5, "m2",
              "A washroom should have at least 2.50 m2 of floor area."),
        _rule("GEN-OFF-001", "office", "area", 8.0, "m2",
              "An enclosed office should have at least 8.0 m2 of floor area."),
    ],
    "retail": [
        _rule("GEN-DOOR-001", "door", "aperture_width", 0.9, "m",
              "Modelled door apertures should be at least 0.90 m wide.", scope="opening"),
        _rule("GEN-SALES-001", "sales", "min_side", 4.0, "m",
              "The sales floor should stay at least 4.00 m across its narrow dimension."),
        _rule("GEN-WC-001", "bathroom", "area", 2.5, "m2",
              "A washroom should have at least 2.50 m2 of floor area."),
        _rule("GEN-STOCK-001", "stock", "area", 12.0, "m2",
              "Stock rooms should have at least 12.0 m2 of floor area."),
    ],
}
_PACKS["mixed"] = _PACKS["office"] + [
    _rule("GEN-LIV-001", "living", "area", 12.0, "m2",
          "A living space should have at least 12.0 m2 of floor area."),
    _rule("GEN-BED-001", "bedroom", "area", 7.0, "m2",
          "A bedroom should have at least 7.0 m2 of floor area."),
]


def rule_pack(use: str, categories: set[str] | None = None) -> list[dict]:
    """Starter requirements, filtered to what this building actually contains.

    Shipping a rule with nothing to measure produces a permanent
    ``cannot_verify`` row, which reads as a defect rather than a requirement.
    """
    rules = [dict(rule) for rule in _PACKS.get(profile(use).key, _PACKS["home"])]
    if categories is None:
        return rules
    kept = []
    for rule in rules:
        pattern = rule["applies_to"].lower()
        # Match exactly how compliance.matches_room will, or the rule can never fire.
        if rule["scope"] == "opening" or pattern == "*":
            kept.append(rule)
        elif any(fnmatch.fnmatchcase(category.lower(), pattern) for category in categories):
            kept.append(rule)
    return kept


def defaults_digest(use: str, kind: str = "") -> str:
    """Compact reference injected into the prompt instead of a tool round trip."""
    active = profile(use)
    kind = (kind or use).strip().lower() or active.key
    typical = _KIND_AREAS.get(kind, active.typical_areas)
    areas = ", ".join(f"{name} ~{area:g} sqft" for name, area in typical.items())
    scheme = layout_scheme(kind, use)
    lines = [
        f"Building kind: {kind}. Layout scheme: {scheme}. Packer family: {active.label} ({active.key}).",
        "Honour the architect's brief. The packer family only chooses corridor width and storey height.",
        f"Typical storey height {active.floor_height_ft:g} ft.",
        f"Typical areas for this kind: {areas}.",
    ]
    lines.extend(f"- {tip}" for tip in layout_notes(kind, use))
    lines.extend(f"- {tip}" for tip in _KIND_GUIDANCE.get(kind, active.guidance))
    packs = rule_pack(active.key)
    lines.append("Requirements that will be measured on the result:")
    lines.extend(
        f"- {rule['applies_to']}: {rule['metric']} {rule['operator']} {rule['value']:g} {rule['unit']}"
        for rule in packs
    )
    return "\n".join(lines)
