"""One-off repair after an interrupted run:

1. For each manifest entry, if its local_file has a doubled extension
   (.csv.csv / .xlsx.xlsx) AND a single-ext twin with the same SHA-256
   exists, delete the doubled copy and point the manifest at the twin.
2. Remove any leftover *.downloading / *.part temp files.
3. Drop entries whose local file no longer exists (superseded copies).
"""

import hashlib
import json
import os
from manifest_utils import normalize_manifest

# Dataset lives one level above this script: RAW_DATA_DOWNLOADER/dataset
DATASET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset")
MANIFEST = os.path.join(DATASET, "manifest.json")
DOUBLED = (".csv.csv", ".xlsx.xlsx", ".xls.xls", ".tsv.tsv")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


with open(MANIFEST, encoding="utf-8") as f:
    manifest = json.load(f)

by_hash = {}
for name in os.listdir(os.path.join(DATASET, "files")):
    p = os.path.join(DATASET, "files", name)
    if os.path.isfile(p) and not name.endswith((".part", ".downloading")):
        base, ext = os.path.splitext(name)
        if ext in (".csv", ".xlsx", ".xls", ".tsv"):
            by_hash.setdefault((base, ext, sha256(p)), []).append(p)

seen_paths = set()
for doc in manifest["documents"]:
    lf = doc.get("local_file")
    if not lf or doc.get("status") not in ("downloaded", "skipped"):
        continue
    p = os.path.join(DATASET, lf.replace("/", os.sep))
    for dbl in DOUBLED:
        if lf.lower().endswith(dbl):
            single = lf[: -len(dbl)] + dbl[: -len(dbl) // 2]
            sp = os.path.join(DATASET, single.replace("/", os.sep))
            if os.path.exists(sp) and os.path.exists(p):
                if sha256(p) == sha256(sp):
                    os.remove(p)
                    doc["local_file"] = single
                    print(f"removed duplicate: {os.path.basename(p)}")
            elif os.path.exists(p):
                os.rename(p, sp)
                doc["local_file"] = single
                print(f"renamed: {lf} -> {single}")
            break

# Drop downloaded/skipped entries whose file vanished (superseded copies).
before = len(manifest["documents"])
kept = []
for doc in manifest["documents"]:
    lf = doc.get("local_file")
    if lf and doc.get("status") in ("downloaded", "skipped"):
        p = os.path.join(DATASET, lf.replace("/", os.sep))
        if not os.path.exists(p):
            print(f"dropping stale entry: {lf} ({doc.get('title')})")
            continue
    kept.append(doc)
manifest["documents"] = kept

# Remove temp leftovers.
files_dir = os.path.join(DATASET, "files")
for name in os.listdir(files_dir):
    if name.endswith((".part", ".downloading")):
        os.remove(os.path.join(files_dir, name))
        print(f"removed temp: {name}")

normalize_manifest(manifest)
with open(MANIFEST, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

print(f"\nmanifest: {before} -> {len(manifest['documents'])} entries")
