"""Generation agent: geometry, packing, and the two-call budget. No network."""

import json
import time

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from plancheck.api.main import app
from plancheck.core.building import DesignBrief
from plancheck.core.settings import reset_settings
from plancheck.generation import GenerationError, generate_from_brief
from plancheck.generation.compiler import CompileError, compile_building
from plancheck.generation.defaults import (
    detect_kind,
    normalise_use,
    parse_area_sqft,
    parse_floor_count,
    rule_pack,
)
from plancheck.generation.research import explore, named_from_brief, _wikipedia_hits, counts_from_brief, expand_repeated_spaces
from plancheck.generation.prompts import build_messages
from plancheck.generation.layout import LayoutError, pack_floors
from plancheck.generation.program import BuildingProgram, FloorLayout
from plancheck.mocks.generation import demo_home, demo_rules
from plancheck.services.commands import CommandError, apply_commands, validate_building
from plancheck.services.compliance import check_building
from plancheck.services.repairs import propose_repairs


def space(sid, floor, category, area, **extra):
    return {
        "id": sid,
        "name": sid.replace("_", " ").title(),
        "floor_id": floor,
        "category": category,
        "target_area_sqft": area,
        **extra,
    }


HOME = {
    "building_use": "home",
    "storeys": [
        {"id": "ground", "name": "Ground floor", "height_ft": 10},
        {"id": "upper", "name": "First floor", "height_ft": 10},
    ],
    "spaces": [
        space("stair_g", "ground", "stair", 90),
        space("hall", "ground", "circulation", 140, entry=True),
        space("living", "ground", "living", 320, min_side_ft=12),
        space("kitchen", "ground", "kitchen", 200),
        space("dining", "ground", "dining", 180),
        space("wc", "ground", "bathroom", 50),
        space("stair_u", "upper", "stair", 90),
        space("landing", "upper", "circulation", 120),
        space("bed_1", "upper", "bedroom", 260, min_side_ft=11),
        space("bed_2", "upper", "bedroom", 180, min_side_ft=10),
        space("bed_3", "upper", "bedroom", 170, min_side_ft=10),
        space("bath", "upper", "bathroom", 70),
    ],
}
OFFICE = {
    "building_use": "office",
    "storeys": [{"id": "l1", "name": "Ground floor"}, {"id": "l2", "name": "Level 2"}],
    "spaces": [
        space("core_1", "l1", "stair", 130),
        space("lobby", "l1", "circulation", 320, entry=True),
        space("reception", "l1", "reception", 300),
        space("work_1", "l1", "open_office", 1400),
        space("wc_1", "l1", "bathroom", 120),
        space("core_2", "l2", "stair", 130),
        space("corridor", "l2", "circulation", 300),
        space("meet_a", "l2", "meeting", 260),
        space("meet_b", "l2", "meeting", 240),
        space("work_2", "l2", "open_office", 1300),
        space("wc_2", "l2", "bathroom", 120),
    ],
}
RETAIL = {
    "building_use": "retail",
    "storeys": [{"id": "ground", "name": "Ground floor", "height_ft": 13}],
    "spaces": [
        space("sales", "ground", "sales", 2400, min_side_ft=20, entry=True),
        space("back", "ground", "circulation", 180),
        space("stock", "ground", "stock", 500),
        space("wc", "ground", "bathroom", 90),
        space("manager", "ground", "office", 140),
    ],
}
MIXED = {
    "building_use": "mixed",
    "storeys": [
        {"id": "ground", "name": "Ground floor", "height_ft": 13},
        {"id": "l2", "name": "Level 2"},
        {"id": "l3", "name": "Level 3"},
    ],
    "spaces": [
        space("core_g", "ground", "stair", 130),
        space("lobby", "ground", "lobby", 420, circulation=True, entry=True),
        space("shop", "ground", "retail", 1400, min_side_ft=18),
        space("core_2", "l2", "stair", 130),
        space("corr_2", "l2", "circulation", 300),
        space("work", "l2", "open_office", 1400),
        space("meet", "l2", "meeting", 240),
        space("core_3", "l3", "stair", 130),
        space("corr_3", "l3", "circulation", 300),
        space("living", "l3", "living", 300),
        space("bed", "l3", "bedroom", 180),
        space("kitchen", "l3", "kitchen", 140),
        space("bath", "l3", "bathroom", 110),
    ],
}
ALL_PROGRAMS = {"home": HOME, "office": OFFICE, "retail": RETAIL, "mixed": MIXED}


