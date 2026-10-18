"""Recalculate 100-point score readiness for the current two-table universe.

This is an audit only. It never writes a score into the production API.
"""

import csv
import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "latest/investment_score_current_readiness_latest.json"
VERSION = "2026-10-18-v8.8-current-universe-validated-da-overlay-audit"
DA_SOURCE = ROOT / "latest/investment_score_da_source_v894.csv"
DA_SUMMARY = ROOT / "latest/investment_score_da_source_v894_summary_latest.json"
DA_DEP_ID = "ifrs-full_AdjustmentsForDepreciationExpense"
DA_AMO_ID = "ifrs-full_AdjustmentsForAmortisationExpense"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))



def read_csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader.fieldnames or []), list(reader)


def validated_da_shadow(tmp):
    """Use already audited exact 2025 XBRL facts for this audit only."""
    source_summary = read_json(DA_SUMMARY)
    if (source_summary.get("status") != "SOURCE_ONLY_READY"
            or source_summary.get("source_only_ready_count") != 67):
        raise ValueError("SCORE_AUDIT_DA_SOURCE_NOT_VALIDATED")
    _, source_rows = read_csv_rows(DA_SOURCE)
    if len(source_rows) != 67:
        raise ValueError("SCORE_AUDIT_DA_SOURCE_ROW_COUNT_CHANGED")
    source_map = {scorer.ticker(row["ticker"]): row for row in source_rows}
    if len(source_map) != len(source_rows):
        raise ValueError("SCORE_AUDIT_DA_SOURCE_DUPLICATE")

    fields, raw_rows = read_csv_rows(scorer.RAW)
    raw_map = {scorer.ticker(row["ticker"]): row for row in raw_rows}
    production = scorer.production_rows()
    selected = {}
    for ticker, prod_row in production.items():
        raw, mode = scorer.get_common_raw(ticker, raw_map, prod_row)
        if raw.get("source_cache_status") != "READY_RAW_SOURCE":
            continue
        raw_ticker = scorer.ticker(raw.get("ticker"))
        source = source_map.get(raw_ticker)
        if not source or source.get("source_status") != "READY_EXACT_DA_SOURCE":
            continue
        if source.get("both_exact_facts_present") != "TRUE":
            continue
        year, fs = source.get("target_year"), source.get("fs_div")
        if not (year and fs in {"CFS", "OFS"}
                and raw.get("annual_source_year") == year
                and raw.get("deep_source_year") == year
                and raw.get("annual_fs_div") == fs
                and raw.get("deep_fs_div") == fs
                and raw.get("deep_source_status") == "OK"):
            continue
        candidates = scorer.parse_json_list(
            raw.get("depreciation_amortization_candidates_json")
        )
        if any(row.get("account_id") in scorer.DA_IDS for row in candidates):
            continue
        dep = scorer.num(source.get("depreciation_value"))
        amo = scorer.num(source.get("amortisation_value"))
        total = scorer.num(source.get("da_total"))
        if (dep is None or amo is None or total is None
                or dep < 0 or amo < 0 or abs(dep + amo - total) > 0.5):
            raise ValueError("SCORE_AUDIT_DA_SOURCE_AMOUNT_INVALID:" + raw_ticker)
        pair = (dep, amo)
        if raw_ticker in selected and selected[raw_ticker] != pair:
            raise ValueError("SCORE_AUDIT_DA_PREFERRED_CONFLICT:" + raw_ticker)
        selected[raw_ticker] = pair

    for raw_ticker, (dep, amo) in selected.items():
        raw = raw_map[raw_ticker]
        candidates = scorer.parse_json_list(
            raw.get("depreciation_amortization_candidates_json")
        )
        candidates.extend([
            {"account_id": DA_DEP_ID, "account_nm": "audited exact depreciation",
             "amount": dep},
            {"account_id": DA_AMO_ID, "account_nm": "audited exact amortisation",
             "amount": amo},
        ])
        raw["depreciation_amortization_candidates_json"] = json.dumps(
            candidates, ensure_ascii=False, separators=(",", ":")
        )
    shadow = tmp / "validated_da_shadow.csv"
    with shadow.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(raw_rows)
    return shadow, sorted(selected)


