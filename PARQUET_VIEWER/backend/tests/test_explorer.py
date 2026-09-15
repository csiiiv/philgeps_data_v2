"""Keyset cursor, typed-filter, OR-logic, and export tests (fixture-based)."""

from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from helpers import build_project, make_client


def detail(response) -> dict:
    payload = response.json()["detail"]
    return payload if isinstance(payload, dict) else {"message": payload}


class CursorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def _all_rows_via_offset(self):
        payload = self.client.post(
            "/api/tables/items/query", json={"page_size": 10}
        ).json()
        return [(r["release_id"], r["item_id"]) for r in payload["rows"]]

    def test_cursor_walks_full_table_in_stable_order(self):
        expected = self._all_rows_via_offset()
        seen: list[tuple[str, str]] = []
        cursor = None
        for _ in range(10):
            body = {"page_size": 2}
            if cursor:
                body["cursor"] = cursor
            payload = self.client.post("/api/tables/items/query", json=body).json()
            seen.extend((r["release_id"], r["item_id"]) for r in payload["rows"])
            cursor = payload["page"]["next_cursor"]
            if not cursor:
                break
        self.assertEqual(seen, expected)
        self.assertEqual(payload["page"]["pagination"], "keyset")

    def test_cursor_rejects_tampering(self):
        first = self.client.post("/api/tables/items/query", json={"page_size": 1}).json()
        cursor = first["page"]["next_cursor"]
        self.assertIsNotNone(cursor)
        body, signature = cursor.split(".")
        forged = body + "." + ("0" * 64)
        response = self.client.post(
            "/api/tables/items/query", json={"page_size": 1, "cursor": forged}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], "invalid_cursor")

    def test_cursor_rejects_reuse_with_different_filters(self):
        first = self.client.post("/api/tables/items/query", json={"page_size": 1}).json()
        cursor = first["page"]["next_cursor"]
        response = self.client.post(
            "/api/tables/items/query",
            json={
                "page_size": 1,
                "cursor": cursor,
                "filters": [{"column": "status", "operator": "eq", "value": "active"}],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], "invalid_cursor")

    def test_cursor_survives_matching_repeat_request(self):
        first = self.client.post(
            "/api/tables/items/query",
            json={"page_size": 1, "sort": [{"column": "item_id", "direction": "asc"}]},
        ).json()
        cursor = first["page"]["next_cursor"]
        second = self.client.post(
            "/api/tables/items/query",
            json={
                "page_size": 1,
                "sort": [{"column": "item_id", "direction": "asc"}],
                "cursor": cursor,
            },
        ).json()
        self.assertEqual(second["rows"][0]["item_id"], "pgti_i2")


class TypedFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_numeric_filter_accepts_string_decimal(self):
        response = self.client.post(
            "/api/tables/items/query",
            json={
                "filters": [
                    {"column": "value_amount", "operator": "lte", "value": "9.99"}
                ]
            },
        ).json()
        self.assertEqual(len(response["rows"]), 2)

    def test_numeric_filter_rejects_non_numeric_text(self):
        response = self.client.post(
            "/api/tables/items/query",
            json={
                "filters": [
                    {"column": "value_amount", "operator": "eq", "value": "abc"}
                ]
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], "invalid_filter_type")

    def test_date_filter_rejects_bad_format(self):
        response = self.client.post(
            "/api/tables/items/query",
            json={
                "filters": [
                    {"column": "planned_date", "operator": "gte", "value": "01/15/2024"}
                ]
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], "invalid_filter_type")

    def test_date_filter_accepts_iso(self):
        response = self.client.post(
            "/api/tables/items/query",
            json={
                "filters": [
                    {"column": "planned_date", "operator": "gte", "value": "2024-01-15"}
                ]
            },
        ).json()
        self.assertEqual(len(response["rows"]), 2)

    def test_bool_filter_rejects_text(self):
        response = self.client.post(
            "/api/tables/items/query",
            json={"filters": [{"column": "flag", "operator": "eq", "value": "yes"}]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], "invalid_filter_type")

    def test_comparison_rejected_for_list_column(self):
        response = self.client.post(
            "/api/tables/items/query",
            json={"filters": [{"column": "tags", "operator": "eq", "value": "a"}]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], "invalid_filter_type")


class OrLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_or_combines_predicates(self):
        payload = self.client.post(
            "/api/tables/items/query",
            json={
                "filter_logic": "or",
                "filters": [
                    {"column": "status", "operator": "eq", "value": "active"},
                    {"column": "item_id", "operator": "eq", "value": "pgti_i2"},
                ],
                "page_size": 10,
            },
        ).json()
        ids = sorted(r["item_id"] for r in payload["rows"])
        self.assertEqual(ids, ["pgti_i1", "pgti_i2"])

    def test_and_remains_default(self):
        payload = self.client.post(
            "/api/tables/items/query",
            json={
                "filters": [
                    {"column": "status", "operator": "eq", "value": "active"},
                    {"column": "item_id", "operator": "eq", "value": "pgti_i2"},
                ],
                "page_size": 10,
            },
        ).json()
        self.assertEqual(len(payload["rows"]), 0)


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_csv_export_has_formula_protection_and_types(self):
        response = self.client.post(
            "/api/tables/items/export",
            json={"columns": ["release_id", "item_id", "value_amount", "tags"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        rows = list(csv.reader(io.StringIO(response.text)))
        self.assertEqual(rows[0][:3], ["release_id", "item_id", "value_amount"])
        # tags round-trips as a JSON array string
        self.assertIn("[", rows[1][3])
        self.assertEqual(len(rows), 4)  # header + 3 rows

    def test_formula_cells_are_prefixed(self):
        from backend.app.query import csv_cell

        self.assertEqual(csv_cell("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(csv_cell("+cmd"), "'+cmd")
        self.assertEqual(csv_cell("-1-1"), "'-1-1")
        self.assertEqual(csv_cell("@x"), "'@x")
        self.assertEqual(csv_cell("plain"), "plain")
        self.assertEqual(csv_cell(None), "")
        # JSON-rendered list contains commas, so it must be quoted
        self.assertEqual(csv_cell(["a", "b"]), '"[""a"", ""b""]"')
        # embedded separators are quoted
        self.assertEqual(csv_cell('a,"b"'), '"a,""b"""')

    def test_json_export_returns_payload_with_limits(self):
        response = self.client.post(
            "/api/tables/items/export?format=json", json={"page_size": 2}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("row_limit", payload)
        self.assertFalse(payload["truncated"])

    def test_export_rejects_unknown_columns(self):
        response = self.client.post(
            "/api/tables/items/export", json={"columns": ["zzz"]}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(detail(response)["code"], "unknown_column")


if __name__ == "__main__":
    unittest.main()
