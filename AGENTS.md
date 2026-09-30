# AGENTS.md - AI Agent Context for OSSIP

## Project Overview

**OSSIP** (Open Source Software Improvement Proposals) is a Python-based data enrichment and visualization tool that aggregates, processes, and presents improvement proposals from various open source projects. The project creates enriched, searchable web interfaces for tracking the status and discussion of improvement proposals.

- **Primary Language:** Python 3.12+
- **Dependency Management:** uv (modern Python package manager)
- **Deployment:** GitHub Pages (via GitHub Actions)
- **Live Site:** [ossip.dev](https://ossip.dev/)
- **Current Status:** Apache Kafka (KIP) and Apache Flink (FLIP) fully
  supported via wiki/mailing lists; Strimzi (SIP), StreamsHub (SHIP) and
  Kroxylicious (KDP) supported via the GitHub PR pipeline

## Tools

Always use Context7 MCP when I need library/API documentation, code generation, setup or configuration steps without me having to explicitly ask.

## Architecture

### High-Level Structure

```
ossip/
├── ipper/              # Main Python package
│   ├── main.py        # CLI entry point
│   ├── common/        # Shared utilities and constants (incl. GitHub proposal pipeline)
│   ├── kafka/         # Kafka Improvement Proposals (KIP) processing
│   ├── flink/         # Flink Improvement Proposals (FLIP) processing
│   ├── strimzi/       # Strimzi Improvement Proposals (SIP) — GitHub-based
│   ├── streamshub/    # StreamsHub Improvement Proposals (SHIP) — GitHub-based
│   └── kroxylicious/  # Kroxylicious Design Proposals (KDP) — GitHub-based
├── templates/         # Jinja2 HTML templates
├── cache/            # Local data cache (gitignored)
├── site_files/       # Generated static site files
└── .github/          # CI/CD workflows
```

### Core Components

1. **CLI Interface** (`ipper/main.py`)
   - Argument parsing with subcommands for each project (kafka, flink, strimzi, streamshub, kroxylicious)
   - Commands: `init`, `update`, `refresh`, `wiki`, `output`
   - The three GitHub-backed projects (strimzi/streamshub/kroxylicious) share
     one implementation in `common/github_cli.py`, dispatched with their
     `GithubProjectConfig`

2. **Data Collection Layer**
   - **Wiki Scrapers** (`kafka/wiki.py`, `flink/wiki.py`, `common/wiki.py`)
     - Fetch improvement proposal data from Apache Confluence wikis
     - Parse HTML content using BeautifulSoup4
     - Extract metadata: status, authors, discussions
   
   - **Mailing List Processor** (`kafka/mailing_list.py`, `common/mailing_list.py`)
     - Downloads Apache mailing list archives (mbox format)
     - Parses email threads for KIP/FLIP mentions
     - Tracks voting patterns and discussion activity
     - Uses regex patterns to identify improvement proposal references
     - **Automatic binding vote detection** using Apache KEYS files
   
   - **Committer Identification** (`common/keys.py`)
     - Downloads and parses Apache KEYS files (PGP keys of project committers)
     - Extracts committer names and email addresses
     - Enables automatic detection of binding votes even without "(binding)" marker
     - Uses exact email matching + fuzzy name matching (70% threshold)
     - Caches committer data for 7 days to minimize downloads

   - **GitHub Proposal Pipeline** (`common/github*.py` + `strimzi/`, `streamshub/`, `kroxylicious/`)
     - Tracks projects whose improvement proposals live as pull requests on GitHub
     - `common/github_config.py`: per-project config (repo, prefix, proposal file location, numbering scheme)
     - `common/github.py`: thin GitHub REST client (`requests` + `get_with_retries`), Link-header pagination, rate-limit handling, codeload tarball download
     - `common/github_process.py`: PR classification (proposal / amendment / plumbing), state derivation (merged → accepted, open → under discussion, closed unmerged → rejected), cache building with incremental update (watermark on `updated_at`, `head.sha` change detection, freeze/reopen semantics), review-activity derivation, cache migration (`migrate_cache`)
     - `common/github_output.py`: HTML index/detail rendering + JSON API emission (reuses Kafka/Flink templates)
     - `common/github_models.py`: pydantic models (GithubProposalDetail with reviews + amendments)
     - Token: `GITHUB_TOKEN` env var (required for `init`/`refresh`, optional for `update`)

3. **Data Processing**
   - **Pandas DataFrames** for tabular data manipulation
   - CSV-based main cache files (`kip_mentions.csv`, `flip_mentions.csv`)
   - Status classification using enums (`IPState`)
   - Automatic deduplication on all data operations
   - **Vote Processing Logic:**
     - Explicit "(binding)" votes: Always counted as binding
     - Explicit "(non-binding)" votes: Never counted (ignored)
     - Unmarked votes: Checked against committer KEYS
       - If voter email matches committer → binding (100% confidence)
       - If voter name fuzzy-matches committer → binding (70%+ confidence)
       - If no match → non-binding (strict approach)

4. **Output Generation**
   - **Jinja2 Templates** for HTML rendering
   - Standalone HTML pages with embedded data
   - Individual proposal detail pages (both KIP and FLIP)
   - **KIP Display Strategy**:
     - Shows ALL KIPs regardless of state (accepted, under discussion, rejected, etc.)
     - "Under Discussion" KIPs: colored status indicators (green/yellow/red/black/blue) based on mailing list activity
     - Accepted KIPs: ✅ emoji
     - Rejected/Not Accepted KIPs: ❌ emoji
     - Withdrawn/Unknown KIPs: 🚫 emoji

## Key Technologies

### Core Dependencies

- **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)** - HTML/XML parsing for wiki scraping
- **[Pandas](https://pandas.pydata.org/)** - Data manipulation and CSV processing
- **[Jinja2](https://jinja.palletsprojects.com/)** - Template engine for HTML generation
- **[Requests](https://requests.readthedocs.io/)** - HTTP client for API/web requests
- **[Jira](https://jira.readthedocs.io/)** - Jira API integration (common module)
- **[rapidfuzz](https://maxbachmann.github.io/RapidFuzz/)** - Fast fuzzy string matching for committer name matching

### Development Tools

- **uv** - Modern, fast Python package installer and dependency manager
- **Black** - Code formatting
- **Pylint** - Code linting
- **MyPy** - Static type checking
- **IPython/ipdb** - Interactive debugging

## Data Sources

### Apache Kafka
- **Wiki:** Confluence page - "Kafka Improvement Proposals"
- **Mailing Lists:** 
  - dev@kafka.apache.org (primary)
  - user@kafka.apache.org
  - jira@kafka.apache.org
  - commits@kafka.apache.org
- **Format:** mbox archives from lists.apache.org
- **KEYS:** https://downloads.apache.org/kafka/KEYS (PGP keys of committers)

### Apache Flink
- **Wiki:** Confluence page - "Flink Improvement Proposals"
- **Mailing Lists:** 
  - dev@flink.apache.org (primary)
  - user@flink.apache.org
  - jira@flink.apache.org
  - commits@flink.apache.org
- **Format:** mbox archives from lists.apache.org
- **Status:** Fully implemented with wiki scraping, mailing list processing, and individual FLIP pages
- **Output:** Main index page plus individual FLIP detail pages
- **KEYS:** https://downloads.apache.org/flink/KEYS (PGP keys of committers)

### Strimzi (GitHub)
- **Repo:** `strimzi/proposals` — proposal files at repo root
- **Prefix / Prefix-URL Scheme:** SIP / `https://strimzi.io/proposals/{id}.html`
- **Numbering:** sequential (merged proposals are numbered by the order their
  files land on main)
- **Votes:** GitHub PR reviews → three unique-user columns: Accepted (APPROVED
  review, terminal), Commented (issue comments / COMMENTED reviews only,
  author and bots excluded), Requested Changes (CHANGES_REQUESTED, no
  approval); latest timestamp per user per column

### StreamsHub (GitHub)
- **Repo:** `streamshub/proposals` — proposal files at repo root
- **Prefix:** SHIP
- **Numbering:** sequential
- **Votes:** GitHub PR reviews (same three-column scheme as Strimzi)

### Kroxylicious (GitHub)
- **Repo:** `kroxylicious/design` — proposal files under `proposals/`
- **Prefix:** KDP
- **Numbering:** proposal number == PR number (drafts use `000-<name>.md`
  placeholders that are renamed to the PR number on merge)
- **Votes:** GitHub PR reviews (same three-column scheme as Strimzi; merged
  KDP proposal PRs capture review/comment snapshots at classification time —
  pre-refactor caches are backfilled once by `migrate_cache` during update)

## Workflow

### Initial Setup (`kafka init` / `flink init`)
1. Download KIP/FLIP wiki information from Confluence
2. Download 365 days of dev mailing list archives
3. Process all mbox files directly
4. Save mentions to `kip_mentions.csv` / `flip_mentions.csv`
5. Cache all data locally

### Updates (`kafka update` / `flink update`)
1. Update KIP/FLIP wiki cache with new proposals
2. Download most recent month's mailing list archive (re-downloads current month to catch late emails)
3. Process new mbox files directly
4. Append to `kip_mentions.csv` / `flip_mentions.csv` with automatic deduplication
5. Update metadata tracking
6. Append proposal events to `cache/events/events.jsonl`

### Event Log (automatic, part of each `update`)
1. Each project's `update` command ends with `update_from_cache(project, cache_path)`
   — diffs the cache against `cache/events/last_seen.json` baselines
2. Detectable changes append to the append-only log `cache/events/events.jsonl`
   (under an exclusive `fcntl.flock`; parallel `local_build.sh` updates are safe)
3. Baselines (`last_seen.json`) advance atomically after the append
4. A missing cache skips the project (never "everything disappeared"); a
   `last_seen.json` version mismatch fails loudly (`EventsVersionError`)
5. Only `update` is hooked — `init`/`refresh` never append (seed via
   `events backfill` first; see below)

### Social Announcements (`social announce`)
1. Load the event log (`cache/events/events.jsonl`) and compute its head seq
2. Load `cache/social/announced_states.json` (v2: per-destination cursors +
   pending queue); absent/v1/corrupt file → auto-seed cursors to the log head
   (posts nothing)
3. Discover announceable events past the least-advanced cursor; merge into the
   pending queue (a newer event for a proposal replaces the pending one)
4. Select up to `max_posts` (retries first, then ascending seq); overflow stays
   pending (cursors never advance past unacked pending events)
5. Post via configured posters (per-destination acks; a retry re-posts only to
   the failed destination)
6. Recompute cursors, prune fully-acked / exhausted events, save state atomically

`--dry-run` never writes the state file; `--reseed` clears pending and resets
cursors to the log head explicitly.

### Refresh (`kafka refresh` / `flink refresh`)
1. Reprocess ALL mbox files from scratch
2. Deduplicate all mentions
3. Regenerate `kip_mentions.csv` / `flip_mentions.csv`
4. Use when cache is corrupted or processing logic changes

### Initial Setup (`strimzi/streamshub/kroxylicious init`)
1. Walk ALL project PRs (classification + state + review/comment snapshots)
2. Download the repo tarball to number merged proposals from the proposal files on main
3. Save the single-source-of-truth JSON cache (`cache/sip_proposals_cache.json`,
   `cache/ship_proposals_cache.json`, `cache/kdp_proposals_cache.json`)
4. Requires `GITHUB_TOKEN` (full fetch is ~500-1000 requests)

### Updates (`strimzi/streamshub/kroxylicious update`)
1. Migrate the cache if it predates the review-activity format (`migrate_cache`;
   includes a one-time backfill of merged KDP proposal snapshots — needs
   `GITHUB_TOKEN` for that part, skipped with a warning otherwise)
2. Incremental: walk PRs newest-first, stop at the watermark (max `updated_at` already seen)
3. `head.sha` change → re-fetch PR files; label-only bump → refresh reviews/comments only
4. Close/reopen/merge transitions handled (freeze review activity, reconcile merged PRs with the tarball)
5. Save the JSON cache atomically (temp file + rename)
6. Append proposal events to `cache/events/events.jsonl` (shared hook in
   `common/github_cli.py`)

### Refresh (`strimzi/streamshub/kroxylicious refresh`)
Same as init (full re-fetch from GitHub). Use when cache is corrupted or
processing logic changes.

### Output Generation
1. Load cached data (`kip_mentions.csv` for Kafka, `flip_wiki_cache.json` + `flip_mentions.csv` for Flink, `sip/ship/kdp_proposals_cache.json` for the GitHub projects)
2. Render Jinja2 templates with enriched data
3. Generate standalone HTML files with:
   - Main index page showing ALL proposals (not filtered by state)
   - Individual detail pages for each proposal (KIP-XXX.html, FLIP-XXX.html,
     SIP-XXX.html / SIP-PR-N.html for unnumbered open proposals, etc.)
4. Emit JSON API files (`write_proposal_details`, `write_schemas`, `generate_api_index`)
5. Copy static pages into `site_files/`: the landing page (`templates/index.html`)
   and the agent-skill page (`templates/skills.html` +
   `templates/skill/ossip/SKILL.md`, which documents the JSON API endpoints
   for AI agents)

**Client-side enhancements (vanilla JS in `templates/assets/`, no build
step):** per-column dropdown filters plus global text search
(`table-filter.js`, with multi-value cell support for multi-author columns),
sortable column headings (`table-sort.js`, driven by `data-sort` attributes
emitted from Python), and a light/dark theme toggle (`theme-toggle.js`,
persisted in localStorage).

### Social Media Announcements (`ipper/social/`)

Posts to Mastodon and Bluesky when a proposal is **new**, **accepted**, or
**rejected/closed**. Social is a **consumer** of the proposal event log
(see the Event Log section): detection moved to `ipper.events`, so social
only maps log events to announcements and manages delivery state. Runs as
a step in the publish workflow (daily cron + pushes to main), gated by the
`SOCIAL_POSTS_ENABLED` repo secret (dry-run mode until it is set to `true`).

**Module layout:**

```
ipper/social/
├── config.py                # re-exports shared project config (common/projects.py)
├── models.py                # v2 state models + announcement vocabulary (EventType)
├── consumer.py              # EventRecord -> announcement type + render models
├── messages.py              # message template, emoji map, length fitting
├── posters/                 # pluggable destinations (base/console/mastodon/bluesky)
└── cli.py                   # `social announce` subcommand (cursor/pending flow)
```

**State file:** `cache/social/announced_states.json` v2 (committed to git
with the other caches): `cursors` = per-destination acked-through seq into
the event log; `pending` = events awaiting per-destination acknowledgement
(each embeds a full `EventRecord` copy). Absent, corrupt or v1 files are
auto-seeded to the log head — nothing historical is ever posted.

**Announcement mapping** (`social/consumer.announcement_type`): `new` → NEW;
`state_changed` into accepted/completed → ACCEPTED (accepted↔completed
flips silent); `state_changed` into "not accepted" → REJECTED; reopens and
other wiggles are logged but silent; renumbered / first_approval /
changes_requested / vote_started / disappeared → never announced. At most
one post per proposal per run (new events replace pending ones with fresh
acks); a new destination starts at the head (no history replay).

**Message format:**
`{Project} {Reference} {emoji} {phrase} — “{Title}” {URL} #{Project} #{PREFIX}`
with emoji keyed on IPState (✅ accepted/completed, 💬 under discussion,
❌ not accepted, 🛠️ in progress, ❓ unknown).

**Dev commands:**

```bash
# Preview what would be posted (no credentials, never writes state)
uv run python ipper/main.py social announce --dry-run

# Print sample NEW/ACCEPTED/REJECTED messages from the event log
uv run python ipper/main.py social announce --demo

# Re-seed cursors to the event-log head (clears pending; posts nothing)
uv run python ipper/main.py social announce --reseed

# Local build including the social dry run
./local_build.sh --render-only --social-dry-run
```

**Secrets (set at go-live):** `SOCIAL_POSTS_ENABLED` (literal `true`),
`MASTODON_BASE_URL` (e.g. `https://social.netech.dev`),
`MASTODON_ACCESS_TOKEN` (instance → Preferences → Development → New
application, scope `write:statuses`), `BLUESKY_IDENTIFIER`,
`BLUESKY_APP_PASSWORD` (bsky.app → Settings → App Passwords — an app
password, not the account password).

**Adding a new destination:** create `ipper/social/posters/<name>.py` with a
class decorated `@register_poster` exposing `name`, `from_env()` (raise
`PosterNotConfigured` when credentials are missing) and
`post(event) -> PostResult` (build its own message via
`messages.build_message`, which takes an optional char limit); import the
module in `posters/__init__.py`; add its env vars to CI. No other changes.

### Event Log (`ipper/events/`)

An append-only JSONL record of every detectable proposal change, maintained
automatically by each project's `update` command and consumed by social
(and future feeds/webhooks/JSON API).

**Files:**

```
cache/events/
├── events.jsonl    # append-only log; full history retained forever
├── last_seen.json  # detection baselines (mutable, atomically rewritten)
└── .lock           # fcntl lock file (gitignored)
```

**Producer flow:** `update_from_cache(project, cache_path)` — under an
exclusive `fcntl.flock` on `.lock` (the five updates run in parallel), load
the log + baselines, convert the cache to `SeenSnapshot`s via an adapter,
pure-diff (`detection.detect_events`), append candidates (replay-dedup
makes a crash between append and baseline-save harmless), then atomically
save the baselines.

**Event taxonomy** (`EventType`): `new`, `state_changed`, `renumbered`,
`disappeared`, `first_approval`, `changes_requested`, `vote_started`.
Everything detectable is logged; consumers decide what they care about.

**Effective-at:** every event has `observed_at` (detection run time) plus
`effective_at`/`effective_at_source` (best-known change time). Wiki
`last_modified_on` values are upper bounds only (the wiki records just the
page's latest edit); GitHub `merged_on`/`closed_on`/`created_at` and review
timestamps are exact.

**stable_id:** `{key}/{event_type}@{YYYY-MM-DD}` with a `-2`, `-3` ...
suffix on same-day same-type collisions; computed once at append time and
stored on the record (consumers never recompute). Keys are PR-number-stable
for GitHub projects (`strimzi:pr-245` survives renumbering to SIP-46).

**Schema evolution:** pydantic models in `ipper/events/models.py` are the
source of truth; per-record `schema_version`. Additive changes need no
bump (readers tolerate unknown fields via `extra="allow"` and unknown
`event_type` values — it's a plain str); breaking changes bump the version
and ship a one-time migrator (git history is the archive).

**Version guard:** a `last_seen.json` version mismatch raises
`EventsVersionError` — never silently reseeded (a reseed would re-emit
thousands of duplicate events into the permanent log).

**Backfill:** `events backfill` (one-time; refuses a non-empty log)
synthesizes historical events from current caches (chronological within
each project, `backfilled: true`) and seeds `last_seen`.

**Consumer API** (`ipper.events`, see the package docstring for a feed
example): `load_events`/`read_events`, `filter_events` (project/type/date/
backfill), `newest_first`, `events_after_seq`, `max_seq`, `latest_snapshot`
(current reference/URL for a key — fixes stale links for renumbered
proposals) plus `headline`/`summary_text` display helpers shared with the
social messages.

**CLI:** `events tail [--project K] [--type T] [--limit N]`,
`events backfill`, `events stats`.

### CI/CD Pipeline (`.github/workflows/publish.yaml`)
- **Triggers:** daily cron (09:30 UTC), manual `workflow_dispatch`, push to
  main touching `templates/**` or the workflow file, and successful
  completion of the "Run Tests" workflow on main; concurrent runs are queued
  (concurrency group `publish`) so cache-commit pushes never race
- **Steps:**
  1. Install Python 3.12 and uv
  2. Run `kafka update` (incremental, including mailing lists)
  3. Run `flink wiki download --update --refresh-days 60`, then `flink update`
  4. Run `strimzi/streamshub/kroxylicious update` (incremental; `GITHUB_TOKEN`
     env passed from secrets — optional, update works unauthenticated)
  5. Copy static pages (landing `index.html`, `skills.html` + the agent
     skill) into `site_files/`
  6. Generate HTML files from cached data (kafka.html, flink.html,
     strimzi/streamshub/kroxylicious.html + individual detail pages + JSON API)
  7. Check build results (a single failed project build only warns; all five
     failing is an error)
  8. Post social media announcements (`social announce --max-posts 10`;
     dry-run unless `SOCIAL_POSTS_ENABLED=true`; `continue-on-error` so failed
     destinations retry next run without losing the cache commit)
  9. Commit updated cache files back to repository (includes the social
     state file)
  10. Deploy to GitHub Pages

## Important Patterns

### Status Classification
```python
class IPState(StrEnum):
    COMPLETED = "completed"
    IN_PROGRESS = "in progress"
    ACCEPTED = "accepted"
    UNDER_DISCUSSION = "under discussion"
    NOT_ACCEPTED = "not accepted"
    UNKNOWN = "unknown"
```

Status determination uses keyword matching on wiki content:
- **Accepted:** "accepted", "approved", "adopted", "implemented", etc.
- **Under Discussion:** "discussion", "draft", "voting", "wip", etc.
- **Not Accepted:** "rejected", "withdrawn", "superseded", etc.

### KIP Mention Types (Email Processing)
```python
class KIPMentionType(Enum):
    SUBJECT = "subject"  # KIP mentioned in email subject
    VOTE = "vote"        # Voting thread
    DISCUSS = "discuss"  # Discussion thread
    BODY = "body"        # Mentioned in email body
```

### Regex Patterns
```python
KIP_PATTERN = re.compile(r"KIP-(?P<kip>\d+)", re.IGNORECASE)
```

### GitHub PR Classification
```python
# Proposal: PR adds a numbered proposal file (NNN-*.md in the configured
# location, excluding 000-template.md / README.md)
# Amendment: PR modifies/renames a proposal file that is already merged on main
# Plumbing: everything else (workflow tweaks, README edits, ...)
# Unnumbered open proposals display as 'PR #N'; Kroxylicious drafts use the
# 000-<name>.md placeholder convention (renumbered to the PR number on merge)
# Merged KDP PRs skip the files call: proposal iff proposals/<PR#>-*.md is
# on main; their review/comment snapshots are captured at that point
```

### GitHub Review Activity (three unique-user columns)
```python
# accepted:         >= 1 APPROVED review (terminal; approvers never appear
#                   in the other columns)
# changes_requested: >= 1 CHANGES_REQUESTED review and no approval
# commented:        issue comments or COMMENTED reviews only; the PR author
#                   and bots ([bot] suffix + KNOWN_BOTS) are excluded
# Each entry keeps the user's latest qualifying timestamp.
# PENDING reviews never count; DISMISSED approvals no longer count as
# acceptance but that user's comments still count.
# Frozen at merge/close time from the PR index snapshots.
```

## File Conventions

- **Cache Directory:** `cache/` (not committed to git except main cache files)
- **Main Cache Files:**
  - Kafka: `cache/mailbox_files/kip_mentions.csv` (single source of truth)
  - Flink: `cache/flip_wiki_cache.json`
  - Strimzi: `cache/sip_proposals_cache.json` · StreamsHub:
    `cache/ship_proposals_cache.json` · Kroxylicious:
    `cache/kdp_proposals_cache.json` (single source of truth)
  - Metadata: `cache/kip_mentions_metadata.json`, `cache/flip_mentions_metadata.json`
  - **Committer KEYS:** `cache/keys/kafka_keys.json`, `cache/keys/flink_keys.json`
  - **Event log:** `cache/events/events.jsonl` (append-only, full history
    retained forever) · `cache/events/last_seen.json` (detection baselines)
    · `cache/events/.lock` (gitignored) — committed with the caches
  - **Social announcements:** `cache/social/announced_states.json` (v2:
    per-destination cursors + pending announcement queue; committed with the caches)
- **Mbox Files:** `cache/mailbox_files/*.mbox` (downloaded archives)
- **Output:** `site_files/*.html`

## Development Commands

```bash
# Install dependencies
uv sync

# Initialize Kafka data (365 days)
uv run python ipper/main.py kafka init --days 365

# Update Kafka data (incremental)
uv run python ipper/main.py kafka update

# Refresh Kafka committer KEYS file
uv run python ipper/main.py kafka keys refresh

# View cached committer information
uv run python ipper/main.py kafka keys info

# Refresh Flink committer KEYS file
uv run python ipper/main.py flink keys refresh

# View Flink cached committer information
uv run python ipper/main.py flink keys info

# Download Flink wiki data (initial or full refresh)
uv run python ipper/main.py flink wiki download

# Update Flink wiki data (incremental, refresh last 60 days)
uv run python ipper/main.py flink wiki download --update --refresh-days 60

# Generate Kafka HTML (shows ALL KIPs + individual KIP pages)
uv run python ipper/main.py kafka output standalone \
  cache/mailbox_files/kip_mentions.csv site_files/kafka.html site_files/kips \
  --api-dir site_files/api/v1/kafka

# Generate Flink HTML (shows ALL FLIPs + individual FLIP pages)
uv run python ipper/main.py flink output \
  cache/flip_wiki_cache.json site_files/flink.html site_files/flips \
  --api-dir site_files/api/v1/flink

# Initialize Strimzi/StreamsHub/Kroxylicious proposal data (requires GITHUB_TOKEN)
uv run python ipper/main.py strimzi init
uv run python ipper/main.py streamshub init
uv run python ipper/main.py kroxylicious init

# Update Strimzi/StreamsHub/Kroxylicious proposal data (incremental)
uv run python ipper/main.py strimzi update
uv run python ipper/main.py streamshub update
uv run python ipper/main.py kroxylicious update

# Generate Strimzi HTML (shows ALL SIPs + individual SIP pages)
uv run python ipper/main.py strimzi output \
  cache/sip_proposals_cache.json site_files/strimzi.html site_files/sips \
  --api-dir site_files/api/v1/strimzi

# Generate StreamsHub HTML
uv run python ipper/main.py streamshub output \
  cache/ship_proposals_cache.json site_files/streamshub.html site_files/ships \
  --api-dir site_files/api/v1/streamshub

# Generate Kroxylicious HTML
uv run python ipper/main.py kroxylicious output \
  cache/kdp_proposals_cache.json site_files/kroxylicious.html site_files/kdps \
  --api-dir site_files/api/v1/kroxylicious

# Run linting checks
uv run ruff check .
```

## Testing & Quality

The project includes:
- **534 comprehensive tests** covering all core functionality
- Type hints throughout (checked with MyPy)
- Code formatting with Black
- Linting with Pylint and Ruff
- Test coverage for KEYS parsing, fuzzy matching, and vote detection
- Test coverage for the GitHub pipeline (client, classification, incremental
  updates, HTML/JSON output, CLI wiring)

**Always run `uv run ruff check .` after making code changes to ensure code quality.**

## API Integrations

### Apache Confluence REST API
- **Base URL:** `https://wiki.apache.org/confluence/rest/api/content`
- **Authentication:** Public access (no auth required)
- **Rate Limiting:** Not explicitly handled
- **Chunking:** Configurable batch size for page fetches (default: 100)

### Apache Mailing List Archives
- **Base URL:** `https://lists.apache.org/api/mbox.lua`
- **Format:** mbox (Unix mailbox format)
- **Access:** Public, monthly archives

### GitHub REST API (Strimzi / StreamsHub / Kroxylicious)
- **Base URL:** `https://api.github.com/repos/{owner}/{repo}`
- **Tarball:** `https://codeload.github.com/{owner}/{repo}/tar.gz/refs/heads/{branch}`
- **Authentication:** `GITHUB_TOKEN` via `Authorization: Bearer` header
  (required for `init`/`refresh` full fetches, optional for incremental `update`)
- **Rate Limiting:** 60 req/hour unauthenticated, 5,000 req/hour authenticated;
  client raises `GithubRateLimitError` when the quota is exhausted
- **Endpoints used:** pulls list (paginated), pull files/reviews/issue comments,
  single pull, repo tarball

## AI Agent Guidelines

### When Working on This Project:

1. **Always pull from remote first** - Before starting any work, run `git pull` to get the latest cache files. The CI job runs daily (09:30 UTC) and commits updated cache data (CSV/JSON files in `cache/`) back to the repository. Working with stale cache data can lead to inconsistencies.
2. **Use uv for dependency management** - Always use `uv run` or `uv sync`, never pip directly
3. **Type hints are required** - The project uses MyPy, maintain type annotations
4. **Minimal changes** - The data pipeline is working; focus on incremental improvements
5. **Test with small data first** - Use `--days 30` for testing instead of full 365-day downloads
6. **Cache awareness** - Understand the caching strategy to avoid unnecessary API calls
7. **HTML templates** - Modify Jinja2 templates for UI changes, not Python code
8. **Project structure** - Each supported project (kafka, flink, strimzi,
   streamshub, kroxylicious) has its own submodule under `ipper/`; the three
   GitHub-backed ones share `ipper/common/github*.py`
9. **Run linting after code changes** - Always run `uv run ruff check .` after making code changes to catch issues early

### Common Tasks:

- **Adding a new project:** Create a new subdirectory under `ipper/` following the kafka/flink pattern
- **Modifying status detection:** Update keyword lists in `wiki.py` files
- **Changing output format:** Edit Jinja2 templates in `templates/`
- **Adding API sources:** Extend `common/` utilities for shared functionality

### Data Flow Summary:

```
Confluence Wiki API → BeautifulSoup → Pandas → JSON Cache (wiki data)
Mailing List API → mbox Parser → Pandas → CSV Cache (mentions)
Apache KEYS API → PGP Parser → JSON Cache (committers)
GitHub REST API (PRs) → PR Classification → JSON Cache (proposals)
  ↓
Committer Index + Vote Detection → Enhanced vote counting
  ↓
CSV/JSON Cache → Jinja2 Templates → Static HTML → GitHub Pages
CSV/JSON Cache → Pydantic → JSON API (/api/v1/)
CSV/JSON Cache → ipper.events adapters → events.jsonl (append-only log)
last_seen.json ↔ git (detection baselines, committed with caches)
event log → social consumer → Posters → Mastodon/Bluesky
announced_states.json (v2 cursors/pending) ↔ git (committed with caches)
```

**Caching Architecture:**
- Single source of truth: `kip_mentions.csv` / `flip_mentions.csv`
- Committer KEYS cached for 7 days (configurable)
- No intermediate per-file caches (removed for simplicity)
- Automatic deduplication on all append operations
- `kafka update` re-downloads current month to catch late-arriving emails

**Vote Counting Architecture:**
1. Email parsed for vote pattern (`+1`, `-1`, `0`)
2. Check for explicit `(binding)` or `(non-binding)` marker
3. If unmarked: Check committer index
   - Exact email match → binding (highest confidence)
   - Fuzzy name match (70%+) → binding
   - No match → non-binding
4. Log all automatic detections for auditing

## Known Limitations

1. No rate limiting on API calls
2. Limited error recovery in data collection
3. `kafka refresh` and `flink refresh` take 2-5 minutes (reprocess all mbox files)
4. Status keyword matching is English-only
5. Large table sizes (1000+ KIPs/FLIPs) may impact page load performance
6. Fuzzy name matching may occasionally miss committers with very different email names

## Future Considerations

- Add support for more Apache projects (e.g., Airflow, Spark)
- Pagination or lazy loading for large KIP/FLIP tables (text search and
  column filtering/sorting are already in place client-side)
- Real-time updates via webhooks
- Internationalization support
- Database backend instead of CSV/JSON caching
- Better rate limiting and error handling for API calls
- Machine learning for improved vote detection confidence scoring
- Historical vote pattern analysis and committer activity tracking
- Social announcements: if the publish runner dies after posting to a
  destination but before the cache commit, the acknowledgements are lost and
  the next run re-posts (rare; self-limiting; accepted residual risk)

---

**Last Updated:** 2026-10-01
**Maintainer:** Thomas Cooper

## Recent Changes (2026-10-01)

### Proposal Event Log (ipper/events) + Social v2 Consumer

**What Changed:**
- New `ipper/events/` package: an append-only JSONL log
  (`cache/events/events.jsonl`) of every detectable proposal change across
  all five projects, maintained automatically by each project's `update`
  command under an exclusive `fcntl.flock` (parallel `local_build.sh`
  updates are safe)
- Event taxonomy: `new`, `state_changed`, `renumbered`, `disappeared`,
  `first_approval`, `changes_requested`, `vote_started` — everything is
  logged; consumers decide what they care about
- Every event carries `observed_at` plus `effective_at`/`effective_at_source`
  (best-known actual change time; exact for GitHub, upper-bound for wiki);
  `stable_id` (`{key}/{event_type}@{date}`) computed once at append and
  stored on the record
- Detection baselines moved to `cache/events/last_seen.json` (version
  mismatch = hard `EventsVersionError`, never silently reseeded); GitHub
  cache records gained full-ISO `created_at` and explicit `closed_on`
  fields (Phase 2, optional with documented fallbacks)
- Shared project config moved to `ipper/common/projects.py`
  (`ipper/social/config.py` re-exports unchanged names)
- One-time `events backfill` command synthesizes historical events from the
  current caches (chronological, `backfilled: true`) and seeds baselines;
  `events tail` / `events stats` for inspection
- Consumer API in `ipper/events/consumer.py` (`filter_events`,
  `newest_first`, `events_after_seq`, `max_seq`, `latest_snapshot`) plus
  `headline`/`summary_text` display helpers shared with social messages —
  the feed-facing surface for the Atom/RSS follow-up (PR #13)
- Social announcement pipeline rewritten as a log consumer: state file v2
  (per-destination cursors + pending queue of embedded `EventRecord`s);
  old v1 baselines/pending are superseded (auto-seeded to the log head,
  nothing historical posted); `ipper/social/detector.py` and
  `ipper/social/adapters/` deleted

**New Files:** `ipper/events/` (models, store, detection, backfill,
presentation, consumer, cli, adapters/{kafka,flink,github}),
`ipper/common/projects.py`, `ipper/social/consumer.py`,
`tests/events/` (7 modules + golden fixture), `cache/events/`

**Deleted Files:** `ipper/social/detector.py`, `ipper/social/adapters/`,
`tests/social/test_detector.py`, `tests/social/test_adapters.py`

**Modified Files:** `ipper/main.py` (events subcommand),
`ipper/kafka/main.py`, `ipper/flink/main.py`, `ipper/common/github_cli.py`
(update hooks + `created_at`/`closed_on` enrichment in
`github_process.py`), `ipper/social/{models,cli}.py`, `tests/social/`
(cli rewrite), `.gitignore` (`cache/events/.lock`)

**Dev commands:**

```bash
uv run python ipper/main.py events backfill   # one-time migration
uv run python ipper/main.py events tail
uv run python ipper/main.py events stats
```

**Benefits:**
- Full change history with best-known change times (the data PR #13's Atom
  feeds needed)
- Crash-safe append + replay-dedup; idempotent second runs
- Social delivery state shrinks to cursors + pending; per-destination
  retries preserved; new destinations never replay history
- Future consumers (webhooks, JSON API) need no cache internals

## Recent Changes (2026-09-29)

### Client-Side Search, Sortable Tables & Agent Skill Page

**What Changed:**
- Column headings on the KIP, FLIP and GitHub proposal index pages are now
  clickable to sort (click again to reverse) — `templates/assets/table-sort.js`;
  sort keys ride on `data-sort` attributes (vote/review counts, activity
  colour rank, ISO created date); `ipper/kafka/output.py` now emits `created_on`
  (ISO) per KIP for age sorting; sorting composes with the dropdown filters
- Global text search across all columns added to
  `templates/assets/table-filter.js` alongside the existing column dropdown
  filters
- Multi-author support for KIPs/FLIPs: "Author(s)" column renders multiple
  authors; `TableFilter` gained multi-value column support
- Agent skill page: `templates/skills.html` + `templates/skill/ossip/SKILL.md`
  (documents the JSON API endpoints for AI agents), linked from the landing
  page and copied into `site_files/` by CI and `local_build.sh`
- Social media links added to the landing page (`templates/index.html`)

**Modified Files:** `templates/assets/table-sort.js` (new),
`templates/assets/table-filter.js`, `templates/skills.html`,
`templates/skill/ossip/SKILL.md`, `templates/index.html`,
`templates/style.css`, the four index templates, `ipper/kafka/output.py`

## Recent Changes (2026-09-27)

### Social Media Announcements (Mastodon + Bluesky)

**What Changed:**
- New `ipper/social/` package: posts to Mastodon and Bluesky when a proposal
  is **new**, **accepted**, or **rejected/closed**; covers all five projects
  (KIP, FLIP, SIP, SHIP, KDP) via cache adapters
- Pluggable destinations via a `Poster` protocol + registry
  (`ipper/social/posters/`); console poster for dry runs, Mastodon.py and
  atproto SDK clients for live posting
- Duplicate protection via an in-repo state file
  (`cache/social/announced_states.json`): per-proposal baselines advanced at
  detection time plus a pending-event queue with per-destination
  acknowledgements — if Mastodon succeeds but Bluesky is down, only Bluesky
  is retried next run
- Baseline seeding: the first live run records current state and posts
  nothing; only future changes are announced. `--dry-run` never writes the
  state file
- Uniform message template
  `{Project} {Reference} {emoji} {phrase} — “{Title}” {URL} {hashtags}` with
  char-limit fitting (Mastodon limit queried from the instance, Bluesky 300,
  link facets for clickable Bluesky URLs)
- New CLI: `uv run python ipper/main.py social announce [--post-to ...]
  [--projects ...] [--dry-run] [--demo] [--reseed] [--max-posts N]
  [--max-attempts N] [--state-file PATH]`
- CI (`publish.yaml`) gained a `Post social media announcements` step between
  build checks and the cache commit, gated by `SOCIAL_POSTS_ENABLED`
  (dry-run until it is set to `true`), `continue-on-error: true` so acks are
  committed even when a destination is down
- `local_build.sh` gained a `--social-dry-run` flag
- New dependencies: `atproto`, `Mastodon.py`

**New Files:**
- `ipper/social/` — `config.py`, `models.py`, `messages.py`, `detector.py`,
  `cli.py`, `adapters/` (kafka, flink, github), `posters/`
  (base, console, mastodon, bluesky)
- `tests/social/` — `conftest.py`, `test_models.py`, `test_messages.py`,
  `test_adapters.py`, `test_detector.py`, `test_posters.py`, `test_cli.py`

**Modified Files:**
- `ipper/main.py` — `social` subcommand registration
- `local_build.sh` — `--social-dry-run` flag (argument loop)
- `.github/workflows/publish.yaml` — social announce step
- `pyproject.toml` — `atproto`, `Mastodon.py` dependencies
- `README.md`, this file — documentation

## Recent Changes (2026-09-20)

### Review-Activity Columns for GitHub-Based Proposals (SIP / SHIP / KDP)

**What Changed:**
- Replaced the mailing-list style +1/0/-1 columns with three unique-user
  review columns: **Accepted**, **Commented**, **Requested Changes**
- Semantics: any APPROVED review → Accepted (terminal); CHANGES_REQUESTED
  without approval → Requested Changes; issue comments or COMMENTED reviews
  → Commented; the PR author and bot accounts are excluded; the latest
  qualifying timestamp is kept per user per column; DISMISSED approvals and
  PENDING reviews are ignored
- Proposal cache records now store `reviews` (`accepted` / `commented` /
  `changes_requested`) instead of `votes`; old caches are migrated on the next
  `update` or `output` run (`migrate_cache` in `common/github_process.py`)
- Merged KDP proposal PRs now capture their review/comment snapshots at
  classification time (previously never fetched); pre-refactor caches are
  backfilled once with a token (~2 requests per PR)
- JSON API v2: GitHub projects emit `review_count` (summaries) and `reviews`
  (details) instead of `vote_count` / `votes`; `ApiIndex.version` bumped to 2;
  new models `ReviewerInfo`, `ReviewSummary`, `ReviewCount`,
  `GithubProposalSummary`; KIP/FLIP models unchanged

**Modified Files:**
- `ipper/common/github_process.py` — `derive_review_activity*`, bot filter,
  merged-KDP snapshot capture, `migrate_cache` + backfill
- `ipper/common/github_output.py`, `github_models.py`, `models.py`,
  `api_output.py`, `github_cli.py`
- `templates/github-index.html.jinja`, `templates/github-more-info.html.jinja`
- Tests: `test_github.py`, `test_github_output.py`, `test_models.py`,
  `test_api_output.py`, `test_json_api_integration.py`

---

## Recent Changes (2026-09-20)

### GitHub-Based Proposal Tracking (SIP / SHIP / KDP)

**What Changed:**
- Added support for three projects whose improvement proposals live as GitHub
  pull requests: Strimzi (SIP), StreamsHub (SHIP) and Kroxylicious (KDP)
- New shared GitHub pipeline under `ipper/common/`: config, REST client,
  PR classification/state machine, HTML + JSON output, CLI wiring
- New per-project packages: `ipper/strimzi/`, `ipper/streamshub/`,
  `ipper/kroxylicious/` (thin CLI dispatchers over `common/github_cli.py`)
- JSON API extended: `/api/v1/{project}/{sip,ship,kdp}s.json` + detail files,
  `GithubProposalDetail` schema; `ProposalSummary`/`ProposalDetail` gained
  nullable `id` and `pr_number`
- New templates `github-index.html.jinja` / `github-more-info.html.jinja`
- CI (`publish.yaml`) runs per-project updates and builds with token support

**New Files:**
- `ipper/common/github.py`, `github_config.py`, `github_process.py`,
  `github_models.py`, `github_output.py`, `github_cli.py`
- `ipper/{strimzi,streamshub,kroxylicious}/main.py`
- `templates/github-index.html.jinja`, `templates/github-more-info.html.jinja`
- `tests/common/test_github.py`, `tests/common/test_github_output.py`,
  `tests/{strimzi,streamshub,kroxylicious}/test_main.py`

**CLI Commands:**
```bash
export GITHUB_TOKEN=ghp_...   # required for init/refresh
uv run python ipper/main.py strimzi init|update|refresh|output
uv run python ipper/main.py streamshub init|update|refresh|output
uv run python ipper/main.py kroxylicious init|update|refresh|output
```

**Benefits:**
- Same UX as KIP/FLIP pages for three more communities
- JSON API consistency across all five projects
- Incremental updates keep GitHub API usage low (~5-15 requests/run)

---

## Recent Changes (2026-02-15)

### Robust Vote Binding Detection with KEYS Files

**What Changed:**
- Added automatic detection of binding votes from committers, even when they don't explicitly mark votes as "(binding)"
- Implemented Apache KEYS file parsing to extract committer names and email addresses
- Integrated fuzzy matching (rapidfuzz) for flexible name matching with 70% similarity threshold
- Added exact email matching for highest confidence committer identification
- Created comprehensive test suite (84 tests total, 27 for KEYS functionality)

**New Files:**
- `ipper/common/keys.py` - KEYS file parsing and committer matching
- `tests/common/test_keys.py` - Comprehensive KEYS parsing tests
- `cache/keys/` - Directory for cached committer data (JSON format)

**Modified Files:**
- `ipper/common/mailing_list.py` - Enhanced `parse_for_vote()` with committer checking
- `ipper/kafka/mailing_list.py` - Integrated KEYS loading for Kafka
- `ipper/flink/mailing_list.py` - Integrated KEYS loading for Flink  
- `ipper/kafka/main.py` - Added `kafka keys refresh` and `kafka keys info` CLI commands
- `pyproject.toml` - Added rapidfuzz dependency

**Vote Detection Logic:**
1. **Explicit "(binding)"** → Always counted (unchanged)
2. **Explicit "(non-binding)"** → Never counted (unchanged)
3. **Unmarked votes (NEW):**
   - Email exact match → binding (100% confidence)
   - Name fuzzy match (≥70%) → binding
   - No match → non-binding (strict approach)

**CLI Commands:**
```bash
# Kafka: Force refresh committer KEYS
uv run python ipper/main.py kafka keys refresh
uv run python ipper/main.py kafka keys info

# Flink: Force refresh committer KEYS
uv run python ipper/main.py flink keys refresh
uv run python ipper/main.py flink keys info
```

**Benefits:**
- More accurate binding vote counts (catches unmarked committer votes)
- Automatic cache management (7-day refresh cycle)
- Full backward compatibility (explicit binding/non-binding still works)
- Detailed logging for auditing automatic detections
- Fast performance (O(1) email lookup, fuzzy matching only as fallback)