def build(raw, area=None):
    program = BuildingProgram.model_validate(raw)
    layouts = pack_floors(program, area)
    return program, layouts, compile_building(program, layouts)


# --- brief parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [("Home", "home"), ("a small dental clinic", "office"), ("corner shop", "retail"),
     ("retail below apartments", "mixed"), ("", "home"),
     ("Hospital", "office"), ("hotel", "mixed"), ("warehouse", "retail")],
)
def test_use_is_read_from_free_text(text, expected):
    assert normalise_use(text) == expected


def test_hospital_is_not_classified_as_retail_because_it_has_a_cafe():
    assert normalise_use(
        "Hospital",
        "Hospital",
        "",
        "lobby, cafe, shared bedrooms, private rooms",
    ) == "office"
    assert detect_kind("Hospital", "Hospital") == "hospital"


def test_mosque_and_restaurant_keep_their_own_kinds():
    assert detect_kind("Mosque") == "worship"
    assert normalise_use("Mosque") == "mixed"
    assert detect_kind("neighborhood restaurant") == "restaurant"
    assert normalise_use("neighborhood restaurant") == "retail"


def test_named_rooms_are_pulled_out_of_the_brief():
    assert "studio" in named_from_brief("3 bedrooms, 2 bathrooms, kitchen and a studio")
    assert counts_from_brief("3 bedrooms, 2 bathrooms, kitchen and a studio") == {
        "bedroom": 3,
        "bathroom": 2,
    }
    dossier = explore(
        DesignBrief(name="Willow", building_use="Home", rooms="kitchen, living room", style="Warm minimal"),
        "home",
        "home",
        2,
        2400,
    )
    assert "warm_minimal" not in {room.category for room in dossier.rooms}


def test_school_classroom_counts_are_separate_rooms():
    assert counts_from_brief("8 classrooms and a gym", kind="school") == {"classroom": 8}
    assert counts_from_brief("8 rooms", kind="school") == {"classroom": 8}
    dossier = explore(
        DesignBrief(name="Riverside School", building_use="School", rooms="8 classrooms"),
        "office",
        "school",
        2,
        20000,
    )
    classroom = next(room for room in dossier.rooms if room.category == "classroom")
    assert classroom.count == 8
    assert classroom.from_brief
    payload = dossier.payload()
    assert payload["required_room_counts"][0]["count"] == 8


def test_grouped_classroom_blob_is_exploded_into_real_rooms():
    program = BuildingProgram.model_validate(
        {
            "building_use": "office",
            "storeys": [{"id": "ground", "name": "Ground"}],
            "spaces": [
                space("group_a", "ground", "classroom", 1600, name="Classrooms Group A (2 rooms)"),
                space("group_b", "ground", "classroom", 1600, name="Classrooms Group B (2 rooms)"),
                space("corr", "ground", "circulation", 220, entry=True),
            ],
        }
    )
    expanded = expand_repeated_spaces(program, {"classroom": 4})
    classrooms = [s for s in expanded.spaces if s.category == "classroom"]
    assert len(classrooms) == 4
    assert not any("group" in s.name.lower() for s in classrooms)
    layouts = pack_floors(expanded, kind="school")
    assert {r.space_id for r in layouts["ground"].rooms} == {s.id for s in expanded.spaces}


def test_research_explores_a_hospital_and_keeps_brief_rooms():
    dossier = explore(
        DesignBrief(
            name="Riverside Hospital",
            building_use="Hospital",
            rooms="wards, cafe, four operating theatres",
            area="80,000 sq ft",
            floors="5",
        ),
        "office",
        "hospital",
        5,
        80000,
    )
    assert dossier.kind == "hospital"
    assert dossier.label == "Hospital"
    categories = {room.category for room in dossier.rooms}
    assert "ward" in categories
    assert "or" in categories
    assert any(room.from_brief for room in dossier.rooms)
    titles = {source.title for source in dossier.sources}
    assert any("hospital" in title.lower() for title in titles)
    assert any("brief" in title.lower() for title in titles)
    external = [source for source in dossier.sources if source.external]
    assert external
    assert all(source.url.startswith("http") for source in external)
    assert any("wbdg.org" in source.url for source in external)
    kinds = [event["kind"] for event in dossier.trace()]
    assert kinds[0] == "thinking"
    assert kinds[-3:] == ["research", "source", "rooms"]
    assert [event["message"] for event in dossier.trace() if event["kind"] == "thinking"] == dossier.thinking
    assert dossier.trace()[-1]["rooms"]


