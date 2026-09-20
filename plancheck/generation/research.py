"""Host-side research for one generation job.

The model is still asked once for a space program. Before that call, this module
reads the brief, names the building kind, consults the internal program library,
and gathers the rooms that kind of building actually needs. Those findings are
shown in the home-screen chat and injected into the planner prompt.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from plancheck.core.building import DesignBrief
from plancheck.generation import defaults

_SPLIT = re.compile(r"[,;/]|\band\b", re.I)
_COUNT_PREFIX = re.compile(
    r"^\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+",
    re.I,
)
_COUNT_ITEM = re.compile(
    r"^\s*(?P<n>\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
    r"(?P<name>.+?)\s*$",
    re.I,
)
_SKIP_COUNTS = re.compile(
    r"\b(floor|floors|storey|storeys|story|stories|level|levels|sq|sqft|ft|m2|metre|meter)\b",
    re.I,
)
_PAREN_ROOMS = re.compile(r"^(?P<head>.*?)\(\s*(?P<n>\d+)\s*rooms?\s*\)\s*$", re.I)
_GROUP_WORD = re.compile(r"\bgroups?\b", re.I)
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_CATEGORY_ALIASES = {
    "classroom": "classroom", "classrooms": "classroom", "class": "classroom",
    "bedroom": "bedroom", "bedrooms": "bedroom",
    "bathroom": "bathroom", "bathrooms": "bathroom", "washroom": "bathroom",
    "washrooms": "bathroom", "restroom": "bathroom", "restrooms": "bathroom",
    "office": "office", "offices": "office",
    "meeting": "meeting", "meeting_room": "meeting", "meeting_rooms": "meeting",
    "guest_room": "guest_room", "guest_rooms": "guest_room",
    "ward": "ward", "wards": "ward",
    "exam": "exam", "exam_room": "exam", "exam_rooms": "exam",
    "or": "or", "operating_theatre": "or", "operating_theatres": "or",
    "operating_theater": "or", "theatre": "or", "theatres": "or",
    "lab": "lab", "labs": "lab", "laboratory": "lab",
    "studio": "studio", "studios": "studio",
}
_KIND_GENERIC_ROOM = {
    "school": "classroom",
    "home": "bedroom",
    "apartment": "bedroom",
    "hotel": "guest_room",
    "clinic": "exam",
    "office": "office",
}
MAX_REPEAT = 16
_NOISE = {
    "a", "an", "the", "with", "plus", "including", "and", "or", "of", "to",
    "some", "few", "several", "space", "spaces", "room", "rooms",
}


@dataclass
class RoomCandidate:
    category: str
    name: str
    typical_area_sqft: float
    why: str
    floor: str = "any"
    from_brief: bool = False
    count: int = 1

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "category": self.category,
            "name": self.name,
            "typical_area_sqft": round(self.typical_area_sqft),
            "why": self.why,
            "floor": self.floor,
        }
        if self.count > 1:
            payload["count"] = self.count
        if self.from_brief:
            payload["from_brief"] = True
        return payload


@dataclass
class KnowledgeSource:
    title: str
    note: str
    origin: str = "Archetype program library"
    url: str = ""
    external: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": self.title,
            "note": self.note,
            "origin": self.origin,
            "external": self.external,
        }
        if self.url:
            payload["url"] = self.url
        return payload


@dataclass
class ResearchDossier:
    kind: str
    label: str
    packer_family: str
    storeys: int
    gross_area_sqft: float
    blurb: str
    thinking: list[str] = field(default_factory=list)
    sources: list[KnowledgeSource] = field(default_factory=list)
    rooms: list[RoomCandidate] = field(default_factory=list)
    named_from_brief: list[str] = field(default_factory=list)
    guidance: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        """Compact research object the planner model reads."""
        return {
            "kind": self.kind,
            "label": self.label,
            "blurb": self.blurb,
            "packer_family": self.packer_family,
            "layout_scheme": defaults.layout_scheme(self.kind, self.packer_family),
            "storeys": self.storeys,
            "gross_area_sqft": round(self.gross_area_sqft),
            "why_this_kind": self.thinking,
            "architect_named_rooms": self.named_from_brief,
            "required_room_counts": [
                {"category": room.category, "name": room.name, "count": room.count}
                for room in self.rooms
                if room.count > 1
            ],
            "recommended_rooms": [room.as_dict() for room in self.rooms],
            "planning_notes": self.guidance,
            "sources": [source.as_dict() for source in self.sources],
            "reference": defaults.defaults_digest(self.packer_family, self.kind),
        }

    def recap(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "blurb": self.blurb,
            "thinking": self.thinking,
            "sources": [source.as_dict() for source in self.sources],
            "rooms": [room.as_dict() for room in self.rooms],
            "named_from_brief": self.named_from_brief,
        }

    def trace(self) -> list[dict[str, Any]]:
        """Job events the home-screen chat renders, in order."""
        named = ", ".join(self.named_from_brief[:8]) or "the rooms in the brief"
        thoughts = [item for item in self.thinking if str(item).strip()] or [
            f"Reading the brief for a {self.label.lower()}."
        ]
        events: list[dict[str, Any]] = [
            {
                "phase": "analyzing",
                "progress": round(0.04 + index * 0.02, 2),
                "kind": "thinking",
                "label": "Thinking",
                "message": thought,
            }
            for index, thought in enumerate(thoughts)
        ]
        events.extend(
            [
                {
                    "phase": "researching",
                    "progress": 0.18,
                    "kind": "research",
                    "label": "Researching",
                    "message": f"Consulting the {self.label.lower()} program library and published design guides.",
                },
                {
                    "phase": "researching",
                    "progress": 0.24,
                    "kind": "source",
                    "label": "Finding sources",
                    "message": (
                        f"Found {len(self.sources)} sources for a {self.label.lower()}"
                        + (
                            f", including {sum(1 for source in self.sources if source.external)} external"
                            if any(source.external for source in self.sources)
                            else ""
                        )
                        + "."
                    ),
                    "sources": [source.as_dict() for source in self.sources],
                },
                {
                    "phase": "planning",
                    "progress": 0.32,
                    "kind": "rooms",
                    "label": "Gathering rooms",
                    "message": (
                        f"Gathering the rooms a {self.label.lower()} needs, "
                        f"then matching them to {named}."
                    ),
                    "rooms": [room.as_dict() for room in self.rooms],
                },
            ]
        )
        return events


def named_from_brief(*texts: str) -> list[str]:
    """Pull room names the architect actually wrote, not the whole sentence."""
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        for part in _SPLIT.split(text):
            name = _COUNT_PREFIX.sub("", part).strip(" .")
            name = re.sub(r"^(?:a|an|the)\s+", "", name, flags=re.I)
            name = re.sub(r"\s+", " ", name)
            if not name or len(name) > 40:
                continue
            key = name.lower()
            if key in _NOISE or key in seen:
                continue
            if not re.search(r"[a-zA-Z]", name):
                continue
            seen.add(key)
            found.append(name)
    return found[:24]


def _parse_count_token(token: str) -> int | None:
    key = token.strip().lower()
    if key.isdigit():
        return int(key)
    return _WORD_NUMBERS.get(key)


def _count_category(name: str, kind: str = "") -> str | None:
    slug = _slug_category(name)
    slug = re.sub(r"^(?:a|an|the)_", "", slug)
    if slug in {"room", "rooms"}:
        return _KIND_GENERIC_ROOM.get((kind or "").strip().lower())
    if slug in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[slug]
    for alias, category in _CATEGORY_ALIASES.items():
        if slug.endswith("_" + alias) or slug.startswith(alias + "_"):
            return category
    return None


def counts_from_brief(*texts: str, kind: str = "") -> dict[str, int]:
    """Read '8 classrooms' / 'ten bedrooms' as required instance counts."""
    found: dict[str, int] = {}
    for text in texts:
        if not text:
            continue
        for part in _SPLIT.split(text):
            match = _COUNT_ITEM.match(part.strip(" ."))
            if match is None or _SKIP_COUNTS.search(match.group("name")):
                continue
            count = _parse_count_token(match.group("n"))
            category = _count_category(match.group("name"), kind)
            if count is None or count < 2 or category is None:
                continue
            found[category] = max(found.get(category, 0), min(MAX_REPEAT, count))
    return found


def _clean_room_name(head: str, index: int, total: int) -> str:
    base = _GROUP_WORD.sub("", head)
    base = re.sub(r"\b[a-z]\b", "", base, flags=re.I)
    base = re.sub(r"\s+", " ", base).strip(" -")
    if base.lower().endswith("s") and not base.lower().endswith(("ss", "us", "is")):
        base = base[:-1]
    base = base or "Room"
    return f"{base} {index}" if total > 1 else base


def expand_repeated_spaces(program: Any, counts: dict[str, int] | None = None) -> Any:
    """Turn grouped blobs and brief counts into one space per room."""
    from plancheck.generation.program import BuildingProgram, slug_id

    if not isinstance(program, BuildingProgram):
        return program
    counts = dict(counts or {})
    used = {space.id for space in program.spaces}
    expanded: list[Any] = []

    def unique(base: str) -> str:
        cid = slug_id(base, "room")
        n = 2
        while cid in used:
            cid = slug_id(f"{base}_{n}", "room")
            n += 1
        used.add(cid)
        return cid

    for space in program.spaces:
        if space.stair or space.circulation:
            expanded.append(space)
            continue
        match = _PAREN_ROOMS.match(space.name.strip())
        copies = 1
        head = space.name
        if match:
            copies = min(MAX_REPEAT, max(2, int(match.group("n"))))
            head = match.group("head").strip()
        elif _GROUP_WORD.search(space.name):
            copies = 2
        if copies <= 1:
            expanded.append(space)
            continue
        used.discard(space.id)
        area = max(20.0, space.target_area_sqft / copies)
        for index in range(1, copies + 1):
            expanded.append(
                space.model_copy(
                    update={
                        "id": unique(f"{space.category}_{index}"),
                        "name": _clean_room_name(head, index, copies)[:80],
                        "target_area_sqft": area,
                        "adjacent_to": [],
                    }
                )
            )

    by_category: dict[str, list[Any]] = {}
    for space in expanded:
        by_category.setdefault(space.category, []).append(space)
    extra: list[Any] = []
    for category, need in counts.items():
        have = by_category.get(category) or []
        if not have or len(have) >= need:
            continue
        template = have[0]
        total = sum(s.target_area_sqft for s in have)
        each = max(20.0, total / need)
        label = category.replace("_", " ").title()
        for index, space in enumerate(have, start=1):
            space.target_area_sqft = each
            space.name = f"{label} {index}"[:80]
        for index in range(len(have) + 1, need + 1):
            extra.append(
                template.model_copy(
                    update={
                        "id": unique(f"{category}_{index}"),
                        "name": f"{label} {index}"[:80],
                        "target_area_sqft": each,
                        "adjacent_to": [],
                    }
                )
            )
    if extra:
        expanded.extend(extra)
    labels: dict[str, int] = {}
    for space in expanded:
        if space.stair or space.circulation:
            continue
        labels[space.category] = labels.get(space.category, 0) + 1
    seen: dict[str, int] = {}
    for space in expanded:
        if labels.get(space.category, 0) < 2 or space.stair or space.circulation:
            continue
        seen[space.category] = seen.get(space.category, 0) + 1
        space.name = f"{space.category.replace('_', ' ').title()} {seen[space.category]}"[:80]
    return program.model_copy(update={"spaces": expanded})


def _slug_category(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "space"


def _typical_area(kind: str, use: str, category: str) -> float:
    active = defaults.profile(use)
    table = defaults._KIND_AREAS.get(kind, active.typical_areas)
    if category in table:
        return table[category]
    for key, area in table.items():
        if key in category or category in key:
            return area
    return active.typical_areas.get(category, 160.0)


def _library_rooms(kind: str, use: str, storeys: int) -> list[RoomCandidate]:
    entry = defaults.kind_entry(kind, use)
    areas = defaults._KIND_AREAS.get(kind, defaults.profile(use).typical_areas)
    rooms: list[RoomCandidate] = []
    for category, name, floor, why in entry.get("rooms") or ():
        if floor == "upper" and storeys < 2:
            floor = "entry"
        rooms.append(
            RoomCandidate(
                category=str(category),
                name=str(name),
                typical_area_sqft=float(areas.get(category, _typical_area(kind, use, str(category)))),
                why=str(why),
                floor=str(floor),
            )
        )
    return rooms


def _merge_named(rooms: list[RoomCandidate], named: list[str], kind: str, use: str) -> list[RoomCandidate]:
    """Keep library rooms and add anything the architect named that isn't already there."""
    index = {room.category: room for room in rooms}
    also = {_slug_category(room.name): room for room in rooms}
    for raw in named:
        category = _slug_category(raw)
        match = index.get(category) or also.get(category)
        if match is None:
            for room in rooms:
                if room.category in category or category in room.category or room.name.lower() in raw.lower():
                    match = room
                    break
        if match is not None:
            match.from_brief = True
            continue
        rooms.append(
            RoomCandidate(
                category=category,
                name=raw[:1].upper() + raw[1:],
                typical_area_sqft=_typical_area(kind, use, category),
                why="Named in the architect's brief, so it must appear in the program.",
                floor="any",
                from_brief=True,
            )
        )
    return rooms


