# AGENTS.md - AI Agent Context for OSSIP

## Project Overview

**OSSIP** (Open Source Software Improvement Proposals) is a Python-based data enrichment and visualization tool that aggregates, processes, and presents improvement proposals from various open source projects. The project creates enriched, searchable web interfaces for tracking the status and discussion of improvement proposals.

- **Primary Language:** Python 3.12+
- **Dependency Management:** uv (modern Python package manager)
- **Deployment:** GitHub Pages (via GitHub Actions)
- **Live Site:** [ossip.dev](https://ossip.dev/)
- **Current Status:** Both Apache Kafka (KIP) and Apache Flink (FLIP) are fully supported

## Tools

Always use Context7 MCP when I need library/API documentation, code generation, setup or configuration steps without me having to explicitly ask.

## Architecture

### High-Level Structure

```
ossip/
├── ipper/              # Main Python package
│   ├── main.py        # CLI entry point
│   ├── common/        # Shared utilities and constants
│   ├── kafka/         # Kafka Improvement Proposals (KIP) processing
│   └── flink/         # Flink Improvement Proposals (FLIP) processing
├── templates/         # Jinja2 HTML templates
├── cache/            # Local data cache (gitignored)
├── site_files/       # Generated static site files
└── .github/          # CI/CD workflows
```

### Core Components

1. **CLI Interface** (`ipper/main.py`)
   - Argument parsing with subcommands for each project (kafka, flink)
   - Commands: `init`, `update`, `refresh`, `wiki`, `output`

2. **Data Collection Layer**
   - **Wiki Scrapers** (`kafka/wiki.py`, `flink/wiki.py`, `common/wiki.py`)
     - Fetch improvement proposal data from Apache Confluence wikis
     - Parse HTML content using BeautifulSoup4
     - Extract metadata: status, authors, discussions
   
   - **Mailing List Processor** (`kafka/mailing_list.py`, `common/mailing_list.py`)
     - Downloads Apache mailing list archives (mbox format)
     - Parses email threads for KIP mentions
     - Tracks voting patterns and discussion activity
     - Uses regex patterns to identify KIP references

3. **Data Processing**
   - **Pandas DataFrames** for tabular data manipulation
   - CSV-based main cache files (`kip_mentions.csv`, `flip_mentions.csv`)
   - Status classification using enums (`IPState`)
   - Automatic deduplication on all data operations

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

### Apache Flink
- **Wiki:** Confluence page - "Flink Improvement Proposals"
- **Status:** Fully implemented with wiki scraping and individual FLIP pages
- **Output:** Main index page plus individual FLIP detail pages

## Workflow

### Initial Setup (`kafka init`)
1. Download KIP wiki information from Confluence
2. Download 365 days of dev mailing list archives
3. Process all mbox files directly
4. Save mentions to `kip_mentions.csv`
5. Cache all data locally

### Updates (`kafka update`)
1. Update KIP wiki cache with new proposals
2. Download most recent month's mailing list archive (re-downloads current month to catch late emails)
3. Process new mbox files directly
4. Append to `kip_mentions.csv` with automatic deduplication
5. Update metadata tracking

### Refresh (`kafka refresh`)
1. Reprocess ALL mbox files from scratch
2. Deduplicate all mentions
3. Regenerate `kip_mentions.csv`
4. Use when cache is corrupted or processing logic changes

### Output Generation
1. Load cached data (`kip_mentions.csv` for Kafka, `flip_wiki_cache.json` + `flip_mentions.csv` for Flink)
2. Render Jinja2 templates with enriched data
3. Generate standalone HTML files with:
   - Main index page showing ALL proposals (not filtered by state)
   - Individual detail pages for each proposal (KIP-XXX.html or FLIP-XXX.html)

### CI/CD Pipeline (`.github/workflows/publish.yaml`)
- **Trigger:** Push to main branch or daily cron (09:30 UTC)
- **Steps:**
  1. Install Python 3.12 and uv
  2. Run `kafka update` (incremental) and `flink wiki download --update --refresh-days 60`
  3. Generate HTML files from cached data (kafka.html and flink.html + individual FLIP pages)
  4. Commit updated cache files back to repository
  5. Deploy to GitHub Pages

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

## File Conventions

- **Cache Directory:** `cache/` (not committed to git except main cache files)
- **Main Cache Files:**
  - Kafka: `cache/mailbox_files/kip_mentions.csv` (single source of truth)
  - Flink: `cache/flip_wiki_cache.json`
  - Metadata: `cache/kip_mentions_metadata.json`, `cache/flip_mentions_metadata.json`
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

# Run linting checks
uv run ruff check .
```

## Testing & Quality

The project includes:
- Type hints throughout (checked with MyPy)
- Code formatting with Black
- Linting with Pylint and Ruff
- No explicit test suite currently present

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

## AI Agent Guidelines

### When Working on This Project:

1. **Always pull from remote first** - Before starting any work, run `git pull` to get the latest cache files. The CI job runs daily (09:30 UTC) and commits updated cache data (CSV/JSON files in `cache/`) back to the repository. Working with stale cache data can lead to inconsistencies.
2. **Use uv for dependency management** - Always use `uv run` or `uv sync`, never pip directly
3. **Type hints are required** - The project uses MyPy, maintain type annotations
4. **Minimal changes** - The data pipeline is working; focus on incremental improvements
5. **Test with small data first** - Use `--days 30` for testing instead of full 365-day downloads
6. **Cache awareness** - Understand the caching strategy to avoid unnecessary API calls
7. **HTML templates** - Modify Jinja2 templates for UI changes, not Python code
8. **Project structure** - Each supported project (kafka, flink) has its own submodule under `ipper/`
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
  ↓
CSV/JSON Cache → Jinja2 Templates → Static HTML → GitHub Pages
```

**Caching Architecture:**
- Single source of truth: `kip_mentions.csv` / `flip_mentions.csv`
- No intermediate per-file caches (removed for simplicity)
- Automatic deduplication on all append operations
- `kafka update` re-downloads current month to catch late-arriving emails

## Known Limitations

1. Flink does not process mailing lists (only wiki data)
2. No rate limiting on API calls
3. Limited error recovery in data collection
4. `kafka refresh` takes 2-5 minutes (reprocesses ~182 mbox files)
5. No automated integration tests
6. Status keyword matching is English-only
7. Large table sizes (1000+ KIPs) may impact page load performance

## Future Considerations

- Add support for more Apache projects (e.g., Airflow, Spark)
- Implement mailing list processing for Flink (similar to Kafka)
- Add JavaScript filtering/search functionality to main pages
- Pagination or lazy loading for large KIP/FLIP tables
- Real-time updates via webhooks
- Internationalization support
- Database backend instead of CSV/JSON caching
- Better rate limiting and error handling for API calls

---

**Last Updated:** 2026-02-07
**Maintainer:** Thomas Cooper
