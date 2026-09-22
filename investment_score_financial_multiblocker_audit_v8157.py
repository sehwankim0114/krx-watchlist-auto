#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-22-v8.15.7-financial-valuation-multiblocker-root-cause"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8156_VERSION = "2026-09-22-v8.15.6-mastern-q2-exhausted-dynamic-reaudit"
V8156_RESULT_COMMIT = "ab85795de6f5b365ea04dd8de0a69a85f7e23a52"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8156.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8156_summary_latest.json"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"
FIN_LOG = ROOT / "latest/financial_valuation_run_log_latest.txt"
RAW = ROOT / "latest/investment_score_source_cache_latest.csv"
RAW_LOG = ROOT / "latest/investment_score_source_run_log_latest.txt"
STATUS = ROOT / "api/status.json"
MANIFEST = ROOT / "api/two_table_v1/manifest.json"

OUT_CSV = ROOT / "latest/investment_score_financial_multiblocker_v8157.csv"
OUT_JSON = ROOT / "latest/investment_score_financial_multiblocker_v8157_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_financial_multiblocker_v8157_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_financial_multiblocker_v8157.md"

TARGET_GROUP = "FINANCIAL_VALUATION_CACHE"

EXPECTED_SELECTED = {
    "000050", "000105", "001020", "001460", "002450",
    "002990", "002995", "003060", "003480", "003850",
    "004990", "006060", "006125", "006220", "008250",
    "010120", "011330", "013890", "014825", "016590",
    "023530", "024090", "036580", "051910", "058650",
    "070960", "071950", "097520", "108675", "145990",
    "241590", "298000", "298050", "363280", "446070",
}

EXPECTED_REASON_COUNTS = {
    "PER:MISSING_PER": 35,
    "PBR:MISSING_PBR_OR_ROE": 33,
    "ROE:MISSING_ROE": 33,
    "순이익 흐름:MISSING_EARNINGS_TREND": 33,
    "영업이익 성장과 흑자 여부:MISSING_OP_PROFIT": 33,
    "영업이익률:MISSING_MARGIN": 33,
    "흑자 지속성과 이익 안정성:MISSING_EARNINGS_TREND": 33,
    "부채비율:MISSING_DEBT_RATIO": 29,
}

EXPECTED_LANES = {
    "STALE_DEPENDENT_CACHE_ROW_MISSING": {
        "ticker_count": 28,
        "blocker_occurrences": 221,
    },
    "PREFERRED_SHARE_NO_CORP_CODE": {
        "ticker_count": 4,
        "blocker_occurrences": 31,
    },
    "CORP_IDENTITY_MISMATCH_REVIEW": {
        "ticker_count": 1,
        "blocker_occurrences": 8,
    },
    "INTENTIONAL_LOSS_PER_NA": {
        "ticker_count": 2,
        "blocker_occurrences": 2,
    },
}

def ticker(value):
    text = "".join(
        ch for ch in str(value or "")
        if ch.isdigit()
    )
    return text.zfill(6) if text else ""

def read_json(path):
    return json.loads(
        Path(path).read_text(encoding="utf-8-sig")
    )

def read_rows(path):
    with Path(path).open(
        encoding="utf-8-sig",
        newline="",
    ) as f:
        return list(csv.DictReader(f))

def parse_kv_log(path):
    out = {}
    for line in Path(path).read_text(
        encoding="utf-8-sig"
    ).splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out

def parse_time(text):
    return datetime.fromisoformat(str(text))

def build_id_time(build_id):
    m = re.match(
        r"^(\d{8}T\d{6}[+-]\d{4})-",
        str(build_id or ""),
    )
    if not m:
        raise RuntimeError(
            "V8157_INVALID_BUILD_ID:"
            + str(build_id)
        )
    return datetime.strptime(
        m.group(1),
        "%Y%m%dT%H%M%S%z",
    )

