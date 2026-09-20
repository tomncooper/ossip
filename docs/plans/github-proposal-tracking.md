# Implementation Plan: GitHub-Based Proposal Tracking

**Status:** Implemented (2026-09-20)
**Date:** 2026-02-16
**Goal:** Add improvement proposal tracking for projects that manage proposals in
GitHub repositories (no mailing lists / Confluence wikis), producing tracking
pages and JSON API output consistent with the existing KIP (Kafka) and FLIP
(Flink) pages.

## Supported Projects

| Project      | Repository                    | Prefix | Proposal files        | Numbering scheme                 |
|--------------|-------------------------------|--------|-----------------------|----------------------------------|
| Strimzi      | `strimzi/proposals`           | SIP    | Repo root, `NNN-*.md` | Sequential (assigned on merge)    |
| StreamsHub   | `streamshub/proposals`        | SHIP   | Repo root, `NNN-*.md` | Sequential (assigned on merge)    |
| Kroxylicious | `kroxylicious/design`         | KDP    | `proposals/NNN-*.md`  | PR number (zero-padded, 3-digit) |

Local reference clones exist under `../redhat/` (for heuristic validation only;
the pipeline always fetches from GitHub).

## Design Decisions (agreed)

1. **Proposal IDs:** SIP / SHIP / KDP prefixes.
2. **Data access:** GitHub REST API via `requests` with `GITHUB_TOKEN` env var
   (optional locally, injected in CI).
3. **Proposal PR detection:** a PR is a *proposal PR* if it adds or modifies a
   file matching `NNN-*.md` in the project's proposal directory, excluding
   `000-template.md` and `README.md`. PRs that only modify already-merged
   proposal files are *amendments*: they bump activity on the original proposal
   but never change its status or create a new record.
4. **States:** merged → accepted; open → under discussion; closed-unmerged →
   rejected. Reopened PRs flip back to under discussion on the next update.
   Sequential-repo proposals under review/rejected carry **no number** (shown
   as `PR #N`); Kroxylicious proposals always carry their PR number. Numbering
   gaps are skipped. Tables are ordered by creation date (descending).
5. **Votes:** PR reviews map to votes — `APPROVED` → +1, `CHANGES_REQUESTED`
   → -1, `COMMENTED` → not counted. Voter = GitHub login, timestamp = review
   submitted_at.
6. **Detail pages:** metadata + votes only (no markdown rendering).
7. **Activity:** for open proposal PRs, last activity = max(PR `updated_at`,
   last push, last issue comment, last review), mapped to the existing
   blue/green/yellow/red/black thresholds (see `KIPStatus` / `calculate_status`
   in `ipper/kafka/output.py` — to be extracted into `common` for reuse).
8. **JSON API:** all three projects join the existing `api/v1` API.
9. **CLI:** subcommands `strimzi`, `streamshub`, `kroxylicious` following the
   kafka/flink pattern.
10. **Votes on rejected proposals:** frozen review votes are retained on
    closed-unmerged (rejected) proposal PRs, captured once at (or before)
    close time.
11. **Votes on merged proposals:** the approval history is retained on merged
    (accepted) proposal PRs, frozen at merge — the historical record of who
    approved the proposal.
12. **Token policy:** `init` / `refresh` require `GITHUB_TOKEN` (Strimzi init
    alone is ~500 requests vs the 60/hr unauthenticated limit); `update` works
    unauthenticated (~5–15 requests per project per run).

## API Budget & Caching Strategy

The `pr_index` inside each committed cache JSON is the incremental-update
engine: a per-PR `updated_at` watermark plus stored classification, file
lists, and `head_sha`. Merged-proposal ground truth comes from a single
tarball download per run.

**Initial population (`init` / `refresh`) — one-time, token required:**

| Cost item | Strimzi | StreamsHub | Kroxylicious |
|---|---|---|---|
| Tarball of `main` (merged proposal files + titles) | 1 | 1 | 1 |
| PR list, all states, paginated | ~4 | 1 | ~2 |
| Files per PR (classification input) | ~300 | ~10 | ~140 |
| Reviews for proposal PRs (frozen vote record) | ~160 | ~4 | ~35 |
| Comments for rejected PRs (close-time snapshot) | ~50 | 0 | ~20 |
| **Total** | **~500** | **~16** | **~200** |

- REST has no batch "files for N PRs" endpoint, so per-PR files calls dominate.
  GraphQL batching (50 PRs/query) would cut this ~30× but is deliberately
  excluded: a second API style to maintain, and auth is mandatory anyway.
