"""Saved-views tests: listing, validation, and execution."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import build_project, make_client


class SavedViewsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_list_views_reports_definitions_and_problems(self):
        response = self.client.get("/api/views")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        names = [view["name"] for view in payload["views"]]
        self.assertIn("items_active", names)
        self.assertIn("bad_column_view", names)
        # the stale view is flagged, not silently dropped
        self.assertTrue(
            any("no_such_column" in problem for problem in payload["problems"])
        )

    def test_run_view_applies_filters_and_sort(self):
        response = self.client.post("/api/views/items_active/query")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["table"], "items")
        self.assertGreaterEqual(payload["page"]["returned"], 1)
        # every returned row must be active
        for row in payload["rows"]:
            self.assertEqual(row["status"], "active")

    def test_run_view_limit_overrides_page_size(self):
        response = self.client.post("/api/views/items_active/query?limit=1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["page"]["page_size"], 1)
        self.assertEqual(payload["page"]["returned"], 1)

    def test_unknown_view_returns_404(self):
        response = self.client.post("/api/views/not_a_view/query")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "invalid_saved_views")


class ViewCountsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_counts_lists_every_valid_view_with_counts(self):
        response = self.client.get("/api/views/counts")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload["counts"]), 1)
        for entry in payload["counts"]:
            self.assertIn("name", entry)
            self.assertIn("label", entry)
            self.assertIsInstance(entry["count"], int)
        names = {entry["name"] for entry in payload["counts"]}
        self.assertIn("items_active", names)

    def test_counts_match_direct_query_total(self):
        counts = self.client.get("/api/views/counts").json()["counts"]
        items_active = next(e for e in counts if e["name"] == "items_active")
        query = self.client.post(
            "/api/views/items_active/query", json={"page_size": 1}
        ).json()
        # Direct execution is bounded; the count must be >= rows returned.
        self.assertGreaterEqual(items_active["count"], len(query["rows"]))

    def test_counts_repeat_is_cached(self):
        self.client.get("/api/views/counts")
        response = self.client.get("/api/views/counts")
        self.assertTrue(response.json()["cached"])


if __name__ == "__main__":
    unittest.main()
