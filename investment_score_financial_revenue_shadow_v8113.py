#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_source_extension_v8111 as v8111

VERSION = "2026-09-16-v8.11.3-validation-fix2-hard-guard-types"
V8111_VERSION = "2026-09-16-v8.11.1-validation-fix-preserve-daegu-baseline-row"
V8112_VERSION = "2026-09-16-v8.11.2-financial-revenue-semantic-alignment-audit"
V8111_RESULT_COMMIT = "295dd21da55135c5d26b89cebb6318ade7b09211"
V8112_RESULT_COMMIT = "1b6aad049721748a9dc68bf5362ee007f518ffcd"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
SOURCE_CONTRACT_VERSION = "2026-09-10-v8.5.4-investment-score-source-contract"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

TARGETS = {
    "000810": "삼성화재",
    "005830": "DB손해보험",
    "029780": "삼성카드",
    "105560": "KB금융",
    "138930": "BNK금융지주",
}
EXPECTED_REASONS = {
    "매출 성장과 안정성:MISSING_REVENUE_GROWTH_INPUT",
    "최근 3년 매출 성장률:MISSING_3Y_REVENUE",
    "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT",
}
REVENUE_FIELD_MAP = {
    # raw source-cache field -> V8.11.2 evidence CSV field
    "annual_revenue_y0": "annual_revenue_y0",
    "annual_revenue_y1": "annual_revenue_y1",
    "annual_revenue_y2": "annual_revenue_y2",
    "q2_revenue_current": "q2_current_revenue",
    "q2_revenue_previous": "q2_previous_revenue",
    "q2_revenue_yoy_pct": "q2_revenue_yoy_pct",
}
REVENUE_FIELDS = tuple(REVENUE_FIELD_MAP)
OP_FIELDS_REQUIRED_UNCHANGED = (
    "annual_operating_profit_y0",
    "annual_operating_profit_y1",
    "annual_operating_profit_y2",
    "q2_operating_profit_current",
    "q2_operating_profit_previous",
)

V8111_SCORE_CSV = ROOT / "latest/investment_score_v880_dry_run_v8111_latest.csv"
V8111_SCORE_JSON = ROOT / "latest/investment_score_v880_dry_run_v8111_summary_latest.json"
V8111_BLOCK_CSV = ROOT / "latest/investment_score_remaining_blockers_v8111.csv"
V8111_BLOCK_JSON = ROOT / "latest/investment_score_remaining_blockers_v8111_summary_latest.json"
V8111_SOURCE_CSV = ROOT / "latest/investment_score_source_cache_extension_v8111.csv"

V8112_CSV = ROOT / "latest/investment_score_financial_revenue_semantic_v8112.csv"
V8112_JSON = ROOT / "latest/investment_score_financial_revenue_semantic_v8112_summary_latest.json"

SOURCE_CSV = ROOT / "latest/investment_score_financial_revenue_shadow_source_v8113.csv"
SOURCE_JSON = ROOT / "latest/investment_score_financial_revenue_shadow_source_v8113_summary_latest.json"
OUT_CSV = ROOT / "latest/investment_score_v880_dry_run_v8113_latest.csv"
OUT_JSON = ROOT / "latest/investment_score_v880_dry_run_v8113_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_v880_dry_run_v8113_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_v880_dry_run_v8113.md"
BLOCK_CSV = ROOT / "latest/investment_score_remaining_blockers_v8113.csv"
BLOCK_JSON = ROOT / "latest/investment_score_remaining_blockers_v8113_summary_latest.json"
BLOCK_LOG = ROOT / "latest/investment_score_remaining_blockers_v8113_run_log_latest.txt"
BLOCK_DOC = ROOT / "docs/investment_score_remaining_blockers_v8113.md"

CONTROL_CSV = Path("/tmp/investment_score_v8113_control.csv")
CONTROL_JSON = Path("/tmp/investment_score_v8113_control.json")
CONTROL_LOG = Path("/tmp/investment_score_v8113_control.log")
CONTROL_DOC = Path("/tmp/investment_score_v8113_control.md")


def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""


