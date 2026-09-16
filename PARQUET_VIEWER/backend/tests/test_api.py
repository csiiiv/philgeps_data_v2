"""API surface tests against fixture Parquets (no production data)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import build_project, make_client


class CatalogApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_health_endpoint_reports_dataset_counts(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dataset_count"], 14)
        self.assertEqual(payload["manifest"]["version"], 2)
        self.assertEqual(payload["manifest"]["source_file_count"], 2)

    def test_catalog_lists_registered_dataset_with_columns(self):
        response = self.client.get("/api/catalog")
        self.assertEqual(response.status_code, 200)
        snapshot = response.json()
        self.assertEqual(snapshot["dataset_count"], 14)
        dataset = next(d for d in snapshot["datasets"] if d["name"] == "items")
        self.assertEqual(dataset["name"], "items")
        self.assertEqual(dataset["primary_key"], ["release_id", "item_id"])
        self.assertEqual(dataset["row_count"], 3)
        names = {column["name"] for column in dataset["columns"]}
        self.assertIn("value_amount", names)

    def test_schema_endpoint_returns_columns_and_rejects_unknown_table(self):
        response = self.client.get("/api/tables/items/schema")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "items")
        missing = self.client.get("/api/tables/not-a-table/schema")
        self.assertEqual(missing.status_code, 404)


class TableApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_query_returns_rows_and_type_labels(self):
        response = self.client.post("/api/tables/items/query", json={"page_size": 10})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["rows"]), 3)
        types = {column["name"]: column["type"] for column in payload["columns"]}
        self.assertIn("DECIMAL", types["value_amount"])
        self.assertIn("DATE", types["planned_date"])
        self.assertIn("TIMESTAMP", types["observed_at"])
        self.assertTrue(
            "LIST" in types["tags"] or "[]" in types["tags"],
            f"expected a list type, got {types['tags']!r}",
        )

    def test_decimal_date_timestamp_list_and_null_round_trip(self):
        response = self.client.post("/api/tables/items/query", json={"page_size": 10})
        rows = response.json()["rows"]
        by_key = {(r["release_id"], r["item_id"]): r for r in rows}
        first = by_key[("pgrl_r1", "pgti_i1")]
        self.assertEqual(first["value_amount"], "1.50")
        self.assertEqual(first["planned_date"], "2024-01-15")
        self.assertEqual(first["observed_at"], "2024-01-16T08:30:00")
        self.assertEqual(first["tags"], ["a", "b"])
        third = by_key[("pgrl_r2", "pgti_i3")]
        self.assertIsNone(third["value_amount"])
        self.assertIsNone(third["planned_date"])
        self.assertIsNone(third["status"])

    def test_eq_filter_returns_exact_row(self):
        response = self.client.post(
            "/api/tables/items/query",
            json={"filters": [{"column": "item_id", "operator": "eq", "value": "pgti_i2"}]},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0]["item_id"], "pgti_i2")

    def test_contains_percent_is_literal_not_wildcard(self):
        response = self.client.post(
            "/api/tables/items/query",
            json={
                "filters": [{"column": "item_id", "operator": "contains", "value": "%"}],
                "page_size": 10,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["rows"]), 0)

    def test_null_filters(self):
        is_null = self.client.post(
            "/api/tables/items/query",
            json={"filters": [{"column": "status", "operator": "is_null"}]},
        ).json()
        self.assertEqual(len(is_null["rows"]), 1)
        not_null = self.client.post(
            "/api/tables/items/query",
            json={"filters": [{"column": "status", "operator": "not_null"}]},
        ).json()
        self.assertEqual(len(not_null["rows"]), 2)

    def test_pagination_reports_has_more_and_next_offset(self):
        payload = self.client.post("/api/tables/items/query", json={"page_size": 2}).json()
        self.assertEqual(payload["page"]["returned"], 2)
        self.assertTrue(payload["page"]["has_more"])
        self.assertEqual(payload["page"]["next_offset"], 2)
        next_page = self.client.post(
            "/api/tables/items/query", json={"page_size": 2, "offset": 2}
        ).json()
        self.assertEqual(next_page["page"]["returned"], 1)
        self.assertFalse(next_page["page"]["has_more"])

    def test_primary_key_tiebreaker_yields_stable_order(self):
        first = self.client.post("/api/tables/items/query", json={"page_size": 2}).json()
        second = self.client.post(
            "/api/tables/items/query", json={"page_size": 2, "offset": 2}
        ).json()
        page_one_keys = [(r["release_id"], r["item_id"]) for r in first["rows"]]
        page_two_keys = [(r["release_id"], r["item_id"]) for r in second["rows"]]
        self.assertEqual(page_one_keys, [("pgrl_r1", "pgti_i1"), ("pgrl_r1", "pgti_i2")])
        self.assertEqual(page_two_keys, [("pgrl_r2", "pgti_i3")])


if __name__ == "__main__":
    unittest.main()
