#!/usr/bin/env python3
"""Bulk downloader for Google Drive / Google Sheets sources.

Reads a text file with one Google URL per line, downloads each accessible
source into a dataset directory, and maintains an incrementally-written
manifest.json mapping every local file back to its original source URL.

Usage:
    python download_gdrive_sources.py INPUT OUTPUT_DIR [--format {xlsx,csv}]
                                    [--force] [--retries N]
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from manifest_utils import MANIFEST_VERSION, normalize_manifest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFEST_NAME = "manifest.json"
FILES_SUBDIR = "files"

CHUNK_SIZE = 1024 * 1024          # 1 MiB streaming chunks
CONNECT_TIMEOUT = 10              # seconds
READ_TIMEOUT = 180                # seconds
HTML_SNIFF_LIMIT = 5 * 1024 * 1024  # max HTML body to buffer while looking
                                    # for a Drive "confirm download" form

TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
TITLE_SUFFIXES = (" - Google Sheets", " - Google Drive", " - Google Docs")

# Titles seen on Google error pages rather than real documents. These must
# never be used as document titles (they leak into filenames otherwise).
JUNK_TITLE_PATTERNS = (
    "nilo-load ang",        # Filipino error page ("failed to load")
    "couldn't load",
    "could not load",
    "cannot load",
    "hindi ma-load",
    "error 404",
    "404 not found",
    "page not found",
    "server error",
    "service error",
    "temporarily unavailable",
    "sign in",
    "sign-in",
    "google accounts",
)

SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
FILE_ID_RE = re.compile(r"/(?:file|document|presentation|drawings)/d/([A-Za-z0-9_-]+)")

CONFIRM_INPUT_RE = re.compile(r"<input[^>]*>", re.I)
ATTR_NAME_RE = re.compile(r'name\s*=\s*"([^"]*)"', re.I)
ATTR_VALUE_RE = re.compile(r'value\s*=\s*"([^"]*)"', re.I)

CONTENT_TYPE_EXT = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/pdf": ".pdf",
    "text/csv": ".csv",
    "application/zip": ".zip",
    "application/json": ".json",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}

WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class DownloadError(Exception):
    """Raised when a source cannot be downloaded; message goes to the manifest."""


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def load_urls(path):
    """Return (line_number, url) pairs, skipping blanks and # comments."""
    entries = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            entries.append((lineno, line))
    return entries


def parse_google_url(url):
    """Classify a URL and extract the Google file id and optional gid.

    Returns a dict:
        {"source_url", "source_type", "google_file_id", "gid"}
    source_type is one of: google_sheet, gdrive_file, unknown.
    """
    parsed = {
        "source_url": url,
        "source_type": "unknown",
        "google_file_id": None,
        "gid": None,
    }
    try:
        parts = urlparse(url)
    except ValueError:
        return parsed

    host = (parts.netloc or "").lower()
    path = parts.path or ""

    def gid_from(parts):
        for raw in (parts.query, (parts.fragment or "").lstrip("#")):
            for val in parse_qs(raw).get("gid", []):
                if str(val).strip():
                    return str(val).strip()
        return None

    if host == "docs.google.com" or host.endswith(".docs.google.com"):
        m = SHEET_ID_RE.search(path)
        if m:
            parsed["source_type"] = "google_sheet"
            parsed["google_file_id"] = m.group(1)
            parsed["gid"] = gid_from(parts)
            return parsed
        m = FILE_ID_RE.search(path)
        if m:
            # Other workspace docs (Docs/Slides/Drawings): treat as Drive file
            parsed["source_type"] = "gdrive_file"
            parsed["google_file_id"] = m.group(1)
            return parsed

    if host in ("drive.google.com",) or host.endswith(".drive.google.com"):
        m = FILE_ID_RE.search(path)
        if m:
            parsed["source_type"] = "gdrive_file"
            parsed["google_file_id"] = m.group(1)
            return parsed
        qs = parse_qs(parts.query or "")
        if "id" in qs and qs["id"]:
            parsed["source_type"] = "gdrive_file"
            parsed["google_file_id"] = qs["id"][0]
            return parsed

    if host == "drive.usercontent.google.com" or host == "drive.google.com":
        # Legacy / modern direct-download endpoint: ?id=FILE_ID&export=download
        qs = parse_qs(parts.query or "")
        if qs.get("id"):
            parsed["source_type"] = "gdrive_file"
            parsed["google_file_id"] = qs["id"][0]
            return parsed

    return parsed


