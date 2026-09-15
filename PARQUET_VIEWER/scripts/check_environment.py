"""Pre-start dependency and data check for the PhilGEPS Parquet Viewer.

Run from PARQUET_VIEWER:  python scripts\\check_environment.py
Exits 0 when the environment can serve the viewer; exits 1 with a
researcher-readable list of problems otherwise. Read-only: never writes or
modifies data.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
REQUIRED_MODULES = ["fastapi", "uvicorn", "duckdb", "pydantic"]
REQUIRED_DATASETS = [
    "tenders",
    "awards",
    "contracts",
    "parties",
    "releases",
    "compiled_processes",
]

problems: list[str] = []
warnings: list[str] = []

# --- Python modules -------------------------------------------------------
for module in REQUIRED_MODULES:
    if importlib.util.find_spec(module) is None:
        problems.append(f"Missing Python package '{module}' (pip install {module})")

# --- Settings file --------------------------------------------------------
settings_path = PROJECT / "config" / "settings.json"
if not settings_path.exists():
    problems.append(f"Missing settings file: {settings_path}")
else:
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        problems.append(f"Settings file is not valid JSON: {error}")
        settings = None
    if settings is not None:
        # Resolve the parquet directory the same way the app does: relative
        # paths resolve against the project root (settings.json's parent's
        # parent).
        raw = settings.get("parquet_directory") or settings.get("parquets")
        if not raw:
            problems.append("settings.json has no 'parquet_directory' entry")
        else:
            parquet_dir = Path(raw)
            if not parquet_dir.is_absolute():
                parquet_dir = (PROJECT / parquet_dir).resolve()
            if not parquet_dir.exists():
                problems.append(f"Parquet directory not found: {parquet_dir}")
            else:
                found = {p.stem for p in parquet_dir.glob("*.parquet")}
                missing = [d for d in REQUIRED_DATASETS if d not in found]
                if missing:
                    problems.append(
                        "Missing required datasets in "
                        f"{parquet_dir}: {', '.join(sorted(missing))}"
                    )
                optional = sorted(found - set(REQUIRED_DATASETS))
                if optional:
                    warnings.append(
                        f"{len(optional)} additional datasets present "
                        f"({', '.join(optional[:5])}"
                        + (", …" if len(optional) > 5 else "")
                        + ")"
                    )

# --- Frontend build -------------------------------------------------------
dist = PROJECT / "frontend" / "dist" / "index.html"
if not dist.exists():
    warnings.append(
        "No frontend build found (frontend/dist/index.html). "
        "Run: cd frontend/app && npm run build"
    )

# --- Report ---------------------------------------------------------------
if warnings:
    print("Warnings:")
    for warning in warnings:
        print(f"  ~ {warning}")
if problems:
    print("Problems (must fix before starting):")
    for problem in problems:
        print(f"  x {problem}")
    sys.exit(1)
print("Environment OK: packages, settings, and datasets present.")
