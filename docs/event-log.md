# The Proposal Event Log (`ipper/events/`)

Developer guide to the append-only event log: what it is, its on-disk schema,
how to consume it, and how it is produced. This is the canonical reference —
`README.md` and `AGENTS.md` point here.

> **Scope:** The event log is committed to git alongside the other caches
> under `cache/`, and it is **also published**: the build enriches it into
> `site_files/api/v1/events/events.json` (`ApiEvent`/`EventsDocument` — the
> verbatim log fields plus precomputed display fields), documented in the
> agent-facing `SKILL.md` and rendered for humans at `timeline.html`
> (see [Publishing](#publishing)). "Consuming it" inside this repo
> (as `ipper/social/` does) still goes through the same consumer helpers.

## 1. Purpose & architecture

Every detectable change to a tracked proposal — across all five projects
(Kafka, Flink, Strimzi, StreamsHub, Kroxylicious) — is recorded as one line in
an append-only log. The log is the single source of change history; consumers
read it instead of diffing caches themselves.

```
project caches (cache/*.json, *.csv)
        │
        │  update_from_cache(project, cache_path)   ← producer, per `update`
        ▼
cache/events/events.jsonl   (append-only, full history, committed to git)
        │
        │  load_events() + consumer helpers
        ▼
consumers:  ipper/social/  (today)   ·   feeds / webhooks / JSON API  (future)
```

The producer runs at the end of each project's `update` command. The only
consumer today is the social-announcement pipeline (`ipper/social/`). The
module was deliberately designed so future consumers (RSS/Atom feeds, webhooks)
need no knowledge of cache internals — only the helpers in
`ipper/events/consumer.py`.

## 2. File layout

Defined in `ipper/events/store.py` (`EVENTS_DIR` etc.):

```
cache/events/
├── events.jsonl    # append-only log; full history retained forever (committed)
├── last_seen.json  # detection baselines: mutable, atomically rewritten (committed)
└── .lock           # fcntl lock file (gitignored)
```

- **`events.jsonl`** — the log itself. Never rewritten, only appended.
- **`last_seen.json`** — the "before" side of the diff: the last-observed
  snapshot of every proposal, per project. Mutated by the producer; used by
  `latest_snapshot()` to resolve a proposal's *current* reference/URL.
- **`.lock`** — guards all mutation (the five project updates run in parallel).

## 3. On-disk schema (`events.jsonl`)

**Each line is one JSON object: a `json.dumps()` of one `EventRecord`.**
There is no outer array, no header line — append-only, one record per line.

The authoritative, always-current field definition is the pydantic model
`EventRecord` in [`ipper/events/models.py`](../ipper/events/models.py). Parse
against that. The table below mirrors it for quick reference:

| Field                 | Type            | Notes |
|-----------------------|-----------------|-------|
| `schema_version`      | int             | Per-record version stamp (currently `1`). |
| `seq`                 | int             | Strictly increasing, never reused. Cursor key for consumers. |
| `stable_id`           | str             | `{key}/{event_type}@{YYYY-MM-DD}` (+ collision suffix). Computed once at append; never recompute. Safe in `tag:` URIs. |
| `project`             | str             | `"kafka"`, `"flink"`, `"strimzi"`, `"streamshub"`, `"kroxylicious"`. |
| `key`                 | str             | Stable proposal identity, e.g. `"kafka:kip-123"`, `"strimzi:pr-245"`. PR-number-stable for GitHub projects (survives renumbering). |
| `event_type`          | str             | An `EventType` *value* — but a **plain str** by design (see §9). |
| `reference`           | str             | Display reference at event time, e.g. `"SIP-46"`, `"SIP-PR-245"`. |
| `title`               | str             | Display title at event time (prefix stripped). |
| `state_before`        | str \| null     | `null` for `new` / backfilled-unknown. |
| `state_after`         | str \| null     | `null` **only** for `disappeared`. |
| `observed_at`         | str (ISO 8601)  | Detection run time (UTC). Always present. |
| `effective_at`        | str \| null     | Best-known *actual* change time (see §5). |
| `effective_at_source` | str \| null     | Where `effective_at` came from. |
| `detail_url`          | str             | Proposal page URL at event time. |
| `reference_before`    | str \| null     | Set for `renumbered` (the old reference). |
| `backfilled`          | bool            | `true` for synthesized history (see §10). |

Readers must tolerate **unknown extra fields** and **unknown `event_type`
values** — the model uses `extra="allow"` and keeps `event_type` as a str so a
newer build's log stays readable by an older checkout.

## 4. Event taxonomy

`EventType` (`ipper/events/models.py`) — the producer vocabulary:

| Type                | Meaning |
|---------------------|---------|
| `new`               | Proposal first seen. `state_before` is null. |
| `state_changed`     | `state_before` → `state_after` transition. |
| `renumbered`        | Reference changed (e.g. GitHub PR → numbered proposal). `reference_before` set. |
| `disappeared`       | Removed from the upstream tracker. `state_after` is null. |
| `first_approval`    | First approving review (GitHub). |
| `changes_requested` | Changes requested on review (GitHub). |
| `vote_started`      | A vote thread started (wiki). |

**Everything detectable is logged; consumers decide what they care about.** The
social pipeline, for example, only announces `new` and a subset of
`state_changed`.

## 5. Timestamps: `observed_at` vs `effective_at`

- **`observed_at`** — when detection ran. Always present. An upper bound on the
  real change time, bounded by how often `update` runs.
- **`effective_at`** (+ `effective_at_source`) — the best-known *actual* change
  time, when we have one. **Exact** for GitHub (`merged_on` / `closed_on` /
  `created_at` / review timestamps). An **upper bound** for wiki
  (`last_modified_on` records only the page's latest edit, not the specific
  change).

Consumers that order or timestamp events should use the helper
`event_time(event)` (`presentation.py`), which returns `effective_at` when
present else `observed_at`. The filter/sort helpers already do this.

## 6. `stable_id`

Format: `{key}/{event_type}@{YYYY-MM-DD}`, with `-2`, `-3`, … appended on
same-proposal/same-type/same-day collisions (`presentation.stable_id`). It is
**computed once at append time and stored on the record** — consumers must
never recompute it. Because `key` is PR-number-stable for GitHub projects
(`strimzi:pr-245` survives renumbering to `SIP-46`), a proposal's ids stay
coherent across a rename. It is stable and safe to embed in Atom/RSS `tag:`
URIs.

## 7. Consumer API

Import everything from the package root — `from ipper.events import ...`. The
read helpers:

| Function | Module | What it does |
|----------|--------|--------------|
| `load_events()` / `read_events()` | `store.py` | Load the whole log as `list[EventRecord]`. Skips corrupt lines and torn final writes. `read_events` is an alias. |
| `filter_events(events, project=, types=, since=, until=, include_backfilled=)` | `consumer.py` | Filter by project / `EventType` values / inclusive `YYYY-MM-DD` date bounds (on `event_time`) / backfill flag. |
| `newest_first(events, limit=None)` | `consumer.py` | Sort by `(event_time, seq)` descending; optional limit. |
| `events_after_seq(events, seq)` | `consumer.py` | Events strictly after `seq`, ascending. For cursor-style consumers. |
| `max_seq(events)` | `consumer.py` | Highest `seq` (0 if empty). The log "head". |
| `latest_snapshot(key)` | `consumer.py` | A proposal's **current** snapshot (reference/`detail_url`) from `last_seen.json` — fixes stale links for renumbered proposals. |
| `headline(event)` / `summary_text(event)` | `presentation.py` | Display wording, shared with the social messages so site and posts never diverge. |

Minimal feed example (from the package docstring):

```python
from ipper.events import load_events, filter_events, newest_first

recent = newest_first(
    filter_events(load_events(), types={"new", "state_changed"}),
    limit=50,
)
```

> **Gotcha — lazy exports.** The package re-exports everything except the
> models lazily via `__getattr__` (to break an import cycle with
> `ipper.social`). Runtime `from ipper.events import load_events` works fine,
> but static-analysis tools / IDEs may not "see" the lazy names until they are
> first accessed. This is expected; don't add eager imports to "fix" it (it
> re-introduces the cycle).

## 8. Writing a new consumer

Two patterns cover almost everything.

**One-shot read (feeds, snapshots):** load, filter, sort, render.

```python
from ipper.events import load_events, filter_events, newest_first, latest_snapshot, headline

def build_feed() -> str:
    events = newest_first(
        filter_events(load_events(), types={"new", "state_changed"}, include_backfilled=False),
        limit=50,
    )
    for e in events:
        current = latest_snapshot(e.key)          # resolve CURRENT ref/url
        url = current.detail_url if current else e.detail_url
        emit_entry(title=headline(e), id=e.stable_id, link=url)
    ...
```

**Cursor-style delivery (webhooks, announcements):** persist the last `seq` you
acted on; each run, process only what's new; advance the cursor after success.
This is exactly how `ipper/social/cli.py` works — read it for a worked, tested
example (per-destination cursors + a pending/retry queue).

```python
from ipper.events import load_events, events_after_seq, max_seq

def run(cursor: int) -> int:
    events = load_events()
    for e in events_after_seq(events, cursor):   # strictly after the cursor, ascending
        deliver(e)
    return max_seq(events)                        # new cursor; persist it
```

Seed a brand-new consumer's cursor at `max_seq(load_events())` so it does **not**
replay all of history on first run (what social does on first launch).

## 9. Schema evolution

The pydantic models in [`ipper/events/models.py`](../ipper/events/models.py)
are the source of truth.

- **Additive changes need no version bump.** Readers tolerate unknown fields
  (`extra="allow"`) and unknown `event_type` values (`event_type` is a plain
  `str`). Add a field or a new `EventType` member and old checkouts keep
  reading.
- **Breaking changes bump `SCHEMA_VERSION`** and ship a one-time migrator. Git
  history is the archive (the log is never rewritten in place).

### Version guard

`last_seen.json` carries a document-level `version`. A mismatch raises
`EventsVersionError` and is **never silently reseeded** — a reseed would
re-detect every proposal and re-emit thousands of duplicate events into the
permanent log. On a version bump you must run the migration, not delete the
baseline.

## 10. Backfill & CLI

The log is populated going forward by `update`. To seed history from the
current caches, run the one-time backfill (it **refuses to run against a
non-empty log**):

```bash
uv run python ipper/main.py events backfill   # chronological, marks backfilled: true
```

Inspection commands:

```bash
uv run python ipper/main.py events tail [--project K] [--type T] [--limit N]
uv run python ipper/main.py events stats      # totals, head seq, per-project/type counts
```

## 11. Producer side (for maintainers)

`update_from_cache(project, cache_path)` (`store.py`) is the only public
mutator. Under an exclusive `fcntl.flock` on `.lock` it:

1. Loads the log + baselines.
2. Converts the project cache to `SeenSnapshot`s via the per-project adapter
   (`ipper/events/adapters/`).
3. Pure-diffs against the baseline (`detection.detect_events`).
4. Appends candidates (`append_events`), assigning `seq` and `stable_id`.
5. Atomically rewrites the baseline (`save_seen`).

**Crash-safety:** if the process dies between the append and the baseline save,
the next run re-detects the same transitions, but **replay-dedup** in
`append_events` (an identity tuple per transition) drops the duplicates — so a
second run is idempotent.

**Guards against data loss:** a missing cache skips the project; a
present-but-empty cache (a failed fetch that still wrote valid JSON) is also
skipped rather than emitting `disappeared` for every proposal.

## Publishing

The log **is now published** as part of every build:

1. `events output` (`ipper/events/output.py`) loads the log, orders it
   newest-first by `(event_time, seq)`, and enriches each record into an
   `ApiEvent` — the verbatim `EventRecord` fields (the versioned contract;
   see §3) plus additive display fields:
   - `event_time` — `effective_at` or `observed_at` (presentation helper)
   - `headline` / `summary` — the shared display wording
   - `current_reference` / `current_detail_url` — the proposal's CURRENT
     reference/URL from `last_seen.json` (renumber-safe linking; `None` when
     the key is no longer tracked)
2. The document is written to `site_files/api/v1/events/events.json`
   (envelope: `version`, `generated_at`, `count`, `latest_seq`, `events`).
3. `generate_api_index` picks it up into `index.json`'s `events` entry
   (`ApiIndex` version 3).
4. The timeline page (`timeline.html` + `assets/timeline.js`) fetches the
   document client-side; `templates/api.html` and
   `templates/skill/ossip/SKILL.md` document the endpoint for agents.

Treat the schema in §3 as a versioned contract: the verbatim log fields are
never rewritten by the emitter, only extended.