# ---------------------------------------------------------------------------
# Metadata (document titles)
# ---------------------------------------------------------------------------

def _page_title(session, url):
    """Fetch a page and return its cleaned <title>, or None."""
    resp = session.get(url, timeout=(CONNECT_TIMEOUT, 30))
    if resp.status_code != 200:
        return None
    m = TITLE_TAG_RE.search(resp.text[:200_000])
    if not m:
        return None
    title = html_mod.unescape(m.group(1)).strip()
    for suffix in TITLE_SUFFIXES:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    if not title:
        return None
    if any(pat in title.lower() for pat in JUNK_TITLE_PATTERNS):
        return None  # Google error page, not a document title
    return title


def get_document_metadata(session, parsed):
    """Best-effort fetch of the real document title. Returns title or None."""
    fid = parsed["google_file_id"]
    try:
        if parsed["source_type"] == "google_sheet":
            title = _page_title(
                session, f"https://docs.google.com/spreadsheets/d/{fid}/htmlview")
            if title is None:
                title = _page_title(
                    session, f"https://docs.google.com/spreadsheets/d/{fid}/edit")
            return title
        if parsed["source_type"] == "gdrive_file":
            return _page_title(
                session, f"https://drive.google.com/file/d/{fid}/view")
    except requests.RequestException:
        pass
    return None


# ---------------------------------------------------------------------------
# Download URL construction
# ---------------------------------------------------------------------------

def build_download_url(parsed, export_format):
    """Return the transport URL used to actually fetch bytes."""
    fid = parsed["google_file_id"]
    if parsed["source_type"] == "google_sheet":
        fmt = "csv" if export_format == "csv" else "xlsx"
        url = f"https://docs.google.com/spreadsheets/d/{fid}/export?format={fmt}"
        if fmt == "csv":
            url += f"&gid={parsed['gid'] or '0'}"
        return url
    # Google Drive files: modern usercontent endpoint handles large files
    # via the confirm-token flow handled in download_file().
    return f"https://drive.usercontent.google.com/download?id={fid}&export=download"


# ---------------------------------------------------------------------------
# Filename handling
# ---------------------------------------------------------------------------

def sanitize_filename(name):
    """Make a string safe as a filename on Windows/Linux/macOS."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if not name:
        name = "untitled"
    if name.split(".")[0].upper() in WINDOWS_RESERVED:
        name = "_" + name
    return name[:150]


def _filename_from_disposition(content_disposition):
    """Extract the server-provided filename, or None."""
    if not content_disposition:
        return None
    from urllib.parse import unquote
    m = re.search(r'filename\*\s*=\s*(?:UTF-8|utf-8)\'\'([^;]+)',
                  content_disposition)
    if m:
        return unquote(m.group(1)).strip('" ')
    m = re.search(r'filename\s*=\s*"([^"]+)"', content_disposition)
    if m:
        return html_mod.unescape(m.group(1)).strip('" ')
    return None


def _ext_for(content_type, content_disposition):
    if content_disposition:
        m = re.search(r'filename\*\s*=\s*(?:UTF-8|utf-8)\'\'([^;]+)',
                      content_disposition)
        if m:
            from urllib.parse import unquote
            _, ext = os.path.splitext(unquote(m.group(1)).strip('" '))
            if ext:
                return ext.lower()
        m = re.search(r'filename\s*=\s*"([^"]+)"', content_disposition)
        if m:
            _, ext = os.path.splitext(m.group(1).strip())
            if ext:
                return ext.lower()
    ctype = (content_type or "").split(";")[0].strip().lower()
    return CONTENT_TYPE_EXT.get(ctype, "")


def unique_path(directory, base, ext):
    """Deterministically avoid clobbering files owned by other sources."""
    candidate = os.path.join(directory, base + ext)
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}__{n}{ext}")
        n += 1
    return candidate


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def _looks_like_html(chunk):
    head = chunk[:2048].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _extract_confirm_params(body_text):
    """Parse the Drive virus-scan confirm form's hidden fields, if present."""
    for tag in CONFIRM_INPUT_RE.finditer(body_text):
        tag_html = tag.group(0)
        name_m = ATTR_NAME_RE.search(tag_html)
        if not name_m:
            continue
        name = html_mod.unescape(name_m.group(1))
        if name in ("id", "export", "confirm", "uuid", "resourcekey"):
            value_m = ATTR_VALUE_RE.search(tag_html)
            value = html_mod.unescape(value_m.group(1)) if value_m else ""
            yield name, value


