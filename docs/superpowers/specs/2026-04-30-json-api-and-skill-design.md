# OSSIP JSON Data API & Claude Code Skill

## Problem

OSSIP aggregates useful data about Apache improvement proposals (KIPs, FLIPs) — status, votes, activity, authorship — but this data is only accessible as rendered HTML on ossip.dev. AI agents cannot reliably extract structured information from the HTML pages (the Kafka page alone is 1.5MB), and the data is not available in any machine-readable format.

## Goal

Expose OSSIP's enriched data as structured JSON files on ossip.dev, and provide a Claude Code skill that teaches agents how to query them. The solution should:

- Work from any repo or conversation (not just inside the OSSIP project)
- Require zero infrastructure beyond the existing GitHub Pages deployment
- Be easy for other developers to install and use
- Support the full range of queries: status lookups, activity summaries, vote details, and keyword search across proposals

## Non-Goals

- Real-time data (daily CI updates are sufficient)
- Server-side filtering or search (agents filter client-side)
- Remote MCP server (future possibility, not in scope)
- Changes to the existing HTML site or templates

---

## Architecture

### Data Flow

```
Existing enriched data (dicts from output.py)
    ├── Jinja2 templates → HTML files (unchanged)
    └── Pydantic models → JSON files (new)
```

JSON generation is a second output format from the same data pipeline. No new data processing logic is needed — only serialization.

### Deployed File Structure

```
ossip.dev/
├── api/
│   └── v1/
│       ├── index.json                          # Entry point: projects, counts, last updated
│       ├── schemas/
│       │   ├── ApiIndex.schema.json
│       │   ├── ProjectSummary.schema.json
│       │   ├── ProposalDetail.schema.json
│       │   ├── KipDetail.schema.json
│       │   └── FlipDetail.schema.json
│       ├── kafka/
│       │   ├── kips.json                       # Summary list (~230KB)
│       │   └── kips/
│       │       ├── 1.json ... 1284.json        # Individual KIP details (<2KB each)
│       └── flink/
│           ├── flips.json                      # Summary list
│           └── flips/
│               ├── 1.json ... 570.json         # Individual FLIP details
├── skill/
│   └── ossip/
│       └── SKILL.md                            # Claude Code skill file
```

### Size Estimates

| File | Estimated Size |
|------|---------------|
| `index.json` | <1KB |
| `kips.json` (summary, all 1284) | ~230KB |
| `flips.json` (summary, all 570) | ~100KB |
| Individual detail files | <2KB each |
| Schema files | <3KB each |
| Total new files | ~1,860 files |

At current scale, the summary files are small enough for agents to fetch and filter client-side. If the proposal count grows significantly (e.g., 5,000+ KIPs), the summary file would exceed ~1MB and a lighter index (IDs + titles only) or pagination should be considered.

---

## Pydantic Models

### Module: `ipper/common/models.py`

All data structures are defined as Pydantic models. These serve as:
1. The serialization layer (model → JSON file)
2. The schema source (auto-exported via `model_json_schema()`)
3. Runtime validation (catch malformed data before it reaches the site)

### Model Hierarchy

```
BaseModel
├── VoterInfo              # name + timestamp for a single vote
├── VoteSummary            # lists of VoterInfo for +1, 0, -1
├── VoteCount              # integer counts only (for summary list)
├── ProposalSummary        # compact proposal for summary lists
├── ProposalDetail         # full proposal with vote details
│   ├── KipDetail          # adds: (no extra fields currently, but extensible)
│   └── FlipDetail         # adds: release_version, release_component, jira_id, jira_link
├── ProjectMeta            # name, proposal_type, count, summary_url
├── ProjectSummary         # wraps list of ProposalSummary
└── ApiIndex               # top-level entry point
```

### Model Definitions

