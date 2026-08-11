---
name: ossip
description: Query Apache KIP/FLIP improvement proposal data from ossip.dev
---

# OSSIP — Open Source Software Improvement Proposals

OSSIP provides structured JSON access to Apache Kafka Improvement Proposals (KIPs) and Flink Improvement Proposals (FLIPs). Use this skill to fetch and analyze proposal metadata, vote details, activity history, and authorship information programmatically.

## Overview

OSSIP aggregates enriched data about improvement proposals from Apache's Kafka and Flink projects:

- **KIPs (Kafka Improvement Proposals)**: ~1,284 proposals with full vote history and discussion threads
- **FLIPs (Flink Improvement Proposals)**: ~570 proposals with release version tracking

All data is available as JSON via REST endpoints. Queries are client-side — fetch the appropriate endpoint and filter the results locally.

## Data Endpoints

### Discovery

- **Index**: `https://ossip.dev/api/v1/index.json`
  - Entry point listing available projects, proposal counts, and data freshness
  - Start here to discover what projects are available

### Kafka (KIPs)

- **Summary**: `https://ossip.dev/api/v1/kafka/kips.json`
  - All ~1,284 KIPs with compact metadata (~230KB)
  - Use for status lookups, filtering by state, and activity-based queries
  - Fields: id, title, state, created_by, created_on, vote_count, activity_status, web_url, detail_url

- **Detail**: `https://ossip.dev/api/v1/kafka/kips/{id}.json`
  - Individual KIP with full vote details (voter names and timestamps)
  - Use for vote analysis and comprehensive proposal context
  - Replaces summary with full vote_summary object

### Flink (FLIPs)

- **Summary**: `https://ossip.dev/api/v1/flink/flips.json`
  - All ~570 FLIPs with compact metadata (~100KB)
  - Use for status lookups, filtering, and activity queries
  - Fields: id, title, state, created_by, created_on, vote_count, activity_status, web_url, detail_url
  - Note: activity_status is null for FLIPs (not color-coded like KIPs)

- **Detail**: `https://ossip.dev/api/v1/flink/flips/{id}.json`
  - Individual FLIP with full vote details and Flink-specific metadata
  - Additional fields: release_version, release_component, jira_id, jira_link
  - Use for tracking releases and Jira linkage

### Schemas

- **Schema Directory**: `https://ossip.dev/api/v1/schemas/`
  - JSON Schema definitions for all response types
  - Use to understand data structure and validate responses

## Query Patterns

### 1. Status Lookup

Fetch a specific proposal to check its current state and discussion progress:

```
GET https://ossip.dev/api/v1/kafka/kips/{id}.json
```

Response includes:
- `state`: "accepted", "under discussion", "not accepted", "completed", "in progress", or "unknown"
- `activity_status`: Color indicator for KIPs ("blue" = new, "red" = stale, "black" = never discussed)
- `last_modified_on` and `last_modified_by`: Most recent change
- `discussion_thread` and `vote_thread`: Links to mailing list discussions

### 2. Activity Queries

Find proposals based on discussion state and recency:

1. Fetch the summary endpoint (kips.json or flips.json)
2. Filter by state (e.g., "under discussion")
3. Filter by activity_status to find:
   - **Recent activity**: blue (new), green (mentioned in last 4 weeks)
   - **Stale discussions**: yellow (12 weeks), red (1 year), black (never)

Example: Find active Kafka discussions:
```
GET https://ossip.dev/api/v1/kafka/kips.json
→ filter state = "under discussion" AND activity_status ∈ ["blue", "green"]
```

### 3. Vote Queries

Analyze voting patterns on specific proposals:

1. Fetch the detail endpoint for the proposal ID
2. Inspect the `votes` object containing voter names and timestamps:
   - `votes.plus_one`: Array of {name, timestamp} for +1 votes
   - `votes.zero`: Array of {name, timestamp} for neutral votes
   - `votes.minus_one`: Array of {name, timestamp} for -1 votes

Example: Find who voted against a KIP:
```
GET https://ossip.dev/api/v1/kafka/kips/123.json
→ votes.minus_one returns [{name: "...", timestamp: "..."}, ...]
```

**Note:** These are binding votes detected from mailing list archives. Vote counts in the summary represent the final tally at the time of the last data refresh.

### 4. Cross-Referencing

Search for proposals related to a topic by keyword:

1. Fetch the summary endpoint
2. Search the `title` field for relevant terms (case-insensitive)

Example: Find KIPs related to consumer group coordination:
```
GET https://ossip.dev/api/v1/kafka/kips.json
→ filter title contains "consumer" OR title contains "group"
```

### 5. Author-Based Queries

Find proposals by a specific author:

1. Fetch the summary endpoint
2. Filter by `created_by` field

