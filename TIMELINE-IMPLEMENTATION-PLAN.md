# Implementation Plan: Proposal Timeline Page + Public Events JSON API

This document is a complete, self-contained implementation plan for adding two
related features to OSSIP:

1. **A public Events JSON API** — the proposal event log
   (`cache/events/events.jsonl`) published under `/api/v1/` for both the
   timeline page and AI agents.
2. **A human-facing Timeline page** (`timeline.html`) — a vertical
   line-and-node timeline with summary cards, infinite scroll over the full
   history (newest-first), and filters.

An implementing agent should be able to complete this from this document plus
the referenced existing code. Read [`AGENTS.md`](AGENTS.md) and
[`docs/event-log.md`](docs/event-log.md) first — the event-log doc is the
canonical reference for the log's schema and consumer API.

---

## 1. Approved design decisions (do not change without asking)

These were explicitly confirmed by the maintainer:

| # | Decision |
|---|----------|
| 1 | Timeline shows **full history** (including `backfilled` events back to KIP-1 in 2015), in **reverse chronological order** (newest first). |
| 2 | **All 7 event types are shown by default**; users can hide types via filters. |
| 3 | **Infinite scroll** through the entire history. |
| 4 | Event log is **published as JSON API** (client-side fetch), not embedded in the HTML. API docs (`api.html`) and agent skill (`SKILL.md`) are updated accordingly. |
| 5 | **One global timeline page**, linked from the landing page, with per-project filter options. **Each project's index page links to the global timeline pre-filtered to that project** (via URL query param). |
| 6 | **Vertical line + nodes** visual style with summary cards. Cards link to the proposal detail pages on ossip.dev (which carry the upstream wiki/PR links). |
| 7 | Filters for **all reasonable dimensions**: project, event type, text search, backfill toggle. |
| 8 | Event cards link to **current** detail pages (resolved through `latest_snapshot` so renumbered proposals link correctly). |
| 9 | Page filename: **`timeline.html`**. |
| 10 | The timeline is for humans; agents consume the **events JSON** (documented in the skill). |

Additional defaults chosen during planning (reasonable to adjust during
implementation if they conflict with reality):

- Endpoint path: `/api/v1/events/events.json` (sibling layout of
  `kafka/kips.json`).
- Display text (`headline`, `summary`) is **precomputed server-side** from the
  existing `ipper.events.presentation` helpers so JS and social wording can
  never diverge, and agents get ready-made display strings.
- Backfilled events are shown inline with a subtle "backfilled" badge and a
  filter toggle to hide them.
- A single JSON file for all events (~3,800 events today ≈ 1.5 MB raw,
  ~200 KB gzipped; GitHub Pages serves gzip). No per-project JSON files in v1.

---

## 2. Context: what exists today

### The event log

- `cache/events/events.jsonl` — append-only JSONL, one `EventRecord` per line
  (`ipper/events/models.py`), currently ~3,809 events, full history retained
  forever, committed to git. `docs/event-log.md` §3 is the field reference.
- Fields: `schema_version, seq, stable_id, project, key, event_type,
  reference, title, state_before, state_after, observed_at, effective_at,
  effective_at_source, detail_url, reference_before, backfilled`.
- 7 event types (`EventType`): `new`, `state_changed`, `renumbered`,
  `disappeared`, `first_approval`, `changes_requested`, `vote_started`.
- `observed_at` = detection run time (always present); `effective_at` =
  best-known actual change time (may be absent). Display/ordering must use
  `presentation.event_time()` = `effective_at or observed_at`.

### Consumer helpers (`ipper/events/`, import from package root)

- `load_events(events_file=None)` / `read_events` — whole log as
  `list[EventRecord]`, skips corrupt lines.
- `newest_first(events, limit=None)` — sort by `(event_time, seq)` descending.
- `filter_events(events, project=, types=, since=, until=, include_backfilled=)`.
- `max_seq(events)` — head seq (0 if empty).
- `latest_snapshot(key, seen_file=None)` — a proposal's **current**
  `SeenSnapshot` (reference/`detail_url`) from `last_seen.json`, or `None`.
- `presentation`: `headline(event, include_project=False)`,
  `summary_text(event)`, `event_time(event)`, `display_state(state)`.

