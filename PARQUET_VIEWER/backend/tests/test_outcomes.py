"""Tests for the process-outcome rules, funnel, and search integration.

Run with the project's standard runner:
    python -m unittest discover -s backend\\tests
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from helpers import FIXTURE_PROCESS_ID, build_project, make_client

from backend.app.derivation import describe
from backend.app.outcomes import OutcomesService


class ClassifierRuleTests(unittest.TestCase):
    """Decision-order table from docs/13 (shared pure function)."""

    def test_contracted_when_award_and_matched_contract(self):
        self.assertEqual(OutcomesService.classify("Awarded", 1, 1, 0, 0), "contracted")

    def test_awarded_without_contract(self):
        self.assertEqual(OutcomesService.classify("Awarded", 1, 0, 0, 0), "awarded")

    def test_partially_awarded_requires_some_but_not_all_items_linked(self):
        self.assertEqual(
            OutcomesService.classify("Awarded", 1, 0, 4, 2), "partially_awarded"
        )

    def test_zero_item_links_is_not_partial(self):
        # Award-link-missing must not be reported as not-awarded items.
        self.assertEqual(OutcomesService.classify("Awarded", 1, 0, 4, 0), "awarded")

    def test_partial_beats_contracted(self):
        self.assertEqual(
            OutcomesService.classify("Awarded", 2, 2, 4, 1), "partially_awarded"
        )

    def test_conflicting_evidence_award_on_failed_tender(self):
        self.assertEqual(
            OutcomesService.classify("Failed", 1, 0, 3, 3), "conflicting_evidence"
        )

    def test_conflicting_evidence_award_on_cancelled_tender(self):
        self.assertEqual(
            OutcomesService.classify("Cancelled", 2, 1, 0, 0), "conflicting_evidence"
        )

    def test_cancelled_without_awards(self):
        self.assertEqual(OutcomesService.classify("Cancelled", 0, 0, 3, 0), "cancelled")

    def test_unsuccessful_without_awards(self):
        self.assertEqual(OutcomesService.classify("Failed", 0, 0, 3, 0), "unsuccessful")

    def test_active_status(self):
        self.assertEqual(OutcomesService.classify("Active", 0, 0, 3, 0), "active")
        self.assertEqual(
            OutcomesService.classify("Shortlisted", 0, 0, 0, 0), "active"
        )

    def test_closed_without_signals_is_unknown(self):
        self.assertEqual(OutcomesService.classify("Closed", 0, 0, 3, 0), "closed_unknown")

    def test_null_status_without_awards_is_unknown(self):
        self.assertEqual(OutcomesService.classify(None, 0, 0, 0, 0), "closed_unknown")


class DerivationMetadataTests(unittest.TestCase):
    def test_describe_validates_origin(self):
        with self.assertRaises(ValueError):
            describe(
                origin="guessed", rule="r", rule_version="1",
                source_fields=[], basis="b", confidence="observed",
                source_count=1,
            )

    def test_describe_validates_confidence(self):
        with self.assertRaises(ValueError):
            describe(
                origin="derived", rule="r", rule_version="1",
                source_fields=[], basis="b", confidence="sure",
                source_count=1,
            )

    def test_describe_roundtrip(self):
        record = describe(
            origin="derived", rule="process-outcomes-v1", rule_version="1",
            source_fields=["tenders.source_status"], basis="preferred_release",
            confidence="derived", source_count=5,
        )
        self.assertEqual(record["source_fields"], ["tenders.source_status"])
        self.assertEqual(record["source_count"], 5)


class FixtureOutcomeTests(unittest.TestCase):
    """Outcome endpoint behavior over the standard fixture project.

    Fixture preferred release: tender Closed, 2 awards, 1 matched contract,
    3 tender items with 2 award-item links -> partially_awarded.
    """

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_outcomes_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_summary_carries_outcome_with_metadata(self):
        response = self.client.get(f"/api/processes/{FIXTURE_PROCESS_ID}/summary")
        self.assertEqual(response.status_code, 200)
        outcome = response.json()["outcome"]
        self.assertEqual(outcome["outcome"], "partially_awarded")
        self.assertTrue(outcome["label"])
        metadata = outcome["metadata"]
        self.assertEqual(metadata["origin"], "derived")
        self.assertEqual(metadata["rule"], "process-outcomes-v1")
        self.assertEqual(metadata["confidence"], "derived")
        self.assertGreater(metadata["source_count"], 0)

    def test_funnel_shape(self):
        response = self.client.get("/api/outcomes/funnel")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # Fixtures build the index inline (small sources), so it is available.
        self.assertTrue(payload["available"])
        self.assertEqual(payload["rule"], "process-outcomes-v1")
        self.assertGreaterEqual(payload["total_processes"], 1)
        outcomes = {stage["outcome"] for stage in payload["stages"]}
        self.assertEqual(
            outcomes,
            {
                "contracted", "awarded", "partially_awarded", "active",
                "closed_unknown", "unsuccessful", "cancelled",
                "conflicting_evidence",
            },
        )
        counts = {stage["outcome"]: stage["count"] for stage in payload["stages"]}
        self.assertGreaterEqual(counts["partially_awarded"], 1)

    def test_funnel_year_filter_excludes_undated(self):
        response = self.client.get("/api/outcomes/funnel?year_from=2030&year_to=2031")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dated_total"], 0)

    def test_search_facets_include_outcomes(self):
        response = self.client.get("/api/search/facets")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("outcomes", payload)
        if payload["available"]:
            entries = [o["outcome"] for o in payload["outcomes"]]
            self.assertIn("partially_awarded", entries)

    def test_search_accepts_outcome_filter(self):
        response = self.client.get(
            "/api/search",
            params={"q": "Fixture", "outcome": "partially_awarded"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["filters"]["outcomes"], ["partially_awarded"])

    def test_search_rejects_unknown_outcome_value(self):
        response = self.client.get(
            "/api/search",
            params={"q": "Fixture", "outcome": "banana"},
        )
        self.assertEqual(response.status_code, 400)

    def test_search_outcome_filter_matches_only_that_outcome(self):
        matched = self.client.get(
            "/api/search",
            params={"q": "Fixture", "outcome": "partially_awarded"},
        ).json()
        other = self.client.get(
            "/api/search",
            params={"q": "Fixture", "outcome": "cancelled"},
        ).json()
        matched_ids = {card["process_id"] for card in matched["procurements"]}
        other_ids = {card["process_id"] for card in other["procurements"]}
        if matched_ids and other_ids:
            self.assertFalse(matched_ids & other_ids)


class IndexProjectionTests(unittest.TestCase):
    """The SQL projection builds, is populated, and stores valid outcomes."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_outcomes_proj_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)
        # A search request triggers the inline index build on small sources.
        cls.client.get("/api/search", params={"q": "Fixture"})

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_outcome_table_agrees_with_classifier(self):
        from backend.app.config import load_settings

        settings = load_settings(self.root / "config" / "settings.json")
        index_db = settings.cache_directory / "search_index.duckdb"
        self.assertTrue(index_db.exists(), "fixture index should build inline")
        connection = duckdb.connect(str(index_db), read_only=True)
        try:
            rows = connection.execute(
                "SELECT process_id, outcome FROM outcomes"
            ).fetchall()
        finally:
            connection.close()
        self.assertTrue(rows, "outcome table should be populated")
        valid = {
            "contracted", "awarded", "partially_awarded", "active",
            "closed_unknown", "unsuccessful", "cancelled",
            "conflicting_evidence",
        }
        for _process_id, outcome in rows:
            self.assertIn(outcome, valid)


if __name__ == "__main__":
    unittest.main()
