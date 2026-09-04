"""Explicit, fail-closed publication of the new table layout (not a new score).

V850 calculations and V851 shadow regressions remain unchanged. Production
requires a reviewed release file; unavailable fundamentals stay unavailable.
"""
from __future__ import annotations

import argparse
import copy
import os
import tempfile
from pathlib import Path

import build_two_table_shadow_v851 as shadow
from stock_table_metrics_v850 import CONTRACT

DIRECTORY = shadow.DIRECTORY
VERSION = "2026-09-04-v8.5.3-two-table-layout-release"
INSTRUCTIONS_VERSION = "2026-09-04-v6.9.0-two-table-layout"
SCHEMA_VERSION = "7.1.0"
CONFIG_PATH = "config/two_table_release.json"
MISSING = ["investment_score_100", "earnings_outlook_change", "rs_sector", "confirmed_swing_low_stop"]
RELEASE = {
    "version": VERSION, "enabled": True, "standalone_swing_table_enabled": False,
    "scope": "LAYOUT_AND_VERIFIED_INDICATORS_WITH_DECLARED_GAPS",
    "unavailable_fields": MISSING, "missing_score_policy": "NO_SCORE_NO_AUTO_BUY_UPGRADE",
}
DISPLAY = {
    "version": VERSION, "coverage": "PARTIAL_DECLARED",
    "unavailable_fields": MISSING, "missing_label": "자료 미제공",
    "investment_score_100": "NOT_AVAILABLE_DO_NOT_RESCALE_LEGACY_SCORE",
    "recommendation_floor": "OBSERVE_NOT_AUTOMATIC_BUY",
    "request_time_prices": "REQUIRED_10_5_2_NO_STATIC_FALLBACK",
    "historical_metrics": "OFFICIAL_CLOSE_ONLY_DO_NOT_RECALCULATE_WITH_LIVE_QUOTES",
    "standalone_swing_table_enabled": False,
}
DISCLOSURE = "새 양식·검증 지표 제공. 100점 점수·실적전망·업종RS·확정 스윙손절 미제공. 현재가는 별도 조회."


def require(ok, message):
    if not ok:
        raise ValueError("TWO_TABLE_RELEASE_" + message)


def release_config(repo):
    path = Path(repo) / CONFIG_PATH
    require(path.is_file() and not path.is_symlink(), "EXPLICIT_CONFIG_REQUIRED")
    value = shadow.read(path)
    require(shadow.encode(value) == shadow.encode(RELEASE), "CONFIG_MISMATCH")
    return value


def metadata(status):
    synced = status.get("api_sync_ok") is True and not status.get("critical_errors")
    fresh = synced and status.get("official_fresh_now") is True and status.get("safe_to_analyze_as_latest") is True
    return {
        "version": VERSION, **shadow.source_identity(status),
        "release_stage": "PRODUCTION", "production_activation_allowed": bool(fresh),
        "custom_gpt_route_enabled": bool(fresh), "safe_to_analyze_as_latest": bool(fresh),
        "standalone_swing_table_enabled": False, "current_time_freshness_recheck_required": True,
        "status": "READY" if fresh else ("BLOCKED_SOURCE_SYNC" if not synced else "STALE_SOURCE"),
        "display_contract": DISPLAY, "disclosure": DISCLOSURE,
    }


def calculation_contract():
    return {**CONTRACT, "release_stage": "PRODUCTION", "layout_release_version": VERSION,
            "metric_coverage": "PARTIAL_DECLARED"}


def to_shadow(payload, status):
    """Validation-only projection into the preserved V851 structural checker."""
    p = copy.deepcopy(payload)
    p.update({"version": shadow.VERSION, **shadow.GATES})
    p["status"] = ("BLOCKED_SOURCE_SYNC" if status.get("api_sync_ok") is not True or status.get("critical_errors")
                   else "SHADOW_READY" if status.get("official_fresh_now") is True and status.get("safe_to_analyze_as_latest") is True
                   else "SHADOW_STALE")
    if "contract" in p:
        p["contract"] = copy.deepcopy(CONTRACT)
    return p