def num(value):
    try:
        s = str(value or "").strip().replace(",", "")
        if s in {"", "-", "None", "null", "nan", "NaN"}:
            return None
        return float(s)
    except Exception:
        return None


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_csv_with_fields(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        rows = list(r)
        return rows, list(r.fieldnames or [])


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def missing_items(row):
    return {
        x for x in str(row.get("missing_components") or "").split(";")
        if x
    }


def validate_inputs():
    for p in (
        V8111_SCORE_CSV, V8111_SCORE_JSON, V8111_BLOCK_CSV,
        V8111_BLOCK_JSON, V8111_SOURCE_CSV, V8112_CSV, V8112_JSON,
    ):
        if not p.is_file():
            raise RuntimeError("V8113_MISSING_INPUT:" + str(p))

    s11 = read_json(V8111_SCORE_JSON)
    if s11.get("version") != V8111_VERSION:
        raise RuntimeError("V8113_V8111_VERSION_MISMATCH")
    if s11.get("status") != "DRY_RUN_ONLY":
        raise RuntimeError("V8113_V8111_STATUS_MISMATCH")
    if int(s11.get("ready_count") or 0) != 56 or int(s11.get("limited_count") or 0) != 56:
        raise RuntimeError("V8113_V8111_READY_LIMITED_MISMATCH")
    recheck = s11.get("v8111_source_extension_recheck") or {}
    if int(recheck.get("after_blocker_occurrences") or 0) != 276:
        raise RuntimeError("V8113_V8111_BLOCKERS_NOT_276")
    if int(recheck.get("after_source_cache_blockers") or 0) != 54:
        raise RuntimeError("V8113_V8111_SOURCE_BLOCKERS_NOT_54")
    if recheck.get("non_target_score_row_changed_count") != 0:
        raise RuntimeError("V8113_V8111_NON_TARGET_DRIFT_PRESENT")

    b11 = read_json(V8111_BLOCK_JSON)
    if b11.get("version") != V8111_VERSION:
        raise RuntimeError("V8113_V8111_BLOCK_VERSION_MISMATCH")
    if int(b11.get("limited_blocker_occurrences") or 0) != 276:
        raise RuntimeError("V8113_V8111_BLOCK_SUMMARY_NOT_276")
    if int((b11.get("source_group_counts") or {}).get("INVESTMENT_SCORE_SOURCE_CACHE") or 0) != 54:
        raise RuntimeError("V8113_V8111_SOURCE_GROUP_NOT_54")

    s12 = read_json(V8112_JSON)
    if s12.get("version") != V8112_VERSION:
        raise RuntimeError("V8113_V8112_VERSION_MISMATCH")
    if s12.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8113_V8112_STATUS_MISMATCH")
    if s12.get("all_five_financial_cache_exact_match") is not True:
        raise RuntimeError("V8113_V8112_NOT_ALL_FIVE_MATCHED")
    if int(s12.get("fully_aligned_count") or 0) != 5:
        raise RuntimeError("V8113_V8112_ALIGNED_COUNT_NOT_5")
    if int(s12.get("mismatch_count") or 0) != 0:
        raise RuntimeError("V8113_V8112_MISMATCH_PRESENT")
    if set(s12.get("fully_aligned_tickers") or []) != set(TARGETS):
        raise RuntimeError("V8113_V8112_TARGET_SET_CHANGED")
    if s12.get("candidate_statement") != "CIS":
        raise RuntimeError("V8113_V8112_STATEMENT_CHANGED")
    if s12.get("candidate_account_id") != "ifrs-full_RevenueFromInterest":
        raise RuntimeError("V8113_V8112_ACCOUNT_CHANGED")
    if s12.get("automatic_semantic_extension", {}).get("approved") is not False:
        raise RuntimeError("V8113_V8112_AUTO_APPROVAL_CHANGED")
    if any(v is not False for v in (s12.get("hard_guards") or {}).values()):
        raise RuntimeError("V8113_V8112_HARD_GUARD_NOT_FALSE")

    rows12 = {ticker(r.get("ticker")): r for r in read_csv(V8112_CSV)}
    if set(rows12) != set(TARGETS):
        raise RuntimeError("V8113_V8112_CSV_TARGET_SET_CHANGED")

    for code, row in rows12.items():
        if row.get("classification") != "EXACT_CIS_INTEREST_REVENUE_ALIGNED_WITH_FINANCIAL_CACHE":
            raise RuntimeError("V8113_V8112_CLASSIFICATION_CHANGED:" + code)
        if row.get("candidate_statement") != "CIS":
            raise RuntimeError("V8113_V8112_ROW_STATEMENT_CHANGED:" + code)
        if row.get("candidate_account_id") != "ifrs-full_RevenueFromInterest":
            raise RuntimeError("V8113_V8112_ROW_ACCOUNT_CHANGED:" + code)
        for raw_field, evidence_field in REVENUE_FIELD_MAP.items():
            if num(row.get(evidence_field)) is None:
                raise RuntimeError(
                    f"V8113_V8112_FIELD_MISSING:{code}:{raw_field}<-{evidence_field}"
                )

    return rows12


def reproduce_v8111_exact():
    # Rebuild the already-tested V8.11.1 shadow baseline entirely under /tmp.
    v8111.validate_inputs()
    _, shadow_prod, da_shadow_stats = v8111.reproduce_v8109_exact()

    rows = read_csv(V8111_SOURCE_CSV)
    if len(rows) != 1 or ticker(rows[0].get("ticker")) != "006370":
        raise RuntimeError("V8113_V8111_SOURCE_EXTENSION_CHANGED")
    daegu_source = rows[0]

    v8111.build_overlay_shadow_raw(daegu_source)
    v8111.build_shadow_fin(daegu_source)

    v8111.base.run_scorer(
        CONTROL_CSV, CONTROL_JSON, CONTROL_LOG, CONTROL_DOC,
        v8111.SHADOW_RAW, v8111.SHADOW_FIN, shadow_prod,
        "2026-09-16-v8.11.3-control-reproduce-v8111",
    )

    expected_rows = read_csv(V8111_SCORE_CSV)
    control_rows = read_csv(CONTROL_CSV)
    expected = {ticker(r.get("ticker")): r for r in expected_rows}
    control = {ticker(r.get("ticker")): r for r in control_rows}
    if len(expected) != 112 or len(control) != 112:
        raise RuntimeError("V8113_CONTROL_ROW_COUNT_NOT_112")
    if set(expected) != set(control):
        raise RuntimeError("V8113_CONTROL_TICKER_UNIVERSE_CHANGED")
    diffs = [c for c in sorted(expected) if expected[c] != control[c]]
    if diffs:
        raise RuntimeError("V8113_CONTROL_NOT_EXACT_V8111:" + ",".join(diffs))

    s = read_json(CONTROL_JSON)
    if int(s.get("ready_count") or 0) != 56 or int(s.get("limited_count") or 0) != 56:
        raise RuntimeError("V8113_CONTROL_READY_LIMITED_MISMATCH")

    return expected, shadow_prod, da_shadow_stats


def build_shadow_source(rows12):
    raw_rows, raw_fields = read_csv_with_fields(v8111.SHADOW_RAW)
    raw_map = {ticker(r.get("ticker")): r for r in raw_rows}
    if set(TARGETS) - set(raw_map):
        raise RuntimeError("V8113_TARGET_RAW_ROW_MISSING")

    candidate_rows = []
    per_target_audit = {}

    for code in sorted(TARGETS):
        original = raw_map[code]
        evidence = rows12[code]

        if original.get("source_cache_status") != "LIMITED_RAW_SOURCE":
            raise RuntimeError(
                "V8113_BASELINE_SOURCE_STATUS_CHANGED:"
                + code + ":" + str(original.get("source_cache_status") or "")
            )

        before = missing_items(
            next(r for r in read_csv(V8111_SCORE_CSV) if ticker(r.get("ticker")) == code)
        )
        if before != EXPECTED_REASONS:
            raise RuntimeError(
                "V8113_TARGET_BASELINE_REASON_SET_CHANGED:"
                + code + ":" + "|".join(sorted(before))
            )

        for field in REVENUE_FIELDS:
            if num(original.get(field)) is not None:
                raise RuntimeError(
                    "V8113_EXPECTED_BASELINE_REVENUE_FIELD_NOT_EMPTY:"
                    + code + ":" + field
                )

        for field in OP_FIELDS_REQUIRED_UNCHANGED:
            if num(original.get(field)) is None:
                raise RuntimeError(
                    "V8113_REQUIRED_BASELINE_OP_FIELD_MISSING:"
                    + code + ":" + field
                )

        patched = dict(original)
        changed = []
        for raw_field, evidence_field in REVENUE_FIELD_MAP.items():
            value = evidence[evidence_field]
            if str(patched.get(raw_field) or "") != str(value):
                changed.append(raw_field)
            patched[raw_field] = value

        # Preserve every non-revenue raw-source field byte-for-byte.
        for field in raw_fields:
            if field in REVENUE_FIELDS:
                continue
            if patched.get(field) != original.get(field):
                raise RuntimeError(
                    "V8113_NON_REVENUE_FIELD_CHANGED:" + code + ":" + field
                )

        raw_map[code] = patched
        candidate_rows.append({
            "ticker": code,
            "name": TARGETS[code],
            "source_status": "SHADOW_CANDIDATE_ONLY",
            "source_version": VERSION,
            "candidate_statement": evidence["candidate_statement"],
            "candidate_account_id": evidence["candidate_account_id"],
            "candidate_account_name": evidence["candidate_account_name"],
            **{
                raw_field: evidence[evidence_field]
                for raw_field, evidence_field in REVENUE_FIELD_MAP.items()
            },
            "semantic_extension_auto_approved": "FALSE",
            "source_contract_changed": "FALSE",
            "evidence_ref": f"V8112:{V8112_RESULT_COMMIT}:{code}:EXACT_CIS_INTEREST_REVENUE_ALIGNED_WITH_FINANCIAL_CACHE",
        })
        per_target_audit[code] = {
            "baseline_source_cache_status": original.get("source_cache_status") or "",
            "validated_revenue_fields_only": list(REVENUE_FIELDS),
            "changed_revenue_fields": changed,
            "non_revenue_field_change_count": 0,
            "baseline_operating_profit_fields_preserved": True,
        }

    patched_rows = [raw_map[ticker(r.get("ticker"))] for r in raw_rows]
    write_csv(v8111.SHADOW_RAW, patched_rows, raw_fields)
    write_csv(SOURCE_CSV, candidate_rows, list(candidate_rows[0].keys()))

    source_summary = {
        "version": VERSION,
        "v8112_version": V8112_VERSION,
        "v8112_result_commit": V8112_RESULT_COMMIT,
        "policy_version": POLICY_VERSION,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "SHADOW_CANDIDATE_ONLY",
        "source_count": 5,
        "source_tickers": sorted(TARGETS),
        "candidate_statement": "CIS",
        "candidate_account_id": "ifrs-full_RevenueFromInterest",
        "validated_revenue_fields": list(REVENUE_FIELDS),
        "evidence_column_map": REVENUE_FIELD_MAP,
        "semantic_extension_auto_approved": False,
        "source_contract_changed": False,
        "production_source_cache_mutated": False,
        "target_audit": per_target_audit,
    }
    SOURCE_JSON.write_text(
        json.dumps(source_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return per_target_audit


def write_blocker_outputs(after_rows):
    baseline_rows, fields = read_csv_with_fields(V8111_BLOCK_CSV)
    filtered = [r for r in baseline_rows if ticker(r.get("ticker")) not in TARGETS]
    write_csv(BLOCK_CSV, filtered, fields)

    if len(filtered) != 261:
        raise RuntimeError(f"V8113_FILTERED_BLOCKER_ROW_COUNT:{len(filtered)}!=261")

    category_counts = Counter(r["blocker_category"] for r in filtered)
    source_counts = Counter(r["source_group"] for r in filtered)
    single_tickers = {
        ticker(r["ticker"]) for r in filtered
        if str(r.get("single_blocker_ticker") or "").upper() == "TRUE"
    }

    if source_counts["INVESTMENT_SCORE_SOURCE_CACHE"] != 39:
        raise RuntimeError(
            "V8113_SOURCE_CACHE_BLOCKER_COUNT:"
            + str(source_counts["INVESTMENT_SCORE_SOURCE_CACHE"])
        )

    summary = {
        "version": VERSION,
        "policy_version": POLICY_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY",
        "production_unique_tickers": 112,
        "ready_count": 61,
        "limited_count": 51,
        "limited_blocker_occurrences": len(filtered),
        "single_blocker_ticker_count": len(single_tickers),
        "blocker_category_counts": dict(category_counts),
        "source_group_counts": dict(source_counts),
        "resolved_by_v8113_shadow": {
            "ticker_count": 5,
            "tickers": sorted(TARGETS),
            "blocker_occurrences": 15,
            "source_group": "INVESTMENT_SCORE_SOURCE_CACHE",
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "source_cache_mutated": False,
            "financial_cache_mutated": False,
            "source_contract_changed": False,
            "new_revenue_account_auto_approved": False,
            "financial_sector_exception_promoted": False,
            "source_value_imputed": False,
        },
        "next_step": "AUDIT_EXPLICIT_NARROW_SOURCE_CONTRACT_PATCH_WITH_FULL_UNIVERSE_REGRESSION",
    }
    BLOCK_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    BLOCK_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY",
            "READY=61",
            "LIMITED=51",
            "BLOCKER_OCCURRENCES=261",
            "SOURCE_CACHE_BLOCKERS=39",
            "RESOLVED_TICKERS=" + ",".join(sorted(TARGETS)),
            "RESOLVED_BLOCKERS=15",
            "SOURCE_CONTRACT_CHANGED=false",
            "STATUS_OK=true",
        ]) + "\n",
        encoding="utf-8",
    )
    BLOCK_DOC.parent.mkdir(parents=True, exist_ok=True)
    BLOCK_DOC.write_text(
        "\n".join([
            "# V8.11.3 remaining-blocker audit",
            "",
            "- Baseline: V8.11.1, 276 blocker occurrences.",
            "- Shadow-only removal: 15 source-cache blocker occurrences across five financial tickers.",
            "- Result: 261 blocker occurrences; source-cache group 54 → 39.",
            "- No production/source-contract mutation.",
            "",
        ]),
        encoding="utf-8",
    )
    return summary


