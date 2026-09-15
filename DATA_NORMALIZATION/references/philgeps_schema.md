# PhilGEPS Schema Evolution Analysis

> **Current-dataset note (September 12, 2026):** This is a historical schema
> analysis and does not exactly match every file now present in
> `RAW_DATA_DOWNLOADER/dataset/`. In particular, the current files include a
> 43-column XLSX layout and four headerless 46-column CSVs. Use
> [`../docs/source_inventory.md`](../docs/source_inventory.md) and the generated
> source catalog for ingestion decisions. The current physical-schema check is
> recorded in [`../docs/schema_verification.md`](../docs/schema_verification.md).
> Retain this document as semantic and historical context.

**Analysis Date:** November 14, 2025  
**Purpose:** Comprehensive understanding of PhilGEPS data structure changes from 2000-2025

---

## Executive Summary

PhilGEPS data has evolved through **5 distinct schemas** over 25 years, reflecting the modernization of the Philippine government procurement system. This analysis examines actual raw source files to document the precise changes, column mappings, and migration implications.

### Quick Reference

| Schema | Period | Format | Columns | Key Change |
|--------|--------|--------|---------|------------|
| **Schema 1** | 2000-2015 | XLSX (row 3) | 40 | Original system, uses `UOM` |
| **Schema 2** | 2016-2020 | XLSX (row 3) | 40 | Renamed `UOM` → `Unit of Measurement` |
| **Schema 3** | 2021-2024 | CSV (row 0) | 43 | Added 3 fields: Created By, Contact Person, Bidder List |
| **Schema 4** | 2025 | CSV (row 0) | 46 | Added 12 location fields, removed 9 legacy fields |
| **Schema 5** | 2021-2024-V2 | CSV (row 0) | 46 | **Same as Schema 4** - Early PhilGEPS 2.0 implementation |

---

## Schema Evolution Timeline

### Schema 1: The Original (2000-2015)

**Files:** `2000-01 -- 2000-12.xlsx` through `2015-01 -- 2015-12.xlsx`  
**Location:** `RAW/raw/2000-2012/` and `RAW/raw/2013-2020/`  
**Format:** Excel (.xlsx) with headers starting at **row 3** (rows 0-2 are metadata/empty)  
**Columns:** 40

#### Key Characteristics

- **Column 1:** `Organization Name` (not "Procuring Entity")
- **Column 2:** `Reference ID` (not "Bid Reference No.")
- **Column 5:** `Publish Date` (not "Published Date")
- **Column 19:** `Item Desc` (abbreviated)
- **Column 21:** `UOM` (abbreviation for Unit of Measurement)
- **Column 31:** `Awardee Corporate Title` (not "Organization Name")
- **Column 37:** `Contract Efectivity Date` (typo remains throughout all schemas!)

#### Missing Features

- No procuring entity location data (Region, Province, City)
- No awardee location data
- No "Created By" tracking
- No bidder list information
- No organization type classification

---

### Schema 2: The Minor Update (2016-2020)

**Change Year:** 2016 (confirmed by checking column 21 in qa_samples)  
**Files:** `2016-01 -- 2016-03.xlsx` through `2020-10 -- 2020-12.xlsx`  
**Location:** `RAW/raw/2013-2020/`  
**Format:** Excel (.xlsx) with headers at row 3  
**Columns:** 40

#### The ONLY Change

**Column 21:** `UOM` → `Unit of Measurement`

Everything else remains identical to Schema 1. This was likely a data standardization effort to use the full term instead of an abbreviation.

#### Why It Matters

This seemingly minor change breaks direct CSV processing if you assume all 2000-2020 files are identical. Scripts must handle both variants:

```python
if col_name in ['UOM', 'Unit of Measurement']:
    unified_name = 'uom'
```

---

### Schema 3: The Modernization (2021-2024)

**Files:** `2021-01 -- 2021-12.csv` through `2024-01 -- 2024-12.csv`  
**Location:** `RAW/raw/2021-2025/`  
**Format:** CSV with headers at **row 0** (no metadata rows)  
**Columns:** 43

#### Major Changes from Schema 1/2

**Format Change:** XLSX → CSV (easier to process, more universally compatible)

