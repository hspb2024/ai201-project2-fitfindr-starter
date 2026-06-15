"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Pull a price ceiling, a size, and a clean keyword description out of the
    raw natural-language query using regex/string parsing (no LLM call).

    Returns a dict: {"description": str, "size": str | None, "max_price": float | None}.
    """
    text = query.strip()
    max_price = None
    size = None

    # max_price: "under $30", "$30", "below 30", "less than 30 dollars"
    price_match = re.search(
        r"(?:under|below|less than|max|<=?)?\s*\$?\s*(\d+(?:\.\d{1,2})?)\s*(?:dollars|usd|bucks)?",
        text,
        flags=re.IGNORECASE,
    )
    # Only treat it as a price if a $, a price keyword, or "dollars" is nearby —
    # otherwise a bare number (e.g. a size "8") would be misread as a price.
    if price_match and re.search(
        r"\$|under|below|less than|max|dollars|usd|bucks|price",
        text,
        flags=re.IGNORECASE,
    ):
        max_price = float(price_match.group(1))

    # size: "size M", "size 8", "in a medium"
    size_match = re.search(
        r"\bsize\s+([a-z0-9/]+)\b|\b(xs|s|m|l|xl|xxl)\b(?=\s|$|,|\.)",
        text,
        flags=re.IGNORECASE,
    )
    if size_match:
        size = (size_match.group(1) or size_match.group(2)).upper()

    # description: strip out the price phrase and the explicit "size X" phrase,
    # leave the rest as keywords.
    description = text
    description = re.sub(
        r"(?:under|below|less than|max|<=?)\s*\$?\s*\d+(?:\.\d{1,2})?\s*(?:dollars|usd|bucks)?",
        " ",
        description,
        flags=re.IGNORECASE,
    )
    description = re.sub(r"\$\s*\d+(?:\.\d{1,2})?", " ", description)
    description = re.sub(r"\bsize\s+[a-z0-9/]+\b", " ", description, flags=re.IGNORECASE)
    description = re.sub(r"\s+", " ", description).strip(" ,.;")

    return {"description": description or text, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session — the single source of truth for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2: parse the raw query into structured search parameters.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: search. This is the only branch point in the loop.
    session["search_results"] = search_listings(
        parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )

    if not session["search_results"]:
        # No matches → set a specific, actionable error and STOP. The styling
        # tools are never called with empty input.
        bits = []
        if parsed["max_price"] is not None:
            bits.append(f"under ${parsed['max_price']:g}")
        if parsed["size"]:
            bits.append(f"in size {parsed['size']}")
        constraints = (" " + " ".join(bits)) if bits else ""
        session["error"] = (
            f"No listings matched '{parsed['description']}'{constraints}. "
            "Try raising your price, dropping the size filter, or using broader "
            "keywords (e.g. 'tee' instead of 'vintage graphic tee')."
        )
        return session

    # Step 4: select the top-ranked result to style.
    session["selected_item"] = session["search_results"][0]

    # Step 5: suggest an outfit using the selected item + the user's wardrobe.
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], session["wardrobe"]
    )

    # Step 6: turn that outfit into a shareable fit-card caption.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: done — error stays None, all three output fields populated.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
