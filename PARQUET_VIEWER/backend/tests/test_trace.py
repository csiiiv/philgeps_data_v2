"""Traceability endpoint tests: breadcrumb resolution and record-source lookup."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import (
    FIXTURE_DOCUMENT_ID,
    FIXTURE_RELEASE_ID_1,
    FIXTURE_SOURCE_FILE_ID,
    FIXTURE_SOURCE_URL,
    build_project,
    make_client,
)


class BreadcrumbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_breadcrumb_resolves_full_audit_path(self):
        response = self.client.get(
            f"/api/breadcrumbs/{FIXTURE_SOURCE_FILE_ID}/3"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # manifest metadata
        self.assertEqual(payload["manifest"]["status"], "found")
        self.assertEqual(payload["manifest"]["normalized_file_name"], "2024-04--2024-06.csv")
        self.assertEqual(payload["manifest"]["document_titles"], ["Fixture source distribution"])
        self.assertEqual(payload["manifest"]["source_url"], FIXTURE_SOURCE_URL)
        # complete observations
        self.assertIn("_source_row_number", payload["normalized_observation"])
        self.assertEqual(payload["normalized_observation"]["notice_title"], "pgti_i1")
        # cleaned layer has typed decimal
        self.assertEqual(payload["cleaned_observation"]["approved_budget"], "1000.0000")
        # derived records reverse lookup
        self.assertGreaterEqual(payload["derived_record_count"], 1)
        self.assertEqual(payload["derived_records"][0]["record_type"], "tender_item")
        self.assertEqual(payload["derived_records"][0]["record_id"], "pgti_i1")

    def test_breadcrumb_side_by_side_layers_differ(self):
        response = self.client.get(f"/api/breadcrumbs/{FIXTURE_SOURCE_FILE_ID}/3").json()
        normalized_budget = response["normalized_observation"]["approved_budget"]
        cleaned_budget = response["cleaned_observation"]["approved_budget"]
        # normalized keeps the raw string; cleaned is a typed decimal string
        self.assertEqual(normalized_budget, "1000")
        self.assertEqual(cleaned_budget, "1000.0000")

    def test_unknown_breadcrumb_returns_404(self):
        response = self.client.get("/api/breadcrumbs/pgf_nope/999")
        self.assertEqual(response.status_code, 404)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "unknown_breadcrumb")

    def test_breadcrumb_clearly_labels_physical_row(self):
        response = self.client.get(
            f"/api/breadcrumbs/{FIXTURE_SOURCE_FILE_ID}/3"
        ).json()
        self.assertEqual(response["breadcrumb"]["source_row_number"], 3)
        # The UI contract: row numbers are physical source rows, not parquet positions
        self.assertNotIn("parquet_row", response["breadcrumb"])


class RecordSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_record_sources_returns_breadcrumbs_with_manifest_names(self):
        response = self.client.get("/api/records/tender_item/pgti_i1/sources")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["record_type"], "tender_item")
        self.assertGreaterEqual(payload["returned"], 1)
        source = payload["sources"][0]
        self.assertEqual(source["source_file_id"], FIXTURE_SOURCE_FILE_ID)
        self.assertEqual(source["normalized_file_name"], "2024-04--2024-06.csv")

    def test_unknown_record_returns_404(self):
        response = self.client.get("/api/records/tender_item/pgti_missing/sources")
        self.assertEqual(response.status_code, 200)  # zero sources is a valid answer
        self.assertEqual(response.json()["returned"], 0)

    def test_invalid_record_type_returns_400(self):
        response = self.client.get("/api/records/not_a_type/pgti_i1/sources")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "invalid_record_type")


class LineageRoundTripTests(unittest.TestCase):
    """A record's breadcrumb must resolve back to the same record."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_round_trip_record_to_breadcrumb_to_derived(self):
        sources = self.client.get(
            "/api/records/tender_item/pgti_i2/sources"
        ).json()
        self.assertGreaterEqual(sources["returned"], 1)
        first = sources["sources"][0]
        crumb = self.client.get(
            f"/api/breadcrumbs/{first['source_file_id']}/{first['source_row_number']}"
        ).json()
        ids = {r["record_id"] for r in crumb["derived_records"]}
        self.assertIn("pgti_i2", ids)

