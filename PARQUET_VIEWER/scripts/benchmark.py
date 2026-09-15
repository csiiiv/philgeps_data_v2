"""Repeatable latency benchmark harness for the viewer's hot paths.

Doc 11 (§22 / Phase 1 step 1) requires measured baselines before any new
projection is designed. This script drives the real FastAPI app in-process
(TestClient), so results include serialization but not network overhead.

Each case runs cold once (fresh process, real file reads) and warm
(repeated). Latency targets are defined in docs/12_benchmark_baseline.md and
encoded in TARGETS below; failures exit non-zero so CI can adopt this later.

Usage:
    python scripts/benchmark.py             # run all cases, print table
    python scripts/benchmark.py --json out.json
    python scripts/benchmark.py --quick     # skip the slowest cold cases
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

TARGETS = {  # seconds; None = record-only, no target yet
    "health": 0.05,
    "catalog": 0.5,
    "search_common_cold": None,
    "search_common_warm": 2.0,
    "search_facets": 0.5,
    "party_page": 2.0,
    "party_identity": 2.0,
    "process_summary_cold": 5.0,
    "process_summary_warm": 0.25,
    "process_detail": 2.0,
    "process_timeline": 2.0,
    "view_counts": 3.0,
    "table_query_page": 1.0,
}

WARM_REPEATS = 5


def _pick_process(client) -> tuple[str, str]:
    """Return (process_id, release_id) from a common-term search hit."""
    payload = client.get("/api/search", params={"q": "school"}).json()
    for card in payload.get("procurements", []) or []:
        pid = card.get("process_id")
        if pid:
            detail = client.get(f"/api/processes/{pid}").json()
            rid = (detail.get("preferred_release") or {}).get("release_id") or ""
            return pid, rid
    raise SystemExit("benchmark could not find a process via search; cannot continue")


def run_case(client, label: str, method: str, path: str, **kwargs):
    """Call once (cold timing) then WARM_REPEATS times (warm stats)."""
    t0 = time.perf_counter()
    response = client.request(method, path, **kwargs)
    cold = time.perf_counter() - t0
    ok = response.status_code == 200
    if not ok:
        print(f"  !! {label} returned {response.status_code}: {path}")

    warm_samples = []
    for _ in range(WARM_REPEATS):
        t0 = time.perf_counter()
        r = client.request(method, path, **kwargs)
        warm_samples.append(time.perf_counter() - t0)
        ok = ok and r.status_code == 200

    target = TARGETS.get(label)
    warm_median = statistics.median(warm_samples)
    meets_target = target is None or warm_median <= target
    return {
        "label": label,
        "path": path,
        "cold_s": round(cold, 3),
        "warm_median_s": round(warm_median, 3),
        "warm_max_s": round(max(warm_samples), 3),
        "target_s": target,
        "ok": ok and meets_target,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None, help="also write results JSON")
    parser.add_argument("--quick", action="store_true", help="skip multi-second cold cases")
    args = parser.parse_args()

    from fastapi.testclient import TestClient

    from app.main import create_app

    t0 = time.perf_counter()
    app = create_app()
    print(f"app built in {time.perf_counter() - t0:.1f}s (index build may be deferred)")
    results = []
    with TestClient(app) as client:
        pid, rid = _pick_process(client)
        print(f"warm reference process: {pid}")

        # Order matters: health/catalog are trivially cacheable, then search
        # (which may build the index), then per-object pages (which reuse it).
        cases = [
            ("health", "GET", "/api/health"),
            ("catalog", "GET", "/api/catalog"),
            ("search_common_cold", "GET", "/api/search", {"params": {"q": "school"}}),
            ("search_common_warm", "GET", "/api/search", {"params": {"q": "school"}}),
            ("search_facets", "GET", "/api/search/facets"),
            ("party_page", "GET", "/api/parties/name/DIGITAL INTERFACE INC."),
            ("party_identity", "GET", "/api/parties/name/DIGITAL INTERFACE INC./identity"),
            ("process_summary_cold", "GET", f"/api/processes/{pid}/summary"),
            ("process_summary_warm", "GET", f"/api/processes/{pid}/summary"),
            ("process_detail", "GET", f"/api/processes/{pid}"),
            ("process_timeline", "GET", f"/api/processes/{pid}/timeline"),
            ("view_counts", "GET", "/api/views/counts"),
            ("table_query_page", "POST", "/api/tables/tenders/query",
             {"json": {"page_size": 50}}),
        ]
        for case in cases:
            label, method, path = case[0], case[1], case[2]
            kwargs = case[3] if len(case) > 3 else {}
            if args.quick and label in ("view_counts",):
                continue
            print(f"  running {label} ...", flush=True)
            results.append(run_case(client, label, method, path, **kwargs))

    met = sum(1 for r in results if r["ok"])
    print(f"\n{'case':<24}{'cold':>9}{'warm med':>10}{'warm max':>10}{'target':>9}  status")
    for r in results:
        t = "-" if r["target_s"] is None else f"{r['target_s']:.2f}"
        mark = "PASS" if r["ok"] else "MISS"
        print(f"{r['label']:<24}{r['cold_s']:>9.3f}{r['warm_median_s']:>10.3f}"
              f"{r['warm_max_s']:>10.3f}{t:>9}  {mark}")
    print(f"\n{met}/{len(results)} cases at or under target")

    if args.json:
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"results written to {args.json}")
    return 0 if met == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
