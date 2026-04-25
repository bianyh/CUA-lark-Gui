import pytest

from cua_lark.llm import VLMClient, VLMError, extract_json_object


def test_extract_json_from_code_fence():
    assert extract_json_object("```json\n{\"ok\": true}\n```") == {"ok": True}


def test_extract_json_from_surrounding_text():
    assert extract_json_object("result: {\"action\": \"wait\"}") == {"action": "wait"}


def test_extract_json_rejects_non_object():
    with pytest.raises(VLMError):
        extract_json_object("[1, 2, 3]")


def test_extract_response_content_from_dict_payload():
    payload = {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
    assert VLMClient._extract_response_content(payload) == "{\"ok\": true}"


def test_extract_response_content_rejects_html_string():
    with pytest.raises(VLMError):
        VLMClient._extract_response_content("<!doctype html><html></html>")
