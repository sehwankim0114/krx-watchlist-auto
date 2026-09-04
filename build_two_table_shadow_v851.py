"""Publish an inactive two-table dataset alongside, never over, the live API.

V8.5.1 wires the tested V8.5.0 calculations into the regular API build. This
is a data-preparation stage, NOT a Worker route or Custom GPT activation.
All generated files live in the owned api/two_table_v1 directory. GitHub
publishes a validated bundle in one commit; the manifest is written last.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from build_stock_table_preview_v850 import build, compact_row, ticker
from stock_table_metrics_v850 import matches_decliners24


VERSION = "2026-09-04-v8.5.1-scheduled-two-table-shadow"
DIRECTORY = "two_table_v1"
TABLES = ("kospi", "decliners", "decliners24")
PAGE_LIMIT = 30000
FILE_PATTERN = re.compile(r"(?:kospi|decliners|decliners24)(?:\.compact\.[1-9][0-9]*)?\.json")
GATES = {
    "release_stage": "SCHEDULED_SHADOW_ONLY",
    "production_activation_allowed": False,
    "custom_gpt_route_enabled": False,
    "standalone_swing_table_enabled": False,
    "safe_to_analyze_as_latest": False,
    "current_time_freshness_recheck_required": True,
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def source_identity(status):
    return {"source_build_id": status.get("build_id"),
            "source_rules_version": status.get("rules_version"),
            "source_rules_sha256": status.get("rules_sha256"),
            "basis_date": status.get("confirmed_basis_date")}


def require(condition, message):
    if not condition:
        raise ValueError("TWO_TABLE_SHADOW_" + message)


def validate_bundle(directory, repo, strict_source_hashes=False):
    """Read-only validation; time-varying source freshness is not cached truth."""
    directory, repo = Path(directory), Path(repo)
    require(directory.is_dir() and not directory.is_symlink(), "DIRECTORY_INVALID")
    require(not (directory / "manifest.json").is_symlink(), "MANIFEST_SYMLINK")
    manifest = read(directory / "manifest.json")
    status = read(repo / "api/status.json")
    require(manifest.get("version") == VERSION, "VERSION_MISMATCH")
    for k, v in {**GATES, **source_identity(status)}.items():
        require(manifest.get(k) == v and type(manifest.get(k)) is type(v), "MANIFEST_" + k)
    files = manifest.get("files")
    require(isinstance(files, dict), "FILE_LIST_INVALID")
    require(all(FILE_PATTERN.fullmatch(n) for n in files), "FILE_NAME_INVALID")
    actual = {p.name for p in directory.iterdir()}
    require(actual == set(files) | {"manifest.json"}, "FILE_SET_MISMATCH")
    if manifest.get("status") == "BLOCKED_SOURCE_SYNC":
        require(not files and not manifest.get("tables"), "BLOCKED_DATA_PRESENT")
        require(status.get("api_sync_ok") is not True or bool(status.get("critical_errors")),
                "BLOCKED_SOURCE_NOW_READY_REBUILD_REQUIRED")
        return manifest
    require(manifest.get("status") in ("SHADOW_READY", "SHADOW_STALE"), "STATUS_INVALID")
    require(status.get("api_sync_ok") is True and not status.get("critical_errors"), "SOURCE_NOT_SYNCED")
    require(all(source_identity(status).values()), "SOURCE_IDENTITY_MISSING")
    tables = manifest.get("tables", {})
    require(set(tables) == set(TABLES), "TABLE_SET_MISMATCH")
    if strict_source_hashes:
        for name, expected in manifest["source_sha256"].items():
            path = repo / name
            require(path.resolve().is_relative_to(repo.resolve()), "SOURCE_PATH_INVALID")
            require(sha(path.read_bytes()) == expected, "SOURCE_CHANGED:" + name)
    loaded = {}
    for name, info in files.items():
        path = directory / name
        require(path.is_file() and not path.is_symlink(), "FILE_INVALID:" + name)
        raw = path.read_bytes()
        require(info == {"sha256": sha(raw), "bytes": len(raw)}, "CHECKSUM:" + name)
        p = json.loads(raw)
        for k, v in {**GATES, **source_identity(status), "version": VERSION}.items():
            require(p.get(k) == v and type(p.get(k)) is type(v), "PAYLOAD_" + k + ":" + name)
        require(p.get("row_count") == len(p.get("rows", [])), "ROW_COUNT:" + name)
        if ".compact." in name:
            require(len(raw) <= PAGE_LIMIT, "PAGE_TOO_LARGE:" + name)
            require(len(p["rows"]) <= 30, "PAGE_ROW_LIMIT:" + name)
        loaded[name] = p
    expected_files = set()
    for label in TABLES:
        canonical_name = label + ".json"
        entry = tables[label]
        expected_files.add(canonical_name)
        require(entry.get("canonical") == canonical_name, "CANONICAL_NAME")
        require(canonical_name in loaded, "CANONICAL_MISSING:" + label)
        canonical = loaded[canonical_name]
        rows = canonical["rows"]
        require(canonical.get("table_id") == label, "TABLE_ID:" + label)
        require(entry.get("row_count") == len(rows), "MANIFEST_ROW_COUNT:" + label)
        codes = [r["ticker"] for r in rows]
        require(all(isinstance(c, str) and re.fullmatch(r"[0-9]{6}", c) for c in codes), "TICKER_FORMAT")
        require(len(codes) == len(set(codes)), "DUPLICATE_TICKER:" + label)
        if label == "kospi":
            selected = read(repo / "api/kospi_watchlist.json")
            require(len(rows) == 30, "KOSPI_NOT_30")
            require(codes == [ticker(r["code"]) for r in selected["rows"]], "KOSPI_ORDER")
        for row in rows:
            m = row["metrics"]
            require(m.get("status") == "OK" and m.get("basis_date") == manifest["basis_date"], "METRICS_BASIS")
            require(row.get("market") == "KOSPI", "MARKET")
            require(row.get("request_time_price") is None, "OFFLINE_LIVE_PRICE_FORBIDDEN")
            for key in ("investment_score_100", "earnings_outlook_change"):
                require(m.get(key) is None, "UNSOURCED_FIELD:" + key)
            require(m.get("rs_sector_pp") == {"1": None, "3": None}, "UNSOURCED_FIELD:rs_sector_pp")
            require(m["trailing_reference"].get("confirmed_swing_low_stop") is None, "UNSOURCED_SWING_STOP")
            if label == "decliners":
                require(m["streak"]["direction"] == -1 and m["streak"]["days"] >= 3, "DECLINER_FILTER")
            if label == "decliners24":
                require(matches_decliners24(m), "STRICT24_FILTER")
        page_names = [f"{label}.compact.{i}.json" for i in range(1, max(1, (len(rows)+29)//30)+1)]
        require(entry.get("pages") == page_names, "PAGE_LIST:" + label)
        projection = []
        for i, name in enumerate(page_names, 1):
            expected_files.add(name)
            require(name in loaded, "PAGE_MISSING:" + name)
            p = loaded[name]
            require(p.get("table_id") == label and p.get("page") == i, "PAGE_ID:" + name)
            require(p.get("page_count") == len(page_names) and p.get("total_rows") == len(rows), "PAGE_TOTAL:" + name)
            from build_stock_table_preview_v850 import COMPACT_COLUMNS
            require(p.get("columns") == COMPACT_COLUMNS, "PAGE_COLUMNS:" + name)
            projection.extend(p["rows"])
        require(projection == [compact_row(r) for r in rows], "COMPACT_VALUES_OR_ORDER:" + label)
    require(expected_files == set(files), "UNREFERENCED_FILES")
    return manifest


def prepare(repo, staging):
    status = read(repo / "api/status.json")
    meta = {"version": VERSION, **GATES, **source_identity(status),
            "source_freshness_at_generation": {
                k: status.get(k) for k in ("official_fresh_now", "safe_to_analyze_as_latest",
                                          "computed_expected_official_trading_date")},
            "disclosure": "정기 생성 준비자료. Worker·GPT 미연결. 현재가·완성 투자표로 사용 금지."}
    manifest = {**meta, "files": {}, "tables": {}}
    if status.get("api_sync_ok") is not True or status.get("critical_errors"):
        manifest["status"] = "BLOCKED_SOURCE_SYNC"
    else:
        with tempfile.TemporaryDirectory(prefix="two-table-calc-") as temp:
            output = Path(temp) / "preview"
            report = build(repo, output)
            manifest.update({k: report[k] for k in (
                "source_commit", "generated_at_utc", "universe_count", "skipped_history",
                "future_bars_ignored", "kospi_coverage_out_of_30", "source_sha256", "pending")})
            fresh = status.get("official_fresh_now") is True and status.get("safe_to_analyze_as_latest") is True
            manifest["status"] = "SHADOW_READY" if fresh else "SHADOW_STALE"
            for label in TABLES:
                canonical = label + ".json"
                rows = read(output / canonical)["row_count"]
                pages = [f"{label}.compact.{i}.json" for i in range(1, max(1, (rows+29)//30)+1)]
                manifest["tables"][label] = {"canonical": canonical, "row_count": rows, "pages": pages}
                for name in [canonical, *pages]:
                    payload = {**read(output / name), **meta}
                    payload["status"] = manifest["status"]
                    raw = encode(payload)
                    if ".compact." in name:
                        require(len(raw) <= PAGE_LIMIT, "PAGE_TOO_LARGE:" + name)
                    (staging / name).write_bytes(raw)
                    manifest["files"][name] = {"sha256": sha(raw), "bytes": len(raw)}
    (staging / "manifest.json").write_bytes(encode(manifest))
    validate_bundle(staging, repo, strict_source_hashes=True)
    return manifest


def owned_directory(repo):
    api = repo / "api"
    target = api / DIRECTORY
    require(api.is_dir() and not api.is_symlink(), "API_PATH_INVALID")
    require(not target.is_symlink(), "TARGET_SYMLINK")
    require(target.resolve() == repo / "api" / DIRECTORY, "TARGET_PATH_INVALID")
    if target.exists():
        require(target.is_dir(), "TARGET_NOT_DIRECTORY")
        children = list(target.iterdir())
        for path in children:
            require(path.is_file() and not path.is_symlink(), "TARGET_CHILD_INVALID")
            require(path.name == "manifest.json" or bool(FILE_PATTERN.fullmatch(path.name)), "UNOWNED_FILE")
        if children:
            require((target / "manifest.json").exists(), "OWNERSHIP_MANIFEST_MISSING")
            require(read(target / "manifest.json").get("version") == VERSION, "OWNERSHIP_VERSION_MISMATCH")
    return target


def publish(repo):
    repo = Path(repo).resolve()
    target = owned_directory(repo)
    with tempfile.TemporaryDirectory(prefix="two-table-publish-") as temp:
        staging = Path(temp)
        manifest = prepare(repo, staging)
        target.mkdir(exist_ok=True)
        previous = {p.name for p in target.iterdir()}
        # Replace only owned generated JSON. Manifest last prevents a partial
        # bundle from validating; a failed CI run never commits/pushes it.
        names = sorted(manifest["files"]) + ["manifest.json"]
        for name in names:
            with tempfile.NamedTemporaryFile(dir=target, prefix=".pending-", delete=False) as f:
                pending = Path(f.name)
                f.write((staging / name).read_bytes())
            try:
                os.replace(pending, target / name)
            finally:
                pending.unlink(missing_ok=True)
        # No recursive deletion; only obsolete pages owned by this generator.
        for name in sorted(previous - set(names)):
            require(bool(FILE_PATTERN.fullmatch(name)), "CLEANUP_NAME_INVALID")
            (target / name).unlink()
    validate_bundle(target, repo, strict_source_hashes=True)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    manifest = (validate_bundle(args.repo / "api" / DIRECTORY, args.repo)
                if args.check_only else publish(args.repo))
    print("V851_TWO_TABLE_SHADOW_CONTRACT=PASS")
    print("TWO_TABLE_SHADOW_STATUS=" + manifest["status"])
    for label, info in manifest["tables"].items():
        print(label.upper() + "_ROWS=" + str(info["row_count"]))
    print("PRODUCTION_ACTIVATION_ALLOWED=false")
    print("STANDALONE_SWING_TABLE_ENABLED=false")


if __name__ == "__main__":
    main()