- ETag conditional requests (`If-None-Match`; 304s are free) are deliberately
  excluded: watermark + `head_sha` gating makes them redundant state.
- Kroxylicious shortcut: a *merged* KDP PR needs no files call — it is a
  proposal iff `proposals/<PR#>-*.md` exists on main. Closed KDP PRs still
  need files (rejected proposal vs plumbing).
- Because caches are committed to the repo (like `kip_mentions.csv`),
  nobody else ever runs `init` — they get the cache from git and only run
  `update`, which fits inside the unauthenticated 60/hr limit.

**Periodic update (daily CI) — typically ~5–15 requests per project:**

1. Tarball re-download (1 req) — diff filenames against cache to detect new
   merges; the PR list identifies which PR merged each new file.
2. PR list sorted by `updated` desc (1–2 req) — the change feed. Walk pages
   only until every remaining entry is at or below the watermark.
3. Per-PR work is gated by what changed (rules in Phase 2, Step 2.5).

## Architecture

```
ipper/
├── common/
│   ├── github.py          # NEW - GitHub REST client (auth, pagination, rate limits)
│   ├── github_config.py   # NEW - per-project config dataclass + SIP/SHIP/KDP instances
│   ├── github_models.py   # NEW - GithubProposalDetail, PR index models, cache models
│   ├── github_process.py  # NEW - tarball parsing, PR classification, record building,
│   │                      #        incremental update, activity & vote extraction
│   ├── github_output.py   # NEW - rendering (index + detail pages), JSON API emission
│   └── models.py          # MODIFIED - id/pr_number optional, shared model tweaks
├── strimzi/
│   └── main.py            # NEW - thin CLI wrapper (SIP config)
├── streamshub/
│   └── main.py            # NEW - thin CLI wrapper (SHIP config)
├── kroxylicious/
│   └── main.py            # NEW - thin CLI wrapper (KDP config)
└── main.py                # MODIFIED - register the three new subparsers

templates/
├── github-index.html.jinja       # NEW - shared index template (parameterised)
├── github-more-info.html.jinja   # NEW - shared detail template
└── index.html                    # MODIFIED - link the three new projects

cache/
├── sip_proposals_cache.json      # NEW - committed, single source of truth
├── ship_proposals_cache.json     # NEW
└── kdp_proposals_cache.json      # NEW

tests/
├── common/test_github.py         # NEW - client, config, classification, records
├── common/test_github_output.py  # NEW - rendering, API output
├── strimzi/test_main.py          # NEW - CLI wiring
├── streamshub/test_main.py       # NEW
└── kroxylicious/test_main.py     # NEW
```

The three per-project modules are thin: they instantiate the shared config and
call a shared parser/command factory (in `github_process.py` / a shared
`setup_github_parser`), so all logic lives in `common` and differences are
purely configuration.

## Detailed Steps

### Phase 1 — Shared GitHub client and validation scaffolding

**Step 1.1: `ipper/common/github.py` — REST client**

- `GithubClient` class wrapping `requests.Session`:
  - Base URL `https://api.github.com`; sets `Authorization: Bearer` header when
    `GITHUB_TOKEN` env var is present. **Required for `init` / `refresh`
    (Strimzi needs ~500 requests); optional for `update`.** Raise a clear
    error advising token setup when the unauthenticated budget is blown.
  - `get(path, params)` with retry-once on transient errors and a hard error
    (with remaining-quota info) when `X-RateLimit-Remaining` hits 0.
  - `paginate(path, params)` generator following `Link` headers
    (`per_page=100`).
  - Methods:
    - `download_tarball(ref="main") -> bytes` (`/repos/{o}/{r}/tarball/{ref}`)
    - `list_pulls(state, sort="updated", direction="desc")` — paginated;
      response entries carry `updated_at`, `state`, and `head.sha`, which
      drive the incremental-update gating in Step 2.5
    - `get_pull_files(pr_number)` — paginated
    - `get_pull_reviews(pr_number)` — paginated
    - `get_issue_comments(pr_number)` — paginated
    - `get_pull(pr_number)`
- Unit tests with mocked `requests` responses (pagination, token header,
  rate-limit exhaustion).

**Step 1.2: `ipper/common/github_config.py` — project configuration**

