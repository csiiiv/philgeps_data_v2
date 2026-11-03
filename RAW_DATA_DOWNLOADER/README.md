# RAW_DATA_DOWNLOADER (stage 0)

Downloads the PhilGEPS quarterly/annual procurement exports from Google
Drive and produces the provenance manifest that every downstream stage
depends on. The downloaded files and manifest are **not** tracked in git
(`dataset/` is gitignored — 8.4 GB); the scripts, URL lists, and reference
docs are.

> **Source data on Google Drive**: <https://drive.google.com/drive/folders/1Km2gqIfaY_9ZotjvePFZVSMEuxud6WWA?usp=sharing>

## Layout

```
dataset/                  # downloads + manifest.json (gitignored)
  files/                  # the source workbooks/CSVs
  manifest.json           # v2 provenance registry (see below)
references/               # URL lists + name-normalization map
  source_urls*.txt        # the four rounds of source URLs
  normalized_file_names.json
scripts/                  # the downloader and dataset utilities
docs/
  gdrive_bulk_downloader_reference.md   # design reference for the downloader
```

## Scripts

| Script | Purpose |
|---|---|
| `download_gdrive_sources.py` | Bulk Google Drive/Sheets downloader: reads a URL list, downloads or resumes each file into `dataset/files/`, records URL → file mapping |
| `rebuild_manifest.py` | (Re)builds `dataset/manifest.json` at manifest **v2**: content-addressed `source_file_id` = SHA-256 of exact bytes, unique file registry across URLs |
| `manifest_utils.py` | Shared helpers for reading/writing the v2 manifest |
| `reconcile_dataset.py` | Idempotent two-pass dataset reconciler (verify downloads against URLs, repair registry) |
| `repair_dataset.py` | One-off repair after an interrupted run |
| `fix_double_extensions.py` | One-off cleanup of doubled extensions (`.csv.csv`) from an earlier downloader bug |
| `show_manifest_status.py` | Human-readable manifest status/diagnostics |

## Manifest v2 in one paragraph

Every downloaded document is registered with its exact-bytes SHA-256, the
URL(s) it was fetched from, its normalized filename, and detected period.
`source_file_id` (the SHA-256) is the key every downstream table joins on:
`philgeps_normalized.parquet._source_file_id` → manifest → original URL.
That chain is what makes any award-item row traceable to a downloadable
source document.

## Current corpus state

- **Source folder (Google Drive)**: <https://drive.google.com/drive/folders/1Km2gqIfaY_9ZotjvePFZVSMEuxud6WWA?usp=sharing>
- **70 local files** — 52 XLSX + 18 CSV, spanning 2000–2025
- **71 source URLs** (one file reachable via two URLs, identical SHA-256)
- The manifest is the provenance backbone; stage 1 (`DATA_NORMALIZATION`)
  consumes it read-only via `../DATA_NORMALIZATION/scripts/build_source_catalog.py`

## Re-running

```powershell
cd RAW_DATA_DOWNLOADER
python scripts/download_gdrive_sources.py references/source_urls_4.txt
python scripts/rebuild_manifest.py
python scripts/reconcile_dataset.py        # optional verification pass
python scripts/show_manifest_status.py
```

Downloads resume; re-running is safe. After any change to the corpus,
downstream stages must be rebuilt (stage 1 catalog → normalized → cleaned →
stage 2 → viewer caches).
