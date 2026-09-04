import copy
import unittest

from validate_daily_integrated_health_v731 import worker_build_rollout_mode


class RolloutHealthTest(unittest.TestCase):
    def setUp(self):
        self.shadow = {
            "version": "2026-09-04-v8.5.1-scheduled-two-table-shadow",
            "release_stage": "SCHEDULED_SHADOW_ONLY",
            "production_activation_allowed": False,
            "custom_gpt_route_enabled": False,
            "safe_to_analyze_as_latest": False,
            "standalone_swing_table_enabled": False,
        }
        self.old = {"build_version": "1.3.9-kospi-action-compact-v2"}
        self.new = {"build_version": "1.4.0-two-table-guarded-preview", "two_table_proxy": {
            "version": "1", "page_limit_bytes": 30000, "page_limit_rows": 30,
            "sha256_required": True, "later_pages_require_build_id": True,
            "cache_mode": "NO_STORE_CONTROL_RECHECK", "values_recalculated": False,
            "standalone_swing_table_enabled": False,
            "paths": ["/tables/v1/kospi", "/tables/v1/decliners", "/tables/v1/decliners24"],
        }}

    def test_known_legacy_only_while_shadow_inactive(self):
        self.assertEqual(worker_build_rollout_mode(self.old, self.shadow), "LEGACY_ALLOWED_SHADOW_ONLY")

    def test_legacy_never_accepted_after_any_activation_flag(self):
        for key in ("production_activation_allowed", "custom_gpt_route_enabled", "safe_to_analyze_as_latest", "standalone_swing_table_enabled"):
            p = dict(self.shadow); p[key] = True
            self.assertEqual(worker_build_rollout_mode(self.old, p), "UNSUPPORTED_OR_ACTIVATION_MISMATCH")

    def test_missing_manifest_cannot_authorize_legacy(self):
        self.assertEqual(worker_build_rollout_mode(self.old, {}), "UNSUPPORTED_OR_ACTIVATION_MISMATCH")

    def test_unknown_dataset_version_cannot_authorize_legacy(self):
        p = dict(self.shadow, version="future-contract")
        self.assertEqual(worker_build_rollout_mode(self.old, p), "UNSUPPORTED_OR_ACTIVATION_MISMATCH")

    def test_new_worker_requires_all_guard_metadata(self):
        self.assertEqual(worker_build_rollout_mode(self.new, self.shadow), "CURRENT_GUARDED_WORKER")
        for key in self.new["two_table_proxy"]:
            p = copy.deepcopy(self.new); p["two_table_proxy"].pop(key)
            self.assertEqual(worker_build_rollout_mode(p, self.shadow), "UNSUPPORTED_OR_ACTIVATION_MISMATCH")

    def test_looser_payload_limit_not_accepted(self):
        p = copy.deepcopy(self.new); p["two_table_proxy"]["page_limit_bytes"] = 45000
        self.assertEqual(worker_build_rollout_mode(p, self.shadow), "UNSUPPORTED_OR_ACTIVATION_MISMATCH")

    def test_unknown_build_not_accepted_by_version_prefix(self):
        self.assertEqual(worker_build_rollout_mode({"build_version": "1.4.0-unknown"}, self.shadow), "UNSUPPORTED_OR_ACTIVATION_MISMATCH")

    def test_new_worker_does_not_depend_on_legacy_exception(self):
        p = dict(self.shadow, release_stage="PRODUCTION", production_activation_allowed=True)
        self.assertEqual(worker_build_rollout_mode(self.new, p), "CURRENT_GUARDED_WORKER")


if __name__ == "__main__":
    unittest.main(verbosity=2)
