"""Read-only local API and initial catalog surface."""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .catalog import Catalog
from .config import Settings, load_settings
from .coverage import SourceCoverageService
from .database import DuckDBPool
from .outcomes import OutcomesService
from .provenance import ProvenanceCache
from .process import ProcessService
from .query import QueryError, TableQuery, TableQueryService, to_csv
from .search import SearchService
from .trace import TraceabilityService
from .views import SavedViewsService


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application, optionally against custom settings.

    The default module-level `app` uses production settings; tests build
    fixture-backed apps through this factory.
    """
    settings = settings or load_settings()
    pool = DuckDBPool(settings)
    catalog = Catalog(settings, pool)
    queries = TableQueryService(settings, pool, catalog)
    provenance = ProvenanceCache(settings, None)
    traces = TraceabilityService(settings, pool, catalog, provenance=provenance)
    processes = ProcessService(settings, pool, catalog)
    saved_views = SavedViewsService(settings, catalog)
    search = SearchService(settings, pool, catalog)
    outcomes = OutcomesService(settings, pool, catalog, search.index)
    coverage = SourceCoverageService(settings, pool, catalog, search.index)
    # Saved-view counts are expensive (full-filter scans); memoize per
    # dataset fingerprint, keeping only the latest snapshot's entry.
    _counts_cache: OrderedDict[str, dict] = OrderedDict()

    app = FastAPI(
        title="PhilGEPS Parquet Viewer",
        description="Read-only validation API for normalized and OCDS-aligned Parquets.",
        version="0.1.0",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.api.allowed_hosts))

    @app.middleware("http")
    async def validate_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin:
            hostname = urlparse(origin).hostname
            if hostname not in settings.api.allowed_hosts:
                return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
        return await call_next(request)

    @app.get("/api/health")
    def health(refresh: bool = Query(default=False)):
        snapshot = catalog.snapshot(refresh=refresh)
        return {
            "status": snapshot["status"],
            "dataset_fingerprint": snapshot["dataset_fingerprint"],
            "dataset_count": snapshot["dataset_count"],
            "healthy_datasets": sum(
                item["status"] == "healthy" for item in snapshot["datasets"]
            ),
            "manifest": snapshot["manifest"],
            "source_layers": snapshot["source_layers"],
        }

    @app.get("/api/catalog")
    def get_catalog(refresh: bool = Query(default=False)):
        return catalog.snapshot(refresh=refresh)

    @app.get("/api/tables/{table_name}/schema")
    def table_schema(table_name: str):
        snapshot = catalog.snapshot()
        item = next(
            (entry for entry in snapshot["datasets"] if entry["name"] == table_name), None
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Unknown dataset")
        return item

    @app.post("/api/tables/{table_name}/query")
    def query_table(table_name: str, request: TableQuery):
        try:
            return queries.execute(table_name, request)
        except QueryError as error:
            status = 404 if error.code in {"unknown_dataset", "dataset_not_queryable"} else 400
            raise HTTPException(
                status_code=status, detail={"code": error.code, "message": str(error)}
            ) from error
        except KeyError as error:
            raise HTTPException(
                status_code=404, detail={"code": "unknown_dataset", "message": str(error)}
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail={"code": "invalid_request", "message": str(error)}
            ) from error

    @app.post("/api/tables/{table_name}/export")
    def export_table(table_name: str, request: TableQuery, format: str = Query(default="csv")):
        try:
            payload = queries.export(
                table_name, request, settings.api.export_row_limit
            )
        except QueryError as error:
            status = 404 if error.code in {"unknown_dataset", "dataset_not_queryable"} else 400
            raise HTTPException(
                status_code=status, detail={"code": error.code, "message": str(error)}
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail={"code": "invalid_request", "message": str(error)}
            ) from error
        if format == "json":
            return JSONResponse(payload)
        safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in table_name)
        csv_text = to_csv(payload)
        return Response(
            content=csv_text,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}_export.csv"',
                "X-Export-Row-Limit": str(settings.api.export_row_limit),
                "X-Export-Truncated": str(payload["truncated"]).lower(),
            },
        )

    @app.get("/api/breadcrumbs/{source_file_id}/{source_row_number}")
    def resolve_breadcrumb(
        source_file_id: str,
        source_row_number: int,
        source_sheet: str | None = Query(default=None),
    ):
        try:
            return traces.resolve_breadcrumb(source_file_id, source_row_number, source_sheet)
        except QueryError as error:
            status = 404 if error.code == "unknown_breadcrumb" else 400
            raise HTTPException(
                status_code=status, detail={"code": error.code, "message": str(error)}
            ) from error

    @app.get("/api/records/{record_type}/{record_id}/sources")
    def record_sources(
        record_type: str,
        record_id: str,
        release_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        try:
            return traces.record_sources(record_type, record_id, release_id, limit)
        except QueryError as error:
            status = 404 if error.code == "unknown_record" else 400
            raise HTTPException(
                status_code=status, detail={"code": error.code, "message": str(error)}
            ) from error

    @app.get("/api/search")
    def search_endpoint(
        q: str = Query(min_length=2, max_length=100),
        page: int = Query(default=0, ge=0),
        status: list[str] = Query(default=[]),
        year_from: int | None = Query(default=None, ge=1990, le=2100),
        year_to: int | None = Query(default=None, ge=1990, le=2100),
        outcome: list[str] = Query(default=[]),
        party_page: int = Query(default=0, ge=0),
    ):
        try:
            return search.search(
                q,
                page,
                statuses=tuple(status),
                year_from=year_from,
                year_to=year_to,
                outcomes=tuple(outcome),
                party_page=party_page,
            )
        except QueryError as error:
            raise HTTPException(
                status_code=400, detail={"code": error.code, "message": str(error)}
            ) from error

    @app.get("/api/outcomes/funnel")
    def outcome_funnel(
        year_from: int | None = Query(default=None, ge=1990, le=2100),
        year_to: int | None = Query(default=None, ge=1990, le=2100),
    ):
        """Coverage funnel: process counts per canonical outcome."""
        return outcomes.funnel(year_from, year_to)

    @app.get("/api/index/manifest")
    def index_manifest():
        """Versioned build manifest for the disposable search projection.

        Diagnostics only: describes what produced the index (rule versions,
        source fingerprints, row counts, build time) and whether it is stale.
        Returns 409 while a build is in flight, 404 when no index exists.
        """
        snapshot = catalog.snapshot()
        paths = {
            item["name"]: Path(item["path"])
            for item in snapshot["datasets"]
            if item["status"] == "healthy"
        }
        manifest = search.index.build_manifest(paths)
        if manifest is None:
            state = search.index.state(paths)
            detail = (
                {"code": "index_building", "state": state}
                if state == "building"
                else {"code": "index_absent"}
            )
            raise HTTPException(
                status_code=409 if state == "building" else 404, detail=detail
            )
        return manifest

    @app.get("/api/outcomes/facets")
    def outcome_facets():
        return outcomes.outcome_facets()

    @app.get("/api/coverage/periods")
    def coverage_periods():
        """Per-source-period coverage: files, release links, issues.

        Serves the disposable `source_periods` projection (rule
        source-coverage-v1). Returns `available: false` while the index
        builds — the direct-Parquet aggregate costs 20s+ and must not run
        on the request path.
        """
        return coverage.periods()

    @app.get("/api/facts/summary")
    def facts_summary():
        """Dimension breakdowns over the process_facts projection.

        Process-grain counts per outcome, procurement method, category, and
        area of delivery — the Phase 1 step 4 analytical surface. Honors the
        docs/11 §2 guardrail: counts only, no monetary totals.
        """
        return outcomes.facts_summary()

    @app.get("/api/search/facets")
    def search_facets_endpoint():
        return search.facets()

    @app.get("/api/parties/name/{name:path}/identity")
    def party_identity_endpoint(name: str):
        """Provisional identity view: canonical party, name forms, candidates."""
        try:
            return search.party_identity_full(name)
        except QueryError as error:
            raise HTTPException(
                status_code=400, detail={"code": error.code, "message": str(error)}
            ) from error

    @app.get("/api/parties/name/{name:path}")
    def party_endpoint(
        name: str,
        page: int = Query(default=0, ge=0),
        scope: str = Query(default="name", pattern="^(name|identity)$"),
    ):
        try:
            return search.party(name, page, scope=scope)
        except QueryError as error:
            raise HTTPException(
                status_code=400, detail={"code": error.code, "message": str(error)}
            ) from error

    @app.get("/api/processes/{process_id}")
    def process_detail(process_id: str):
        try:
            return processes.detail(process_id)
        except QueryError as error:
            status = 404 if error.code == "unknown_process" else 400
            raise HTTPException(
                status_code=status, detail={"code": error.code, "message": str(error)}
            ) from error

    @app.get("/api/processes/{process_id}/summary")
    def process_summary(process_id: str):
        try:
            return processes.summary(process_id)
        except QueryError as error:
            status = 404 if error.code == "unknown_process" else 400
            raise HTTPException(
                status_code=status, detail={"code": error.code, "message": str(error)}
            ) from error

    @app.get("/api/processes/{process_id}/timeline")
    def process_timeline(process_id: str, limit: int = Query(default=200, ge=1, le=1000)):
        return processes.timeline(process_id, limit)

    @app.get("/api/processes/{process_id}/compare")
    def process_compare(
        process_id: str,
        left: str = Query(..., min_length=1, description="Left release id"),
        right: str = Query(..., min_length=1, description="Right release id"),
    ):
        """Field-level diff of two releases on the same process."""
        try:
            return processes.compare_releases(process_id, left, right)
        except QueryError as error:
            status = 404 if error.code == "unknown_process" else 400
            raise HTTPException(
                status_code=status, detail={"code": error.code, "message": str(error)}
            ) from error

    @app.get("/api/source-files/{source_file_id}/rows")
    def source_file_rows(source_file_id: str, start_row: int, end_row: int):
        try:
            return traces.source_file_rows(source_file_id, start_row, end_row)
        except QueryError as error:
            status = 404 if error.code in {"unknown_source_file"} else 400
            raise HTTPException(
                status_code=status, detail={"code": error.code, "message": str(error)}
            ) from error

    @app.get("/api/releases/{release_id}/sources")
    def release_sources(release_id: str):
        try:
            return traces.release_sources(release_id)
        except QueryError as error:
            status = 404 if error.code in {"unknown_release", "unknown_breadcrumb"} else 400
            raise HTTPException(
                status_code=status, detail={"code": error.code, "message": str(error)}
            ) from error

    @app.get("/api/releases/{release_id}/children")
    def release_children(release_id: str):
        return processes.child_counts(release_id)

    @app.get("/api/views")
    def list_saved_views():
        return saved_views.list_views()

    @app.get("/api/views/counts")
    def saved_view_counts():
        """Row counts for every valid saved view, memoized per fingerprint.

        Powers the data-health page: plain-language questions with live
        counts. Counts only the filter predicates; projection/sort are
        irrelevant to the number.
        """
        started = perf_counter()
        snapshot = catalog.snapshot()
        fingerprint = snapshot["dataset_fingerprint"]
        cached = _counts_cache.get(fingerprint)
        if cached is not None:
            return {**cached, "cached": True, "elapsed_ms": 0.0}
        listing = saved_views.list_views()
        counts: list[dict[str, Any]] = []
        errors: list[str] = []
        for view in listing["views"]:
            try:
                dataset, request = saved_views.as_query(view["name"], limit=1)
                request.cursor = None
                request.offset = 0
                total = queries.count(dataset, request)
                counts.append({
                    "name": view["name"],
                    "label": view["label"],
                    "description": view.get("description"),
                    "warning": view.get("warning"),
                    "dataset": dataset,
                    "count": total,
                })
            except (QueryError, ValueError) as error:
                errors.append(f"{view['name']}: {error}")
        payload = {
            "views_version": listing["views_version"],
            "counts": counts,
            "problems": listing["problems"] + errors,
            "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        }
        if len(_counts_cache) > 4:
            _counts_cache.clear()
        _counts_cache[fingerprint] = payload
        return payload

    @app.post("/api/views/{view_name}/query")
    def run_saved_view(view_name: str, limit: int | None = Query(default=None, ge=1, le=1000)):
        try:
            dataset, request = saved_views.as_query(view_name, limit)
        except QueryError as error:
            raise HTTPException(
                status_code=404, detail={"code": error.code, "message": str(error)}
            ) from error
        try:
            return queries.execute(dataset, request)
        except QueryError as error:
            status = 404 if error.code in {"unknown_dataset", "dataset_not_queryable"} else 400
            raise HTTPException(
                status_code=status, detail={"code": error.code, "message": str(error)}
            ) from error

    # Production build of the Vite/React frontend (frontend/app -> frontend/dist).
    # Development uses `scripts/dev.ps1`, which runs the Vite dev server and
    # proxies /api requests to this application.
    frontend = settings.project_root / "frontend"
    assets = frontend / "dist" / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.on_event("startup")
    def warm_background_builds() -> None:
        # Kick both disposable projections in daemon threads: requests served
        # before they finish fall back to direct scans transparently.
        threading.Thread(
            target=search.warm, name="search-index-build", daemon=True
        ).start()

        def _warm_provenance() -> None:
            snapshot = catalog.snapshot()
            path = None
            for item in snapshot["datasets"]:
                if item["name"] == "record_sources" and item["status"] == "healthy":
                    path = Path(item["path"])
                    break
            provenance.warm(path)

        threading.Thread(
            target=_warm_provenance, name="provenance-build", daemon=True
        ).start()

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(frontend / "dist" / "index.html")

    return app


settings = load_settings()
app = create_app(settings)
