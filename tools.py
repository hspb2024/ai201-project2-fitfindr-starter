"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Groq model used by the two LLM-backed tools (suggest_outfit, create_fit_card).
MODEL = "llama-3.3-70b-versatile"

# Tiny stop-word list so common filler words don't inflate relevance scores.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "in", "of", "to", "my",
    "some", "looking", "want", "need", "size", "under", "im", "i", "me",
}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # 1. Apply the hard filters (size + price) before scoring relevance.
    filtered = []
    for item in listings:
        if max_price is not None and item["price"] > max_price:
            continue
        if size is not None and size.strip():
            # Case-insensitive substring match so "M" matches "S/M",
            # "M (oversized)", etc.
            if size.strip().lower() not in item["size"].lower():
                continue
        filtered.append(item)

    # 2. Tokenize the description into meaningful keywords.
    tokens = [
        t for t in re.findall(r"[a-z0-9]+", description.lower())
        if len(t) > 1 and t not in _STOPWORDS
    ]

    # No usable keywords (e.g. description was just stop-words): the size/price
    # filters are all we have, so return everything that passed them.
    if not tokens:
        return filtered

    # 3. Score each listing by weighted keyword overlap. Matches in the title
    #    or style_tags count for more than matches buried in the description.
    scored = []
    for item in filtered:
        strong = " ".join([
            item["title"],
            " ".join(item.get("style_tags", [])),
            item["category"],
        ]).lower()
        weak = " ".join([
            item["description"],
            " ".join(item.get("colors", [])),
            item.get("brand") or "",
        ]).lower()

        score = 0
        for token in tokens:
            if token in strong:
                score += 2
            elif token in weak:
                score += 1

        # 4. Drop anything with no keyword overlap at all.
        if score > 0:
            scored.append((score, item))

    # 5. Sort by score, highest first (stable sort keeps dataset order for ties).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_line = (
        f"{new_item.get('title', 'this item')} "
        f"(category: {new_item.get('category', 'unknown')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'unspecified'}, "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'unspecified'})"
    )

    items = wardrobe.get("items", []) if isinstance(wardrobe, dict) else []

    if not items:
        # Empty wardrobe → general styling advice, no invented owned pieces.
        prompt = (
            f"A shopper is considering this secondhand piece: {item_line}.\n"
            "They haven't told us what's in their closet yet. In 2-3 sentences, "
            "give general styling advice: what kinds of pieces pair well with it, "
            "what vibe it suits, and one concrete tip for wearing it. "
            "Do NOT invent specific items they own — speak in general terms."
        )
    else:
        # Non-empty wardrobe → outfits using their actual named pieces.
        closet = "\n".join(
            f"- {w.get('name', 'item')} ({w.get('category', '?')})"
            for w in items
        )
        prompt = (
            f"A shopper is considering this secondhand piece: {item_line}.\n\n"
            f"Here is what's already in their wardrobe:\n{closet}\n\n"
            "Suggest 1-2 complete outfits that pair the new piece with specific "
            "items from their wardrobe. Refer to the wardrobe pieces by name. "
            "Keep it to 2-4 sentences and add one concrete styling tip "
            "(tuck, roll, layer, cuff, etc.)."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a sharp, encouraging secondhand-fashion stylist.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        text = (response.choices[0].message.content or "").strip()
        if text:
            return text
        # Empty model output — fall through to the fallback below.
        raise ValueError("empty LLM response")
    except Exception:
        # Never return "" or raise to the caller: give a usable fallback so the
        # planning loop can still proceed to create_fit_card.
        return (
            f"Style {new_item.get('title', 'this piece')} with simple, "
            "complementary basics — neutral bottoms and clean footwear let it "
            "stand out. Keep the rest of the look minimal so the piece is the focus."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # 1. Guard against an empty or whitespace-only outfit string.
    if not outfit or not outfit.strip():
        return (
            "Can't generate a fit card without an outfit suggestion — "
            "try a different query so I have a look to caption."
        )

    title = new_item.get("title", "this piece")
    price = new_item.get("price")
    platform = new_item.get("platform", "a resale app")
    price_str = f"${price:g}" if isinstance(price, (int, float)) else "a steal"

    prompt = (
        f"Write a short, casual Instagram/TikTok caption for a thrifted find.\n"
        f"Item: {title}\n"
        f"Price: {price_str}\n"
        f"Platform: {platform}\n"
        f"Outfit: {outfit}\n\n"
        "Rules: 2-4 sentences. Sound like a real person posting their fit, "
        "NOT a product description. Mention the item name, the price, and the "
        "platform naturally, once each. Capture the outfit vibe in specific "
        "terms. A tasteful emoji or two is fine."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You write punchy, authentic secondhand-fashion captions.",
                },
                {"role": "user", "content": prompt},
            ],
            # High temperature so repeated calls on the same input read differently.
            temperature=1.0,
            max_tokens=150,
        )
        text = (response.choices[0].message.content or "").strip()
        if text:
            return text
        raise ValueError("empty LLM response")
    except Exception:
        # Fallback template so the user always gets a caption.
        return (
            f"just thrifted this {title} for {price_str} on {platform} 🛍️ "
            f"styled it exactly how I pictured — obsessed."
        )
