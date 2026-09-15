import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURE_PROCESS_ID, build_project, make_client


class SearchEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_search_finds_procurement_by_title_fragment(self):
        response = self.client.get("/api/search", params={"q": "Fixture tender"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["procurements"]), 1)
        card = payload["procurements"][0]
        self.assertEqual(card["process_id"], FIXTURE_PROCESS_ID)
        self.assertEqual(card["title"], "Fixture tender title")
        self.assertEqual(card["status"], "complete")

    def test_search_finds_party_by_name_fragment(self):
        response = self.client.get("/api/search", params={"q": "Fixture Works"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        party_names = [p["name"] for p in payload["parties"]]
        self.assertIn("Department of Fixture Works", party_names)
        card = next(p for p in payload["parties"]
                    if p["name"] == "Department of Fixture Works")
        self.assertIn("procuringEntity", card["roles"])
        self.assertEqual(card["release_count"], 1)

    def test_search_is_case_insensitive(self):
        response = self.client.get("/api/search", params={"q": "fixture tender"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["procurements"]), 1)

    def test_search_repeat_is_cached(self):
        self.client.get("/api/search", params={"q": "Fixture tender"})
        response = self.client.get("/api/search", params={"q": "Fixture tender"})
        self.assertTrue(response.json()["cached"])

    def test_search_no_results_reports_empty_lists(self):
        response = self.client.get("/api/search", params={"q": "zz no match zz"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["procurements"], [])
        self.assertEqual(payload["parties"], [])

    def test_search_rejects_short_query(self):
        response = self.client.get("/api/search", params={"q": "a"})
        self.assertEqual(response.status_code, 422)  # FastAPI Query validation

    def test_search_result_shapes_do_not_leak_child_keys(self):
        payload = self.client.get("/api/search", params={"q": "Fixture"}).json()
        for card in payload["procurements"]:
            self.assertNotIn("release_id", card)
            self.assertNotIn("tender_id", card)
        for card in payload["parties"]:
            self.assertNotIn("party_id", card)

    def test_search_reports_index_state(self):
        payload = self.client.get("/api/search", params={"q": "Fixture tender"}).json()
        # Fixtures are small: the index builds inline and answers the search.
        self.assertEqual(payload["index"], "hit")

    def test_search_reports_totals(self):
        payload = self.client.get("/api/search", params={"q": "Fixture tender"}).json()
        self.assertEqual(payload["procurement_total"], 1)
        self.assertEqual(payload["party_total"], 0)

    def test_search_filter_status_excludes_non_matching(self):
        # Fixture tender status is "complete": filtering to "cancelled"
        # must return zero procurements.
        response = self.client.get(
            "/api/search",
            params={"q": "Fixture tender", "status": "cancelled"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["procurement_total"], 0)
        self.assertEqual(payload["procurements"], [])
        # Filters are echoed back so the UI can stay in sync.
        self.assertEqual(payload["filters"]["statuses"], ["cancelled"])

    def test_search_filter_status_none_matches_null_status(self):
        # The fixture tender has a recorded status; "none" (unrecorded)
        # must therefore not match it.
        response = self.client.get(
            "/api/search",
            params={"q": "Fixture tender", "status": "none"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["procurement_total"], 0)

    def test_search_filter_year_range(self):
        # Fixture closing_date is 2024-02-01: inside 2020-2024, outside 2025+.
        inside = self.client.get(
            "/api/search",
            params={"q": "Fixture tender", "year_from": 2020, "year_to": 2024},
        ).json()
        self.assertEqual(inside["procurement_total"], 1)
        outside = self.client.get(
            "/api/search",
            params={"q": "Fixture tender", "year_from": 2025},
        ).json()
        self.assertEqual(outside["procurement_total"], 0)

    def test_search_filter_unknown_status_is_ignored(self):
        payload = self.client.get(
            "/api/search",
            params={"q": "Fixture tender", "status": "bogus"},
        ).json()
        # Unknown statuses are dropped, not treated as a match-all/no-match.
        self.assertEqual(payload["procurement_total"], 1)
        self.assertEqual(payload["filters"]["statuses"], [])

    def test_search_filters_are_cached_separately(self):
        # Warm both variants first: the suite runs tests that already cached
        # the plain query, so only the differential behavior is asserted.
        self.client.get("/api/search", params={"q": "Fixture tender"})
        filtered = self.client.get(
            "/api/search", params={"q": "Fixture tender", "status": "complete"}
        )
        # Same query, different filters: fresh result, not the plain cache hit.
        self.assertNotIn("cached", filtered.json())
        repeat = self.client.get(
            "/api/search", params={"q": "Fixture tender", "status": "complete"}
        )
        self.assertTrue(repeat.json()["cached"])

    def test_facets_report_status_and_year_counts(self):
        response = self.client.get("/api/search/facets")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["available"])
        statuses = {entry["status"]: entry["count"] for entry in payload["statuses"]}
        self.assertEqual(statuses.get("complete"), 1)
        years = {entry["year"]: entry["count"] for entry in payload["years"]}
        self.assertEqual(years.get(2024), 1)

    def test_search_parties_paginate_independently(self):
        # Party windowing must be independent of the procurement page:
        # party_page=1 returns the second window without disturbing page 0.
        first = self.client.get(
            "/api/search", params={"q": "Fixture"}
        ).json()
        self.assertGreaterEqual(first["party_total"], 1)
        self.assertEqual(first["party_page"], 0)
        second = self.client.get(
            "/api/search", params={"q": "Fixture", "party_page": 1}
        ).json()
        self.assertEqual(second["party_page"], 1)
        # Fixture has 3 parties (< PARTY_LIMIT): page 1 is empty but valid.
        self.assertEqual(second["parties"], [])


class ProcessEnhancementTests(unittest.TestCase):
    """Quality flag help + award-vs-tender ratio on the process summary."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_summary_reports_award_vs_tender_ratio(self):
        payload = self.client.get(
            f"/api/processes/{FIXTURE_PROCESS_ID}/summary"
        ).json()
        avt = payload["award_vs_tender"]
        self.assertTrue(avt["comparable"])
        # Fixture: tender 5000 PHP, awards 4800 + 1500 = 6300 PHP -> 126%.
        self.assertEqual(avt["tender_amount"], "5000.0000")
        self.assertEqual(avt["award_currency"], "PHP")
        self.assertEqual(avt["award_total"], "6300.0000")
        self.assertEqual(avt["ratio_percent"], 126)
        self.assertEqual(avt["contract_total"], "4800.0000")

    def test_summary_includes_quality_flags(self):
        payload = self.client.get(
            f"/api/processes/{FIXTURE_PROCESS_ID}/summary"
        ).json()
        self.assertIsInstance(payload["quality_flags"], list)

    def test_party_page_includes_stats(self):
        payload = self.client.get(
            "/api/parties/name/Department of Fixture Works"
        ).json()
        stats = payload["stats"]
        self.assertEqual(
            stats["role_split"], [{"role": "procuringEntity", "count": 1}]
        )
        # One procurement closing in 2024, status complete, value 5000.
        self.assertEqual(
            stats["status_counts"], [{"status": "complete", "count": 1}]
        )
        self.assertEqual(stats["value_over_time"][0]["year"], 2024)
        self.assertEqual(stats["value_over_time"][0]["count"], 1)
        self.assertEqual(stats["value_over_time"][0]["value"], "5000.0000")
        self.assertEqual(stats["value_currency"], "PHP")
        self.assertTrue(stats["value_comparable"])

    def test_party_stats_identity_scope_aggregates_variants(self):
        exact = self.client.get(
            "/api/parties/name/Department of Fixture Works",
            params={"scope": "name"},
        ).json()
        identity = self.client.get(
            "/api/parties/name/Department of Fixture Works",
            params={"scope": "identity"},
        ).json()
        # Identity scope counts strictly more rows (both spellings).
        self.assertGreaterEqual(
            identity["stats"]["status_counts"][0]["count"],
            exact["stats"]["status_counts"][0]["count"],
        )

    def test_party_identity_full_shape(self):
        payload = self.client.get(
            "/api/parties/name/Department of Fixture Works/identity"
        ).json()
        self.assertIn("name_key", payload)
        self.assertIn("variants", payload)
        self.assertIn("canonical", payload)
        self.assertIn("other_name_forms", payload)
        self.assertIn("unresolved_candidates", payload)
        # The fixture project has no identity-resolution parquets, so the
        # endpoint must degrade honestly instead of 500-ing.
        self.assertIn("available", payload)

    def test_identity_payload_is_json_serializable_with_list_columns(self):
        # Regression: identity queries over parquets with LIST columns
        # (identity_quality_flags) once returned numpy arrays that FastAPI
        # could not serialize (500 on the real DIGITAL INTERFACE data).
        # _jsonable must coerce them to plain Python values.
        from backend.app.search import SearchService

        self.assertEqual(SearchService._jsonable(["a", "b"]), ["a", "b"])
        self.assertEqual(SearchService._jsonable("plain"), "plain")
        if __import__("numpy").ndarray is not None:
            import numpy as np

            self.assertEqual(
                SearchService._jsonable(np.array(["x", "y"])), ["x", "y"]
            )
            self.assertEqual(SearchService._jsonable(np.int64(7)), 7)

    def test_party_contracts_by_year_shape(self):
        payload = self.client.get(
            "/api/parties/name/Gencorp Supplies Inc.",
            params={"scope": "name"},
        ).json()
        contracts = payload["contracts_by_year"]
        # Fixture has one contract (2024-02-10) linked to the supplier award.
        self.assertTrue(contracts["available"])
        self.assertEqual(
            contracts["years"],
            [{"year": 2024, "count": 1, "value": "4800.0000"}],
        )


class PartyPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_party_page_lists_procurement_cards(self):
        response = self.client.get("/api/parties/name/Department of Fixture Works")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["name"], "Department of Fixture Works")
        self.assertEqual(payload["total"], 1)
        card = payload["procurements"][0]
        self.assertEqual(card["title"], "Fixture tender title")
        self.assertEqual(card["process_id"], FIXTURE_PROCESS_ID)

    def test_party_page_unknown_name_is_empty_not_error(self):
        response = self.client.get("/api/parties/name/No Such Party")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["procurements"], [])

    def test_party_page_identity_scope_widens_to_spelling_variants(self):
        # "Department of Fixture Works" (release 1) and "DEPARTMENT OF FIXTURE
        # WORKS" (release 2) share a name_key: identity scope must include
        # both spellings' processes; exact-name scope must not.
        exact = self.client.get(
            "/api/parties/name/Department of Fixture Works",
            params={"scope": "name"},
        ).json()
        self.assertEqual(exact["scope"], "name")
        self.assertEqual(exact["total"], 1)
        # Both spellings are reported as variants of one identity.
        self.assertIn("Department of Fixture Works", exact["variants"])
        self.assertIn("DEPARTMENT OF FIXTURE WORKS", exact["variants"])

        identity = self.client.get(
            "/api/parties/name/Department of Fixture Works",
            params={"scope": "identity"},
        ).json()
        self.assertEqual(identity["scope"], "identity")
        self.assertGreaterEqual(identity["total"], exact["total"])

    def test_party_page_rejects_unknown_scope(self):
        response = self.client.get(
            "/api/parties/name/Department of Fixture Works",
            params={"scope": "everything"},
        )
        self.assertEqual(response.status_code, 422)  # FastAPI pattern validation


class SearchIndexDisposalTests(unittest.TestCase):
    """The index is disposable: deleting the file must degrade, not break."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_delete_index_falls_back_and_rebuilds(self):
        warm = self.client.get("/api/search", params={"q": "Fixture tender"})
        self.assertEqual(warm.status_code, 200)
        self.assertEqual(warm.json()["index"], "hit")
        # The cache database lives under the fixture's .cache directory.
        index_path = self.root / ".cache" / "search_index.duckdb"
        self.assertTrue(index_path.exists())
        index_path.unlink()
        rebuilt = self.client.get("/api/search", params={"q": "Fixture tender"})
        self.assertEqual(rebuilt.status_code, 200)
        self.assertEqual(rebuilt.json()["index"], "hit")