def validate_da_reconciliation(before, after, selected):
    old = {row["ticker"]: row for row in before}
    new = {row["ticker"]: row for row in after}
    if old.keys() != new.keys():
        raise ValueError("SCORE_AUDIT_DA_UNIVERSE_CHANGED")
    selected = set(selected)
    newly_ready = []
    for ticker in old:
        a, b = old[ticker], new[ticker]
        if a["score_status"] == "READY":
            if b["score_status"] != "READY" or a["score_total"] != b["score_total"]:
                raise ValueError("SCORE_AUDIT_DA_READY_REGRESSION:" + ticker)
        if ticker not in selected:
            if (a["score_status"], a["score_total"], a["missing_components"]) != (
                    b["score_status"], b["score_total"], b["missing_components"]):
                raise ValueError("SCORE_AUDIT_DA_UNSELECTED_CHANGED:" + ticker)
        else:
            old_missing = set(filter(None, a["missing_components"].split(";")))
            new_missing = set(filter(None, b["missing_components"].split(";")))
            if (old_missing - new_missing) != {
                    reason for reason in old_missing if reason.startswith("EV/EBITDA:")
            } or (new_missing - old_missing):
                raise ValueError("SCORE_AUDIT_DA_COMPONENT_SCOPE_CHANGED:" + ticker)
            if any(reason.startswith("EV/EBITDA:") for reason in new_missing):
                raise ValueError("SCORE_AUDIT_DA_EV_STILL_MISSING:" + ticker)
            if a["score_status"] != "READY" and b["score_status"] == "READY":
                newly_ready.append(ticker)
    return sorted(newly_ready)


