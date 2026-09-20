from plancheck.mocks.generation import demo_home
from plancheck.services.agent import fallback_furnish, host_intent, local_respond
from plancheck.services.commands import apply_commands
from plancheck.services.furniture import furniture_catalog, furnish_building, is_furnish_request, target_rooms


def test_catalog_covers_a_whole_house():
    catalog = furniture_catalog()
    roles = {item["role"] for item in catalog}
    ids = {item["id"] for item in catalog}
    assert len(catalog) >= 40
    assert {"sofa", "chair", "bed", "desk", "dining_table", "coffee_table"} <= roles
    assert {"sofa_02", "GothicBed_01", "dining_table", "metal_office_desk"} <= ids


def test_furnish_request_detection():
    assert is_furnish_request("Furnish the living room")
    assert is_furnish_request("add a sofa to the lounge")
    assert host_intent("Furnish this floor") == "finish"
    assert host_intent("widen the hallway") == "geometry"


def test_furnish_living_room_places_catalog_models():
    building = demo_home()
    living = next(room for room in building.rooms if "living" in f"{room.name} {room.category}".lower())
    commands = furnish_building(building, rooms=[living], message="furnish the living room")
    assert commands
    assert all(cmd["kind"] == "place_object" for cmd in commands)
    assert all(cmd["params"]["kind"] == "furniture" for cmd in commands)
    assert all(cmd["params"]["asset_id"] in {item["id"] for item in furniture_catalog()} for cmd in commands)
    applied = apply_commands(building, commands, actor="agent")
    assert len(applied.objects) > len(building.objects)
    xs = [obj.x for obj in applied.objects if obj.kind == "furniture"]
    ys = [obj.y for obj in applied.objects if obj.kind == "furniture"]
    min_x = min(pt[0] for pt in living.polygon)
    max_x = max(pt[0] for pt in living.polygon)
    min_y = min(pt[1] for pt in living.polygon)
    max_y = max(pt[1] for pt in living.polygon)
    assert all(min_x <= x <= max_x for x in xs)
    assert all(min_y <= y <= max_y for y in ys)


def test_local_assistant_furnishes_named_room():
    building = demo_home()
    living = next(room for room in building.rooms if room.category == "living")
    result = local_respond(building, [], "Furnish the living room", context="3d")
    assert result["intent"] == "finish"
    assert result["commands"]
    applied = apply_commands(building, result["commands"], actor="agent")
    from shapely.geometry import Point, Polygon
    poly = Polygon(living.polygon)
    furniture = [obj for obj in applied.objects if obj.kind == "furniture"]
    assert furniture
    assert all(poly.contains(Point(obj.x, obj.y)) for obj in furniture)


def test_fallback_skips_bathrooms():
    building = demo_home()
    baths = [room for room in building.rooms if "bath" in f"{room.name} {room.category}".lower()]
    assert baths
    assert target_rooms(building, "furnish this floor", [], [baths[0].floor_id])
    assert baths[0] not in target_rooms(building, "furnish this floor", [], [baths[0].floor_id])
    result = fallback_furnish(building, "Furnish this floor", [], baths[0].floor_id)
    assert result["commands"]
    ids = {cmd["params"]["asset_id"] for cmd in result["commands"]}
    assert "toilet" not in ids
