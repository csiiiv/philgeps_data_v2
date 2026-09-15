# Identifiers and release construction

## Identifier namespaces

Internal identifiers use type-specific prefixes so they are unambiguous across
tables:

- `pgcp_`: contracting process
- `pgrl_`: observed release/state
- `pgti_`: tender item
- `pgaw_`: award
- `pgct_`: contract
- `pgpa_`: party mention

The suffix is a lowercase SHA-256 digest over a versioned canonical identity
payload. Hash inputs, null representation, Unicode normalization, decimal
format, timestamp format, and array ordering must be documented and tested.

## Contracting-process identity

The preferred candidate is a valid PhilGEPS bid reference, but it is not
accepted blindly. The complete grain profile established:

- 10,293,935 distinct non-null values across 17,528,727 observations;
- `0` is a placeholder in 405,345 rows and cannot identify a process;
- one additional row has no bid reference;
- only two valid-looking bid references have multiple exact procuring-entity
  labels, affecting four rows; manual review shows abbreviated variants of the
  same agency with matching solicitation numbers and titles; and
- solicitation numbers are widely reused and cannot replace bid references.

The process-key rule for the ID prototype is:

1. Use `bid_reference_no` when it is non-null and not an obvious placeholder.
2. Keep the two observed entity-label variants under their shared bid reference
   and flag the conflicting organization labels. Do not split a process on an
   exact-name difference alone.
3. For missing or placeholder references, use an inferred composite of
   procuring entity, solicitation number when present, notice title, and bid
   publication date when the required entity/title/date components exist.
4. Otherwise use the immutable source breadcrumb as a row-level fallback.

The fallback composite applies to 252,692 observations and yields 206,640
candidate processes. The remaining 152,654 observations use row-level
fallbacks. Both kinds are explicitly flagged and must not be merged later
without a recorded alias operation.

See [Processes and actual examples](09_processes_and_examples.md) for the rows
behind these decisions.

## OCIDs

OCDS requires a registered OCID prefix. Until one is obtained, `process_id` is
authoritative internally and `ocid` remains null. Values that merely resemble
an OCID must not be published.

After registration:

```text
ocid = <registered-prefix>-<stable-publisher-process-identifier>
```

Official guidance:
https://standard.open-contracting.org/latest/en/schema/identifiers/

## Child identifiers

- Tender ID: a process-local deterministic ID. Preserve `solicitation_no` as a
  source identifier but do not rely on it for uniqueness.
- Item ID: line-item number when unique within the process; otherwise a hash of
  the item identity fields plus a deterministic collision ordinal.
- Award ID: process-scoped award reference when available; otherwise a stable
  process-scoped hash. Award references are reused across processes.
- Contract ID: award-scoped contract number when available; otherwise a stable
  award-scoped hash. Contract numbers are missing from 2,733,103 of 4,788,907
  contract-evidence rows and are heavily reused across processes.
- Party ID: a release-scoped mention identifier derived from the best available
  name and organization attributes. It is not cross-process entity resolution.

OCDS award and contract identifiers need only be unique and stable within their
OCID, but the Parquet `record_id` form is globally prefixed for easier joins.

The profile found 3,514 process/line-number groups with changed item content,
so item content is release state rather than identity. It also found 74,870
process/contract-number groups associated with more than one award reference,
which is why contract identity is award-scoped.

## From rows to releases

### Grouping

All rows for a process observation are grouped before hashing. Tender scalar
fields are compared, and items, awards, contracts, suppliers, and parties are
assembled as arrays.

### Canonicalization

The release content hash includes all mapped publishable content and local
fields that affect the observed state. It excludes:

- source filenames and URLs;
- ingestion timestamps;
- preferred-source markers;
- quality flags derived solely from the same content;
- array input order.

Arrays are sorted by their stable child identifiers. Timestamps and decimals
use one canonical string representation before hashing.

### Repeated and changed observations

- Same process identity + same content hash: one release, multiple source rows.
- Same process identity + different content hash: separate immutable releases.
- Different candidate process identities: never merge solely because titles or
  organization names match.

This follows the OCDS guidance for generating release identifiers from content
hashes when a source lacks a reliable last-modified timestamp:

https://standard.open-contracting.org/latest/en/guidance/build/easy_releases/

## Release date

Release `date` is required in OCDS, but PhilGEPS exports do not expose a general
last-modified timestamp. The initial precedence is:

1. award publication timestamp for a newly observed award state;
2. bid publication timestamp for a tender state;
3. award decision date when publication time is absent;
4. earliest source-export observation date as an explicitly inferred fallback.

Every value stores `release_date_basis` and confidence. A source filename date
must never silently override contradictory record dates.

## Release tags

Tags describe the sections populated and the observed change. Initial releases
may contain `tender`, `award`, and `contract` together. Later changed states use
update tags only when ordering and prior-state evidence are sufficient.
Amendment, cancellation, and termination tags are never inferred from a generic
status change without a documented mapping rule.
