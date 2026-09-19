from plancheck.services.llm import parse_json


def test_parse_json_strips_fences():
    assert parse_json("```json\n{\"intent\":\"answer\"}\n```")["intent"] == "answer"


def test_parse_json_rejects_plain_text():
    import pytest
    from plancheck.services.llm import LLMError

    with pytest.raises(LLMError):
        parse_json("not json")