def _http_get(session, url, max_retries):
    """GET with retries/backoff; returns a (possibly redirect-followed) response."""
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = session.get(
                url,
                stream=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                allow_redirects=True,
            )
            if resp.status_code in (429, 432):
                # Quota block (persistent for hours): one short retry, then
                # let the caller fall back to an alternate endpoint.
                last_err = DownloadError(
                    f"HTTP {resp.status_code}: rate limited by Google")
                resp.close()
                if attempt < 1:
                    time.sleep(15)
                    continue
                break
            if resp.status_code in (500, 502, 503, 504):
                last_err = DownloadError(f"HTTP {resp.status_code}: server busy")
                resp.close()
            elif resp.status_code == 403:
                raise DownloadError("HTTP 403: access denied")
            elif resp.status_code == 404:
                raise DownloadError("HTTP 404: not found")
            elif resp.status_code != 200:
                raise DownloadError(f"HTTP {resp.status_code}")
            else:
                return resp
        except requests.RequestException as exc:
            last_err = DownloadError(f"network error: {exc}")
        if attempt < max_retries:
            time.sleep(min(2 ** attempt, 30))
    raise last_err or DownloadError("download failed")


def download_file(session, url, dest_path, max_retries=3):
    """Stream url -> dest_path atomically. Returns (content_type, disposition).

    Raises DownloadError on failure. Writes to dest_path + '.part' and
    renames only after a complete, content-verified download.
    """
    part_path = dest_path + ".part"
    current_url = url
    confirm_hops = 0

    try:
        while True:
            resp = _http_get(session, current_url, max_retries)
            ctype = resp.headers.get("Content-Type", "")
            disposition = resp.headers.get("Content-Disposition", "")

            chunk_iter = resp.iter_content(chunk_size=CHUNK_SIZE)
            first_chunk = b""
            try:
                first_chunk = next(chunk_iter)
            except StopIteration:
                pass

            if ("text/html" in ctype.lower()) or _looks_like_html(first_chunk):
                # Buffer the page and look for a Drive confirm form.
                body = [first_chunk]
                size = len(first_chunk)
                for chunk in chunk_iter:
                    body.append(chunk)
                    size += len(chunk)
                    if size >= HTML_SNIFF_LIMIT:
                        break
                resp.close()
                page = first_chunk and b"".join(body)
                page_text = page.decode("utf-8", "replace") if page else ""
                params = dict(_extract_confirm_params(page_text))
                if params.get("id") and params.get("confirm") and confirm_hops < 2:
                    confirm_hops += 1
                    current_url = (
                        "https://drive.usercontent.google.com/download?"
                        + urlencode(params)
                    )
                    continue
                raise DownloadError(
                    "received an HTML page instead of a file "
                    "(document may not be publicly accessible)"
                )

            with open(part_path, "wb") as out:
                if first_chunk:
                    out.write(first_chunk)
                for chunk in chunk_iter:
                    if chunk:
                        out.write(chunk)
            resp.close()
            os.replace(part_path, dest_path)
            return ctype, disposition
    finally:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Manifest handling
