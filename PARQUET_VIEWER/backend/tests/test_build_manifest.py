"""Tests for the versioned build manifest (docs/11 Phase 1 step 5).

The manifest records what produced the disposable search projection:
rule versions, source fingerprints, row counts, and build time. It rides
inside the index's `meta` table so it swaps atomically with the projection.

Run with the project's standard runner:
    python -m unittest discover -s backend\\tests
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import build_project, make_client


class BuildManifestTests(unittest.TestCase):
    """The built index carries a complete, well-formed build manifest."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_manifest_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)
        # A search request triggers the inline index build on small sources.
        cls.client.get("/api/search", params={"q": "Fixture"})

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_manifest_endpoint_returns_versioned_manifest(self):
        response = self.client.get("/api/index/manifest")
        self.assertEqual(response.status_code, 200)
        manifest = response.json()
        self.assertEqual(manifest["manifest_version"], 1)
        self.assertEqual(manifest["projection"], "search_index")
        self.assertIsInstance(manifest["schema_version"], int)
        self.assertIn("built_at", manifest)

    def test_manifest_records_rule_versions(self):
        manifest = self.client.get("/api/index/manifest").json()
        self.assertEqual(
            manifest["rules"]["outcome"]["rule"], "process-outcomes-v1"
        )
        self.assertEqual(
            manifest["rules"]["relationship"]["rule"], "relationship-status-v1"
        )
        self.assertEqual(manifest["rules"]["facts"]["rule"], "process-facts-v1")
        self.assertEqual(manifest["rules"]["coverage"]["rule"], "source-coverage-v1")

    def test_manifest_records_row_counts(self):
        manifest = self.client.get("/api/index/manifest").json()
        counts = manifest["row_counts"]
        self.assertGreater(counts["procurements"], 0)
        self.assertGreater(counts["process_facts"], 0)
        self.assertGreater(counts["outcomes"], 0)
        self.assertGreaterEqual(counts["filter_stats"], 0)
        self.assertGreater(counts["source_periods"], 0)

    def test_manifest_fresh_after_build(self):
        manifest = self.client.get("/api/index/manifest").json()
        self.assertFalse(manifest["stale"])
        self.assertEqual(manifest["index_state"], "hit")

    def test_manifest_sources_cover_index_inputs(self):
        manifest = self.client.get("/api/index/manifest").json()
        # Fingerprint entries for the index's source datasets (paths vary by
        # fixture root); schema_version is excluded from `sources`.
        self.assertIn("compiled_processes", manifest["sources"])
        self.assertIn("tenders", manifest["sources"])


class BuildManifestDegradationTests(unittest.TestCase):
    """No index (or a pre-manifest index) must 404, never 500."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_manifest_none_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_manifest_endpoint_404_without_index(self):
        response = self.client.get("/api/index/manifest")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "index_absent")