def classify(fin_row, reasons):
    if fin_row is None:
        return (
            "STALE_DEPENDENT_CACHE_ROW_MISSING",
            "Current production ticker is absent from financial cache.",
        )

    identity = str(
        fin_row.get("corp_identity_status") or ""
    )
    source_status = str(
        fin_row.get("financial_source_status") or ""
    )
    data_status = str(
        fin_row.get("financial_data_status") or ""
    )
    valuation = str(
        fin_row.get("valuation_data_status") or ""
    )

    if identity == "NO_CORP_CODE":
        return (
            "PREFERRED_SHARE_NO_CORP_CODE",
            "Official corpCode stock-code mapping has no separate preferred-share issuer row.",
        )

    if identity == "MISMATCH":
        return (
            "CORP_IDENTITY_MISMATCH_REVIEW",
            "Stock code candidate exists but company-name identity policy rejects the mapping.",
        )

    if (
        identity in {"MATCH", "MATCH_NORMALIZED"}
        and source_status == "OK"
        and data_status == "READY"
        and valuation == "PARTIAL_LOSS_PER_NA"
        and reasons == {"PER:MISSING_PER"}
    ):
        return (
            "INTENTIONAL_LOSS_PER_NA",
            "Financial source is complete; PER is intentionally undefined for non-positive annualized earnings.",
        )

    return (
        "UNEXPECTED_FINANCIAL_LANE",
        "Current financial cache state does not match an approved V8.15.7 lane.",
    )