# ---------------------------------------------------------------------------

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_manifest(out_dir):
    path = os.path.join(out_dir, MANIFEST_NAME)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("documents"), list):
                return normalize_manifest(data)
        except (json.JSONDecodeError, OSError):
            print("warning: existing manifest.json is unreadable; starting fresh")
    return normalize_manifest({
        "version": MANIFEST_VERSION,
        "generated_at": now_iso(),
        "documents": [],
    })


def save_manifest(out_dir, manifest, attempts=6):
    """Atomic incremental write so progress survives interruption.

    Windows: antivirus or the IDE may briefly lock manifest.json, making
    os.replace fail with PermissionError. Retry with backoff.
    """
    path = os.path.join(out_dir, MANIFEST_NAME)
    tmp = path + ".tmp"
    normalize_manifest(manifest)
    for attempt in range(attempts):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def new_entry(parsed, title):
    return {
        "title": title,
        "source_url": parsed["source_url"],
        "source_type": parsed["source_type"],
        "google_file_id": parsed["google_file_id"],
        "gid": parsed["gid"],
        "local_file": None,
        "sha256": None,
        "status": "failed",
        "downloaded_at": None,
        "error": None,
    }


def find_manifest_entry(manifest, source_url):
    for doc in manifest["documents"]:
        if doc.get("source_url") == source_url:
            return doc
    return None


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------

