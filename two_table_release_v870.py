from __future__ import annotations

import argparse
import copy
import os
import tempfile
from pathlib import Path

import build_two_table_shadow_v851 as shadow
from build_stock_table_preview_v850 import compact_row, ticker
from sector_rs_source_v870 import NEW_COLUMNS, enrich_bundle
from stock_table_metrics_v850 import CONTRACT, matches_decliners24

DIRECTORY = shadow.DIRECTORY
VERSION = "2026-09-12-v8.7.0-sector-rs-production-release"
INSTRUCTIONS_VERSION = "2026-09-12-v6.9.2-sector-rs-glossary"
SCHEMA_VERSION = "7.1.2"
CONFIG_PATH = "config/two_table_release.json"
GLOSSARY_PATH = "latest/stock_table_metric_glossary_latest.json"
MISSING = ["investment_score_100", "earnings_outlook_change", "confirmed_swing_low_stop"]
RELEASE = {
    "version": VERSION,
    "enabled": True,
    "standalone_swing_table_enabled": False,
    "scope": "LAYOUT_VERIFIED_INDICATORS_AND_OFFICIAL_KRX_SECTOR_RS_WITH_DECLARED_GAPS",
    "unavailable_fields": MISSING,
    "missing_score_policy": "NO_SCORE_NO_AUTO_BUY_UPGRADE",
}
DISPLAY = {
    "version": VERSION,
    "coverage": "SECTOR_RS_AVAILABLE_OTHER_GAPS_DECLARED",
    "unavailable_fields": MISSING,
    "missing_label": "자료 미제공",
    "investment_score_100": "NOT_AVAILABLE_DO_NOT_RESCALE_LEGACY_SCORE",
    "earnings_outlook_change": "NOT_AVAILABLE_NO_CONSENSUS_REVISION_SOURCE",
    "confirmed_swing_low_stop": "NOT_AVAILABLE_SIGNAL_PRICE_BASIS_DATE_CONTRACT_REQUIRED",
    "rs_sector": "AVAILABLE_OFFICIAL_KRX_INDUSTRY_INDEX_1M_3M_PERCENTAGE_POINTS",
    "recommendation_floor": "OBSERVE_NOT_AUTOMATIC_BUY",
    "request_time_prices": "REQUIRED_10_5_2_NO_STATIC_FALLBACK",
    "historical_metrics": "OFFICIAL_CLOSE_ONLY_DO_NOT_RECALCULATE_WITH_LIVE_QUOTES",
    "standalone_swing_table_enabled": False,
}
DISCLOSURE = (
    "새 양식·검증 지표와 공식 KRX 업종RS 제공. "
    "100점 점수·실적전망·확정 스윙손절은 미제공. 현재가는 별도 조회."
)


def require(ok, message):
    if not ok:
        raise ValueError("TWO_TABLE_RELEASE_" + message)


def release_config(repo):
    path = Path(repo) / CONFIG_PATH
    require(path.is_file() and not path.is_symlink(), "EXPLICIT_CONFIG_REQUIRED")
    value = shadow.read(path)
    require(shadow.encode(value) == shadow.encode(RELEASE), "CONFIG_MISMATCH")
    return value


def glossary_contract(repo):
    path = Path(repo) / GLOSSARY_PATH
    require(path.is_file() and not path.is_symlink(), "GLOSSARY_SOURCE_REQUIRED")
    value = shadow.read(path)
    footer = value.get("compact_footer_text")
    terms = value.get("terms")
    policy = value.get("display_policy") or {}
    expected_terms = {"swing", "ma", "atr14", "rs_kospi", "rs_sector", "streak"}
    require(isinstance(value.get("version"), str) and bool(value["version"]), "GLOSSARY_VERSION")
    require(isinstance(footer, str) and 0 < len(footer.strip()) <= 850, "GLOSSARY_FOOTER")
    require(isinstance(terms, dict) and set(terms) == expected_terms, "GLOSSARY_TERMS")
    require(policy.get("attach_to_stock_tables") is True, "GLOSSARY_DISPLAY_POLICY")
    return {"version": value["version"], "footer": footer.strip()}


