"""Saved views: versioned JSON view definitions rendered through the query API.

Per `docs/08_search_filter_and_common_views.md`, reusable review views are
configuration, not hardcoded pages: each definition names a dataset, filters,
projection, sort, grain label, and warning text. Reviewers can add validation
questions by editing `config/saved_views.json` — no new API endpoints.

Definitions are validated against the dataset registry at load time
(dataset and filter/sort columns must exist), so a stale view fails loudly
at startup instead of producing a confusing 400 at query time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .catalog import Catalog
from .config import Settings
from .query import FilterSpec, QueryError, SortSpec, TableQuery

VIEWS_ERROR_INVALID = "invalid_saved_views"


def _operator_wants_value(operator: str) -> bool:
    return operator not in {"is_null", "not_null"}


class SavedViewsService:
    def __init__(self, settings: Settings, catalog: Catalog):
        self.settings = settings
        self.catalog = catalog

    @property
    def _path(self) -> Path:
        return self.settings.project_root / "config" / "saved_views.json"

    def _load_raw(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"views_version": 1, "views": []}
        return json.loads(self._path.read_text(encoding="utf-8"))

    # -------------------------------------------------------------- listing

    def list_views(self) -> dict[str, Any]:
        """Return view definitions validated against the current registry."""
        raw = self._load_raw()
        snapshot = self.catalog.snapshot()
        columns_by_dataset = {
            item["name"]: {column["name"] for column in item["columns"]}
            for item in snapshot["datasets"]
            if item["status"] == "healthy"
        }
        views = []
        problems: list[str] = []
        for entry in raw.get("views", []):
            name = entry.get("name")
            dataset = entry.get("dataset")
            if not name or not dataset:
                problems.append(f"view missing name or dataset: {entry!r}")
                continue
            if dataset not in columns_by_dataset:
                problems.append(f"{name}: unknown dataset {dataset}")
                continue
            available = columns_by_dataset[dataset]
            for filter_spec in entry.get("filters", []):
                if filter_spec.get("column") not in available:
                    problems.append(f"{name}: unknown filter column {filter_spec.get('column')}")
            for sort_spec in entry.get("sort", []):
                if sort_spec.get("column") not in available:
                    problems.append(f"{name}: unknown sort column {sort_spec.get('column')}")
            for column in entry.get("columns") or []:
                if column not in available:
                    problems.append(f"{name}: unknown projection column {column}")
            views.append(self._normalize(entry))
        return {
            "views_version": raw.get("views_version", 1),
            "views": views,
            "problems": problems,
        }

    def _normalize(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": entry["name"],
            "label": entry.get("label") or entry["name"],
            "description": entry.get("description"),
            "dataset": entry["dataset"],
            "grain": entry.get("grain"),
            "warning": entry.get("warning"),
            "filters": [
                {key: value for key, value in item.items() if key in {"column", "operator", "value"}}
                for item in entry.get("filters", [])
            ],
            "filter_logic": entry.get("filter_logic", "and"),
            "columns": entry.get("columns"),
            "sort": entry.get("sort", []),
            "page_size": entry.get("page_size"),
        }

    # ------------------------------------------------------------ execution

    def as_query(self, view_name: str, limit: int | None = None) -> tuple[str, TableQuery]:
        """Compile a named view into a TableQuery for the query endpoint."""
        listing = self.list_views()
        match = next((v for v in listing["views"] if v["name"] == view_name), None)
        if match is None:
            raise QueryError(VIEWS_ERROR_INVALID, f"Unknown saved view: {view_name}")
        filters = [
            FilterSpec(
                column=item["column"],
                operator=item["operator"],
                value=item.get("value") if _operator_wants_value(item["operator"]) else None,
            )
            for item in match["filters"]
        ]
        sort = [SortSpec(column=item["column"], direction=item.get("direction", "asc"))
                for item in match["sort"]]
        request = TableQuery(
            columns=match["columns"],
            filters=filters,
            filter_logic=match["filter_logic"],  # type: ignore[arg-type]
            sort=sort,
            page_size=min(limit, match["page_size"]) if limit and match["page_size"]
            else (limit or match["page_size"]),
        )
        return match["dataset"], request
