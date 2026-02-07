# OSSIP 
_A hub for Open Source Software Improvement Proposals_

[ossip.dev](https://ossip.dev/)

This repo holds scripts for generating a website which collects and enriches the Improvement Proposals (IPs) from various open source software (OSS) projects (hence the name).

Currently supported projects are:
- [Apache Kafka](https://kafka.apache.org/) project's [Kafka Improvement Proposals (KIPs)](https://cwiki.apache.org/confluence/display/kafka/kafka+improvement+proposals)
- [Apache Flink](https://flink.apache.org/) project's [Flink Improvement Proposals (FLIPs)](https://cwiki.apache.org/confluence/display/FLINK/Flink+Improvement+Proposals)

## Development

### Installation

This project uses [`uv`](https://docs.astral.sh/uv/) to manage dependencies. 
To install the necessary libraries run:

```bash
$ uv sync
```

### Running Tests

This project includes unit tests for critical functions. To run the test suite:

```bash
# Run all tests
$ uv run pytest

# Run with verbose output
$ uv run pytest -v

# Run specific test file
$ uv run pytest tests/common/test_utils.py

# Run tests without coverage report
$ uv run pytest --no-cov
```

Current test coverage focuses on critical functions in the `ipper/common` module:
- **`utils.py`**: 100% coverage (date/time utilities)
- **`mailing_list.py`**: 40% coverage (parsing functions)
- **Overall `ipper/common`**: 35% coverage

The test suite includes 38 tests covering:
- Month list generation (prevents future month bugs)
- Email timestamp parsing (multiple formats)
- Vote parsing (binding votes only)
- Metadata handling
- Age calculation

Coverage reports are generated in HTML format (see `htmlcov/index.html`) and in the terminal output.

### Code Quality Checks

This project uses **Ruff** for fast linting and formatting:

```bash
# Check code for issues
$ uv run ruff check ipper/

# Auto-fix issues (removes unused imports, fixes formatting, etc.)
$ uv run ruff check ipper/ --fix

# Format code
$ uv run ruff format ipper/

# Check formatting without modifying files
$ uv run ruff format --check ipper/
```

Ruff checks for:
- **Unused imports** (auto-removed)
- **Import sorting** (auto-organized)
- **Modern Python idioms** (e.g., `list[str]` instead of `List[str]`)
- **Common bugs** (mutable defaults, etc.)
- **Code simplifications**

Configuration is in `pyproject.toml` under `[tool.ruff]`.

Type checking with MyPy:

```bash
# Run type checker
$ uv run mypy ipper/
```

### Downloading and processing KIP data

To download the Apache Kafka `dev` mailing list for the last year (longer periods can be set via the `--days` option), process the archives and download the KIP Wiki information from the confluence site; run the `init` command:

```bash
$ uv run python ipper/main.py kafka init --days 365
```

To update only the most recent month and add any new KIPs which have been posted since the last update run:

```bash
$ uv run python ipper/main.py kafka update
```

### Downloading and processing FLIP data

To download and process Apache Flink FLIP Wiki information from the confluence site, run:

```bash
$ uv run python ipper/main.py flink wiki download --update --refresh-days 60
```

The `--update` flag will update existing cached data, and `--refresh-days` specifies how many days back to refresh.

### Building the site

#### Quick Local Build

For convenience, a `local_build.sh` script is provided that automates the entire build process:

```bash
# Full build (updates data + generates HTML)
$ ./local_build.sh

# Render-only build (skips data updates, only regenerates HTML from cached data)
$ ./local_build.sh --render-only
```

#### Manual Build Steps

To create the standalone Kafka site html run the command below where the first argument is the kip mentions cache file produced by the step above and the second is the html output filepath:

```bash
$ uv run python ipper/main.py kafka output standalone cache/mailbox_files/kip_mentions.csv site_files/kafka.html
```

To create the Flink site html with individual FLIP pages:

```bash
$ uv run python ipper/main.py flink output cache/flip_wiki_cache.json site_files/flink.html site_files/flips
```

This generates a main index page and individual FLIP detail pages in the specified output directory.

You will also need to copy over the static files from the `templates` directory to the `site_files` directory:

```bash
$ mkdir -p site_files/assets
$ cp templates/index.html site_files
$ cp templates/style.css site_files
$ cp -r templates/assets site_files/assets
```

## Deployment

A Github action (see `.github/publish.yaml`) will build and publish the site on every push to `main`. 
The site is automatically built and deployed every day at approximately 09:30 UTC.