def validate_bundle(directory, repo, strict_source_hashes=False):
    """Verify real checksums/gates first, then all existing row/filter contracts."""
    directory, repo = Path(directory), Path(repo)
    release_config(repo)
    require(directory.is_dir() and not directory.is_symlink(), "DIRECTORY_INVALID")
    require(not (directory / "manifest.json").is_symlink(), "MANIFEST_SYMLINK")
    manifest = shadow.read(directory / "manifest.json")
    status = shadow.read(repo / "api/status.json")
    expected = metadata(status)
    files = manifest.get("files")
    require(isinstance(files, dict) and all(shadow.FILE_PATTERN.fullmatch(n) for n in files), "FILE_LIST_INVALID")
    require({p.name for p in directory.iterdir()} == set(files) | {"manifest.json"}, "FILE_SET_MISMATCH")
    with tempfile.TemporaryDirectory(prefix="two-table-validate-") as temp:
        projected = Path(temp)
        projected_manifest = to_shadow(manifest, status)
        for name in [*files, "manifest.json"]:
            path = directory / name
            require(path.is_file() and not path.is_symlink(), "FILE_INVALID:" + name)
            raw = path.read_bytes()
            if name != "manifest.json":
                require(files[name] == {"sha256": shadow.sha(raw), "bytes": len(raw)}, "CHECKSUM:" + name)
                if ".compact." in name:
                    require(len(raw) <= 28500, "TRANSPORT_HEADROOM:" + name)
            p = shadow.read(path)
            for key, value in expected.items():
                require(shadow.encode(p.get(key)) == shadow.encode(value), "METADATA_" + key + ":" + name)
            if name == "manifest.json":
                continue
            require(p.get("contract") == calculation_contract(), "CALCULATION_CONTRACT:" + name)
            require(p.get("explicit_missing") == MISSING, "MISSING_FIELDS:" + name)
            transformed = shadow.encode(to_shadow(p, status))
            (projected / name).write_bytes(transformed)
            projected_manifest["files"][name] = {"sha256": shadow.sha(transformed), "bytes": len(transformed)}
        (projected / "manifest.json").write_bytes(shadow.encode(projected_manifest))
        shadow.validate_bundle(projected, repo, strict_source_hashes)
    return manifest


def publish(repo):
    repo = Path(repo).resolve()
    release_config(repo)
    api = repo / "api"
    target = api / DIRECTORY
    require(api.is_dir() and not api.is_symlink() and not target.is_symlink(), "TARGET_INVALID")
    if target.exists():
        require(target.is_dir(), "TARGET_NOT_DIRECTORY")
        for p in target.iterdir():
            require(p.is_file() and not p.is_symlink() and
                    (p.name == "manifest.json" or shadow.FILE_PATTERN.fullmatch(p.name)), "UNOWNED_FILE")
        require(shadow.read(target / "manifest.json").get("version") in (shadow.VERSION, VERSION), "OWNERSHIP_VERSION")
    with tempfile.TemporaryDirectory(prefix="two-table-release-") as temp:
        staging = Path(temp)
        manifest = shadow.prepare(repo, staging)
        meta = metadata(shadow.read(repo / "api/status.json"))
        manifest.update(meta)
        manifest["pending"] = MISSING + ["MANUAL_GPT_REPLACEMENT_AND_END_TO_END_DISPLAY_TEST"]
        for name in manifest["files"]:
            p = shadow.read(staging / name)
            p.update(meta)
            p["contract"] = calculation_contract()
            raw = shadow.encode(p)
            (staging / name).write_bytes(raw)
            manifest["files"][name] = {"sha256": shadow.sha(raw), "bytes": len(raw)}
        (staging / "manifest.json").write_bytes(shadow.encode(manifest))
        validate_bundle(staging, repo, strict_source_hashes=True)
        target.mkdir(exist_ok=True)
        previous = {p.name for p in target.iterdir()}
        names = sorted(manifest["files"]) + ["manifest.json"]
        for name in names:
            with tempfile.NamedTemporaryFile(dir=target, prefix=".pending-", delete=False) as f:
                pending = Path(f.name)
                f.write((staging / name).read_bytes())
            try:
                os.replace(pending, target / name)
            finally:
                pending.unlink(missing_ok=True)
        for name in previous - set(names):
            require(bool(shadow.FILE_PATTERN.fullmatch(name)), "UNOWNED_CLEANUP")
            (target / name).unlink()
    return validate_bundle(target, repo, strict_source_hashes=True)


def command_routes():
    return [{"command": command, "operation_id": "getKospiWatchlist", "path": "/tables/v1/{table}",
             "parameters": {"table": table}, "api_file": "api/two_table_v1/" + table + ".json",
             "format_version": VERSION, "all_pages_required": True, "legacy_fallback_allowed": False}
            for command, table in (("코피표", "kospi"), ("연속하락표", "decliners"), ("2.4연속하락표", "decliners24"))]


def attach_routes(contract):
    routes = command_routes()
    contract["two_table_release"] = {"version": VERSION, "routes": routes,
        "core_command_count": 13, "additional_command_count": 2, "effective_command_count": 15,
        "activation_requires_fresh_worker_response": True, "standalone_swing_table_enabled": False}
    kospi = next(r for r in contract["commands"] if r["command"] == "코피표")
    kospi.update(routes[0])
    kospi["operation_ids"] = ["getKospiWatchlist"]
    return contract


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    result = (validate_bundle(args.repo / "api" / DIRECTORY, args.repo)
              if args.check_only else publish(args.repo))
    print("V853_TWO_TABLE_RELEASE_CONTRACT=PASS")
    print("TWO_TABLE_RELEASE_STATUS=" + result["status"])
    print("PRODUCTION_ACTIVATION_ALLOWED=" + str(result["production_activation_allowed"]).lower())
    print("INCOMPLETE_METRICS_EXPLICIT=true")
    print("STANDALONE_SWING_TABLE_ENABLED=false")


if __name__ == "__main__":
    main()