### Site / build architecture (constraints)

- Fully static site on GitHub Pages. Standalone HTML pages; **vanilla JS in
  `templates/assets/`, no build step** (existing examples:
  `table-filter.js`, `table-sort.js`, `theme-toggle.js`).
- Light/dark theme: `data-theme="light"` attribute + CSS variables in
  `templates/style.css`; bootstrap snippet + `theme-toggle.js` on every page.
- Project index pages are Jinja2-rendered (`kafka-index.html.jinja`,
  `flink-index.html.jinja`, `github-index.html.jinja` — the GitHub one is
  shared by strimzi/streamshub/kroxylicious). Static pages (`index.html`,
  `api.html`, `skills.html`) are copied verbatim by CI.
- JSON API lives in `site_files/api/v1/`; per-project summaries under
  `<project>/`, schemas under `schemas/`, index at `index.json`
  (`generate_api_index` in `ipper/common/api_output.py`, currently
  `ApiIndex` version 2).
- Build is driven by `.github/workflows/publish.yaml` and `local_build.sh`
  (mirror each other).
- Project metadata for display names/prefixes: `SOCIAL_PROJECTS` in
  `ipper/common/projects.py` (keys: `kafka`, `flink`, `strimzi`,
  `streamshub`, `kroxylicious`).

### Known gotchas

- `ipper/events/__init__.py` exports everything except models **lazily** via
  `__getattr__` (to break an import cycle with `ipper.social`). Do not "fix"
  this by adding eager imports. Importing `from ipper.events.models import X`
  directly is fine (models.py imports nothing from the app).
- `stable_id` is computed once at append and stored; consumers must never
  recompute it.
- `event_type` is a plain `str` by design; readers must tolerate unknown
  values (this includes the timeline page — render unknown types with a
  generic badge).
- Events' `detail_url` values are absolute `https://ossip.dev/...` URLs. The
  timeline must convert same-origin URLs to paths so links work on any
  deployment origin (see §5.3).
- CI gates (all three must pass before commit):
  `uv run ruff check ipper/ tests/`,
  `uv run ruff format --check ipper/ tests/`,
  `uv run pytest`.

---

## 3. Architecture after this change

```
cache/events/events.jsonl ── events output ──▶ site_files/api/v1/events/events.json
                                                    │
                                                    ├─ fetched by timeline.html (assets/timeline.js)
                                                    └─ consumed by AI agents (documented in api.html / SKILL.md)

index.json (ApiIndex v3) ─── gains events entry (url, count, latest_seq, last_event_at)

site_files/timeline.html ◀── copied from templates/timeline.html
kafka.html / flink.html / github-*.html ── nav link "Timeline" → timeline.html?project=<key>
index.html ── top-links "Timeline" → timeline.html
```

Build order matters: **the events API must be generated before
`generate_api_index` runs**, because the index reads `events.json` to
populate its new `events` entry.

---

## 4. Phase 1 — Events JSON API

### 4.1 New models (`ipper/events/models.py`)

Add two models. `ApiEvent` extends `EventRecord` with **additive display
fields only** (the verbatim log fields remain the versioned contract):

```python
class ApiEvent(EventRecord):
    """An EventRecord enriched for the public JSON API and timeline page."""

    event_time: str            # presentation.event_time(): effective_at or observed_at
    headline: str             # presentation.headline(event, include_project=True)
    summary: str              # presentation.summary_text(event)
    current_reference: str | None = None  # from latest_snapshot(); None if unknown
    current_detail_url: str | None = None  # from latest_snapshot(); None if unknown


class EventsDocument(BaseModel):
    """Root of /api/v1/events/events.json."""

    model_config = ConfigDict(extra="allow")

    version: int = 1
    generated_at: str         # YYYY-MM-DDTHH:MM:SSZ, build time
    count: int               # len(events)
    latest_seq: int          # max seq in the log (0 if empty)
    events: list[ApiEvent]   # newest-first
```

Notes:

- `headline(..., include_project=True)` produces e.g.
  `"Kafka KIP-123 accepted — <title>"`. Keep project inclusion **on** for the
  API: the timeline is a global feed and each card needs the project name
  anyway; agents benefit too. (If `SOCIAL_PROJECTS[event.project]` raises
  `KeyError` for some future project, fall back to the raw key — wrap the
  call.)
