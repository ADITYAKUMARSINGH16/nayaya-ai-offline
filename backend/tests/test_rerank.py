"""Tests for the reciprocal rank fusion merger."""
from app.services.rerank import rrf_merge


def test_rrf_merges_consistent_top_pick():
    a = ["303", "305", "318"]
    b = ["303", "318", "305"]
    c = ["303", "105", "318"]
    out = rrf_merge([a, b, c], top_k=3)
    assert out[0] == "303"           # appears top of every list


def test_rrf_handles_disjoint_lists():
    out = rrf_merge([["a"], ["b"], ["c"]], top_k=3)
    assert sorted(out) == ["a", "b", "c"]


def test_rrf_respects_top_k():
    out = rrf_merge([["a", "b", "c", "d"]], top_k=2)
    assert out == ["a", "b"]