```python
from pydantic import BaseModel


class VoterInfo(BaseModel):
    name: str
    timestamp: str


class VoteSummary(BaseModel):
    plus_one: list[VoterInfo]
    zero: list[VoterInfo]
    minus_one: list[VoterInfo]


class VoteCount(BaseModel):
    plus_one: int
    zero: int
    minus_one: int


class ProposalSummary(BaseModel):
    id: int
    title: str
    state: str
    created_by: str
    created_on: str
    vote_count: VoteCount
    activity_status: str | None
    detail_url: str
    web_url: str


class ProposalDetail(BaseModel):
    id: int
    title: str
    state: str
    created_by: str
    created_on: str
    last_modified_on: str
    last_modified_by: str
    discussion_thread: str | None
    vote_thread: str | None
    jira: str | None
    web_url: str
    activity_status: str | None
    votes: VoteSummary


class KipDetail(ProposalDetail):
    pass


class FlipDetail(ProposalDetail):
    release_version: str | None
    release_component: str | None
    jira_id: str | None
    jira_link: str | None


class ProjectMeta(BaseModel):
    name: str
    proposal_type: str
    count: int
    summary_url: str


class ProjectSummary(BaseModel):
    project: str
    proposal_type: str
    last_updated: str
    count: int
    proposals: list[ProposalSummary]


class ApiIndex(BaseModel):
    version: int
    last_updated: str
    projects: dict[str, ProjectMeta]
```

### Field Value Conventions

- Fields with wiki value `"not set"` or `"unknown"` are mapped to `None` in the Pydantic models. Consumers should never see the sentinel strings.
- `activity_status` values: `"blue"` (new, <4 weeks old), `"green"` (<4 weeks since last mention), `"yellow"` (<12 weeks), `"red"` (<1 year), `"black"` (>1 year or never mentioned). `null` for proposals not in "under discussion" state.
- `state` values match `IPState`: `"accepted"`, `"under discussion"`, `"not accepted"`, `"completed"`, `"in progress"`, `"unknown"`.
- Date fields use ISO 8601 format. Fields that represent calendar dates (`created_on`) use `YYYY-MM-DD`. Fields that represent points in time (`last_modified_on`, `VoterInfo.timestamp`, `ProjectSummary.last_updated`, `ApiIndex.last_updated`) use `YYYY-MM-DDTHH:MM:SSZ`.

### Subclassing Rationale

Flink proposals have fields that Kafka proposals don't (`release_version`, `release_component`, `jira_id`, `jira_link`). Rather than making these optional on a single model (which would become messy as more projects are added), each project gets its own subclass of `ProposalDetail`. This keeps schemas clean and per-project fields contained.

---

## New Modules

### `ipper/common/models.py`

Pydantic model definitions as described above.

### `ipper/common/api_output.py`

Shared JSON rendering logic:

- `write_json_file(model: BaseModel, output_path: Path)` — writes a single Pydantic model to a JSON file, creating parent directories as needed
- `write_proposal_details(proposals: list[ProposalDetail], output_dir: Path)` — writes individual `{id}.json` files
- `write_project_summary(summary: ProjectSummary, output_path: Path)` — writes the summary list file
- `write_schemas(output_dir: Path)` — exports JSON Schema files from all Pydantic models. Called from the index post-step rather than from each project, to avoid a race condition when projects build in parallel
- `generate_api_index(api_base_dir: Path)` — **resilient index generator**: scans `api_base_dir` for per-project summary files (`kafka/kips.json`, `flink/flips.json`), reads each one found to extract count and last_updated, assembles an `ApiIndex` model, and writes `index.json`. The top-level `ApiIndex.last_updated` is derived as the maximum `last_updated` across all discovered project summaries (or the current UTC timestamp if no projects are found). Also calls `write_schemas()` to export JSON Schema files. If no project files are found, writes a valid empty index. This replaces the originally-considered `api finalize` CLI subcommand with a simple function call.

### Changes to `ipper/kafka/output.py`

**Refactor `render_standalone_status_page()`**: Currently this function internally fetches wiki data from Confluence (`get_kip_main_page_info()` → `get_kip_information()`). This data loading is extracted to the caller (`run_output_standalone_cmd` in `ipper/kafka/main.py`) so the enriched data is available for both HTML rendering and JSON generation. This also fixes an existing inefficiency where wiki data was fetched twice when generating both the main page and individual KIP info pages.