**Column Renames:**
- `Organization Name` → `Procuring Entity`
- `Reference ID` → `Bid Reference No.`
- `Publish Date` → `Published Date`
- `Item Desc` → `Item Description`
- `Awardee Corporate Title` → `Awardee Organization Name`

**3 New Columns Added:**
1. **Column 26:** `Created By` - User who created the record in the system
2. **Column 42:** `Awardee Contact Person` - Contact information for awarded entity
3. **Column 43:** `List of Bidder's` - All entities that bid on the contract

#### Column Order Changes

The column order was **significantly restructured**. For example:
- Old position 11 (`Procurement Mode`) → New position 7
- Old position 23 (`PreBid Date`) → New position 15
- Award-related columns moved later in the sequence

This makes direct positional mapping impossible - you must map by column name.

---

### Schema 4: The Location Revolution (2025)

**Files:** `2025-01 -- 2025-03.csv`, `2025-04 -- 2025-06.csv`, `2025-07 -- 2025-09.csv`  
**Location:** `RAW/raw/2021-2025/`  
**Format:** CSV with headers at row 0  
**Columns:** 46

#### Major Changes from Schema 3

**12 New Location Columns:**

**Procuring Entity Location (Columns 2-7):**
1. `Region` - Geographic region of PE
2. `Province` - Province of PE
3. `City/Municipality` - City/municipality of PE
4. `Government Branch` - Executive, Legislative, Judicial
5. `PE Organization Type` - Specific org type
6. `PE Organization Type (Grouped)` - Grouped classification

**Awardee Location (Columns 41-46):**
1. `Country of Awardee` - Usually "Philippines"
2. `Region of Awardee` - Geographic region
3. `Province of Awardee` - Province
4. `City/Municipality of Awardee` - City/municipality
5. `Awardee Size` - Small/Medium/Large
6. `Awardee Joint Venture` - JV partners if applicable

**9 Legacy Columns Removed:**
1. `Solicitation No.` - Legacy field from old system
2. `Notice Type` - Redundant with Classification
3. `PreBid Date` - Less commonly used
4. `Created By` - Removed after 1 generation
5. `Award Type` - Simplified
6. `Reason for Award` - Simplified
7. `Contract No` - System-generated instead
8. `Awardee Contact Person` - Privacy concern?
9. `List of Bidder's` - Privacy concern?

**Status Field Improvements:**
- Old: `Notice Status` → New: `Bid Notice Status` (more descriptive)
- Old: `Award Status` → New: `Award Notice Status` (consistent naming)

**Other Renames:**
- `Procuring Entity` → `Procuring Entity (PE)` (added abbreviation)
- `Award No.` → `Award Reference No.` (more descriptive)
- Typo **still not fixed:** `Contract Efectivity Date` (should be "Effectivity")

---

### Schema 5: The Retroactive Export (2021-2024-V2)

**Files:** Quarterly CSV files for 2021-2024  
**Location:** `RAW/raw/2021-2025-V2/`  
**Format:** CSV with headers at row 0  
**Columns:** 46 (identical to Schema 4)

#### What Is This?

Schema 5 is **NOT a new schema** - it's historical 2021-2024 data **re-exported using the Schema 4 structure**.

**Evidence:**
1. Same 46 columns as Schema 4 (2025)
2. Same column names including `Procuring Entity (PE)`
3. Same location fields present
4. Same canonical status field names
5. **Different file:** Quarterly splits instead of yearly

#### Why Does This Exist?

Likely scenarios:
1. **Data Migration:** When PhilGEPS 2.0 launched, they migrated old data
2. **Location Enrichment:** Retroactively added location data to historical records
3. **Data Quality:** Re-processed data with better validation
4. **Quarterly Reporting:** Changed reporting frequency from yearly to quarterly

#### Data Quality Implications

**Schema 5 is SUPERIOR to Schema 3 for 2021-2024 data because:**
- ✅ Has location data (6 PE fields + 6 Awardee fields)
- ✅ Uses canonical status field names
- ✅ More consistent with 2025+ data structure
- ✅ Likely underwent additional data cleansing