def metadata(status):
    synced = status.get("api_sync_ok") is True and not status.get("critical_errors")
    fresh = synced and status.get("official_fresh_now") is True and status.get("safe_to_analyze_as_latest") is True
    return {
        "version": VERSION,
        **shadow.source_identity(status),
        "release_stage": "PRODUCTION",
        "production_activation_allowed": bool(fresh),
        "custom_gpt_route_enabled": bool(fresh),
        "safe_to_analyze_as_latest": bool(fresh),
        "standalone_swing_table_enabled": False,
        "current_time_freshness_recheck_required": True,
        "status": "READY" if fresh else ("BLOCKED_SOURCE_SYNC" if not synced else "STALE_SOURCE"),
        "display_contract": DISPLAY,
        "disclosure": DISCLOSURE,
    }


def calculation_contract():
    return {
        **CONTRACT,
        "release_stage": "PRODUCTION",
        "layout_release_version": VERSION,
        "metric_coverage": "SECTOR_RS_AVAILABLE_OTHER_GAPS_DECLARED",
        "sector_rs_contract": "2026-09-12-v8.7.0-official-krx-sector-rs",
        "sector_rs_formula": "STOCK_RETURN_PCT_MINUS_OFFICIAL_KRX_INDUSTRY_INDEX_RETURN_PCT",
        "sector_rs_period_alignment": "EXACT_EXISTING_STOCK_RETURN_START_DATE_TO_COMMON_OFFICIAL_BASIS_DATE",
        "sector_rs_unit": "PERCENTAGE_POINTS",
    }


