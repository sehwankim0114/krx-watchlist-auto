"""Promote a validated exact OCF candidate into the source-only cache.

The 100-point score remains disabled in the production API. The candidate and
baseline scorers must agree with the committed candidate audit before writing.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import audit_current_ocf_candidates as candidate_audit
import audit_current_score_readiness as readiness_audit
import investment_score_dry_run_v882 as scorer


ROOT = Path(__file__).resolve().parent
VERSION = "2026-10-18-current-exact-ocf-source-promotion"
CONTRACT_VERSION = "2026-09-12-v8.7.4-audited-operating-cash-flow-source"
SOURCE = ROOT / "latest/investment_score_ocf_source_latest.csv"
META = ROOT / "latest/investment_score_ocf_source_latest.json"
CANDIDATE_CSV = candidate_audit.CANDIDATE_CSV
CANDIDATE_JSON = candidate_audit.SUMMARY_JSON
LOG = ROOT / "latest/investment_score_current_ocf_promotion_run_log_latest.txt"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    status = read_json(ROOT / "api/status.json")
    manifest = read_json(ROOT / "api/two_table_v1/manifest.json")
    candidate = read_json(CANDIDATE_JSON)
    meta = read_json(META)
    if not status.get("api_sync_ok") or status.get("critical_errors"):
        raise RuntimeError("API_NOT_SYNCED")
    if manifest["source_build_id"] != status["build_id"]:
        raise RuntimeError("API_MANIFEST_BUILD_MISMATCH")
    if candidate.get("status") != "AUDIT_CANDIDATE_ONLY_NOT_PRODUCTION":
        raise RuntimeError("CANDIDATE_NOT_AUDITED")
    if candidate.get("source_build_id") != status["build_id"]:
        raise RuntimeError("CANDIDATE_BUILD_STALE")
    if candidate.get("source_basis_date") != manifest["basis_date"]:
        raise RuntimeError("CANDIDATE_BASIS_STALE")
    if candidate.get("production_ocf_cache_changed") is not False:
        raise RuntimeError("CANDIDATE_ALREADY_MODIFIED_SOURCE")
    if candidate.get("previous_ready_scores_unchanged") is not True:
        raise RuntimeError("CANDIDATE_READY_REGRESSION")
    if meta.get("version") != CONTRACT_VERSION:
        raise RuntimeError("OCF_SOURCE_CONTRACT_CHANGED")
    if meta.get("account_id_policy") != (
        "EXACT_ONLY:" + candidate_audit.IFRS_OCF_ID
    ):
        raise RuntimeError("OCF_ACCOUNT_POLICY_CHANGED")

    rows = candidate_audit.read_csv(CANDIDATE_CSV)
    expected_tickers = candidate.get("new_exact_ocf_candidate_tickers") or []
    if len(rows) != candidate["new_exact_ocf_candidate_count"]:
        raise RuntimeError("CANDIDATE_ROW_COUNT_CHANGED")
    if sorted(row["ticker"] for row in rows) != sorted(expected_tickers):
        raise RuntimeError("CANDIDATE_TICKER_SET_CHANGED")
    if len(set(expected_tickers)) != len(expected_tickers):
        raise RuntimeError("DUPLICATE_CANDIDATE_TICKER")
    if not rows:
        print("CURRENT_OCF_PROMOTION=NO_NEW_EXACT_SOURCE")
        return

    universe = candidate_audit.current_universe()
    financial = scorer.read_csv_map(candidate_audit.FIN_SOURCE)
    raw = scorer.read_csv_map(candidate_audit.RAW_SOURCE)
    existing_rows = candidate_audit.read_csv(SOURCE)
    existing = {
        scorer.ticker(row.get("ticker")): row for row in existing_rows
        if scorer.ticker(row.get("ticker"))
    }
    if len(existing) != len(existing_rows):
        raise RuntimeError("EXISTING_OCF_DUPLICATE_TICKER")

    combined = dict(existing)
    for row in rows:
        code = row["ticker"]
        fin = financial.get(code) or {}
        annual = raw.get(code) or {}
        old = existing.get(code) or {}
        if code not in universe or row["name"] != universe[code]:
            raise RuntimeError("CANDIDATE_NOT_CURRENT_UNIVERSE:" + code)
        if old.get("source_status") == "READY":
            raise RuntimeError("CANDIDATE_OVERWRITES_READY:" + code)
        if (
            row["source_mode"] != "CURRENT_DART_EXACT_2025_ANNUAL"
            or row["source_status"] != "READY"
            or row["account_id"] != candidate_audit.IFRS_OCF_ID
            or row["source_report_year"] != "2025"
            or row["source_report_code"] != "11011"
            or row["source_ticker"] != code
        ):
            raise RuntimeError("CANDIDATE_CONTRACT_INVALID:" + code)
        if (
            annual.get("source_cache_status") != "READY_RAW_SOURCE"
            or annual.get("annual_source_year") != "2025"
            or annual.get("annual_fs_div") != row["source_fs_div"]
            or (scorer.num(annual.get("annual_revenue_y0")) or 0) <= 0
        ):
            raise RuntimeError("CANDIDATE_REVENUE_SCOPE_CHANGED:" + code)
        if (
            fin.get("financial_data_status") != "READY"
            or fin.get("corp_identity_status") not in {"MATCH", "MATCH_NORMALIZED"}
            or fin.get("corp_code") != row["source_corp_code"]
            or fin.get("name") != row["name"]
            or scorer.num(row["operating_cash_flow_annual"]) is None
        ):
            raise RuntimeError("CANDIDATE_IDENTITY_OR_AMOUNT_CHANGED:" + code)
        combined[code] = {
            field: row.get(field, "") for field in candidate_audit.SOURCE_FIELDS
        }

    old_paths = {
        key: getattr(scorer, key)
        for key in ("OCF", "OUT_CSV", "OUT_JSON", "OUT_LOG", "OUT_DOC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="promote_current_ocf_") as name:
            tmp = Path(name)
            merged_path = tmp / "merged_source.csv"
            candidate_audit.write_csv(merged_path, [
                {
                    field: source_row.get(field, "")
                    for field in candidate_audit.SOURCE_FIELDS
                }
                for _, source_row in sorted(combined.items())
            ], candidate_audit.SOURCE_FIELDS)
            baseline_rows, baseline = candidate_audit.score_with_ocf(
                SOURCE, tmp, "baseline"
            )
            promoted_rows, promoted = candidate_audit.score_with_ocf(
                merged_path, tmp, "promoted"
            )
            if set(baseline_rows) != set(promoted_rows) or set(promoted_rows) != set(universe):
                raise RuntimeError("PROMOTION_SCORE_UNIVERSE_CHANGED")
            if baseline["ready_count"] != candidate["baseline_ready_count"]:
                raise RuntimeError("PROMOTION_BASELINE_READY_CHANGED")
            if promoted["ready_count"] != candidate["candidate_ready_count"]:
                raise RuntimeError("PROMOTION_CANDIDATE_READY_CHANGED")
            if candidate_audit.ocf_missing(baseline) != candidate["baseline_ocf_missing_count"]:
                raise RuntimeError("PROMOTION_BASELINE_OCF_CHANGED")
            if candidate_audit.ocf_missing(promoted) != candidate["candidate_ocf_missing_count"]:
                raise RuntimeError("PROMOTION_CANDIDATE_OCF_CHANGED")
            for code, before in baseline_rows.items():
                after = promoted_rows[code]
                if before["score_status"] == "READY" and (
                    after["score_status"] != "READY"
                    or after["score_total"] != before["score_total"]
                    or after["score_band"] != before["score_band"]
                ):
                    raise RuntimeError("PROMOTION_PREVIOUS_READY_CHANGED:" + code)
            source_bytes = merged_path.read_bytes()
    finally:
        for key, value in old_paths.items():
            setattr(scorer, key, value)

    SOURCE.write_bytes(source_bytes)
    now = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    ready_count = sum(
        row.get("source_status") == "READY" for row in combined.values()
    )
    meta.update({
        "refresh_version": VERSION,
        "generated_at_kst": now,
        "production_unique_tickers": len(combined),
        "operating_cash_flow_ready": ready_count,
        "operating_cash_flow_limited": len(combined) - ready_count,
        "current_universe_count": len(universe),
        "current_universe_exact_candidate_added": len(rows),
        "current_universe_ocf_missing_after_promotion": candidate["candidate_ocf_missing_count"],
        "current_universe_candidate_source_build_id": status["build_id"],
        "current_universe_candidate_source_basis_date": manifest["basis_date"],
        "current_universe_candidate_tickers": sorted(expected_tickers),
        "current_universe_candidate_policy": (
            "2025_ANNUAL_11011_EXACT_IFRS_CF_MATCHED_TO_ANNUAL_REVENUE_FS_DIV"
        ),
    })
    META.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    readiness_audit.run()
    updated_readiness = read_json(readiness_audit.OUT)
    if updated_readiness["ready_count"] != promoted["ready_count"]:
        raise RuntimeError("POST_PROMOTION_READINESS_MISMATCH")
    LOG.write_text("\n".join([
        "VERSION=" + VERSION,
        "SOURCE_BUILD_ID=" + status["build_id"],
        "CANDIDATE_ADDED=" + str(len(rows)),
        "BASELINE_READY=" + str(baseline["ready_count"]),
        "PROMOTED_READY=" + str(promoted["ready_count"]),
        "BASELINE_OCF_MISSING=" + str(candidate["baseline_ocf_missing_count"]),
        "PROMOTED_OCF_MISSING=" + str(candidate["candidate_ocf_missing_count"]),
        "PRODUCTION_OCF_SOURCE_CHANGED=true",
        "PRODUCTION_API_CHANGED=false",
        "PRODUCTION_SCORE_WRITTEN=false",
        "STATUS=PASS",
    ]) + "\n", encoding="utf-8")
    print("CURRENT_OCF_PROMOTION=PASS")
    print("CURRENT_OCF_SOURCE_ADDED=" + str(len(rows)))
    print("CURRENT_OCF_SCORE_READY=" + str(promoted["ready_count"]))


if __name__ == "__main__":
    main()