**Schema 3 advantages:**
- ✅ Has `Created By` field (user tracking)
- ✅ Has `Awardee Contact Person` (contact info)
- ✅ Has `List of Bidder's` (competition info)
- ✅ Has legacy fields like `Solicitation No.`, `Contract No`

---


## 📊 Complete Semantic Grouping Table

This view groups related fields together across schemas, making it easier to see how specific data categories evolved. The 14 categories are:

1. Procuring Entity
2. Bid Identification
3. Bid Timeline
4. Budget & Funding
5. Procurement
6. Line Items
7. UNSPSC
8. Bid Status
9. Award ID
10. Award Timeline
11. Contract
12. Award Status
13. Awardee Information
14. Competition

| Field Name | Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025/V2 | Evolution Notes |
|-----------|-------------------------|----------------------|---------------------|-----------------|
| **🏛️ PROCURING ENTITY** | | | | |
| Entity name | `Organization Name` | `Procuring Entity` | `Procuring Entity (PE)` | Renamed 2021, clarified 2025 |
| Region | — | — | `Region` | **NEW 2025/V2** |
| Province | — | — | `Province` | **NEW 2025/V2** |
| City/Municipality | — | — | `City/Municipality` | **NEW 2025/V2** |
| Government branch | — | — | `Government Branch` | **NEW 2025/V2** |
| Organization type | — | — | `PE Organization Type` | **NEW 2025/V2** |
| Organization type (grouped) | — | — | `PE Organization Type (Grouped)` | **NEW 2025/V2** |
| **📋 BID IDENTIFICATION** | | | | |
| Reference number | `Reference ID` | `Bid Reference No.` | `Bid Reference No.` | Renamed 2021 |
| Solicitation number | `Solicitation No.` | `Solicitation No.` | **REMOVED** | Legacy field dropped 2025 |
| Notice title | `Notice Title` | `Notice Title` | `Notice Title` | Stable |
| Classification | `Classification` | `Classification` | `Classification` | Stable |
| Notice type | `Notice Type` | `Notice Type` | **REMOVED** | Redundant, dropped 2025 |
| Business category | `Business Category` | `Business Category` | `Business Category` | Stable |
| **📅 BID TIMELINE** | | | | |
| Published date | `Publish Date` | `Published Date` | `Published Date` | Renamed 2021 |
| Pre-bid date | `PreBid Date` | `PreBid Date` | **REMOVED** | Less common, dropped 2025 |
| Closing date | `Closing Date` | `Closing Date` | `Closing Date` | Stable |
| **💰 BUDGET & FUNDING** | | | | |
| Funding source | `Funding Source` | `Funding Source` | `Funding Source` | Stable |
| Funding instrument | `Funding Instrument` | `Funding Instrument` | `Funding Instrument` | Stable |
| Approved budget | `Approved Budget of the Contract` | `Approved Budget of the Contract` | `Approved Budget of the Contract` | Stable |
| Trade agreement | `Trade Agreement` | `Trade Agreement` | `Trade Agreement` | Stable |
| **🛒 PROCUREMENT** | | | | |
| Procurement mode | `Procurement Mode` | `Procurement Mode` | `Procurement Mode` | Stable |
| Area of delivery | `Area of Delivery` | `Area of Delivery` | `Area of Delivery` | Stable |
| Contract duration | `Contract Duration` | `Contract Duration` | `Contract Duration` | Stable |
| Calendar type | `Calendar Type` | `Calendar Type` | `Calendar Type` | Stable |
| **📦 LINE ITEMS** | | | | |
| Line item number | `Line Item No` | `Line Item No` | `Line Item No` | Stable |
| Item name | `Item Name` | `Item Name` | `Item Name` | Stable |
| Item description | `Item Desc` | `Item Description` | `Item Description` | Full word 2021 |
| Quantity | `Quantity` | `Quantity` | `Quantity` | Stable |
| Unit of measure | `UOM` (2000-2015)<br>`Unit of Measurement` (2016-2020) | `UOM` | `UOM` | **Changed 2016**, reverted 2021 |
| Item budget | `Item Budget` | `Item Budget` | `Item Budget` | Stable |
| **🏷️ UNSPSC** | | | | |
| UNSPSC code | `UNSPSC Code` | `UNSPSC Code` | `UNSPSC Code` | Stable |
| UNSPSC description | `UNSPSC Description` | `UNSPSC Description` | `UNSPSC Description` | Stable |
| **📊 BID STATUS** | | | | |
| Bid/notice status | `Notice Status` | `Notice Status` | `Bid Notice Status` | More descriptive 2025 |
| Created by user | — | `Created By` | **REMOVED** | Added 2021, privacy concern 2025 |
| **🏆 AWARD ID** | | | | |
| Award reference | `Award No.` | `Award No.` | `Award Reference No.` | More descriptive 2025 |
| Award title | `Award Title` | `Award Title` | `Award Title` | Stable |
| Award type | `Award Type` | `Award Type` | **REMOVED** | Simplified 2025 |
| **📅 AWARD TIMELINE** | | | | |
| Published date (award) | `Publish Date(Award)` | `Published Date(Award)` | `Published Date(Award)` | Renamed 2021 |
| Award date | `Award Date` | `Award Date` | `Award Date` | Stable |
| Notice to proceed | `Notice to Proceed Date` | `Notice to Proceed Date` | `Notice to Proceed Date` | Stable |
| Contract effectivity | `Contract Efectivity Date` ⚠️ | `Contract Efectivity Date` ⚠️ | `Contract Effectivity Date` ✅ | Typo fixed 2025 |
| Contract end date | `Contract End Date` | `Contract End Date` | `Contract End Date` | Stable |
| **💵 CONTRACT** | | | | |
| Contract amount | `Contract Amount` | `Contract Amount` | `Contract Amount` | Stable |
| Contract number | `Contract No` | `Contract No` | **REMOVED** | Auto-generated 2025 |
| **🎯 AWARD STATUS** | | | | |
| Award status | `Award Status` | `Award Status` | `Award Notice Status` | Consistent naming 2025 |
| Reason for award | `Reason for Award` | `Reason for Award` | **REMOVED** | Simplified 2025 |
| **🏢 AWARDEE INFORMATION** | | | | |
| Organization name | `Awardee Corporate Title` | `Awardee Organization Name` | `Awardee Organization Name` | Renamed 2021 |
| Contact person | — | `Awardee Contact Person` | **REMOVED** | Added 2021, removed 2025 (privacy) |
| Country | — | — | `Country of Awardee` | **NEW in 2025/V2** |
| Region | — | — | `Region of Awardee` | **NEW in 2025/V2** |
| Province | — | — | `Province of Awardee` | **NEW in 2025/V2** |
| City/Municipality | — | — | `City/Municipality of Awardee` | **NEW in 2025/V2** |
| Awardee size | — | — | `Awardee Size` | **NEW in 2025/V2** (Small/Med/Large) |
| Joint venture | — | — | `Awardee Joint Venture` | **NEW in 2025/V2** (JV partners) |
| **👥 COMPETITION** | | | | |
| List of bidders | — | `List of Bidder's` | **REMOVED** | Added 2021, sensitive data 2025 |

