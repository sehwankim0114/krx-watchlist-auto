"""Recalculate 100-point score readiness for the current two-table universe.

This is an audit only. It never writes a score into the production API.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "latest/investment_score_current_readiness_latest.json"
VERSION = "2026-10-17-v8.8-current-universe-score-readiness-audit"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


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
        summary = read_json(scorer.OUT_JSON)

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
    eligible_ready_count = summary["ready_count"] if basis_matches else 0
    blockers = []
    if summary["limited_count"]:
        blockers.append("LIMITED_SCORE_COMPONENTS_REMAIN")
    if not basis_matches:
        blockers.append("PRICE_ELASTICITY_BASIS_STALE")
    if elasticity.get("limited_tickers"):
        blockers.append("PRICE_ELASTICITY_SOURCE_PARTIAL")
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
        "eligible_ready_count_after_source_freshness_gate": eligible_ready_count,
        "eligible_ready_pct_after_source_freshness_gate": round(
            eligible_ready_count / summary["production_unique_tickers"] * 100, 2
        ) if summary["production_unique_tickers"] else 0,
        "top_missing_reasons": summary["top_missing_reasons"],
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
    print("CURRENT_SCORE_ELASTICITY_BASIS_MATCH=" + str(basis_matches).lower())


if __name__ == "__main__":
    run()