def test_wikipedia_hits_are_cited_as_external_sources(monkeypatch):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "query": {
                        "search": [
                            {"title": "Hospital", "snippet": "A <span>health</span> care institution."},
                        ]
                    }
                }
            ).encode()

    monkeypatch.setattr("plancheck.generation.research.urllib.request.urlopen", lambda *a, **k: _Resp())
    hits = _wikipedia_hits("Hospital")
    assert hits[0].external
    assert hits[0].url.endswith("Hospital")
    assert "health care institution" in hits[0].note


def test_planner_prompt_is_given_the_research_dossier():
    brief = DesignBrief(name="Riverside Hospital", building_use="Hospital", rooms="wards, cafe")
    dossier = explore(brief, "office", "hospital", 5, 80000)
    messages = build_messages(brief, "office", 5, 80000, kind="hospital", research=dossier.payload())
    assert "RESEARCH" in messages[0]["content"]
    user = messages[-1]["content"]
    assert '"kind": "hospital"' in user
    assert "recommended_rooms" in user
    assert "layout_scheme" in user
    assert "ward" in user.lower()
    assert "Archetype hospital program library" in user
    assert "wbdg.org" in user


def test_home_office_does_not_turn_a_house_into_an_office():
    assert normalise_use(
        "Home",
        "House",
        "",
        "10 bedrooms, kitchen, living room, home office",
    ) == "home"


@pytest.mark.parametrize("text,expected", [("2", 2), ("three floors", 3), ("G+2", 3), ("", 2)])
def test_floor_count_parsing(text, expected):
    assert parse_floor_count(text) == expected


def test_floor_count_ignores_bedroom_counts():
    assert parse_floor_count("10 bedrooms, 2 bathrooms") == 2
    assert parse_floor_count("5", "10 bedrooms") == 5
    assert parse_floor_count("Build a 5 story hospital") == 5


def test_area_parsing_handles_both_unit_systems():
    assert parse_area_sqft("2,400 sq ft") == 2400
    assert round(parse_area_sqft("220 m2")) == 2368
    assert parse_area_sqft("no number here", default=1234) == 1234


# --- packer -----------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(ALL_PROGRAMS))
def test_packer_tiles_every_storey_without_overlap(name):
    program = BuildingProgram.model_validate(ALL_PROGRAMS[name])
    layouts = pack_floors(program)
    for storey in program.storeys:
        layout = layouts[storey.id]
        expected = {s.id for s in program.floor_spaces(storey.id)}
        assert {r.space_id for r in layout.rooms} == expected
        # FloorLayout rejects overlaps, so equal areas means the plate is covered.
        assert sum(r.area_sqft for r in layout.rooms) == pytest.approx(
            layout.width_ft * layout.depth_ft, rel=1e-6
        )


@pytest.mark.parametrize("name", ["home", "office", "mixed"])
def test_stair_stacks_on_the_same_footprint(name):
    program = BuildingProgram.model_validate(ALL_PROGRAMS[name])
    layouts = pack_floors(program)
    stairs = {s.id for s in program.spaces if s.stair}
    placed = [
        (r.x1, r.y1, r.x2, r.y2)
        for layout in layouts.values()
        for r in layout.rooms
        if r.space_id in stairs
    ]
    assert len(placed) == len(program.storeys)
    assert len(set(placed)) == 1


def test_every_floor_shares_one_plate():
    program = BuildingProgram.model_validate(MIXED)
    sizes = {(l.width_ft, l.depth_ft) for l in pack_floors(program).values()}
    assert len(sizes) == 1


def test_plate_follows_the_requested_gross_area():
    program = BuildingProgram.model_validate(HOME)
    layout = pack_floors(program, 2400)["ground"]
    assert layout.width_ft * layout.depth_ft == pytest.approx(1200, rel=0.05)