**Totals by Schema:**
- Schema 1-2 (2000-2020): **40 fields**
- Schema 3 (2021-2024): **43 fields** (+3: Created By, Contact Person, List of Bidders)
- Schema 4-5 (2025/V2): **46 fields** (+12 location fields, -9 legacy/privacy fields)

---

### Category Breakdown by Schema Period

### 🏛️ Procuring Entity Information

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Organization Name` | `Procuring Entity` | `Procuring Entity (PE)` | Core entity field |
| — | — | `Region` | **NEW in 2025/V2** |
| — | — | `Province` | **NEW in 2025/V2** |
| — | — | `City/Municipality` | **NEW in 2025/V2** |
| — | — | `Government Branch` | **NEW in 2025/V2** |
| — | — | `PE Organization Type` | **NEW in 2025/V2** |
| — | — | `PE Organization Type (Grouped)` | **NEW in 2025/V2** |

**Evolution:** From single name field to rich entity profile with complete location and classification data.

---

### 📋 Bid Notice Identification

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Reference ID` | `Bid Reference No.` | `Bid Reference No.` | Renamed in 2021 |
| `Solicitation No.` | `Solicitation No.` | **REMOVED** | Legacy field dropped 2025 |
| `Notice Title` | `Notice Title` | `Notice Title` | Unchanged |
| `Classification` | `Classification` | `Classification` | Unchanged |
| `Notice Type` | `Notice Type` | **REMOVED** | Redundant, dropped 2025 |
| `Business Category` | `Business Category` | `Business Category` | Unchanged |

