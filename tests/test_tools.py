"""
tests/test_tools.py

Tests for the three FitFindr tools, run with `pytest tests/`.

Each tool has at least one test for its happy path and one for its failure
mode. The two LLM-backed tools (suggest_outfit, create_fit_card) make real
Groq API calls, so those tests need GROQ_API_KEY set in .env.
"""

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── search_listings ─────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Impossible query — must return an empty list, never raise.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_case_insensitive():
    # "m" (lowercase) should still match sizes like "S/M".
    results = search_listings("tee", size="m", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_results_sorted_by_relevance():
    results = search_listings("vintage denim jacket", size=None, max_price=None)
    # The top result should be a strong match — its text mentions a keyword.
    assert results, "expected at least one result"
    top_text = (results[0]["title"] + " ".join(results[0]["style_tags"])).lower()
    assert any(kw in top_text for kw in ("vintage", "denim", "jacket"))


# ── suggest_outfit ───────────────────────────────────────────────────────────

@pytest.fixture
def sample_item():
    return search_listings("vintage graphic tee", size=None, max_price=50)[0]


def test_suggest_outfit_with_wardrobe(sample_item):
    out = suggest_outfit(sample_item, get_example_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


def test_suggest_outfit_empty_wardrobe(sample_item):
    # Empty wardrobe is a handled case, not an error: still returns advice.
    out = suggest_outfit(sample_item, get_empty_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


# ── create_fit_card ──────────────────────────────────────────────────────────

def test_create_fit_card_happy_path(sample_item):
    card = create_fit_card(
        "Pair it with baggy jeans and chunky sneakers.", sample_item
    )
    assert isinstance(card, str)
    assert card.strip() != ""


def test_create_fit_card_empty_outfit(sample_item):
    # Empty outfit must return a descriptive message string, not raise.
    card = create_fit_card("", sample_item)
    assert isinstance(card, str)
    assert card.strip() != ""
    assert "outfit" in card.lower()


def test_create_fit_card_whitespace_outfit(sample_item):
    card = create_fit_card("   \n  ", sample_item)
    assert isinstance(card, str)
    assert "outfit" in card.lower()