class ProvenanceCacheTests(unittest.TestCase):
    """The disposable cache must be transparent, correct, and safely deletable."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_record_sources_response_reports_cache_state(self):
        payload = self.client.get("/api/records/tender_item/pgti_i1/sources").json()
        # fixture project builds the cache synchronously at startup (tiny data)
        self.assertEqual(payload["cache"], "hit")

    def test_cache_file_is_inside_cache_directory(self):
        # trigger the lazy build with a real lookup first
        self.client.get("/api/records/tender_item/pgti_i1/sources").raise_for_status()
        cache_dir = self.root / ".cache"
        self.assertTrue((cache_dir / "provenance.duckdb").exists())
        import duckdb
        connection = duckdb.connect(str(cache_dir / "provenance.duckdb"), read_only=True)
        try:
            row = connection.execute("SELECT count(*) FROM sources").fetchone()
            self.assertEqual(row[0], 9)  # fixture record_sources row count
            meta = dict(
                connection.execute("SELECT key, value FROM meta").fetchall()
            )
            self.assertIn("fingerprint", meta)
            self.assertIn("row_count", meta)
        finally:
            connection.close()

    def test_lookup_via_cache_matches_direct_scan(self):
        import duckdb
        cache_dir = self.root / ".cache"
        direct = duckdb.connect()
        try:
            direct_rows = direct.execute(
                """
                SELECT release_id, source_file_id, source_sheet, source_row_number
                FROM read_parquet(?)
                WHERE record_type = 'tender_item' AND record_id = 'pgti_i1'
                """,
                [str(self.root / "parquets" / "record_sources.parquet")],
            ).fetchall()
        finally:
            direct.close()
        connection = duckdb.connect(str(cache_dir / "provenance.duckdb"), read_only=True)
        try:
            from backend.app.provenance import make_record_key

            cache_rows = connection.execute(
                """
                SELECT release_id, source_file_id, source_sheet, source_row_number
                FROM sources
                WHERE record_key = ?
                """,
                [make_record_key("tender_item", "pgti_i1")],
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(sorted(direct_rows), sorted(cache_rows))

    def test_delete_cache_mid_life_falls_back_and_rebuilds(self):
        import duckdb
        cache_dir = self.root / ".cache"
        db = cache_dir / "provenance.duckdb"
        # build it, then delete it
        self.client.get("/api/records/tender_item/pgti_i1/sources").raise_for_status()
        self.assertTrue(db.exists())
        db.unlink()
        # direct-scan fallback still answers correctly
        payload = self.client.get("/api/records/tender_item/pgti_i1/sources").json()
        self.assertEqual(payload["cache"], "hit")  # tiny fixture rebuilds inline
        self.assertEqual(payload["returned"], 1)
        # and the cache file was rebuilt inside .cache
        self.assertTrue(db.exists())
        connection = duckdb.connect(str(db), read_only=True)
        try:
            row = connection.execute("SELECT count(*) FROM sources").fetchone()
            self.assertEqual(row[0], 9)
        finally:
            connection.close()


class ReleaseSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_release_sources_reports_file_rows_and_urls(self):
        response = self.client.get(f"/api/releases/{FIXTURE_RELEASE_ID_1}/sources")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload["files"]), 1)
        entry = payload["files"][0]
        self.assertEqual(entry["source_file_id"], FIXTURE_SOURCE_FILE_ID)
        self.assertEqual(entry["normalized_file_name"], "2024-04--2024-06.csv")
        self.assertEqual(entry["first_row"], 101)
        self.assertEqual(entry["last_row"], 105)
        self.assertEqual(entry["row_refs"], 6)
        self.assertEqual(entry["record_types"], 5)
        self.assertEqual(entry["source_url"], FIXTURE_SOURCE_URL)

    def test_release_sources_unknown_release_is_empty(self):
        response = self.client.get("/api/releases/pgrl_none/sources")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["files"], [])
        self.assertEqual(payload["returned"], 0)


if __name__ == "__main__":
    unittest.main()