def test_packer_refuses_an_impossible_plate():
    program = BuildingProgram.model_validate(
        {
            "building_use": "office",
            "storeys": [{"id": "g", "name": "G"}],
            "spaces": [space(f"r{i}", "g", "office", 20) for i in range(40)],
        }
    )
    with pytest.raises(LayoutError):
        pack_floors(program)


def test_home_hall_is_a_compact_foyer_not_a_full_width_corridor():
    layout = pack_floors(BuildingProgram.model_validate(HOME), kind="home")["ground"]
    hall = next(r for r in layout.rooms if r.space_id == "hall")
    living = next(r for r in layout.rooms if r.space_id == "living")
    assert hall.width_ft < layout.width_ft * 0.55
    assert living.area_sqft > hall.area_sqft
    assert hall.x2 <= living.x1 + 1e-6 or hall.y2 <= living.y1 + 1e-6 or living.y2 <= hall.y1 + 1e-6


def test_retail_sales_is_not_cut_by_a_hallway():
    layout = pack_floors(BuildingProgram.model_validate(RETAIL), kind="retail")["ground"]
    sales = next(r for r in layout.rooms if r.space_id == "sales")
    corridor = next(r for r in layout.rooms if r.space_id == "back")
    plate = layout.width_ft * layout.depth_ft
    assert sales.area_sqft > 0.4 * plate
    assert corridor.y1 > layout.depth_ft * 0.35 or corridor.width_ft < layout.width_ft * 0.55


def test_office_still_uses_a_double_loaded_corridor():
    layout = pack_floors(BuildingProgram.model_validate(OFFICE), kind="office")["l2"]
    corridor = next(r for r in layout.rooms if r.space_id == "corridor")
    assert corridor.width_ft == pytest.approx(layout.width_ft)


def test_worship_gives_the_sanctuary_the_plate():
    program = BuildingProgram.model_validate(
        {
            "building_use": "mixed",
            "storeys": [{"id": "ground", "name": "Ground floor"}],
            "spaces": [
                space("lobby", "ground", "circulation", 280, entry=True),
                space("sanctuary", "ground", "sanctuary", 2400, min_side_ft=24),
                space("office", "ground", "office", 160),
                space("ablution", "ground", "bathroom", 120),
                space("store", "ground", "storage", 140),
            ],
        }
    )
    layout = pack_floors(program, kind="worship")["ground"]
    sanctuary = next(r for r in layout.rooms if r.space_id == "sanctuary")
    lobby = next(r for r in layout.rooms if r.space_id == "lobby")
    assert sanctuary.area_sqft > 0.45 * layout.width_ft * layout.depth_ft
    assert lobby.width_ft < layout.width_ft or lobby.y1 > 0


def test_layout_scheme_matches_building_kind():
    from plancheck.generation.layout import scheme_for

    assert scheme_for("home", "home") == "cluster"
    assert scheme_for("hospital", "office") == "corridor"
    assert scheme_for("retail", "retail") == "edge"
    assert scheme_for("worship", "mixed") == "hall"


# --- compiler ---------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(ALL_PROGRAMS))
def test_compiled_geometry_is_valid_and_uniquely_identified(name):
    program, layouts, building = build(ALL_PROGRAMS[name])
    validate_building(building)
    ids = [e.id for group in
           (building.floors, building.vertices, building.walls, building.rooms,
            building.openings, building.objects)
           for e in group]
    assert len(ids) == len(set(ids))
    assert len(building.floors) == len(program.storeys)
    assert len(building.rooms) == len(program.spaces)


def test_envelope_is_locked_and_partitions_are_not():
    _, _, building = build(HOME)
    envelope = [w for w in building.walls if w.locked]
    partitions = [w for w in building.walls if not w.locked]
    assert envelope and partitions
    assert all(w.structural == "loadbearing" for w in envelope)
    assert all(w.structural == "nonstructural" for w in partitions)
    assert all(w.thickness_ft > partitions[0].thickness_ft for w in envelope)


def test_partitions_stay_editable_by_the_agent_and_the_envelope_does_not():
    _, _, building = build(HOME)
    partition = next(w for w in building.walls if not w.locked)
    moved = apply_commands(
        building,
        [{"kind": "offset_partition", "target_id": partition.id, "params": {"distance_ft": 0.5}}],
        actor="agent",
    )
    assert moved is not building
    locked = next(w for w in building.walls if w.locked)
    with pytest.raises(CommandError):
        apply_commands(
            building,
            [{"kind": "offset_partition", "target_id": locked.id, "params": {"distance_ft": 0.5}}],
            actor="agent",
        )


