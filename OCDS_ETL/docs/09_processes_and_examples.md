# Contracting processes and actual PhilGEPS examples

## Meaning of a process

A contracting process is the lifecycle container for one procurement. It can
include a tender or notice, tender items, awards, suppliers, contracts, and
multiple observations of those objects over time. It is not equivalent to one
PhilGEPS row or one source file.

```text
contracting process
|-- one or more observed releases/states
|-- zero or one tender per release
|   `-- zero or more tender items
|-- zero or more awards
|   `-- zero or more supplier references
|-- zero or more contracts
`-- participating parties
```

A PhilGEPS export is flat, so tender-level and organization-level values are
often repeated for every item or award. The ETL groups the rows into a process
before creating OCDS-aligned objects. Every contributing row remains linked
through `record_sources.parquet`.

The complete grain profile currently yields approximately 10,653,228 candidate
processes:

- 10,293,934 valid-looking, distinct bid references, excluding `0`;
- 206,640 inferred composite candidates for rows with an unusable bid
  reference but enough descriptive evidence; and
- 152,654 source-row fallback candidates.

This remains a candidate count until the deterministic ID prototype is built.

## How to read the examples

The examples below are actual values selected from
`DATA_NORMALIZATION/output/philgeps_cleaned.parquet`. Dates and numbers show the
cleaned typed representation; text remains source-derived. Spelling and
punctuation errors are retained intentionally.

Each callable breadcrumb uses:

```text
source_file_id:physical_source_row
```

Run `python OCDS_ETL/scripts/show_source_entry.py <breadcrumb>` to render all
non-null values from that observation as a Markdown table. The script resolves
the normalized filename, worksheet, checksum, and URL from
`RAW_DATA_DOWNLOADER/dataset/manifest.json`. Physical row numbers, rather than
a normalized table offset, are used so a user can inspect the original file.

## Process shapes

### Tender-only process

Bid reference `1000054`, from the Province of Benguet, has two item rows and no
award reference anywhere in the candidate process.

| Line | Item | Award reference | Physical row |
|---:|---|---|---:|
| 1 | Pick-up back cover | null | 88,866 |
| 2 | Engine | null | 88,867 |

Notice title: `Purchase of pick-up back cover/top cover (campershell)`.

Breadcrumbs:
`pgf_bd707e1e735efa8cc5955b6abb39b432f9507615274d66668b4266a89d642601:88866`
and
`pgf_bd707e1e735efa8cc5955b6abb39b432f9507615274d66668b4266a89d642601:88867`
([source file](https://docs.google.com/spreadsheets/d/1g1uD8YyxOnypDMcnklfJd1JF_YL0L3jN/edit?usp=sharing&ouid=100820037704850818637&rtpof=true&sd=true)).

This becomes one process, one tender, and two items. No award or contract is
invented. The absent later stages remain visible as process completeness
metrics, but do not make the analytical process invalid.

### Multi-item process

Bid reference `1000937` is a City of Tanauan procurement with five line items.
The first three source rows are:

| Line | Item | Description | Physical row |
|---:|---|---|---:|
| 1 | floor tiles | 16x16 | 89,525 |
| 2 | sand | white | 89,526 |
| 3 | cement | portland | 89,527 |

All five rows have the title
`purchase of construction materials ( Altura E/S)` and no award reference.

Breadcrumb range:
`pgf_bd707e1e735efa8cc5955b6abb39b432f9507615274d66668b4266a89d642601:89525`
through
`pgf_bd707e1e735efa8cc5955b6abb39b432f9507615274d66668b4266a89d642601:89529`
([source file](https://docs.google.com/spreadsheets/d/1g1uD8YyxOnypDMcnklfJd1JF_YL0L3jN/edit?usp=sharing&ouid=100820037704850818637&rtpof=true&sd=true)).

The repeated notice fields do not create five tenders. They create five child
items under one tender.

### Multi-award process

Bid reference `8651857` contains six distinct award references for six line
items. The first three are:

| Line | Award reference | Supplier | Physical row |
|---:|---|---|---:|
| 1 | 3654877 | DOUBLE 8 OFFICE AND SCHOOL SUPPLIES | 143,681 |
| 2 | 3654935 | DOUBLE 8 OFFICE AND SCHOOL SUPPLIES | 143,679 |
| 3 | 3655001 | DOUBLE 8 OFFICE AND SCHOOL SUPPLIES | 143,680 |

Notice title: `Provision of communication Load to DepEd Bayugan CityDivision
Personnel for the 2nd Quarter (April to June 2022.`

Breadcrumb range:
`pgf_e75661739ca491d4629e1c5af5dbbd925ff535df590d13beb83cbf3cbccd5284:143679`
through
`pgf_e75661739ca491d4629e1c5af5dbbd925ff535df590d13beb83cbf3cbccd5284:143681`
([source file](https://drive.google.com/file/d/1sWfECAwymlh7EWuxbk2lOTubxjS2uVnT/view)).

This is one process with multiple awards, not six duplicated processes. It
also demonstrates why an award ID is scoped to its process.

### Tender-award-contract process

Bid reference `1000218` has evidence for all three principal stages:

- procuring entity: `CITY GOVERNMENT OF LUCENA`;
- title: `Repair & Maintenance of Service Vehicle ( Avanza SHU-873) for the
  use of City Budget Office.`;
- award reference: `158940`;
- supplier: `TOYOTA BALINTAWAK, INC.`;
- contract number: `2009-0726`;
- contract amount: `14526.8500`;
- award date: `2009-10-02`;
- contract effectivity: `2009-10-06`; and
- contract end: `2009-10-15`.

Breadcrumb:
`pgf_bd707e1e735efa8cc5955b6abb39b432f9507615274d66668b4266a89d642601:313100`
([source file](https://docs.google.com/spreadsheets/d/1g1uD8YyxOnypDMcnklfJd1JF_YL0L3jN/edit?usp=sharing&ouid=100820037704850818637&rtpof=true&sd=true)).

This can populate tender, award, supplier, and contract objects, subject to the
field-mapping and OCDS publication gates.

### Re-observed process across files

Bid reference `11282818`, titled `Road Opening from Old Puro to Causeway
(Phase I to III)`, appears in five source files with the same publication date,
`2024-10-03`:

| Normalized source filename | Callable breadcrumb | Source |
|---|---|---|
| `2021-01--2021-03.csv` | `pgf_a757d1091f0813007bd072bc91bd84e17b22e92d893ee67f15b7787dc665c28a:97292` | [file](https://drive.google.com/file/d/1Y9fgX2SPMKnjH4ercqiX3XEhMPJQkKMo/view) |
| `2021-04--2021-06.csv` | `pgf_d0193c5ae5d8ad56542b931a3d2331d8eb3faa1d9f3926cf77b77d120d05563d:109800` | [file](https://drive.google.com/file/d/17mko2FthvdGLkNvWS1AfGUsbkF97uUKm/view) |
| `2021-07--2021-09.csv` | `pgf_eb9dd9e5d65e46089658416d7934ad398415fe9102d1aca08d2ebb11638ee66c:119489` | [file](https://drive.google.com/file/d/1GUp-pB4g8lvh47ydXgV1m0X3L2-H9qVK/view) |
| `2021-10--2021-12.csv` | `pgf_4e24ca80916a38a76954acfc8e8434f98fb44501f1b1ed02fa63d6f70997f9f9:142822` | [file](https://drive.google.com/file/d/1Uml_SqS7GevgmryonNs5RFiDKAPwQQgi/view) |
| `2024-10--2024-12.csv` | `pgf_2266e5f97fafc121828197ac5297d48f21053c219c7f42ea307e22f982007ce9:14266` | [file](https://drive.google.com/file/d/1y4-jcz_SmUiNd_oqyjtK9yWu1W1QCvHt/view) |

This is also a concrete data-quality warning: a filename-derived period does
not necessarily describe every record contained in that file. The ETL must
not turn these five breadcrumbs into five processes or use the filename period
as the release date without checking record-level dates.

### Conflicting item observations

Bid reference `3010464`, line item `1`, appears twice in adjacent rows with
different content:

| Physical row | Item name | Description | Item budget | UNSPSC |
|---:|---|---|---:|---|
| 27,545 | Consulting Services | Internet Banking System Upgrade Project | 48,000,000 | null |
| 27,546 | INTERNET BANKING SYSTEM | ONE LOT INTERNET BANKING SYSTEM UPGRADE PROJECT | 47,500,000 | 43000000 |

Both have quantity `1` and unit `Lot`.

Breadcrumbs:
`pgf_0a8fb819ac61b34e7d84bedfed1c153e8f3833e6ddfe004253a160688d567279:27545`
and
`pgf_0a8fb819ac61b34e7d84bedfed1c153e8f3833e6ddfe004253a160688d567279:27546`
([source file](https://docs.google.com/spreadsheets/d/1oysMwDyrLYB1aMHBHD-U6PT0tG7h7Iob/edit?gid=1484907208#gid=1484907208)).

This is evidence of conflicting item assertions, but not enough evidence to
declare which row is a correction. Both remain traceable. The release builder
must not silently choose the larger or later physical row.

### Contract number associated with multiple awards

Within bid reference `2270893`, contract number `BSU-PB 2013-25` occurs with
two award references:

| Award reference | Supplier | Contract amount | Physical row |
|---|---|---:|---:|
| 626428 | BAUAN STEEL CORPORATION | 101,544.3200 | 124,299 |
| 626429 | BAUAN STEEL CORPORATION | 144,170.0000 | 124,295 |

Breadcrumbs:
`pgf_6660b1a4698a3f3393215492c326b1fadc15b9e249df59504eaa5876f6f97e61:124295`
and
`pgf_6660b1a4698a3f3393215492c326b1fadc15b9e249df59504eaa5876f6f97e61:124299`
([source file](https://docs.google.com/spreadsheets/d/1FVZr5vHItTezu_T0-ANKUEEJDT8PD50s/edit?gid=1982102923#gid=1982102923)).

This does not prove either row is wrong. It proves that `contract_no` alone is
not a safe child key. The analytical identity must be scoped to the related
award, while both source assertions remain available.

## Process identity types

### Valid bid-reference identity

For ordinary rows, a non-null bid reference other than an obvious placeholder
is the leading process identifier. Bid reference `1000054` above is an example:
its two lines form one process.

The internal ID will hash a versioned identity payload such as:

```json
{
  "identity_version": 1,
  "basis": "bid_reference",
  "bid_reference_no": "1000054"
}
```

### Inferred content-composite identity

Bid reference `0` cannot identify a process. An actual candidate from the
Municipality of Paete has these shared values:

- solicitation: `13-0017`;
- title: `Furnishing and delivery of room accomodation and meals/snacks to be
  used for the ELA-CapDEV Seminar`;
- publication date: `2013-08-14`; and
- eight numbered items, including `VIP room` and `Private room`.

The first three items occupy physical rows 7,340-7,342.

Breadcrumb range:
`pgf_e1854d38dbf997dfd1950199ac169cc052b749e20bf12da2f3ee6a7c50dd4cb3:7340`
through
`pgf_e1854d38dbf997dfd1950199ac169cc052b749e20bf12da2f3ee6a7c50dd4cb3:7342`
([source file](https://docs.google.com/spreadsheets/d/1e8a7ZMJeczL5OBdTfpfMfvzQsQiUhtTr/edit?gid=1011441875#gid=1011441875)).

These rows can be grouped conservatively using the normalized entity,
solicitation when present, title, and publication date. The resulting process
must carry `source_identifier_basis = inferred_content_composite` and lower
identity confidence.

### Source-row fallback identity

Some `0` references lack a publication date, so the approved composite cannot
be constructed. One example is:

- entity: `DEPARTMENT OF ENVIRONMENT AND NATURAL RES. - PENRO, CAM. NOR`;
- solicitation and title: `ENGP-CSD-COFFEE-2018-019`;
- bid publication date: null;
- line item: `1`; and
- award reference: `1055793`.

Breadcrumb:
`pgf_0999f110da82603d3a68f3f3326fd5dc493bd43a913151516c1f19bb9769ec42:4`
([source file](https://docs.google.com/spreadsheets/d/1o8FSeS1jabAiWV81u-7-bt1G0vJODzRF/edit?usp=sharing&ouid=100820037704850818637&rtpof=true&sd=true)).

This row receives an identity derived from its immutable breadcrumb. It remains
available but is not merged with similarly titled rows unless a later,
documented alias rule provides stronger evidence.

### Entity-label conflict within one process

Bid reference `3933064` appears in two adjacent rows with the same solicitation
`EI-2016-055` and the same notice title, but two entity labels:

```text
DEPARTMENT OF PUBLIC WORKS AND HIGHWAYS - S. MINDORO ED
DEPARTMENT OF PUBLIC WORKS AND HIGHWAYS - SOUTHERN MINDORO E
```

Breadcrumbs:
`pgf_442b1ee3f2109e624cefbfd28909b743ac8d3bc3787dc83974f85f66be7976df:24343`
and
`pgf_442b1ee3f2109e624cefbfd28909b743ac8d3bc3787dc83974f85f66be7976df:24344`
([source file](https://docs.google.com/spreadsheets/d/14lcWT4Z2gf8ST2gTfiac6ZxclfPz8Dl2/edit?usp=sharing&ouid=100820037704850818637&rtpof=true&sd=true)).

The lookup script's complete field-by-field rendering of these two observations
is saved as [source entry example](../artifacts/source_entry_example.md).

The profile initially detects two exact organization keys. Manual inspection
shows that this is an agency-label variation, not good evidence of two
procurements. The shared bid reference therefore remains one process and the
entity values become conflicting source assertions. This is why exact
organization-name equality is not automatically part of the primary process
key.

## Incomplete and uncertain processes

A process can legitimately stop at the tender stage, or its later-stage data
can be missing from the source. Analytical construction therefore does not
require every tender to have an award or every award to have a contract.

The current corpus has no contract-evidence or supplier-evidence rows with a
missing award reference under the Phase 1 evidence definitions. This is an
observed result, not a permanent schema constraint. Future or differently
interpreted rows can still produce `missing` or `ambiguous` link statuses and
corresponding entries in `data_quality_issues.parquet`.

Only records selected for standards-valid OCDS JSON must satisfy the applicable
OCDS reference requirements. Analytical rows are retained even when they are
incomplete, conflicting, or ineligible for publication.
