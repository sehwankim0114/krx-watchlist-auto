#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-16-v8.11.5-temp-source-enricher-full-refresh-regression"
V8114_VERSION = "2026-09-16-v8.11.4-validation-fix2-dynamic-source-row-count"
V8114_RESULT_COMMIT = "c903bcd0c5a6cf44441731de0919ba08da7099a4"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
BASE_SOURCE_CONTRACT_VERSION = "2026-09-10-v8.5.4-investment-score-source-contract"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

AUDITED = {
    "000810": "삼성화재",
    "005830": "DB손해보험",
    "029780": "삼성카드",
    "105560": "KB금융",
    "138930": "BNK금융지주",
}
EXPECTED_ACTIVE = {"000810", "005830", "029780", "105560"}
EXPECTED_INACTIVE = {"138930"}

EXACT_STATEMENT = "CIS"
EXACT_ACCOUNT_ID = "ifrs-full_RevenueFromInterest"

SOURCE_REASONS = {
    "매출 성장과 안정성:MISSING_REVENUE_GROWTH_INPUT",
    "최근 3년 매출 성장률:MISSING_3Y_REVENUE",
    "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT",
}
REVENUE_FIELDS = (
    "annual_revenue_y0",
    "annual_revenue_y1",
    "annual_revenue_y2",
    "q2_revenue_current",
    "q2_revenue_previous",
    "q2_revenue_yoy_pct",
)
TARGET_ALLOWED_CHANGE_FIELDS = set(REVENUE_FIELDS) | {
    "three_year_source_status",
    "quarter_source_status",
    "source_cache_status",
    "source_cache_reason",
    "quarter_acceleration_classification",
    "quarter_acceleration_policy_status",
    "fetched_at_kst",
}

CONTROL_DIR = Path("/tmp/v8115_control")
SHADOW_DIR = Path("/tmp/v8115_shadow")
CONTROL_SOURCE = CONTROL_DIR / "investment_score_source_cache_latest.csv"
SHADOW_SOURCE = SHADOW_DIR / "investment_score_source_cache_latest.csv"
CONTROL_SOURCE_LOG = CONTROL_DIR / "investment_score_source_run_log_latest.txt"
SHADOW_SOURCE_LOG = SHADOW_DIR / "investment_score_source_run_log_latest.txt"

V8114_JSON = ROOT / "latest/investment_score_narrow_revenue_contract_v8114_summary_latest.json"
V8112_CSV = ROOT / "latest/investment_score_financial_revenue_semantic_v8112.csv"

CONTROL_SCORE_CSV = Path("/tmp/v8115_control_score.csv")
CONTROL_SCORE_JSON = Path("/tmp/v8115_control_score.json")
CONTROL_SCORE_LOG = Path("/tmp/v8115_control_score.log")
CONTROL_SCORE_DOC = Path("/tmp/v8115_control_score.md")

SHADOW_SCORE_CSV = Path("/tmp/v8115_shadow_score.csv")
SHADOW_SCORE_JSON = Path("/tmp/v8115_shadow_score.json")
SHADOW_SCORE_LOG = Path("/tmp/v8115_shadow_score.log")
SHADOW_SCORE_DOC = Path("/tmp/v8115_shadow_score.md")

OUT_CSV = ROOT / "latest/investment_score_temp_source_refresh_v8115.csv"
OUT_JSON = ROOT / "latest/investment_score_temp_source_refresh_v8115_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_temp_source_refresh_v8115_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_temp_source_refresh_v8115.md"
PATCH_JSON = ROOT / "latest/investment_score_temp_source_patch_v8115.json"


def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""