def test_walls_are_shared_between_neighbouring_rooms():
    _, _, building = build(HOME)
    ground = [r for r in building.rooms if r.floor_id == "ground"]
    shared = [
        wall_id
        for wall_id in {w.id for w in building.walls if w.floor_id == "ground"}
        if sum(wall_id in room.wall_ids for room in ground) == 2
    ]
    assert shared, "adjacent rooms must reference one wall, not two coincident ones"


@pytest.mark.parametrize("name", sorted(ALL_PROGRAMS))
def test_every_room_is_reachable_and_openings_fit_their_walls(name):
    _, _, building = build(ALL_PROGRAMS[name])
    assert not building.review, [r.message for r in building.review]
    walls = {w.id: w for w in building.walls}
    vertices = {v.id: v for v in building.vertices}
    for opening in building.openings:
        wall = walls[opening.wall_id]
        start, end = vertices[wall.start_id], vertices[wall.end_id]
        length = ((end.x - start.x) ** 2 + (end.y - start.y) ** 2) ** 0.5
        assert opening.offset_ft >= 0
        assert opening.offset_ft + opening.width_ft <= length + 1e-6
        assert opening.sill_ft + opening.height_ft <= wall.height_ft + 1e-6
    assert any(o.kind == "door" for o in building.openings)
    assert any(o.kind == "window" for o in building.openings)


def test_ground_floor_gets_an_entry_and_stairs_stack_as_objects():
    _, _, building = build(OFFICE)
    stairs = [o for o in building.objects if o.asset_id == "stairs"]
    assert len(stairs) == 2
    assert len({(o.x, o.y) for o in stairs}) == 1
    assert any(o.asset_id == "toilet" for o in building.objects)


def _rect_for(program, layouts, space_id):
    space = program.space(space_id)
    layout = layouts[space.floor_id]
    return next(r for r in layout.rooms if r.space_id == space_id)


def test_bathroom_fixtures_sit_on_a_wall_not_in_the_middle():
    program, layouts, building = build(HOME)
    rect = _rect_for(program, layouts, "wc")
    toilets = [o for o in building.objects if o.asset_id == "toilet" and o.floor_id == "ground"]
    assert toilets
    toilet = toilets[0]
    assert rect.x1 < toilet.x < rect.x2
    assert rect.y1 < toilet.y < rect.y2
    edge = min(toilet.x - rect.x1, rect.x2 - toilet.x, toilet.y - rect.y1, rect.y2 - toilet.y)
    assert edge < 2.0
    living = _rect_for(program, layouts, "living")
    assert not (living.x1 < toilet.x < living.x2 and living.y1 < toilet.y < living.y2) or edge < 2.0


def test_kitchens_get_a_sink_not_a_toilet():
    program, layouts, building = build(HOME)
    kitchen = _rect_for(program, layouts, "kitchen")
    in_kitchen = [
        o for o in building.objects
        if kitchen.x1 < o.x < kitchen.x2 and kitchen.y1 < o.y < kitchen.y2
    ]
    assert {o.asset_id for o in in_kitchen} <= {"sink", "counter"}
    assert any(o.asset_id == "sink" for o in in_kitchen)
    assert not any(o.asset_id == "toilet" for o in in_kitchen)


def test_a_named_washroom_still_gets_bathroom_fixtures():
    raw = {
        "building_use": "office",
        "storeys": [{"id": "ground", "name": "Ground"}],
        "spaces": [
            space("sales", "ground", "sales", 800, min_side_ft=16, entry=True),
            space("male", "ground", "washroom", 80, name="Male washroom"),
        ],
    }
    _, layouts, building = build(raw)
    toilets = [o for o in building.objects if o.asset_id == "toilet"]
    assert toilets
    rect = layouts["ground"].rooms
    wash = next(r for r in rect if r.space_id == "male")
    sales = next(r for r in rect if r.space_id == "sales")
    toilet = toilets[0]
    assert wash.x1 < toilet.x < wash.x2 and wash.y1 < toilet.y < wash.y2
    assert not (sales.x1 + 1 < toilet.x < sales.x2 - 1 and sales.y1 + 1 < toilet.y < sales.y2 - 1)