def process_url(index, total, parsed, manifest, session, args, state):
    """Download (or skip) one source URL; returns the manifest entry."""
    label = parsed["google_file_id"] or parsed["source_url"]
    print(f"\n[{index}/{total}] {label}")
    print(f"        {parsed['source_type']}"
          + (f" gid={parsed['gid']}" if parsed["gid"] else ""))

    if parsed["source_type"] == "unknown":
        entry = new_entry(parsed, None)
        entry["error"] = "unrecognized URL format"
        print(f"        FAILED: {entry['error']}")
        return entry

    fid_key = (parsed["source_type"], parsed["google_file_id"])

    # -- Resume: previous successful download for this exact URL? ----------
    # Accept both "downloaded" (prior run completed it) and "skipped" (a
    # later run verified the same file already exists and hash-matches).
    existing = find_manifest_entry(manifest, parsed["source_url"])
    if (existing and existing.get("status") in ("downloaded", "skipped")
            and not args.force):
        local = existing.get("local_file")
        local_path = os.path.join(state["out_dir"], local) if local else None
        if local_path and os.path.exists(local_path):
            if sha256_file(local_path) == existing.get("sha256"):
                print(f"        already downloaded -> {local} (skipping)")
                entry = new_entry(parsed, existing.get("title"))
                entry.update({
                    "local_file": local,
                    "sha256": existing.get("sha256"),
                    "status": "skipped",
                    "downloaded_at": existing.get("downloaded_at"),
                })
                entry["error"] = None
                return entry
            print("        manifest/file hash mismatch; redownloading")
        else:
            print("        manifest file missing; redownloading")

    # -- Duplicate source (same file id, different URL) ---------------------
    prior = state["by_file_id"].get(fid_key)
    if prior and prior.get("status") in ("downloaded", "skipped"):
        local = prior.get("local_file")
        local_path = (os.path.join(state["out_dir"], local)
                      if local else None)
        if local_path and os.path.exists(local_path):
            entry = new_entry(parsed, prior.get("title"))
            entry.update({
                "local_file": local,
                "sha256": prior.get("sha256"),
                "status": "skipped",
                "downloaded_at": prior.get("downloaded_at"),
                "duplicate_of": prior["source_url"],
                "error": None,
            })
            print(f"        duplicate of {prior['source_url']} -> skipped")
            return entry

    # -- Metadata -----------------------------------------------------------
    title = get_document_metadata(session, parsed)
    shown = title or f"google-{parsed['source_type']}-{parsed['google_file_id']}"
    print(f"        title: {title or '(unavailable)'}")

    # -- Download -----------------------------------------------------------
    url = build_download_url(parsed, args.format)
    files_dir = state["files_dir"]
    base = sanitize_filename(title or parsed["google_file_id"])
    entry = new_entry(parsed, title)

    # Placeholder name while streaming; final extension comes from headers
    tmp_target = unique_path(files_dir, base, ".downloading")
    try:
        ctype, disposition = download_file(
            session, url, tmp_target, max_retries=args.retries)
    except DownloadError as exc:
        if (parsed["source_type"] == "google_sheet"
                and "rate limited" in str(exc)):
            # Sheets export endpoints are quota-blocked (HTTP 432) for this
            # IP, but the Drive endpoint often still serves the file. For
            # rtpof=true sheets (originally-uploaded Office files) this even
            # yields the pristine uploaded original, not a re-export.
            fallback_url = (
                "https://drive.usercontent.google.com/download?id="
                f"{parsed['google_file_id']}&export=download")
            print(f"        {exc}; falling back to Drive endpoint")
            try:
                ctype, disposition = download_file(
                    session, fallback_url, tmp_target, max_retries=args.retries)
            except DownloadError as exc2:
                entry["error"] = str(exc2)
                print(f"        FAILED: {exc2}")
                return entry
            # The Drive response carries the original filename; prefer it as
            # the title when metadata scraping came up empty.
            fallback_title = _filename_from_disposition(disposition)
            if fallback_title:
                stem, _ = os.path.splitext(fallback_title)
                if stem and stem.lower() != "untitled":
                    entry["title"] = title = stem
                    base = sanitize_filename(title)
        else:
            entry["error"] = str(exc)
            print(f"        FAILED: {exc}")
            return entry

    # Finalize the filename. If the title already ends with a sane extension
    # (Drive CSV titles like "2025_(JUL-SEPT).csv"), split it off instead of
    # appending another one.
    ext = _ext_for(ctype, disposition)
    final_base = sanitize_filename(title) if title else base
    title_ext = os.path.splitext(final_base)[1].lower()
    if title_ext in (".csv", ".xlsx", ".xls", ".tsv", ".zip", ".pdf"):
        ext = title_ext
        final_base = final_base[: -len(title_ext)].rstrip(". ") or final_base
    if parsed["source_type"] == "google_sheet" and disposition:
        # Title came from a Drive confirm/download response: the disposition
        # filename is authoritative for the extension.
        disp_name = _filename_from_disposition(disposition)
        if disp_name:
            ext = os.path.splitext(disp_name)[1].lower() or ext
    if not ext:
        ext = ".bin"
    final_path = unique_path(files_dir, final_base, ext)
    os.replace(tmp_target, final_path)
    local_rel = FILES_SUBDIR + "/" + os.path.basename(final_path)

    digest = sha256_file(final_path)
    entry.update({
        "local_file": local_rel,
        "sha256": digest,
        "status": "downloaded",
        "downloaded_at": now_iso(),
        "error": None,
    })
    state["by_file_id"][fid_key] = entry
    print(f"        downloading -> {local_rel}")
    print(f"        SHA256: {digest[:16]}...")
    print("        OK")
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="download_gdrive_sources.py",
        description="Bulk download Google Drive / Sheets URLs into a dataset "
                    "directory with a provenance manifest.",
    )
    parser.add_argument("INPUT",
                        help="text file containing one Google URL per line")
    parser.add_argument("OUTPUT_DIR", help="dataset output directory")
    parser.add_argument("--format", choices=("xlsx", "csv"), default="xlsx",
                        help="Google Sheets export format (default: xlsx)")
    parser.add_argument("--force", action="store_true",
                        help="redownload existing successful items")
    parser.add_argument("--retries", type=int, default=3,
                        help="number of HTTP retries per request (default: 3)")
    args = parser.parse_args(argv)

    input_path = os.path.abspath(args.INPUT)
    out_dir = os.path.abspath(args.OUTPUT_DIR)
    files_dir = os.path.join(out_dir, FILES_SUBDIR)
    os.makedirs(files_dir, exist_ok=True)

    try:
        url_items = load_urls(input_path)
    except OSError as exc:
        print(f"error: cannot read input file: {exc}", file=sys.stderr)
        return 2
    if not url_items:
        print("error: no URLs found in input file", file=sys.stderr)
        return 2

    # Preserve the original list inside the dataset for provenance.
    input_copy = os.path.join(out_dir, "source_urls.txt")
    if os.path.abspath(input_copy) != input_path:
        shutil.copyfile(input_path, input_copy)

    manifest = load_manifest(out_dir)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "gdrive-bulk-downloader/1.0",
    })

    state = {"out_dir": out_dir, "files_dir": files_dir, "by_file_id": {}}
    # Index earlier successes (manifest + this run) for duplicate detection.
    # Prefer entries whose local file still exists ("skipped" entries were
    # hash-verified this run; older "downloaded" ones may predate a cleanup).
    for doc in manifest["documents"]:
        key = (doc.get("source_type"), doc.get("google_file_id"))
        if doc.get("status") not in ("downloaded", "skipped"):
            continue
        local = doc.get("local_file")
        if not local or not os.path.exists(
                os.path.join(out_dir, local.replace("/", os.sep))):
            continue
        if key not in state["by_file_id"]:
            state["by_file_id"][key] = doc

    total = len(url_items)
    failed_urls = []  # rate-limited URLs worth retrying after a cooldown

    def process_and_record(i, url, parsed, lineno=None):
        if parsed["source_type"] == "unknown":
            entry = new_entry(parsed, None)
            entry["error"] = (
                f"unrecognized URL format (line {lineno})" if lineno
                else "unrecognized URL format")
            print(f"\n[{i}/{total}] {url}")
            print(f"        FAILED: {entry['error']}")
        else:
            entry = process_url(i, total, parsed, manifest, session, args, state)
        # Replace any prior manifest entry for this exact URL (incremental).
        manifest["documents"] = [
            d for d in manifest["documents"]
            if d.get("source_url") != url
        ]
        manifest["documents"].append(entry)
        save_manifest(out_dir, manifest)
        return entry

    for i, (lineno, url) in enumerate(url_items, start=1):
        parsed = parse_google_url(url)
        entry = process_and_record(i, url, parsed, lineno)
        if (entry["status"] == "failed"
                and "rate limited" in str(entry.get("error") or "")):
            failed_urls.append(url)

    # Cooldown retry pass: Google's anonymous quota (HTTP 429/432) is
    # transient, so wait once and retry whatever was rate-limited.
    if failed_urls:
        wait_s = 120
        print(f"\n{len(failed_urls)} source(s) were rate limited; "
              f"cooling down {wait_s}s and retrying...")
        time.sleep(wait_s)
        for j, url in enumerate(list(failed_urls), start=1):
            parsed = parse_google_url(url)
            entry = process_and_record(f"R{j}/{len(failed_urls)}", url, parsed)
            if (entry["status"] == "failed"
                    and "rate limited" in str(entry.get("error") or "")):
                failed_urls.append(url)
            failed_urls.remove(url)

    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    for doc in manifest["documents"]:
        status = doc.get("status")
        if status in counts:
            counts[status] += 1

    print(f"\nCompleted: {total} sources")
    print(f"Downloaded: {counts['downloaded']}")
    print(f"Skipped:    {counts['skipped']}")
    print(f"Failed:     {counts['failed']}")
    print(f"Manifest:   {os.path.join(out_dir, MANIFEST_NAME)}")

    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