**Evolution:** Simplified by removing redundant `Notice Type` and legacy `Solicitation No.` fields.

---

### 📅 Bid Notice Dates & Timeline

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Publish Date` | `Published Date` | `Published Date` | Renamed in 2021 |
| `PreBid Date` | `PreBid Date` | **REMOVED** | Less commonly used |
| `Closing Date` | `Closing Date` | `Closing Date` | Unchanged |

**Evolution:** Streamlined to focus on critical dates (published and closing).

---

### 💰 Budget & Funding

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Funding Source` | `Funding Source` | `Funding Source` | Unchanged |
| `Funding Instrument` | `Funding Instrument` | `Funding Instrument` | Unchanged |
| `Approved Budget of the Contract` | `Approved Budget of the Contract` | `Approved Budget of the Contract` | Unchanged |
| `Trade Agreement` | `Trade Agreement` | `Trade Agreement` | Unchanged |

**Evolution:** This group remained completely stable across all schemas.

---

### 🛒 Procurement Details

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Procurement Mode` | `Procurement Mode` | `Procurement Mode` | Unchanged |
| `Area of Delivery` | `Area of Delivery` | `Area of Delivery` | Unchanged |
| `Contract Duration` | `Contract Duration` | `Contract Duration` | Unchanged |
| `Calendar Type` | `Calendar Type` | `Calendar Type` | Unchanged |

**Evolution:** Another completely stable group across 25 years.

---

### 📦 Line Item Details

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Line Item No` | `Line Item No` | `Line Item No` | Unchanged |
| `Item Name` | `Item Name` | `Item Name` | Unchanged |
| `Item Desc` | `Item Description` | `Item Description` | Renamed in 2021 (full word) |
| `Quantity` | `Quantity` | `Quantity` | Unchanged |
| **`UOM`** (2000-2015) | `UOM` | `UOM` | **Changed in 2016** ⚡ |
| **`Unit of Measurement`** (2016-2020) | | | |
| `Item Budget` | `Item Budget` | `Item Budget` | Unchanged |

**Evolution:** Minor rename of `Item Desc` and the notable `UOM` → `Unit of Measurement` change in 2016 (Schema 2).

---

### 🏷️ UNSPSC Classification

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `UNSPSC Code` | `UNSPSC Code` | `UNSPSC Code` | Unchanged |
| `UNSPSC Description` | `UNSPSC Description` | `UNSPSC Description` | Unchanged |

**Evolution:** International standard classification remained stable.

---

### 📊 Bid Notice Status & Tracking

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Notice Status` | `Notice Status` | `Bid Notice Status` | **Renamed 2025** (more descriptive) |
| — | **`Created By`** ⭐ | **REMOVED** | Added 2021, removed 2025 |
| — | — | — | |

**Evolution:** Status field made more explicit. User tracking field was short-lived (2021-2024 only).

---

### 🏆 Award Identification

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Award No.` | `Award No.` | `Award Reference No.` | Renamed 2025 (more descriptive) |
| `Award Title` | `Award Title` | `Award Title` | Unchanged |
| `Award Type` | `Award Type` | **REMOVED** | Simplified in 2025 |

**Evolution:** Simplified by removing `Award Type` while making reference field more explicit.

---

### 📅 Award Dates & Timeline

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Publish Date(Award)` | `Published Date(Award)` | `Published Date(Award)` | Renamed in 2021 |
| `Award Date` | `Award Date` | `Award Date` | Unchanged |
| `Notice to Proceed Date` | `Notice to Proceed Date` | `Notice to Proceed Date` | Unchanged |
| `Contract Efectivity Date` ⚠️ | `Contract Efectivity Date` ⚠️ | `Contract Effectivity Date` ✅ | **Typo fixed in 2025!** |
| `Contract End Date` | `Contract End Date` | `Contract End Date` | Unchanged |

**Evolution:** The 25-year-old "Efectivity" typo was finally fixed in Schema 4 (2025)!

---

### 💵 Contract Financial Details

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Contract Amount` | `Contract Amount` | `Contract Amount` | Unchanged |
| `Contract No` | `Contract No` | **REMOVED** | System-generated in 2025 |

