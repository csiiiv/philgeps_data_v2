"""Tests for the shared relationship-confidence vocabulary (docs/11 §16).

Run with the project's standard runner:
    python -m unittest discover -s backend\\tests
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURE_PROCESS_ID, build_project, make_client

from backend.app.derivation import (
    LINK_STATES,
    relationship_metadata,
    relationship_status,
)


class RelationshipVocabularyTests(unittest.TestCase):
    """§16 rule: one closed vocabulary, no invented sixth state."""

    def test_matched_maps_to_linked(self):
        self.assertEqual(relationship_status("matched"), "linked")

    def test_missing_maps_to_missing(self):
        self.assertEqual(relationship_status("missing"), "missing")

    def test_ambiguous_maps_to_ambiguous(self):
        self.assertEqual(relationship_status("ambiguous"), "ambiguous")

    def test_null_maps_to_missing(self):
        # A null status means "no evidence of a link" — a visible gap.
        self.assertEqual(relationship_status(None), "missing")

    def test_unknown_status_maps_to_missing_not_invented_state(self):
        self.assertEqual(relationship_status("weird_future_value"), "missing")

    def test_case_and_whitespace_normalized(self):
        self.assertEqual(relationship_status("  Matched "), "linked")

    def test_vocabulary_is_closed(self):
        for raw in ("matched", "missing", "ambiguous", None, "other"):
            self.assertIn(relationship_status(raw), LINK_STATES)


class RelationshipMetadataTests(unittest.TestCase):
    """§16 metadata extends the shared derivation shape (step 0)."""

    def test_metadata_shape(self):
        meta = relationship_metadata(
            source_table="award_suppliers",
            status_column="award_link_status",
            raw_status="matched",
        )
        self.assertEqual(meta["origin"], "normalized")
        self.assertEqual(meta["rule"], "relationship-status-v1")
        self.assertEqual(meta["rule_version"], "1")
        self.assertEqual(meta["source_fields"], ["award_suppliers.award_link_status"])
        self.assertEqual(meta["confidence"], "observed")
        self.assertEqual(meta["source_count"], 1)
        self.assertIn("matched", meta["basis"])

    def test_metadata_for_null_status_is_provisional(self):
        meta = relationship_metadata(
            source_table="award_suppliers",
            status_column="party_link_status",
            raw_status=None,
        )
        self.assertEqual(meta["confidence"], "provisional")


class ProcessSummaryLinkIntegrationTests(unittest.TestCase):
    """Supplier entries expose the normalized `link` block in the API."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_links_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)
        cls.response = cls.client.get(f"/api/processes/{FIXTURE_PROCESS_ID}/summary")
        cls.payload = cls.response.json() if cls.response.status_code == 200 else {}

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def _suppliers(self):
        for award in self.payload.get("awards", []):
            for supplier in award.get("suppliers", []):
                yield supplier

    def test_link_block_present_when_awards_exist(self):
        suppliers = list(self._suppliers())
        if not suppliers:
            self.skipTest("fixture has no award suppliers")
        for supplier in suppliers:
            self.assertIn("link", supplier)
            link = supplier["link"]
            self.assertIn(link["award"], LINK_STATES)
            self.assertIn(link["party"], LINK_STATES)
            self.assertEqual(link["metadata"]["rule"], "relationship-status-v1")

    def test_link_states_always_in_vocabulary(self):
        for supplier in self._suppliers():
            self.assertIn(supplier["link"]["award"], LINK_STATES)
            self.assertIn(supplier["link"]["party"], LINK_STATES)
