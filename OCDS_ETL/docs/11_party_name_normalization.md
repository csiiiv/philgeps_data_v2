# Party-name normalization

## Outcome

Party-name normalization is a separate, versioned layer over the lossless
`parties.parquet` output. It supplies retrieval and candidate-matching keys; it
does not overwrite source names or assert that matching keys identify the same
legal entity.

The current rule is `party-name-v1`, defined in
`config/party_name_normalization.json`. Its compact output is
`outputs/parquet/party_name_forms.parquet`, with one row per distinct observed
name rather than one row per party mention.

## Full-data profile

The profile covers all 14,181,024 party mentions:

| Measure | Count |
|---|---:|
| Distinct observed names | 177,189 |
| Distinct conservative keys | 176,727 |
| Distinct punctuation-folded keys | 174,778 |
| Distinct terminal-suffix keys | 174,646 |
| Punctuation-only candidate groups | 1,838 |
| Legal-suffix equivalence candidate groups | 132 |
| Mentions in all candidate groups | 399,154 |

The complete reproducible results and largest candidate groups are in
`artifacts/party_name_profile.md` and `artifacts/party_name_profile.json`.

## Examples from the data

| Candidate key | Observed source spellings | Interpretation |
|---|---|---|
| `emcor inc` | `EMCOR INC`; `EMCOR INC.`; `EMCOR, INC`; `EMCOR, INC.`; `EMCOR, INCORPORATED` | Strong lexical alias candidate; still not a legal-identity assertion. |
| `medilines distributors inc` | `MEDILINES DISTRIBUTORS INCORPORATED`; `MEDILINES DISTRIBUTORS, INC.` | Terminal legal-form equivalence. |
| `superior motor corp` | `SUPERIOR MOTOR CORP`; `SUPERIOR MOTOR CORP.`; `SUPERIOR MOTOR CORPORATION` | Terminal legal-form equivalence. |
| `mhr health care co` | `MHR HEALTH CARE COMPANY`; `MHR HEALTH CARE, CO.` | Terminal legal-form equivalence. |
| `university of the philippines los ba os` | `UNIVERSITY OF THE PHILIPPINES - LOS BAÃ‘OS`; `UNIVERSITY OF THE PHILIPPINES-LOS BAÃ‘OS` | Punctuation candidate affected by source encoding damage; do not use as a display value. |

## Rule stages

1. Preserve `parties.name` unchanged.
2. Lowercase only for key generation.
3. Fold non-ASCII-alphanumeric runs to spaces, then trim and collapse spaces.
4. On a second key only, canonicalize a terminal `incorporated`,
   `corporation`, `company`, or `limited` to `inc`, `corp`, `co`, or `ltd`.
5. Attach counts that show whether a key has alternate source spellings or
   legal-suffix forms.

This produces two levels of evidence: `punctuation_name_key` for formatting
variation and `legal_suffix_name_key` for the extra legal-form equivalence.

## What this does not resolve

Equal keys are not automatically merged. Canonical party clustering needs
additional positive evidence such as an official identifier or a compatible
address, and must reject conflicting identifiers, locations, or organizational
units. Fuzzy spelling, encoding repair, abbreviations other than terminal legal
forms, and joint-venture parsing remain separate decisions.

The visible `BAÃ‘OS` example is deliberately preserved. Any future encoding
repair must retain the observed value, record the repair method, and remain
traceable through the party record to `record_sources.parquet`.

## Rebuild

```powershell
python OCDS_ETL\scripts\profile_party_names.py
python OCDS_ETL\scripts\build_party_name_forms.py
```

The builder writes a staging Parquet, checks exact distinct-name coverage,
unique deterministic form IDs, and non-empty keys, then replaces the published
name-form file.

## Resolution evidence layer

`scripts/build_party_resolution_candidates.py` applies
`config/party_resolution.json` to the multi-spelling groups and publishes
`outputs/parquet/party_resolution_candidates.parquet`. The full build contains
399,154 party mentions in 1,962 groups and reconciles exactly to the party-name
profile.

| Evidence status | Groups | Party mentions |
|---|---:|---:|
| `corroborated_candidate` | 395 | 26,248 |
| `partial_context` | 1,211 | 331,890 |
| `divergent_location_context` | 132 | 14,859 |
| `name_only` | 224 | 26,157 |

Only 21 of the 395 corroborated groups depend on legal-suffix equivalence; the
other 374 are punctuation or case variants. Ten corroborated groups contain
multiple organization contexts and 36 contain multiple roles. These facts make
the candidates useful for review, but too weak for an unconditional canonical
merge.

The full examples and validation results are in
`artifacts/party_resolution_profile.md` and
`artifacts/party_resolution_profile.json`. Every candidate retains its
`release_id` and `party_id`, so its raw source rows remain resolvable through
`record_sources.parquet`.

## Provisional canonical promotion

Rule `party-promotion-v1` promotes only punctuation-or-case groups satisfying
all of the following:

- every observed name form has location evidence;
- the forms share exactly one normalized location;
- there is at most one non-empty organization context; and
- supplier and public-body role families are not mixed.

This admits 318 groups. Only the 7,993 party mentions that themselves carry the
corroborating location are written to `party_aliases.parquet`; 9,375 other
mentions in those groups remain unresolved. The 318 corresponding rows in
`canonical_parties.parquet` have `identity_status = 'provisional'`, null
official identifiers, and an explicit quality flag.

Rebuild and validate with:

```powershell
python OCDS_ETL\scripts\build_canonical_parties.py
```

The machine-readable result is
`artifacts/canonical_party_validation.json`. These analytical IDs must not be
published as registered organization identifiers.