**Evolution:** Contract number field removed, likely auto-generated in new system.

---

### 🎯 Award Status & Outcome

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Award Status` | `Award Status` | `Award Notice Status` | **Renamed 2025** (consistent naming) |
| `Reason for Award` | `Reason for Award` | **REMOVED** | Simplified in 2025 |

**Evolution:** Status field renamed for consistency with `Bid Notice Status`. Reason field removed.

---

### 🏢 Awardee Information

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| `Awardee Corporate Title` | `Awardee Organization Name` | `Awardee Organization Name` | Renamed in 2021 |
| — | **`Awardee Contact Person`** ⭐ | **REMOVED** | Added 2021, removed 2025 (privacy) |
| — | — | `Country of Awardee` | **NEW in 2025/V2** |
| — | — | `Region of Awardee` | **NEW in 2025/V2** |
| — | — | `Province of Awardee` | **NEW in 2025/V2** |
| — | — | `City/Municipality of Awardee` | **NEW in 2025/V2** |
| — | — | `Awardee Size` | **NEW in 2025/V2** (Small/Medium/Large) |
| — | — | `Awardee Joint Venture` | **NEW in 2025/V2** (JV partners) |

**Evolution:** From single name field to comprehensive contractor profile with complete location and classification. Contact person removed for privacy.

---

### 👥 Competition & Transparency

| Schema 1-2<br>2000-2020 | Schema 3<br>2021-2024 | Schema 4-5<br>2025 / 2021-2024-V2 | Notes |
|---|---|---|---|
| — | **`List of Bidder's`** ⭐ | **REMOVED** | Added 2021, removed 2025 (privacy/competition) |

**Evolution:** Bidder list was briefly exposed (2021-2024) then removed, likely due to privacy concerns and competitive sensitivity.

---

## Field Category Summary

| Category | Schema 1-2 Count | Schema 3 Count | Schema 4-5 Count | Stability |
|----------|------------------|----------------|------------------|-----------|
| **Procuring Entity** | 1 field | 1 field | 7 fields | ⭐⭐⭐ Major expansion |
| **Bid Identification** | 6 fields | 6 fields | 4 fields | ⭐⭐ Simplified |
| **Bid Timeline** | 3 fields | 3 fields | 2 fields | ⭐ Minor reduction |
| **Budget & Funding** | 4 fields | 4 fields | 4 fields | ⭐⭐⭐ Completely stable |
| **Procurement Details** | 4 fields | 4 fields | 4 fields | ⭐⭐⭐ Completely stable |
| **Line Items** | 6 fields | 6 fields | 6 fields | ⭐⭐ Mostly stable (UOM rename) |
| **UNSPSC** | 2 fields | 2 fields | 2 fields | ⭐⭐⭐ Completely stable |
| **Bid Status** | 1 field | 2 fields | 1 field | ⭐ Tracking added/removed |
| **Award Identification** | 3 fields | 3 fields | 2 fields | ⭐ Minor simplification |
| **Award Timeline** | 5 fields | 5 fields | 5 fields | ⭐⭐⭐ Stable (typo fixed) |
| **Contract Financials** | 2 fields | 2 fields | 1 field | ⭐ Minor simplification |
| **Award Status** | 2 fields | 2 fields | 1 field | ⭐ Simplified |
| **Awardee Info** | 1 field | 2 fields | 7 fields | ⭐⭐⭐ Major expansion |
| **Competition** | 0 fields | 1 field | 0 fields | ⭐ Temporary addition |

**Key Insights from Grouping:**