After refactoring, `render_standalone_status_page()` accepts pre-computed `kip_status` data instead of a DataFrame.

**Add JSON conversion functions**:
- `kip_to_detail(kip_wiki_info: dict, kip_status_entry: dict) -> KipDetail` — merges raw wiki fields (discussion_thread, vote_thread, jira, last_modified_on/by) with status fields (activity_status from `KIPStatus` enum, full vote lists). Maps `kip_id` to `id`, `NOT_SET_STR` to `None`, Confluence dates to ISO 8601, `KIPStatus.text` to activity_status string.
- `kip_to_summary(kip_status_entry: dict) -> ProposalSummary` — compact version with integer vote counts
- `generate_kafka_json_api(kip_status: list[dict], kip_wiki_info: dict, api_dir: Path)` — orchestrates conversion of all KIPs to models and calls shared write functions

### Changes to `ipper/kafka/main.py`

Add `--api-dir` optional argument to the `standalone` output subparser. Refactor `run_output_standalone_cmd()` to load wiki data once and pass the enriched data to HTML rendering, KIP info page rendering, and (if `--api-dir` is set) JSON generation.

### Changes to `ipper/flink/output.py`

**Add JSON conversion functions**:
- `flip_to_detail(flip_data: dict) -> FlipDetail` — maps enriched FLIP wiki dict to `FlipDetail`, including Flink-specific fields (`release_version`, `release_component`, `jira_id`, `jira_link`). Maps `UNKNOWN_STR` to `None`. Sets `activity_status` to `None` (Flink does not use colored activity status).
- `flip_to_summary(flip_data: dict) -> ProposalSummary` — compact version with integer vote counts
- `generate_flink_json_api(enriched_wiki_cache: dict, api_dir: Path)` — orchestrates conversion and write

### Changes to `ipper/flink/main.py`

Add `--api-dir` optional argument to the output parser. Refactor `process_output()` to enrich wiki data once (currently `enrich_flip_wiki_info_with_votes` is called twice — once per HTML renderer) and pass the pre-enriched data to both HTML renderers and (if `--api-dir` is set) JSON generation.

---

## Build Pipeline Integration

### Approach: Per-Project Integrated Output

JSON generation is added to each project's existing output command rather than creating a separate cross-project command. When the HTML output runs, JSON files are generated alongside it into a `site_files/api/v1/` directory. Each project generates its own JSON independently — if one project's build fails, the other still produces valid JSON output.

The existing output commands gain an optional `--api-dir` argument:

```bash
# Generates both HTML and JSON API
uv run python ipper/main.py kafka output standalone \
  cache/mailbox_files/kip_mentions.csv site_files/kafka.html site_files/kips \
  --api-dir site_files/api/v1/kafka

uv run python ipper/main.py flink output \
  cache/flip_wiki_cache.json site_files/flink.html site_files/flips \
  --api-dir site_files/api/v1/flink
```

Each project's output step writes:
- Its summary file (`kips.json` or `flips.json`)
- Individual detail files (`kips/{id}.json` or `flips/{id}.json`)

The `index.json` and JSON Schema files are generated by a lightweight post-step that scans the filesystem for whatever project summaries exist. Schemas are written here rather than in each project's output step to avoid a race condition when projects build in parallel (as they do in `local_build.sh`). This is a function call in `ipper/common/api_output.py`, not a CLI subcommand.

### Fault Tolerance Design

The current pipeline treats each project independently — `local_build.sh` even runs Kafka and Flink updates in parallel. The JSON API preserves this independence:

1. Each project's `--api-dir` output is self-contained — no dependency on the other project
2. The `generate_api_index()` post-step is resilient: it discovers what project summary files exist on disk and assembles `index.json` from whatever it finds
3. If only one project succeeds, `index.json` lists only that project — partial but accurate
4. If zero projects succeed, `index.json` is a valid empty index (`{"version": 1, "projects": {}}`)

### `local_build.sh` Changes

Add `--api-dir` arguments to the existing build commands and a resilient index generation post-step:

```bash
# Build Kafka (HTML + JSON)
uv run python ipper/main.py kafka output standalone \
  cache/mailbox_files/kip_mentions.csv site_files/kafka.html site_files/kips \
  --api-dir site_files/api/v1/kafka

# Build Flink (HTML + JSON)
uv run python ipper/main.py flink output \
  cache/flip_wiki_cache.json site_files/flink.html site_files/flips \
  --api-dir site_files/api/v1/flink

# Generate API index from whatever project outputs exist
uv run python -c "
from ipper.common.api_output import generate_api_index
from pathlib import Path
generate_api_index(Path('site_files/api/v1'))
"
```

For fault tolerance, the build script should track per-project exit codes (it already has this pattern with `KIP_EXIT` and `FLIP_EXIT` for the update steps) and allow the build to continue when one project fails, reporting the failure at the end.

### `publish.yaml` (CI) Changes

Same `--api-dir` arguments added to the existing build steps. Each project build step uses `continue-on-error: true` so the pipeline doesn't abort when one project fails. A post-step generates `index.json` from whatever succeeded. A final check step reports which projects succeeded or failed.

```yaml
- name: Build the Kafka site
  run: |
    uv run python ipper/main.py kafka output standalone \
      cache/mailbox_files/kip_mentions.csv site_files/kafka.html site_files/kips \
      --api-dir site_files/api/v1/kafka
  continue-on-error: true

- name: Build the Flink site
  run: |
    uv run python ipper/main.py flink output \
      cache/flip_wiki_cache.json site_files/flink.html site_files/flips \
      --api-dir site_files/api/v1/flink
  continue-on-error: true

- name: Generate API index
  run: |
    uv run python -c "
    from ipper.common.api_output import generate_api_index
    from pathlib import Path
    generate_api_index(Path('site_files/api/v1'))
    "

- name: Check build results
  if: always()
  run: |
    if [ "${{ steps.kafka-build.outcome }}" = "failure" ]; then
      echo "::warning::Kafka build failed — JSON API will not include KIP data"
    fi
    if [ "${{ steps.flink-build.outcome }}" = "failure" ]; then
      echo "::warning::Flink build failed — JSON API will not include FLIP data"
    fi
```

Note: The Kafka and Flink build steps need `id: kafka-build` and `id: flink-build` respectively for the outcome check to reference them.

The JSON files land in `site_files/` and are picked up by the existing pages artifact upload. JSON API files are ephemeral build artifacts in `site_files/` and are NOT committed to the repository (covered by the existing `site_files/*` gitignore rule). GitHub Pages serves files with permissive CORS headers by default, which is sufficient for agent-based and browser-based consumers fetching the JSON API.

### Skill File Deployment

The skill file is stored in the repo at `templates/skill/ossip/SKILL.md` and deployed to `ossip.dev/skill/ossip/SKILL.md`. This follows the current Claude Code skill format where skills are directories containing a `SKILL.md` file. The directory is copied during the static file copy step alongside `index.html` and `style.css`:

```bash
mkdir -p site_files/skill/ossip
cp templates/skill/ossip/SKILL.md site_files/skill/ossip/SKILL.md
```

---

## New Dependency

Add `pydantic` to the project dependencies in `pyproject.toml`:

```toml
dependencies = [
    # ... existing deps ...
    "pydantic>=2.7,<3",
]
```

Pinned above 2.7 to avoid early Pydantic 2.x `model_json_schema()` inconsistencies, and below 3 to prevent breaking changes from a major version bump.

---

## Claude Code Skill

### Location

- Source: `templates/skill/ossip/SKILL.md` (in the repo)
- Deployed: `ossip.dev/skill/ossip/SKILL.md` (on the static site)

### Content

The skill file teaches Claude how to:

1. **Discover** — fetch `index.json` to learn what projects and data are available
2. **Lookup** — fetch individual detail files for specific KIP/FLIP queries
3. **Search/Filter** — fetch summary files and filter by state, activity, author, or title keywords
4. **Cross-reference** — search titles for domain terms when the user is working on related code

### Skill Structure

