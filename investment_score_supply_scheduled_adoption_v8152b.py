#!/usr/bin/env python3
from __future__ import annotations

import copy
import csv
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-22-v8.15.2B-adopt-scheduled-uangel-supply-apply"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
SUPPLY_POLICY_VERSION = "2026-07-01-v6.0-supply-status-separated"
V8151_VERSION = "2026-09-22-v8.15.1-narrow-production-uangel-supply-source-patch"
V8151_RESULT_COMMIT = "c2e1e2e5c19f17f5d75f644d8cdd4a42a262abf7"
FIRST_SCHEDULED_API_COMMIT = "bc2dc0cf66f78a5359ab221c6dfd9af155347b8b"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

PROD_SUPPLY_CSV = ROOT / "latest/investment_score_supply_source_latest.csv"
PROD_SUPPLY_META = ROOT / "latest/investment_score_supply_source_latest.json"
PROD_SUPPLY_LOG = ROOT / "latest/investment_score_supply_source_run_log_latest.txt"
PATCH_JSON = ROOT / "latest/investment_score_supply_production_patch_v8151_summary_latest.json"
MANIFEST = ROOT / "api/two_table_v1/manifest.json"
STATUS = ROOT / "api/status.json"

SUMMARY_OUT = ROOT / "latest/investment_score_supply_api_adoption_v8152b_summary_latest.json"
LOG_OUT = ROOT / "latest/investment_score_supply_api_adoption_v8152b_run_log_latest.txt"
DOC_OUT = ROOT / "docs/investment_score_supply_api_adoption_v8152b.md"

ACTUAL_CSV = Path("/tmp/v8152b_actual_score.csv")
ACTUAL_JSON = Path("/tmp/v8152b_actual_score.json")
ACTUAL_LOG = Path("/tmp/v8152b_actual_score.log")
ACTUAL_DOC = Path("/tmp/v8152b_actual_score.md")
CF_CSV = Path("/tmp/v8152b_counterfactual_score.csv")
CF_JSON = Path("/tmp/v8152b_counterfactual_score.json")
CF_LOG = Path("/tmp/v8152b_counterfactual_score.log")
CF_DOC = Path("/tmp/v8152b_counterfactual_score.md")

TARGET = "072130"
TARGET_NAME = "유엔젤"
SUPPLY_REASON = "수급·공시부담:SUPPLY_LIMITED_NO_POSITIVE_EVIDENCE"

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def row_map(path):
    return {r["ticker"]: r for r in read_rows(path)}

def stable(row):
    return json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

def split_missing(value):
    return [x for x in str(value or "").split(";") if x]

def blocker_count(rows):
    return sum(
        int(r.get("missing_component_count") or 0)
        for r in rows.values()
    )

