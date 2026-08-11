# JSON Data API & Claude Code Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose OSSIP's enriched KIP/FLIP data as structured JSON files on ossip.dev, and provide a Claude Code skill that teaches agents how to query them.

**Architecture:** JSON generation is a second output format from the same data pipeline. Pydantic models define the data structures, serve as the serialization layer, and auto-export JSON Schemas. Each project (Kafka, Flink) gets JSON conversion functions added to its existing output module, wired via an `--api-dir` CLI argument. A resilient post-step scans the filesystem to generate `index.json` from whatever project summaries exist.

**Tech Stack:** Python 3.12+, Pydantic 2.7+, existing Jinja2/pandas pipeline, GitHub Pages static hosting.

**Spec:** `docs/superpowers/specs/2026-04-30-json-api-and-skill-design.md`

## Global Constraints

- Pydantic `>=2.7,<3` (need stable `model_json_schema()`)
- Fields with wiki value `"not set"` or `"unknown"` map to `None` — consumers never see sentinels
- Date fields: `created_on` uses `YYYY-MM-DD`, timestamps use `YYYY-MM-DDTHH:MM:SSZ`
- Vote timestamps convert from `"Jan 02, 2025 10:00 UTC"` to ISO 8601
- Flink has no `activity_status` (always `None`)
- JSON files go in `site_files/` (ephemeral build artifacts, already gitignored)
- HTML output must be unchanged by adding `--api-dir`

---

## File Map

### New files (10)

| File | Responsibility |
|------|---------------|
| `ipper/common/models.py` | Pydantic model definitions (all data structures) |
| `ipper/common/api_output.py` | Shared JSON write utilities, date/sentinel helpers, resilient index generator |
| `templates/skill/ossip/SKILL.md` | Claude Code skill file |
| `templates/api.html` | Static HTML page documenting the JSON API and skill installation |
| `tests/common/test_models.py` | Model serialization + schema tests |
| `tests/common/test_api_output.py` | Write utility + index generator tests |
| `tests/kafka/test_json_api.py` | KIP conversion function tests |
| `tests/flink/test_json_api.py` | FLIP conversion function tests |
| `tests/common/test_json_api_integration.py` | End-to-end pipeline tests |

### Modified files (8)

| File | Changes |
|------|---------|
| `pyproject.toml` | Add `pydantic>=2.7,<3` dependency |
| `ipper/kafka/output.py` | Add `kip_to_detail`, `kip_to_summary`, `generate_kafka_json_api`; refactor `render_standalone_status_page` to accept pre-computed `kip_status` instead of fetching wiki data internally |
| `ipper/kafka/main.py` | Refactor `run_output_standalone_cmd` to load wiki data once; add `--api-dir` CLI argument |
| `ipper/flink/output.py` | Add `flip_to_detail`, `flip_to_summary`, `generate_flink_json_api`; remove `flip_mentions` param from renderers |
| `ipper/flink/main.py` | Refactor `process_output` to enrich once; add `--api-dir` CLI argument |
| `local_build.sh` | Add `--api-dir` flags, skill file copy, API docs page copy, index generation post-step |
| `.github/workflows/publish.yaml` | Add `--api-dir`, `continue-on-error`, index step, build result check, copy API docs + skill |
| `README.md` | Add JSON API and skill installation section |

---

## Dependency Graph

```
Tier 1 (parallel):  [Task 1: models + dep]   [Task 2: skill file]
                           |                        |
Tier 2:              [Task 3: api_output]    [Task 10: documentation (API page + README)]
                          / \                       |
Tier 3 (parallel):  [Task 4: kafka conv]   [Task 5: flink conv]
                         |                      |
Tier 4 (parallel):  [Task 6: kafka refactor]  [Task 7: flink refactor]
                         \                     /
Tier 5 (parallel):  [Task 8: build pipeline]  [Task 9: integration tests]
```

Task 10 (documentation) depends on Task 2 (skill file) and can run in parallel with Tasks 3-7. Task 8 (build pipeline) picks up the new `api.html` page for deployment.

---

