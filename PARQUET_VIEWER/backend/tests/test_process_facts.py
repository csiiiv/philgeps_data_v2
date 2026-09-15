"""Tests for the process_facts projection and /api/facts/summary.

docs/11 Phase 1 step 4 (rule process-facts-v1): one analytical row per
process with dimensions (method, category, area, closing year), evidence
counts, and the outcome computed in the same pass as docs/13 so the
`outcomes` table can never drift from the facts.

Run with the project's standard runner:
    python -m unittest discover -s backend\\tests
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from helpers import build_project, make_client


class ProcessFactsTableTests(unittest.TestCase):
    """The facts table carries dimensions and agrees with `outcomes`."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_facts_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)
        # A search request triggers the inline index build on small sources.
        cls.client.get("/api/search", params={"q": "Fixture"})
        cls.db = cls.root / ".cache" / "search_index.duckdb"
        cls.con = duckdb.connect(str(cls.db), read_only=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls.client.close()

    def test_one_row_per_process(self):
        facts = self.con.execute(
            "SELECT count(*) FROM process_facts"
        ).fetchone()[0]
        procs = self.con.execute(
            "SELECT count(DISTINCT process_id) FROM process_facts"
        ).fetchone()[0]
        self.assertEqual(facts, procs)

    def test_dimensions_present(self):
        row = self.con.execute(
            """
            SELECT procurement_method, main_procurement_category,
                   area_of_delivery, closing_year, contract_tender_ratio
            FROM process_facts LIMIT 1
            """
        ).fetchone() if self._has_ratio() else self.con.execute(
            """
            SELECT procurement_method, main_procurement_category,
                   area_of_delivery, closing_year
            FROM process_facts LIMIT 1
            """
        ).fetchone()
        self.assertEqual(row[0], "open")
        self.assertEqual(row[1], "goods")
        self.assertEqual(row[2], "Region X")
        self.assertEqual(row[3], 2024)

    def _has_ratio(self) -> bool:
        cols = {
            c[0]
            for c in self.con.execute(
                "SELECT name FROM parquet_schema('x') LIMIT 0"
            ).fetchall()
        } if False else None
        # Simpler: try the select and fall back.
        try:
            self.con.execute(
                "SELECT contract_tender_ratio FROM process_facts LIMIT 1"
            ).fetchone()
            return True
        except duckdb.Error:
            return False

    def test_outcome_table_is_pure_projection(self):
        mismatch = self.con.execute(
            """
            SELECT count(*) FROM outcomes o
            FULL OUTER JOIN process_facts f USING (process_id)
            WHERE o.outcome IS DISTINCT FROM f.outcome
               OR o.process_id IS NULL
               OR f.process_id IS NULL
            """
        ).fetchone()[0]
        self.assertEqual(mismatch, 0)


class FactsSummaryEndpointTests(unittest.TestCase):
    """The aggregate endpoint reports dimensions and honest unavailability."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_facts_api_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)
        cls.client.get("/api/search", params={"q": "Fixture"})

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_summary_has_dimensions_and_metadata(self):
        response = self.client.get("/api/facts/summary")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["available"])
        self.assertGreater(payload["total_processes"], 0)
        self.assertEqual(payload["rule"], "process-facts-v1")
        # The fixture uses 'open' method, 'goods' category, 'Region X' area.
        self.assertEqual(payload["methods"][0]["value"], "open")
        self.assertEqual(payload["categories"][0]["value"], "goods")
        self.assertEqual(payload["areas"][0]["value"], "Region X")
        # Outcome buckets sum to the total.
        self.assertEqual(
            sum(o["count"] for o in payload["outcomes"]),
            payload["total_processes"],
        )
        # Metadata rides the shared derivation shape.
        self.assertEqual(payload["metadata"]["rule"], "process-facts-v1")
        self.assertEqual(payload["metadata"]["origin"], "derived")

    def test_counts_only_no_money(self):
        payload = self.client.get("/api/facts/summary").json()
        blob = str(payload)
        self.assertNotIn("amount", blob.lower())

    def test_dimension_buckets_sum_to_total(self):
        """Guards against grouping-set misrouting with NULL dimension data."""
        payload = self.client.get("/api/facts/summary").json()
        for key in ("methods", "categories", "areas"):
            self.assertEqual(
                sum(b["count"] for b in payload[key]),
                payload["total_processes"],
                f"{key} buckets do not sum to total",
            )
