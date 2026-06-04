"""Tests for the LegalGraph-Lite builder."""
import json
import tempfile
from pathlib import Path

from app.services import legal_graph
from app.services.legal_graph import (
    build_adjacency,
    extract_references,
    save_graph,
)


def test_extract_references_finds_section_numbers():
    text = "This offence is punishable as in section 103 and is subject to sec 51."
    refs = extract_references(text, self_number="200")
    assert "103" in refs
    assert "51" in refs


def test_extract_references_excludes_self():
    text = "section 303 — applies to section 303"
    assert "303" not in extract_references(text, self_number="303")


def test_build_adjacency_links_cross_refs_both_ways():
    sections = [
        {"section_number": "303", "section_title": "Theft", "act": "BNS", "category": "Criminal_Laws",
         "text": "Punishable as in section 305."},
        {"section_number": "305", "section_title": "Enhanced punishment", "act": "BNS", "category": "Criminal_Laws",
         "text": "Punishment for theft under section 303 of certain property."},
    ]
    g = build_adjacency(sections)
    assert "303" in g["sections"]
    assert "305" in g["edges"]["303"]
    assert "303" in g["edges"]["305"]   # undirected


def test_neighbours_via_graph_file(tmp_path: Path, monkeypatch):
    sections = [
        {"section_number": "303", "section_title": "Theft", "act": "BNS", "category": "Criminal_Laws",
         "text": "See section 305."},
        {"section_number": "305", "section_title": "More", "act": "BNS", "category": "Criminal_Laws",
         "text": "Reference back to section 303."},
        {"section_number": "318", "section_title": "Cheating", "act": "BNS", "category": "Criminal_Laws",
         "text": "Different topic, no refs."},
    ]
    g = build_adjacency(sections)
    path = tmp_path / "graph.json"
    save_graph(g, path)
    monkeypatch.setattr(legal_graph, "GRAPH_PATH", path)
    legal_graph.load_graph.cache_clear()

    out = legal_graph.neighbours("303")
    assert "305" in out
