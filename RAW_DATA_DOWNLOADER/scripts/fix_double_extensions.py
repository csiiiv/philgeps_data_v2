"""One-off cleanup: strip doubled extensions (e.g. .csv.csv) created by an
earlier run, rename the files, and update manifest.json to match.
Hashes are unchanged since file bytes are untouched."""

import json
import os
from manifest_utils import normalize_manifest

# Dataset lives one level above this script: RAW_DATA_DOWNLOADER/dataset
DATASET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset")
MANIFEST = os.path.join(DATASET, "manifest.json")
DOUBLED = (".csv.csv", ".xlsx.xlsx", ".xls.xls", ".tsv.tsv")

with open(MANIFEST, encoding="utf-8") as f:
    manifest = json.load(f)

renamed = 0
for doc in manifest["documents"]:
    lf = doc.get("local_file")
    if not lf or doc.get("status") != "downloaded":
        continue
    for dbl in DOUBLED:
        if lf.lower().endswith(dbl):
            new_name = lf[: -len(dbl)] + dbl[: -len(dbl) // 2]
            old_path = os.path.join(DATASET, lf.replace("/", os.sep))
            new_path = os.path.join(DATASET, new_name.replace("/", os.sep))
            if os.path.exists(old_path) and not os.path.exists(new_path):
                os.rename(old_path, new_path)
                doc["local_file"] = new_name
                renamed += 1
                print(f"renamed: {lf}  ->  {new_name}")
            break

normalize_manifest(manifest)
with open(MANIFEST, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

print(f"\n{renamed} file(s) renamed; manifest updated.")