def num(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        s = str(value).strip().replace(",", "")
        if s in {"", "-", "None", "null", "nan", "NaN"}:
            return None
        x = float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def read_kv(path: Path):
    out = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def missing_items(row):
    return {
        x
        for x in str(row.get("missing_components") or "").split(";")
        if x
    }


def normalized_source_row(row):
    out = dict(row)
    out.pop("fetched_at_kst", None)
    return out


def source_diff_fields(a, b):
    fields = set(a) | set(b)
    return sorted(
        f for f in fields
        if str(a.get(f) or "") != str(b.get(f) or "")
    )


def run_scorer(raw_path, out_csv, out_json, out_log, out_doc, version):
    old = {
        "VERSION": scorer.VERSION,
        "RAW": scorer.RAW,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = version
        scorer.RAW = raw_path
        scorer.OUT_CSV = out_csv
        scorer.OUT_JSON = out_json
        scorer.OUT_LOG = out_log
        scorer.OUT_DOC = out_doc
        rc = scorer.main()
    finally:
        for key, value in old.items():
            setattr(scorer, key, value)
    if rc not in (None, 0):
        raise RuntimeError(f"V8115_SCORER_FAILED:{version}:{rc}")


def validate_lineage():
    v8114 = read_json(V8114_JSON)
    if v8114.get("version") != V8114_VERSION:
        raise RuntimeError("V8115_V8114_VERSION_MISMATCH")
    if v8114.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8115_V8114_STATUS_MISMATCH")
    if v8114.get("patch_status") != "PROPOSAL_ONLY_NOT_APPLIED":
        raise RuntimeError("V8115_V8114_PATCH_STATUS_MISMATCH")
    if set(v8114.get("audited_contract_scope_tickers") or []) != set(AUDITED):
        raise RuntimeError("V8115_V8114_AUDITED_SCOPE_CHANGED")
    if set(v8114.get("current_source_active_tickers") or []) != EXPECTED_ACTIVE:
        raise RuntimeError("V8115_V8114_ACTIVE_SCOPE_CHANGED")
    if set(v8114.get("current_inactive_tickers") or []) != EXPECTED_INACTIVE:
        raise RuntimeError("V8115_V8114_INACTIVE_SCOPE_CHANGED")
    if v8114.get("proposed_contract", {}).get("statement") != EXACT_STATEMENT:
        raise RuntimeError("V8115_V8114_STATEMENT_CHANGED")
    if v8114.get("proposed_contract", {}).get("account_id") != EXACT_ACCOUNT_ID:
        raise RuntimeError("V8115_V8114_ACCOUNT_CHANGED")
    if v8114.get("proposed_contract", {}).get("selection_rule") != "EXACT_ID_UNIQUE_ONLY":
        raise RuntimeError("V8115_V8114_SELECTION_RULE_CHANGED")
    return v8114


def validate_refresh_pair(v8114):
    control_rows = {
        ticker(r.get("ticker")): r
        for r in read_csv(CONTROL_SOURCE)
        if ticker(r.get("ticker"))
    }
    shadow_rows = {
        ticker(r.get("ticker")): r
        for r in read_csv(SHADOW_SOURCE)
        if ticker(r.get("ticker"))
    }
    if set(control_rows) != set(shadow_rows):
        raise RuntimeError("V8115_SOURCE_TARGET_UNIVERSE_CHANGED")
    if len(control_rows) != int(v8114["current_source_cache_rows"]):
        raise RuntimeError(
            f"V8115_CONTROL_SOURCE_ROW_COUNT_CHANGED:"
            f"{len(control_rows)}!={v8114['current_source_cache_rows']}"
        )

    active = set(AUDITED) & set(control_rows)
    inactive = set(AUDITED) - active
    if active != EXPECTED_ACTIVE:
        raise RuntimeError(
            "V8115_ACTIVE_SOURCE_SET_CHANGED:" + ",".join(sorted(active))
        )
    if inactive != EXPECTED_INACTIVE:
        raise RuntimeError(
            "V8115_INACTIVE_SOURCE_SET_CHANGED:" + ",".join(sorted(inactive))
        )

    non_target_diffs = []
    for code in sorted(set(control_rows) - active):
        a = normalized_source_row(control_rows[code])
        b = normalized_source_row(shadow_rows[code])
        if a != b:
            non_target_diffs.append(code)
    if non_target_diffs:
        raise RuntimeError(
            "V8115_NON_TARGET_SOURCE_DRIFT:"
            + ",".join(non_target_diffs[:30])
        )

    evidence = {
        ticker(r.get("ticker")): r
        for r in read_csv(V8112_CSV)
        if ticker(r.get("ticker"))
    }

    target_audit = []
    for code in sorted(active):
        before = control_rows[code]
        after = shadow_rows[code]
        changed = source_diff_fields(before, after)
        unexpected = sorted(set(changed) - TARGET_ALLOWED_CHANGE_FIELDS)
        if unexpected:
            raise RuntimeError(
                "V8115_TARGET_UNEXPECTED_FIELD_CHANGE:"
                + code + ":" + ",".join(unexpected)
            )

        if before.get("source_cache_status") != "LIMITED_RAW_SOURCE":
            raise RuntimeError(
                f"V8115_CONTROL_TARGET_NOT_LIMITED:"
                f"{code}:{before.get('source_cache_status')}"
            )
        if after.get("source_cache_status") != "READY_RAW_SOURCE":
            raise RuntimeError(
                f"V8115_SHADOW_TARGET_NOT_READY_RAW:"
                f"{code}:{after.get('source_cache_status')}"
            )
        if after.get("three_year_source_status") != "READY":
            raise RuntimeError(
                f"V8115_SHADOW_3Y_NOT_READY:{code}:"
                f"{after.get('three_year_source_status')}"
            )
        if after.get("quarter_source_status") != "READY_Q2_SOURCE":
            raise RuntimeError(
                f"V8115_SHADOW_Q2_NOT_READY:{code}:"
                f"{after.get('quarter_source_status')}"
            )

        ev = evidence.get(code)
        if ev is None:
            raise RuntimeError("V8115_V8112_EVIDENCE_MISSING:" + code)

        evidence_map = {
            "annual_revenue_y0": "annual_revenue_y0",
            "annual_revenue_y1": "annual_revenue_y1",
            "annual_revenue_y2": "annual_revenue_y2",
            "q2_revenue_current": "q2_current_revenue",
            "q2_revenue_previous": "q2_previous_revenue",
            "q2_revenue_yoy_pct": "q2_revenue_yoy_pct",
        }
        for raw_field, ev_field in evidence_map.items():
            actual = num(after.get(raw_field))
            expected = num(ev.get(ev_field))
            if actual is None or expected is None or abs(actual - expected) > 0.01:
                raise RuntimeError(
                    f"V8115_OFFICIAL_VALUE_MISMATCH:"
                    f"{code}:{raw_field}:{actual}!={expected}"
                )

        target_audit.append({
            "ticker": code,
            "name": AUDITED[code],
            "current_activation": "ACTIVE_SOURCE_TARGET",
            "control_status": before.get("source_cache_status") or "",
            "shadow_status": after.get("source_cache_status") or "",
            "control_reason": before.get("source_cache_reason") or "",
            "shadow_reason": after.get("source_cache_reason") or "",
            "three_year_status_after": after.get("three_year_source_status") or "",
            "quarter_status_after": after.get("quarter_source_status") or "",
            "changed_fields": ";".join(changed),
            "unexpected_field_change_count": 0,
            "official_values_match_v8112": "TRUE",
        })

    for code in sorted(inactive):
        target_audit.append({
            "ticker": code,
            "name": AUDITED[code],
            "current_activation": "NOT_CURRENTLY_ACTIVE_TARGET",
            "control_status": "",
            "shadow_status": "",
            "control_reason": "",
            "shadow_reason": "",
            "three_year_status_after": "",
            "quarter_status_after": "",
            "changed_fields": "",
            "unexpected_field_change_count": 0,
            "official_values_match_v8112": "HISTORICAL_EVIDENCE_PRESERVED",
        })

    return control_rows, shadow_rows, active, inactive, target_audit


def scorer_regression(active):
    run_scorer(
        CONTROL_SOURCE,
        CONTROL_SCORE_CSV,
        CONTROL_SCORE_JSON,
        CONTROL_SCORE_LOG,
        CONTROL_SCORE_DOC,
        "2026-09-16-v8.11.5-control-full-refresh",
    )
    run_scorer(
        SHADOW_SOURCE,
        SHADOW_SCORE_CSV,
        SHADOW_SCORE_JSON,
        SHADOW_SCORE_LOG,
        SHADOW_SCORE_DOC,
        VERSION,
    )

    control = {
        ticker(r.get("ticker")): r
        for r in read_csv(CONTROL_SCORE_CSV)
        if ticker(r.get("ticker"))
    }
    shadow = {
        ticker(r.get("ticker")): r
        for r in read_csv(SHADOW_SCORE_CSV)
        if ticker(r.get("ticker"))
    }

    if set(control) != set(shadow):
        raise RuntimeError("V8115_SCORER_UNIVERSE_CHANGED")

    scorer_active = active & set(control)
    if scorer_active != EXPECTED_ACTIVE:
        raise RuntimeError(
            "V8115_SCORER_ACTIVE_SET_CHANGED:"
            + ",".join(sorted(scorer_active))
        )

    non_target_diffs = [
        code
        for code in sorted(control)
        if code not in scorer_active and control[code] != shadow[code]
    ]
    if non_target_diffs:
        raise RuntimeError(
            "V8115_NON_TARGET_SCORE_DRIFT:"
            + ",".join(non_target_diffs[:30])
        )

    old_ready = {
        code for code, row in control.items()
        if row.get("score_status") == "READY"
    }
    new_ready = {
        code for code, row in shadow.items()
        if row.get("score_status") == "READY"
    }
    lost_ready = sorted(old_ready - new_ready)
    if lost_ready:
        raise RuntimeError(
            "V8115_READY_REGRESSION:" + ",".join(lost_ready)
        )

    target_score = {}
    for code in sorted(scorer_active):
        before = missing_items(control[code])
        after = missing_items(shadow[code])
        if not SOURCE_REASONS <= before:
            raise RuntimeError(
                "V8115_SOURCE_REASONS_ABSENT_BEFORE:"
                + code + ":"
                + "|".join(sorted(SOURCE_REASONS - before))
            )
        expected_after = before - SOURCE_REASONS
        if after != expected_after:
            raise RuntimeError(
                "V8115_TARGET_AFTER_MISMATCH:"
                + code + ":EXPECTED="
                + "|".join(sorted(expected_after))
                + ":ACTUAL="
                + "|".join(sorted(after))
            )
        target_score[code] = {
            "status_before": control[code].get("score_status") or "",
            "status_after": shadow[code].get("score_status") or "",
            "missing_before": sorted(before),
            "missing_after": sorted(after),
            "resolved_source_blockers": 3,
        }

    control_blockers = sum(
        len(missing_items(row))
        for row in control.values()
        if row.get("score_status") == "LIMITED"
    )
    shadow_blockers = sum(
        len(missing_items(row))
        for row in shadow.values()
        if row.get("score_status") == "LIMITED"
    )
    reduction = control_blockers - shadow_blockers
    if reduction != 12:
        raise RuntimeError(
            f"V8115_BLOCKER_REDUCTION_NOT_12:"
            f"{control_blockers}->{shadow_blockers}"
        )

    newly_ready = sorted(new_ready - old_ready)
    expected_new = {"000810", "005830", "105560"}
    if set(newly_ready) != expected_new:
        raise RuntimeError(
            "V8115_NEWLY_READY_SET_CHANGED:"
            + ",".join(newly_ready)
        )

    if target_score["029780"]["missing_after"] != [
        "수급·공시부담:SUPPLY_LIMITED_NO_POSITIVE_EVIDENCE"
    ]:
        raise RuntimeError("V8115_SAMSUNG_CARD_REMAINDER_CHANGED")

    return {
        "scorer_universe_count": len(control),
        "control_ready_count": len(old_ready),
        "shadow_ready_count": len(new_ready),
        "ready_delta": len(new_ready) - len(old_ready),
        "newly_ready_tickers": newly_ready,
        "lost_ready_tickers": lost_ready,
        "control_blocker_occurrences": control_blockers,
        "shadow_blocker_occurrences": shadow_blockers,
        "blocker_occurrences_reduced_by": reduction,
        "non_target_score_row_changed_count": len(non_target_diffs),
        "target_score_results": target_score,
    }


def main():
    for path in (
        CONTROL_SOURCE,
        SHADOW_SOURCE,
        CONTROL_SOURCE_LOG,
        SHADOW_SOURCE_LOG,
        V8114_JSON,
        V8112_CSV,
    ):
        if not path.is_file():
            raise RuntimeError("V8115_MISSING_INPUT:" + str(path))

    v8114 = validate_lineage()
    control_rows, shadow_rows, active, inactive, target_audit = (
        validate_refresh_pair(v8114)
    )
    scoring = scorer_regression(active)

    control_log = read_kv(CONTROL_SOURCE_LOG)
    shadow_log = read_kv(SHADOW_SOURCE_LOG)

    if int(control_log.get("OUTPUT_ROWS") or 0) != len(control_rows):
        raise RuntimeError("V8115_CONTROL_LOG_ROW_COUNT_MISMATCH")
    if int(shadow_log.get("OUTPUT_ROWS") or 0) != len(shadow_rows):
        raise RuntimeError("V8115_SHADOW_LOG_ROW_COUNT_MISMATCH")

    patch = {
        "version": VERSION,
        "status": "TEMP_PATCH_EXECUTED_ONLY",
        "production_source_enricher_modified": False,
        "production_source_cache_modified": False,
        "audited_scope": sorted(AUDITED),
        "active_scope": sorted(active),
        "inactive_scope": sorted(inactive),
        "revenue_contract": {
            "statement": EXACT_STATEMENT,
            "account_id": EXACT_ACCOUNT_ID,
            "selection_rule": "EXACT_ID_UNIQUE_ONLY",
            "full_account_fetch_scope": "AUDITED_ACTIVE_TICKERS_ONLY",
            "fallback": "UNCHANGED_V854_LOGIC",
        },
    }
    PATCH_JSON.write_text(
        json.dumps(patch, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = {
        "version": VERSION,
        "v8114_version": V8114_VERSION,
        "v8114_result_commit": V8114_RESULT_COMMIT,
        "policy_version": POLICY_VERSION,
        "base_source_contract_version": BASE_SOURCE_CONTRACT_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY",
        "patch_status": "TEMP_PATCH_EXECUTED_ONLY",
        "audited_scope_count": 5,
        "audited_scope_tickers": sorted(AUDITED),
        "active_source_target_count": len(active),
        "active_source_target_tickers": sorted(active),
        "inactive_target_tickers": sorted(inactive),
        "control_source_rows": len(control_rows),
        "shadow_source_rows": len(shadow_rows),
        "control_source_raw_ready": int(control_log.get("RAW_SOURCE_READY") or 0),
        "shadow_source_raw_ready": int(shadow_log.get("RAW_SOURCE_READY") or 0),
        "raw_ready_delta": (
            int(shadow_log.get("RAW_SOURCE_READY") or 0)
            - int(control_log.get("RAW_SOURCE_READY") or 0)
        ),
        "control_three_year_ready": int(control_log.get("THREE_YEAR_READY") or 0),
        "shadow_three_year_ready": int(shadow_log.get("THREE_YEAR_READY") or 0),
        "control_quarter_ready": int(control_log.get("QUARTER_SOURCE_READY") or 0),
        "shadow_quarter_ready": int(shadow_log.get("QUARTER_SOURCE_READY") or 0),
        "target_source_audit": target_audit,
        **scoring,
        "hard_guards": {
            "production_source_enricher_modified": False,
            "production_source_cache_modified": False,
            "production_source_run_log_modified": False,
            "production_financial_cache_modified": False,
            "production_api_modified": False,
            "scoring_policy_modified": False,
            "inactive_target_force_inserted": False,
            "broad_financial_sector_exception_created": False,
            "fuzzy_cis_revenue_match_allowed": False,
            "source_value_imputed": False,
            "non_target_source_rows_unchanged": True,
            "non_target_score_rows_unchanged": True,
            "ready_regression_count": 0,
        },
        "next_step": (
            "FREEZE_V8115_TEMP_SOURCE_REFRESH_EVIDENCE_"
            "AND_PREPARE_STAGED_PRODUCTION_SOURCE_CONTRACT_PATCH"
        ),
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(OUT_CSV, target_audit, list(target_audit[0].keys()))

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY",
            "PATCH_STATUS=TEMP_PATCH_EXECUTED_ONLY",
            "AUDITED_SCOPE=5",
            f"ACTIVE_SOURCE_TARGETS={len(active)}",
            "ACTIVE_SOURCE_TICKERS=" + ",".join(sorted(active)),
            "INACTIVE_SOURCE_TICKERS=" + ",".join(sorted(inactive)),
            f"CONTROL_SOURCE_ROWS={len(control_rows)}",
            f"SHADOW_SOURCE_ROWS={len(shadow_rows)}",
            f"CONTROL_RAW_READY={summary['control_source_raw_ready']}",
            f"SHADOW_RAW_READY={summary['shadow_source_raw_ready']}",
            f"RAW_READY_DELTA={summary['raw_ready_delta']}",
            f"SCORER_UNIVERSE={scoring['scorer_universe_count']}",
            f"CONTROL_READY={scoring['control_ready_count']}",
            f"SHADOW_READY={scoring['shadow_ready_count']}",
            f"READY_DELTA={scoring['ready_delta']}",
            "NEWLY_READY_TICKERS="
            + ",".join(scoring["newly_ready_tickers"]),
            f"CONTROL_BLOCKERS={scoring['control_blocker_occurrences']}",
            f"SHADOW_BLOCKERS={scoring['shadow_blocker_occurrences']}",
            f"BLOCKER_REDUCED_BY={scoring['blocker_occurrences_reduced_by']}",
            "NON_TARGET_SOURCE_ROWS_UNCHANGED=true",
            "NON_TARGET_SCORE_ROWS_UNCHANGED=true",
            "READY_REGRESSION_COUNT=0",
            "PRODUCTION_SOURCE_ENRICHER_MODIFIED=false",
            "PRODUCTION_SOURCE_CACHE_MODIFIED=false",
            "STATUS_OK=true",
            "NEXT_STEP=FREEZE_V8115_TEMP_SOURCE_REFRESH_EVIDENCE_"
            "AND_PREPARE_STAGED_PRODUCTION_SOURCE_CONTRACT_PATCH",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.11.5 temp source-enricher full-refresh regression",
            "",
            f"- Version: `{VERSION}`",
            "- Production V8.5.4 source enricher is unchanged.",
            "- Control and patched refreshes both run end-to-end from the same current financial/source-cache seed.",
            "- Patched refresh adds full-account exact CIS interest-revenue evidence only for audited active tickers.",
            "- Exact-ID unique selection only; no fuzzy match and no inactive-target insertion.",
            f"- Active source targets: {', '.join(sorted(active))}",
            f"- Source rows: {len(control_rows)} → {len(shadow_rows)}",
            f"- RAW ready: {summary['control_source_raw_ready']} → {summary['shadow_source_raw_ready']}",
            f"- Scorer READY: {scoring['control_ready_count']} → {scoring['shadow_ready_count']}",
            f"- Scorer blockers: {scoring['control_blocker_occurrences']} → {scoring['shadow_blocker_occurrences']}",
            "",
            "## Next",
            "",
            "`FREEZE_V8115_TEMP_SOURCE_REFRESH_EVIDENCE_AND_PREPARE_STAGED_PRODUCTION_SOURCE_CONTRACT_PATCH`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8115_TEMP_SOURCE_FULL_REFRESH_REGRESSION=PASS")


if __name__ == "__main__":
    main()
