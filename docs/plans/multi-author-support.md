# Implementation Plan: Multi-Author Support for Improvement Proposals

## Summary

Add support for proposals (KIPs and FLIPs) that have multiple authors. Currently the
author shown on the site is the Confluence page *creator* (`history.createdBy`), which is
wrong for larger proposals authored by several people. We will parse explicit author
declarations from the wiki page bodies, merge them with the page creator (fuzzy-deduped),
and expose the result as a new `authors` field in the caches, JSON API, detail pages, and
main index pages (replacing the "Created by" column with an "Author(s)" column and a
multi-value author filter).

## Design Decisions (agreed)

1. **`created_by` is kept** everywhere (page creator) — it is useful provenance
   information for the JSON API and detail pages.
2. **`authors` is the merged, deduplicated list** of:
   - the page creator (`created_by`, first in the list),
   - names from an explicit "Author(s):" declaration on the wiki page, and
   - names from "Co Author(s):" declarations.
   Duplicates are removed using exact (case-insensitive) matching first, then fuzzy
   name matching via `rapidfuzz.fuzz.token_sort_ratio` (same approach as
   `ipper/common/keys.py`, but with a **higher default threshold of 85** because
   falsely merging two *distinct* authors is worse than a near-duplicate surviving).
3. **If the wiki page lists no authors**, `authors == [created_by]`.
4. **Main index pages show "Author(s)" instead of "Created by"**, and the filter
   dropdown lists individual names only; a row with multiple authors matches the
   filter when the selected author is one of its authors (partial membership).
5. **JSON API / detail pages keep `created_by`** and gain an additive `authors` field
   (non-breaking change).

## Research Findings: Author Formats in the Wild

Live pages were fetched from the Confluence REST API to catalogue the formats we must
parse.

### Kafka (paragraph-based, near the top of the page)

| Example | Observed HTML shape |
|---|---|
| KIP-1279 | `<p><span><strong>Authors</strong>: Luke Chen, Federico Valeri, Omnia Ibrahim, Gaurav Narula</span></p>` (plain, comma-separated) |
| KIP-1165 | `<strong>Authors:</strong> Greg Harris, Ivan Yurchenko, Jorge Quilcate, ...` (colon inside the bold label) |
| KIP-1134 | `<strong>Authors: </strong><em>Daniel Urban, Gergely Harmadas, ...</em>` (names inside `<em>`) |
| KIP-1303, KIP-1360 | names split across nested styled `<span>` elements |
| KIP-1320 | `<strong>Authors:</strong> Eric Chang<br/><strong>Discussion thread:</strong> ...` — **single paragraph shared with other fields, `<br/>`-separated** |
| KIP-1255 | `<strong>Co Author: </strong><a class="confluence-userlink">Satish ...</a>` — supplementary co-author as a Confluence user-mention link |

### Flink (summary-table-row-based)

| Example | Observed HTML shape |
|---|---|
| FLIP-588 | `<tr><th>Authors</th><td><p><a class="confluence-userlink">Aleksandr Savonin</a> , <a class="confluence-userlink">Alan Sheinberg</a></p></td></tr>` |

Notes:

- The FLIP summary table (already parsed by `_enrich_flip_info`) can carry an
  `Authors` row with comma-separated user-mention links.
- A full-text CQL search finds ~72 KAFKA-space and ~82 FLINK-space pages mentioning
  "authors" (including non-proposal pages), so this affects a modest but real subset.
- Key parsing implications: work from **text content** (BeautifulSoup `.text` collapses
  nested spans/anchors), split on `,` / ` and ` / `;`, and cut at known stop phrases
  ("discussion thread", "vote thread", "jira") for paragraphs that share fields.

---

## Implementation Steps

### Step 1 — Shared author utilities

**New file: `ipper/common/authors.py`**

