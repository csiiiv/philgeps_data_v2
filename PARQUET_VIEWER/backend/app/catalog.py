"""Schema-checked registry and dataset fingerprint."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

from .config import Settings
from .database import DuckDBPool, sql_literal_path


@dataclass(frozen=True)
class DatasetDefinition:
    name: str
    file: str
    primary_key: tuple[str, ...]
    record_type: str | None
    warning: str | None


class Catalog:
    def __init__(self, settings: Settings, pool: DuckDBPool):
        self.settings = settings
        self.pool = pool
        self._lock = Lock()
        self._snapshot: dict[str, Any] | None = None
        registry_path = settings.project_root / "config" / "datasets.json"
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
        self.registry_version = int(raw["registry_version"])
        self.definitions = tuple(
            DatasetDefinition(
                name=item["name"],
                file=item["file"],
                primary_key=tuple(item["primary_key"]),
                record_type=item.get("record_type"),
                warning=item.get("warning"),
            )
            for item in raw["datasets"]
        )
        names = [item.name for item in self.definitions]
        if len(names) != len(set(names)):
            raise ValueError("dataset registry contains duplicate names")

    def snapshot(self, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._snapshot is None or refresh:
                self._snapshot = self._build_snapshot()
            return self._snapshot

    def _build_snapshot(self) -> dict[str, Any]:
        datasets: list[dict[str, Any]] = []
        fingerprint_parts: list[dict[str, Any]] = []
        with self.pool.connection() as connection:
            for definition in self.definitions:
                path = (self.settings.parquet_directory / definition.file).resolve()
                item: dict[str, Any] = {
                    "name": definition.name,
                    "file": definition.file,
                    "primary_key": list(definition.primary_key),
                    "record_type": definition.record_type,
                    "warning": definition.warning,
                    "path": str(path),
                }
                if not path.exists():
                    item.update(status="missing", row_count=None, size_bytes=None, columns=[])
                    datasets.append(item)
                    fingerprint_parts.append({"name": definition.name, "status": "missing"})
                    continue
                try:
                    relation = f"read_parquet({sql_literal_path(path)})"
                    described = connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
                    columns = [
                        {"name": row[0], "type": row[1], "nullable": row[2] == "YES"}
                        for row in described
                    ]
                    column_names = {column["name"] for column in columns}
                    missing_keys = [key for key in definition.primary_key if key not in column_names]
                    row_count = connection.execute(
                        "SELECT sum(num_rows)::BIGINT FROM parquet_file_metadata(?)", [str(path)]
                    ).fetchone()[0]
                    stat = path.stat()
                    schema_hash = hashlib.sha256(
                        json.dumps(columns, sort_keys=True).encode("utf-8")
                    ).hexdigest()
                    status = "healthy" if not missing_keys else "schema_mismatch"
                    item.update(
                        status=status,
                        row_count=row_count,
                        size_bytes=stat.st_size,
                        modified_ns=stat.st_mtime_ns,
                        schema_hash=schema_hash,
                        columns=columns,
                        missing_primary_key_columns=missing_keys,
                    )
                    fingerprint_parts.append({
                        "name": definition.name,
                        "size": stat.st_size,
                        "modified_ns": stat.st_mtime_ns,
                        "rows": row_count,
                        "schema_hash": schema_hash,
                    })
                except Exception as error:  # surfaced as health data, not hidden
                    item.update(
                        status="error", row_count=None, size_bytes=path.stat().st_size,
                        columns=[], error=f"{type(error).__name__}: {error}"
                    )
                    fingerprint_parts.append({"name": definition.name, "status": "error"})
                datasets.append(item)

        manifest = self._manifest_status()
        source_layers = self._source_layer_status()
        fingerprint_payload = {
            "registry_version": self.registry_version,
            "datasets": fingerprint_parts,
            "manifest": manifest.get("fingerprint"),
            "source_layers": source_layers,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        healthy = all(item["status"] == "healthy" for item in datasets)
        healthy = healthy and manifest["status"] == "healthy"
        healthy = healthy and all(item["status"] == "healthy" for item in source_layers)
        return {
            "status": "healthy" if healthy else "degraded",
            "dataset_fingerprint": fingerprint,
            "registry_version": self.registry_version,
            "dataset_count": len(datasets),
            "datasets": datasets,
            "manifest": manifest,
            "source_layers": source_layers,
        }

    def _manifest_status(self) -> dict[str, Any]:
        path = self.settings.manifest
        if not path.exists():
            return {"status": "missing", "path": str(path), "fingerprint": None}
        raw_bytes = path.read_bytes()
        try:
            manifest = json.loads(raw_bytes)
            return {
                "status": "healthy" if manifest.get("version") == 2 else "schema_mismatch",
                "path": str(path),
                "version": manifest.get("version"),
                "document_count": len(manifest.get("documents", [])),
                "source_file_count": len(manifest.get("source_files", [])),
                "fingerprint": hashlib.sha256(raw_bytes).hexdigest(),
            }
        except json.JSONDecodeError as error:
            return {
                "status": "error", "path": str(path), "fingerprint": None,
                "error": f"JSONDecodeError: {error}"
            }

    def _source_layer_status(self) -> list[dict[str, Any]]:
        result = []
        for name, path in (
            ("normalized", self.settings.normalized_parquet),
            ("cleaned", self.settings.cleaned_parquet),
        ):
            if not path.exists():
                result.append({"name": name, "status": "missing", "path": str(path)})
                continue
            stat = path.stat()
            result.append({
                "name": name, "status": "healthy", "path": str(path),
                "size_bytes": stat.st_size, "modified_ns": stat.st_mtime_ns,
            })
        return result
