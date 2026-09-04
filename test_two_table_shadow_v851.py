"""Offline publication, identity, pagination, and failure-mode regressions."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import test_stock_table_metrics_v850 as fixtures
from build_two_table_shadow_v851 import (
    DIRECTORY, GATES, VERSION, encode, publish, read, sha, validate_bundle,
)


class ShadowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.BuilderIntegrationTest.setUpClass()
        cls.seed = fixtures.BuilderIntegrationTest.repo

    @classmethod
    def tearDownClass(cls):
        fixtures.BuilderIntegrationTest.tearDownClass()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        shutil.copytree(self.seed, self.repo)
        self.target = self.repo / "api" / DIRECTORY

    def tearDown(self):
        self.temp.cleanup()

    def status(self, **changes):
        p = self.repo / "api/status.json"
        value = read(p)
        value.update(changes)
        p.write_bytes(encode(value))

    def check(self):
        return validate_bundle(self.target, self.repo)

    def snapshot(self):
        return {p.relative_to(self.repo).as_posix(): p.read_bytes()
                for p in self.repo.rglob("*") if p.is_file() and ".git" not in p.parts
                and DIRECTORY not in p.parts}

    def tamper_payload(self, name, change):
        path = self.target / name
        value = read(path)
        change(value)
        raw = encode(value)
        path.write_bytes(raw)
        manifest_path = self.target / "manifest.json"
        manifest = read(manifest_path)
        manifest["files"][name] = {"sha256": sha(raw), "bytes": len(raw)}
        manifest_path.write_bytes(encode(manifest))

    def test_old_api_source_files_untouched(self):
        before = self.snapshot()
        manifest = publish(self.repo)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(manifest["tables"]["kospi"]["row_count"], 30)
        self.assertEqual(set(manifest["tables"]), {"kospi", "decliners", "decliners24"})
        self.check()

    def test_fresh_is_still_inactive(self):
        self.status(status="READY", official_fresh_now=True, safe_to_analyze_as_latest=True)
        manifest = publish(self.repo)
        self.assertEqual(manifest["status"], "SHADOW_READY")
        for name in [*manifest["files"], "manifest.json"]:
            for key, value in GATES.items():
                self.assertEqual(read(self.target / name)[key], value)

    def test_stale_source_remains_stale(self):
        self.assertEqual(publish(self.repo)["status"], "SHADOW_STALE")
        self.assertFalse(self.check()["safe_to_analyze_as_latest"])

    def test_runtime_freshness_change_never_activates_snapshot(self):
        self.status(status="READY", official_fresh_now=True, safe_to_analyze_as_latest=True)
        publish(self.repo)
        self.status(status="STALE_OFFICIAL", official_fresh_now=False, safe_to_analyze_as_latest=False,
                    computed_expected_official_trading_date="2099-01-01")
        self.assertFalse(self.check()["safe_to_analyze_as_latest"])

    def test_check_only_changes_nothing(self):
        publish(self.repo)
        before = {p.name: p.read_bytes() for p in self.target.iterdir()}
        self.check()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.target.iterdir()})

    def test_source_build_rules_and_date_mismatch_rejected(self):
        publish(self.repo)
        status = read(self.repo / "api/status.json")
        for key in ("build_id", "rules_version", "rules_sha256", "confirmed_basis_date"):
            self.status(**{key: "wrong"})
            with self.assertRaisesRegex(ValueError, "MANIFEST_"):
                self.check()
            (self.repo / "api/status.json").write_bytes(encode(status))

    def test_strict_input_hashes_detect_modified_sources(self):
        publish(self.repo)
        path = self.repo / "latest/universe_raw_history_latest.csv"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "SOURCE_CHANGED"):
            validate_bundle(self.target, self.repo, strict_source_hashes=True)

    def test_upstream_sync_failure_clears_tables_to_blocked(self):
        publish(self.repo)
        self.status(api_sync_ok=False)
        manifest = publish(self.repo)
        self.assertEqual(manifest["status"], "BLOCKED_SOURCE_SYNC")
        self.assertEqual([p.name for p in self.target.iterdir()], ["manifest.json"])
        self.check()

    def test_critical_upstream_error_blocks(self):
        self.status(critical_errors=["fixture error"])
        self.assertEqual(publish(self.repo)["status"], "BLOCKED_SOURCE_SYNC")
        self.check()

    def test_blocked_bundle_cannot_be_reused_after_source_recovers(self):
        self.status(api_sync_ok=False)
        publish(self.repo)
        self.status(api_sync_ok=True)
        with self.assertRaisesRegex(ValueError, "REBUILD_REQUIRED"):
            self.check()

    def test_failed_calculation_preserves_previous_bundle(self):
        publish(self.repo)
        before = {p.name: p.read_bytes() for p in self.target.iterdir()}
        path = self.repo / "api/kospi_watchlist.json"
        value = read(path); value["build_id"] = "wrong"; path.write_bytes(encode(value))
        with self.assertRaisesRegex(ValueError, "BUILD_ID_MISMATCH"):
            publish(self.repo)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.target.iterdir()})

    def test_unknown_file_is_preserved_and_blocks_publish(self):
        publish(self.repo)
        note = self.target / "user-note.txt"
        note.write_text("keep me")
        with self.assertRaisesRegex(ValueError, "UNOWNED_FILE"):
            publish(self.repo)
        self.assertEqual(note.read_text(), "keep me")

    def test_symlink_target_rejected(self):
        outside = Path(self.temp.name) / "outside"; outside.mkdir()
        self.target.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "TARGET_SYMLINK"):
            publish(self.repo)
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlink_child_rejected(self):
        publish(self.repo)
        link = self.target / "decliners.compact.2.json"
        link.symlink_to(self.repo / "api/status.json")
        before = (self.repo / "api/status.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "TARGET_CHILD_INVALID"):
            publish(self.repo)
        self.assertEqual(before, (self.repo / "api/status.json").read_bytes())

    def test_another_generator_version_not_overwritten(self):
        publish(self.repo)
        path = self.target / "manifest.json"
        p = read(path); p["version"] = "future-owner"; path.write_bytes(encode(p))
        with self.assertRaisesRegex(ValueError, "OWNERSHIP_VERSION_MISMATCH"):
            publish(self.repo)

    def test_obsolete_owned_page_cleanup(self):
        publish(self.repo)
        old = self.target / "decliners.compact.2.json"
        old.write_text("obsolete generated page")
        publish(self.repo)
        self.assertFalse(old.exists())
        self.check()

    def test_tampering_detected_by_checksum(self):
        publish(self.repo)
        path = self.target / "kospi.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "CHECKSUM"):
            self.check()

    def test_compact_row_order_and_values_checked_beyond_hash(self):
        publish(self.repo)
        self.tamper_payload("kospi.compact.1.json", lambda p: p["rows"].reverse())
        with self.assertRaisesRegex(ValueError, "COMPACT_VALUES_OR_ORDER"):
            self.check()

    def test_missing_page_rejected(self):
        publish(self.repo)
        (self.target / "decliners.compact.1.json").unlink()
        with self.assertRaisesRegex(ValueError, "FILE_SET_MISMATCH"):
            self.check()

    def test_empty_matches_have_one_empty_page(self):
        manifest = publish(self.repo)
        for label in ("decliners", "decliners24"):
            self.assertEqual(manifest["tables"][label]["row_count"], 0)
            self.assertEqual(manifest["tables"][label]["pages"], [label + ".compact.1.json"])
        self.check()

    def test_forged_offline_current_price_is_rejected(self):
        publish(self.repo)
        self.tamper_payload("kospi.json", lambda p: p["rows"][0].update(request_time_price=1234))
        with self.assertRaisesRegex(ValueError, "OFFLINE_LIVE_PRICE_FORBIDDEN"):
            self.check()

    def test_oversized_page_rejected(self):
        publish(self.repo)
        self.tamper_payload("kospi.compact.1.json", lambda p: p.update(extra="x" * 30000))
        with self.assertRaisesRegex(ValueError, "PAGE_TOO_LARGE"):
            self.check()

    def test_accidental_activation_rejected(self):
        publish(self.repo)
        self.tamper_payload("kospi.json", lambda p: p.update(production_activation_allowed=True))
        with self.assertRaisesRegex(ValueError, "PAYLOAD_production_activation_allowed"):
            self.check()


if __name__ == "__main__":
    unittest.main(verbosity=2)
