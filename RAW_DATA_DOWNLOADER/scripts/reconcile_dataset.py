"""Idempotent dataset reconciler (two-pass):

Pass 1: fix every manifest reference whose local_file has a doubled
        extension (.csv.csv etc.) when the single-ext twin exists.
Pass 2: delete doubled-extension files on disk that are no longer
        referenced by any manifest entry, plus leftover temp files.
Pass 3: drop downloaded/skipped entries still pointing at missing files.
"""

import json
import os

from manifest_utils import normalize_manifest

# Dataset lives one level above this script: RAW_DATA_DOWNLOADER/dataset
DATASET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset")
MANIFEST = os.path.join(DATASET, "manifest.json")
DOUBLED = (".csv.csv", ".xlsx.xlsx", ".xls.xls", ".tsv.tsv")


def single_name(lf):
    for dbl in DOUBLED:
        if lf.lower().endswith(dbl):
            return lf[: -len(dbl)] + dbl[: -len(dbl) // 2]
    return None


with open(MANIFEST, encoding="utf-8") as f:
    manifest = json.load(f)

# Pass 1: fix references (no deletions yet).
fixed = 0
for doc in manifest["documents"]:
    lf = doc.get("local_file")
    if not lf or doc.get("status") not in ("downloaded", "skipped"):
        continue
    single = single_name(lf)
    if not single:
        continue
    if os.path.exists(os.path.join(DATASET, single.replace("/", os.sep))):
        doc["local_file"] = single
        fixed += 1
        print(f"ref fixed: {lf} -> {single}")

# Pass 2: delete orphaned doubled files and temp leftovers.
referenced = {
    doc.get("local_file")
    for doc in manifest["documents"]
    if doc.get("local_file")
}
files_dir = os.path.join(DATASET, "files")
removed = 0
for name in os.listdir(files_dir):
    p = os.path.join(files_dir, name)
    if not os.path.isfile(p):
        continue
    rel = "files/" + name
    if name.endswith((".part", ".downloading")):
        os.remove(p)
        print(f"removed temp: {name}")
        removed += 1
    elif single_name(rel) and rel not in referenced:
        single = single_name(rel)
        sp = os.path.join(DATASET, single.replace("/", os.sep))
        if os.path.exists(sp):
            os.remove(p)
            print(f"removed orphan: {name}")
            removed += 1
        else:
            os.rename(p, sp)
            print(f"renamed to unique: {name} -> {os.path.basename(single)}")

# Pass 3: drop entries pointing at missing files.
before = len(manifest["documents"])
kept = []
for doc in manifest["documents"]:
    lf = doc.get("local_file")
    if lf and doc.get("status") in ("downloaded", "skipped"):
        if not os.path.exists(os.path.join(DATASET, lf.replace("/", os.sep))):
            print(f"dropped stale: {lf} ({doc.get('title')})")
            continue
    kept.append(doc)
manifest["documents"] = kept
normalize_manifest(manifest)

with open(MANIFEST, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

print(f"\nrefs fixed: {fixed}, files removed: {removed}, "
      f"entries: {before} -> {len(manifest['documents'])}")