def run():
    status = read_json(ROOT / "api/status.json")
    manifest = read_json(ROOT / "api/two_table_v1/manifest.json")
    if not status.get("api_sync_ok") or status.get("critical_errors"):
        raise ValueError("SCORE_AUDIT_API_NOT_SYNCED")
    if manifest["source_build_id"] != status["build_id"]:
        raise ValueError("SCORE_AUDIT_BUILD_MISMATCH")

    with tempfile.TemporaryDirectory(prefix="current_score_readiness_") as name:
        tmp = Path(name)
        scorer.OUT_CSV = tmp / "score_rows.csv"
        scorer.OUT_JSON = tmp / "score_summary.json"
        scorer.OUT_LOG = tmp / "score_run_log.txt"
        scorer.OUT_DOC = tmp / "score_explanation.md"
        scorer.main()
        _, baseline_rows = read_csv_rows(scorer.OUT_CSV)
        shadow, da_selected = validated_da_shadow(tmp)
        scorer.RAW = shadow
        scorer.main()
        summary = read_json(scorer.OUT_JSON)
        _, score_rows = read_csv_rows(scorer.OUT_CSV)
        da_newly_ready = validate_da_reconciliation(
            baseline_rows, score_rows, da_selected
        )

    if summary["production_unique_tickers"] != len(scorer.production_rows()):
        raise ValueError("SCORE_AUDIT_UNIVERSE_MISMATCH")
    if summary["ready_count"] + summary["limited_count"] != summary["production_unique_tickers"]:
        raise ValueError("SCORE_AUDIT_ROW_COUNT_MISMATCH")
    guards = summary["hard_guards"]
    if not (
        guards["production_api_changed"] is False
        and guards["production_investment_score_written"] is False
        and guards["legacy_score_rescaled"] is False
        and guards["limited_score_total_is_null"] is True
    ):
        raise ValueError("SCORE_AUDIT_SAFETY_GUARD_FAILED")

    elasticity = read_json(ROOT / "latest/investment_score_price_elasticity_20d_latest.json")
    elasticity_basis = elasticity.get("basis_date")
    current_basis = manifest.get("basis_date")
    basis_matches = elasticity_basis == current_basis
    ready_tickers = {
        row["ticker"] for row in score_rows if row["score_status"] == "READY"
    }
    if len(ready_tickers) != summary["ready_count"]:
        raise ValueError("SCORE_AUDIT_READY_TICKER_COUNT_MISMATCH")
    financial = scorer.read_csv_map(scorer.FIN)
    valuation_current_tickers = set()
    for ticker in ready_tickers:
        row = financial.get(ticker) or {}
        loss_per_exception = (
            row.get("valuation_data_status") == "PARTIAL_LOSS_PER_NA"
            and row.get("earnings_trend") in {"적자지속", "적자전환"}
            and not row.get("per_annualized")
        )
        if (
            row.get("valuation_price_basis_date") == current_basis
            and row.get("financial_data_status") == "READY"
            and (row.get("valuation_data_status") == "READY" or loss_per_exception)
        ):
            valuation_current_tickers.add(ticker)
    current_price_input_ready_count = (
        len(valuation_current_tickers) if basis_matches else 0
    )
    raw_sources = scorer.read_csv_map(scorer.RAW)
    ocf_sources = scorer.read_csv_map(scorer.OCF)
    ocf_period_mismatches = sorted(
        ticker for ticker in scorer.production_rows()
        if (ocf_sources.get(ticker) or {}).get("source_status") == "READY"
        and (raw_sources.get(ticker) or {}).get("annual_source_year") != "2025"
    )
    current_price_and_ocf_period_ready_count = (
        len(valuation_current_tickers - set(ocf_period_mismatches))
        if basis_matches else 0
    )
    blockers = []
    if summary["limited_count"]:
        blockers.append("LIMITED_SCORE_COMPONENTS_REMAIN")
    if not basis_matches:
        blockers.append("PRICE_ELASTICITY_BASIS_STALE")
    if elasticity.get("limited_tickers"):
        blockers.append("PRICE_ELASTICITY_SOURCE_PARTIAL")
    if len(valuation_current_tickers) != len(ready_tickers):
        blockers.append("VALUATION_PRICE_BASIS_OR_STATUS_NOT_CURRENT")
    if ocf_period_mismatches:
        blockers.append("OCF_ANNUAL_REPORT_YEAR_MISMATCH")
    blockers.append("PRODUCTION_SCORE_ADOPTION_AND_GPT_E2E_NOT_DONE")

    result = {
        "version": VERSION,
        "generated_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY_NOT_FOR_GPT_DISPLAY",
        "source_build_id": status["build_id"],
        "source_rules_sha256": status["rules_sha256"],
        "basis_date": current_basis,
        "policy_version": summary["policy_version"],
        "scorer_version": summary["version"],
        "production_unique_tickers": summary["production_unique_tickers"],
        "ready_count": summary["ready_count"],
        "limited_count": summary["limited_count"],
        "ready_pct": summary["ready_pct"],
        "current_valuation_ready_count_among_scorer_ready": len(valuation_current_tickers),
        "current_price_input_ready_count": current_price_input_ready_count,
        "current_price_and_ocf_period_ready_count": current_price_and_ocf_period_ready_count,
        "ocf_required_annual_report_year": "2025",
        "ocf_annual_period_mismatch_count": len(ocf_period_mismatches),
        "ocf_annual_period_mismatch_tickers": ocf_period_mismatches,
        "current_price_input_ready_pct": round(
            current_price_input_ready_count / summary["production_unique_tickers"] * 100, 2
        ) if summary["production_unique_tickers"] else 0,
        "top_missing_reasons": summary["top_missing_reasons"],
        "da_validated_shadow_tickers": da_selected,
        "da_validated_shadow_count": len(da_selected),
        "da_newly_ready_tickers": da_newly_ready,
        "da_newly_ready_count": len(da_newly_ready),
        "da_source_year": "2025",
        "da_source_only_overlay": True,
        "score_summary_ready_only": summary["score_summary_ready_only"],
        "price_elasticity_source_basis_date": elasticity_basis,
        "price_elasticity_source_ready_tickers": elasticity.get("ready_tickers"),
        "price_elasticity_source_limited_tickers": elasticity.get("limited_tickers"),
        "price_elasticity_basis_matches_current": basis_matches,
        "promotion_blockers": blockers,
        "production_score_written": False,
        "partial_scores_published": False,
        "legacy_score_rescaled": False,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CURRENT_SCORE_READINESS_AUDIT=PASS")
    print("CURRENT_SCORE_BUILD_ID=" + status["build_id"])
    print("CURRENT_SCORE_UNIVERSE=" + str(summary["production_unique_tickers"]))
    print("CURRENT_SCORE_READY=" + str(summary["ready_count"]))
    print("CURRENT_SCORE_LIMITED=" + str(summary["limited_count"]))
    print("CURRENT_SCORE_DA_OVERLAY=" + str(len(da_selected)))
    print("CURRENT_SCORE_DA_NEW_READY=" + str(len(da_newly_ready)))
    print("CURRENT_SCORE_ELASTICITY_BASIS_MATCH=" + str(basis_matches).lower())


if __name__ == "__main__":
    run()