```python
"""Parsing and deduplication of improvement proposal authors."""

import logging
import re

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Matches "Author", "Authors", "Co-Author", "Co Author", "Co-authors", etc.
AUTHOR_LABEL_PATTERN: re.Pattern = re.compile(
    r"^\s*(?:co[\s-]+)?authors?\s*[:：]?\s*", re.IGNORECASE
)

# Text that ends an author list when the paragraph contains other fields
# (e.g. KIP-1320: "Authors: Eric Chang<br/>Discussion thread: ...")
STOP_PHRASES: list[str] = ["discussion thread", "vote thread", "jira"]

# Delimiters between names in a list
NAME_DELIMITER_PATTERN: re.Pattern = re.compile(r"\s*(?:,|;|\band\b)\s*")

FUZZY_DEDUPE_THRESHOLD: float = 85.0


def parse_authors_from_text(text: str) -> list[str]:
    """Parse individual author names from the text following an author label.

    Handles comma / semicolon / " and " separated lists, trims whitespace,
    removes empty entries, and cuts the list at known stop phrases
    ("discussion thread", "vote thread", "jira") so that paragraphs which
    share fields with the author line (KIP-1320 style) parse correctly.
    """

def is_author_line(text: str) -> bool:
    """True if the paragraph/cell text starts with an author label
    ("Authors:", "Co-Author:", etc.)."""

def dedupe_authors(
    names: list[str], threshold: float = FUZZY_DEDUPE_THRESHOLD
) -> list[str]:
    """Deduplicate author names, preserving first-occurrence order.

    1. Normalise (strip + casefold) and drop exact duplicates.
    2. Fuzzy-dedupe each remaining name against already-kept names using
       rapidfuzz.fuzz.token_sort_ratio; names scoring >= threshold are
       considered duplicates and dropped. Every fuzzy merge is logged
       (kept name, dropped name, score) for auditability.
    """
```

Implementation notes:

- `parse_authors_from_text` should locate the stop phrase with a case-insensitive
  search **from the left** (the phrases only appear after the name list when the
  paragraph is shared), then split the remainder on `NAME_DELIMITER_PATTERN`.
- Names must be stripped of trailing punctuation (`,`, `;`, `.`) and zero-width
  characters that Confluence sometimes emits inside styled spans.
- Where to draw the line on `and`: only treat the word "and" as a delimiter when it
  is surrounded by whitespace (regex above), so names containing "and" as a
  substring (e.g. "Anderson") are safe.

### Step 2 — Kafka wiki parsing

**File: `ipper/kafka/wiki.py`**

1. In `enrich_kip_info()`, extend the existing paragraph loop to detect author
   lines. The loop already iterates `parsed_body.find_all("p")` and pattern-matches
   on `para.text.lower()`; add branches:

   ```python
   elif "authors" in para.text.lower() and is_author_line(para.text):
       # extract names from para.text after the label
   elif "co author" in para.text.lower() and is_author_line(para.text):
       # co-authors, same extraction
   ```

   Because `para.text` flattens nested `<span>`/`<em>`/`<a>` elements, the
   KIP-1134/KIP-1303/KIP-1360 nested-markup cases and KIP-1255 user-link case
   are handled by the same text-based extraction.

2. Use only the **first matching paragraph of each kind** (mirroring the existing
   `state_processed` / `jira_processed` flag pattern) to avoid picking up prose
   mentions of "authors" later in the document.

3. Store the raw parsed names in local variables during `enrich_kip_info` and set
   them on `child_dict` (e.g. `child_dict["wiki_authors"]`,
   `child_dict["wiki_co_authors"]`).

4. In `process_child_kip()`, assemble the final field **after** enrichment:

   ```python
   child_dict["authors"] = dedupe_authors(
       [
           child_dict["created_by"],
           *child_dict.pop("wiki_authors", []),
           *child_dict.pop("wiki_co_authors", []),
       ]
   )
   ```

   - `pop()` keeps the intermediate keys out of the persisted cache dict — the
     cache stores only the final merged `authors` list (minimal-change /
     lean-cache principle).
   - Result: creator first, explicit authors and co-authors appended,
     duplicates removed; no author info → `authors == [created_by]`.
   - `created_by` is left untouched for compatibility.