def _wikipedia_hits(label: str, timeout: float = 2.5) -> list[KnowledgeSource]:
    """Optional live lookup. Failures are ignored so generation still finishes."""
    query = f"{label} building architecture"
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 2,
            "format": "json",
            "utf8": 1,
        }
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Archetype/0.2 (local building design tool)"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.5, timeout)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return []
    hits: list[KnowledgeSource] = []
    for item in (payload.get("query") or {}).get("search") or []:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        snippet = re.sub(r"<[^>]+>", "", str(item.get("snippet") or ""))
        snippet = re.sub(r"\s+", " ", snippet).strip()
        hits.append(
            KnowledgeSource(
                title=f"Wikipedia — {title}",
                note=snippet or f"Background on {title}.",
                origin="Wikipedia",
                url="https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                external=True,
            )
        )
    return hits[:2]


def explore(
    brief: DesignBrief,
    use: str,
    kind: str,
    storeys: int,
    area_sqft: float,
    live: bool = False,
) -> ResearchDossier:
    """Name the building, consult internal and external knowledge, gather rooms."""
    kind = (kind or use or "home").strip().lower()
    entry = defaults.kind_entry(kind, use)
    active = defaults.profile(use)
    label = defaults.kind_label(kind, use)
    named = named_from_brief(brief.rooms, brief.prompt)
    counts = counts_from_brief(brief.rooms, brief.prompt, kind=kind)
    rooms = _merge_named(_library_rooms(kind, use, storeys), named, kind, use)
    for category, count in counts.items():
        match = next((room for room in rooms if room.category == category), None)
        if match is None:
            rooms.append(
                RoomCandidate(
                    category=category,
                    name=category.replace("_", " ").title(),
                    typical_area_sqft=_typical_area(kind, use, category),
                    why=f"The brief asks for {count} separate {category.replace('_', ' ')}s, not one grouped rectangle.",
                    floor="any",
                    from_brief=True,
                    count=count,
                )
            )
        else:
            match.from_brief = True
            match.count = count
            match.why = f"The brief asks for {count} separate {match.name.lower()}s, not one grouped rectangle."

    # Circulation and a stacked stair are always required by the packer.
    categories = {room.category for room in rooms}
    if "circulation" not in categories and "lobby" not in categories:
        rooms.append(
            RoomCandidate(
                category="circulation",
                name="Circulation",
                typical_area_sqft=float(active.typical_areas.get("circulation", 200)),
                why="Every storey needs a corridor, hall or lobby the other rooms open onto.",
                floor="every",
            )
        )
    if storeys > 1 and "stair" not in categories:
        rooms.append(
            RoomCandidate(
                category="stair",
                name="Stair",
                typical_area_sqft=float(active.typical_areas.get("stair", 120)),
                why="Each storey needs a stair of the same size so the core stacks.",
                floor="every",
            )
        )

    source_title, source_note = entry.get("source") or (
        f"Archetype {label.lower()} program library",
        f"Typical rooms, areas and stacking for a {label.lower()}.",
    )
    sources = [
        KnowledgeSource(title=str(source_title), note=str(source_note)),
        KnowledgeSource(
            title="Your design brief",
            note=(
                f"{brief.name or 'Untitled'}: {storeys} storey"
                f"{'s' if storeys != 1 else ''}, about {round(area_sqft):,} sq ft"
                + (f". Named rooms: {', '.join(named[:8])}" if named else ".")
            ),
            origin="Project brief",
        ),
        KnowledgeSource(
            title="Starter requirements",
            note="Door widths, minimum room sizes and corridor widths that will be measured on the result.",
            origin="Archetype starter requirements",
        ),
    ]
    for row in defaults.kind_external(kind, use):
        sources.append(
            KnowledgeSource(
                title=str(row["title"]),
                note=str(row["note"]),
                origin=str(row.get("origin") or "External"),
                url=str(row.get("url") or ""),
                external=True,
            )
        )
    if live:
        seen = {source.url for source in sources if source.url}
        for hit in _wikipedia_hits(label):
            if hit.url and hit.url in seen:
                continue
            sources.append(hit)
            if hit.url:
                seen.add(hit.url)

    article = "an" if label[:1].lower() in "aeiou" else "a"
    thinking = [
        f"Reading the brief for {brief.name or 'this project'} — it reads as {article} {label.lower()}, not a generic floor plate.",
        str(entry.get("blurb") or f"Plan this as {article} {label.lower()} using the {active.label.lower()} packer family."),
    ]
    if named:
        thinking.append(
            f"The brief names {', '.join(named[:6])}"
            + (f" and {len(named) - 6} more" if len(named) > 6 else "")
            + ". Those rooms stay; typical rooms fill the gaps."
        )
    if counts:
        bits = [f"{n} {category.replace('_', ' ')}s" for category, n in counts.items()]
        thinking.append(
            "Those counts are separate rooms on the plan — "
            + ", ".join(bits)
            + " — not grouped blobs."
        )
    guidance = list(defaults._KIND_GUIDANCE.get(kind, active.guidance))
    guidance.extend(defaults.layout_notes(kind, use))
    guidance.append("The architect's brief always wins over the typical room list.")
    guidance.append(
        f"Layout scheme is {defaults.layout_scheme(kind, use)}; packer family {active.label.lower()} "
        f"only sets storey height ({active.floor_height_ft:g} ft)."
    )

    return ResearchDossier(
        kind=kind,
        label=label,
        packer_family=use,
        storeys=storeys,
        gross_area_sqft=area_sqft,
        blurb=str(entry.get("blurb") or ""),
        thinking=thinking,
        sources=sources,
        rooms=rooms,
        named_from_brief=named,
        guidance=guidance,
    )
