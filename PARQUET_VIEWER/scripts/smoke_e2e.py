"""End-to-end smoke test: startup -> catalog -> search -> process -> provenance.

Assumes the viewer is running (default http://127.0.0.1:8765). Exercises the
researcher path end-to-end through the public HTTP API and prints PASS/FAIL
per step with a final exit code.

Usage (PowerShell, from PARQUET_VIEWER):
    python scripts\\smoke_e2e.py
    python scripts\\smoke_e2e.py --base-url http://127.0.0.1:9000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from urllib import error, parse, request

BASE_DEFAULT = "http://127.0.0.1:8765"
TIMEOUT_S = 120

results: list[tuple[str, bool, str]] = []


def get(base: str, path: str) -> tuple[int, dict]:
    req = request.Request(base + path, headers={"Accept": "application/json"})
    with request.urlopen(req, timeout=TIMEOUT_S) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def check(label: str, condition: bool, detail: str = "") -> bool:
    results.append((label, condition, detail))
    print(("PASS  " if condition else "FAIL  ") + label + (f" — {detail}" if detail else ""))
    return condition


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE_DEFAULT)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    # 1. Health
    try:
        status, body = get(base, "/api/health")
        check("health endpoint", status == 200)
    except error.URLError as exc:
        check("health endpoint", False, f"server unreachable: {exc}")
        return finish()

    # 2. Catalog with healthy datasets
    status, body = get(base, "/api/catalog")
    datasets = body.get("datasets", [])
    healthy = [d for d in datasets if d.get("status") == "healthy"]
    check(
        "catalog lists healthy datasets",
        status == 200 and len(healthy) > 0,
        f"{len(healthy)}/{len(datasets)} healthy",
    )

    # 3. Search returns process cards
    status, body = get(base, "/api/search?q=office+supplies")
    cards = body.get("procurements", [])
    check(
        "search returns procurement cards",
        status == 200 and len(cards) > 0,
        f"{len(cards)} cards, total={body.get('total')}",
    )

    # 4. Process summary (uses first card's process id)
    process_id = (cards[0] if cards else {}).get("process_id")
    if process_id:
        status, body = get(base, f"/api/processes/{process_id}/summary")
        check(
            "process summary resolves",
            status == 200 and body.get("process_id") == process_id,
            f"title={str(body.get('title'))[:60]!r}",
        )
        check(
            "summary carries timeline + quality flags",
            "timeline" in body and "quality_flags" in body,
        )
    else:
        check("process summary resolves", False, "no process_id from search")

    # 5. Party page with stats and contracts-by-year
    party = parse.quote("Gencorp Supplies Inc.")
    status, body = get(base, f"/api/parties/name/{party}")
    check(
        "party page returns stats",
        status == 200 and isinstance(body.get("stats"), dict),
    )
    check(
        "party page carries contracts_by_year",
        isinstance(body.get("contracts_by_year"), dict)
        and body["contracts_by_year"].get("available") is True,
    )

    # 6. Identity endpoint degrades gracefully
    status, body = get(base, f"/api/parties/name/{party}/identity")
    check(
        "identity endpoint answers (200)",
        status == 200 and "available" in body,
    )

    # 7. Release sources (provenance path): resolve a process' preferred
    # release via the process detail endpoint, then fetch its sources.
    release_id = None
    if process_id:
        try:
            status, body = get(base, f"/api/processes/{process_id}")
            release_id = body.get("preferred_release_id") if status == 200 else None
        except error.URLError:
            release_id = None
    if release_id:
        status, body = get(base, f"/api/releases/{release_id}/sources")
        check(
            "release sources resolve",
            status == 200 and isinstance(body, (list, dict)),
            f"release={release_id[:18]}…",
        )
    else:
        check("release sources resolve", False, "could not resolve a release_id")

    return finish()


def finish() -> int:
    failed = [r for r in results if not r[1]]
    print()
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    start = time.perf_counter()
    code = main()
    print(f"elapsed: {time.perf_counter() - start:.1f}s")
    sys.exit(code)
