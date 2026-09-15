# Cross-year supplier contract queries

## Objective

Support questions such as “show all contracts associated with this supplier
over the last ten years” while being explicit about supplier identity,
relationship completeness, date basis, and shared contract values.

## Reuse the normalized party layer

The viewer uses the existing ETL outputs:

- `party_name_forms.parquet` contains all 177,189 observed names with
  punctuation and terminal legal-suffix keys;
- `party_resolution_candidates.parquet` contains 399,154 mentions in
  multi-spelling candidate groups;
- `canonical_parties.parquet` contains 318 provisional analytical clusters;
  and
- `party_aliases.parquet` contains 7,993 location-supported provisional
  assignments.

These remain the only party-normalization and resolution rules. A viewer cache
must reuse their keys and IDs rather than inventing another normalizer.

## Identity scopes

A supplier query always declares one of these scopes:

1. `exact_spelling`: only the selected observed name.
2. `punctuation_normalized`: source names with the same punctuation key.
3. `legal_suffix_candidate`: names with the same legal-suffix key, clearly
   labeled unverified.
4. `provisional_canonical`: only location-supported aliases belonging to a
   provisional canonical party.
5. `manual_alias_selection`: an explicit set of observed names chosen by the
   reviewer.

The interface must state the selected scope and included spellings. It must not
say “all contracts of a supplier” without qualifying how supplier identity was
determined.

`provisional_canonical` has higher precision but low coverage. Broader lexical
scopes improve recall and increase the possibility of unrelated parties being
included. Manual alias selection is therefore an important validation mode.

## Authoritative relationship path

```text
party name form
    -> release-scoped party mention and supplier role
    -> award supplier assertion
    -> matched award
    -> matched contract
    -> release and contracting process
    -> record source breadcrumbs
```

Incomplete assertions are not discarded. The UI can switch between matched
contracts and unresolved/missing/ambiguous relationship evidence.

## Direct Parquet query pattern

```sql
WITH selected_forms AS (
  SELECT observed_name
  FROM read_parquet('outputs/parquet/party_name_forms.parquet')
  WHERE legal_suffix_name_key = 'emcor inc'
),
supplier_mentions AS (
  SELECT
    p.release_id,
    p.party_id,
    p.name AS observed_supplier_name
  FROM read_parquet('outputs/parquet/parties.parquet') p
  JOIN selected_forms f
    ON f.observed_name = p.name
  JOIN read_parquet('outputs/parquet/party_roles.parquet') pr
    USING (release_id, party_id)
  WHERE pr.role = 'supplier'
)
SELECT DISTINCT
  sm.observed_supplier_name,
  c.release_id,
  c.contract_id,
  c.source_contract_number,
  c.value_amount,
  c.value_currency,
  c.period_start,
  c.period_end,
  s.award_id,
  s.award_link_status,
  s.party_link_status
FROM supplier_mentions sm
JOIN read_parquet('outputs/parquet/award_suppliers.parquet') s
  USING (release_id, party_id)
JOIN read_parquet('outputs/parquet/contracts.parquet') c
  ON c.release_id = s.release_id
 AND c.award_id = s.award_id
WHERE s.award_link_status = 'matched'
  AND s.party_link_status = 'matched'
  AND c.award_link_status = 'matched'
  AND coalesce(c.period_start, c.notice_to_proceed_date) >= DATE '2016-01-01'
  AND coalesce(c.period_start, c.notice_to_proceed_date) < DATE '2026-01-01';
```

`DISTINCT` is important because `award_suppliers` stores source assertions and
multiple observations can support the same analytical relationship. In the
current data, a direct matched join produces 4,743,081 rows but only 3,217,676
distinct supplier-contract relationships. Some relationships have as many as
832 supporting assertions.

## Date scope

A ten-year filter must state its date basis. Available evidence includes
contract start, notice-to-proceed, award date, award publication, and release
date.

The convenience fallback can be:

```text
contract start
    -> notice to proceed
    -> award date
    -> release date
```

Every result exposes `date_basis`. Reviewers can instead require one strict
basis, such as award date only, to avoid mixing lifecycle meanings.

## Historical versus preferred state

The viewer offers two scopes:

- `preferred_state` joins through `compiled_processes.preferred_release_id` and
  represents the current analytical view of each process; and
- `all_observed_states` searches every release and may show the same logical
  contract in multiple observed states.

The result grain and duplicate policy must be visible. Historical observations
should not be silently collapsed into preferred state.

## Monetary interpretation

One award or contract can have multiple suppliers, and PhilGEPS may not provide
a value allocation among them. Assigning the full amount to every supplier
would overstate supplier revenue.

The viewer therefore reports:

- distinct contracts and awards;
- associated contract face value;
- supplier count for each award;
- whether an allocation is available; and
- a shared-value warning where allocation is unknown.

Aggregates use the label “associated contract value,” not “supplier revenue.”

## Optional performance projection

If direct joins are not interactive, build a disposable
`supplier_contract_facts` table in `.cache/viewer.duckdb`. Its grain is one
distinct `(release_id, award_id, contract_id, party_id)` relationship. It
contains `supporting_assertion_count` and only the search, filter, display, and
navigation fields:

- process, release, award, contract, party, and name-form IDs;
- observed name and existing normalized keys;
- nullable provisional canonical party ID and evidence status;
- relationship statuses;
- contract number, selected date, and date basis;
- award and contract values;
- tender title, procuring entity, method, and geography;
- supplier count and quality-issue counts; and
- record IDs used to fetch source breadcrumbs.

Assertion IDs remain reachable through a separate drill-through query rather
than multiplying the fact rows.

It does not contain a new party identity decision and is never authoritative.
It is rebuilt when source Parquet metadata, name rules, resolution rules, or
compilation rules change.

## Supplier page

The supplier page shows:

- selected identity scope and included spellings;
- candidate/provisional warnings;
- locations and role evidence;
- contracts and awards over time;
- procuring entities and procurement methods;
- awards without contracts;
- unresolved supplier and award links;
- associated values with shared-value warnings;
- source-file and date coverage; and
- quality issues and source breadcrumbs.

Useful breakdowns include year, procuring entity, method, location, source
spelling, and relationship status. Clicking any count opens the exact rows
behind it.
