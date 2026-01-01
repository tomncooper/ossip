# AGENTS.md - AI Agent Context for OSSIP

## Project Overview

**OSSIP** (Open Source Software Improvement Proposals) is a Python-based data enrichment and visualization tool that aggregates, processes, and presents improvement proposals from various open source projects. The project creates enriched, searchable web interfaces for tracking the status and discussion of improvement proposals.

- **Primary Language:** Python 3.12+
- **Dependency Management:** Poetry
- **Deployment:** GitHub Pages (via GitHub Actions)
- **Live Site:** [ossip.dev](https://ossip.dev/)

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
   - Commands: `init`, `update`, `wiki`, `mail`, `output`

2. **Data Collection Layer**
   - **Wiki Scrapers** (`kafka/wiki.py`, `flink/wiki.py`, `common/wiki.py`)
     - Fetch improvement proposal data from Apache Confluence wikis
     - Parse HTML content using BeautifulSoup4
     - Extract metadata: status, authors, discussions
   
   - **Mailing List Processor** (`kafka/mailing_list.py`)
     - Downloads Apache mailing list archives (mbox format)
     - Parses email threads for KIP mentions
     - Tracks voting patterns and discussion activity
     - Uses regex patterns to identify KIP references

3. **Data Processing**
   - **Pandas DataFrames** for tabular data manipulation
   - CSV-based caching system for processed data
   - Status classification using enums (`IPState`)

4. **Output Generation**
   - **Jinja2 Templates** for HTML rendering
   - Standalone HTML pages with embedded data
   - Raw information pages for individual proposals

## Key Technologies

### Core Dependencies

- **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)** - HTML/XML parsing for wiki scraping
- **[Pandas](https://pandas.pydata.org/)** - Data manipulation and CSV processing
- **[Jinja2](https://jinja.palletsprojects.com/)** - Template engine for HTML generation
- **[Requests](https://requests.readthedocs.io/)** - HTTP client for API/web requests
- **[Jira](https://jira.readthedocs.io/)** - Jira API integration (common module)

### Development Tools

- **Poetry** - Dependency management and packaging
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
- **Status:** Partial implementation (wiki only, no mailing list processing yet)

## Workflow

### Initial Setup (`kafka init`)
1. Download KIP wiki information from Confluence
2. Download 365 days of dev mailing list archives
3. Process mbox files to extract KIP mentions
4. Cache all data locally

### Updates (`kafka update`)
1. Update KIP wiki cache with new proposals
2. Download most recent month's mailing list archive
3. Reprocess new messages
4. Merge with existing cache

### Output Generation
1. Load cached data (CSV for Kafka, JSON for Flink)
2. Render Jinja2 templates with enriched data
3. Generate standalone HTML files

### CI/CD Pipeline (`.github/workflows/publish.yaml`)
- **Trigger:** Push to main branch or daily cron (09:30 UTC)
- **Steps:**
  1. Install Python 3.12 and Poetry
  2. Run `kafka init` and `flink wiki download`
  3. Generate HTML files from cached data
  4. Deploy to GitHub Pages

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

- **Cache Directory:** `cache/` (not committed to git)
- **Mbox Cache:** `cache/kafka_processed_mailbox_cache/*.cache.csv`
- **Wiki Cache:** 
  - Kafka: CSV files in `cache/`
  - Flink: `cache/flip_wiki_cache.json`
- **Output:** `site_files/*.html`

## Development Commands

```bash
# Install dependencies
poetry install

# Initialize Kafka data (365 days)
poetry run python ipper/main.py kafka init --days 365

# Update Kafka data
poetry run python ipper/main.py kafka update

# Download Flink wiki data
poetry run python ipper/main.py flink wiki download

# Generate Kafka HTML
poetry run python ipper/main.py kafka output standalone \
  cache/mailbox_files/kip_mentions.csv site_files/kafka.html

# Generate Flink HTML
poetry run python ipper/main.py flink output \
  cache/flip_wiki_cache.json site_files/flink.html site_files/flips
```

## Testing & Quality

The project includes:
- Type hints throughout (checked with MyPy)
- Code formatting with Black
- Linting with Pylint
- No explicit test suite currently present

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

1. **Respect the Poetry workflow** - Always use `poetry run` or `poetry install`, never pip directly
2. **Type hints are required** - The project uses MyPy, maintain type annotations
3. **Minimal changes** - The data pipeline is working; focus on incremental improvements
4. **Test with small data first** - Use `--days 30` for testing instead of full 365-day downloads
5. **Cache awareness** - Understand the caching strategy to avoid unnecessary API calls
6. **HTML templates** - Modify Jinja2 templates for UI changes, not Python code

### Common Tasks:

- **Adding a new project:** Create a new subdirectory under `ipper/` following the kafka/flink pattern
- **Modifying status detection:** Update keyword lists in `wiki.py` files
- **Changing output format:** Edit Jinja2 templates in `templates/`
- **Adding API sources:** Extend `common/` utilities for shared functionality

### Data Flow Summary:

```
Confluence Wiki API → BeautifulSoup → Pandas → CSV/JSON Cache
Mailing List API → mbox Parser → Pandas → CSV Cache
CSV/JSON Cache → Jinja2 Templates → Static HTML → GitHub Pages
```

## Known Limitations

1. Flink support is incomplete (no mailing list processing)
2. No rate limiting on API calls
3. No incremental wiki updates (only full refresh or add new)
4. Limited error recovery in data collection
5. No automated tests
6. Status keyword matching is English-only

## Future Considerations

- Add support for more Apache projects (e.g., Airflow, Spark)
- Implement GraphQL or better API pagination
- Add search functionality to generated pages
- Real-time updates via webhooks
- Internationalization support
- Database backend instead of CSV caching

---

**Last Updated:** 2026-01-01
**Maintainer:** Thomas Cooper