5. **Type annotations (MyPy):** the wiki cache starts storing `list[str]`
   values, so widen the annotations in this file:
   - `get_kip_information()` return type:
     `dict[int, dict[str, int | str]]` → `dict[int, dict[str, int | str |
     list[str]]]` — update **both** occurrences (the signature and the
     `output` comprehension annotation when loading the cache file).
   - `process_child_kip()`'s local `child_dict` declaration
     (`dict[str, list[str] | str | int]`) already permits `list[str]`; add a
     matching return annotation so callers stay type-safe.

### Step 3 — Flink wiki parsing

**File: `ipper/flink/wiki.py`**

1. In `_add_row_data()`, add an `"author"` branch alongside the existing
   `"discussion"` / `"vote"` / `"jira"` / `"release"` routing:

   ```python
   if "author" in header:
       # extract names from row_data.text (cell text flattens the
       # confluence-userlink anchors, FLIP-588 style)
       flip_dict["wiki_authors"] = parse_authors_from_text(row_data.text)
       return
   ```

   Note the FLIP-588 cell text is `Aleksandr Savonin , Alan Sheinberg` —
   the comma-delimited split handles this directly.

2. In `_enrich_flip_info()`, initialise `flip_dict["wiki_authors"] = []` with the
   other defaults so the key always exists (mirrors the existing
   `UNKNOWN_STR`-style default pattern).

3. In `process_child_kip()`, assemble `authors` exactly as in Step 2
   (creator + wiki_authors, fuzzy-deduped, `pop()` the intermediate key).