def run_actual():
    old = {
        "VERSION": scorer.VERSION,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = VERSION
        scorer.OUT_CSV = ACTUAL_CSV
        scorer.OUT_JSON = ACTUAL_JSON
        scorer.OUT_LOG = ACTUAL_LOG
        scorer.OUT_DOC = ACTUAL_DOC
        rc = scorer.main()
    finally:
        for key, value in old.items():
            setattr(scorer, key, value)
    if rc not in (None, 0):
        raise RuntimeError("V8152B_ACTUAL_SCORER_FAILED:" + str(rc))

def run_counterfactual(prod_rows):
    original = scorer.production_rows
    old = {
        "VERSION": scorer.VERSION,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = VERSION
        scorer.production_rows = lambda: copy.deepcopy(prod_rows)
        scorer.OUT_CSV = CF_CSV
        scorer.OUT_JSON = CF_JSON
        scorer.OUT_LOG = CF_LOG
        scorer.OUT_DOC = CF_DOC
        rc = scorer.main()
    finally:
        scorer.production_rows = original
        for key, value in old.items():
            setattr(scorer, key, value)
    if rc not in (None, 0):
        raise RuntimeError("V8152B_CF_SCORER_FAILED:" + str(rc))

def main():
    for p in (
        PROD_SUPPLY_CSV,
        PROD_SUPPLY_META,
        PROD_SUPPLY_LOG,
        PATCH_JSON,
        MANIFEST,
        STATUS,
    ):
        if not p.is_file():
            raise RuntimeError("V8152B_MISSING_INPUT:" + str(p))

    for commit in (V8151_RESULT_COMMIT, FIRST_SCHEDULED_API_COMMIT):
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            check=True,
        )

    patch = read_json(PATCH_JSON)
    meta = read_json(PROD_SUPPLY_META)
    manifest = read_json(MANIFEST)
    status = read_json(STATUS)

    if patch.get("version") != V8151_VERSION:
        raise RuntimeError("V8152B_V8151_VERSION_MISMATCH")
    if patch.get("status") != "PRODUCTION_SOURCE_PATCHED_API_REBUILD_PENDING":
        raise RuntimeError("V8152B_V8151_STATUS_MISMATCH")
    if patch.get("narrow_patch_tickers") != [TARGET]:
        raise RuntimeError("V8152B_V8151_TARGET_CHANGED")
    if (
        int(patch.get("ready_delta") or 0),
        int(patch.get("limited_delta") or 0),
        int(patch.get("blocker_occurrences_reduced_by") or 0),
    ) != (1, -1, 1):
        raise RuntimeError("V8152B_V8151_EFFECT_CHANGED")

    if meta.get("version") != V8151_VERSION:
        raise RuntimeError("V8152B_META_VERSION_MISMATCH")
    if int(meta.get("source_count") or 0) != 9:
        raise RuntimeError("V8152B_SOURCE_COUNT_NOT_9")
    if TARGET not in (meta.get("source_tickers") or []):
        raise RuntimeError("V8152B_TARGET_MISSING_FROM_SOURCE_META")
    if (meta.get("supply_levels") or {}).get(TARGET) != "경계":
        raise RuntimeError("V8152B_TARGET_LEVEL_NOT_WARNING")

    if status.get("api_sync_ok") is not True:
        raise RuntimeError("V8152B_API_NOT_SYNCED")
    if status.get("critical_errors") != []:
        raise RuntimeError("V8152B_API_CRITICAL_ERRORS")
    if status.get("safe_to_analyze_as_latest") is not True:
        raise RuntimeError("V8152B_API_NOT_SAFE_LATEST")

    if manifest.get("release_stage") != "PRODUCTION":
        raise RuntimeError("V8152B_MANIFEST_NOT_PRODUCTION")
    if manifest.get("production_activation_allowed") is not True:
        raise RuntimeError("V8152B_PRODUCTION_NOT_ALLOWED")
    if manifest.get("safe_to_analyze_as_latest") is not True:
        raise RuntimeError("V8152B_MANIFEST_NOT_SAFE_LATEST")
    if manifest.get("basis_date") != status.get("confirmed_basis_date"):
        raise RuntimeError("V8152B_BASIS_MISMATCH")
    if manifest.get("source_build_id") != status.get("build_id"):
        raise RuntimeError("V8152B_BUILD_ID_MISMATCH")

    supply_sha = hashlib.sha256(PROD_SUPPLY_CSV.read_bytes()).hexdigest()
    manifest_supply_sha = (manifest.get("source_sha256") or {}).get(
        "latest/investment_score_supply_source_latest.csv"
    )
    if supply_sha != manifest_supply_sha:
        raise RuntimeError("V8152B_SUPPLY_HASH_NOT_APPLIED")

    supply_rows = read_rows(PROD_SUPPLY_CSV)
    if len(supply_rows) != 9:
        raise RuntimeError("V8152B_SUPPLY_CSV_ROWS_NOT_9")
    supply_by = {r["ticker"]: r for r in supply_rows}
    if TARGET not in supply_by:
        raise RuntimeError("V8152B_TARGET_MISSING_FROM_SUPPLY_CSV")
    if supply_by[TARGET].get("supply_status") != "OK":
        raise RuntimeError("V8152B_TARGET_SUPPLY_STATUS_NOT_OK")
    if supply_by[TARGET].get("supply_level") != "경계":
        raise RuntimeError("V8152B_TARGET_SUPPLY_LEVEL_NOT_WARNING")

    api_rows = {}
    appearances = {}
    for table in ("kospi", "decliners", "decliners24"):
        payload = read_json(ROOT / f"api/two_table_v1/{table}.json")
        for row in payload.get("rows") or []:
            code = row["ticker"]
            api_rows[code] = row
            appearances.setdefault(code, []).append(table)

    if TARGET not in api_rows:
        raise RuntimeError("V8152B_TARGET_NOT_IN_PRODUCTION_API")
    target_analysis = api_rows[TARGET].get("analysis") or {}
    if target_analysis.get("supply_status") != "OK":
        raise RuntimeError("V8152B_API_TARGET_STATUS_NOT_OK")
    if target_analysis.get("supply_level") != "경계":
        raise RuntimeError("V8152B_API_TARGET_LEVEL_NOT_WARNING")
    keywords = {
        x
        for x in str(target_analysis.get("supply_keywords") or "").split(",")
        if x
    }
    if keywords != {"대량보유", "주요주주변동"}:
        raise RuntimeError(
            "V8152B_API_TARGET_KEYWORDS_CHANGED:" + ",".join(sorted(keywords))
        )

    run_actual()
    actual_rows = row_map(ACTUAL_CSV)
    actual_summary = read_json(ACTUAL_JSON)
    if TARGET not in actual_rows:
        raise RuntimeError("V8152B_TARGET_NOT_IN_ACTUAL_SCORER")
    actual_target = actual_rows[TARGET]
    if actual_target.get("score_status") != "READY":
        raise RuntimeError("V8152B_ACTUAL_TARGET_NOT_READY")
    if split_missing(actual_target.get("missing_components")):
        raise RuntimeError("V8152B_ACTUAL_TARGET_HAS_BLOCKERS")
    points = json.loads(
        actual_target.get("component_points_json") or "{}"
    ).get("수급·공시부담")
    if points != 4:
        raise RuntimeError("V8152B_ACTUAL_SUPPLY_POINTS_NOT_4:" + str(points))

    actual_prod = scorer.production_rows()
    if TARGET not in actual_prod:
        raise RuntimeError("V8152B_TARGET_NOT_IN_PRODUCTION_ROWS")

    counterfactual_prod = copy.deepcopy(actual_prod)
    cf_analysis = copy.deepcopy(
        counterfactual_prod[TARGET].get("analysis") or {}
    )
    cf_analysis["supply_status"] = "LIMITED"
    cf_analysis["supply_level"] = "없음"
    cf_analysis["supply_keywords"] = ""
    counterfactual_prod[TARGET]["analysis"] = cf_analysis

    run_counterfactual(counterfactual_prod)
    cf_rows = row_map(CF_CSV)
    cf_summary = read_json(CF_JSON)

    if set(actual_rows) != set(cf_rows):
        raise RuntimeError("V8152B_COUNTERFACTUAL_UNIVERSE_CHANGED")
    cf_target = cf_rows[TARGET]
    if cf_target.get("score_status") != "LIMITED":
        raise RuntimeError("V8152B_CF_TARGET_NOT_LIMITED")
    if split_missing(cf_target.get("missing_components")) != [SUPPLY_REASON]:
        raise RuntimeError("V8152B_CF_TARGET_NOT_SINGLE_SUPPLY")

    actual_ready = int(actual_summary.get("ready_count") or 0)
    actual_limited = int(actual_summary.get("limited_count") or 0)
    cf_ready = int(cf_summary.get("ready_count") or 0)
    cf_limited = int(cf_summary.get("limited_count") or 0)
    actual_blockers = blocker_count(actual_rows)
    cf_blockers = blocker_count(cf_rows)

    if actual_ready - cf_ready != 1:
        raise RuntimeError("V8152B_READY_DELTA_NOT_1")
    if actual_limited - cf_limited != -1:
        raise RuntimeError("V8152B_LIMITED_DELTA_NOT_MINUS_1")
    if cf_blockers - actual_blockers != 1:
        raise RuntimeError("V8152B_BLOCKER_REDUCTION_NOT_1")

    changed = [
        code
        for code in sorted(actual_rows)
        if stable(actual_rows[code]) != stable(cf_rows[code])
    ]
    if changed != [TARGET]:
        raise RuntimeError(
            "V8152B_CHANGED_SCORE_SET_NOT_TARGET_ONLY:"
            + ",".join(changed[:20])
        )

    now = datetime.now(KST).isoformat(timespec="seconds")

    meta["status"] = "PRODUCTION_SOURCE_APPLIED_API_REBUILT"
    integration = dict(meta.get("integration") or {})
    integration.update({
        "production_api_rebuilt": True,
        "production_api_rebuild_mode": "SCHEDULED_API_REBUILD_ADOPTED_V8152B",
        "production_api_rebuild_commit": FIRST_SCHEDULED_API_COMMIT,
        "production_api_source_commit": manifest.get("source_commit"),
        "production_api_basis_date": manifest.get("basis_date"),
        "production_api_source_build_id": manifest.get("source_build_id"),
        "production_api_supply_sha256": supply_sha,
    })
    meta["integration"] = integration
    meta["post_apply_validation"] = {
        "universe_count": len(actual_rows),
        "counterfactual_ready_count": cf_ready,
        "actual_ready_count": actual_ready,
        "counterfactual_limited_count": cf_limited,
        "actual_limited_count": actual_limited,
        "counterfactual_blocker_occurrences": cf_blockers,
        "actual_blocker_occurrences": actual_blockers,
        "ready_delta": 1,
        "limited_delta": -1,
        "blocker_occurrences_reduced_by": 1,
        "changed_score_row_count": 1,
        "changed_score_tickers": [TARGET],
        "actual_supply_points": 4,
    }
    meta["next_step"] = "POST_SUPPLY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8153"
    PROD_SUPPLY_META.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    PROD_SUPPLY_LOG.write_text(
        "\n".join([
            f"VERSION={V8151_VERSION}",
            "STATUS=PRODUCTION_SOURCE_APPLIED_API_REBUILT",
            "SOURCE_COUNT=9",
            "NARROW_PATCH_TICKER=072130",
            "NARROW_PATCH_SUPPLY_STATUS=OK",
            "NARROW_PATCH_SUPPLY_LEVEL=경계",
            "PRODUCTION_API_REBUILT=true",
            "PRODUCTION_API_REBUILD_MODE=SCHEDULED_API_REBUILD_ADOPTED_V8152B",
            f"PRODUCTION_API_REBUILD_COMMIT={FIRST_SCHEDULED_API_COMMIT}",
            f"PRODUCTION_API_SOURCE_COMMIT={manifest.get('source_commit')}",
            f"PRODUCTION_API_BASIS_DATE={manifest.get('basis_date')}",
            f"PRODUCTION_API_SOURCE_BUILD_ID={manifest.get('source_build_id')}",
            f"CURRENT_SCORER_UNIVERSE={len(actual_rows)}",
            f"COUNTERFACTUAL_READY={cf_ready}",
            f"ACTUAL_READY={actual_ready}",
            f"COUNTERFACTUAL_LIMITED={cf_limited}",
            f"ACTUAL_LIMITED={actual_limited}",
            f"COUNTERFACTUAL_BLOCKERS={cf_blockers}",
            f"ACTUAL_BLOCKERS={actual_blockers}",
            "READY_DELTA=1",
            "LIMITED_DELTA=-1",
            "BLOCKER_REDUCED_BY=1",
            "CHANGED_SCORE_ROWS=1",
            "CHANGED_SCORE_TICKERS=072130",
            "ACTUAL_SUPPLY_POINTS=4",
            "SCORING_POLICY_MODIFIED=false",
            "SUPPLY_POLICY_MODIFIED=false",
            "STATUS_OK=true",
            "NEXT_STEP=POST_SUPPLY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8153",
        ]) + "\n",
        encoding="utf-8",
    )

    summary = {
        "version": VERSION,
        "generated_at_kst": now,
        "status": "SCHEDULED_PRODUCTION_UANGEL_SUPPLY_APPLY_ADOPTED",
        "v8151_version": V8151_VERSION,
        "v8151_result_commit": V8151_RESULT_COMMIT,
        "first_scheduled_api_commit": FIRST_SCHEDULED_API_COMMIT,
        "policy_version": POLICY_VERSION,
        "supply_policy_version": SUPPLY_POLICY_VERSION,
        "production_api": {
            "basis_date": manifest.get("basis_date"),
            "source_build_id": manifest.get("source_build_id"),
            "source_commit": manifest.get("source_commit"),
            "safe_to_analyze_as_latest": manifest.get("safe_to_analyze_as_latest"),
            "table_row_counts": {
                key: value["row_count"]
                for key, value in manifest["tables"].items()
            },
            "target_tables": appearances.get(TARGET) or [],
        },
        "supply_source": {
            "row_count": 9,
            "sha256": supply_sha,
            "manifest_sha256": manifest_supply_sha,
            "hash_applied": True,
            "target_ticker": TARGET,
            "target_name": TARGET_NAME,
            "target_status": "OK",
            "target_level": "경계",
        },
        "counterfactual_scorer": {
            "universe_count": len(cf_rows),
            "ready_count": cf_ready,
            "limited_count": cf_limited,
            "blocker_occurrences": cf_blockers,
            "target_status": cf_target.get("score_status"),
            "target_missing_components": split_missing(
                cf_target.get("missing_components")
            ),
        },
        "actual_scorer": {
            "universe_count": len(actual_rows),
            "ready_count": actual_ready,
            "limited_count": actual_limited,
            "blocker_occurrences": actual_blockers,
            "target_status": actual_target.get("score_status"),
            "target_supply_points": 4,
        },
        "ready_delta": 1,
        "limited_delta": -1,
        "blocker_occurrences_reduced_by": 1,
        "changed_score_row_count": 1,
        "changed_score_tickers": [TARGET],
        "hard_guards": {
            "production_api_modified": False,
            "production_supply_source_csv_modified": False,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_ocf_cache_modified": False,
            "production_price_elasticity_cache_modified": False,
            "scoring_policy_modified": False,
            "supply_policy_modified": False,
            "source_value_imputed": False,
            "issuer_mapping_guessed": False,
            "duplicate_api_rebuild_performed": False,
        },
        "next_step": "POST_SUPPLY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8153",
    }
    SUMMARY_OUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    LOG_OUT.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=SCHEDULED_PRODUCTION_UANGEL_SUPPLY_APPLY_ADOPTED",
            f"FIRST_SCHEDULED_API_COMMIT={FIRST_SCHEDULED_API_COMMIT}",
            "SUPPLY_SOURCE_ROWS=9",
            "SUPPLY_SOURCE_HASH_APPLIED=true",
            f"SCORER_UNIVERSE={len(actual_rows)}",
            f"COUNTERFACTUAL_READY={cf_ready}",
            f"ACTUAL_READY={actual_ready}",
            f"COUNTERFACTUAL_LIMITED={cf_limited}",
            f"ACTUAL_LIMITED={actual_limited}",
            f"COUNTERFACTUAL_BLOCKERS={cf_blockers}",
            f"ACTUAL_BLOCKERS={actual_blockers}",
            "READY_DELTA=1",
            "LIMITED_DELTA=-1",
            "BLOCKER_REDUCED_BY=1",
            "CHANGED_SCORE_ROWS=1",
            "CHANGED_SCORE_TICKERS=072130",
            "ACTUAL_SUPPLY_POINTS=4",
            "PRODUCTION_API_MODIFIED=false",
            "PRODUCTION_SUPPLY_SOURCE_CSV_MODIFIED=false",
            "DUPLICATE_API_REBUILD_PERFORMED=false",
            "STATUS_OK=true",
            "NEXT_STEP=POST_SUPPLY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8153",
        ]) + "\n",
        encoding="utf-8",
    )

    DOC_OUT.parent.mkdir(parents=True, exist_ok=True)
    DOC_OUT.write_text(
        "\n".join([
            "# V8.15.2B scheduled UANGEL supply apply adoption",
            "",
            "- Scheduled API rebuild already consumed the 9-row verified supply source.",
            "- No duplicate production rebuild is performed.",
            "- 유엔젤 (072130) is `OK / 경계` in production.",
            "- Manifest supply hash equals the current persistent supply CSV hash.",
            "- Counterfactual restores only 072130 to `LIMITED / 없음`.",
            "- Actual effect must be READY +1, LIMITED -1, blocker -1.",
            "- Only score row 072130 may differ.",
            "- Actual supply component score is 4 points.",
            "",
            "Next: `POST_SUPPLY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8153`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8152B_SCHEDULED_UANGEL_SUPPLY_ADOPTION=PASS")

if __name__ == "__main__":
    main()