## Task 1: Pydantic Models

**Files:**
- Modify: `pyproject.toml`
- Create: `ipper/common/models.py`
- Create: `tests/common/test_models.py`

**Produces:** All model classes importable from `ipper.common.models`: `VoterInfo`, `VoteSummary`, `VoteCount`, `ProposalSummary`, `ProposalDetail`, `KipDetail`, `FlipDetail`, `ProjectMeta`, `ProjectSummary`, `ApiIndex`.

- [ ] **Step 1:** Add `"pydantic>=2.7,<3"` to `dependencies` in `pyproject.toml`, run `uv sync`

- [ ] **Step 2:** Write tests in `tests/common/test_models.py`

Key test cases (class-based, following existing patterns):
- `TestVoterInfo`: serialization roundtrip
- `TestProposalSummary`: with/without `activity_status`
- `TestProposalDetail`: `None` fields for sentinel values
- `TestKipDetail`: is subclass of `ProposalDetail`, schema export works
- `TestFlipDetail`: has Flink-specific fields, all can be `None`
- `TestApiIndex`: empty projects, with projects

```python
class TestFlipDetail:
    def test_has_flink_specific_fields(self):
        detail = FlipDetail(
            id=1, title="Test FLIP", state="in progress",
            created_by="Alice", created_on="2025-01-02",
            last_modified_on="2025-01-03T10:00:00Z", last_modified_by="Alice",
            discussion_thread=None, vote_thread=None, jira=None,
            web_url="https://example.com", activity_status=None,
            votes=VoteSummary(plus_one=[], zero=[], minus_one=[]),
            release_version="1.18", release_component="Flink",
            jira_id="FLINK-12345",
            jira_link="https://issues.apache.org/jira/browse/FLINK-12345",
        )
        assert detail.release_version == "1.18"

    def test_flink_fields_can_be_none(self):
        detail = FlipDetail(
            id=2, title="Test", state="unknown",
            created_by="Bob", created_on="2025-06-01",
            last_modified_on="2025-06-02T10:00:00Z", last_modified_by="Bob",
            discussion_thread=None, vote_thread=None, jira=None,
            web_url="https://example.com", activity_status=None,
            votes=VoteSummary(plus_one=[], zero=[], minus_one=[]),
            release_version=None, release_component=None,
            jira_id=None, jira_link=None,
        )
        assert detail.release_version is None
```

Run: `uv run pytest tests/common/test_models.py -v` — expect FAIL

- [ ] **Step 3:** Write models in `ipper/common/models.py`

Model hierarchy (from spec):
```
BaseModel
├── VoterInfo              # name + timestamp (ISO 8601)
├── VoteSummary            # lists of VoterInfo for plus_one, zero, minus_one
├── VoteCount              # integer counts only (for summary list)
├── ProposalSummary        # compact: id, title, state, created_by, created_on, vote_count, activity_status, detail_url, web_url
├── ProposalDetail         # full: adds last_modified_on/by, discussion_thread, vote_thread, jira, votes (VoteSummary)
│   ├── KipDetail          # no extra fields (extensible)
│   └── FlipDetail         # adds: release_version, release_component, jira_id, jira_link
├── ProjectMeta            # name, proposal_type, count, summary_url
├── ProjectSummary         # project, proposal_type, last_updated, count, proposals list
└── ApiIndex               # version, last_updated, projects dict
```

All field definitions are in the spec section "Model Definitions" — use those exactly.

Run: `uv run pytest tests/common/test_models.py -v` — expect PASS

- [ ] **Step 4:** Commit

---

## Task 2: Skill File (parallel with Task 1)

**Files:**
- Create: `templates/skill/ossip/SKILL.md`

**Produces:** Static markdown file ready for deployment.

- [ ] **Step 1:** Create `templates/skill/ossip/SKILL.md`

Content follows spec section "Skill Structure" — frontmatter with `name: ossip` and `description`, then sections for Data Endpoints, Query Patterns (status lookup, activity queries, vote queries, cross-referencing), and Response Guidelines.

- [ ] **Step 2:** Commit

---

