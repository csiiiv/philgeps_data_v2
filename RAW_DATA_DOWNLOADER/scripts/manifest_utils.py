"""Shared helpers for the version 2 provenance manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


MANIFEST_VERSION = 2
DEFAULT_NAME_MAP = (
    Path(__file__).resolve().parents[1] / "references" / "normalized_file_names.json"
)


def document_id_for(source_url):
    """Stable ID for one exact source URL entry."""
    if not source_url:
        return None
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    return "pgd_" + digest


def source_file_id_for(sha256):
    """Content-addressed ID for downloaded bytes."""
    if not sha256:
        return None
    return "pgf_" + sha256.lower()


def load_normalized_file_names(path=DEFAULT_NAME_MAP):
    """Load the explicit local-path to normalized-name mapping."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalize_manifest(manifest, normalized_file_names=None):
    """Upgrade a manifest in place and rebuild its unique source-file index."""
    if normalized_file_names is None:
        normalized_file_names = load_normalized_file_names()
    documents = manifest.setdefault("documents", [])
    seen_document_ids = set()
    source_files = {}

    for document in documents:
        document_id = document_id_for(document.get("source_url"))
        if document_id in seen_document_ids:
            raise ValueError(
                "manifest contains the same source_url more than once: "
                + str(document.get("source_url"))
            )
        if document_id:
            seen_document_ids.add(document_id)
        document["document_id"] = document_id

        source_file_id = source_file_id_for(document.get("sha256"))
        document["source_file_id"] = source_file_id
        if not source_file_id:
            continue

        item = source_files.setdefault(
            source_file_id,
            {
                "source_file_id": source_file_id,
                "sha256": document["sha256"].lower(),
                "local_files": [],
                "document_ids": [],
            },
        )
        local_file = document.get("local_file")
        if local_file and local_file not in item["local_files"]:
            item["local_files"].append(local_file)
        if document_id and document_id not in item["document_ids"]:
            item["document_ids"].append(document_id)

    for item in source_files.values():
        item["local_files"].sort()
        item["document_ids"].sort()
        mapped_names = {
            normalized_file_names[local_file]
            for local_file in item["local_files"]
            if local_file in normalized_file_names
        }
        if len(mapped_names) > 1:
            raise ValueError(
                f"one source_file_id has conflicting normalized names: {mapped_names}"
            )
        item["normalized_file_name"] = next(iter(mapped_names), None)

    manifest["version"] = MANIFEST_VERSION
    manifest["source_files"] = sorted(
        source_files.values(),
        key=lambda item: (item["local_files"] or [item["source_file_id"]])[0],
    )
    return manifest
