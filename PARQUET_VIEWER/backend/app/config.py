"""Application settings with project-contained writable paths."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_from_project(value: str) -> Path:
    return (PROJECT_ROOT / value).resolve()


@dataclass(frozen=True)
class DuckDBSettings:
    memory_limit: str
    threads: int
    max_concurrent_queries: int
    # Ceiling for the one-shot disposable-projection builds (search index,
    # provenance cache). Separate from `memory_limit` because builds are
    # batch jobs: on small VPS boxes they get their own (often larger)
    # budget while the interactive query pool stays small, and the build
    # thread serializes against the query pool either way.
    build_memory_limit: str | None = None


@dataclass(frozen=True)
class APISettings:
    default_page_size: int
    maximum_page_size: int
    export_row_limit: int
    query_timeout_seconds: float
    cursor_secret: str
    allowed_hosts: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    project_root: Path
    parquet_directory: Path
    normalized_parquet: Path
    cleaned_parquet: Path
    manifest: Path
    cache_directory: Path
    duckdb: DuckDBSettings
    api: APISettings


def _merge_allowed_hosts(configured: list[str]) -> tuple[str, ...]:
    """Merge settings hosts with optional PHILGEPS_EXTRA_ALLOWED_HOSTS.

    Comma-separated extras let a network launch script allow the current LAN
    IP and hostname without editing settings.json.
    """
    hosts: list[str] = []
    for value in [*configured, *os.environ.get("PHILGEPS_EXTRA_ALLOWED_HOSTS", "").split(",")]:
        host = value.strip()
        if host and host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def load_settings(path: Path | None = None) -> Settings:
    """Load settings; relative paths resolve against the settings file's project.

    Passing a custom settings path (as the fixture tests do) makes that file's
    project root authoritative for all data-path resolution.
    """
    path = (path or PROJECT_ROOT / "config" / "settings.json").resolve()
    root = path.parents[1]

    def resolve(value: str) -> Path:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        return candidate.resolve()

    raw = json.loads(path.read_text(encoding="utf-8"))
    cache = resolve(raw["cache_directory"])
    if root not in (cache, *cache.parents):
        raise ValueError("cache_directory must stay within the viewer project")
    duckdb_raw = raw["duckdb"]
    api_raw = raw["api"]
    return Settings(
        project_root=root,
        parquet_directory=resolve(raw["parquet_directory"]),
        normalized_parquet=resolve(raw["normalized_parquet"]),
        cleaned_parquet=resolve(raw["cleaned_parquet"]),
        manifest=resolve(raw["manifest"]),
        cache_directory=cache,
        duckdb=DuckDBSettings(
            memory_limit=str(duckdb_raw["memory_limit"]),
            threads=max(1, int(duckdb_raw["threads"])),
            max_concurrent_queries=max(1, int(duckdb_raw["max_concurrent_queries"])),
            build_memory_limit=(
                str(duckdb_raw["build_memory_limit"])
                if duckdb_raw.get("build_memory_limit") is not None
                else None
            ),
        ),
        api=APISettings(
            default_page_size=int(api_raw["default_page_size"]),
            maximum_page_size=int(api_raw["maximum_page_size"]),
            export_row_limit=int(api_raw["export_row_limit"]),
            query_timeout_seconds=float(api_raw.get("query_timeout_seconds", 60.0)),
            cursor_secret=str(
                os.environ.get("PHILGEPS_CURSOR_SECRET")
                or api_raw.get("cursor_secret", "")
            ),
            allowed_hosts=_merge_allowed_hosts(list(api_raw["allowed_hosts"])),
        ),
    )
