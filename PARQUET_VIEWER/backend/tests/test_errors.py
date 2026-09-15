"""Error-code, validation, and timeout behavior tests (fixture-based)."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

import duckdb

from helpers import build_project, make_client

from backend.app.config import load_settings
from backend.app.query import (
    QUERY_ERROR_INVALID_FILTER,
    QUERY_ERROR_INVALID_PAGE,
    QUERY_ERROR_TIMEOUT,
    QUERY_ERROR_UNKNOWN_COLUMN,
    QUERY_ERROR_UNKNOWN_DATASET,
    FilterSpec,
    QueryError,
    TableQuery,
    TableQueryService,
)


def detail(response) -> dict:
    payload = response.json()["detail"]
    return payload if isinstance(payload, dict) else {"message": payload}


class ErrorCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_unknown_dataset_returns_404_with_code(self):
        response = self.client.post("/api/tables/nope/query", json={"page_size": 5})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(detail(response)["code"], QUERY_ERROR_UNKNOWN_DATASET)

    def test_unknown_column_returns_400_with_code(self):
        response = self.client.post("/api/tables/items/query", json={"columns": ["zzz"]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], QUERY_ERROR_UNKNOWN_COLUMN)

    def test_page_size_zero_is_rejected(self):
        response = self.client.post("/api/tables/items/query", json={"page_size": 0})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], QUERY_ERROR_INVALID_PAGE)

    def test_page_size_above_maximum_is_rejected(self):
        response = self.client.post("/api/tables/items/query", json={"page_size": 999})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], QUERY_ERROR_INVALID_PAGE)

    def test_object_filter_value_is_rejected_as_invalid_filter(self):
        response = self.client.post(
            "/api/tables/items/query",
            json={"filters": [{"column": "item_id", "operator": "eq", "value": {"a": 1}}]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], QUERY_ERROR_INVALID_FILTER)

    def test_list_filter_value_is_rejected_as_invalid_filter(self):
        response = self.client.post(
            "/api/tables/items/query",
            json={"filters": [{"column": "item_id", "operator": "eq", "value": ["x"]}]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], QUERY_ERROR_INVALID_FILTER)

    def test_contains_on_non_text_column_is_rejected(self):
        response = self.client.post(
            "/api/tables/items/query",
            json={
                "filters": [
                    {"column": "value_amount", "operator": "contains", "value": "9"}
                ]
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(detail(response)["code"], {QUERY_ERROR_INVALID_FILTER, "invalid_filter_type"})

    def test_missing_body_returns_422(self):
        response = self.client.post("/api/tables/items/query")
        self.assertEqual(response.status_code, 422)

    def test_forbidden_origin_is_rejected(self):
        denied = self.client.get("/api/health", headers={"Origin": "https://example.com"})
        self.assertEqual(denied.status_code, 403)


class _FakeCursor:
    description = [("release_id",)]

    def fetchall(self):
        return []


class _SlowConnection:
    """Simulates a connection blocked in execute() until interrupted."""

    def __init__(self):
        self._interrupted = threading.Event()
        self.interrupt_calls = 0

    def execute(self, *_args: Any, **_kwargs: Any):
        # Block like a long-running query; the watchdog interrupt unblocks it.
        if not self._interrupted.wait(timeout=30):
            raise AssertionError("watchdog never interrupted the query")
        self.interrupt_calls += 1
        raise duckdb.InterruptException()

    def interrupt(self):
        self._interrupted.set()

    def close(self):
        pass


class _FakePool:
    def __init__(self, connection):
        self._connection = connection

    def connection(self):
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            yield self._connection

        return _ctx()


class TimeoutTests(unittest.TestCase):
    def test_watchdog_interrupts_and_reports_timeout(self):
        root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(root, query_timeout_seconds=0.1)
        settings = load_settings(root / "config" / "settings.json")

        slow = _SlowConnection()
        pool = _FakePool(slow)
        service = TableQueryService(settings, pool, None)  # type: ignore[arg-type]
        request = TableQuery(filters=[], page_size=5)
        # execute() needs a real catalog snapshot; patch it to a minimal one.
        dataset = {
            "name": "items",
            "status": "healthy",
            "path": str(root / "parquets" / "items.parquet"),
            "primary_key": ["release_id", "item_id"],
            "columns": [{"name": "release_id", "type": "VARCHAR", "nullable": True}],
        }
        service.catalog = type(
            "StubCatalog", (), {"snapshot": lambda self_, refresh=False: {"datasets": [dataset], "dataset_fingerprint": "f"}}
        )()
        with self.assertRaises(QueryError) as raised:
            service.execute("items", request)
        self.assertEqual(raised.exception.code, QUERY_ERROR_TIMEOUT)
        self.assertIn("deadline", str(raised.exception))


class ScalarValidationTests(unittest.TestCase):
    def test_scalar_values_pass_validation(self):
        from backend.app.query import _scalar_filter_value

        for value in (None, "x", 5, 5.5, True):
            self.assertEqual(_scalar_filter_value(value), value)


class ResponseLimitTests(unittest.TestCase):
    """Wide-row / long-text response safeguards (config/saved 2026-09-16)."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_long_text_cells_are_truncated_with_marker(self):
        from backend.app.query import MAX_CELL_CHARS, _cell_text

        long_text = "x" * (MAX_CELL_CHARS + 5000)
        out = _cell_text(long_text)
        self.assertLess(len(out), len(long_text))
        self.assertTrue(out.endswith("chars]"))
        self.assertIn("… [+5000 chars]", out[-30:])
        # Short text passes through untouched.
        self.assertEqual(_cell_text("normal"), "normal")

    def test_oversized_rows_are_dropped_and_reported(self):
        from backend.app import query as query_mod

        # A row whose JSON weight exceeds the cap is dropped, not served.
        payload_row = {"a": "x" * (query_mod.MAX_ROW_WEIGHT_CHARS + 10)}
        self.assertGreater(
            query_mod._row_payload_weight(payload_row),
            query_mod.MAX_ROW_WEIGHT_CHARS,
        )
        normal = {"a": "fine"}
        self.assertEqual(
            query_mod._row_payload_weight(normal),
            len('{"a": "fine"}'),
        )


class ConcurrencyTests(unittest.TestCase):
    """Connection limits and cleanup after failed queries."""

    def test_pool_bounds_concurrent_connections(self):
        root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(root)
        settings = load_settings(root / "config" / "settings.json")
        from backend.app.database import DuckDBPool

        pool = DuckDBPool(settings)
        max_slots = max(2, settings.duckdb.max_concurrent_queries // 2)
        acquired: list[Any] = []
        errors: list[Exception] = []

        def worker(index: int) -> None:
            try:
                with pool.connection() as conn:
                    acquired.append(conn)
                    # Hold briefly to force overlap.
                    conn.execute("SELECT 1").fetchall()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(i,)) for i in range(max_slots * 3)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertGreater(len(acquired), 0)

    def test_failed_query_returns_error_and_pool_stays_usable(self):
        root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(root)
        settings = load_settings(root / "config" / "settings.json")
        from backend.app.database import DuckDBPool

        pool = DuckDBPool(settings)
        # Cause a failure inside a pooled connection.
        with self.assertRaises(Exception):
            with pool.connection() as conn:
                conn.execute("SELECT * FROM does_not_exist").fetchall()
        # The same pool must still serve a good query afterwards.
        with pool.connection() as conn:
            value = conn.execute("SELECT 42").fetchone()[0]
        self.assertEqual(value, 42)


if __name__ == "__main__":
    unittest.main()
