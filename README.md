# FitFindr 🛍️

FitFindr is a single-turn agent for secondhand fashion. You describe what you
want (optionally with a size and price ceiling and a note about your style); it
**searches** mock resale listings, **suggests an outfit** that pairs the best
find with pieces already in your wardrobe, and writes a casual, shareable
**fit-card** caption for it. If nothing matches your search, it stops and tells
you what to change — it never tries to style an empty result.

---

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash)   |  source .venv/bin/activate on Mac/Linux
pip install -r requirements.txt
```

Create a `.env` in the repo root (it's git-ignored — never commit it):

```
GROQ_API_KEY=your_key_here
```

Get a free key at [console.groq.com](https://console.groq.com). The two
LLM-backed tools use Groq's `llama-3.3-70b-versatile`.

### Run it

```bash
python app.py          # Gradio UI, opens at http://localhost:7860
python agent.py        # CLI: runs a happy-path and a no-results interaction
pytest tests/          # 10 tool tests, including every failure mode
```

---

## How it works

```
User query + wardrobe choice
        │
        ▼
   run_agent()  ── parse query ──► {description, size, max_price}
        │
        ├─► search_listings(description, size, max_price)
        │        │  results == []  ──►  set session["error"], RETURN early
        │        │                       (suggest_outfit is never called)
        │        ▼  results == [item, …]
        │   selected_item = results[0]
        │        │
        ├─► suggest_outfit(selected_item, wardrobe)  ──► outfit_suggestion
        │        │
        └─► create_fit_card(outfit_suggestion, selected_item)  ──► fit_card
        │
        ▼
   return session  ──►  UI renders 3 panels (or the error message)
