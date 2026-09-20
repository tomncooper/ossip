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
     - `common/github_process.py`: PR classification (proposal / amendment / plumbing), state derivation (merged → accepted, open → under discussion, closed unmerged → rejected), cache building with incremental update (watermark on `updated_at`, `head.sha` change detection, freeze/reopen semantics)
     - `common/github_output.py`: HTML index/detail rendering + JSON API emission (reuses Kafka/Flink templates)
     - `common/github_models.py`: cache/pydantic models (reviews snapshot, amendments)
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
- **Votes:** GitHub PR reviews (APPROVED → +1, CHANGES_REQUESTED → -1)

### StreamsHub (GitHub)
- **Repo:** `streamshub/proposals` — proposal files at repo root
- **Prefix:** SHIP
- **Numbering:** sequential
- **Votes:** GitHub PR reviews

### Kroxylicious (GitHub)
- **Repo:** `kroxylicious/design` — proposal files under `proposals/`
- **Prefix:** KDP
- **Numbering:** proposal number == PR number (drafts use `000-<name>.md`
  placeholders that are renamed to the PR number on merge)
- **Votes:** GitHub PR reviews

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

### Refresh (`kafka refresh` / `flink refresh`)
1. Reprocess ALL mbox files from scratch
2. Deduplicate all mentions
3. Regenerate `kip_mentions.csv` / `flip_mentions.csv`
4. Use when cache is corrupted or processing logic changes

### Initial Setup (`strimzi/streamshub/kroxylicious init`)
1. Walk ALL project PRs (classification + state + votes + comments)
2. Download the repo tarball to number merged proposals from the proposal files on main
3. Save the single-source-of-truth JSON cache (`cache/sip_proposals_cache.json`,
   `cache/ship_proposals_cache.json`, `cache/kdp_proposals_cache.json`)
4. Requires `GITHUB_TOKEN` (full fetch is ~500-1000 requests)

### Updates (`strimzi/streamshub/kroxylicious update`)
1. Incremental: walk PRs newest-first, stop at the watermark (max `updated_at` already seen)
2. `head.sha` change → re-fetch PR files; label-only bump → refresh reviews/comments only
3. Close/reopen/merge transitions handled (freeze votes, reconcile merged PRs with the tarball)
4. Save the JSON cache atomically (temp file + rename)

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

### CI/CD Pipeline (`.github/workflows/publish.yaml`)
- **Trigger:** Push to main branch or daily cron (09:30 UTC)
- **Steps:**
  1. Install Python 3.12 and uv
  2. Run `kafka update` and `flink update` (both incremental, including mailing lists)
  3. Run `strimzi/streamshub/kroxylicious update` (incremental; `GITHUB_TOKEN`
     env passed from secrets — optional, update works unauthenticated)
  4. Generate HTML files from cached data (kafka.html, flink.html,
     strimzi/streamshub/kroxylicious.html + individual detail pages + JSON API)
  5. Commit updated cache files back to repository
  6. Deploy to GitHub Pages

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
  cache/mailbox_files/kip_mentions.csv site_files/kafka.html site_files/kips

# Generate Flink HTML (shows ALL FLIPs + individual FLIP pages)
uv run python ipper/main.py flink output \
  cache/flip_wiki_cache.json site_files/flink.html site_files/flips

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
  cache/sip_proposals_cache.json site_files/strimzi.html site_files/sips

# Generate StreamsHub HTML
uv run python ipper/main.py streamshub output \
  cache/ship_proposals_cache.json site_files/streamshub.html site_files/ships

# Generate Kroxylicious HTML
uv run python ipper/main.py kroxylicious output \
  cache/kdp_proposals_cache.json site_files/kroxylicious.html site_files/kdps

# Run linting checks
uv run ruff check .
```

## Testing & Quality

The project includes:
- **456 comprehensive tests** covering all core functionality
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
- Add JavaScript filtering/search functionality to main pages
- Pagination or lazy loading for large KIP/FLIP tables
- Real-time updates via webhooks
- Internationalization support
- Database backend instead of CSV/JSON caching
- Better rate limiting and error handling for API calls
- Machine learning for improved vote detection confidence scoring
- Historical vote pattern analysis and committer activity tracking

---

**Last Updated:** 2026-09-20
**Maintainer:** Thomas Cooper

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

---

**Last Updated:** 2026-02-07
**Maintainer:** Thomas Cooper
