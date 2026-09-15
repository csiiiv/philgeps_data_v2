"""Tests for the item-level award-linkage view (docs/11 Phase 2).

The Items tab separates awarded from unawarded line items using award_items
evidence, per the §16 rule: linkage is only labeled when evidence exists —
zero linkage rows must not read as "unawarded" (docs/13).

Run with the project's standard runner:
    python -m unittest discover -s backend\\tests
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURE_PROCESS_ID, build_project, make_client


class ItemLinkageTests(unittest.TestCase):
    """item_structure carries per-item award linkage and a rollup."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="pgview_itemlink_"))
        build_project(cls.root)
        cls.client = make_client(cls.root)
        response = cls.client.get(
            f"/api/processes/{FIXTURE_PROCESS_ID}/summary"
        )
        cls.payload = response.json()
        cls.items = cls.payload["item_structure"]["items"]

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_rollup_present(self):
        structure = self.payload["item_structure"]
        self.assertTrue(structure["linkage_evidence"])
        self.assertEqual(structure["linked_count"], 2)
        self.assertEqual(structure["unlinked_count"], 1)

    def test_linked_item_names_its_awards(self):
        linked = [
            i for i in self.items if i["award_link"]["state"] == "linked"
        ]
        self.assertEqual(len(linked), 2)
        for item in linked:
            self.assertTrue(item["award_link"]["award_ids"])
            self.assertEqual(
                item["award_link"]["metadata"]["rule"],
                "relationship-status-v1",
            )

    def test_unlinked_item_marked_missing_not_awarded(self):
        unlinked = [
            i for i in self.items if i["award_link"]["state"] == "missing"
        ]
        # Fixture: pgti_i3 'Unawarded lot C' has no award_items row.
        self.assertEqual([i["item_id"] for i in unlinked], ["pgti_i3"])
        self.assertEqual(unlinked[0]["award_link"]["award_ids"], [])
        self.assertEqual(
            unlinked[0]["award_link"]["metadata"]["confidence"],
            "provisional",
        )

    def test_counts_agree_with_items(self):
        structure = self.payload["item_structure"]
        self.assertEqual(
            structure["linked_count"] + structure["unlinked_count"],
            len(self.items),
        )