def run_shadow(rows12):
    baseline_map, shadow_prod, da_shadow_stats = reproduce_v8111_exact()
    raw_audit = build_shadow_source(rows12)

    v8111.base.run_scorer(
        OUT_CSV, OUT_JSON, OUT_LOG, OUT_DOC,
        v8111.SHADOW_RAW, v8111.SHADOW_FIN, shadow_prod, VERSION,
    )

    rows = read_csv(OUT_CSV)
    if len(rows) != 112:
        raise RuntimeError(f"V8113_OUTPUT_ROW_COUNT:{len(rows)}")
    after_map = {ticker(r.get("ticker")): r for r in rows}
    if set(after_map) != set(baseline_map):
        raise RuntimeError("V8113_TICKER_UNIVERSE_CHANGED")

    non_target_diffs = [
        code for code in sorted(after_map)
        if code not in TARGETS and after_map[code] != baseline_map[code]
    ]
    if non_target_diffs:
        raise RuntimeError(
            "V8113_NON_TARGET_SCORE_ROW_DRIFT:" + ",".join(non_target_diffs)
        )

    target_results = {}
    for code in sorted(TARGETS):
        before = missing_items(baseline_map[code])
        after = missing_items(after_map[code])
        if before != EXPECTED_REASONS:
            raise RuntimeError(
                "V8113_TARGET_BEFORE_REASON_SET_CHANGED:"
                + code + ":" + "|".join(sorted(before))
            )
        if after:
            raise RuntimeError(
                "V8113_TARGET_STILL_BLOCKED:"
                + code + ":" + "|".join(sorted(after))
            )
        if after_map[code].get("score_status") != "READY":
            raise RuntimeError(
                "V8113_TARGET_NOT_READY:"
                + code + ":" + str(after_map[code].get("score_status") or "")
            )
        target_results[code] = {
            "name": TARGETS[code],
            "status_before": baseline_map[code].get("score_status") or "",
            "status_after": after_map[code].get("score_status") or "",
            "missing_before": sorted(before),
            "missing_after": [],
            "resolved_blocker_count": 3,
            "raw_overlay_audit": raw_audit[code],
        }

    old_ready = {
        c for c, r in baseline_map.items() if r.get("score_status") == "READY"
    }
    new_ready = {
        c for c, r in after_map.items() if r.get("score_status") == "READY"
    }
    lost_ready = sorted(old_ready - new_ready)
    newly_ready = sorted(new_ready - old_ready)
    if lost_ready:
        raise RuntimeError("V8113_READY_REGRESSION:" + ",".join(lost_ready))
    if set(newly_ready) != set(TARGETS):
        raise RuntimeError("V8113_NEWLY_READY_SET_MISMATCH:" + ",".join(newly_ready))

    baseline_blockers = sum(
        len(missing_items(r)) for r in baseline_map.values()
        if r.get("score_status") == "LIMITED"
    )
    after_blockers = sum(
        len(missing_items(r)) for r in rows
        if r.get("score_status") == "LIMITED"
    )
    if baseline_blockers != 276:
        raise RuntimeError(f"V8113_BASELINE_BLOCKERS:{baseline_blockers}")
    if after_blockers != 261:
        raise RuntimeError(f"V8113_AFTER_BLOCKERS:{after_blockers}")

    blocker_summary = write_blocker_outputs(rows)

    score_summary = read_json(OUT_JSON)
    score_summary["version"] = VERSION
    score_summary["status"] = "DRY_RUN_ONLY"
    score_summary["v8113_shadow_recheck"] = {
        "baseline_version": V8111_VERSION,
        "baseline_result_commit": V8111_RESULT_COMMIT,
        "evidence_version": V8112_VERSION,
        "evidence_result_commit": V8112_RESULT_COMMIT,
        "baseline_control_exact_match": True,
        "candidate_statement": "CIS",
        "candidate_account_id": "ifrs-full_RevenueFromInterest",
        "baseline_ready_count": 56,
        "after_ready_count": len(new_ready),
        "ready_delta": len(new_ready) - 56,
        "newly_ready_tickers": newly_ready,
        "lost_ready_tickers": lost_ready,
        "baseline_blocker_occurrences": baseline_blockers,
        "after_blocker_occurrences": after_blockers,
        "blocker_occurrences_reduced_by": baseline_blockers - after_blockers,
        "baseline_source_cache_blockers": 54,
        "after_source_cache_blockers": int(
            blocker_summary["source_group_counts"]["INVESTMENT_SCORE_SOURCE_CACHE"]
        ),
        "source_cache_blockers_reduced_by": 15,
        "target_results": target_results,
        "non_target_score_row_changed_count": len(non_target_diffs),
        "v8111_da_shadow_reproduction": da_shadow_stats,
    }
    score_summary["hard_guards"] = {
        "production_api_changed": False,
        "production_investment_score_written": False,
        "scoring_policy_changed": False,
        "source_cache_mutated": False,
        "financial_cache_mutated": False,
        "source_contract_changed": False,
        "new_revenue_account_auto_approved": False,
        "financial_sector_exception_promoted": False,
        "source_value_imputed": False,
        "h1_used_directly_as_q2": False,
        "ambiguous_revenue_account_promoted": False,
        "v8111_baseline_mutated": False,
        "non_target_score_rows_unchanged": True,
        "ready_regression_count": 0,
    }
    score_summary["next_step"] = (
        "AUDIT_EXPLICIT_NARROW_SOURCE_CONTRACT_PATCH_WITH_FULL_UNIVERSE_REGRESSION"
    )
    OUT_JSON.write_text(
        json.dumps(score_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=DRY_RUN_ONLY",
            "BASELINE_CONTROL_EXACT_MATCH=true",
            "BASELINE_READY=56",
            f"AFTER_READY={len(new_ready)}",
            f"READY_DELTA={len(new_ready)-56}",
            "NEWLY_READY_TICKERS=" + ",".join(newly_ready),
            "BLOCKER_OCCURRENCES=276->261",
            "BLOCKER_REDUCED_BY=15",
            "SOURCE_CACHE_BLOCKERS=54->39",
            "NON_TARGET_SCORE_ROWS_UNCHANGED=true",
            "READY_REGRESSION_COUNT=0",
            "SOURCE_CONTRACT_CHANGED=false",
            "NEW_REVENUE_ACCOUNT_AUTO_APPROVED=false",
            "FINANCIAL_SECTOR_EXCEPTION_PROMOTED=false",
            "SOURCE_VALUE_IMPUTED=false",
            "STATUS_OK=true",
            "NEXT_STEP=AUDIT_EXPLICIT_NARROW_SOURCE_CONTRACT_PATCH_WITH_FULL_UNIVERSE_REGRESSION",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.11.3 five-financial-ticker revenue shadow dry-run",
            "",
            f"- Version: `{VERSION}`",
            "- Baseline: exact reproduction of V8.11.1.",
            "- Evidence: V8.11.2 exact CIS `ifrs-full_RevenueFromInterest` alignment.",
            "- Scope: only six revenue fields for five audited tickers.",
            "- Operating-profit and all other raw-source fields are preserved exactly.",
            "- Expected result verified by scorer: five newly READY tickers, 15 blockers removed.",
            "",
            "## Safety",
            "",
            "- No source-contract change.",
            "- No production/source/financial cache mutation.",
            "- No automatic account approval.",
            "- No imputation.",
            "- No non-target score drift.",
            "",
        ]),
        encoding="utf-8",
    )


def main():
    rows12 = validate_inputs()
    run_shadow(rows12)
    print("V8113_SHADOW_FIVE_FINANCIAL_REVENUE_EXTENSION=PASS")


if __name__ == "__main__":
    main()
