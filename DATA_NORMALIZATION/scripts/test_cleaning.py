import json
import unittest
from pathlib import Path

import duckdb

from build_cleaned_parquet import (
    clean_text_expression,
    decimal_expression,
    timestamp_expression,
)


class CleaningExpressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rules_path = Path(__file__).resolve().parents[1] / "config" / "cleaning_rules.json"
        cls.rules = json.loads(rules_path.read_text(encoding="utf-8"))
        cls.connection = duckdb.connect()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.connection.close()

    def evaluate(self, expression, value):
        return self.connection.execute(
            f"SELECT {expression} FROM (SELECT ?::VARCHAR AS value)", [value]
        ).fetchone()[0]

    def test_null_literal_becomes_null(self) -> None:
        expression = clean_text_expression("value", self.rules)
        self.assertIsNone(self.evaluate(expression, " N/A "))

    def test_organization_whitespace_is_collapsed_and_trimmed(self) -> None:
        expression = clean_text_expression("procuring_entity_name", self.rules)
        actual = self.connection.execute(
            f"SELECT {expression} FROM (SELECT ?::VARCHAR AS procuring_entity_name)",
            ["  Example\u00a0  Agency\u00a0"],
        ).fetchone()[0]
        self.assertEqual(actual, "Example Agency")

    def test_status_mapping_is_explicit(self) -> None:
        expression = clean_text_expression("bid_notice_status", self.rules)
        actual = self.connection.execute(
            f"SELECT {expression} FROM (SELECT 'DisApproved' AS bid_notice_status)"
        ).fetchone()[0]
        self.assertEqual(actual, "Disapproved")

    def test_excel_timestamp_retains_time(self) -> None:
        actual = self.evaluate(timestamp_expression("value"), "43096.416666666664")
        self.assertEqual(str(actual), "2017-12-27 10:00:00")

    def test_item_budget_sentinel_becomes_null(self) -> None:
        expression = decimal_expression("value", "DECIMAL(38,4)", self.rules | {
            "numeric_null_sentinels": {"value": ["-1"]}
        })
        self.assertIsNone(self.evaluate(expression, "-1.00"))


if __name__ == "__main__":
    unittest.main()
