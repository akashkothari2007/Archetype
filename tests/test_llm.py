from plancheck.services.llm import LLMError, parse_json
import pytest


def test_parse_json_strips_fences():
    assert parse_json("```json\n{\"intent\":\"answer\"}\n```")["intent"] == "answer"


def test_parse_json_rejects_plain_text():
    with pytest.raises(LLMError):
        parse_json("not json")


def test_parse_json_strips_think_tags_and_prefers_the_program():
    text = (
        "<think>I should return {\"bad\": true} as a sketch.</think>\n"
        "Here is the plan:\n"
        '{"program": {"building_use": "home", "storeys": [{"id": "g", "name": "G"}],'
        ' "spaces": [{"id": "living", "name": "Living", "floor_id": "g",'
        ' "category": "living", "target_area_sqft": 200}]}}'
    )
    data = parse_json(text)
    assert data["program"]["building_use"] == "home"
    assert data["program"]["spaces"][0]["id"] == "living"


def test_parse_json_repairs_a_truncated_program():
    text = (
        '{"program": {"building_use": "office", "storeys": [{"id": "g", "name": "G"}],'
        ' "spaces": [{"id": "ward_1", "name": "Ward", "floor_id": "g",'
        ' "category": "ward", "target_area_sqft": 900'
    )
    data = parse_json(text)
    assert data["program"]["spaces"][0]["id"] == "ward_1"
    assert data["program"]["building_use"] == "office"
