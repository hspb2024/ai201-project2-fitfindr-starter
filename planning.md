# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## What FitFindr Does (overview)

FitFindr is a single-turn shopping agent for secondhand fashion. The user types one natural-language request (what they want, optionally a size and a price ceiling, and a bit about their style). The agent parses that request, **searches** the mock listings dataset for matching pieces, picks the best one, **suggests an outfit** that pairs the new piece with items already in the user's wardrobe, and finally writes a casual, shareable **fit card** caption for the find. If the search returns nothing, the agent stops immediately and tells the user how to adjust their query — it never calls the styling tools with empty input.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the 40-item mock listings dataset for pieces that match the user's free-text description, filtering out anything over the price ceiling or in the wrong size, then ranks the survivors by how well their text matches the description. It is a pure, deterministic function — no LLM call.

**Input parameters:**
- `description` (str): Free-text keywords describing the desired item, e.g. `"vintage graphic tee"`. Used for keyword-overlap scoring against each listing's `title`, `description`, `style_tags`, `category`, `colors`, and `brand`.
- `size` (str | None): Size string to filter by, e.g. `"M"`. Matching is case-insensitive and substring-based so `"M"` matches `"S/M"` and `"M (oversized)"`. `None` skips size filtering.
- `max_price` (float | None): Inclusive price ceiling, e.g. `30.0`. Listings with `price > max_price` are dropped. `None` skips price filtering.

**What it returns:**
A `list[dict]` of full listing dictionaries, sorted by relevance score (highest first). Each dict contains: `id` (str), `title` (str), `description` (str), `category` (str), `style_tags` (list[str]), `size` (str), `condition` (str: excellent/good/fair), `price` (float), `colors` (list[str]), `brand` (str | None), `platform` (str: depop/thredUp/poshmark). Listings whose keyword-overlap score is 0 are excluded entirely. Returns an **empty list** when nothing matches — it never raises.

**What happens if it fails or returns nothing:**
Returning `[]` is a normal, expected outcome, not an exception. The planning loop checks for the empty list, sets `session["error"]` to a helpful, specific message (suggesting the user relax the price, broaden the description, or drop the size filter), and returns early **without** calling `suggest_outfit`.

---

### Tool 2: suggest_outfit

**What it does:**
Takes the chosen listing and the user's wardrobe and asks the LLM (Groq) to propose 1–2 concrete outfit combinations that style the new piece with items the user already owns. Returns natural-language styling advice.

**Input parameters:**
- `new_item` (dict): A single listing dict (the top search result the user is considering). The tool reads its `title`, `category`, `colors`, `style_tags`, and `condition` to ground the suggestion.
- `wardrobe` (dict): A wardrobe dict shaped `{"items": [ {id, name, category, colors, style_tags, notes}, ... ]}`, from `get_example_wardrobe()` or `get_empty_wardrobe()`. The `items` list may be empty.

**What it returns:**
A non-empty `str` of outfit suggestions. When the wardrobe has items, the string names specific owned pieces (e.g. "pair it with your wide-leg khaki trousers and chunky white sneakers") and gives a styling tip. When the wardrobe is empty, it returns general styling advice (what kinds of pieces pair well, what vibe it suits) instead of referencing nonexistent items.

**What happens if it fails or returns nothing:**
An empty wardrobe is handled by branching to the general-advice prompt — not treated as an error. If the LLM call itself throws (network/auth), the tool catches it and returns a short fallback styling string so the loop can still proceed to `create_fit_card`; it never returns `""` or raises to the caller.

---

### Tool 3: create_fit_card

**What it does:**
Generates a short, casual, shareable social-media caption ("fit card") for the thrifted find, using the outfit suggestion and the item's details. Uses a higher LLM temperature so repeated calls read differently.

**Input parameters:**
- `outfit` (str): The outfit-suggestion string returned by `suggest_outfit()`.
- `new_item` (dict): The listing dict for the thrifted item — supplies `title`, `price`, and `platform` to mention naturally in the caption.

**What it returns:**
A 2–4 sentence `str` usable as an Instagram/TikTok caption. It feels like a real OOTD post (not a product description), mentions the item name, price, and platform once each, and captures the outfit vibe in specific terms.

**What happens if it fails or returns nothing:**
If `outfit` is missing, empty, or whitespace-only, the tool returns a descriptive error-message string (e.g. "Can't write a fit card without an outfit suggestion.") instead of raising. If the LLM call throws, it catches and returns a simple template caption built from the item fields so the user still gets output.

