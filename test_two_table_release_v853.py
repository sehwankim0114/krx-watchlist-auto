"""Production consent, missing-data, transport budget and mutation regressions."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

import test_stock_table_metrics_v850 as fixture
import two_table_release_v853 as release
from build_two_table_shadow_v851 import encode, read, sha, publish as publish_shadow


class ReleaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.BuilderIntegrationTest.setUpClass()
        cls.seed = fixture.BuilderIntegrationTest.repo

    @classmethod
    def tearDownClass(cls):
        fixture.BuilderIntegrationTest.tearDownClass()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        shutil.copytree(self.seed, self.repo)
        self.target = self.repo / "api" / release.DIRECTORY
        (self.repo / "config").mkdir(exist_ok=True)
        (self.repo / release.CONFIG_PATH).write_bytes(encode(release.RELEASE))
        self.status(status="READY", official_fresh_now=True, safe_to_analyze_as_latest=True)

    def tearDown(self):
        self.temp.cleanup()

    def status(self, **changes):
        path = self.repo / "api/status.json"
        p = read(path); p.update(changes); path.write_bytes(encode(p))

    def publish(self):
        return release.publish(self.repo)

    def check(self):
        return release.validate_bundle(self.target, self.repo)

    def tamper(self, change, name="kospi.compact.1.json"):
        path = self.target / name
        p = read(path); change(p); raw = encode(p); path.write_bytes(raw)
        mpath = self.target / "manifest.json"; m = read(mpath)
        m["files"][name] = {"sha256": sha(raw), "bytes": len(raw)}
        mpath.write_bytes(encode(m))

    def test_fresh_requires_explicit_config(self):
        (self.repo / release.CONFIG_PATH).unlink()
        with self.assertRaisesRegex(ValueError, "EXPLICIT_CONFIG_REQUIRED"):
            self.publish()
        self.assertFalse(self.target.exists())

    def test_disabled_or_forged_config_rejected(self):
        for changes in ({"enabled": False}, {"enabled": 1}, {"unavailable_fields": []}, {"standalone_swing_table_enabled": True}):
            p = {**release.RELEASE, **changes}
            (self.repo / release.CONFIG_PATH).write_bytes(encode(p))
            with self.assertRaisesRegex(ValueError, "CONFIG_MISMATCH"):
                self.publish()

    def test_fresh_layout_ready_with_explicit_missing(self):
        m = self.publish()
        self.assertEqual(m["status"], "READY")
        self.assertTrue(m["production_activation_allowed"])
        for n in m["files"]:
            p = read(self.target / n)
            self.assertEqual(p["contract"], release.calculation_contract())
            self.assertEqual(p["explicit_missing"], release.MISSING)
        self.check()

    def test_no_fabricated_score_with_rehashed_payload(self):
        self.publish()
        self.tamper(lambda p: p["rows"][0]["metrics"].update(investment_score_100=88), "kospi.json")
        with self.assertRaisesRegex(ValueError, "UNSOURCED_FIELD"):
            self.check()

    def test_stale_remains_blocked(self):
        self.status(official_fresh_now=False, safe_to_analyze_as_latest=False)
        m = self.publish()
        self.assertEqual(m["status"], "STALE_SOURCE")
        self.assertFalse(m["production_activation_allowed"])
        self.check()

    def test_unsynchronized_publishes_empty_blocked_bundle(self):
        self.publish()
        self.status(api_sync_ok=False)
        m = self.publish()
        self.assertEqual(m["status"], "BLOCKED_SOURCE_SYNC")
        self.assertEqual(m["files"], {})
        self.assertEqual(list(self.target.iterdir()), [self.target / "manifest.json"])

    def test_read_only_check_and_old_inputs_preserved(self):
        sources = ["api/status.json", "api/kospi_watchlist.json", "latest/universe_raw_history_latest.csv"]
        before = {n: (self.repo / n).read_bytes() for n in sources}
        self.publish()
        self.assertEqual(before, {n: (self.repo / n).read_bytes() for n in sources})
        saved = {p.name: p.read_bytes() for p in self.target.iterdir()}
        self.check()
        self.assertEqual(saved, {p.name: p.read_bytes() for p in self.target.iterdir()})

    def test_shadow_upgrade_is_explicit_and_idempotent(self):
        publish_shadow(self.repo)
        self.publish(); self.publish(); self.check()

    def test_rehashed_gate_missing_disclosure_and_contract_tampering_rejected(self):
        for change in (lambda p: p.update(production_activation_allowed=1),
                       lambda p: p.update(explicit_missing=[]),
                       lambda p: p["contract"].update(release_stage="PREVIEW_ONLY"),
                       lambda p: p["display_contract"].update(coverage="COMPLETE")):
            self.publish(); self.tamper(change)
            with self.assertRaises(ValueError):
                self.check()

    def test_checksum_and_source_mismatch(self):
        self.publish()
        p = self.target / "kospi.compact.1.json"
        p.write_bytes(p.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "CHECKSUM"):
            self.check()
        self.publish(); self.status(build_id="wrong")
        with self.assertRaisesRegex(ValueError, "METADATA_source_build_id"):
            self.check()

    def test_oversize_transport_headroom_rejected(self):
        self.publish(); self.tamper(lambda p: p.update(padding="x" * 29000))
        with self.assertRaisesRegex(ValueError, "TRANSPORT_HEADROOM"):
            self.check()

    def test_unknown_existing_file_not_deleted(self):
        self.publish()
        p = self.target / "user-notes.txt"; p.write_text("keep")
        with self.assertRaisesRegex(ValueError, "UNOWNED_FILE"):
            self.publish()
        self.assertEqual(p.read_text(), "keep")

    def test_symlink_target_rejected(self):
        outside = Path(self.temp.name) / "outside"; outside.mkdir()
        self.target.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "TARGET_INVALID"):
            self.publish()

    def test_three_exact_commands_use_one_existing_operation(self):
        routes = release.command_routes()
        self.assertEqual([r["parameters"]["table"] for r in routes], ["kospi", "decliners", "decliners24"])
        self.assertEqual({r["operation_id"] for r in routes}, {"getKospiWatchlist"})
        self.assertTrue(all(r["legacy_fallback_allowed"] is False for r in routes))


if __name__ == "__main__":
    unittest.main()
