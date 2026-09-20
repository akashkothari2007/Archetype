import pytest

from plancheck.mocks.generation import demo_home
from plancheck.services.commands import CommandError, apply_commands


def site_command(**params):
    return {"kind": "set_site", "target_id": "", "params": params}


def test_building_starts_unsited():
    site = demo_home().site
    assert site.lat is None and site.lon is None
    assert site.rotation_deg == 0


def test_set_site_records_the_location_and_leaves_geometry_alone():
    before = demo_home()
    after = apply_commands(before, [site_command(lat=43.4723, lon=-80.5449, address="Waterloo")])
    assert (after.site.lat, after.site.lon) == (43.4723, -80.5449)
    assert after.site.address == "Waterloo"
    assert [w.id for w in after.walls] == [w.id for w in before.walls]
    assert [v.model_dump() for v in after.vertices] == [v.model_dump() for v in before.vertices]


def test_rotation_and_offset_merge_without_clearing_the_pin():
    sited = apply_commands(demo_home(), [site_command(lat=51.5, lon=-0.12)])
    turned = apply_commands(sited, [site_command(rotation_deg=37.5, ground_offset_ft=-2)])
    assert (turned.site.lat, turned.site.lon) == (51.5, -0.12)
    assert turned.site.rotation_deg == 37.5
    assert turned.site.ground_offset_ft == -2


def test_commands_are_rejected_rather_than_half_applied():
    building = demo_home()
    with pytest.raises(CommandError):
        apply_commands(building, [site_command(lat=43.47)])
    with pytest.raises(CommandError):
        apply_commands(building, [site_command(elevation_m=12)])
    with pytest.raises(ValueError):
        apply_commands(building, [site_command(lat=118, lon=0)])
    assert building.site.lat is None


def test_unsetting_the_pin_returns_the_building_to_no_location():
    sited = apply_commands(demo_home(), [site_command(lat=1.35, lon=103.8, address="Singapore")])
    cleared = apply_commands(sited, [site_command(lat=None, lon=None, address="")])
    assert cleared.site.lat is None and cleared.site.lon is None
