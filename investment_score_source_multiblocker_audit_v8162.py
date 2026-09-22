#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-22-v8.16.2-source-cache-multiblocker-root-cause"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8161_VERSION = "2026-09-22-v8.16.1A-post-financial-apply-current-blocker-reaudit"
V8161_RESULT_COMMIT = "62fce7cabb644358dd3d717c7c46ba82c111a32e"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

V8161_JSON = ROOT / "latest/investment_score_current_blockers_v8161_summary_latest.json"
V8161_CSV = ROOT / "latest/investment_score_current_blockers_v8161.csv"
SOURCE_CACHE = ROOT / "latest/investment_score_source_cache_latest.csv"
SOURCE_LOG = ROOT / "latest/investment_score_source_run_log_latest.txt"
FIN_CACHE = ROOT / "latest/financial_valuation_cache_latest.csv"
FIN_LOG = ROOT / "latest/financial_valuation_run_log_latest.txt"

OUT_CSV = ROOT / "latest/investment_score_source_multiblocker_v8162.csv"
OUT_JSON = ROOT / "latest/investment_score_source_multiblocker_v8162_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_source_multiblocker_v8162_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_source_multiblocker_v8162.md"

VALID_IDENTITY = {"MATCH", "MATCH_NORMALIZED", "NAME_NOT_AVAILABLE"}
VALID_FINANCIAL_STATUS = {"READY", "PARTIAL"}

EXPECTED_SELECTED = {
    "000050","000105","001020","001460","002450","002990","002995",
    "003060","003480","003850","004990","006060","006125","006220",
    "008250","010120","011330","013890","014825","016590","023530",
    "024090","024110","058650","070960","071950","086790","092440",
    "097520","108675","139130","145990","241590","279570","298000",
    "298050","363280","446070","499790",
}

EXPECTED_ELIGIBLE_MISSING = {
    "000050","001020","001460","002450","002990","003060","003480",
    "003850","004990","006060","006220","008250","011330","013890",
    "016590","023530","024090","058650","070960","071950","097520",
    "145990","241590","298000","298050","363280","446070",
}

EXPECTED_UPSTREAM_BLOCKED = {
    "000105","002995","006125","010120","014825","108675",
}

EXPECTED_ANNUAL_QUARTER_LIMITED = {
    "024110","086790","139130","279570",
}
EXPECTED_QUARTER_ONLY_LIMITED = {"092440"}
EXPECTED_THREE_YEAR_ONLY_LIMITED = {"499790"}

def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def read_kv(path):
    out = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out

def current_financial_eligible(fin_rows):
    out = set()
    for r in fin_rows:
        code = ticker(r.get("ticker"))
        corp = "".join(ch for ch in str(r.get("corp_code") or "") if ch.isdigit())
        if not code or not corp:
            continue
        if str(r.get("financial_source_status") or "") != "OK":
            continue
        if str(r.get("financial_data_status") or "") not in VALID_FINANCIAL_STATUS:
            continue
        if str(r.get("corp_identity_status") or "") not in VALID_IDENTITY:
            continue
        out.add(code)
    return out

