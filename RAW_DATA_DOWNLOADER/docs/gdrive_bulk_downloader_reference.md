# Google Drive / Google Sheets Bulk Downloader --- Implementation Reference

## Objective

Build a small utility that accepts a list of Google Drive and Google
Sheets URLs, downloads each accessible source into a local dataset
directory, and creates a machine-readable `manifest.json` linking every
downloaded document back to its original source URL.

The downloader should prioritize reproducibility, provenance, clear
error reporting, and safe reruns.

> **Production corpus**: the actual PhilGEPS exports this utility was
> built for live in the [PHILGEPS-V2 Drive folder](https://drive.google.com/drive/folders/1Km2gqIfaY_9ZotjvePFZVSMEuxud6WWA?usp=sharing)
> (70 files, 2000–2025).

## Expected Input

Use a plain-text file such as `source_urls.txt`, with one source URL per
line:

``` text
https://docs.google.com/spreadsheets/d/ABC123/edit#gid=0
https://docs.google.com/spreadsheets/d/XYZ456/edit#gid=12345
https://drive.google.com/file/d/FILE123/view
```

Ignore blank lines and optionally lines beginning with `#`.

The input may contain a mixture of:

-   Native Google Sheets spreadsheets.
-   Google Drive-hosted XLSX, CSV, or other downloadable files.
-   Google Sheets URLs containing a specific `gid` referring to a
    worksheet/tab.
-   Duplicate URLs or multiple URLs referring to the same underlying
    document.
-   Inaccessible, deleted, malformed, or otherwise broken URLs.

## Desired Output Structure

``` text
dataset/
├── manifest.json
├── source_urls.txt
└── files/
    ├── Annual Procurement Plan 2025.xlsx
    ├── Contract Awards 2025.xlsx
    └── ...
```

Preserve the original input list as `source_urls.txt` for provenance.

## Core Workflow

For every input URL:

1.  Preserve the original URL exactly as supplied.
2.  Identify the URL/document type.
3.  Extract the Google document/file identifier where possible.
4.  For Google Sheets URLs, extract `gid` if present.
5.  Determine the actual document title when possible.
6.  Determine an appropriate export/download method.
7.  Download the file.
8.  Generate a safe local filename.
9.  Calculate SHA-256 over the downloaded bytes.
10. Record the result in `manifest.json`.
11. If an item cannot be downloaded, record the failure rather than
    terminating the entire batch.

## Google Sheets URL Parsing

Typical URL:

``` text
https://docs.google.com/spreadsheets/d/ABC123/edit#gid=456789
```

Extract:

``` text
spreadsheet_id = ABC123
gid            = 456789
```

The spreadsheet ID generally appears between:

``` text
/spreadsheets/d/
```

and the following `/`.

The `gid` may appear in the query string or fragment and should
therefore be parsed robustly rather than assuming only one URL format.

## Google Sheets Export

### Whole workbook as XLSX

For a native Google Sheet, the preferred default output is the complete
workbook as XLSX:

``` text
https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=xlsx
```

A URL containing `gid` should still normally download the complete
workbook unless the user explicitly selects per-tab CSV mode.

### Specific worksheet as CSV

Optional mode:

``` text
https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={GID}
```

This exports only the referenced worksheet/tab.

Recommended CLI behavior:

``` text
--format xlsx       # default: entire Google Sheet workbook
--format csv        # export referenced gid when available
```

## Authentication and Permissions

Do not assume that every URL is publicly downloadable.

There are two major cases:

### Public or link-accessible documents

Direct HTTP export/download may work without authentication.

### Documents requiring a Google account

Plain unauthenticated HTTP requests may return a login page, permission
page, or HTML rather than the expected spreadsheet/file.

For authenticated collections, prefer the Google Drive API / appropriate
Google authentication rather than relying on browser cookies.

The implementation should detect suspicious responses. For example, an
`.xlsx` download that actually has `text/html` content should be treated
as a failure rather than silently saved as a workbook.

## Manifest

`manifest.json` is the authoritative mapping between local files and
their sources.

Recommended structure:

``` json
{
  "version": 2,
  "generated_at": "2026-09-11T23:45:12+08:00",
  "source_files": [
    {
      "source_file_id": "pgf_e3b0c44298fc...",
      "sha256": "e3b0c44298fc...",
      "local_files": ["files/Annual Procurement Plan 2025.xlsx"],
      "normalized_file_name": "2025-01--2025-12.xlsx",
      "document_ids": ["pgd_abc123..."]
    }
  ],
  "documents": [
    {
      "document_id": "pgd_abc123...",
      "source_file_id": "pgf_e3b0c44298fc...",
      "title": "Annual Procurement Plan 2025",
      "source_url": "https://docs.google.com/spreadsheets/d/ABC123/edit#gid=0",
      "source_type": "google_sheet",
      "google_file_id": "ABC123",
      "gid": "0",
      "local_file": "files/Annual Procurement Plan 2025.xlsx",
      "sha256": "e3b0c44298fc...",
      "status": "downloaded",
      "downloaded_at": "2026-09-11T23:45:12+08:00",
      "error": null
    }
  ]
}
```

## Minimum Manifest Fields

At minimum, preserve:

``` text
title
source_url
local_file
status
```

Strongly recommended additional fields:

``` text
source_type
google_file_id
gid
sha256
downloaded_at
error
document_id
source_file_id
```

`document_id` is the SHA-256-derived identity of the exact source URL.
`source_file_id` is derived from the downloaded file SHA-256 and references the
unique top-level `source_files` registry. Multiple source URLs may therefore
share one `source_file_id`. Downstream datasets should reference
`source_file_id`, not a manifest array position.

### `normalized_file_name`

Canonical display/output name stored on each top-level `source_files` entry.
PhilGEPS files use `YYYY-MM--YYYY-MM.ext`, where the two values are the first
and last months represented by the file. The explicit mapping is maintained in
`references/normalized_file_names.json`; it does not rename the downloaded
file recorded in `local_files`.

### `title`

Human-readable source document title. Prefer the actual Google
Drive/Sheets metadata title rather than deriving it solely from the URL.

### `source_url`

The original URL exactly as supplied in the input list.

Do **not** replace this with the generated `/export` URL. The original
URL is the provenance/reference URL; the export URL is only a transport
mechanism.

### `local_file`

Path relative to the dataset root, for example:

``` text
files/Annual Procurement Plan 2025.xlsx
```

Relative paths make the package portable.

### `sha256`

SHA-256 of the exact downloaded file bytes. Calculate after the file has
been fully written.

Example Python:

``` python
import hashlib

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
```

### `status`

Suggested values:

``` text
downloaded
skipped
failed
```

### `error`

`null` for successful downloads. For failures, store a concise
diagnostic message.

Example:

``` json
{
  "title": null,
  "source_url": "https://docs.google.com/spreadsheets/d/INVALID/edit",
  "source_type": "google_sheet",
  "google_file_id": "INVALID",
  "gid": null,
  "local_file": null,
  "sha256": null,
  "status": "failed",
  "downloaded_at": null,
  "error": "HTTP 403: access denied"
}
```

Failures should remain in the manifest so the final dataset records
every attempted source.

## Filename Handling

Use the actual document title as the basis of the filename when
available.

Sanitize characters that are illegal or problematic on common
filesystems, including:

``` text
< > : " / \\ | ? *
```

Also:

-   Trim trailing periods/spaces.
-   Avoid empty filenames.
-   Preserve the correct extension.
-   Handle duplicate titles deterministically.

For duplicates, a reasonable scheme is:

``` text
Annual Procurement Plan.xlsx
Annual Procurement Plan__2.xlsx
```

or append a short stable portion of the Google file ID.

Do not overwrite an unrelated existing file merely because two documents
have the same title.

## Duplicate Detection

Consider duplicates at two levels.

### Duplicate source

Multiple input URLs may refer to the same Google file ID. Detect this
and avoid unnecessary repeated downloads where appropriate.

However, retain enough provenance information to show that multiple
input URLs were supplied if that matters to the source list.

### Duplicate content

Two different source documents may produce identical bytes. SHA-256
makes this detectable after download. Do not automatically discard them
unless deduplication is explicitly enabled.

## Safe Reruns / Resume Behavior

The downloader should be safely rerunnable.

On startup, load an existing `manifest.json` if present.

For an existing successful entry:

1.  Check whether `local_file` exists.
2.  Optionally recompute SHA-256.
3.  If the file exists and matches the manifest, skip the download.
4.  If it is missing or mismatched, download it again.

Provide a force option if useful:

``` text
--force
```

This avoids redownloading a large collection after an interrupted run.

## HTTP Robustness

Implement:

-   Connection/read timeout.
-   Limited retries with backoff.
-   Redirect handling.
-   HTTP status validation.
-   Content-type sanity checks.
-   Temporary `.part` files during download.
-   Atomic rename after a successful download.

Conceptually:

``` text
filename.xlsx.part
        ↓ successful complete download
filename.xlsx
```

This prevents an interrupted transfer from appearing to be a valid
completed file.

## Suggested CLI

Example:

``` bash
python download_gdrive_sources.py source_urls.txt ./dataset
```

Possible options:

``` bash
python download_gdrive_sources.py source_urls.txt ./dataset \\
    --format xlsx \\
    --retries 3
```

Desired help interface:

``` text
usage: download_gdrive_sources.py INPUT OUTPUT_DIR [options]

INPUT       Text file containing one Google URL per line
OUTPUT_DIR  Dataset output directory

options:
  --format {xlsx,csv}   Google Sheets export format (default: xlsx)
  --force               Redownload existing successful items
  --retries N           Number of HTTP retries
```

Use Python `argparse` unless the project already uses another CLI
framework.

## Suggested Python Structure

Keep parsing, downloading, and manifest handling separated enough to
test independently.

``` text
download_gdrive_sources.py
│
├── load_urls()
├── parse_google_url()
├── get_document_metadata()
├── build_download_url()
├── sanitize_filename()
├── download_file()
├── sha256_file()
├── load_manifest()
├── save_manifest()
└── main()
```

A small project can keep these functions in one file initially. Split
into modules only when complexity warrants it.

## URL Parser Output

A useful internal representation is:

``` python
{
    "source_url": original_url,
    "source_type": "google_sheet",
    "google_file_id": "ABC123",
    "gid": "0"
}
```

Other possible `source_type` values:

``` text
google_sheet
gdrive_file
unknown
```

Unknown URLs should be recorded as failures with an explanation rather
than silently ignored.

## Logging

Console output should make batch progress obvious:

``` text
[1/150] Annual Procurement Plan 2025
        downloading -> files/Annual Procurement Plan 2025.xlsx
        SHA256: 91a43b...
        OK

[2/150] Contract Awards 2025
        FAILED: HTTP 403 access denied
```

At completion, print a summary:

``` text
Completed: 150 sources
Downloaded: 142
Skipped:      5
Failed:       3
Manifest: dataset/manifest.json
```

## Data Integrity / Provenance Principles

The package should preserve a traceable chain:

``` text
Original source URL
        ↓
Google file/document ID
        ↓
Downloaded local file
        ↓
SHA-256
        ↓
manifest.json
```

The manifest should be sufficient to answer:

-   Where did this local file come from?
-   What was the original source URL?
-   What was the source document called?
-   When was it downloaded?
-   Is this local copy byte-for-byte the same copy recorded at download
    time?
-   Which sources failed to download?

## Important Implementation Rules

1.  Never silently discard failed URLs.
2.  Never use the generated export URL as the canonical source
    reference.
3.  Never save an HTML login/error page as `.xlsx` without detecting the
    mismatch.
4.  Do not overwrite files solely because titles collide.
5.  Write/update the manifest incrementally so progress survives
    interruption.
6.  Use relative local paths in the manifest.
7.  Calculate hashes from the final downloaded bytes.
8.  Preserve the original URL list.
9.  Prefer actual Google metadata titles when authentication/API access
    permits it.
10. Keep the first implementation simple; concurrency can be added later
    if sequential downloads are too slow.

## Initial Deliverable

Implement a working Python utility that:

-   Reads URLs from `source_urls.txt`.
-   Recognizes native Google Sheets URLs.
-   Downloads each Sheet as a complete `.xlsx` workbook by default.
-   Supports ordinary downloadable Google Drive files where practical.
-   Uses actual titles when obtainable and safe fallback names
    otherwise.
-   Generates SHA-256 hashes.
-   Produces and incrementally updates `manifest.json`.
-   Continues after individual failures.
-   Supports rerunning/resuming without unnecessarily downloading
    completed files again.

Start with a reliable sequential implementation. Add parallel
downloading only after the basic behavior, authentication handling,
manifest generation, and failure recovery are correct.
