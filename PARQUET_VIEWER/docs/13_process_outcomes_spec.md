# Process outcome taxonomy and rules (process-outcomes-v1)

Status: draft for the first implementation slice (docs/11 §1, §2).
Rule version constant: `process-outcomes-v1`.

## Inputs

The rule reads only evidence that already exists in the authoritative
Parquets; it never invents lifecycle stages:

- `releases` — `has_tender`, `has_award`, `has_contract` per release
- `tenders` — `source_status` (observed), `closing_date`, `value_amount`
- `awards` — `award_id`, `value_amount`, `status` (normalized)
- `contracts` — `contract_id`, `award_link_status`
- `data_quality_issues` — `issue_category = 'conflict'` rows tied to the
  release's records
- `compiled_processes` — the preferred release for one row per process

## Outcome taxonomy (closed set)

| outcome | meaning |
|---|---|
| `contracted` | Award(s) exist and at least one contract evidences them |
| `awarded` | Award(s) exist, no contract evidence |
| `partially_awarded` | Some tender line items have award-item links and some do not. Zero links is **not** partial: with no item evidence the linkage is unknown, so the process classifies by award/contract presence instead (guardrail 2 — award link missing ≠ not awarded) |
| `cancelled` | Tender source status is `Cancelled` (no award evidence wins ties) |
| `unsuccessful` | Tender source status is `Failed` |
| `closed_unknown` | Tender closed with no award, no failure, no cancellation evidence |
| `active` | Tender is `Active` or `Shortlisted` (still in flight) |
| `conflicting_evidence` | Contradictory signals (e.g. award + `Failed` status) — requires review |

`conflicting_evidence` never silently overrides: when both a conflict issue
and a definite signal exist, the definite signal wins and the conflict is
recorded in `outcome_basis` instead.

## Decision order (first match wins)

1. Tender status `Cancelled` **and** no awards → `cancelled`
2. Tender status `Failed` **and** no awards → `unsuccessful`
3. Award + `Failed`/`Cancelled` both present → `conflicting_evidence`
4. `conflict` issue category on the process → `conflicting_evidence`
5. Awards present with item evidence and a strict subset of items linked → `partially_awarded`
6. Awards present, contract linked → `contracted` (else `awarded`)
7. Tender status `Active`/`Shortlisted`/`Shortlisted` variants → `active`
8. Tender closed with no award → `closed_unknown`
9. No tender at all but awards exist → `awarded` (rare, source-driven)
10. Nothing observed → `closed_unknown`

Order notes: 5 before 6 so a partially awarded process is not flattened into
`contracted`; 5 applies only when `award_items` links exist for the release
(otherwise every process would look partial — 4.67M of 4.93M awards have item
links).

## Metadata (shared derivation-metadata shape)

Every emitted row carries the shared shape agreed in docs/11 Phase 1 step 0:

```json
{
  "origin": "derived",
  "rule": "process-outcomes-v1",
  "rule_version": "1",
  "source_fields": ["releases.has_award", "tenders.source_status", "..."],
  "basis": "preferred_release",
  "confidence": "observed",
  "source_count": 4
}
```

`confidence`: `observed` (direct evidence), `derived` (rule application),
`provisional` (fallbacks used). `basis` records which release/table the
decision read.

## Population and grain

- Grain: one row per `process_id` (11.25M rows).
- Counts aggregate at process grain; values are never summed into the funnel
  (doc 11 §2 rule: incomplete values must not remove a process).
- A process with zero releases anywhere still gets a row (`closed_unknown`)
  so the funnel denominators are complete.

## Tests (fixture matrix)

Each fixture asserts both `outcome` and `outcome_basis`:

1. tender + award + matched contract → `contracted`
2. tender + award, no contract → `awarded`
3. award only on item-linked subset → `partially_awarded`
4. `Cancelled` tender, no awards → `cancelled`
5. `Failed` tender, no awards → `unsuccessful`
6. award + `Failed` status → `conflicting_evidence`
7. closed tender, no award/fail/cancel → `closed_unknown`
8. `Active` tender → `active`

## Build manifest

The search index that carries the `outcomes` table also stores a versioned
build manifest in its `meta` table (key `build_manifest`), exposed at
`GET /api/index/manifest`:

- `manifest_version` — shape of the manifest itself (currently 1);
- `projection` — which disposable projection produced it (`search_index`);
- `schema_version` — the index schema version the build ran with;
- `rules` — rule name + version for every derived artifact inside
  (`process-outcomes-v1`, `process-facts-v1`, `relationship-status-v1`,
  `source-coverage-v1`);
- `sources` — per-input path/size/mtime fingerprints used for the build;
- `row_counts` — `procurements`, `process_facts`, `outcomes`, `filter_stats`,
  `source_periods`;
- `built_at` / `built_at_epoch_s`;
- `stale` / `index_state` — added by the endpoint (not stored): whether the
  on-disk index still matches current sources, and hit/building/miss state.

The manifest is diagnostics only. It never decides freshness — the stored
fingerprint comparison does that — so a missing or malformed manifest
degrades to a 404/`index_absent` response without affecting queries.
