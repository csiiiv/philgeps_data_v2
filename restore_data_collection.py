#!/usr/bin/env python3
"""Restore the DATA_COLLECTION archive into the canonical pipeline layout.

The shared ``DATA_COLLECTION`` archive carries every generated dataset
(20 Parquet files + the provenance manifest). The viewer and the ETL stages
expect those files at fixed *relative* locations inside the repo (see
``PARQUET_VIEWER/config/settings.json``). This script puts them there.

Data files are MOVED (use ``--keep-source`` to copy instead):

    philgeps_normalized.parquet      -> DATA_NORMALIZATION/output/
    philgeps_cleaned.parquet         -> DATA_NORMALIZATION/output/
    ocds_star_schema/<table>.parquet -> OCDS_ETL/outputs/parquet/   (18 tables)
    manifest/manifest.json           -> RAW_DATA_DOWNLOADER/dataset/

Git-tracked copies (``mapping/``, ``manifest/source_urls.txt``, ``docs/``)
are hash-compared against the repo checkout and REPORTED ONLY - git is
authoritative and is never overwritten by this script.

All paths are resolved relative to this script's location (the repo root),
never the current working directory, so it runs identically on
Windows / macOS / Linux. Stdlib only; no third-party dependencies.

Exit codes
    0  success (possibly after skips)
    2  archive missing or incomplete
    3  conflicts detected (nothing overwritten without --force)

Examples
    # Preview the plan; change nothing
    python restore_data_collection.py --dry-run

    # Move the data into place
    python restore_data_collection.py

    # Copy instead of move, write a machine-readable report
    python restore_data_collection.py --keep-source --report restore_report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

# --- Layout -----------------------------------------------------------------

STAR_TABLES = [
    "awards", "award_items", "award_suppliers", "canonical_parties",
    "compiled_processes", "contracting_processes", "contracts",
    "data_quality_issues", "parties", "party_aliases", "party_name_forms",
    "party_resolution_candidates", "party_roles", "process_release_history",
    "record_sources", "releases", "tenders", "tender_items",
]

# (archive-relative source, repo-relative target)
TRANSFERS = [
    ("philgeps_normalized.parquet",
     "DATA_NORMALIZATION/output/philgeps_normalized.parquet"),
    ("philgeps_cleaned.parquet",
     "DATA_NORMALIZATION/output/philgeps_cleaned.parquet"),
    *[("ocds_star_schema/{}.parquet".format(t),
       "OCDS_ETL/outputs/parquet/{}.parquet".format(t))
      for t in STAR_TABLES],
    ("manifest/manifest.json",
     "RAW_DATA_DOWNLOADER/dataset/manifest.json"),
]

# Git-tracked counterparts: hash-compared, never overwritten here.
TRACKED_CHECKS = [
    ("manifest/source_urls.txt",
     "RAW_DATA_DOWNLOADER/references/source_urls_4.txt"),
    ("mapping/schema_registry.json",
     "DATA_NORMALIZATION/config/schema_registry.json"),
    ("mapping/field_mapping.json",
     "OCDS_ETL/config/field_mapping.json"),
    ("mapping/codelist_mapping.json",
     "OCDS_ETL/config/codelist_mapping.json"),
    ("mapping/UNIFIED_exports_OCDS_Field_Mapping_FILLED.xlsx",
     "OCDS_ETL/artifacts/filled_templates/UNIFIED_exports_OCDS_Field_Mapping_FILLED.xlsx"),
    ("mapping/UNIFIED_exports_OCDS_Codelist_Mapping_FILLED.xlsx",
     "OCDS_ETL/artifacts/filled_templates/UNIFIED_exports_OCDS_Codelist_Mapping_FILLED.xlsx"),
    ("docs/DATA_OUTPUTS.md", "DATA_OUTPUTS.md"),
    ("docs/README.md", "README.md"),
]

CHUNK = 4 * 1024 * 1024


# --- Helpers ----------------------------------------------------------------

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def same_file(a: Path, b: Path) -> bool:
    """True when both paths are hardlinks to the same physical file.

    The DATA_COLLECTION staging area on the build machine used NTFS
    hardlinks, so this short-circuits hashing multi-GB files. Works on
    Windows (NTFS file index), macOS, and Linux via st_dev/st_ino.
    """
    try:
        sa, sb = a.stat(), b.stat()
    except OSError:
        return False
    return (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino)


def fmt_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return "{:.2f} {}".format(size, unit) if unit != "B" else "{} B".format(int(size))
        size /= 1024
    return "{:.2f} TB".format(size)


# --- Plan -------------------------------------------------------------------

def build_plan(archive: Path, root: Path, force: bool, keep_source: bool) -> list:
    plan = []
    conflicts = 0

    for rel_source, rel_target in TRANSFERS:
        source = archive / rel_source
        target = root / rel_target
        entry = {
            "source": rel_source, "target": rel_target,
            "source_path": source, "target_path": target,
            "bytes": source.stat().st_size,
            "action": "transfer", "note": "", "source_hash": None,
        }

        if target.exists():
            if same_file(source, target):
                # Hardlink to the same physical file: identical by definition.
                entry["action"] = "skip" if keep_source else "skip-delete-source"
                entry["note"] = "target is a hardlink to the same file"
            elif target.stat().st_size != entry["bytes"]:
                if force:
                    entry["action"] = "overwrite"
                    entry["note"] = "target differs in size; --force given"
                else:
                    entry["action"] = "conflict"
                    entry["note"] = "target exists and differs in size; rerun with --force"
                    conflicts += 1
            else:
                entry["source_hash"] = sha256(source)
                if entry["source_hash"] == sha256(target):
                    entry["action"] = "skip" if keep_source else "skip-delete-source"
                    entry["note"] = "target already identical"
                elif force:
                    entry["action"] = "overwrite"
                    entry["note"] = "target content differs; --force given"
                else:
                    entry["action"] = "conflict"
                    entry["note"] = "target exists with different content; rerun with --force"
                    conflicts += 1
        plan.append(entry)

    return plan, conflicts


def execute(entry: dict, keep_source: bool, verify_hash: bool) -> None:
    source, target = entry["source_path"], entry["target_path"]
    action = entry["action"]

    if action == "skip":
        return
    if action == "skip-delete-source":
        source.unlink()
        return

    # action in ("transfer", "overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)

    if not keep_source:
        # Rename is atomic and instant on the same filesystem and replaces
        # any existing target; fall back to copy only across devices.
        try:
            os.replace(source, target)
            return
        except OSError:
            pass

    shutil.copy2(source, target)   # copy2 overwrites an existing target
    if target.stat().st_size != entry["bytes"]:
        raise RuntimeError("size mismatch after copy: {}".format(target))
    if verify_hash:
        if not entry["source_hash"]:
            entry["source_hash"] = sha256(source)
        if sha256(target) != entry["source_hash"]:
            raise RuntimeError("hash mismatch after copy: {}".format(target))
    if not keep_source:
        source.unlink()


# --- Main -------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restore the DATA_COLLECTION archive into the canonical "
                    "pipeline layout (relative paths, cross-platform).")
    parser.add_argument("--archive-dir", default="DATA_COLLECTION",
                        help="archive folder, relative to the repo root "
                             "(default: DATA_COLLECTION)")
    parser.add_argument("--repo-root", default=None,
                        help="override repo root for testing (default: this "
                             "script's directory)")
    parser.add_argument("--keep-source", action="store_true",
                        help="copy instead of move; archive stays intact")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing targets whose content differs")
    parser.add_argument("--verify-hashes", action="store_true",
                        help="SHA-256-verify every copied file (renames and "
                             "hardlinks are verified by construction)")
    parser.add_argument("--dry-run", action="store_true",
                        help="preview the plan; change nothing")
    parser.add_argument("--report", metavar="PATH", default=None,
                        help="write a JSON report of the run to PATH")
    args = parser.parse_args(argv)

    root = (Path(args.repo_root) if args.repo_root
            else Path(__file__).resolve().parent).resolve()
    archive = Path(args.archive_dir)
    if not archive.is_absolute():
        archive = root / archive
    archive = archive.resolve()

    print("repo root : {}".format(root))
    print("archive   : {}".format(archive))
    print("mode      : {}{}".format("copy" if args.keep_source else "move",
                                    " + hash verification" if args.verify_hashes else ""))
    print()

    # -- Validate archive ----------------------------------------------------
    if not archive.is_dir():
        print("ERROR archive directory not found: {} "
              "(extract the DATA_COLLECTION archive first, or pass --archive-dir)"
              .format(archive), file=sys.stderr)
        return 2
    missing = [rel for rel, _ in TRANSFERS if not (archive / rel).is_file()]
    if missing:
        print("ERROR archive is incomplete - {} missing file(s):".format(len(missing)),
              file=sys.stderr)
        for rel in missing:
            print("  {}".format(rel), file=sys.stderr)
        return 2

    # -- Plan ----------------------------------------------------------------
    plan, conflicts = build_plan(archive, root, args.force, args.keep_source)

    moved = skipped = 0
    moved_bytes = 0
    for entry in plan:
        action, label = entry["action"], entry["target"]
        if action in ("skip", "skip-delete-source"):
            skipped += 1
        elif action in ("transfer", "overwrite"):
            moved += 1
            moved_bytes += entry["bytes"]
        if args.dry_run:
            future = {
                "transfer": "would transfer", "overwrite": "would overwrite",
                "skip": "skip", "skip-delete-source": "skip (would drop archive copy)",
                "conflict": "CONFLICT",
            }[action]
            print("  [{:>28}] {} ({}){}".format(
                future, label, fmt_bytes(entry["bytes"]),
                " - {}".format(entry["note"]) if entry["note"] else ""))
        else:
            if action in ("transfer", "overwrite"):
                execute(entry, args.keep_source, args.verify_hashes)
                print("  [{:>9}] {} ({})".format(
                    "overwrote" if action == "overwrite" else "moved",
                    label, fmt_bytes(entry["bytes"])))
            elif action in ("skip", "skip-delete-source"):
                execute(entry, args.keep_source, args.verify_hashes)
                print("  [{:>9}] {} - {}".format("skip", label, entry["note"]))
            else:
                print("  [{:>9}] {} - {}".format("CONFLICT", label, entry["note"]))

    # -- Git-tracked counterparts ---------------------------------------------
    print()
    print("git-tracked counterparts (reported only - git is authoritative):")
    tracked_match = tracked_differ = 0
    tracked_report = []
    for rel_source, rel_target in TRACKED_CHECKS:
        source, target = archive / rel_source, root / rel_target
        if not source.is_file():
            status = "absent "
            detail = "not in archive"
        elif not target.is_file():
            status = "MISSING"
            detail = "not in repo checkout"
            tracked_differ += 1
        elif sha256(source) == sha256(target):
            status = "match  "
            detail = ""
            tracked_match += 1
        else:
            status = "DIFFERS"
            detail = "repo copy and archive copy differ; git copy wins"
            tracked_differ += 1
        line = "  [{}] {}{}".format(status, rel_target,
                                    " - {}".format(detail) if detail else "")
        print(line)
        tracked_report.append({"archive": rel_source, "repo": rel_target,
                               "status": status.strip()})

    # -- Summary ----------------------------------------------------------------
    status = "conflicts" if conflicts else "ok"
    print()
    print("RESTORE_SUMMARY status={} transfers={} skips={} conflicts={} "
          "tracked_match={} tracked_differ={} bytes={}".format(
              status, moved, skipped, conflicts,
              tracked_match, tracked_differ, moved_bytes))

    if args.report:
        report = {
            "status": status,
            "dry_run": args.dry_run,
            "repo_root": str(root),
            "archive": str(archive),
            "summary": {"transfers": moved, "skips": skipped,
                        "conflicts": conflicts, "bytes_moved": moved_bytes,
                        "tracked_match": tracked_match,
                        "tracked_differ": tracked_differ},
            "plan": [{k: (str(v) if isinstance(v, Path) else v)
                      for k, v in entry.items()} for entry in plan],
            "tracked": tracked_report,
        }
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("report written to {}".format(args.report))

    if conflicts:
        print("nothing was overwritten; re-run with --force to replace the "
              "conflicting targets", file=sys.stderr)
        return 3

    if not args.dry_run:
        print()
        print("next steps:")
        print("  start viewer:  cd PARQUET_VIEWER && "
              "python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8765")
        print("  health check:  curl http://127.0.0.1:8765/api/health")
        print("  backend tests: python -m unittest discover -s PARQUET_VIEWER/backend/tests")
        print("notes:")
        print("  - raw source downloads are NOT in the archive (manifest only);")
        print("    re-run stage 0 to rebuild them (see RAW_DATA_DOWNLOADER/README.md)")
        print("  - OCDS_ETL build intermediates (outputs/.build) are not archived;")
        print("    re-run OCDS_ETL scripts to rebuild the star schema from scratch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
