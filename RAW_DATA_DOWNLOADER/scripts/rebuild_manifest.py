#!/usr/bin/env python3
"""Upgrade dataset/manifest.json and rebuild its unique source-file registry."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from manifest_utils import normalize_manifest


def main():
    default_manifest = Path(__file__).resolve().parents[1] / "dataset" / "manifest.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, default=default_manifest)
    args = parser.parse_args()
    path = args.manifest.resolve()
    manifest = normalize_manifest(json.loads(path.read_text(encoding="utf-8")))

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)

    print(f"manifest version: {manifest['version']}")
    print(f"documents: {len(manifest['documents'])}")
    print(f"source files: {len(manifest['source_files'])}")
    print(f"updated: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

