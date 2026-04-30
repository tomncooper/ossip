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
│   └── ossip.md                                # Claude Code skill file
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
- Date fields use ISO 8601 format (`YYYY-MM-DD` for dates, `YYYY-MM-DDTHH:MM:SSZ` for timestamps).

### Subclassing Rationale

Flink proposals have fields that Kafka proposals don't (`release_version`, `release_component`, `jira_id`, `jira_link`). Rather than making these optional on a single model (which would become messy as more projects are added), each project gets its own subclass of `ProposalDetail`. This keeps schemas clean and per-project fields contained.

---

## New Modules

### `ipper/common/models.py`

Pydantic model definitions as described above.

### `ipper/common/api_output.py`

Shared JSON rendering logic:

- `write_proposal_detail(proposal: ProposalDetail, output_dir: Path)` — writes a single `{id}.json` file
- `write_project_summary(summary: ProjectSummary, output_path: Path)` — writes the summary list
- `write_api_index(index: ApiIndex, output_path: Path)` — writes `index.json`
- `write_schemas(output_dir: Path)` — exports JSON Schema files from Pydantic models
- `render_json_api(...)` — orchestrates all of the above for a given project

### Changes to `ipper/kafka/output.py`

Add a function to convert existing enriched KIP data dicts into `KipDetail` / `ProposalSummary` Pydantic models and call the shared JSON rendering. This reuses the same enriched data that the HTML renderer already computes.

### Changes to `ipper/flink/output.py`

Same pattern as Kafka, using `FlipDetail` for the detail models.

---

## Build Pipeline Integration

### Approach: Integrated Output

JSON generation is added to the existing output commands rather than creating separate commands. When the HTML output runs, JSON files are generated alongside it into a `site_files/api/v1/` directory.

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

The `index.json` and schemas are written after both projects have generated their data. This could be a small post-step in the build script or a dedicated command.

### `local_build.sh` Changes

Add `--api-dir` arguments to the existing build commands and a final step to generate `index.json` and schemas:

```bash
# Build Kafka (HTML + JSON)
uv run python ipper/main.py kafka output standalone \
  cache/mailbox_files/kip_mentions.csv site_files/kafka.html site_files/kips \
  --api-dir site_files/api/v1/kafka

# Build Flink (HTML + JSON)
uv run python ipper/main.py flink output \
  cache/flip_wiki_cache.json site_files/flink.html site_files/flips \
  --api-dir site_files/api/v1/flink

# Generate API index and schemas
uv run python ipper/main.py api finalize site_files/api/v1
```

### `api finalize` Command

A new top-level subcommand in `ipper/main.py` (alongside `kafka` and `flink`). It:
1. Reads the project-level summary files already written by the Kafka/Flink output steps
2. Generates `index.json` with project metadata and counts
3. Exports JSON Schema files from all Pydantic models to `schemas/`

This runs after both project output steps, since it needs to know the total counts from each project.

### `publish.yaml` (CI) Changes

Same `--api-dir` arguments added to the existing build steps. One new step added after the project builds to run `api finalize`. The JSON files land in `site_files/` and are picked up by the existing pages artifact upload.

### Skill File Deployment

The `ossip.md` skill file is a static file stored in the repo (e.g., `templates/skill/ossip.md`). It is copied to `site_files/skill/ossip.md` during the static file copy step, alongside `index.html` and `style.css`.

---

## New Dependency

Add `pydantic` to the project dependencies in `pyproject.toml`:

```toml
dependencies = [
    # ... existing deps ...
    "pydantic>=2.0.0",
]
```

---

## Claude Code Skill

### Location

- Source: `templates/skill/ossip.md` (in the repo)
- Deployed: `ossip.dev/skill/ossip.md` (on the static site)

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

Users download the skill file and place it in their Claude Code skills directory. Documentation for this will be on the OSSIP README and/or site.

---

## Testing Strategy

### Unit Tests

- Pydantic model serialization: verify models produce expected JSON structure
- Schema export: verify `model_json_schema()` output is valid JSON Schema
- Data conversion: verify enriched dicts convert correctly to Pydantic models
- Edge cases: proposals with no votes, missing fields, `"not set"` values

### Integration Tests

- End-to-end JSON generation: run the output command on test data, verify file structure and contents
- Schema validation: validate generated JSON data files against the exported schemas
- Size sanity checks: verify summary files are within expected size ranges

### CI Validation

- Add a step to validate generated JSON against schemas as part of the build
- This catches data/schema drift before it reaches the live site

---

## Summary

| Component | What | Where |
|-----------|------|-------|
| Pydantic models | Data structures + validation + schema source | `ipper/common/models.py` |
| JSON renderer | Serialize models to static JSON files | `ipper/common/api_output.py` |
| Kafka integration | Convert KIP data → models → JSON | `ipper/kafka/output.py` (modified) |
| Flink integration | Convert FLIP data → models → JSON | `ipper/flink/output.py` (modified) |
| API index + schemas | Entry point + JSON Schema files | `ipper/common/api_output.py` |
| Build integration | `--api-dir` flag + `api finalize` command | `local_build.sh`, `publish.yaml`, CLI |
| Claude Code skill | Agent instructions for querying the API | `templates/skill/ossip.md` |
| New dependency | Pydantic | `pyproject.toml` |