## Task 3: Shared JSON Output Utilities

**Depends on:** Task 1

**Files:**
- Create: `ipper/common/api_output.py`
- Create: `tests/common/test_api_output.py`

**Produces:** `write_json_file(model, path)`, `write_proposal_details(proposals, dir)`, `write_project_summary(summary, path)`, `write_schemas(dir)`, `generate_api_index(base_dir)`, plus shared helpers: `confluence_date_to_iso_date(s)`, `confluence_date_to_iso_datetime(s)`, `vote_timestamp_to_iso(s)`, `sentinel_to_none(s)`, `VOTE_TIMESTAMP_FORMAT`.

- [ ] **Step 1:** Write tests in `tests/common/test_api_output.py`

Key test classes:
- `TestWriteJsonFile`: creates parent dirs, writes valid JSON
- `TestWriteProposalDetails`: creates individual `{id}.json` files
- `TestWriteProjectSummary`: writes summary with correct structure
- `TestWriteSchemas`: creates schema files, valid JSON, idempotent
- `TestGenerateApiIndex`: both projects present (picks max `last_updated`), only one project, zero projects (valid empty index), writes schemas
- `TestDateConversions`: Confluence date to ISO date, Confluence date to ISO datetime, vote timestamp to ISO
- `TestSentinelToNone`: `"not set"` → `None`, `"unknown"` → `None`, real values preserved

Run: `uv run pytest tests/common/test_api_output.py -v` — expect FAIL

- [ ] **Step 2:** Write implementation in `ipper/common/api_output.py`

Date/sentinel helpers (public, used by kafka and flink conversion):
```python
VOTE_TIMESTAMP_FORMAT = "%b %d, %Y %H:%M UTC"

def confluence_date_to_iso_date(date_str: str) -> str:
    parsed = dt.datetime.strptime(date_str, APACHE_CONFLUENCE_DATE_FORMAT)
    return parsed.strftime("%Y-%m-%d")

def confluence_date_to_iso_datetime(date_str: str) -> str:
    parsed = dt.datetime.strptime(date_str, APACHE_CONFLUENCE_DATE_FORMAT)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")

def vote_timestamp_to_iso(timestamp_str: str) -> str:
    parsed = dt.datetime.strptime(timestamp_str, VOTE_TIMESTAMP_FORMAT)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")

def sentinel_to_none(value: str) -> str | None:
    if value in (NOT_SET_STR, UNKNOWN_STR):
        return None
    return value
```

Write utilities:
- `write_json_file(model, path)` — `model.model_dump_json(indent=2)`, create parent dirs
- `write_proposal_details(proposals, dir)` — iterate, write `{id}.json` each
- `write_project_summary(summary, path)` — delegate to `write_json_file`
- `write_schemas(dir)` — export `model_json_schema()` for `ApiIndex`, `ProjectSummary`, `KipDetail`, `FlipDetail`
- `generate_api_index(base_dir)` — scan for `kafka/kips.json` and `flink/flips.json`, read count/last_updated from each, build `ApiIndex`, write `index.json`, call `write_schemas`. Resilient: missing projects are skipped, zero projects produces valid empty index.

Run: `uv run pytest tests/common/test_api_output.py -v` — expect PASS

- [ ] **Step 3:** Commit

---

## Task 4: Kafka JSON Conversion Functions (parallel with Task 5)

**Depends on:** Task 3

**Files:**
- Modify: `ipper/kafka/output.py` (add functions, add imports)
- Create: `tests/kafka/test_json_api.py`

**Consumes:** Models from `ipper.common.models`, helpers from `ipper.common.api_output` (`confluence_date_to_iso_date`, `confluence_date_to_iso_datetime`, `vote_timestamp_to_iso`, `sentinel_to_none`, `write_proposal_details`, `write_project_summary`)

**Produces:** `kip_to_detail(wiki_entry, status_entry) -> KipDetail`, `kip_to_summary(status_entry, wiki_entry) -> ProposalSummary`, `generate_kafka_json_api(kip_status, kip_wiki_info, api_dir)`

