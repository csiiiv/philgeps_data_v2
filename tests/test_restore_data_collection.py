"""Tests for restore_data_collection.py (runs entirely in a temp sandbox).

Run from the repo root:

    python -m unittest discover -s tests -v

The tests build a miniature fake repo + DATA_COLLECTION archive in a
temp directory (a few KB of plain text files), invoke the restore
script's CLI entry point, and assert on file locations and exit codes.
No production data is touched.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "restore_data_collection.py"

_spec = importlib.util.spec_from_file_location("restore_data_collection", SCRIPT)
restore = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("restore_data_collection", restore)
_spec.loader.exec_module(restore)

STAR_TABLES = restore.STAR_TABLES
TRANSFERS = restore.TRANSFERS
TRACKED_CHECKS = restore.TRACKED_CHECKS


class SandboxTest(unittest.TestCase):
    """Each test gets a fresh fake repo + archive in a temp directory."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.archive = self.root / "DATA_COLLECTION"
        self.build_archive()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- sandbox construction ------------------------------------------------

    def build_archive(self, marker: str = "original") -> None:
        """Create a miniature, complete DATA_COLLECTION archive."""
        self.archive.mkdir(parents=True, exist_ok=True)
        for rel, _ in TRANSFERS:
            path = self.archive / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}:{}".format(marker, rel), encoding="utf-8")
        for rel, _ in TRACKED_CHECKS:
            path = self.archive / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("tracked:{}".format(rel), encoding="utf-8")

    def archive_file(self, rel: str) -> Path:
        return self.archive / rel

    def target_file(self, rel_target: str) -> Path:
        return self.root / rel_target

    def run_cli(self, *argv: str) -> int:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            return restore.main(list(argv))

    # -- tests -----------------------------------------------------------------

    def test_move_transfers_all_data_files(self):
        rc = self.run_cli("--repo-root", str(self.root))
        self.assertEqual(rc, 0)
        for rel_source, rel_target in TRANSFERS:
            target = self.target_file(rel_target)
            self.assertTrue(target.is_file(), "missing target {}".format(rel_target))
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "original:{}".format(rel_source),
                "wrong content at {}".format(rel_target),
            )
            self.assertFalse(
                self.archive_file(rel_source).exists(),
                "archive copy should be removed in move mode: {}".format(rel_source),
            )
        # git-tracked copies must NOT be moved out of the archive
        for rel, _ in TRACKED_CHECKS:
            self.assertTrue(self.archive_file(rel).is_file(),
                            "tracked copy should stay in archive: {}".format(rel))

    def test_keep_source_copies_without_deleting(self):
        rc = self.run_cli("--repo-root", str(self.root), "--keep-source")
        self.assertEqual(rc, 0)
        for rel_source, rel_target in TRANSFERS:
            self.assertTrue(self.target_file(rel_target).is_file())
            self.assertTrue(self.archive_file(rel_source).is_file(),
                            "archive copy must survive --keep-source")

    def test_rerun_is_skip_not_conflict(self):
        self.run_cli("--repo-root", str(self.root), "--keep-source")
        rc = self.run_cli("--repo-root", str(self.root))
        self.assertEqual(rc, 0, "identical targets must skip, not conflict")

    def test_conflict_blocks_without_force(self):
        # Populate targets, then rebuild the archive with different bytes.
        self.run_cli("--repo-root", str(self.root), "--keep-source")
        self.build_archive(marker="changed")
        rc = self.run_cli("--repo-root", str(self.root))
        self.assertEqual(rc, 3, "differing targets must exit 3 without --force")
        # nothing overwritten: target still holds the original bytes
        rel_source, rel_target = TRANSFERS[0]
        self.assertEqual(self.target_file(rel_target).read_text(encoding="utf-8"),
                         "original:{}".format(rel_source))

    def test_force_overwrites_conflicts(self):
        self.run_cli("--repo-root", str(self.root), "--keep-source")
        self.build_archive(marker="changed")
        rc = self.run_cli("--repo-root", str(self.root), "--force")
        self.assertEqual(rc, 0)
        rel_source, rel_target = TRANSFERS[0]
        self.assertEqual(self.target_file(rel_target).read_text(encoding="utf-8"),
                         "changed:{}".format(rel_source))

    def test_incomplete_archive_fails_fast(self):
        (self.archive / "philgeps_normalized.parquet").unlink()
        rc = self.run_cli("--repo-root", str(self.root))
        self.assertEqual(rc, 2)
        # nothing transferred: no target may exist
        for _, rel_target in TRANSFERS:
            self.assertFalse(self.target_file(rel_target).exists(),
                             "partial transfer on incomplete archive: {}".format(rel_target))

    def test_missing_archive_dir_is_error(self):
        import shutil
        shutil.rmtree(self.archive)
        rc = self.run_cli("--repo-root", str(self.root))
        self.assertEqual(rc, 2)

    def test_dry_run_touches_nothing(self):
        rc = self.run_cli("--repo-root", str(self.root), "--dry-run")
        self.assertEqual(rc, 0)
        for rel_source, rel_target in TRANSFERS:
            self.assertFalse(self.target_file(rel_target).exists(),
                             "dry-run must not create targets")
            self.assertTrue(self.archive_file(rel_source).exists(),
                            "dry-run must not consume archive")

    def test_tracked_counterparts_match_and_report(self):
        # Place matching tracked counterparts in the fake repo.
        for rel_source, rel_target in TRACKED_CHECKS:
            target = self.target_file(rel_target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((self.archive / rel_source).read_bytes())
        rc = self.run_cli("--repo-root", str(self.root))
        self.assertEqual(rc, 0)

    def test_report_json_written(self):
        report_path = self.root / "restore_report.json"
        self.run_cli("--repo-root", str(self.root), "--report", str(report_path))
        self.assertTrue(report_path.is_file())
        import json
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["conflicts"], 0)
        self.assertEqual(len(payload["plan"]), len(TRANSFERS))
        self.assertEqual(len(payload["tracked"]), len(TRACKED_CHECKS))


if __name__ == "__main__":
    unittest.main()