```

### Planning loop — what decisions the agent makes

The loop ([`agent.py`](agent.py) → `run_agent`) is a fixed linear pipeline with
**one decision point**, not free-form tool selection. The order is always:
parse → search → (branch) → suggest → caption.

The only branch is on the **search result**:

- **`search_listings` returns `[]`** → the agent sets a specific, actionable
  message in `session["error"]` and returns immediately. It does **not** call
  `suggest_outfit` or `create_fit_card`, so `outfit_suggestion` and `fit_card`
  stay `None`. This is the behavior that makes the agent respond *differently*
  to different inputs.
- **`search_listings` returns matches** → the agent selects the top-ranked
  result (`results[0]`), styles it, captions it, and returns a fully populated
  session with `error = None`.

The loop "knows it's done" when it returns the session — either early (error
set) or after the caption step.

### State management

All state lives in one `session` dict created by `_new_session()` — the single
source of truth for an interaction. Tools never call each other or share
globals; the loop reads from and writes to `session` between every step, so each
tool's output becomes the next tool's input.

| field | set by | consumed by |
|-------|--------|-------------|
| `query` | caller | the parser |
| `parsed` (`{description, size, max_price}`) | `_parse_query` | `search_listings` |
| `search_results` (`list[dict]`) | `search_listings` | branch check, selection |
| `selected_item` (`dict`) | `results[0]` | `suggest_outfit`, `create_fit_card` |
| `wardrobe` (`dict`) | caller | `suggest_outfit` |
| `outfit_suggestion` (`str`) | `suggest_outfit` | `create_fit_card` |
| `fit_card` (`str`) | `create_fit_card` | UI |
| `error` (`str` or `None`) | loop, on empty search | UI (checked first) |

`selected_item` is passed by reference — `session["selected_item"] is
session["search_results"][0]` — so the exact dict that came out of the search is
the one that goes into both styling tools (no copying, no re-prompting).

---

## Tool inventory

### 1. `search_listings(description, size, max_price) -> list[dict]`

**Purpose:** Find listings matching the user's request. Pure/deterministic — no
LLM call.

**Inputs:**
- `description` (`str`) — free-text keywords, e.g. `"vintage graphic tee"`.
- `size` (`str | None`) — case-insensitive substring filter; `"M"` matches
  `"S/M"`. `None` skips size filtering.
- `max_price` (`float | None`) — inclusive price ceiling. `None` skips it.

**Output:** A `list[dict]` of full listing dicts (`id`, `title`, `description`,
`category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`,
`platform`), sorted by a weighted keyword-overlap score (matches in `title`/
`style_tags`/`category` weigh 2×, matches in `description`/`colors`/`brand`
weigh 1×). Listings scoring 0 are dropped. Returns `[]` when nothing matches.

### 2. `suggest_outfit(new_item, wardrobe) -> str`

**Purpose:** Style the chosen find against the user's wardrobe. LLM-backed.

**Inputs:**
- `new_item` (`dict`) — a listing dict (uses its title, category, colors, tags).
- `wardrobe` (`dict`) — `{"items": [ {id, name, category, colors, style_tags,
  notes}, … ]}`. May be empty.

**Output:** A non-empty `str`. With a stocked wardrobe it names specific owned
pieces and gives a styling tip; with an empty wardrobe it returns general
styling advice (no invented items).

### 3. `create_fit_card(outfit, new_item) -> str`

**Purpose:** Write a casual social-media caption for the find. LLM-backed,
temperature `1.0` so repeated calls vary.

**Inputs:**
- `outfit` (`str`) — the suggestion from `suggest_outfit`.
- `new_item` (`dict`) — the listing dict (for name, price, platform).

**Output:** A 2–4 sentence caption `str` mentioning the item name, price, and
platform once each. If `outfit` is empty/whitespace, returns a descriptive
error-message string instead.

---

## Error handling

Each tool degrades gracefully instead of raising; the loop turns the one
unrecoverable case (no listings) into an early return.

| Tool | Failure mode | Response | Concrete example from testing |
|------|--------------|----------|-------------------------------|
| `search_listings` | No match | Returns `[]`; the loop sets `session["error"]` and stops before styling | `search_listings('designer ballgown', size='XXS', max_price=5)` → `[]`, and the agent replies: *"No listings matched 'designer ballgown' under $5 in size XXS. Try raising your price, dropping the size filter, or using broader keywords…"* |
| `suggest_outfit` | Empty wardrobe | Branches to a general-advice prompt; never returns `""` | With `get_empty_wardrobe()`: *"This adorable Y2K Baby Tee is perfect for a playful, nostalgic look… pairs well with high-waisted pants, flowy skirts, or distressed denim…"* (general advice, no invented items) |
| `create_fit_card` | Empty/whitespace outfit | Returns a descriptive message string before any LLM call | `create_fit_card('', item)` → *"Can't generate a fit card without an outfit suggestion — try a different query so I have a look to caption."* |

Both LLM tools also wrap the API call in `try/except` and return a usable
fallback string if Groq is unreachable, so a network blip never crashes the
agent.

---

## AI usage

I used **Claude** to implement the code from the specs I wrote in
[`planning.md`](planning.md). Two specific instances:

1. **`search_listings` (Tool 1).** *Input:* the Tool 1 spec block (parameters,
   the weighted-scoring + drop-score-0 rules, the empty-list failure mode) plus
   the `load_listings()` docstring. *Produced:* a filter-then-score
   implementation. *What I changed:* the first draft scored every field equally,
   so a keyword buried in a description ranked the same as one in the title — I
   added 2× weighting for `title`/`style_tags`/`category` and a stop-word list
   so filler words like "looking"/"want" didn't inflate scores. I also added the
   "no usable keywords → return the size/price-filtered set" guard.

2. **Planning loop (`run_agent`).** *Input:* the Planning Loop + State Management
   sections and the architecture diagram from `planning.md`. *Produced:* the
   linear pipeline with the early-return branch. *What I overrode:* the draft
   called all three tools and only checked for emptiness at the end — I moved the
   `if not search_results:` check to **before** `suggest_outfit` so the styling
   tools are genuinely skipped, and verified it with `selected_item is
   search_results[0]` and the no-results test leaving `fit_card` as `None`.

---

## Spec reflection

The spec held up well: the `session`-dict design meant wiring the loop was just
"write field, read field," and the single search-result branch was the only real
control flow. The one thing I underestimated in planning was **query parsing** —
I'd written "regex/string parsing" without detailing it, and in practice I had
to add guards so a bare number like the `"8"` in `"combat boots size 8"` is read
as a *size*, not a *price* (a price needs a `$` or a word like "under"/"dollars"
nearby). Tightening the spec there would have saved a debugging pass.

---

## Project layout

```
agent.py              run_agent() planning loop + _parse_query() + session state
tools.py              search_listings, suggest_outfit, create_fit_card
app.py                Gradio UI + handle_query()
tests/test_tools.py   10 pytest tests (happy paths + every failure mode)
conftest.py           puts repo root on sys.path for the tests
data/                 listings.json (40 mock listings) + wardrobe_schema.json
utils/data_loader.py  load_listings(), get_example_wardrobe(), get_empty_wardrobe()
planning.md           the spec this implementation was built from
```