- Do **not** recompute `stable_id` or reorder fields; serialization keeps all
  `EventRecord` fields as-is (subclassing preserves field order, extra
  `extra="allow"` is inherited).

### 4.2 New emitter (`ipper/events/output.py`, new file)

```python
def enrich_event(event: EventRecord, seen_file: Path | None = None) -> ApiEvent:
    """Attach display fields + current reference/URL to one event."""

def generate_events_api(
    api_dir: str | Path,
    events_file: Path | None = None,   # defaults to store.EVENTS_FILE
    seen_file: Path | None = None,     # defaults to store.SEEN_FILE (pass through to latest_snapshot)
) -> Path:
    """Write api_dir/events.json (newest-first, enriched). Returns the path."""
```

Behavior:

1. `events = load_events(events_file)`; if the file is missing or the log is
   empty, still write a valid document (`count: 0`, `latest_seq: 0`,
   `events: []`) — the site must not fail because the log is empty (mirror
   `generate_api_index`'s resilience).
2. `ordered = newest_first(events)`.
3. Enrich each event (see 4.1). `latest_snapshot` lookups are cheap (one
   `load_seen` per event is wasteful — load `last_seen.json` once and index by
   key, or call `load_seen(seen_file)` once and pass the map; keep the
   public signature simple, memoize internally).
4. Write `api_dir/events.json` with the same style as
   `api_output.write_json_file` (`model_dump_json(indent=2)`), creating the
   directory. Either widen `write_json_file`'s type annotation to include
   `EventsDocument` or just inline the two-liner here (preferred — avoids
   touching `api_output`'s union type).
5. Also export schemas: extend `models_to_export` in
   `api_output.write_schemas` with `(ApiEvent, "ApiEvent.schema.json")` and
   `(EventsDocument, "EventsDocument.schema.json")`. Import them from
   `ipper.events.models` directly (import-cycle-safe, see §2 gotchas).

`latest_snapshot` returns `None` for keys no longer tracked (e.g. a proposal
that later disappeared): then `current_*` are `None` and consumers fall back
to the event-time `reference`/`detail_url`.

### 4.3 API index (`ipper/common/models.py` + `api_output.py`)

- New model in `ipper/common/models.py`:

```python
class EventsMeta(BaseModel):
    """Metadata about the events endpoint in the API index."""
    url: str          # "events/events.json"
    count: int
    latest_seq: int
    last_event_at: str | None  # event_time of the newest event, None if empty
```

- `ApiIndex` gains `events: EventsMeta | None = None` and its `version`
  bumps from **2 to 3** (additive but versioned conservatively; update the
  docstring).
- `generate_api_index(base_dir)`: after scanning projects, if
  `base_dir/"events/events.json"` exists, read it and populate
  `index.events` (count/latest_seq from the document; `last_event_at` from
  the first event's `event_time` since the list is newest-first). If it does
  not exist, leave `events=None` (tests that only build project summaries
  keep working).

### 4.4 CLI (`ipper/events/cli.py`)

Register an `output` subcommand on the existing `events` tree:

```
uv run python ipper/main.py events output --api-dir site_files/api/v1/events
```

- Args: `--api-dir` (required), plus optional `--events-file` and
  `--seen-file` (default to the store paths; used by tests — follow the
  `_events_file()` monkeypatch-friendly pattern already in this module).
- Implementation calls `generate_events_api` and prints the path + count
  (`Wrote {count} events to {path}`).
- Register nothing at top level — `setup_events_parser` is already wired in
  `ipper/main.py`.

### 4.5 Resulting JSON (example)

```json
{
  "version": 1,
  "generated_at": "2026-11-21T09:30:00Z",
  "count": 3809,
  "latest_seq": 3809,
  "events": [
    {
      "schema_version": 1,
      "seq": 3809,
      "stable_id": "kafka:kip-900/state_changed@2026-11-20",
      "project": "kafka",
      "key": "kafka:kip-900",
      "event_type": "state_changed",
      "reference": "KIP-900",
      "title": "Some Title",
      "state_before": "under discussion",
      "state_after": "accepted",
      "observed_at": "2026-11-20T13:54:01+00:00",
      "effective_at": "2026-11-19T10:00:00Z",
      "effective_at_source": "merged_on",
      "detail_url": "https://ossip.dev/kips/KIP-900.html",
      "reference_before": null,
      "backfilled": false,
      "event_time": "2026-11-19T10:00:00Z",
      "headline": "Kafka KIP-900 accepted — Some Title",
      "summary": "State changed from under discussion to accepted.",
      "current_reference": "KIP-900",
      "current_detail_url": "https://ossip.dev/kips/KIP-900.html"
    }
  ]
}
```

---

## 5. Phase 2 — Timeline page

### 5.1 `templates/timeline.html` (new, static shell)

Model it on `templates/skills.html`/`api.html` (static, not Jinja2 — all data
arrives via fetch). Required elements:

- Standard `<head>`: charset, viewport, `<title>OSSIP - Proposal Timeline</title>`,
  `style.css`, and the theme bootstrap inline snippet used on every page.
- `<body class="timeline-page">`:
  - `<h1>Proposal Timeline</h1>`
  - `nav-bar` matching the project pages:
    `Back to OSSIP` · `GitHub Repository: tomncooper/ossip` ·
    `<a href="api.html">JSON API</a>` · `Last Updated: <span id="tl-updated">…</span>`
    (filled by JS from `generated_at`).
  - **Filter bar** (`div.tl-controls`, sticky at top via CSS):
    - Project chips (`div#tl-project-chips`): `All` + one chip per project
      (`Kafka`, `Flink`, `Strimzi`, `StreamsHub`, `Kroxylicious`), single-select
      behavior (clicking `All` clears; clicking a project selects it; keep it
      simple — v1 is single-project-or-all, matching the deep-link use case).
    - Event-type chips (`div#tl-type-chips`): 7 toggle chips, **all active by
      default**; clicking toggles a type's visibility (active = shown). Label
      + icon from the table in §5.2. Must degrade gracefully for unknown
      types found in the data: build the type chip list from the union of
      known types and types present in the fetched data.
    - Text search (`input#tl-search`, `type="search"`,
      placeholder `Search title or reference…`): case-insensitive substring
      match on `title` and `reference` (and `current_reference`).
    - Backfill toggle (`label` + `input#tl-backfilled`, checkbox, **checked
      by default**): unchecked hides `backfilled: true` events.
    - Result count (`span#tl-count`, e.g. `Showing 214 of 3809 events`).
  - `<ol class="timeline" id="tl-timeline" aria-live="polite"></ol>` — the
    event cards (see §5.3).
  - `<div id="tl-sentinel" class="tl-sentinel">Loading events…</div>` —
    infinite-scroll sentinel; shows a spinner/"Loading more…" while fetching
    batches and `End of timeline` when exhausted.
  - A `<noscript>` message: the timeline requires JavaScript, link to
    `api.html` for the raw JSON.
  - Scripts: `<script src="assets/theme-toggle.js"></script>` then
    `<script src="assets/timeline.js"></script>`.

### 5.2 Event-type visual vocabulary (shared by page + docs)

| `event_type` | Chip label | Node icon | Notes |
|---|---|---|---|
| `new` | New | 🆕 | |
| `state_changed` | State change | *(state emoji)* | Icon from `state_after` (mirrors social's map): accepted/completed → ✅, under discussion → 💬, not accepted → ❌, in progress → 🛠️, unknown → ❓ |
| `renumbered` | Renumbered | ♻️ | |
| `disappeared` | Removed | 🚫 | |
| `first_approval` | First approval | 👍 | |
| `changes_requested` | Changes requested | 🛠️ | |
| `vote_started` | Vote started | 🗳️ | |
| *(unknown)* | the raw value | • | never break on unknown types |

Project chips get colored dots matching each project's existing card accent
in `style.css` (reuse the color values from `.project-card.kafka` etc.;
extract them into CSS variables if they are not already variables).

### 5.3 `templates/assets/timeline.js` (new, vanilla JS)

Structure (IIFE or module pattern; no frameworks, no build step):

```js
const EVENTS_URL = "api/v1/events/events.json";
const BATCH_SIZE = 50;

// State
let allEvents = [];          // full ApiEvent list, newest-first, as fetched
let filteredEvents = [];     // after filters
let renderedCount = 0;

// Filters (all derived once from URL, then mutated by UI)
const filters = { project: null, hiddenTypes: new Set(), search: "", showBackfilled: true };
```

Functions to implement:

- `init()` — parse URL params, build chips, fetch, first render.
- `filtersFromUrl()` — read `URLSearchParams`:
  - `project=<key>` (single project key; ignore invalid keys)
  - `hide=<type,type,…>` — comma-separated event types to start hidden
  - `q=<text>` — initial search
  - `backfill=0` — start with backfilled hidden
  Apply these to the UI controls too (chips reflect the URL state). This is
  the deep-link contract used by project pages.
- `fetchEvents()` — `fetch(EVENTS_URL)` → JSON; on failure show a friendly
  error in the timeline area with a retry button. Store `generated_at` into
  `#tl-updated`.
- `applyFilters()` — recompute `filteredEvents` from `allEvents` honoring
  project / hidden types / search / backfill; update `#tl-count`; reset
  `renderedCount = 0`, clear the `<ol>`, and render the first batch.
- `renderBatch()` — append the next `BATCH_SIZE` events as `<li>` cards
  (markup below). Called by `init` and by the scroll observer.
- `eventCard(ev)` — build one `<li>`:

```html
<li class="tl-event" data-project="kafka" data-type="state_changed">
  <span class="tl-node" aria-hidden="true">✅</span>
  <div class="tl-card">
    <div class="tl-meta">
      <span class="tl-date">Nov 19, 2026</span>
      <span class="tl-project tl-project-kafka"><span class="tl-dot"></span>Kafka</span>
      <a class="tl-ref" href="kips/KIP-900.html">KIP-900</a>
      <span class="tl-badge-backfilled" title="Synthesized from historical cache data">backfilled</span>
    </div>
    <div class="tl-headline">Some Title</div>
    <div class="tl-summary">State changed from under discussion to accepted.</div>
  </div>
</li>
```

  - Date: `new Date(ev.event_time).toLocaleDateString(undefined, {year: "numeric", month: "short", day: "numeric"})` — but prefer an explicit format (`Nov 19, 2026`) so the page is locale-stable; fall back to the raw string if parsing fails.
  - The reference link and card headline are **links**: `href` from
    `current_detail_url ?? detail_url`, converted to a **same-origin path**
    when possible (e.g. `https://ossip.dev/kips/KIP-900.html` →
    `kips/KIP-900.html`) via `new URL(url, location.href)` and comparing
    origins; keep the absolute URL when origins differ (local file://
    testing, mirrors). Reference text: `current_reference ?? reference`.
  - Headline text: strip the leading `"Kafka KIP-900 …"` prefix? **No** — the
    card already shows project chip + reference link, so render
    `ev.headline`'s title portion. Simplest robust approach: use
    `ev.summary` under a title-only headline: render `ev.title` as the card
    headline and `ev.summary` as the body (the chips/link/date already
    convey reference + change). Keep `ev.headline` unused by the page if it
    duplicates — but do not remove it from the API (agents use it).
  - `backfilled` badge only when `ev.backfilled === true` (badge visible
    only while the toggle is on, obviously — it can only be seen then).
  - Escape all text (use `textContent`, never `innerHTML` with data).
- `setupInfiniteScroll()` — `IntersectionObserver` on `#tl-sentinel`; when it
  becomes visible and more events remain, `renderBatch()`. Also a
  window-scroll fallback listener for older browsers. Update sentinel text:
    `Loading more…` (while appending), `End of timeline` (exhausted),
    `No events match the current filters` (empty `filteredEvents`).
- DOM node cap (optional but recommended): if the `<ol>` exceeds ~1000
  children, remove the oldest (topmost) rendered items and track the offset
  so filter re-renders reset correctly. Keep this simple; if it complicates
  the code, ship v1 with plain append and note the size in §Future.
- Wire UI events: project chips (single-select), type chips (toggle), search
  (`input` event, debounce ~200ms), backfill checkbox — all call
  `applyFilters()`.

### 5.4 CSS (`templates/style.css`, append a timeline section)

- `.tl-controls` sticky (`position: sticky; top: 0;`), themed background
  using existing CSS variables, `z-index` above cards, border-bottom.
- `.timeline` — vertical line: `ol.timeline { list-style: none; position:
  relative; padding-left: 3rem; }` with `ol.timeline::before { content: "";
  position: absolute; left: 1rem; top: 0; bottom: 0; width: 2px;
  background: var(--border-color or equivalent); }`.
- `.tl-event { position: relative; }` with `.tl-node` absolutely positioned
  on the line (circle background so the line appears to pass behind it).
- `.tl-card` — card styling consistent with the site (border-radius, subtle
  background from theme variables, padding, margin-bottom).
- `.tl-project` chips + `.tl-dot` per-project colors (5 classes:
  `tl-project-kafka` …); `.tl-chip` + `.tl-chip.active` for filter buttons;
  `.tl-badge-backfilled` (muted pill).
- Both themes must look right — use only existing CSS variables where
  possible, and add new ones under `:root` / `[data-theme="light"]` as
  needed (follow the file's existing variable pattern).
- Responsive: cards full-width on narrow screens; filter bar wraps
  (`flex-wrap: wrap`).

---

## 6. Phase 3 — Navigation entry points

1. **Landing page** — `templates/index.html`, in the `top-links` line add:
   `<a href="timeline.html">Timeline</a>` (keep the `·` separators).
2. **Kafka index** — `templates/kafka-index.html.jinja`, in `nav-bar` add:
   `<div class="nav-item"><a href="timeline.html?project=kafka">Timeline</a></div>`
3. **Flink index** — `templates/flink-index.html.jinja`, same with
   `?project=flink`.
4. **GitHub index (shared by strimzi/streamshub/kroxylicious)** —
   `templates/github-index.html.jinja`:
   - `ipper/common/github_output.py` `render_index_page` must pass the
     project key to the template: add `project_key=config.key` to the
     `template.render(...)` call.
   - Template nav item:
     `<div class="nav-item"><a href="timeline.html?project={{ project_key|e }}">Timeline</a></div>`
5. Also add a "Timeline" link to `templates/skills.html` and
   `templates/api.html` nav if those pages have a shared nav row (they do —
   `.nav-item`s), for consistency.

No Python-side changes needed for kafka/flink templates (links are static
text in Jinja).

---

## 7. Phase 4 — Build wiring

Both `.github/workflows/publish.yaml` and `local_build.sh` need the same
three changes (keep them in sync — the workflow mirrors the script):

1. **Copy the page**: in the "Copy static page to site_files" step, add
   `cp templates/timeline.html site_files` (next to the existing
   `cp templates/api.html …` line). `timeline.js` needs no step —
   `cp -r templates/assets site_files/assets` already covers it.
2. **Generate the events API** — add a step **after the last project
   `output` (kroxylicious) and before the `generate_api_index` step**
   (the index reads `events/events.json`):

   ```yaml
   - name: Generate events JSON API
     run: uv run python ipper/main.py events output --api-dir site_files/api/v1/events
   ```

   (in `local_build.sh`, the equivalent `uv run …` line just before the
   `generate_api_index` python block).

3. **Index**: `generate_api_index(Path('site_files/api/v1'))` needs no
   command change — it picks up `events/events.json` automatically once the
   emitter runs first.

A single failed step here should behave like the other build steps (warn,
don't kill the whole publish) — follow whatever pattern the surrounding
project `output` steps use.

---

## 8. Phase 5 — Documentation

### 8.1 `templates/api.html`

- **Endpoints section**: add an "Events" subsection:
  - `https://ossip.dev/api/v1/events/events.json` — proposal event log,
    newest-first, `count`/`latest_seq`/`generated_at` envelope, one entry
    per detected change across all five projects.
  - Document the seven event types (table from §5.2 minus icons).
  - Document `seq` as a cursor for incremental polling and `stable_id` as a
    stable per-event identity.
  - Document the enrichment fields (`event_time`, `headline`, `summary`,
    `current_reference`, `current_detail_url`) and advise consumers to
    prefer `current_detail_url` (renumber-safe).
  - Explain `observed_at` vs `effective_at` (detection time vs best-known
    actual change time; use `event_time`).
  - Mention `backfilled: true` = synthesized history (approximate dates).
- **Field Reference section**: add the event-type table and the
  effective/observed time note.
- Update any "API version 2" mentions to **version 3**.

### 8.2 `templates/skill/ossip/SKILL.md`

- Add an "Events (all projects)" block under Data Endpoints:
  - `https://ossip.dev/api/v1/events/events.json` (~3.8k events, newest-first)
  - Fields summary + event types + cursor guidance.
- Add a query pattern, e.g. "Recent proposal activity":
  1. Fetch the events endpoint.
  2. Filter by `project` (client-side) for a project's timeline.
  3. For incremental polling, remember `latest_seq` and next time keep only
     events with `seq > previous_latest_seq`.
  4. Use `event_time` for ordering/display; `effective_at` when exact change
     time matters and is present.
- Mention the human-facing `https://ossip.dev/timeline.html` page in one
  line (agents may cite it to users).

### 8.3 `docs/event-log.md`

- Rewrite the "Future: publishing" section: the log **is now published** at
  `/api/v1/events/events.json` (enriched document described above; raw
  `EventRecord` fields unchanged). Note the "Scope" note at the top of the
  doc ("not served under /api/v1/") is now stale — update it.

### 8.4 `README.md` and `AGENTS.md`

- `README.md`: mention the timeline page and events endpoint wherever the
  site's pages/API are listed.
- `AGENTS.md`: add a **"Recent Changes"** section entry (follow the existing
  format: What Changed / New Files / Modified Files / Benefits / Dev
  commands) and update the standing sections that are now inaccurate:
  - Data Flow Summary (add events API → timeline step)
  - Output Generation (mention timeline.html + events API emission)
  - Development Commands (add the `events output` command)
  - API Integrations / event log scope notes if they mention "not public".

---

## 9. Phase 6 — Tests

Follow existing conventions (`tests/events/`, pytest, tmp_path fixtures —
see `tests/events/test_store.py`, `test_cli.py` for patterns).

### New: `tests/events/test_output.py`

- **Ordering**: given a hand-built log (write JSONL lines to a tmp file),
  `generate_events_api` output is newest-first by `(event_time, seq)`,
  including ties broken by `seq` descending.
- **Enrichment**: `headline`/`summary` match `presentation.headline(ev,
  include_project=True)` / `summary_text(ev)`; `event_time` = `effective_at`
  when present else `observed_at`.
- **Current URL resolution**: an event whose `key` exists in a tmp
  `last_seen.json` with a different (renumbered) `reference`/`detail_url`
  gets the *current* values; a key absent from `last_seen` gets
  `current_* = None`.
- **Document shape**: `version`, `generated_at` format, `count`, `latest_seq`.
- **Empty/missing log**: missing file or empty log still yields a valid
  document with `count: 0`.
- **Round-trip**: every output event parses back as `ApiEvent`.

### Extend `tests/events/test_cli.py`

- `events output --api-dir …` writes the file and exits 0 (use the
  module's `_events_file()` monkeypatch pattern or the new explicit
  `--events-file`/`--seen-file` args).

### Extend `tests/common/test_api_output.py` (and `test_models.py`)

- `generate_api_index` with an `events/events.json` present populates
  `index.events` (url/count/latest_seq/last_event_at) and writes
  `version: 3`.
- Without `events/events.json`, `index.events is None` and the index is
  still valid.
- Schema export includes `ApiEvent.schema.json` and
  `EventsDocument.schema.json`.

### Extend `tests/common/test_github_output.py`

- `render_index_page` passes `project_key` to the rendered HTML (assert the
  `timeline.html?project=strimzi` link appears) — one test covers all three
  GitHub projects since the template is shared.

### Manual verification (no JS test framework exists — keep the JS logic simple)

See §10.

---

## 10. Verification checklist (run before committing)

```bash
# CI gates (all three must pass)
uv run ruff check ipper/ tests/
uv run ruff format --check ipper/ tests/   # `uv run ruff format ipper/ tests/` to fix
uv run pytest

# Full local build (render-only; uses committed caches)
./local_build.sh --render-only
```

Then serve and click through:

```bash
cd site_files && python -m http.server 8080
```

- `http://localhost:8080/timeline.html` loads, events render newest-first,
  scrolling loads batches until "End of timeline".
- Scroll reaches the oldest events (2015-era KIPs) — full history is present.
- Project chips filter; `?project=kafka` deep link pre-selects Kafka.
- Type chips hide/show each of the 7 types; unknown types don't break
  rendering (temporarily hand-edit the fetched JSON in devtools to check).
- Search box matches title/reference; backfill toggle hides ~most of the
  history.
- `kafka.html`, `flink.html`, `strimzi.html`, `streamshub.html`,
  `kroxylicious.html` all have working Timeline links that land on the
  correctly pre-filtered timeline; landing page top-links has Timeline.
- Light/dark toggle works on the timeline; sticky filter bar readable in
  both themes.
- `api/v1/events/events.json` is valid JSON; `api/v1/index.json` has
  `version: 3` and the `events` entry; `api/v1/schemas/` has the two new
  schema files.
- Card links: a renumbered proposal's card links to the **current** page
  (spot-check a `renumbered` event, e.g. a SIP that went PR → numbered).

Also verify `git pull` was done before starting (per AGENTS.md guidelines —
CI commits caches daily).

---

## 11. Suggested implementation order

1. Phase 1 (models → emitter → api index → CLI), with tests at each step —
   everything else consumes this.
2. Phase 6 tests for Phase 1 + run gates.
3. Phase 2 (HTML shell → CSS → JS fetch/render → filters → infinite scroll).
4. Phase 3 (nav links incl. `project_key` plumbing) + its test.
5. Phase 4 (build wiring) + full `local_build.sh --render-only` + §10 manual
   pass.
6. Phase 5 (docs) last, against the finished shapes.

---

## 12. Out of scope (do not build now; note for the future)

- Upstream `web_url` (GitHub PR / wiki page) on events — cards link to
  OSSIP detail pages, which already link upstream. Would require adding
  `web_url` to `SeenSnapshot` + adapters.
- Per-project event JSON files (client-side filtering suffices for v1).
- RSS/Atom feeds (the original motivation for the consumer API — now easy to
  add since the document exists).
- API pagination (`?since_seq=`) — the single file is fine at current scale.
- Date-range filter UI on the timeline (search + type/project filters cover
  v1).
- JS unit tests / virtualized rendering beyond the simple node cap.

---

## 13. File manifest

**New files:**

| Path | Contents |
|---|---|
| `ipper/events/output.py` | `enrich_event`, `generate_events_api` |
| `templates/timeline.html` | static timeline page shell |
| `templates/assets/timeline.js` | fetch + filters + infinite scroll + render |
| `tests/events/test_output.py` | emitter/enrichment/document tests |

**Modified files:**

| Path | Change |
|---|---|
| `ipper/events/models.py` | add `ApiEvent`, `EventsDocument` |
| `ipper/events/cli.py` | add `events output` subcommand |
| `ipper/common/models.py` | add `EventsMeta`; `ApiIndex.events` + version 3 |
| `ipper/common/api_output.py` | `generate_api_index` events entry; `write_schemas` two new schemas |
| `ipper/common/github_output.py` | pass `project_key` to index template |
| `templates/style.css` | timeline styles |
| `templates/index.html` | Timeline top-link |
| `templates/kafka-index.html.jinja` | Timeline nav link (`?project=kafka`) |
| `templates/flink-index.html.jinja` | Timeline nav link (`?project=flink`) |
| `templates/github-index.html.jinja` | Timeline nav link (`?project={{ project_key }}`) |
| `templates/api.html` | Events endpoint docs, version 3 |
| `templates/skills.html` | Timeline nav link |
| `templates/skill/ossip/SKILL.md` | events endpoint + query patterns |
| `docs/event-log.md` | publishing section update |
| `.github/workflows/publish.yaml` | cp timeline.html; events output step |
| `local_build.sh` | same two changes |
| `README.md` | timeline + events API mentions |
| `AGENTS.md` | Recent Changes entry + standing-section updates |

---

*Plan approved by the maintainer on the design questions; defaults marked in
§1 may be adjusted during implementation if they conflict with existing code,
but the approved decisions (numbered table) should not be.*