1. **Location Data is the Big Change** - Both PE and Awardee went from 1 field to 7 fields (6 location + 1 classification)
2. **Core Procurement Fields are Rock Solid** - Budget, funding, procurement mode, item details barely changed
3. **Privacy-Driven Removals** - Created By, Contact Person, and List of Bidders were all removed in 2025
4. **Simplification Trend** - Legacy fields (Solicitation No, Notice Type, Award Type, Reason for Award) systematically removed
5. **Consistent Naming** - Status fields standardized to "Bid Notice Status" and "Award Notice Status"

---


## Key Observations & Insights

1. **Location Data Gap:**
    - 2000-2020: No location data
    - 2021-2024 (Schema 3): Still no location data
    - 2021-2024 (Schema 5): Full location data (retroactive)
    - 2025+: Full location data

2. **Privacy Considerations:**
    - Schema 3 introduced personal data fields (Created By, Awardee Contact Person, List of Bidders)
    - Schema 4/5 removed these, likely due to privacy regulations (Data Privacy Act of 2012) and GDPR-like compliance

3. **Status Field Canonicalization:**
    - Old: `Notice Status` → New: `Bid Notice Status`
    - Old: `Award Status` → New: `Award Notice Status`
    - The rename makes fields more descriptive and consistent

4. **Column Order Is Unreliable:**
    - Column positions change dramatically between schemas
    - **Always map by column NAME, never by position**

5. **Typo Correction:**
    - The longstanding typo `Contract Efectivity Date` was corrected to `Contract Effectivity Date` in Schema 4

6. **File Naming Conventions:**
    - Schema 1-2: `YYYY-MM -- YYYY-MM.xlsx`
    - Schema 3: `YYYY-MM -- YYYY-MM.csv`
    - Schema 4: `YYYY-MM -- YYYY-MM.csv`
    - Schema 5: `YYYY_MMM-MMM.csv`
    - Schema 5 uses a different naming convention, confirming it's a separate export process

---

## Side-by-Side Column Comparison

### Complete Column Mapping Table