def test_a_storey_without_a_bathroom_gets_one():
    from plancheck.generation.program import ensure_wet_rooms

    program = BuildingProgram.model_validate(
        {
            "building_use": "office",
            "storeys": [{"id": "ground", "name": "Ground"}],
            "spaces": [space("office", "ground", "office", 400)],
        }
    )
    filled = ensure_wet_rooms(program)
    assert any(s.category == "bathroom" for s in filled.spaces)


def test_compiler_rejects_a_storey_with_no_layout():
    program = BuildingProgram.model_validate(HOME)
    layouts = pack_floors(program)
    layouts.pop("upper")
    with pytest.raises(CompileError):
        compile_building(program, layouts)


# --- contracts --------------------------------------------------------------


def test_overlapping_rectangles_are_rejected_before_compiling():
    with pytest.raises(ValueError, match="overlap"):
        FloorLayout.model_validate(
            {
                "floor_id": "g",
                "width_ft": 30,
                "depth_ft": 20,
                "rooms": [
                    {"space_id": "a", "x1": 0, "y1": 0, "x2": 20, "y2": 20},
                    {"space_id": "b", "x1": 10, "y1": 0, "x2": 30, "y2": 20},
                ],
            }
        )


def test_program_rejects_a_space_on_an_unknown_storey():
    with pytest.raises(ValueError, match="unknown floor_id"):
        BuildingProgram.model_validate(
            {
                "storeys": [{"id": "g", "name": "G"}],
                "spaces": [space("a", "g", "living", 200), space("b", "nope", "living", 200)],
            }
        )


def test_dangling_adjacency_hints_are_dropped_rather_than_fatal():
    program = BuildingProgram.model_validate(
        {
            "storeys": [{"id": "g", "name": "G"}],
            "spaces": [space("a", "g", "living", 200, adjacent_to=["ghost", "a"])],
        }
    )
    assert program.spaces[0].adjacent_to == []


def test_program_accepts_any_building_kind_and_ignores_extra_keys():
    program = BuildingProgram.model_validate(
        {
            "building_use": "hospital",
            "windows": 40,
            "storeys": [{"id": "Ground Floor", "name": "Ground", "height_ft": 30, "material": "concrete"}],
            "spaces": [
                {
                    "id": "Main Lobby",
                    "name": "Lobby",
                    "floor_id": "ground",
                    "category": "lobby",
                    "target_area_sqft": 800,
                    "purpose": "arrival",
                }
            ],
        }
    )
    assert program.building_use == "office"
    assert program.storeys[0].id == "ground_floor"
    assert program.storeys[0].height_ft == 24
    assert program.spaces[0].id == "main_lobby"
    assert program.spaces[0].floor_id == "ground_floor"


# --- requirements -----------------------------------------------------------


def test_rule_pack_only_ships_requirements_that_can_be_measured():
    _, program_obj, building = build(OFFICE)
    program = BuildingProgram.model_validate(OFFICE)
    rules = rule_pack("office", {s.category for s in program.spaces})
    assert rules
    results = check_building(building, rules)
    assert results
    assert not [r for r in results if r["status"] == "cannot_verify"]


def test_generated_geometry_is_measured_and_repairable():
    # Eight 70 sqft offices sit under the 8 m2 requirement on purpose.
    spaces = [space("core", "g", "stair", 130), space("corr", "g", "circulation", 200, entry=True)]
    spaces += [space(f"o{i}", "g", "office", 70) for i in range(8)]
    program = BuildingProgram.model_validate(
        {"building_use": "office", "storeys": [{"id": "g", "name": "G"}], "spaces": spaces}
    )
    layouts = pack_floors(program, sum(s["target_area_sqft"] for s in spaces))
    building = compile_building(program, layouts)
    rules = rule_pack("office", {s.category for s in program.spaces})
    failures = [c for c in check_building(building, rules) if c["status"] == "fail"]
    assert failures, "undersized offices should be reported, not silently accepted"
    proposal = propose_repairs(building, rules)
    assert proposal["summary"]["proposed"] or proposal["summary"]["blocked"]