def main():
    for p in (
        BLOCK_CSV,
        BLOCK_JSON,
        FIN,
        FIN_LOG,
        RAW,
        RAW_LOG,
        STATUS,
        MANIFEST,
    ):
        if not p.is_file():
            raise RuntimeError(
                "V8157_MISSING_INPUT:" + str(p)
            )

    s8156 = read_json(BLOCK_JSON)
    status = read_json(STATUS)
    manifest = read_json(MANIFEST)

    if s8156.get("version") != V8156_VERSION:
        raise RuntimeError(
            "V8157_V8156_VERSION_MISMATCH"
        )
    if s8156.get("status") != (
        "AUDIT_ONLY_EXHAUSTION_AWARE_DYNAMIC_CURRENT_BLOCKERS"
    ):
        raise RuntimeError(
            "V8157_V8156_STATUS_MISMATCH"
        )
    if s8156.get("policy_version") != POLICY_VERSION:
        raise RuntimeError(
            "V8157_POLICY_VERSION_MISMATCH"
        )
    if s8156.get("selection_mode") != "MULTI_BLOCKER_GROUP":
        raise RuntimeError(
            "V8157_SELECTION_MODE_CHANGED"
        )
    if s8156.get("selected_source_group") != TARGET_GROUP:
        raise RuntimeError(
            "V8157_SELECTED_GROUP_CHANGED"
        )
    if set(s8156.get("selected_tickers") or []) != EXPECTED_SELECTED:
        raise RuntimeError(
            "V8157_SELECTED_TICKERS_CHANGED"
        )
    if int(
        s8156.get("selected_ticker_count") or 0
    ) != 35:
        raise RuntimeError(
            "V8157_SELECTED_COUNT_NOT_35"
        )
    if s8156.get("next_step") != (
        "AUDIT_TOP_MULTI_BLOCKER_GROUP_V8157"
    ):
        raise RuntimeError(
            "V8157_PREDECESSOR_NEXT_STEP_MISMATCH"
        )

    if status.get("api_sync_ok") is not True:
        raise RuntimeError(
            "V8157_API_NOT_SYNCED"
        )
    if status.get("safe_to_analyze_as_latest") is not True:
        raise RuntimeError(
            "V8157_API_NOT_SAFE_LATEST"
        )
    if manifest.get("release_stage") != "PRODUCTION":
        raise RuntimeError(
            "V8157_MANIFEST_NOT_PRODUCTION"
        )
    if manifest.get("source_build_id") != status.get("build_id"):
        raise RuntimeError(
            "V8157_BUILD_ID_MISMATCH"
        )

    block_rows = [
        r for r in read_rows(BLOCK_CSV)
        if r.get("source_group") == TARGET_GROUP
    ]

    if len(block_rows) != 262:
        raise RuntimeError(
            "V8157_BLOCKER_OCCURRENCES_NOT_262:"
            + str(len(block_rows))
        )

    reason_counts = Counter(
        r.get("blocker_reason") or ""
        for r in block_rows
    )
    if dict(reason_counts) != EXPECTED_REASON_COUNTS:
        raise RuntimeError(
            "V8157_REASON_COUNTS_CHANGED:"
            + json.dumps(
                dict(reason_counts),
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    reasons_by_code = defaultdict(set)
    meta = {}
    for r in block_rows:
        code = ticker(r.get("ticker"))
        reasons_by_code[code].add(
            r.get("blocker_reason") or ""
        )
        meta[code] = {
            "name": r.get("name") or "",
            "market": r.get("market") or "",
            "missing_component_count": (
                r.get("missing_component_count") or ""
            ),
        }

    if set(reasons_by_code) != EXPECTED_SELECTED:
        raise RuntimeError(
            "V8157_BLOCKER_TARGET_SET_CHANGED"
        )

    fin_rows = read_rows(FIN)
    fin_map = {
        ticker(r.get("ticker")): r
        for r in fin_rows
        if ticker(r.get("ticker"))
    }

    raw_rows = read_rows(RAW)
    raw_codes = {
        ticker(r.get("ticker"))
        for r in raw_rows
        if ticker(r.get("ticker"))
    }

    lane_tickers = defaultdict(list)
    lane_occurrences = Counter()
    out_rows = []

    for code in sorted(EXPECTED_SELECTED):
        reasons = reasons_by_code[code]
        fin = fin_map.get(code)
        lane, note = classify(fin, reasons)

        if lane == "UNEXPECTED_FINANCIAL_LANE":
            raise RuntimeError(
                "V8157_UNEXPECTED_LANE:"
                + code
                + ":"
                + json.dumps(
                    fin or {},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

        occurrence_count = len(reasons)
        lane_tickers[lane].append(code)
        lane_occurrences[lane] += occurrence_count

        out_rows.append({
            "ticker": code,
            "name": meta[code]["name"],
            "market": meta[code]["market"],
            "financial_blocker_occurrences": occurrence_count,
            "financial_blocker_reasons": ";".join(
                sorted(reasons)
            ),
            "recovery_lane": lane,
            "recovery_note": note,
            "financial_cache_row_present": (
                "TRUE" if fin is not None else "FALSE"
            ),
            "raw_score_cache_row_present": (
                "TRUE" if code in raw_codes else "FALSE"
            ),
            "corp_code": "" if fin is None else (
                fin.get("corp_code") or ""
            ),
            "corp_name": "" if fin is None else (
                fin.get("corp_name") or ""
            ),
            "corp_identity_status": "" if fin is None else (
                fin.get("corp_identity_status") or ""
            ),
            "corp_identity_reason": "" if fin is None else (
                fin.get("corp_identity_reason") or ""
            ),
            "financial_source_status": "" if fin is None else (
                fin.get("financial_source_status") or ""
            ),
            "financial_data_status": "" if fin is None else (
                fin.get("financial_data_status") or ""
            ),
            "valuation_data_status": "" if fin is None else (
                fin.get("valuation_data_status") or ""
            ),
            "financial_basis": "" if fin is None else (
                fin.get("financial_basis") or ""
            ),
            "net_income": "" if fin is None else (
                fin.get("net_income") or ""
            ),
            "per_annualized": "" if fin is None else (
                fin.get("per_annualized") or ""
            ),
        })

    lane_counts = {
        lane: {
            "ticker_count": len(codes),
            "blocker_occurrences": int(
                lane_occurrences[lane]
            ),
            "tickers": sorted(codes),
        }
        for lane, codes in lane_tickers.items()
    }

    for lane, expected in EXPECTED_LANES.items():
        actual = lane_counts.get(lane) or {}
        if int(
            actual.get("ticker_count") or 0
        ) != expected["ticker_count"]:
            raise RuntimeError(
                "V8157_LANE_TICKER_COUNT_CHANGED:"
                + lane
            )
        if int(
            actual.get("blocker_occurrences") or 0
        ) != expected["blocker_occurrences"]:
            raise RuntimeError(
                "V8157_LANE_OCCURRENCE_CHANGED:"
                + lane
            )

    if set(lane_counts) != set(EXPECTED_LANES):
        raise RuntimeError(
            "V8157_LANE_SET_CHANGED:"
            + ",".join(sorted(lane_counts))
        )

    stale_codes = set(
        lane_tickers[
            "STALE_DEPENDENT_CACHE_ROW_MISSING"
        ]
    )

    # The 28 stale financial-cache misses are also absent from the
    # downstream score-source cache. This is evidence of refresh
    # ordering, not 28 independent issuer failures.
    raw_overlap = stale_codes & raw_codes
    if raw_overlap:
        raise RuntimeError(
            "V8157_STALE_FINANCIAL_ROWS_ALREADY_IN_RAW_CACHE:"
            + ",".join(sorted(raw_overlap))
        )

    fin_log = parse_kv_log(FIN_LOG)
    raw_log = parse_kv_log(RAW_LOG)

    if fin_log.get("STATUS") != "OK":
        raise RuntimeError(
            "V8157_FINANCIAL_RUN_NOT_OK"
        )
    if fin_log.get("CACHE_OUTPUT_ROWS") != "271":
        raise RuntimeError(
            "V8157_FINANCIAL_CACHE_ROW_COUNT_CHANGED"
        )
    if raw_log.get("OUTPUT_ROWS") != "254":
        raise RuntimeError(
            "V8157_RAW_CACHE_ROW_COUNT_CHANGED"
        )

    fin_run_time = parse_time(
        fin_log["RUN_AT_KST"]
    )
    raw_run_time = parse_time(
        raw_log["RUN_AT_KST"]
    )
    api_build_time = build_id_time(
        status["build_id"]
    )

    if not (
        fin_run_time
        < raw_run_time
        < api_build_time
    ):
        raise RuntimeError(
            "V8157_REFRESH_ORDER_NOT_STALE_CHAIN:"
            f"{fin_run_time}|{raw_run_time}|{api_build_time}"
        )

    # The current production universe was rebuilt after both
    # dependent investment caches. This explains the 28 cache-row
    # misses and gives the next safe recovery lane.
    refresh_gap_seconds = int(
        (
            api_build_time
            - fin_run_time
        ).total_seconds()
    )

    OUT_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    fields = list(out_rows[0].keys())
    with OUT_CSV.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        w = csv.DictWriter(
            f,
            fieldnames=fields,
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(out_rows)

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(
            KST
        ).isoformat(timespec="seconds"),
        "status": (
            "AUDIT_ONLY_FINANCIAL_MULTIBLOCKER_ROOT_CAUSE"
        ),
        "policy_version": POLICY_VERSION,
        "v8156_version": V8156_VERSION,
        "v8156_result_commit": (
            V8156_RESULT_COMMIT
        ),
        "source_group": TARGET_GROUP,
        "target_ticker_count": 35,
        "blocker_occurrence_count": 262,
        "blocker_reason_counts": dict(
            reason_counts
        ),
        "financial_cache_row_count": len(
            fin_rows
        ),
        "raw_score_cache_row_count": len(
            raw_rows
        ),
        "lane_counts": lane_counts,
        "stale_dependency_chain": {
            "financial_cache_run_at_kst": (
                fin_run_time.isoformat()
            ),
            "raw_score_cache_run_at_kst": (
                raw_run_time.isoformat()
            ),
            "current_api_build_at_kst": (
                api_build_time.isoformat()
            ),
            "current_api_build_id": (
                status["build_id"]
            ),
            "financial_before_raw_before_api": True,
            "financial_to_api_gap_seconds": (
                refresh_gap_seconds
            ),
            "stale_financial_row_missing_count": 28,
            "stale_financial_row_missing_tickers": sorted(
                stale_codes
            ),
            "same_28_absent_from_raw_score_cache": True,
        },
        "highest_actionable_recovery_lane": (
            "STALE_DEPENDENT_CACHE_ROW_MISSING"
        ),
        "highest_actionable_recovery_ticker_count": 28,
        "highest_actionable_recovery_blocker_occurrences": 221,
        "non_source_recovery_lanes": {
            "preferred_share_no_corp_code": sorted(
                lane_tickers[
                    "PREFERRED_SHARE_NO_CORP_CODE"
                ]
            ),
            "corp_identity_mismatch_review": sorted(
                lane_tickers[
                    "CORP_IDENTITY_MISMATCH_REVIEW"
                ]
            ),
            "intentional_loss_per_na": sorted(
                lane_tickers[
                    "INTENTIONAL_LOSS_PER_NA"
                ]
            ),
        },
        "automatic_promotion": {
            "allowed": False,
            "promoted_ticker_count": 0,
        },
        "hard_guards": {
            "production_financial_cache_modified": False,
            "production_raw_score_cache_modified": False,
            "production_api_modified": False,
            "production_investment_score_written": False,
            "scoring_policy_modified": False,
            "corp_identity_policy_modified": False,
            "preferred_share_alias_inferred": False,
            "loss_per_fabricated": False,
            "source_value_imputed": False,
        },
        "next_step": (
            "REFRESH_CURRENT_PRODUCTION_FINANCIAL_CACHE_AND_SHADOW_V8158"
        ),
    }

    OUT_JSON.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY_FINANCIAL_MULTIBLOCKER_ROOT_CAUSE",
            "TARGET_TICKERS=35",
            "BLOCKER_OCCURRENCES=262",
            "LANE_STALE_DEPENDENT_CACHE_ROW_MISSING_TICKERS=28",
            "LANE_STALE_DEPENDENT_CACHE_ROW_MISSING_BLOCKERS=221",
            "LANE_PREFERRED_SHARE_NO_CORP_CODE_TICKERS=4",
            "LANE_PREFERRED_SHARE_NO_CORP_CODE_BLOCKERS=31",
            "LANE_CORP_IDENTITY_MISMATCH_REVIEW_TICKERS=1",
            "LANE_CORP_IDENTITY_MISMATCH_REVIEW_BLOCKERS=8",
            "LANE_INTENTIONAL_LOSS_PER_NA_TICKERS=2",
            "LANE_INTENTIONAL_LOSS_PER_NA_BLOCKERS=2",
            f"FINANCIAL_CACHE_RUN_AT_KST={fin_run_time.isoformat()}",
            f"RAW_SCORE_CACHE_RUN_AT_KST={raw_run_time.isoformat()}",
            f"CURRENT_API_BUILD_AT_KST={api_build_time.isoformat()}",
            "FINANCIAL_BEFORE_RAW_BEFORE_API=true",
            "STALE_FINANCIAL_ROWS_ALSO_ABSENT_FROM_RAW_CACHE=28",
            "AUTOMATIC_PROMOTION=false",
            "PRODUCTION_DATA_MODIFIED=false",
            "SCORING_POLICY_MODIFIED=false",
            "STATUS_OK=true",
            "NEXT_STEP=REFRESH_CURRENT_PRODUCTION_FINANCIAL_CACHE_AND_SHADOW_V8158",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUT_DOC.write_text(
        "\n".join([
            "# V8.15.7 financial valuation multi-blocker root-cause audit",
            "",
            "- Selected group: `FINANCIAL_VALUATION_CACHE`.",
            "- Targets: 35 tickers / 262 blocker occurrences.",
            "- 28 tickers / 221 blockers: current production tickers missing from both financial cache and raw score-source cache.",
            "- 4 preferred shares / 31 blockers: no separate OpenDART stock-code corp mapping; no alias is inferred.",
            "- 1 ticker / 8 blockers: LS ELECTRIC name-identity mismatch requires a separate identity-policy review.",
            "- 2 tickers / 2 blockers: complete financial data but PER intentionally undefined because annualized net income is non-positive.",
            "",
            f"- Financial cache run: {fin_run_time.isoformat()}",
            f"- Raw score cache run: {raw_run_time.isoformat()}",
            f"- Current production API build: {api_build_time.isoformat()}",
            "",
            "The dominant 28-ticker gap is a dependency-refresh ordering problem, not 28 independently proven issuer failures.",
            "No production cache, API, score, identity policy, or scoring policy is modified in this audit.",
            "",
            "Next: `REFRESH_CURRENT_PRODUCTION_FINANCIAL_CACHE_AND_SHADOW_V8158`",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        "V8157_FINANCIAL_MULTIBLOCKER_ROOT_CAUSE_AUDIT=PASS"
    )

if __name__ == "__main__":
    main()