| # | Schema 1<br>2000-2015 | Schema 2<br>2016-2020 | Schema 3<br>2021-2024 | Schema 4<br>2025 | Schema 5<br>2021-2024-V2 |
|---|---|---|---|---|---|
| 1 | `Organization Name` | `Organization Name` | `Procuring Entity` | `Procuring Entity (PE)` | `Procuring Entity (PE)` |
| 2 | `Reference ID` | `Reference ID` | `Bid Reference No.` | `Region` | `Region` |
| 3 | `Solicitation No.` | `Solicitation No.` | `Solicitation No.` | `Province` | `Province` |
| 4 | `Notice Title` | `Notice Title` | `Notice Title` | `City/Municipality` | `City/Municipality` |
| 5 | `Publish Date` | `Publish Date` | `Notice Type` | `Government Branch` | `Government Branch` |
| 6 | `Classification` | `Classification` | `Classification` | `PE Organization Type` | `PE Organization Type` |
| 7 | `Notice Type` | `Notice Type` | `Procurement Mode` | `PE Organization Type (Grouped)` | `PE Organization Type (Grouped)` |
| 8 | `Business Category` | `Business Category` | `Business Category` | `Bid Reference No.` | `Bid Reference No.` |
| 9 | `Funding Source` | `Funding Source` | `Funding Source` | `Notice Title` | `Notice Title` |
| 10 | `Funding Instrument` | `Funding Instrument` | `Funding Instrument` | `Classification` | `Classification` |
| 11 | `Procurement Mode` | `Procurement Mode` | `Trade Agreement` | `Procurement Mode` | `Procurement Mode` |
| 12 | `Trade Agreement` | `Trade Agreement` | `Approved Budget of the Contract` | `Business Category` | `Business Category` |
| 13 | `Approved Budget of the Contract` | `Approved Budget of the Contract` | `Published Date` | `Funding Source` | `Funding Source` |
| 14 | `Area of Delivery` | `Area of Delivery` | `Closing Date` | `Funding Instrument` | `Funding Instrument` |
| 15 | `Contract Duration` | `Contract Duration` | `PreBid Date` | `Trade Agreement` | `Trade Agreement` |
| 16 | `Calendar Type` | `Calendar Type` | `Area of Delivery` | `Approved Budget of the Contract` | `Approved Budget of the Contract` |
| 17 | `Line Item No` | `Line Item No` | `Contract Duration` | `Published Date` | `Published Date` |
| 18 | `Item Name` | `Item Name` | `Calendar Type` | `Closing Date` | `Closing Date` |
| 19 | `Item Desc` | `Item Desc` | `Line Item No` | `Area of Delivery` | `Area of Delivery` |
| 20 | `Quantity` | `Quantity` | `Item Name` | `Contract Duration` | `Contract Duration` |
| 21 | **`UOM`** | **`Unit of Measurement`** | `Item Description` | `Calendar Type` | `Calendar Type` |
| 22 | `Item Budget` | `Item Budget` | `Quantity` | `Line Item No` | `Line Item No` |
| 23 | `PreBid Date` | `PreBid Date` | `UOM` | `Item Name` | `Item Name` |
| 24 | `Closing Date` | `Closing Date` | `Item Budget` | `Item Description` | `Item Description` |
| 25 | `Notice Status` | `Notice Status` | `Notice Status` | `Quantity` | `Quantity` |
| 26 | `Award No.` | `Award No.` | **`Created By`** ⭐ | `UOM` | `UOM` |
| 27 | `Award Title` | `Award Title` | `Award No.` | `Item Budget` | `Item Budget` |
| 28 | `Award Type` | `Award Type` | `Award Title` | **`Bid Notice Status`** | **`Bid Notice Status`** |
| 29 | `UNSPSC Code` | `UNSPSC Code` | `Award Type` | `Award Reference No.` | `Award Reference No.` |
| 30 | `UNSPSC Description` | `UNSPSC Description` | `UNSPSC Code` | `Award Title` | `Award Title` |
| 31 | `Awardee Corporate Title` | `Awardee Corporate Title` | `UNSPSC Description` | `UNSPSC Code` | `UNSPSC Code` |
| 32 | `Contract Amount` | `Contract Amount` | `Published Date(Award)` | `UNSPSC Description` | `UNSPSC Description` |
| 33 | `Contract No` | `Contract No` | `Award Date` | `Published Date(Award)` | `Published Date(Award)` |
| 34 | `Publish Date(Award)` | `Publish Date(Award)` | `Notice to Proceed Date` | `Award Date` | `Award Date` |
| 35 | `Award Date` | `Award Date` | `Contract No` | `Contract Amount` | `Contract Amount` |
| 36 | `Notice to Proceed Date` | `Notice to Proceed Date` | `Contract Amount` | **`Award Notice Status`** | **`Award Notice Status`** |
| 37 | `Contract Efectivity Date` | `Contract Efectivity Date` | `Contract Efectivity Date` | `Notice to Proceed Date` | `Notice to Proceed Date` |
| 38 | `Contract End Date` | `Contract End Date` | `Contract End Date` | `Contract Effectivity Date` | `Contract Effectivity Date` |
| 39 | `Reason for Award` | `Reason for Award` | `Award Status` | `Contract End Date` | `Contract End Date` |
| 40 | `Award Status` | `Award Status` | `Reason for Award` | `Awardee Organization Name` | `Awardee Organization Name` |
| 41 | — | — | `Awardee Organization Name` | **`Country of Awardee`** 🌍 | **`Country of Awardee`** 🌍 |
| 42 | — | — | **`Awardee Contact Person`** ⭐ | **`Region of Awardee`** 🌍 | **`Region of Awardee`** 🌍 |
| 43 | — | — | **`List of Bidder's`** ⭐ | **`Province of Awardee`** 🌍 | **`Province of Awardee`** 🌍 |
| 44 | — | — | — | **`City/Municipality of Awardee`** 🌍 | **`City/Municipality of Awardee`** 🌍 |
| 45 | — | — | — | **`Awardee Size`** 🌍 | **`Awardee Size`** 🌍 |
| 46 | — | — | — | **`Awardee Joint Venture`** 🌍 | **`Awardee Joint Venture`** 🌍 |

**Legend:**
- ⭐ = New tracking/metadata field
- 🌍 = Location/classification field
- **Bold** = Major rename or new field

---

**Document Version:** 1.0  
**Last Updated:** November 14, 2025  
**Next Review:** When Schema 6 emerges or schema changes detected