# --- demo provider ----------------------------------------------------------


def test_demo_home_still_compiles_through_the_shared_compiler():
    building = demo_home()
    validate_building(building)
    assert len(building.floors) == 2
    assert building == demo_home()
    assert any(w.locked for w in building.walls)
    assert propose_repairs(building, demo_rules())["commands"]


def test_demo_provider_needs_no_key():
    result = generate_from_brief(DesignBrief(name="Demo"))
    assert result.llm_calls == 0
    assert result.program is None
    assert len(result.building.floors) == 2


# --- the agent loop ---------------------------------------------------------


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("PLANCHECK_GENERATION_PROVIDER", "baseten")
    monkeypatch.setenv("PLANCHECK_AGENT_API_KEY", "test-key")
    reset_settings()
    monkeypatch.setattr("plancheck.generation.research._wikipedia_hits", lambda *a, **k: [])


def scripted(monkeypatch, *replies):
    """Replace the model with a fixed script and record how often it is called."""
    calls = []

    def fake(role, messages, **kwargs):
        calls.append((role, messages))
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr("plancheck.generation.agent.complete_json", fake)
    return calls


def test_one_model_call_is_enough_on_the_happy_path(live, monkeypatch):
    calls = scripted(monkeypatch, {"program": HOME})
    result = generate_from_brief(DesignBrief(name="Willow", prompt="A calm family house"))
    assert len(calls) == 1
    assert result.llm_calls == 1
    validate_building(result.building)
    assert len(result.building.floors) == 2
    assert result.program["building_use"] == "home"
    assert result.layouts["ground"]["rooms"]
    prompt = calls[0][1][-1]["content"]
    assert '"research"' in prompt
    assert "recommended_rooms" in prompt


def test_a_broken_program_gets_exactly_one_corrective_turn(live, monkeypatch):
    broken = {"program": {"storeys": [{"id": "g", "name": "G"}], "spaces": []}}
    calls = scripted(monkeypatch, broken, {"program": RETAIL})
    result = generate_from_brief(DesignBrief(name="Shop"))
    assert len(calls) == 2
    assert result.llm_calls == 2
    validate_building(result.building)
    # The corrective turn is told what actually went wrong.
    assert "previous_attempt_failed_because" in calls[1][1][-1]["content"]


def test_the_same_failing_plan_twice_fails_closed(live, monkeypatch):
    calls = scripted(monkeypatch, {"program": HOME})
    monkeypatch.setattr(
        "plancheck.generation.agent.compile_building",
        lambda *a, **k: (_ for _ in ()).throw(CompileError("walls do not close")),
    )
    with pytest.raises(GenerationError, match="same plan again"):
        generate_from_brief(DesignBrief(name="Loop"))
    # The repeat is rejected before it costs a third call or a second pipeline run.
    assert len(calls) == 2


def test_two_different_failures_end_the_job(live, monkeypatch):
    calls = scripted(monkeypatch, {"program": HOME | {"notes": "a"}}, {"program": HOME | {"notes": "b"}})
    monkeypatch.setattr(
        "plancheck.generation.agent.compile_building",
        lambda *a, **k: (_ for _ in ()).throw(CompileError("walls do not close")),
    )
    with pytest.raises(GenerationError, match="walls do not close"):
        generate_from_brief(DesignBrief(name="Broken"))
    assert len(calls) == 2


def test_prose_instead_of_a_program_is_not_retried_forever(live, monkeypatch):
    calls = scripted(monkeypatch, {"message": "Sure! What style would you like?"})
    with pytest.raises(GenerationError):
        generate_from_brief(DesignBrief(name="Chatty"))
    assert len(calls) == 2