- [ ] **Step 1:** Write tests in `tests/kafka/test_json_api.py`

Test data factories:
```python
def _make_kip_wiki_info_entry(kip_id=100):
    return {
        "kip_id": kip_id, "title": f"KIP-{kip_id}: Test Proposal",
        "web_url": f"https://wiki.apache.org/confluence/display/KAFKA/KIP-{kip_id}",
        "content_url": "https://example.com/api/content/12345",
        "created_on": "2025-01-15T10:30:00.000Z", "created_by": "Alice",
        "last_modified_on": "2025-02-20T14:45:00.000Z", "last_modified_by": "Bob",
        "state": "under discussion",
        "jira": "https://issues.apache.org/jira/browse/KAFKA-12345",
        "discussion_thread": "https://lists.apache.org/thread/abc123",
        "vote_thread": "not set",
    }

def _make_kip_status_entry(kip_id=100):
    return {
        "id": kip_id, "text": "Test Proposal",
        "url": f"https://wiki.apache.org/confluence/display/KAFKA/KIP-{kip_id}",
        "created_by": "Alice", "state": "under discussion",
        "age": "1 year", "status": KIPStatus.GREEN,
        "last_mention_age": "2 weeks", "emoji": None,
        "+1": [{"name": "Charlie", "timestamp": "Feb 10, 2025 09:00 UTC"}],
        "0": [], "-1": [{"name": "Eve", "timestamp": "Feb 09, 2025 11:00 UTC"}],
    }
```

Key test cases:
- `TestKipToDetail`: basic conversion, sentinel fields → `None`, vote timestamps converted to ISO 8601, `activity_status` is `status.text` for discussion KIPs and `None` for others, no votes produces empty lists
- `TestKipToSummary`: basic conversion, `title` uses full wiki title (not cleaned `text`), `created_on` is ISO date, `vote_count` has integer counts, `detail_url` is `kips/{id}.json`
- `TestGenerateKafkaJsonApi`: creates `kips.json` + `kips/{id}.json` files, skips KIPs missing from wiki info

Run: `uv run pytest tests/kafka/test_json_api.py -v` — expect FAIL

- [ ] **Step 2:** Add conversion functions to `ipper/kafka/output.py`

Add imports at top:
```python
import logging
from ipper.common.models import (
    KipDetail, ProposalSummary, ProjectSummary,
    VoteCount, VoterInfo, VoteSummary,
)
from ipper.common.api_output import (
    confluence_date_to_iso_date, confluence_date_to_iso_datetime,
    vote_timestamp_to_iso, sentinel_to_none,
    write_proposal_details, write_project_summary,
)
from ipper.common.constants import NOT_SET_STR, UNKNOWN_STR

logger = logging.getLogger(__name__)
```

Key mapping decisions for `kip_to_detail(wiki_entry, status_entry)`:
- `id` ← `status_entry["id"]`
- `title` ← `wiki_entry["title"]` (full title with "KIP-XXX:" prefix)
- `activity_status` ← `status_entry["status"].text` if status is not None, else `None`
- `created_on` ← `confluence_date_to_iso_date(wiki_entry["created_on"])`
- `last_modified_on` ← `confluence_date_to_iso_datetime(wiki_entry["last_modified_on"])`
- `discussion_thread`, `vote_thread`, `jira` ← `sentinel_to_none(wiki_entry[field])`
- Vote lists ← convert each voter's timestamp via `vote_timestamp_to_iso`

Key mapping for `kip_to_summary(status_entry, wiki_entry)`:
- `title` ← `wiki_entry["title"]` (full wiki title, NOT `status_entry["text"]`)
- `created_on` ← `confluence_date_to_iso_date(wiki_entry["created_on"])` (needs wiki_entry because status dict only has human-readable `age`)
- `vote_count` ← `VoteCount(plus_one=len(entry["+1"]), ...)`
- `detail_url` ← `f"kips/{id}.json"`