4. **Type annotations (MyPy):** `get_flip_information()` is currently
   unannotated; annotate it (and its `output` / `existing_cache` types) with
   the same widened union as Kafka (Step 2): `dict[int, dict[str, int | str |
   list[str]]]`, so the new `list[str]` cache values stay type-checked.
   (`process_child_kip()`'s local declaration already allows `list[str]`.)

### Step 4 — Data models

**File: `ipper/common/models.py`**

Add an additive field to both models (docstrings updated):

```python
class ProposalSummary(BaseModel):
    ...
    created_by: str          # unchanged: wiki page creator
    authors: list[str]       # NEW: merged, deduplicated author list
    ...

class ProposalDetail(BaseModel):
    ...
    created_by: str          # unchanged
    authors: list[str]       # NEW
    ...
```

`KipDetail` / `FlipDetail` inherit the field; no other model changes.

### Step 5 — Output pipeline (Kafka)

**File: `ipper/kafka/output.py`**

1. `create_status_dict()` (~line 138): add

   ```python
   status_entry["authors"] = kip_data.get("authors", [kip_data["created_by"]])
   ```

   (the `.get()` fallback makes `kafka output` robust against pre-existing caches
   that have not yet been backfilled).

2. `kip_to_detail()` (~line 300) and `kip_to_summary()` (~line 340): add

   ```python
   authors=wiki_entry.get("authors", [wiki_entry["created_by"]]),
   ```

3. **Type annotations (MyPy):** `create_status_dict()` declares
   `status_entry` (and its return type) as
   `dict[str, int | str | None | KIPStatus | list[dict[str, str]]]` — storing
   `authors: list[str]` in it **fails MyPy**. Widen those unions with
   `| list[str]`. `kip_to_detail()` / `kip_to_summary()` take untyped dicts
   and need no changes.

### Step 6 — Output pipeline (Flink)

**File: `ipper/flink/output.py`**

Apply the same changes at lines ~191 and ~234 (the `FlipDetail` / `ProposalSummary`
constructions): populate `authors=flip_data.get("authors", [flip_data["created_by"]])`.

No annotation changes needed here — the Flink converters take untyped dicts;
the widened unions only concern the Kafka status dict (Step 5).

### Step 7 — TableFilter multi-value support

**File: `templates/assets/table-filter.js`**

Current behaviour (which would **break** with multi-author values):

- `populateFilters()` adds each unique attribute *string* as one dropdown option →
  a combined `"Luke Chen, Federico Valeri, ..."` value would appear as a single
  giant entry.
- `applyFilters()` matches with exact equality (`rowValue === filterValue`) →
  selecting "Luke Chen" would not match a row holding the multi-name string.

Changes:

1. Extend the column config with an optional `multi` flag:

   ```js
   columns: [
       { id: 'state', label: 'State', dataAttr: 'data-state' },
       { id: 'author', label: 'Author', dataAttr: 'data-authors', multi: true }
   ]
   ```

2. New helper `getRowValues(row, col)`:

   ```js
   function getRowValues(row, col) {
       const raw = row.getAttribute(col.dataAttr);
       if (!raw || raw.trim() === '') return [];
       if (col.multi) {
           try {
               return JSON.parse(raw);
           } catch (e) {
               // Tolerate legacy non-JSON values: treat as single value
               return [raw];
           }
       }
       return [raw];
   }
   ```

3. `populateFilters()`: for multi columns, iterate `getRowValues(...)` and add
   each individual name to the unique set — the dropdown lists **individual names
   only**, deduplicated and alphabetically sorted.

4. `applyFilters()`: for multi columns, a row matches when
   `getRowValues(row, col).includes(filterValue)`; single-value columns keep the
   existing exact-equality behaviour (fully backwards compatible for the State
   and Component filters).

### Step 8 — Main index templates

**Files: `templates/kafka-index.html.jinja`, `templates/flink-index.html.jinja`**

1. Replace the "Created by" `<th>` with `Author(s)`.
2. Replace the author `<td>` cell with `{{ kip['authors']|join(", ") }}`
   (respectively `flip['authors']`).
3. Replace the row attribute:

   ```jinja
   data-authors="{{ kip['authors']|tojson|e }}"
   ```

   (drop `data-created-by`).
4. Update the `TableFilter.init` config to:

   ```js
   { id: 'author', label: 'Author', dataAttr: 'data-authors', multi: true }
   ```

5. CSS (`templates/style.css`): add a `max-width` (e.g. `16rem`) with word-wrap
   to the author column so nine-name lists (KIP-1165) don't blow up the table
   layout.

### Step 9 — Detail page templates

**Files: `templates/kip-more-info.html.jinja`, `templates/flip-more-info.html.jinja`**

Both templates iterate `dict.items()` generically, so a list value would currently
render as `['A', 'B']`. Add a list-handling branch in the value cell:

```jinja
{% if value is string %}
    ... existing link/plain rendering ...
{% elif value is sequence %}
    {{ value|join(", ") }}
{% else %}
    {{ value }}
{% endif %}
```

`created_by` continues to render as its own row ("who created the wiki page");
`authors` renders as the merged list. No filtering needed — the generic loop picks
both keys up automatically.

### Step 10 — Skill documentation

**File: `templates/skill/ossip/SKILL.md`**

- Add `authors` to the documented field lists for the summary and detail JSON
  (both `kips.json` / `flips.json` summaries and `kips/{id}.json` details).
- Document `created_by` explicitly as "name of the wiki page creator" and
  `authors` as "merged, deduplicated list of proposal authors (creator + any
  authors/co-authors declared on the wiki page)".
- Update any filter examples (`filter created_by = "alice"` → also usable with
  `authors contains "alice"`).

### Step 11 — Cache backfill

New `authors` keys must be backfilled into the existing caches. Both incremental
update paths currently skip unmodified entries:

- Kafka — `get_kip_information()` (`ipper/kafka/wiki.py`): in the `elif update:`
  branch, extend the reprocess condition:

  ```python
  cached_modified = output[kip_id].get("last_modified_on")
  api_modified = child["history"]["lastUpdated"]["when"]
  if cached_modified != api_modified or "authors" not in output[kip_id]:
      output[kip_id] = process_child_kip(kip_id, child)
  ```

- Flink — `get_flip_information()` (`ipper/flink/wiki.py`): **fold the
  backfill into the existing skip condition** rather than inserting a
  separate `if "authors" not in ...: continue` guard. The skip lives inside
  `if created_date < refresh_cutoff:` (after a `try` that parses the cached
  `created_on`); a standalone guard placed inside or after that block would
  only ever backfill FLIPs created within the 60-day refresh window. Skip
  only when **both** conditions hold:

  ```python
  # Skip only if outside the refresh window AND already backfilled
  if created_date < refresh_cutoff and "authors" in output[flip_id]:
      logger.info(
          "Skipping FLIP-%s (created %s, outside %s-day refresh window)",
          flip_id,
          created_on_str,
          refresh_days,
      )
      continue
  ```

  An old FLIP without `authors` now falls through to the existing
  `output[flip_id] = process_child_kip(flip_id, child)` and is backfilled
  (the `else` branch's "created recently" log fires for these — reword it,
  e.g. "Refreshing FLIP-%s (recent or missing authors)"). The
  `except (KeyError, ValueError)` branch (unparseable `created_on`) already
  reprocesses, which backfills those entries too.

Verified properties of this guard approach:

- **No extra API cost** — `child_page_generator()` already fetches every
  child page with `expand=history.lastUpdated,body.view` on each update run,
  so the page body needed for author parsing is already in memory; backfill
  reprocessing is BeautifulSoup CPU only. The backfilling CI run has the
  same network profile as a normal update.
- **Completes in a single run** — update iterates every child page
  regardless of modification state, so the first `kafka update` /
  `flink update` after merging backfills the entire cache.
- **Self-clearing** — once `authors` is written (including
  `authors == [created_by]` for author-less pages), the guard never
  re-triggers; the cost is one-time.
- **Deployed site is consistent from day one** — CI runs `update` before
  `output` in the same job, so the first published pages render from
  backfilled caches; the `.get()` fallbacks in Steps 5–6 only matter for
  local renders against a stale checkout.
- **`refresh` does *not* backfill** — `kafka refresh` / `flink refresh`
  reprocess *mbox* archives only and never touch the wiki caches. Only
  `update` (with this guard) or `wiki download --overwrite` regenerate wiki
  cache entries — don't reach for `refresh` when backfilling.
- **Orphaned entries never backfill** — cached entries whose wiki page no
  longer appears in the child listing (deleted/renamed pages, or titles that
  no longer match the KIP/FLIP pattern) never have the guard applied and
  fall back to `authors == [created_by]` forever via the output-layer
  `.get()`. Rare, but "every entry backfilled after one run" is not strictly
  true for these.

The in-code guard is the primary backfill mechanism; a one-time manual
`kafka wiki download --overwrite` / `flink wiki download --overwrite` is
**not** needed — it buys nothing over the guard (CI backfills before
rendering), while the guard additionally protects against partially failed
runs and any future cache regeneration. Keep `--overwrite` only as a manual
escape hatch for a corrupted cache.

### Step 12 — Tests

**New file: `tests/common/test_authors.py`**

- `is_author_line` / `parse_authors_from_text`:
  - each real-world format from the research table as an HTML-snippet fixture:
    KIP-1279 (plain), KIP-1165 (colon in label), KIP-1134 (italic), KIP-1320
    (shared paragraph — must stop at "Discussion thread"), KIP-1255
    (co-author, single name), FLIP-588 (`"A , B"` comma style),
  - " and " delimiter, trailing punctuation, empty/absent label.
- `dedupe_authors`:
  - exact duplicates and case differences collapse,
  - "Greg Harris" vs "Gregory Harris" collapses (fuzzy),
  - "Tom Cooper" vs "Tim Cooper" must **not** collapse (threshold check),
  - first-occurrence ordering preserved.

