"""Tests for the JSON-stripping helper in the LLM provider base."""
from app.core.llm.base import _strip_json


def test_strips_code_fence():
    raw = "```json\n{\"a\": 1}\n```"
    assert _strip_json(raw) == "{\"a\": 1}"


def test_strips_think_block():
    raw = "<think>thinking...</think>\n{\"x\": true}"
    assert _strip_json(raw) == "{\"x\": true}"


def test_extracts_json_from_prose():
    raw = "Here is the result: {\"y\": [1, 2, 3]} hope that helps!"
    assert _strip_json(raw) == "{\"y\": [1, 2, 3]}"


def test_plain_object_pass_through():
    raw = "{\"a\": \"b\"}"
    assert _strip_json(raw) == "{\"a\": \"b\"}"
