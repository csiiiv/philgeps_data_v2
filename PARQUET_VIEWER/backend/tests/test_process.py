"""Process-explorer endpoint tests: detail, timeline, and child counts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import (
    FIXTURE_PROCESS_ID,
    FIXTURE_RELEASE_ID_1,
    FIXTURE_RELEASE_ID_2,
    build_project,
    make_client,
)


class ProcessDetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_detail_returns_identity_and_preferred_release(self):
        response = self.client.get(f"/api/processes/{FIXTURE_PROCESS_ID}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["process_id"], FIXTURE_PROCESS_ID)
        self.assertEqual(payload["source_process_identifier"], "REF-2024-001")
        self.assertEqual(payload["source_identifier_basis"], "observed_source")
        self.assertEqual(payload["release_count"], 2)
        # preferred + alternates come from compiled_processes
        self.assertEqual(payload["preferred_release_id"], FIXTURE_RELEASE_ID_1)
        self.assertEqual(payload["selection_basis"], "latest_content")
        self.assertEqual(payload["alternate_release_ids"], [FIXTURE_RELEASE_ID_2])
        self.assertTrue(payload["has_multiple_releases"])
        self.assertEqual(payload["compilation_rule_version"], "process-compilation-v1")

    def test_unknown_process_returns_404(self):
        response = self.client.get("/api/processes/pgcp_nope")
        self.assertEqual(response.status_code, 404)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "unknown_process")

    def test_timeline_orders_releases_chronologically(self):
        response = self.client.get(f"/api/processes/{FIXTURE_PROCESS_ID}/timeline")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["returned"], 2)
        dates = [r["release_date"] for r in payload["releases"]]
        self.assertEqual(dates, sorted(dates))
        # the preferred release is the later one
        self.assertEqual(payload["releases"][-1]["release_id"], FIXTURE_RELEASE_ID_1)
        # lifecycle flags present
        self.assertTrue(payload["releases"][0]["has_tender"])

    def test_child_counts_covers_registered_child_datasets(self):
        response = self.client.get(f"/api/releases/{FIXTURE_RELEASE_ID_1}/children")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("tenders", payload["counts"])
        self.assertEqual(payload["counts"]["tenders"]["count"], 1)
        self.assertEqual(payload["counts"]["tenders"]["record_type"], "tender")
        # all registered child datasets are reported
        self.assertEqual(payload["counts"]["parties"]["count"], 3)
        self.assertEqual(payload["counts"]["awards"]["count"], 2)
        self.assertEqual(payload["counts"]["contracts"]["count"], 1)

    def test_compare_releases_reports_tender_field_changes(self):
        # left = earlier alternate, right = preferred: title/status/amount changed.
        response = self.client.get(
            f"/api/processes/{FIXTURE_PROCESS_ID}/compare",
            params={
                "left": FIXTURE_RELEASE_ID_2,
                "right": FIXTURE_RELEASE_ID_1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["left"]["release_id"], FIXTURE_RELEASE_ID_2)
        self.assertEqual(payload["right"]["release_id"], FIXTURE_RELEASE_ID_1)
        tender = payload["tender"]
        self.assertTrue(tender["available"])
        self.assertEqual(tender["status"], "changed")
        by_field = {f["field"]: f for f in tender["fields"]}
        self.assertEqual(by_field["title"]["change"], "changed")
        self.assertEqual(by_field["title"]["left"], "Fixture tender title (draft)")
        self.assertEqual(by_field["title"]["right"], "Fixture tender title")
        self.assertEqual(by_field["value_amount"]["left"], "4500.0000")
        self.assertEqual(by_field["value_amount"]["right"], "5000.0000")
        self.assertEqual(by_field["bid_reference"]["change"], "unchanged")
        # Awards exist only on the preferred release → counted as added.
        self.assertEqual(payload["awards"]["summary"]["added"], 2)
        self.assertEqual(payload["awards"]["summary"]["removed"], 0)

    def test_compare_rejects_identical_release_ids(self):
        response = self.client.get(
            f"/api/processes/{FIXTURE_PROCESS_ID}/compare",
            params={
                "left": FIXTURE_RELEASE_ID_1,
                "right": FIXTURE_RELEASE_ID_1,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "invalid_compare")


class ProcessSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_fixture_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_summary_shows_human_fields(self):
        response = self.client.get(f"/api/processes/{FIXTURE_PROCESS_ID}/summary")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # researcher-facing content
        self.assertEqual(payload["title"], "Fixture tender title")
        self.assertEqual(payload["procuring_entity"], "Department of Fixture Works")
        self.assertEqual(
            payload["suppliers"],
            ["Gencorp Supplies Inc.", "Listed But Not Awarded Corp."],
        )
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["procurement_method"], "open")
        # PhilGEPS website IDs for document cross-checks
        self.assertEqual(payload["bid_reference"], "11495158")
        self.assertEqual(payload["award_structure"]["awards"][0]["award_reference"], "5708843")
        items = payload["item_structure"]
        self.assertEqual(items["item_total"], 3)
        self.assertEqual(items["items"][0]["line_item_number"], 1)
        self.assertEqual(items["items"][0]["title"], "Fixture line item A")
        self.assertEqual(items["items"][0]["budget"]["amount"], "3000.0000")
        self.assertEqual(items["items"][0]["unit_price"]["amount"], "300.0000")
        # value chain with recorded currency (never asserted PHP)
        self.assertEqual(payload["tender_value"]["amount"], "5000.0000")
        self.assertEqual(payload["tender_value"]["currency"], "PHP")
        self.assertEqual(payload["award_values"][0]["amount"], "4800.0000")
        self.assertEqual(payload["contract_values"][0]["currency"], "PHP")
        # dates
        self.assertEqual(payload["closing_date"], "2024-02-01")
        self.assertEqual(payload["award_dates"][0], "2024-02-05")
        # counts
        self.assertEqual(payload["supplier_count"], 2)
        self.assertEqual(payload["award_count"], 2)
        self.assertEqual(payload["contract_count"], 1)

    def test_summary_award_structure_discloses_splits(self):
        payload = self.client.get(
            f"/api/processes/{FIXTURE_PROCESS_ID}/summary"
        ).json()
        structure = payload["award_structure"]
        self.assertEqual(structure["award_total"], 2)
        # awards sorted by value descending: 4800 first
        self.assertEqual(structure["awards"][0]["value"]["amount"], "4800.0000")
        self.assertEqual(
            [s["name"] for s in structure["awards"][0]["suppliers"]],
            ["Gencorp Supplies Inc."],
        )
        gencorp = structure["awards"][0]["suppliers"][0]
        self.assertEqual(gencorp["observation_count"], 2)
        self.assertEqual(gencorp["duplicate_status"], "deduped")
        self.assertIn("source_row_deduped", gencorp["quality_flags"])
        # split award: two assertions on lot B (same name, differing JV —
        # not exact clones, so both kept and flagged as possible duplicates)
        lot_b = next(a for a in structure["awards"] if a["title"] == "Split lot B")
        self.assertEqual(len(lot_b["suppliers"]), 2)
        self.assertTrue(
            all(s["duplicate_status"] == "possible_duplicate" for s in lot_b["suppliers"])
        )
        self.assertEqual(lot_b["item_count"], 1)
        self.assertIn("items", lot_b)
        self.assertEqual(lot_b["items"][0]["title"], "Split lot B item")
        self.assertTrue(
            any(s["joint_venture"] for s in lot_b["suppliers"]),
            "JV annotation should surface on the split lot",
        )
        # listed-but-never-awarded supplier is called out separately
        self.assertEqual(structure["listed_not_awarded"], ["Listed But Not Awarded Corp."])
        self.assertEqual(structure["listed_not_awarded_total"], 1)
        self.assertEqual(
            structure["awarded_supplier_names"],
            ["Gencorp Supplies Inc.", "Splitter Trading"],
        )

    def test_summary_timeline_events_are_dated_and_ordered(self):
        payload = self.client.get(
            f"/api/processes/{FIXTURE_PROCESS_ID}/summary"
        ).json()
        timeline = payload["timeline"]
        self.assertTrue(timeline["branched"])
        self.assertEqual(len(timeline["branches"]), 2)
        spine_kinds = [e["kind"] for e in timeline["spine"]]
        self.assertIn("bid_published", spine_kinds)
        self.assertIn("closing", spine_kinds)
        # Award/contract milestones live on award lanes, not the shared spine
        self.assertNotIn("award_date", spine_kinds)
        closing = next(e for e in timeline["spine"] if e["kind"] == "closing")
        self.assertEqual(closing["items_role"], "not_awarded")
        self.assertEqual(closing["items"][0]["title"], "Unawarded lot C")

        events = payload["timeline_events"]
        self.assertGreaterEqual(len(events), 7)
        kinds = [e["kind"] for e in events]
        self.assertIn("bid_published", kinds)
        self.assertIn("closing", kinds)
        self.assertIn("award_date", kinds)
        self.assertIn("award_published", kinds)
        self.assertIn("notice_to_proceed", kinds)
        self.assertIn("contract_effectivity", kinds)
        self.assertIn("contract_end", kinds)
        date_fields = {e["date_field"] for e in events}
        self.assertIn("bid_published_date", date_fields)
        self.assertIn("award_date", date_fields)
        self.assertIn("award_published_date", date_fields)
        self.assertIn("contract_effectivity_date", date_fields)
        # Within each award lane, events are date-ordered
        for branch in timeline["branches"]:
            dates = [e["date"] for e in branch["events"] if e.get("date")]
            self.assertEqual(dates, sorted(dates))
            if branch["award_id"] == "pgaw_fixture01":
                self.assertTrue(
                    any(e["kind"] == "notice_to_proceed" for e in branch["events"]),
                    "Contract stops should nest under the matching award lane",
                )
        # every event names its PhilGEPS date field
        for event in events:
            self.assertIn("dataset", event)
            self.assertIn("record_id", event)
            self.assertIn("date_field", event)
            self.assertIn("date_label", event)
        # award detail carries supplier names and PhilGEPS award reference
        award_event = next(e for e in events if e["date_field"] == "award_date")
        self.assertIn("Gencorp Supplies Inc.", award_event["detail"])
        self.assertIn("Award ref", award_event["detail"])
        published = next(e for e in events if e["date_field"] == "bid_published_date")
        self.assertIn("Bid ref 11495158", published["detail"])
        award_with_items = next(e for e in events if e["date_field"] == "award_date")
        self.assertIn("items", award_with_items)
        self.assertGreaterEqual(len(award_with_items["items"]), 1)
        self.assertEqual(award_with_items["items"][0]["title"], "Fixture line item A")
        # award date and award published are separate stops when both exist
        self.assertNotEqual(
            next(e for e in events if e["date_field"] == "award_date")["date"],
            next(e for e in events if e["date_field"] == "award_published_date")["date"],
        )

    def test_summary_keeps_keys_nested_in_technical(self):
        payload = self.client.get(
            f"/api/processes/{FIXTURE_PROCESS_ID}/summary"
        ).json()
        # internal keys live under `technical`, not at top level
        self.assertNotIn("preferred_release_id", payload)
        self.assertEqual(
            payload["technical"]["preferred_release_id"], FIXTURE_RELEASE_ID_1
        )
        self.assertEqual(payload["technical"]["selection_basis"], "latest_content")
        self.assertIn("compilation_rule_version", payload["technical"])

    def test_summary_unknown_process_404(self):
        response = self.client.get("/api/processes/pgcp_missing/summary")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "unknown_process")


class SupplierCollapseTests(unittest.TestCase):
    """Exact clones collapse with a deduped mark; near-matches stay and flag."""

    def test_exact_clones_collapse_with_deduped_mark(self):
        from backend.app.process import ProcessService

        rows = [
            {
                "name": "Acme",
                "party_id": "p1",
                "joint_venture": None,
                "award_link_status": "matched",
                "party_link_status": "matched",
                "quality_flags": [],
            },
            {
                "name": "Acme",
                "party_id": "p1",
                "joint_venture": None,
                "award_link_status": "matched",
                "party_link_status": "matched",
                "quality_flags": [],
            },
        ]
        collapsed = ProcessService._collapse_supplier_assertions(rows)
        self.assertEqual(len(collapsed), 1)
        self.assertEqual(collapsed[0]["observation_count"], 2)
        self.assertEqual(collapsed[0]["duplicate_status"], "deduped")
        self.assertIn("source_row_deduped", collapsed[0]["quality_flags"])

    def test_differing_fields_kept_as_possible_duplicates(self):
        from backend.app.process import ProcessService

        rows = [
            {
                "name": "Acme",
                "party_id": "p1",
                "joint_venture": "JV A",
                "award_link_status": "matched",
                "party_link_status": "matched",
                "quality_flags": [],
            },
            {
                "name": "Acme",
                "party_id": "p1",
                "joint_venture": None,
                "award_link_status": "matched",
                "party_link_status": "matched",
                "quality_flags": [],
            },
        ]
        collapsed = ProcessService._collapse_supplier_assertions(rows)
        self.assertEqual(len(collapsed), 2)
        self.assertTrue(
            all(item["duplicate_status"] == "possible_duplicate" for item in collapsed)
        )
        self.assertTrue(
            all(item["observation_count"] == 1 for item in collapsed)
        )


if __name__ == "__main__":
    unittest.main()