def test_the_model_may_fix_one_storey_with_explicit_rectangles(live, monkeypatch):
    fix = {
        "layouts": {
            "ground": {
                "width_ft": 40,
                "depth_ft": 30,
                "rooms": [
                    {"space_id": "stair_g", "x1": 0, "y1": 0, "x2": 10, "y2": 12},
                    {"space_id": "hall", "x1": 10, "y1": 0, "x2": 40, "y2": 12},
                    {"space_id": "living", "x1": 0, "y1": 12, "x2": 16, "y2": 30},
                    {"space_id": "kitchen", "x1": 16, "y1": 12, "x2": 28, "y2": 30},
                    {"space_id": "dining", "x1": 28, "y1": 12, "x2": 36, "y2": 30},
                    {"space_id": "wc", "x1": 36, "y1": 12, "x2": 40, "y2": 30},
                ],
            }
        }
    }
    calls = scripted(monkeypatch, {"program": HOME}, fix)
    attempts = {"n": 0}
    real = pack_floors

    def once(program, area=None, kind=""):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise LayoutError("first pack failed")
        return real(program, area, kind)

    monkeypatch.setattr("plancheck.generation.agent.pack_floors", once)
    result = generate_from_brief(DesignBrief(name="Fixed"))
    assert len(calls) == 2
    ground = {r["space_id"]: r for r in result.layouts["ground"]["rooms"]}
    assert (ground["stair_g"]["x2"], ground["stair_g"]["y2"]) == (10, 12)


def test_a_live_provider_without_a_key_refuses_instead_of_faking_it(monkeypatch):
    monkeypatch.setenv("PLANCHECK_GENERATION_PROVIDER", "baseten")
    monkeypatch.setenv("PLANCHECK_AGENT_API_KEY", "")
    reset_settings()
    with pytest.raises(GenerationError, match="no API key"):
        generate_from_brief(DesignBrief(name="No key"))


def test_a_wall_clock_budget_stops_the_job(live, monkeypatch):
    scripted(monkeypatch, {"program": HOME})
    monkeypatch.setattr("plancheck.generation.agent.DEADLINE_S", -1)
    with pytest.raises(GenerationError):
        generate_from_brief(DesignBrief(name="Slow"))


def test_progress_is_reported_in_order(live, monkeypatch):
    scripted(monkeypatch, {"program": OFFICE})
    seen = []
    generate_from_brief(
        DesignBrief(name="Studio", building_use="Office"),
        lambda **kw: seen.append((kw.get("phase"), kw.get("progress"), kw.get("kind"))),
    )
    phases = [p for p, _, _ in seen]
    assert phases[0] == "analyzing"
    assert "researching" in phases and "planning" in phases and "validating" in phases
    assert [p for _, p, _ in seen] == sorted(p for _, p, _ in seen)
    kinds = [k for *_, k in seen]
    assert "thinking" in kinds and "source" in kinds and "rooms" in kinds


# --- API --------------------------------------------------------------------


def run_generate(client, brief):
    response = client.post("/api/desktop/generate", json=brief)
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(200):
        job = client.get("/api/desktop/jobs/" + job_id).json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def test_generate_endpoint_uses_the_agent_and_saves_a_real_plan(live, monkeypatch, tmp_path):
    monkeypatch.setenv("PLANCHECK_DATA_DIR", str(tmp_path))
    reset_settings()
    scripted(monkeypatch, {"program": OFFICE})
    client = TestClient(app)
    job = run_generate(client, {"name": "Studio", "building_use": "Office", "prompt": "Two floors"})
    assert job["state"] == "done", job

    project = client.get("/api/desktop/projects/" + job["result"]["project_id"]).json()
    assert len(project["building"]["floors"]) == 2
    assert project["brief"]["prompt"] == "Two floors"
    assert project["checks"]
    # Not the demo house.
    assert {r["name"] for r in project["building"]["rooms"]} != {
        r.name for r in demo_home().rooms
    }
    audit = json.loads(
        (tmp_path / job["result"]["project_id"] / "program.json").read_text(encoding="utf8")
    )
    assert audit["llm_calls"] == 1
    assert audit["program"]["building_use"] == "office"
    assert job["result"]["research"]["kind"] in {"office", "home"}
    assert job["result"]["research"]["rooms"]


def test_generate_endpoint_reports_the_failure_and_writes_nothing(live, monkeypatch, tmp_path):
    monkeypatch.setenv("PLANCHECK_DATA_DIR", str(tmp_path))
    reset_settings()
    scripted(monkeypatch, {"message": "I need more detail"})
    client = TestClient(app)
    job = run_generate(client, {"name": "Doomed"})
    assert job["state"] == "error"
    assert job["result"] is None
    assert client.get("/api/desktop/projects").json() == []


def test_health_reports_the_generation_provider(live):
    payload = TestClient(app).get("/api/desktop/health").json()
    assert payload["generation_provider"] == "baseten"
