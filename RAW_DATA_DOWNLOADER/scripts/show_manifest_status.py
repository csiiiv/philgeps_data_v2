import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else r"dataset\manifest.json"
m = json.load(open(path, encoding="utf-8"))
docs = m["documents"]
print(f"manifest version: {m.get('version')}")
print(f"documents: {len(docs)}")
print(f"source files: {len(m.get('source_files', []))}")
for d in docs:
    status = d["status"]
    title = str(d["title"])[:55]
    err = d["error"] or ""
    lf = d["local_file"] or ""
    print(f"[{status:>10}] {title:<55} {lf}")
    if err:
        print(f"{'':>13}ERROR: {err}")
