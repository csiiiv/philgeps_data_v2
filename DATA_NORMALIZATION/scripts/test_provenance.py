import unittest

from provenance import make_source_breadcrumb, make_source_row_id


class ProvenanceTests(unittest.TestCase):
    def test_source_row_id_is_deterministic_and_location_sensitive(self) -> None:
        digest = "a" * 64
        first = make_source_row_id(digest, 5, "Awards")
        self.assertEqual(first, make_source_row_id(digest, 5, "Awards"))
        self.assertNotEqual(first, make_source_row_id(digest, 6, "Awards"))
        self.assertNotEqual(first, make_source_row_id(digest, 5, "Other"))

    def test_csv_breadcrumb_uses_basename(self) -> None:
        self.assertEqual(
            make_source_breadcrumb("files/2024_Jan-Mar.csv", 12345),
            "2024_Jan-Mar.csv · row 12,345",
        )

    def test_excel_breadcrumb_includes_sheet(self) -> None:
        self.assertEqual(
            make_source_breadcrumb("files/awards.xlsx", 8201, "Awards"),
            "awards.xlsx · Awards · row 8,201",
        )

    def test_invalid_row_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_source_row_id("a" * 64, 0)


if __name__ == "__main__":
    unittest.main()