```markdown
---
name: ossip
description: Query Apache KIP/FLIP improvement proposal data from ossip.dev
---

# OSSIP — Open Source Software Improvement Proposals

[Instructions for using the JSON API endpoints]

## Data Endpoints

- Index: https://ossip.dev/api/v1/index.json
- Kafka summary: https://ossip.dev/api/v1/kafka/kips.json
- Kafka detail: https://ossip.dev/api/v1/kafka/kips/{id}.json
- Flink summary: https://ossip.dev/api/v1/flink/flips.json
- Flink detail: https://ossip.dev/api/v1/flink/flips/{id}.json
- Schemas: https://ossip.dev/api/v1/schemas/

## Query Patterns

### Status lookup
Fetch the detail endpoint for the specific proposal ID.

### Activity queries
Fetch the summary endpoint, filter by state and activity_status fields.

### Vote queries
Fetch the detail endpoint for full voter names and timestamps.

### Cross-referencing
Fetch the summary endpoint, search title fields for relevant terms.

## Response Guidelines

- Always link to the proposal's web_url for the canonical wiki source
- Note the last_updated timestamp so users know data freshness
- For vote counts, clarify these are binding votes detected from mailing lists
- Link to the OSSIP detail page for visual context when helpful
```

### Installation

Users download the skill directory and place it at `~/.claude/skills/ossip/SKILL.md` for personal use, or `.claude/skills/ossip/SKILL.md` in a project for project-scoped use. The skill follows the [Agent Skills open standard](https://agentskills.io), keeping frontmatter to the standard fields (`name`, `description`). Documentation for installation will be on the OSSIP README and/or site.

---

## Testing Strategy

### Unit Tests (`tests/common/test_models.py`)

- Pydantic model serialization: verify models produce expected JSON structure
- Schema export: verify `model_json_schema()` output is valid JSON Schema
- Sentinel string cleanup: verify models never contain `"not set"` or `"unknown"` — these should be `None`
- `KipDetail` and `FlipDetail` subclass behavior

### Unit Tests (`tests/common/test_api_output.py`)

- `write_proposal_details` creates correct file structure with valid JSON
- `write_project_summary` produces valid JSON matching model schema
- `write_schemas` produces valid JSON Schema files (idempotent)
- `generate_api_index` with both projects present
- `generate_api_index` with only one project present (fault tolerance)
- `generate_api_index` with zero projects present (empty but valid index)

### Unit Tests (`tests/kafka/test_json_api.py`, `tests/flink/test_json_api.py`)

- Per-project dict → Pydantic model conversion (KIP and FLIP)
- Field mapping: `kip_id` → `id`, `NOT_SET_STR`/`UNKNOWN_STR` → `None`, Confluence dates → ISO 8601
- Edge cases: proposals with no votes, missing fields, unknown state
- Flink-specific: `release_version`, `release_component`, `jira_id`, `jira_link` mapping

### Integration Tests

- End-to-end JSON generation: run the output command with `--api-dir` on test data, verify file structure and contents
- Schema validation: validate generated JSON data files against the exported schemas
- Size sanity checks: verify summary files are within expected size ranges
- Verify HTML output is unchanged when `--api-dir` is added

### CI Validation

- Add a step to validate generated JSON against schemas as part of the build
- This catches data/schema drift before it reaches the live site

---

## Summary

| Component | What | Where |
|-----------|------|-------|
| Pydantic models | Data structures + validation + schema source | `ipper/common/models.py` |
| JSON renderer | Shared write utilities + resilient index generation | `ipper/common/api_output.py` |
| Kafka integration | Convert KIP data → models → JSON + refactor data loading | `ipper/kafka/output.py`, `ipper/kafka/main.py` (modified) |
| Flink integration | Convert FLIP data → models → JSON + refactor enrichment | `ipper/flink/output.py`, `ipper/flink/main.py` (modified) |
| API index + schemas | Resilient filesystem-scanning index + JSON Schema export | `ipper/common/api_output.py` |
| Build integration | `--api-dir` flag on per-project output + resilient index post-step | `local_build.sh`, `publish.yaml` |
| Claude Code skill | Agent instructions for querying the API | `templates/skill/ossip/SKILL.md` |
| New dependency | Pydantic | `pyproject.toml` |
