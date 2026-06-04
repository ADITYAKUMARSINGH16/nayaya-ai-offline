"""Tests for the citation-extraction logic used by the verifier."""
from app.agents.verifier import extract_section_numbers


def test_extracts_sections_from_judgment_text():
    text = "The accused is guilty under Section 303 and Section 305 of the BNS."
    assert extract_section_numbers(text) == ["303", "305"]


def test_handles_no_sections():
    assert extract_section_numbers("No legal references here.") == []


def test_dedupes_and_sorts():
    text = "Section 303 again Section 303 and section 105"
    assert extract_section_numbers(text) == ["105", "303"]