---

### Additional Tools (if any)

None for the core build. (Stretch idea: a `parse_query` LLM tool that extracts `description`/`size`/`max_price` from the raw query — see Planning Loop, Step 2.)

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is a fixed, linear pipeline with one early-exit branch. It is not free-form tool selection — the order is deterministic, and the only decision point is whether the search produced results.

1. **Initialize** the session with `_new_session(query, wardrobe)`.
2. **Parse** `query` into `description`, `size`, and `max_price`, stored in `session["parsed"]`. Implementation choice: regex/string parsing for the structured bits — `max_price` from a pattern like `under $30` / `$30` / `30 dollars`; `size` from a pattern like `size M` or a standalone size token; `description` is the remaining cleaned text. (Stretch: hand the raw query to the LLM to return a JSON object with the three fields.)
3. **Call `search_listings(description, size, max_price)`** and store the list in `session["search_results"]`.
   - **Branch — empty?** `if not session["search_results"]:` set `session["error"]` to a specific, actionable message and `return session` immediately. Do **not** call `suggest_outfit`.
   - **Else** continue.
4. **Select** `session["selected_item"] = session["search_results"][0]` (the top-ranked result).
5. **Call `suggest_outfit(selected_item, wardrobe)`** and store the string in `session["outfit_suggestion"]`.
6. **Call `create_fit_card(outfit_suggestion, selected_item)`** and store the string in `session["fit_card"]`.
7. **Return** the session.

The loop "knows it's done" when it has returned the session — either early (with `error` set and the styling fields `None`) or after Step 6 (with `error` still `None` and all three output fields populated).

---

## State Management

**How does information from one tool get passed to the next?**

All state lives in a single `session` dict created by `_new_session()` — it is the single source of truth for one interaction. Tools do not call each other directly and hold no shared global state; the planning loop reads from and writes to `session` between each call, so every tool's output becomes available to the next step.

Tracked fields:
- `query` (str): the original user input.
- `parsed` (dict): `{description, size, max_price}` from Step 2.
- `search_results` (list[dict]): output of `search_listings`.
- `selected_item` (dict | None): `search_results[0]`, the input to both styling tools.
- `wardrobe` (dict): passed straight into `suggest_outfit`.
- `outfit_suggestion` (str | None): output of `suggest_outfit`, the input to `create_fit_card`.
- `fit_card` (str | None): output of `create_fit_card`.
- `error` (str | None): set only when the loop terminates early; the caller (`app.py` / CLI) checks this **first**.

Flow of data between tools: `parsed` → `search_listings` → `search_results` → `selected_item` → `suggest_outfit` → `outfit_suggestion` → `create_fit_card` → `fit_card`.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Stop the pipeline. Set `session["error"]` to: *"No listings matched 'vintage graphic tee' under $30 in size M. Try raising your price, dropping the size filter, or using broader keywords (e.g. 'tee' instead of 'vintage graphic tee')."* Return the session without calling the styling tools. |
| suggest_outfit | Wardrobe is empty | Don't error. Branch to a general-advice LLM prompt and return styling ideas for the piece on its own ("this pairs well with relaxed denim and chunky sneakers for a casual vibe"), so the interaction still reaches `create_fit_card`. |
| create_fit_card | Outfit input is missing or incomplete | Guard first: if `outfit` is empty/whitespace, return a descriptive string ("Can't generate a fit card without an outfit suggestion — try a different query."). If the LLM call fails, fall back to a simple template caption built from `title`, `price`, and `platform`. Never raise. |

---

## Architecture

