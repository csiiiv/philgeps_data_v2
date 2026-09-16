"""Tests for source-period coverage (rule source-coverage-v1).

Covers the pure period parser, the projection served by
GET /api/coverage/periods, its derivation metadata, and honest
unavailability when the index has not been built.

Run with the project's standard runner:
    python -m unittest discover -s backend\\tests
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import (
    FIXTURE_PROCESS_ID,
    FIXTURE_RELEASE_ID_1,
    FIXTURE_SOURCE_FILE_ID,
    FIXTURE_SOURCE_FILE_ID_2,
    build_project,
    make_client,
)

from backend.app.coverage import period_from_file_name


class PeriodParserTests(unittest.TestCase):
    def test_quarter_from_month(self):
        self.assertEqual(period_from_file_name("2021-04--2021-06.csv"), "2021-Q2")
        self.assertEqual(period_from_file_name("2024-01--2024-03.csv"), "2024-Q1")
        self.assertEqual(period_from_file_name("2025-11--2026-01.csv"), "2025-Q4")

    def test_unparsable_names_land_in_unknown(self):
        self.assertEqual(period_from_file_name("supplement.csv"), "unknown")
        self.assertEqual(period_from_file_name(""), "unknown")
        self.assertEqual(period_from_file_name(None), "unknown")
        self.assertEqual(period_from_file_name("13-14--2024-06.csv"), "unknown")
        self.assertEqual(period_from_file_name("2024-13--2024-12.csv"), "unknown")


class CoverageEndpointTests(unittest.TestCase):
    """The projection answers from the built index with honest semantics."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_coverage_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)
        # Trigger the inline index build (small fixture sources).
        cls.client.get("/api/search", params={"q": "Fixture"})
        cls.payload = cls.client.get("/api/coverage/periods").json()

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_available_with_metadata(self):
        self.assertTrue(self.payload["available"])
        self.assertEqual(self.payload["rule"], "source-coverage-v1")
        self.assertEqual(self.payload["metadata"]["origin"], "derived")
        fields = self.payload["metadata"]["source_fields"]
        self.assertIn("releases.source_file_ids", fields)
        self.assertIn("manifest.source_files.normalized_file_name", fields)

    def test_periods_are_quarters_newest_first(self):
        periods = [p["period"] for p in self.payload["periods"]]
        self.assertEqual(periods, sorted(periods, reverse=True))
        self.assertIn("2024-Q2", periods)
        # The unparsable file name lands in a visible bucket, not dropped.
        self.assertIn("unknown", periods)

    def test_release_links_counted_per_period(self):
        by_period = {p["period"]: p for p in self.payload["periods"]}
        # Both fixture releases link to pgf_fixture01 (2024-Q2).
        self.assertEqual(by_period["2024-Q2"]["release_links"], 2)
        self.assertEqual(by_period["2024-Q2"]["distinct_releases"], 2)
        self.assertEqual(by_period["2024-Q2"]["source_files"], 1)

    def test_observations_allocated_evenly(self):
        by_period = {p["period"]: p for p in self.payload["periods"]}
        # Single-file releases: full observation rows land on the period.
        # r1 supports 1 obs row, r2 supports 1 obs row.
        self.assertEqual(by_period["2024-Q2"]["observations"], 2)

    def test_issues_join_via_releases(self):
        by_period = {p["period"]: p for p in self.payload["periods"]}
        # pgdq_i1 and pgdq_i2 sit on r1 (file 1, 2024-Q2); pgdq_i3/i4 are
        # file-level with NULL release_id and must NOT be counted.
        self.assertEqual(by_period["2024-Q2"]["issues"], 2)
        # The unknown-period file has no release linkage yet: 0 issues.
        self.assertEqual(by_period["unknown"]["issues"], 0)

    def test_totals_are_consistent(self):
        totals = self.payload["totals"]
        self.assertEqual(totals["source_files"], 2)
        self.assertEqual(
            totals["release_links"],
            sum(p["release_links"] for p in self.payload["periods"]),
        )


class CoverageDegradationTests(unittest.TestCase):
    """Index unavailable → available:false, never a 500 or fake zeros."""

    def test_unavailable_when_index_absent(self):
        from backend.app.coverage import SourceCoverageService

        class _NoIndex:
            @staticmethod
            def _query(_paths, _sql, _params):
                return None

        service = SourceCoverageService(None, None, None, _NoIndex())
        payload = service.periods()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["periods"], [])
        self.assertEqual(payload["rule"], "source-coverage-v1")


class CoverageFixtureSanityTests(unittest.TestCase):
    """The process page still works with the enlarged fixture (guards the
    shared fixture: adding datasets must not break existing flows)."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_coverage_sanity_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_process_summary_still_resolves(self):
        response = self.client.get(f"/api/processes/{FIXTURE_PROCESS_ID}/summary")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["process_id"], FIXTURE_PROCESS_ID
        )