def validate_bundle(directory, repo, strict_source_hashes=False):
    directory, repo = Path(directory), Path(repo)
    release_config(repo)
    require(directory.is_dir() and not directory.is_symlink(), "DIRECTORY_INVALID")
    require(not (directory / "manifest.json").is_symlink(), "MANIFEST_SYMLINK")

    manifest = shadow.read(directory / "manifest.json")
    status = shadow.read(repo / "api/status.json")
    expected = metadata(status)
    glossary = glossary_contract(repo)
    files = manifest.get("files")
    require(isinstance(files, dict) and all(shadow.FILE_PATTERN.fullmatch(n) for n in files), "FILE_LIST_INVALID")
    require({p.name for p in directory.iterdir()} == set(files) | {"manifest.json"}, "FILE_SET_MISMATCH")
    require(set(manifest.get("tables", {})) == set(shadow.TABLES), "TABLE_SET_MISMATCH")

    if strict_source_hashes:
        for name, expected_hash in (manifest.get("source_sha256") or {}).items():
            path = repo / name
            require(path.resolve().is_relative_to(repo.resolve()), "SOURCE_PATH_INVALID")
            require(shadow.sha(path.read_bytes()) == expected_hash, "SOURCE_CHANGED:" + name)

    loaded = {}
    for name, info in files.items():
        path = directory / name
        require(path.is_file() and not path.is_symlink(), "FILE_INVALID:" + name)
        raw = path.read_bytes()
        require(info == {"sha256": shadow.sha(raw), "bytes": len(raw)}, "CHECKSUM:" + name)
        if ".compact." in name:
            require(len(raw) <= 28500, "TRANSPORT_HEADROOM:" + name)
        payload = shadow.read(path)
        for key, value in expected.items():
            require(shadow.encode(payload.get(key)) == shadow.encode(value), "METADATA_" + key + ":" + name)
        require(payload.get("metric_glossary_version") == glossary["version"], "GLOSSARY_VERSION:" + name)
        require(payload.get("metric_glossary_footer") == glossary["footer"], "GLOSSARY_FOOTER:" + name)
        require(payload.get("contract") == calculation_contract(), "CALCULATION_CONTRACT:" + name)
        require(payload.get("explicit_missing") == MISSING, "MISSING_FIELDS:" + name)
        loaded[name] = payload

    expected_files = set()
    for label in shadow.TABLES:
        canonical_name = label + ".json"
        entry = manifest["tables"][label]
        expected_files.add(canonical_name)
        require(entry.get("canonical") == canonical_name and canonical_name in loaded, "CANONICAL:" + label)
        canonical = loaded[canonical_name]
        rows = canonical["rows"]
        require(canonical.get("table_id") == label, "TABLE_ID:" + label)
        require(entry.get("row_count") == len(rows), "MANIFEST_ROW_COUNT:" + label)
        codes = [row["ticker"] for row in rows]
        require(len(codes) == len(set(codes)), "DUPLICATE_TICKER:" + label)
        if label == "kospi":
            selected = shadow.read(repo / "api/kospi_watchlist.json")
            require(len(rows) == 30, "KOSPI_NOT_30")
            require(codes == [ticker(r["code"]) for r in selected["rows"]], "KOSPI_ORDER")

        for row in rows:
            metrics = row["metrics"]
            require(metrics.get("status") == "OK" and metrics.get("basis_date") == manifest["basis_date"], "METRICS_BASIS")
            require(row.get("market") == "KOSPI", "MARKET")
            require(row.get("request_time_price") is None, "OFFLINE_LIVE_PRICE_FORBIDDEN")
            require(metrics.get("investment_score_100") is None, "UNSOURCED_FIELD:investment_score_100")
            require(metrics.get("earnings_outlook_change") is None, "UNSOURCED_FIELD:earnings_outlook_change")
            require(metrics["trailing_reference"].get("confirmed_swing_low_stop") is None, "UNSOURCED_SWING_STOP")
            rs = metrics.get("rs_sector_pp")
            require(isinstance(rs, dict) and set(rs) == {"1", "3"}, "RS_SECTOR_SHAPE")
            require(all(isinstance(rs[p], (int, float)) and not isinstance(rs[p], bool) for p in ("1", "3")), "RS_SECTOR_VALUES")
            require("rs_sector" not in (metrics.get("missing") or {}), "RS_SECTOR_STILL_MISSING")
            benchmark = metrics.get("sector_benchmark") or {}
            require(isinstance(benchmark.get("benchmark_ticker"), str), "SECTOR_BENCHMARK_TICKER")
            require(isinstance(benchmark.get("benchmark_name"), str) and benchmark["benchmark_name"], "SECTOR_BENCHMARK_NAME")
            require(isinstance(benchmark.get("selection_mode"), str) and benchmark["selection_mode"], "SECTOR_BENCHMARK_MODE")
            if label == "decliners":
                require(metrics["streak"]["direction"] == -1 and metrics["streak"]["days"] >= 3, "DECLINER_FILTER")
            if label == "decliners24":
                require(matches_decliners24(metrics), "STRICT24_FILTER")

        page_names = [f"{label}.compact.{i}.json" for i in range(1, max(1, (len(rows)+29)//30)+1)]
        require(entry.get("pages") == page_names, "PAGE_LIST:" + label)
        projection = []
        for i, name in enumerate(page_names, 1):
            expected_files.add(name)
            require(name in loaded, "PAGE_MISSING:" + name)
            payload = loaded[name]
            require(payload.get("table_id") == label and payload.get("page") == i, "PAGE_ID:" + name)
            require(payload.get("page_count") == len(page_names) and payload.get("total_rows") == len(rows), "PAGE_TOTAL:" + name)
            require(payload.get("columns") == NEW_COLUMNS, "PAGE_COLUMNS:" + name)
            for compact in payload["rows"]:
                require(isinstance(compact, list) and len(compact) == 15, "COMPACT_WIDTH:" + name)
            projection.extend(payload["rows"])

        expected_projection = []
        for row in rows:
            base = compact_row(row)
            rs = row["metrics"]["rs_sector_pp"]
            expected_projection.append(base[:-1] + [[rs["1"], rs["3"]], base[-1]])
        require(projection == expected_projection, "COMPACT_VALUES_OR_ORDER:" + label)

    require(expected_files == set(files), "UNREFERENCED_FILES")
    require(manifest.get("explicit_missing") in (None, MISSING), "MANIFEST_MISSING_FIELDS")
    pending = manifest.get("pending") or []
    require("rs_sector" not in pending, "RS_SECTOR_STILL_PENDING")
    return manifest


def publish(repo):
    repo = Path(repo).resolve()
    release_config(repo)
    status = shadow.read(repo / "api/status.json")
    require(status.get("api_sync_ok") is True and not status.get("critical_errors"), "SOURCE_NOT_SYNCHRONIZED")
    require(status.get("confirmed_basis_date"), "BASIS_DATE_MISSING")

    api = repo / "api"
    target = api / DIRECTORY
    require(api.is_dir() and not api.is_symlink() and not target.is_symlink(), "TARGET_INVALID")
    if target.exists():
        require(target.is_dir(), "TARGET_NOT_DIRECTORY")
        for p in target.iterdir():
            require(p.is_file() and not p.is_symlink() and
                    (p.name == "manifest.json" or shadow.FILE_PATTERN.fullmatch(p.name)), "UNOWNED_FILE")
        prior_version = shadow.read(target / "manifest.json").get("version")
        require(prior_version in (shadow.VERSION, "2026-09-04-v8.5.3-two-table-layout-release", VERSION), "OWNERSHIP_VERSION")

    with tempfile.TemporaryDirectory(prefix="two-table-release-v870-") as temp:
        staging = Path(temp)
        manifest = shadow.prepare(repo, staging)
        require(manifest.get("status") in ("SHADOW_READY", "SHADOW_STALE"), "SHADOW_NOT_BUILDABLE")

        sector_audit = enrich_bundle(staging, status["confirmed_basis_date"], repo=repo)
        require(sector_audit["rs_values_ready"] == sector_audit["rs_values_expected"], "SECTOR_RS_COVERAGE")

        meta = metadata(status)
        manifest.update(meta)
        manifest["pending"] = MISSING + ["MANUAL_GPT_END_TO_END_DISPLAY_TEST"]
        manifest["explicit_missing"] = MISSING
        manifest["sector_rs_source"] = {
            "version": sector_audit["version"],
            "basis_date": sector_audit["basis_date"],
            "unique_ticker_count": sector_audit["unique_ticker_count"],
            "rs_values_ready": sector_audit["rs_values_ready"],
            "rs_values_expected": sector_audit["rs_values_expected"],
        }

        glossary = glossary_contract(repo)
        for name in list(manifest["files"]):
            payload = shadow.read(staging / name)
            payload.update(meta)
            payload["contract"] = calculation_contract()
            payload["explicit_missing"] = MISSING
            payload["metric_glossary_version"] = glossary["version"]
            payload["metric_glossary_footer"] = glossary["footer"]
            raw = shadow.encode(payload)
            if ".compact." in name:
                require(len(raw) <= 28500, "TRANSPORT_HEADROOM:" + name)
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
    return [
        {
            "command": command,
            "operation_id": "getKospiWatchlist",
            "path": "/tables/v1/{table}",
            "parameters": {"table": table},
            "api_file": "api/two_table_v1/" + table + ".json",
            "format_version": VERSION,
            "all_pages_required": True,
            "legacy_fallback_allowed": False,
        }
        for command, table in (("코피표", "kospi"), ("연속하락표", "decliners"), ("2.4연속하락표", "decliners24"))
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    result = (
        validate_bundle(args.repo / "api" / DIRECTORY, args.repo)
        if args.check_only else publish(args.repo)
    )
    print("V870_TWO_TABLE_RELEASE_CONTRACT=PASS")
    print("TWO_TABLE_RELEASE_STATUS=" + result["status"])
    print("PRODUCTION_ACTIVATION_ALLOWED=" + str(result["production_activation_allowed"]).lower())
    print("RS_SECTOR_AVAILABLE=true")
    print("EXPLICIT_MISSING_FIELDS=" + ",".join(MISSING))
    print("STANDALONE_SWING_TABLE_ENABLED=false")


if __name__ == "__main__":
    main()