```
                    User query  +  wardrobe choice
                              │
                              ▼
          ┌──────────────────────────────────────────────────────┐
          │                  PLANNING LOOP (run_agent)            │
          │                                                       │
          │   Step 1: _new_session(query, wardrobe) ──► SESSION   │◄───────────┐
          │   Step 2: parse query  ──► session["parsed"]          │            │
          │                                                       │       SESSION STATE
          │   Step 3: search_listings(description, size, max_price)│      ┌──────────────┐
          │       │                                               │      │ query        │
          │       │  results == []                                │      │ parsed       │
          │       ├──► [ERROR] session["error"]="No listings…"    │─────►│ search_results│
          │       │            return session  ───────────────┐  │      │ selected_item │
          │       │                                            │  │      │ wardrobe      │
          │       │  results == [item, …]                      │  │      │ outfit_sugg.  │
          │       ▼                                            │  │      │ fit_card      │
          │   Step 4: selected_item = results[0] ──► SESSION    │  │      │ error         │
          │       │                                            │  │      └──────────────┘
          │       ▼                                            │  │            ▲
          │   Step 5: suggest_outfit(selected_item, wardrobe)  │  │            │
          │       │        (empty wardrobe → general advice)   │  │ writes ────┘
          │       ▼   session["outfit_suggestion"] = "…"       │  │
          │       │                                            │  │
          │   Step 6: create_fit_card(outfit_suggestion,       │  │
          │       │                   selected_item)           │  │
          │       ▼   session["fit_card"] = "…"                │  │
          │       │                                            │  │
          │   Step 7: return session ◄─────────────────────────┘  │
          └──────────────────────────────────────────────────────┘
                              │
                              ▼
          Return session  ──►  app.py / CLI renders:
            error set?  → show error message, two empty panels
            else        → show listing, outfit idea, fit card
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

I'll use **Claude** to draft each tool, one at a time, feeding it the exact section of this planning.md as the spec.

- **search_listings:** I'll paste the Tool 1 block (inputs, return shape, the "drop score-0 results" rule, and the empty-list failure mode) plus the `load_listings()` docstring, and ask Claude to implement it using `load_listings()` — no LLM. **Verify:** read the code to confirm it (a) filters by all three params, (b) lowercases for size/keyword matching, (c) drops zero-score listings, (d) returns `[]` rather than raising. Then test with 3 queries: `"vintage graphic tee", max_price=30` (expect tee listings, none > $30), `"combat boots", size="8"` (size filter works), and `"designer ballgown", max_price=5` (expect `[]`).
- **suggest_outfit:** I'll paste the Tool 2 block and the wardrobe schema, and ask Claude to write both prompt branches (empty vs. non-empty wardrobe) calling Groq via the `_get_groq_client()` helper. **Verify:** run once with `get_example_wardrobe()` (output must name real owned pieces) and once with `get_empty_wardrobe()` (must give general advice, no invented items, non-empty string).
- **create_fit_card:** I'll paste the Tool 3 block including the caption style rules. **Verify:** check the empty-`outfit` guard returns a string, then run twice on the same input to confirm higher temperature produces different captions that each mention item name, price, and platform once.

**Milestone 4 — Planning loop and state management:**

I'll give Claude the **Planning Loop**, **State Management**, and **Architecture diagram** sections together, plus the `run_agent` docstring, and ask it to implement `run_agent()` and the query-parsing step. **Verify:** confirm the early-return branch fires on empty search results (styling tools never called), confirm state flows only through the `session` dict, and run the CLI in `agent.py` for both the happy path and the no-results path. Then wire `handle_query()` in `app.py` and check all three panels render, including the error case showing a message with two empty panels.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Parse + Search:**
`run_agent` initializes the session and parses the query into `description="vintage graphic tee"`, `size=None`, `max_price=30.0`. It calls `search_listings("vintage graphic tee", size=None, max_price=30.0)`. The tool filters out anything over $30, scores by keyword overlap, and returns matching tops (e.g. the Y2K Baby Tee — Butterfly Print, $18, depop, and other graphic/vintage tees) sorted best-first. `session["search_results"]` now holds that non-empty list.

**Step 2 — Select + Suggest outfit:**
The results are non-empty, so the loop sets `session["selected_item"] = search_results[0]` (the top tee). It calls `suggest_outfit(selected_item, wardrobe)` with the example wardrobe. The LLM returns something like: *"Tuck the butterfly baby tee into your baggy straight-leg jeans and finish with the chunky white sneakers for an easy Y2K look. Layer the vintage black denim jacket over it when it's cooler."* This is stored in `session["outfit_suggestion"]`.

**Step 3 — Fit card:**
The loop calls `create_fit_card(outfit_suggestion, selected_item)`. The LLM returns a casual caption, e.g. *"found this y2k butterfly baby tee on depop for $18 and it's already my favorite 🦋 styled it with my baggy jeans + chunky sneakers — full fit in my stories."* Stored in `session["fit_card"]`. The loop returns the session with `error=None`.

**Final output to user:**
The UI shows three panels — the **top listing** (Y2K Baby Tee — Butterfly Print, $18, depop, excellent condition), the **outfit idea** (the styling text from Step 2), and the **fit card** caption from Step 3. If instead the search had returned `[]` (e.g. the "designer ballgown size XXS under $5" query), the user would see only the error message — *"No listings matched… try raising your price or broadening your keywords."* — and the outfit/fit-card panels would be empty.