`generate_kafka_json_api(kip_status, kip_wiki_info, api_dir)`:
- Iterates `kip_status`, looks up each in `kip_wiki_info`, builds detail + summary lists
- Calls `write_proposal_details(details, api_dir / "kips")`
- Builds `ProjectSummary(project="kafka", proposal_type="KIP", ...)` and writes via `write_project_summary`

Run: `uv run pytest tests/kafka/test_json_api.py -v` — expect PASS
Run: `uv run pytest tests/kafka/ -v` — verify existing tests still pass

- [ ] **Step 3:** Commit

---

## Task 5: Flink JSON Conversion Functions (parallel with Task 4)

**Depends on:** Task 3

**Files:**
- Modify: `ipper/flink/output.py` (add functions, add imports)
- Create: `tests/flink/test_json_api.py`

**Consumes:** Same helpers from `ipper.common.api_output` as Task 4.

**Produces:** `flip_to_detail(flip_data) -> FlipDetail`, `flip_to_summary(flip_data) -> ProposalSummary`, `generate_flink_json_api(enriched_wiki_cache, api_dir)`

- [ ] **Step 1:** Write tests in `tests/flink/test_json_api.py`

Test data factory — enriched FLIP dict (after `enrich_flip_wiki_info_with_votes`):
```python
def _make_enriched_flip(flip_id=42):
    return {
        "id": flip_id, "title": f"FLIP-{flip_id}: Test Flink Proposal",
        "web_url": f"https://cwiki.apache.org/confluence/display/FLINK/FLIP-{flip_id}",
        "content_url": "https://example.com/api/content/67890",
        "created_on": "2025-03-01T09:00:00.000Z", "created_by": "Alice",
        "last_modified_on": "2025-04-15T16:20:00.000Z", "last_modified_by": "Bob",
        "state": "in progress",
        "discussion_thread": "https://lists.apache.org/thread/xyz789",
        "vote_thread": "not set",
        "release_component": "Flink", "release_version": "1.18",
        "jira_id": "FLINK-54321",
        "jira_link": "https://issues.apache.org/jira/browse/FLINK-54321",
        "+1": [{"name": "Charlie", "timestamp": "Mar 10, 2025 09:00 UTC"}],
        "0": [], "-1": [],
    }
```

Key test cases:
- `TestFlipToDetail`: basic conversion, sentinel values → `None`, vote timestamps converted, `activity_status` always `None`, Flink-specific fields populated, string `id` handled via `int()`
- `TestFlipToSummary`: basic conversion, `detail_url` is `flips/{id}.json`, `activity_status` always `None`
- `TestGenerateFlinkJsonApi`: creates `flips.json` + `flips/{id}.json` files

Run: `uv run pytest tests/flink/test_json_api.py -v` — expect FAIL

- [ ] **Step 2:** Add conversion functions to `ipper/flink/output.py`

Add imports at top (similar to Task 4 but with `FlipDetail` instead of `KipDetail`).
Add `logger = logging.getLogger(__name__)`.

