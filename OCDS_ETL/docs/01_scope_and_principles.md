# Scope and principles

## Goal

Produce a reproducible representation of historical PhilGEPS notices, items,
awards, contracts, and participating organizations that:

- follows OCDS semantics wherever the source supports them;
- is efficient to query as multiple static Parquet tables;
- can generate valid OCDS 1.1.5 JSON release and record packages;
- preserves all observed states and their source breadcrumbs;
- makes uncertainty and inferred mappings explicit.

## Non-goals for the first implementation

- Claiming legal identity resolution from organization names alone.
- Deleting duplicate or conflicting source observations.
- Inventing missing awards, contracts, dates, or organization identifiers.
- Treating a quarterly export as a PhilGEPS transaction log.
- Registering or fabricating an official OCID prefix.
- Normalizing geographic names before the PSGC mapping work is approved.

## Core decisions

### OCDS is the semantic contract

OCDS JSON is hierarchical. Arrays such as tender items, awards, contracts, and
parties create one-to-many relationships that should be separated in tabular
storage. The official serialization guidance recommends a multi-table form for
this case:

https://standard.open-contracting.org/latest/en/guidance/build/serialization/

### Parquet is the analytical representation

Each entity or relationship is stored as one Parquet file. Parquet tables use
snake_case names and explicit primary/foreign keys. The JSON exporter maps
these tables to OCDS paths and packages; it is the conformance boundary.

### Source observations are evidence, not releases

One PhilGEPS row combines tender-level fields, one line item, and possibly an
award, supplier, and contract. A row therefore cannot be treated as one OCDS
release. Rows must first be grouped into contracting-process states.

### No destructive deduplication

Identical observations may support one derived state, but each breadcrumb is
retained in `record_sources.parquet`. Conflicting observations become separate
states or quality issues until a deterministic reconciliation rule applies.

### Missing and uncertain mappings remain visible

Every mapping is classified as:

- `direct`: source meaning matches the OCDS field;
- `mapped`: an explicit codelist or deterministic conversion is required;
- `inferred`: usable only with a recorded basis and confidence;
- `local`: retained outside OCDS core or through an extension;
- `unresolved`: blocked pending profiling or a policy decision.

## Layer boundaries

1. **Cleaned observations** — typed PhilGEPS rows with immutable provenance.
2. **Observed OCDS states** — grouped, content-addressed process releases and
   child objects.
3. **Compiled analytics** — preferred/latest state per process, exposed as
   views or optional derived Parquets.
4. **Publication packages** — OCDS 1.1.5 JSON releases and records with package
   metadata.

The first three layers are internal analytical products. Only the fourth is
described as OCDS data after schema validation.