```python
@dataclass(frozen=True)
class GithubProjectConfig:
    key: str                      # "strimzi" | "streamshub" | "kroxylicious"
    name: str                     # display name
    owner: str
    repo: str
    prefix: str                   # "SIP" | "SHIP" | "KDP"
    proposal_dir: str             # "" for root, "proposals" for Kroxylicious
    numbering: str                # "sequential" | "pr_number"
    proposal_pattern: re.Pattern  # ^(\d{3})-.+\.md$
    excluded_files: frozenset[str]  # {"000-template.md", "README.md"}

STRIMZI_CONFIG = GithubProjectConfig(...)
STREAMSHUB_CONFIG = GithubProjectConfig(...)
KROXYLICIOUS_CONFIG = GithubProjectConfig(...)
```

**Step 1.3: Heuristic validation pass (throwaway, not committed)**

Before locking in classification, run the client against the three real repos
and compare results with the local clones under `../redhat/`:
- Confirm every merged `NNN-*.md` file is captured by the tarball parse.
- Sample open/closed PRs and check the classification (proposal vs plumbing vs
  amendment) against their file lists, especially:
  - Kroxylicious PRs that add `proposals/000-<name>.md` then rename to the PR
    number within the same PR.
  - Strimzi PRs touching only `README.md` / CI / template (plumbing).
  - Any PR modifying an existing merged proposal file (amendment).
Adjust config/heuristics based on findings, then proceed.

### Phase 2 — Data processing

**Step 2.1: Tarball parsing (merged proposals)**

- Extract the tarball in memory; for each file matching `proposal_pattern`
  (in `proposal_dir`, not in `excluded_files`):
  - Number from the filename (e.g. `157-add-support-to-ssl-mqtt-bridge.md` → 157).
  - Title from the first `# ` heading; for Kroxylicious strip the leading
    `NNN - ` prefix (their convention is `# 124 - Title`).
- Produce a `MergedProposal` record: number, title, file path, blob URL
  (`https://github.com/{owner}/{repo}/blob/main/{path}`).

**Step 2.2: PR classification**

For each PR (from `list_pulls(state="all")` + `get_pull_files`):
- **New proposal PR:** the files added include ≥ 1 match of `proposal_pattern`
  that is not in `excluded_files` (added files only, so the Kroxylicious
  `000-` placeholder and same-PR rename both count).
- **Amendment PR:** no added proposal files, but ≥ 1 *modified* file that is a
  currently-merged proposal file → attach to that proposal as an amendment
  (bump `last_modified_on`, record PR number + URL + date).
- **Plumbing PR:** neither of the above → ignored (not stored beyond the PR
  index to avoid re-classification on every update).

**Step 2.3: Proposal record building**

- **Merged (accepted):**
  - `id` = file number; `state` = "accepted"
  - `created_by` / `authors` = PR author login
  - `created_on` = PR `created_at` (date part)
  - `merged_on` = PR `merged_at`
  - `web_url` = blob URL; `pr_url` = PR URL
  - `last_modified_on` = max(merge date, any amendment PR dates)
  - Votes: reviews captured at merge time are frozen and kept (historical
    record of who approved)
  - `activity_status` = None
- **Open (under discussion):**
  - `id` = None (sequential repos) or PR number (Kroxylicious)
  - `pr_number` = PR number; display as `PR #N` when `id` is None
  - votes from reviews (mapping in Design Decisions §5)
  - `last_activity` = max(`updated_at`, last push, last issue comment,
    last review); `activity_status` via the shared threshold logic
- **Closed-unmerged (rejected):**
  - Same identity rules as open; state "rejected"
  - `activity_status` = None; votes/activity frozen at close time

**Step 2.4: Extract shared activity thresholds**

Move `KIPStatus` / `calculate_status` from `ipper/kafka/output.py` into
`ipper/common/utils.py` (generalised names, e.g. `ActivityStatus`,
`calculate_activity_status`), keeping a thin re-export in `kafka/output.py` so
existing tests/imports keep working. GitHub processing reuses it.

**Step 2.5: Cache format and incremental update**

Cache file per project (`cache/{sip,ship,kdp}_proposals_cache.json`):

```json
{
  "last_updated": "2026-02-16T09:30:00Z",
  "proposals": { "<key>": { "...proposal record...": "" } },
  "pr_index": {
    "<pr_number>": {
      "state": "open|closed|merged",
      "classification": "proposal|amendment|plumbing|unknown",
      "proposal_key": "",
      "files": [],
      "updated_at": "",
      "head_sha": "",
      "frozen": true,
      "reviews_snapshot": [],
      "comments_snapshot": []
    }
  }
}
```

- Proposal record key: `"<number>"` for merged; `"pr-<number>"` for
  non-merged (avoids key collisions in sequential repos where PR numbers and
  proposal numbers overlap).