Key mapping for `flip_to_detail(flip_data)`:
- Takes single dict (already enriched with votes, unlike Kafka which takes two dicts)
- `id` ← `int(flip_data["id"])` (FLIP cache uses string keys)
- `activity_status` ← always `None`
- `jira` ← `sentinel_to_none(flip_data.get("jira_link", NOT_SET_STR))` (maps to URL, consistent with Kafka's `jira` field)
- Flink-specific: `release_version`, `release_component`, `jira_id`, `jira_link` all via `sentinel_to_none`

`generate_flink_json_api(enriched_wiki_cache, api_dir)`:
- Keys in `enriched_wiki_cache` are STRINGS (JSON dict keys) — sort by `int(key)` descending
- Builds `ProjectSummary(project="flink", proposal_type="FLIP", ...)`

Run: `uv run pytest tests/flink/test_json_api.py -v` — expect PASS
Run: `uv run pytest tests/flink/ -v` — verify existing tests still pass

- [ ] **Step 3:** Commit

---

## Task 6: Kafka Refactoring + CLI `--api-dir` (parallel with Task 7)

**Depends on:** Tasks 3, 4

**Files:**
- Modify: `ipper/kafka/output.py` (refactor `render_standalone_status_page` signature)
- Modify: `ipper/kafka/main.py` (refactor `run_output_standalone_cmd`, add `--api-dir`)

**Refactoring overview:**

The current `render_standalone_status_page(kip_mentions, output_file)` internally calls `get_kip_main_page_info()` and `get_kip_information()`. Then `run_output_standalone_cmd` calls those SAME functions again for KIP info pages. This double-fetch is moved to the caller.

- [ ] **Step 1:** Refactor `render_standalone_status_page` in `ipper/kafka/output.py`

Change signature from:
```python
def render_standalone_status_page(kip_mentions: DataFrame, output_filename: str, ...) -> None:
```
to:
```python
def render_standalone_status_page(kip_status: list[dict], output_filename: str, ...) -> None:
```

Remove the internal calls to `get_kip_main_page_info()`, `get_kip_information()`, and `create_status_dict()` from the function body. The function now just renders the template with the pre-computed `kip_status`.

Remove the now-unused imports of `get_kip_main_page_info` and `get_kip_information` from `ipper/kafka/output.py`.

- [ ] **Step 2:** Refactor `run_output_standalone_cmd` in `ipper/kafka/main.py`

New implementation:
```python
def run_output_standalone_cmd(args: Namespace) -> None:
    cache_file = Path(args.kip_mentions_file)
    kip_mentions = load_mbox_cache_file(cache_file)

    # Load wiki data ONCE (was fetched twice before)
    kip_main_info = get_kip_main_page_info()
    kip_wiki_info = get_kip_information(kip_main_info)

    kip_status = create_status_dict(kip_mentions, kip_wiki_info)
    render_standalone_status_page(kip_status, args.output_file)

    if args.kip_info_dir:
        enriched_kip_info = enrich_kip_wiki_info_with_votes(kip_wiki_info, kip_mentions)
        render_kip_info_pages(enriched_kip_info, args.kip_info_dir)

    if args.api_dir:
        generate_kafka_json_api(kip_status, kip_wiki_info, Path(args.api_dir))
```

Add imports: `create_status_dict`, `generate_kafka_json_api` from `ipper.kafka.output`.

- [ ] **Step 3:** Add `--api-dir` argument in `setup_output_command`

Add to `standalone_subparser` (after `kip_info_dir` argument, around line 192):
```python
standalone_subparser.add_argument(
    "--api-dir", default=None,
    help="Optional: Directory for JSON API output (e.g., site_files/api/v1/kafka)",
)
```

- [ ] **Step 4:** Run all kafka tests to verify no regressions

Run: `uv run pytest tests/kafka/ -v` — expect PASS

- [ ] **Step 5:** Commit

---

## Task 7: Flink Refactoring + CLI `--api-dir` (parallel with Task 6)

**Depends on:** Tasks 3, 5

**Files:**
- Modify: `ipper/flink/output.py` (remove `flip_mentions` param from renderers)
- Modify: `ipper/flink/main.py` (refactor `process_output`, add `--api-dir`)

**Refactoring overview:**

Currently `render_flink_main_page` and `render_raw_info_pages` each accept `flip_mentions` and independently call `enrich_flip_wiki_info_with_votes()` — enriching twice. The enrichment moves to `process_output()`, which enriches once and passes pre-enriched data to both renderers.

- [ ] **Step 1:** Remove `flip_mentions` parameter from renderers in `ipper/flink/output.py`

For `render_flink_main_page` (line 71): remove `flip_mentions: DataFrame | None = None` parameter and the `if flip_mentions is not None: wiki_cache = enrich_flip_wiki_info_with_votes(...)` block.

For `render_raw_info_pages` (line 112): same change.

Both functions now expect pre-enriched `wiki_cache` data.

- [ ] **Step 2:** Refactor `process_output` in `ipper/flink/main.py`

New implementation:
```python
def process_output(args: Namespace) -> None:
    wiki_cache_path = Path(args.wiki_cache_file)
    if not wiki_cache_path.exists():
        raise AttributeError(f"Wiki Cache file {wiki_cache_path} does not exist")

    with open(wiki_cache_path, encoding="utf8") as wiki_cache_file:
        wiki_cache_data = json.load(wiki_cache_file)

    # Enrich with vote data ONCE (was done twice, once per renderer)
    mentions_file = Path("cache/flink_mailbox_files/flip_mentions.csv")
    if mentions_file.exists():
        logger.info("Loading FLIP mentions from %s", mentions_file)
        flip_mentions = load_mbox_cache_file(mentions_file)
        wiki_cache_data = enrich_flip_wiki_info_with_votes(wiki_cache_data, flip_mentions)
    else:
        logger.info("No FLIP mentions file found, rendering without vote data")

    render_flink_main_page(wiki_cache_data, args.main_page_file,
                           args.template_dir, args.main_page_template_filename)

    render_raw_info_pages(wiki_cache_data, args.raw_flip_dir,
                          args.template_dir, args.raw_flip_template_filename)

    if args.api_dir:
        generate_flink_json_api(wiki_cache_data, Path(args.api_dir))
```

Add imports: `enrich_flip_wiki_info_with_votes`, `generate_flink_json_api` from `ipper.flink.output`.

- [ ] **Step 3:** Add `--api-dir` argument in `setup_output_command`

Add to `output_parser` (after existing optional arguments, around line 470):
```python
output_parser.add_argument(
    "--api-dir", default=None,
    help="Optional: Directory for JSON API output (e.g., site_files/api/v1/flink)",
)
```

- [ ] **Step 4:** Run all flink tests to verify no regressions

Run: `uv run pytest tests/flink/ -v` — expect PASS

- [ ] **Step 5:** Commit

---

## Task 8: Build Pipeline Changes (parallel with Task 9)

**Depends on:** Tasks 6, 7

**Files:**
- Modify: `local_build.sh`
- Modify: `.github/workflows/publish.yaml`

- [ ] **Step 1:** Update `local_build.sh`

1. Add skill file and API docs copy to static files section (after `cp -r templates/assets site_files/assets`):
```bash
mkdir -p site_files/skill/ossip
cp templates/skill/ossip/SKILL.md site_files/skill/ossip/SKILL.md
cp templates/api.html site_files/api.html
```

2. Add `--api-dir` to Kafka build (line 67):
```bash
uv run python ipper/main.py kafka output standalone \
  cache/mailbox_files/kip_mentions.csv site_files/kafka.html site_files/kips \
  --api-dir site_files/api/v1/kafka
```

3. Add `--api-dir` to Flink build (line 71):
```bash
uv run python ipper/main.py flink output \
  cache/flip_wiki_cache.json site_files/flink.html site_files/flips \
  --api-dir site_files/api/v1/flink
```

4. Add index generation post-step (before final success message):
```bash
echo "Generating API index..."
uv run python -c "
from ipper.common.api_output import generate_api_index
from pathlib import Path
generate_api_index(Path('site_files/api/v1'))
"
```

- [ ] **Step 2:** Update `.github/workflows/publish.yaml`

1. Add `id: kafka-build` and `continue-on-error: true` to "Build the Kafka site" step; add `--api-dir site_files/api/v1/kafka`
2. Add `id: flink-build` and `continue-on-error: true` to "Build the Flink site" step; add `--api-dir site_files/api/v1/flink`
3. Add skill file + API docs copy step after static file copy
4. Add "Generate API index" step (calls `generate_api_index`)
5. Add "Check build results" step with `if: always()` that warns on individual failures, errors if both fail

- [ ] **Step 3:** Commit

---

## Task 9: Integration Tests (parallel with Task 8)

**Depends on:** Tasks 6, 7

**Files:**
- Create: `tests/common/test_json_api_integration.py`

- [ ] **Step 1:** Write integration tests

Key test classes:
- `TestKafkaIntegration`: end-to-end with realistic multi-KIP data — verify `kips.json` validates as `ProjectSummary`, individual detail files validate as `KipDetail`, sentinel values are `None`, activity_status correct
- `TestFlinkIntegration`: same pattern with FLIP data — verify Flink-specific fields, `activity_status` always `None`
- `TestApiIndexIntegration`: full pipeline — generate Kafka JSON, generate index, verify `index.json` has correct counts and `last_updated`, schemas exist
- `TestSchemaValidation`: generate JSON files, read them back, validate against Pydantic models
- `TestHtmlUnchanged`: verify `render_standalone_status_page` works with pre-computed `kip_status` (new signature)

Run: `uv run pytest tests/common/test_json_api_integration.py -v` — expect PASS

- [ ] **Step 2:** Run full test suite

Run: `uv run pytest -v` — expect all PASS

- [ ] **Step 3:** Commit

---

## Task 10: Documentation (parallel with Tasks 3-7)

**Depends on:** Task 2 (skill file)

**Files:**
- Create: `templates/api.html`
- Modify: `README.md`

**Produces:** A static HTML page at `ossip.dev/api.html` and a README section, both explaining the JSON API and skill installation.

- [ ] **Step 1:** Create `templates/api.html`

Static HTML page (same structure as `templates/index.html` — uses `style.css`, includes the trademark footer). Content sections:

1. **JSON API** — overview of the API, daily refresh cadence, CORS availability
2. **Endpoints** — table of all endpoints with URLs, descriptions, and example response snippets:
   - `api/v1/index.json` — API entry point
   - `api/v1/kafka/kips.json` — Kafka KIP summary list
   - `api/v1/kafka/kips/{id}.json` — individual KIP detail
   - `api/v1/flink/flips.json` — Flink FLIP summary list
   - `api/v1/flink/flips/{id}.json` — individual FLIP detail
   - `api/v1/schemas/` — JSON Schema files
3. **Field Reference** — key field definitions: `state` values, `activity_status` color meanings, date format conventions, `null` for unset fields
4. **Using the OSSIP Skill** — what the skill is, what agents it works with, common query patterns
5. **Installation** — step-by-step for each agent:
   - **Claude Code (project-scoped):** download `SKILL.md` to `.claude/skills/ossip/SKILL.md`
   - **Claude Code (personal):** download to `~/.claude/skills/ossip/SKILL.md`
   - **Claude Desktop / other agents:** note that any agent supporting the [Agent Skills](https://agentskills.io) standard can use the skill file
6. **Schemas** — link to the auto-generated JSON Schema files for programmatic consumers

Add a link to `api.html` from `templates/index.html` (e.g., a small "API" link in the header or below the project cards).

- [ ] **Step 2:** Add JSON API and skill section to `README.md`

Add a section covering:
- Brief description of the JSON API (endpoints, refresh cadence)
- Skill installation instructions (Claude Code project-scoped and personal)
- Link to the full documentation at `ossip.dev/api.html`

- [ ] **Step 3:** Update Task 8's build pipeline to copy `api.html`

Note: Task 8 already handles static file copying. Add to the static files section in both `local_build.sh` and `publish.yaml`:
```bash
cp templates/api.html site_files/api.html
```

- [ ] **Step 4:** Commit

---

## Verification

After all tasks complete:

1. **Unit tests:** `uv run pytest -v` — all pass
2. **Lint:** `uv run ruff check ipper/ tests/` — no errors
3. **Format:** `uv run ruff format --check ipper/ tests/` — no errors
4. **Local build:** `./local_build.sh --render-only` — generates HTML + JSON API files in `site_files/`
5. **Spot-check output:**
   - `site_files/api/v1/index.json` exists with both projects
   - `site_files/api/v1/kafka/kips.json` has correct count
   - `site_files/api/v1/kafka/kips/1.json` is valid KipDetail
   - `site_files/api/v1/flink/flips.json` has correct count
   - `site_files/api/v1/schemas/` has 4 schema files
   - `site_files/skill/ossip/SKILL.md` exists
   - `site_files/api.html` exists and renders correctly
6. **HTML regression:** diff `site_files/kafka.html` and `site_files/flink.html` against prior build — no changes
7. **Documentation:** verify `api.html` links work, skill installation instructions are accurate, README section is present