def main():
    for p in (V8161_JSON, V8161_CSV, SOURCE_CACHE, SOURCE_LOG, FIN_CACHE, FIN_LOG):
        if not p.is_file():
            raise RuntimeError("V8162_MISSING_INPUT:" + str(p))

    s = read_json(V8161_JSON)
    if s.get("version") != V8161_VERSION:
        raise RuntimeError("V8162_V8161_VERSION_MISMATCH")
    if s.get("status") != "AUDIT_ONLY_POST_FINANCIAL_DYNAMIC_CURRENT_BLOCKERS":
        raise RuntimeError("V8162_V8161_STATUS_MISMATCH")
    if s.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8162_POLICY_VERSION_MISMATCH")
    if s.get("selection_mode") != "MULTI_BLOCKER_GROUP":
        raise RuntimeError("V8162_SELECTION_MODE_NOT_MULTI")
    if s.get("selected_source_group") != "INVESTMENT_SCORE_SOURCE_CACHE":
        raise RuntimeError("V8162_SELECTED_GROUP_MISMATCH")
    if int(s.get("selected_ticker_count") or 0) != 39:
        raise RuntimeError("V8162_SELECTED_COUNT_NOT_39")
    if set(s.get("selected_tickers") or []) != EXPECTED_SELECTED:
        raise RuntimeError("V8162_SELECTED_SET_MISMATCH")
    if s.get("next_step") != "AUDIT_TOP_MULTI_BLOCKER_GROUP_V8162":
        raise RuntimeError("V8162_PREDECESSOR_NEXT_STEP_MISMATCH")

    source_group_counts = s.get("source_group_counts") or {}
    if int(source_group_counts.get("INVESTMENT_SCORE_SOURCE_CACHE") or 0) != 149:
        raise RuntimeError("V8162_SOURCE_GROUP_TOTAL_NOT_149")

    blockers = [
        r for r in read_rows(V8161_CSV)
        if r.get("source_group") == "INVESTMENT_SCORE_SOURCE_CACHE"
    ]
    selected_blockers = [
        r for r in blockers
        if ticker(r.get("ticker")) in EXPECTED_SELECTED
    ]
    excluded = [
        r for r in blockers
        if ticker(r.get("ticker")) not in EXPECTED_SELECTED
    ]

    if len(blockers) != 149:
        raise RuntimeError("V8162_BLOCKERS_NOT_149:" + str(len(blockers)))
    if len(selected_blockers) != 148:
        raise RuntimeError(
            "V8162_SELECTED_BLOCKERS_NOT_148:" + str(len(selected_blockers))
        )
    if len(excluded) != 1:
        raise RuntimeError("V8162_EXCLUDED_SINGLE_NOT_1")
    if (
        ticker(excluded[0].get("ticker")) != "357430"
        or excluded[0].get("recovery_status") != "EXHAUSTED_OFFICIAL_Q2_ACCEL_PATH"
    ):
        raise RuntimeError("V8162_EXCLUDED_SINGLE_NOT_357430_EXHAUSTED")

    reason_counts = Counter(r.get("blocker_reason") or "" for r in selected_blockers)
    expected_reasons = {
        "매출 성장과 안정성:MISSING_REVENUE_GROWTH_INPUT": 38,
        "최근 3년 매출 성장률:MISSING_3Y_REVENUE": 38,
        "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT": 38,
        "최근 3년 영업이익 성장률:MISSING_3Y_OP": 34,
    }
    if dict(reason_counts) != expected_reasons:
        raise RuntimeError(
            "V8162_REASON_COUNTS_CHANGED:" + repr(dict(reason_counts))
        )

    source_rows = read_rows(SOURCE_CACHE)
    fin_rows = read_rows(FIN_CACHE)
    source_map = {ticker(r.get("ticker")): r for r in source_rows if ticker(r.get("ticker"))}
    eligible = current_financial_eligible(fin_rows)

    if len(source_rows) != 254:
        raise RuntimeError("V8162_SOURCE_CACHE_ROWS_NOT_254:" + str(len(source_rows)))
    if len(fin_rows) != 299:
        raise RuntimeError("V8162_FIN_CACHE_ROWS_NOT_299:" + str(len(fin_rows)))
    if len(eligible) != 281:
        raise RuntimeError("V8162_CURRENT_ELIGIBLE_NOT_281:" + str(len(eligible)))

    source_codes = set(source_map)
    eligible_missing_all = eligible - source_codes
    source_extra = source_codes - eligible
    if eligible_missing_all != EXPECTED_ELIGIBLE_MISSING:
        raise RuntimeError(
            "V8162_ELIGIBLE_MISSING_SET_CHANGED:"
            + ",".join(sorted(eligible_missing_all))
        )
    if source_extra:
        raise RuntimeError(
            "V8162_SOURCE_EXTRA_VS_ELIGIBLE:" + ",".join(sorted(source_extra))
        )

    selected_missing = EXPECTED_SELECTED - source_codes
    if len(selected_missing) != 33:
        raise RuntimeError("V8162_SELECTED_MISSING_NOT_33")
    if (selected_missing & eligible) != EXPECTED_ELIGIBLE_MISSING:
        raise RuntimeError("V8162_ELIGIBLE_SELECTED_MISSING_BAD")
    if (selected_missing - eligible) != EXPECTED_UPSTREAM_BLOCKED:
        raise RuntimeError("V8162_UPSTREAM_BLOCKED_SET_BAD")

    present = EXPECTED_SELECTED & source_codes
    if len(present) != 6:
        raise RuntimeError("V8162_PRESENT_SELECTED_NOT_6")

    annual_quarter = set()
    quarter_only = set()
    three_year_only = set()

    for code in present:
        r = source_map[code]
        a = r.get("three_year_source_status") or ""
        q = r.get("quarter_source_status") or ""
        if a != "READY" and q != "READY_Q2_SOURCE":
            annual_quarter.add(code)
        elif a == "READY" and q != "READY_Q2_SOURCE":
            quarter_only.add(code)
        elif a != "READY" and q == "READY_Q2_SOURCE":
            three_year_only.add(code)
        else:
            raise RuntimeError("V8162_UNEXPECTED_PRESENT_READY_ROW:" + code)

    if annual_quarter != EXPECTED_ANNUAL_QUARTER_LIMITED:
        raise RuntimeError("V8162_ANNUAL_QUARTER_SET_BAD")
    if quarter_only != EXPECTED_QUARTER_ONLY_LIMITED:
        raise RuntimeError("V8162_QUARTER_ONLY_SET_BAD")
    if three_year_only != EXPECTED_THREE_YEAR_ONLY_LIMITED:
        raise RuntimeError("V8162_THREE_YEAR_ONLY_SET_BAD")

    lane_by_ticker = {}
    for code in EXPECTED_SELECTED:
        if code in EXPECTED_ELIGIBLE_MISSING:
            lane_by_ticker[code] = "ELIGIBLE_SOURCE_ROW_MISSING"
        elif code in EXPECTED_UPSTREAM_BLOCKED:
            lane_by_ticker[code] = "UPSTREAM_FINANCIAL_BLOCKED_SOURCE_ROW_MISSING"
        elif code in EXPECTED_ANNUAL_QUARTER_LIMITED:
            lane_by_ticker[code] = "EXISTING_ANNUAL_AND_QUARTER_LIMITED"
        elif code in EXPECTED_QUARTER_ONLY_LIMITED:
            lane_by_ticker[code] = "EXISTING_QUARTER_ONLY_LIMITED"
        elif code in EXPECTED_THREE_YEAR_ONLY_LIMITED:
            lane_by_ticker[code] = "EXISTING_THREE_YEAR_ONLY_LIMITED"
        else:
            raise RuntimeError("V8162_UNCLASSIFIED_SELECTED:" + code)

    lane_occurrences = Counter()
    lane_tickers = defaultdict(set)
    for r in selected_blockers:
        code = ticker(r.get("ticker"))
        lane = lane_by_ticker[code]
        lane_occurrences[lane] += 1
        lane_tickers[lane].add(code)

    expected_lane_occ = {
        "ELIGIBLE_SOURCE_ROW_MISSING": 108,
        "UPSTREAM_FINANCIAL_BLOCKED_SOURCE_ROW_MISSING": 24,
        "EXISTING_ANNUAL_AND_QUARTER_LIMITED": 12,
        "EXISTING_QUARTER_ONLY_LIMITED": 1,
        "EXISTING_THREE_YEAR_ONLY_LIMITED": 3,
    }
    if dict(lane_occurrences) != expected_lane_occ:
        raise RuntimeError(
            "V8162_LANE_OCCURRENCES_CHANGED:" + repr(dict(lane_occurrences))
        )

    source_log = read_kv(SOURCE_LOG)
    fin_log = read_kv(FIN_LOG)

    if source_log.get("OUTPUT_ROWS") != "254":
        raise RuntimeError("V8162_SOURCE_LOG_ROWS_NOT_254")
    if source_log.get("TARGETS") != "254":
        raise RuntimeError("V8162_SOURCE_LOG_TARGETS_NOT_254")
    if not source_log.get("RUN_AT_KST"):
        raise RuntimeError("V8162_SOURCE_RUN_AT_MISSING")

    scheduled_gate_compatible = bool(fin_log.get("RUN_AT_KST"))
    gate_reason = (
        "COMPATIBLE"
        if scheduled_gate_compatible
        else "FINANCIAL_RUN_AT_KST_MISSING_AFTER_V8160"
    )

    out_rows = []
    for code in sorted(EXPECTED_SELECTED):
        row = source_map.get(code) or {}
        code_blockers = [
            r for r in selected_blockers
            if ticker(r.get("ticker")) == code
        ]
        out_rows.append({
            "ticker": code,
            "lane": lane_by_ticker[code],
            "blocker_occurrences": len(code_blockers),
            "blocker_reasons": ";".join(
                sorted(r.get("blocker_reason") or "" for r in code_blockers)
            ),
            "current_financial_eligible": (
                "TRUE" if code in eligible else "FALSE"
            ),
            "source_cache_row_present": (
                "TRUE" if code in source_map else "FALSE"
            ),
            "source_cache_status": row.get("source_cache_status") or "",
            "source_cache_reason": row.get("source_cache_reason") or "",
            "three_year_source_status": row.get("three_year_source_status") or "",
            "quarter_source_status": row.get("quarter_source_status") or "",
            "deep_source_status": row.get("deep_source_status") or "",
            "fetched_at_kst": row.get("fetched_at_kst") or "",
        })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=list(out_rows[0].keys()),
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(out_rows)

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY_SOURCE_CACHE_MULTIBLOCKER_ROOT_CAUSE",
        "policy_version": POLICY_VERSION,
        "v8161_version": V8161_VERSION,
        "v8161_result_commit": V8161_RESULT_COMMIT,
        "source_group": "INVESTMENT_SCORE_SOURCE_CACHE",
        "source_group_total_blocker_occurrences": 149,
        "selected_multi_ticker_count": 39,
        "selected_multi_blocker_occurrences": 148,
        "excluded_known_exhausted_single": {
            "ticker": "357430",
            "blocker_occurrences": 1,
            "recovery_status": "EXHAUSTED_OFFICIAL_Q2_ACCEL_PATH",
        },
        "selected_reason_counts": expected_reasons,
        "current_cache_state": {
            "financial_cache_rows": 299,
            "source_cache_rows": 254,
            "current_financial_eligible_targets": 281,
            "eligible_missing_source_rows": 27,
            "source_rows_outside_current_eligible": 0,
            "source_cache_run_at_kst": source_log.get("RUN_AT_KST"),
        },
        "lanes": {
            lane: {
                "ticker_count": len(lane_tickers[lane]),
                "blocker_occurrences": lane_occurrences[lane],
                "tickers": sorted(lane_tickers[lane]),
            }
            for lane in expected_lane_occ
        },
        "highest_actionable_recovery_lane": {
            "lane": "ELIGIBLE_SOURCE_ROW_MISSING",
            "ticker_count": 27,
            "blocker_occurrences": 108,
            "recommended_action": (
                "RUN_CURRENT_PRODUCTION_SOURCE_REFRESH_IN_SHADOW"
            ),
        },
        "v854_scheduled_gate": {
            "compatible": scheduled_gate_compatible,
            "reason": gate_reason,
            "financial_run_at_kst_present": bool(fin_log.get("RUN_AT_KST")),
            "source_run_at_kst_present": bool(source_log.get("RUN_AT_KST")),
            "manual_dispatch_force_refresh_available": True,
        },
        "automatic_promotion": {
            "allowed": False,
            "promoted_ticker_count": 0,
        },
        "hard_guards": {
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_financial_run_log_modified": False,
            "production_api_modified": False,
            "production_score_written": False,
            "scoring_policy_modified": False,
            "source_value_imputed": False,
            "upstream_blocked_rows_forced_into_source_cache": False,
            "existing_partial_rows_reinterpreted": False,
        },
        "next_step": (
            "REPAIR_V854_GATE_AND_SHADOW_REFRESH_CURRENT_SOURCE_CACHE_V8163"
        ),
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY_SOURCE_CACHE_MULTIBLOCKER_ROOT_CAUSE",
            "SOURCE_GROUP=INVESTMENT_SCORE_SOURCE_CACHE",
            "SOURCE_GROUP_TOTAL_BLOCKERS=149",
            "SELECTED_MULTI_TICKERS=39",
            "SELECTED_MULTI_BLOCKERS=148",
            "EXCLUDED_EXHAUSTED_SINGLE=357430",
            "FINANCIAL_CACHE_ROWS=299",
            "SOURCE_CACHE_ROWS=254",
            "CURRENT_FINANCIAL_ELIGIBLE_TARGETS=281",
            "ELIGIBLE_SOURCE_ROW_MISSING_TICKERS=27",
            "ELIGIBLE_SOURCE_ROW_MISSING_BLOCKERS=108",
            "UPSTREAM_FINANCIAL_BLOCKED_TICKERS=6",
            "UPSTREAM_FINANCIAL_BLOCKED_BLOCKERS=24",
            "EXISTING_ANNUAL_AND_QUARTER_LIMITED_TICKERS=4",
            "EXISTING_ANNUAL_AND_QUARTER_LIMITED_BLOCKERS=12",
            "EXISTING_QUARTER_ONLY_LIMITED_TICKERS=1",
            "EXISTING_QUARTER_ONLY_LIMITED_BLOCKERS=1",
            "EXISTING_THREE_YEAR_ONLY_LIMITED_TICKERS=1",
            "EXISTING_THREE_YEAR_ONLY_LIMITED_BLOCKERS=3",
            (
                "V854_SCHEDULED_GATE_COMPATIBLE="
                + str(scheduled_gate_compatible).lower()
            ),
            f"V854_SCHEDULED_GATE_REASON={gate_reason}",
            "AUTOMATIC_PROMOTION=false",
            "PRODUCTION_DATA_MODIFIED=false",
            "STATUS_OK=true",
            (
                "NEXT_STEP="
                "REPAIR_V854_GATE_AND_SHADOW_REFRESH_CURRENT_SOURCE_CACHE_V8163"
            ),
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.16.2 source-cache multi-blocker root-cause audit",
            "",
            "- Current source-cache group: 149 blocker occurrences.",
            "- Selected multi-blocker lane: 39 tickers / 148 occurrences.",
            "- 357430 is excluded from the selected lane because its single Q2 acceleration path is already exhausted.",
            "- Current financial cache: 299 rows.",
            "- Current valid source-enricher targets: 281.",
            "- Current source cache: 254 rows.",
            "- 27 currently eligible tickers are missing from the source cache, accounting for 108 blockers.",
            "- 6 selected tickers are upstream-financial-blocked and account for 24 blockers.",
            "- 4 existing rows have both three-year and quarter source limitations (12 blockers).",
            "- 092440 has a quarter-only limitation (1 blocker).",
            "- 499790 has a three-year-only limitation (3 blockers).",
            (
                "- V8.5.4 scheduled gate compatibility: "
                + ("PASS" if scheduled_gate_compatible else "FAIL")
                + f" ({gate_reason})."
            ),
            "- No production data is modified.",
            "",
            "Next: REPAIR_V854_GATE_AND_SHADOW_REFRESH_CURRENT_SOURCE_CACHE_V8163",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8162_SOURCE_MULTIBLOCKER_AUDIT=PASS")
    print("V8162_SELECTED_MULTI_BLOCKERS=148")
    print("V8162_ELIGIBLE_MISSING_TICKERS=27")
    print("V8162_ELIGIBLE_MISSING_BLOCKERS=108")
    print(
        "V8162_V854_SCHEDULED_GATE_COMPATIBLE="
        + str(scheduled_gate_compatible).lower()
    )
    print(
        "V8162_NEXT_STEP="
        "REPAIR_V854_GATE_AND_SHADOW_REFRESH_CURRENT_SOURCE_CACHE_V8163"
    )

if __name__ == "__main__":
    main()
