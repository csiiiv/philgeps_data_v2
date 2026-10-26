import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURE_PROCESS_ID, FIXTURE_RELEASE_ID_1, build_project, make_client


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


class SearchSortTests(unittest.TestCase):
    """Server-side result ordering over the FULL match population."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_sort_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_sort_echoed_in_payload(self):
        payload = self.client.get(
            "/api/search",
            params={"q": "Fixture tender", "sort": "closing_date:asc"},
        ).json()
        self.assertEqual(
            payload["sort"], {"column": "closing_date", "direction": "asc"}
        )

    def test_default_payload_sort_is_null(self):
        payload = self.client.get(
            "/api/search", params={"q": "Fixture tender"}
        ).json()
        self.assertIsNone(payload["sort"])

    def test_sort_procuring_entity_and_region(self):
        for column in ("procuring_entity", "region", "awardee"):
            payload = self.client.get(
                "/api/search",
                params={"q": "Fixture tender", "sort": f"{column}:asc"},
            ).json()
            self.assertEqual(
                payload["sort"], {"column": column, "direction": "asc"}
            )
            self.assertEqual(
                payload["procurements"][0]["procuring_entity"],
                "Department of Fixture Works",
            )

    def test_procurement_cards_include_buyer_and_region(self):
        payload = self.client.get(
            "/api/search", params={"q": "Fixture tender"}
        ).json()
        card = payload["procurements"][0]
        self.assertEqual(card["procuring_entity"], "Department of Fixture Works")
        # Fixture parties have no source_region column.
        self.assertIsNone(card["region"])

    def test_procurement_cards_include_top_awardee(self):
        payload = self.client.get(
            "/api/search", params={"q": "Fixture tender"}
        ).json()
        card = payload["procurements"][0]
        # Gencorp won 4800, Splitter Trading won 1500: Gencorp is top.
        self.assertEqual(card["awardee"], "Gencorp Supplies Inc.")

    def test_sort_title_ascending_orders_results(self):
        payload = self.client.get(
            "/api/search", params={"q": "Fixture", "sort": "title"}
        ).json()
        titles = [card["title"] for card in payload["procurements"]]
        self.assertEqual(titles, sorted(titles))

    def test_sort_award_value_descending_orders_nulls_last(self):
        payload = self.client.get(
            "/api/search", params={"q": "Fixture", "sort": "award_value_amount:desc"}
        ).json()
        cards = payload["procurements"]
        values = [
            float(card["award_value_amount"])
            for card in cards
            if card["award_value_amount"] is not None
        ]
        self.assertEqual(values, sorted(values, reverse=True))
        # Nulls (no awards / mixed currency) must sort after valued rows.
        if any(card["award_value_amount"] is None for card in cards):
            self.assertIsNone(cards[-1]["award_value_amount"])

    def test_sort_rejects_unknown_column(self):
        response = self.client.get(
            "/api/search", params={"q": "Fixture tender", "sort": "banana"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"]["code"], "invalid_search"
        )

    def test_sort_rejects_unknown_direction(self):
        response = self.client.get(
            "/api/search", params={"q": "Fixture tender", "sort": "title:sideways"}
        )
        self.assertEqual(response.status_code, 400)

    def test_party_page_sort_orders_cards(self):
        payload = self.client.get(
            "/api/parties/name/Department of Fixture Works",
            params={"sort": "title:asc"},
        ).json()
        self.assertEqual(
            payload["sort"], {"column": "title", "direction": "asc"}
        )
        titles = [card["title"] for card in payload["procurements"]]
        self.assertEqual(titles, sorted(titles))

    def test_party_page_sort_by_supplier_award(self):
        payload = self.client.get(
            "/api/parties/name/Gencorp Supplies Inc.",
            params={"sort": "supplier_award_value_amount:desc"},
        ).json()
        self.assertEqual(
            payload["sort"],
            {"column": "supplier_award_value_amount", "direction": "desc"},
        )
        card = payload["procurements"][0]
        self.assertEqual(card["supplier_award_value_amount"], "4800.0000")
        # Search endpoint must still reject the party-only column.
        rejected = self.client.get(
            "/api/search",
            params={"q": "Fixture", "sort": "supplier_award_value_amount:desc"},
        )
        self.assertEqual(rejected.status_code, 400)

    def test_sort_is_cached_separately(self):
        plain = self.client.get("/api/search", params={"q": "Fixture tender"})
        sorted_req = self.client.get(
            "/api/search", params={"q": "Fixture tender", "sort": "title:asc"}
        )
        # Same query, different sort: fresh result, not the plain cache hit.
        self.assertNotIn("cached", sorted_req.json())
        repeat = self.client.get(
            "/api/search", params={"q": "Fixture tender", "sort": "title:asc"}
        )
        self.assertTrue(repeat.json()["cached"])


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

    def test_search_cards_carry_awarded_amount(self):
        # Preferred release awards: 4800 + 1500 PHP -> awarded total 6300.
        payload = self.client.get(
            "/api/search", params={"q": "Fixture tender"}
        ).json()
        card = payload["procurements"][0]
        self.assertEqual(float(card["award_value_amount"]), 6300.0)
        self.assertEqual(card["award_value_currency"], "PHP")

    def test_party_page_stats_split_tender_and_awarded_value(self):
        # Gencorp: tenders seen via its processes (5000) vs distinct awards
        # naming it (4800 — pgaw_fixture01 only; pgaw_fixture02 names
        # Splitter Trading). Award grain, supplier-assertion attribution.
        payload = self.client.get(
            "/api/parties/name/Gencorp Supplies Inc."
        ).json()
        stats = payload["stats"]
        self.assertEqual(stats["awarded_total"], "4800.0000")
        self.assertEqual(stats["awarded_currency"], "PHP")
        self.assertTrue(stats["awarded_comparable"])
        # Tender total unchanged (one process, 5000 PHP notice value).
        self.assertEqual(stats["total_value"], "5000.0000")

    def test_party_page_cards_carry_awarded_amount(self):
        payload = self.client.get(
            "/api/parties/name/Department of Fixture Works"
        ).json()
        card = payload["procurements"][0]
        self.assertEqual(float(card["award_value_amount"]), 6300.0)
        # Buyer is not an award supplier — supplier-scoped amount is null.
        self.assertIsNone(card["supplier_award_value_amount"])
        self.assertFalse(card["supplier_award_shared"])

    def test_party_page_supplier_award_is_party_scoped(self):
        # Process total 6300; Gencorp only won pgaw_fixture01 (4800).
        payload = self.client.get(
            "/api/parties/name/Gencorp Supplies Inc."
        ).json()
        self.assertGreaterEqual(len(payload["procurements"]), 1)
        card = payload["procurements"][0]
        self.assertEqual(float(card["award_value_amount"]), 6300.0)
        self.assertEqual(card["supplier_award_value_amount"], "4800.0000")
        self.assertEqual(card["supplier_award_value_currency"], "PHP")
        self.assertFalse(card["supplier_award_shared"])

    def test_party_page_shared_supplier_award_is_flagged(self):
        # Add a co-supplier on Gencorp's exclusive lot so the award is shared.
        import duckdb as _duckdb

        root = Path(tempfile.mkdtemp(prefix="pgview_shared_award_"))
        build_project(root)
        parquet = root / "parquets" / "award_suppliers.parquet"
        con = _duckdb.connect()
        con.execute(
            f"""
            COPY (
                SELECT * FROM (VALUES
                    ('pgsa_fixture01', '{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture01',
                     'pgpt_supplier', 'Gencorp Supplies Inc.', NULL,
                     'matched', 'matched', NULL),
                    ('pgsa_fixture01c', '{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture01',
                     'pgpt_partner', 'Partner Co.', NULL,
                     'matched', 'matched', NULL),
                    ('pgsa_fixture02', '{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture02',
                     'pgpt_supplier2', 'Splitter Trading', 'JV with Partner Co.',
                     'matched', 'matched', NULL)
                ) AS t(award_supplier_assertion_id, release_id, award_id,
                       party_id, source_supplier_label, source_joint_venture,
                       award_link_status, party_link_status, supplier_quality_flags)
            ) TO '{str(parquet).replace(chr(39), chr(39) * 2)}' (FORMAT PARQUET)
            """
        )
        con.close()
        client = make_client(root)
        try:
            payload = client.get(
                "/api/parties/name/Gencorp Supplies Inc."
            ).json()
            card = payload["procurements"][0]
            self.assertEqual(float(card["award_value_amount"]), 6300.0)
            # Still only Gencorp's lot (4800), but shared with Partner Co.
            self.assertEqual(card["supplier_award_value_amount"], "4800.0000")
            self.assertTrue(card["supplier_award_shared"])
            self.assertEqual(card["supplier_award_co_suppliers"], 2)
        finally:
            client.close()

    def test_mixed_currency_awards_report_null_awarded_total(self):
        # Build a one-off fixture project with a mixed-currency award pair
        # to prove the honest-currency rule: NULL, never a cross-sum.
        import duckdb as _duckdb

        root = Path(tempfile.mkdtemp(prefix="pgview_mixed_"))
        build_project(root)
        awards_path = root / "parquets" / "awards.parquet"
        con = _duckdb.connect()
        con.execute(
            f"""
            COPY (
                SELECT * FROM (VALUES
                    ('{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture01', '5708843',
                     'Fixture award',
                     CAST('4800.0000' AS DECIMAL(38,4)), 'PHP',
                     TIMESTAMP '2024-02-05 00:00:00', DATE '2024-02-06'),
                    ('{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture02', '5708844',
                     'Split lot B',
                     CAST('100.0000' AS DECIMAL(38,4)), 'USD',
                     TIMESTAMP '2024-02-06 00:00:00', DATE '2024-02-06')
                ) AS t(release_id, award_id, source_award_reference, title,
                       value_amount, value_currency, date, date_published)
            ) TO '{str(awards_path).replace(chr(39), chr(39) * 2)}' (FORMAT PARQUET)
            """
        )
        con.close()
        # Stale the index so the next search rebuilds from the new awards.
        index_path = root / ".cache" / "search_index.duckdb"
        if index_path.exists():
            index_path.unlink()
        client = make_client(root)
        try:
            payload = client.get(
                "/api/search", params={"q": "Fixture tender"}
            ).json()
            card = payload["procurements"][0]
            self.assertIsNone(card["award_value_amount"])
            self.assertIsNone(card["award_value_currency"])
        finally:
            client.close()

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