- `init` / `refresh`: full fetch — tarball + all PRs (state=all) + files for
  every PR + reviews/comments for proposal PRs; build cache from scratch.
  Requires `GITHUB_TOKEN` (see API Budget & Caching Strategy).
- `update` (incremental; precise gating rules):
  1. Re-download tarball (single request; cheap) and reconcile merged
     proposals: new merges move records from `pr-<n>` to numbered, pull
     author/created/merged metadata from the PR list, freeze the final
     review snapshot as the proposal's approval history.
  2. Walk `list_pulls(state="all", sort="updated", direction="desc")` until
     reaching PRs whose `updated_at` ≤ the cached watermark and whose state
     is unchanged — stop there (everything older is unchanged). Typically one
     page.
  3. Gate per-PR work by what changed:
     - **New PR** (not in `pr_index`): fetch files (1 req), classify.
     - **Known open PR with `updated_at` bump and `head.sha` change**:
       re-fetch files + reviews + comments (≤3 req). A label-only bump
       (`updated_at` moved but `head.sha` is unchanged and no reviews/comments
       are implied) triggers no file re-fetch.
     - **Known closed/merged PR with `updated_at` bump**: update
       state/metadata from the list response only — 0 extra requests.
     - **PR transitioning open → closed/merged**: fetch reviews + comments one
       final time (2 req) to capture the frozen vote record, then freeze.
     - **Unchanged PRs**: nothing, ever.
  4. Reopened PRs: `rejected` → `under discussion` automatically (state comes
     from the list response); unfreeze and resume activity/vote tracking.
  5. For open proposal PRs whose `updated_at` moved: refresh reviews +
     comments to update votes and `last_activity` / `activity_status` — a new
     review or comment always bumps `updated_at`, so votes are never missed.
- Deduplicate and write atomically (write temp file, rename).

**Step 2.6: `ipper/common/github_models.py`**

- `GithubProposalDetail(ProposalDetail)` with `pr_number: int | None`,
  `merged_on: str | None`, `pr_url: str | None`, `amendments: list[Amendment]`.
- In `common/models.py`: make `ProposalDetail.id`/`ProposalSummary.id`
  `int | None` and add optional `pr_number: int | None = None` (Kroxylicious
  non-merged proposals get `id` = PR number — collision-free because merged
  KDP numbers *are* merged PR numbers; sequential-repo non-merged proposals
  have `id` = None).
- Update `write_schemas` / schema generation in `common/api_output.py` for the
  new optionality.

### Phase 3 — CLI

**Step 3.1: Shared command factory**

In a new module (e.g. `ipper/common/github_cli.py`), a
`setup_github_project_parser(subparsers, config)` that registers:

```
ipper {strimzi|streamshub|kroxylicious} init
ipper {strimzi|streamshub|kroxylicious} update
ipper {strimzi|streamshub|kroxylicious} refresh
ipper {strimzi|streamshub|kroxylicious} output <cache_file> <index_html> <detail_dir> --api-dir <dir>
```

Semantics mirror kafka/flink: `init` = full first fetch; `update` =
incremental; `refresh` = full reprocess. No wiki/mail/keys subcommands needed.

**Step 3.2: Per-project wrappers**

`ipper/strimzi/main.py`, `ipper/streamshub/main.py`,
`ipper/kroxylicious/main.py`: each exports `setup_<project>_parser()` that
calls the factory with its config. Register all three in `ipper/main.py`
alongside kafka/flink.

### Phase 4 — Output

**Step 4.1: Templates**

- `templates/github-index.html.jinja`: clone of `flink-index.html.jinja`,
  parameterised by project name, prefix, and proposal list. Columns:
  `#` (number or `PR #N`), Title, State, Authors, Created, Votes (+1/0/-1),
  Activity indicator (open proposals only), Info link. **Rows sorted by
  `created_on` descending.** Keep the existing client-side filter controls
  (state/author filters) adapted as needed.
- `templates/github-more-info.html.jinja`: clone of `flip-more-info.html.jinja`
  showing metadata (state, authors, created/merged dates, PR link, blob link,
  amendments, votes with voter names + timestamps).
- Status indicators: accepted → ✅; rejected → ❌; under discussion →
  activity colour dot (consistent with KIP pages).

**Step 4.2: `ipper/common/github_output.py`**

- `render_index_page(config, cache, out_path)`,
  `render_detail_pages(config, cache, detail_dir)`,
  `generate_github_json_api(config, cache, api_dir)` reusing
  `common/api_output.py` helpers (`write_proposal_details`,
  `write_project_summary`).