Example: All FLIPs created by a user:
```
GET https://ossip.dev/api/v1/flink/flips.json
→ filter created_by = "alice"
```

## Response Structure

All responses are JSON objects or arrays conforming to the schemas at `ossip.dev/api/v1/schemas/`.

### Proposal Summary (from summary endpoints)

```json
{
  "id": 123,
  "title": "Proposal Title",
  "state": "under discussion",
  "created_by": "author name",
  "created_on": "2023-01-15",
  "vote_count": {
    "plus_one": 5,
    "zero": 2,
    "minus_one": 0
  },
  "activity_status": "blue",
  "detail_url": "https://ossip.dev/api/v1/kafka/kips/123.json",
  "web_url": "https://cwiki.apache.org/..."
}
```

### Proposal Detail (from detail endpoints)

```json
{
  "id": 123,
  "title": "Proposal Title",
  "state": "under discussion",
  "created_by": "author name",
  "created_on": "2023-01-15",
  "last_modified_on": "2024-03-20T14:30:00Z",
  "last_modified_by": "reviewer name",
  "discussion_thread": "https://mail-archives.apache.org/...",
  "vote_thread": "https://mail-archives.apache.org/...",
  "jira": "KAFKA-12345",
  "web_url": "https://cwiki.apache.org/...",
  "activity_status": "green",
  "votes": {
    "plus_one": [
      {"name": "alice", "timestamp": "2023-02-01T10:30:00Z"},
      {"name": "bob", "timestamp": "2023-02-02T09:15:00Z"}
    ],
    "zero": [],
    "minus_one": []
  }
}
```

## Response Guidelines

When presenting proposal information to users:

1. **Always link to the canonical source**: Include the `web_url` field (links to Apache's wiki) so users can verify data and read full context
2. **Disclose data freshness**: Note the `last_updated` timestamp from the summary endpoint — data is refreshed daily from mailing list archives
3. **Clarify vote meaning**: When reporting votes, explain that these are **binding votes detected from mailing lists** — the vote_count represents the final tally at the time of the last refresh
4. **Provide context links**: For visual browsing, you can link to the OSSIP detail page at `https://ossip.dev/` which displays the same data in a human-readable format
5. **Handle missing data**: Fields set to `null` indicate data was not found or is not applicable. Never substitute sentinel strings like "unknown" or "not set" — these are cleaned to `null` by the API

## Common Tasks

### Task: "Is KIP-123 approved?"

1. Fetch: `GET https://ossip.dev/api/v1/kafka/kips/123.json`
2. Check: `state` field
3. If state = "accepted" → approved; else → not approved or in progress

### Task: "Which proposals have stalled?"

1. Fetch: `GET https://ossip.dev/api/v1/kafka/kips.json`
2. Filter: `activity_status = "black"` (never discussed or not mentioned in >1 year)
3. Report: title, state, created_on, and link to web_url

### Task: "Who objected to KIP-456?"

1. Fetch: `GET https://ossip.dev/api/v1/kafka/kips/456.json`
2. Extract: `votes.minus_one` array
3. Report: voter names and vote timestamps

### Task: "Find FLIPs related to scheduling"

1. Fetch: `GET https://ossip.dev/api/v1/flink/flips.json`
2. Filter: `title` contains "schedul" (case-insensitive)
3. Report: matching titles, states, and web_url links

## Data Notes

- **Proposal IDs**: Positive integers. KIP and FLIP numbering is independent (both start from 1).
- **Dates**: Calendar dates (created_on) use `YYYY-MM-DD` format. Timestamps (last_modified_on, votes) use ISO 8601 with seconds and Z (UTC) timezone.
- **States**: One of "accepted", "under discussion", "not accepted", "completed", "in progress", "unknown"
- **Activity Status** (KIPs only):
  - `"blue"`: New, created in last 4 weeks
  - `"green"`: Mentioned in last 4 weeks
  - `"yellow"`: Mentioned in last 12 weeks
  - `"red"`: Mentioned in last 1 year
  - `"black"`: Never mentioned or last mentioned >1 year ago
  - `null`: Proposal is not in "under discussion" state
- **Null Values**: Fields with unavailable data are `null`, never empty strings or sentinel values
- **Flink-Specific Fields** (in FLIP detail responses):
  - `release_version`: Target Flink release version
  - `release_component`: Component area (e.g., "Runtime", "Connectors")
  - `jira_id`: Jira issue identifier if tracked
  - `jira_link`: Direct URL to Jira issue

## Error Handling

- **404**: Proposal ID does not exist. Check the summary endpoint to find valid IDs.
- **Timeout or unavailable**: The API may be temporarily unavailable during site maintenance. Retry after a few seconds.
- **Stale data**: If you notice incorrect information, check the `last_updated` timestamp — data may not have refreshed yet. Daily updates are performed; manual refresh requests can be submitted via the OSSIP GitHub project.