**New tests: `tests/kafka/test_wiki.py` (extend existing file)**

- `enrich_kip_info` with a multi-author body sets `wiki_authors` /
  `wiki_co_authors`; `process_child_kip` produces the merged `authors` list
  (creator first), dedupes a repeated creator, and falls back to
  `[created_by]` for author-less pages.

**New file: `tests/flink/test_wiki.py`**

- `_add_row_data` handles an `Authors` table row (FLIP-588 snippet);
  `process_child_kip` merges and falls back correctly.

**New tests: backfill guards (Step 11)**

- `tests/kafka/test_wiki.py`: `get_kip_information` with `update=True` and a
  cached KIP whose `last_modified_on` is unchanged but which lacks `authors` →
  the entry is reprocessed and gains `authors`; a cached KIP that already
  has `authors` (and an unchanged `last_modified_on`) → not reprocessed.
  Mock `child_page_generator` and `process_child_kip`.
- `tests/flink/test_wiki.py`: a cached FLIP created **outside** the refresh
  window and lacking `authors` → *not* skipped (backfilled); the same FLIP
  with `authors` present → skipped; a FLIP inside the window → refreshed
  either way. Mock `child_page_generator` and `process_child_kip`.
- These conditions are exactly the kind that silently regress when the
  update paths are refactored; the tests pin the placement requirement
  above.

**Extend: `tests/common/test_models.py`, `tests/kafka/test_json_api.py`,
`tests/flink/test_json_api.py`, `tests/common/test_api_output.py`**

- Fixtures gain `authors` lists; assert the field round-trips into the
  generated JSON.

**Manual verification**

- Render the Kafka and Flink index pages locally
  (`local_build.sh` or the `output` subcommands) and confirm:
  - the Author(s) column, JSON `data-authors` attribute, and multi-select
    filter behave (individual names in the dropdown; selecting one name
    shows every proposal they authored),
  - detail pages show both `created_by` and the joined author list.
- Run `uv run ruff check .` and the full test suite
  (`uv run pytest`), plus MyPy since type hints are required.

---

## Rollout Order

1. `ipper/common/authors.py` + unit tests (no callers yet — safe).
2. `ipper/kafka/wiki.py` + `ipper/flink/wiki.py` parsing and assembly + tests.
3. Cache backfill guards (Step 11).
4. Models and output pipelines (Steps 4–6).
5. `table-filter.js` multi-value support (Step 7).
6. Templates and skill docs (Steps 8–10).
7. Full test suite, ruff, mypy.
8. Local render + manual filter verification.
9. Commit; CI's daily `kafka update` / `flink update` backfills the caches and
   publishes.

## Risks & Edge Cases

- **False-positive author lines**: prose containing "authors" mid-paragraph is
  excluded by anchoring the label match to the start of the paragraph/cell and
  taking only the first match of each kind.
- **Fuzzy over-merging**: mitigated by the 85 threshold + audit logging of every
  merge; distinct-name tests guard the regression.
- **Old caches**: `.get("authors", [created_by])` fallbacks in the output layer
  keep `output` commands working on un-backfilled caches.
- **Orphaned cache entries**: entries whose wiki page no longer appears in
  the child listing (deleted/renamed) are never reprocessed, so they
  permanently fall back to `authors == [created_by]` via the output-layer
  `.get()` (see Step 11) — "everything backfilled after one run" is not
  strictly true.
- **`refresh` does not backfill**: `kafka refresh` / `flink refresh`
  reprocess mbox archives only; the wiki caches only change via `update`
  (with the Step 11 guard) or `wiki download --overwrite`.
- **Dropdown size**: the author dropdown grows to the union of individual author
  names (same order of magnitude as the current created-by list); no
  regression expected.
- **Long author lists**: column `max-width` CSS keeps the table layout intact.