- Detail page filenames: `{PREFIX}-{number}.html` for numbered proposals,
  `{PREFIX}-PR-{pr_number}.html` for unnumbered.

**Step 4.3: Site integration**

- Update `templates/index.html` with cards/links for Strimzi, StreamsHub,
  Kroxylicious.
- Register the three projects in the `ApiIndex` (keys `strimzi`, `streamshub`,
  `kroxylicious`; proposal types `SIP`, `SHIP`, `KDP`) —
  `generate_api_index` already scans `api/v1/*/`, verify it picks them up or
  extend its project registry.

### Phase 5 — CI

**Step 5.1: `.github/workflows/publish.yaml`**

Add after the flink steps:

```yaml
- name: Update Strimzi proposal data
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: uv run python ipper/main.py strimzi update

# ... same for streamshub, kroxylicious ...

- name: Build the Strimzi site
  id: strimzi-build
  continue-on-error: true
  run: uv run python ipper/main.py strimzi output cache/sip_proposals_cache.json site_files/strimzi.html site_files/sips --api-dir site_files/api/v1/strimzi

# ... same for streamshub (ships) and kroxylicious (kdps) ...
```

- Extend the "Check build results" step to warn per-project and only fail if
  *all* builds fail (consistent with existing behaviour).
- The existing "Commit updated cache files" step already covers the new cache
  files (`git add cache/`).

### Phase 6 — Tests, docs, quality

**Step 6.1: Tests** (pytest + pytest-mock, following existing conventions)

- `tests/common/test_github.py`:
  - Client: pagination, token header, rate-limit exhaustion error.
  - Config: patterns match/exclude correctly per project (template, README,
    non-markdown, wrong directory).
  - Tarball parsing: number/title extraction, Kroxylicious title prefix
    stripping, gap skipping.
  - Classification: new proposal (incl. `000-` placeholder and same-PR
    rename), plumbing, amendment; PR that adds a proposal *and* modifies
    README still counts as a proposal PR.
  - Lifecycle: rejected → reopened → under discussion; sequential numbering
    (no number until merge, number assigned on merge); KDP numbering
    (PR number at all stages); frozen votes on close/merge.
  - Votes: `APPROVED`/`CHANGES_REQUESTED`/`COMMENTED` mapping, voter + ts.
  - Incremental update: stops paging at the watermark boundary (unchanged
    PRs never re-fetched); `head_sha` gating (label-only `updated_at` bump
    triggers no file re-fetch, real push does); close transition captures the
    final review/comment snapshot and freezes votes; reopen unfreezes and
    resumes tracking; new-merge reconciliation moves a record `pr-<n>` →
    numbered with frozen approval history.
- `tests/common/test_github_output.py`: table ordering by created_on, `PR #N`
  rendering, detail page naming, JSON API serialization with `id: null`.
- `tests/{strimzi,streamshub,kroxylicious}/test_main.py`: CLI wiring,
  command dispatch.
- Update `tests/common/test_models.py` and API schema tests for optional
  `id` / new fields.

**Step 6.2: Documentation**

- Update `AGENTS.md`: architecture (new modules, caches, configs), CLI
  commands, CI changes, GitHub data-source section, design decisions.
- Update `README.md` if it lists supported projects.

**Step 6.3: Quality gates**

- `uv run ruff check .`
- `uv run pytest` (full suite; expect 84 existing + new tests to pass)
- Local end-to-end smoke test:
  `uv run python ipper/main.py strimzi init` → `strimzi output ...`, inspect
  generated HTML; repeat for the other two; verify rate limits are respected
  with and without `GITHUB_TOKEN`.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Classification heuristics wrong for edge-case PRs | Phase 1.3 validation pass against real repos before building on top |
| Rate limits (60 req/hr unauthenticated) | Token support; single-tarball merged fetch; incremental PR updates; per-PR file fetches only for unclassified/changed PRs |
| PR number / proposal number collisions (sequential repos) | Distinct cache keys (`pr-<n>`) and detail filenames (`SIP-PR-123.html`); `id` = None until merged |
| Very large PR counts on `init` (Strimzi) | Paginated fetch with progress logging; one-time cost; token raises ceiling to 5000/hr |
| `updated_at` churn (label-only bumps) causing unnecessary open-PR re-fetches | Compare `head.sha` from the list response before re-fetching files | 
| Stale frozen data for closed PRs | Frozen by design; a `refresh` re-fetches everything |

## Out of Scope (future considerations)

- Rendering proposal markdown content on detail pages
- GitHub Discussions as a discussion source
- Issues-based proposal processes
- Commit co-author enrichment for `authors`
