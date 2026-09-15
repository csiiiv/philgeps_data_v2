"""Deterministic identifiers and display breadcrumbs for source rows."""

from __future__ import annotations

import hashlib
from pathlib import Path


def make_source_row_id(
    source_file_sha256: str, physical_row_number: int, sheet_name: str | None = None
) -> str:
    """Return an immutable row ID tied to exact file bytes and visible row number."""
    if len(source_file_sha256) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in source_file_sha256
    ):
        raise ValueError("source_file_sha256 must be a 64-character hexadecimal digest")
    if physical_row_number < 1:
        raise ValueError("physical_row_number must be at least 1")
    identity = (
        source_file_sha256.lower()
        + "\0"
        + (sheet_name or "")
        + "\0"
        + str(physical_row_number)
    )
    return "pgr_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def make_source_breadcrumb(
    local_file: str, physical_row_number: int, sheet_name: str | None = None
) -> str:
    """Return the short source label intended for dashboard users."""
    if physical_row_number < 1:
        raise ValueError("physical_row_number must be at least 1")
    parts = [Path(local_file).name]
    if sheet_name:
        parts.append(sheet_name)
    parts.append(f"row {physical_row_number:,}")
    return " · ".join(parts)
