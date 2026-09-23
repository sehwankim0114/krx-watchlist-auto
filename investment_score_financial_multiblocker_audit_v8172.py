#!/usr/bin/env python3
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-23-v8.17.2-financial-valuation-multiblocker-root-cause"
POLICY = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8171A_VERSION = "2026-09-23-v8.17.1A-dynamic-current-blocker-reaudit"
V8171A_COMMIT = "2c89816f540b518a0fdca94a7783579796beb61b"
GROUP = "FINANCIAL_VALUATION_CACHE"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8171a.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8171a_summary_latest.json"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"
FIN_LOG = ROOT / "latest/financial_valuation_run_log_latest.txt"
RAW = ROOT / "latest/investment_score_source_cache_latest.csv"
RAW_LOG = ROOT / "latest/investment_score_source_run_log_latest.txt"
MANIFEST = ROOT / "api/two_table_v1/manifest.json"

OUT_CSV = ROOT / "latest/investment_score_financial_multiblocker_v8172.csv"
OUT_JSON = ROOT / "latest/investment_score_financial_multiblocker_v8172_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_financial_multiblocker_v8172_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_financial_multiblocker_v8172.md"

EXPECTED_REASON_COUNTS = {
    "PER:MISSING_PER": 73,
    "PBR:MISSING_PBR_OR_ROE": 71,
    "ROE:MISSING_ROE": 71,
    "순이익 흐름:MISSING_EARNINGS_TREND": 71,
    "영업이익 성장과 흑자 여부:MISSING_OP_PROFIT": 71,
    "영업이익률:MISSING_MARGIN": 71,
    "흑자 지속성과 이익 안정성:MISSING_EARNINGS_TREND": 71,
    "부채비율:MISSING_DEBT_RATIO": 62,
}

EXPECTED_LANES = {
    "CURRENT_UNIVERSE_FINANCIAL_CACHE_ROW_MISSING": (68, 536),
    "OFFICIAL_NO_CORP_CODE": (2, 15),
    "CORP_IDENTITY_MISMATCH_REVIEW": (1, 8),
    "INTENTIONAL_LOSS_PER_NA": (2, 2),
}

def ticker(v):
    s = "".join(c for c in str(v or "") if c.isdigit())
    return s.zfill(6) if s else ""

def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def read_rows(p):
    with Path(p).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def kv(p):
    out = {}
    for line in Path(p).read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def parse_time(v):
    return datetime.fromisoformat(str(v))

def build_time(build_id):
    m = re.match(r"^(\d{8}T\d{6}[+-]\d{4})-", str(build_id or ""))
    if not m:
        raise RuntimeError("V8172_BAD_BUILD_ID:" + str(build_id))
    return datetime.strptime(m.group(1), "%Y%m%dT%H%M%S%z")

def classify(fin, reasons):
    if fin is None:
        return (
            "CURRENT_UNIVERSE_FINANCIAL_CACHE_ROW_MISSING",
            "Current scorer ticker is absent from the financial cache after the production universe expanded.",
        )

    identity = str(fin.get("corp_identity_status") or "")
    source = str(fin.get("financial_source_status") or "")
    data = str(fin.get("financial_data_status") or "")
    valuation = str(fin.get("valuation_data_status") or "")

    if identity == "NO_CORP_CODE" and source == "NO_CORP_CODE":
        return (
            "OFFICIAL_NO_CORP_CODE",
            "OpenDART official stock-code mapping has no accepted corp-code row; no issuer alias is inferred.",
        )

    if identity == "MISMATCH":
        return (
            "CORP_IDENTITY_MISMATCH_REVIEW",
            "OpenDART candidate exists but the current company-name identity rule rejects it.",
        )

    if (
        identity in {"MATCH", "MATCH_NORMALIZED"}
        and source == "OK"
        and data == "READY"
        and valuation == "PARTIAL_LOSS_PER_NA"
        and reasons == {"PER:MISSING_PER"}
    ):
        return (
            "INTENTIONAL_LOSS_PER_NA",
            "Financial data is complete; PER is intentionally undefined because annualized net income is non-positive.",
        )

    return (
        "UNEXPECTED_FINANCIAL_LANE",
        "Financial cache state does not match an approved V8.17.2 lane.",
    )

def main():
    s = read_json(BLOCK_JSON)
    mf = read_json(MANIFEST)
    fl = kv(FIN_LOG)
    rl = kv(RAW_LOG)

    assert s["version"] == V8171A_VERSION
    assert s["status"] == "AUDIT_ONLY_DYNAMIC_CURRENT_PRODUCTION_BLOCKERS"
    assert s["policy_version"] == POLICY
    assert s["selection_mode"] == "MULTI_BLOCKER_GROUP"
    assert s["selected_source_group"] == GROUP
    assert s["selected_ticker_count"] == 73
    assert len(s["selected_tickers"]) == 73
    assert s["source_group_counts"][GROUP] == 561
    assert s["next_step"] == "AUDIT_TOP_MULTI_BLOCKER_GROUP_V8172"

    assert mf["release_stage"] == "PRODUCTION"
    assert mf["safe_to_analyze_as_latest"] is True
    assert mf["basis_date"] == "2026-09-22"

    selected = set(s["selected_tickers"])
    block_rows = [
        r for r in read_rows(BLOCK_CSV)
        if r.get("source_group") == GROUP
        and ticker(r.get("ticker")) in selected
    ]
    if len(block_rows) != 561:
        raise RuntimeError("V8172_BLOCKER_COUNT_NOT_561:" + str(len(block_rows)))

    reasons = Counter(r.get("blocker_reason") or "" for r in block_rows)
    if dict(reasons) != EXPECTED_REASON_COUNTS:
        raise RuntimeError(
            "V8172_REASON_COUNTS_CHANGED:"
            + json.dumps(dict(reasons), ensure_ascii=False, sort_keys=True)
        )

    reasons_by = defaultdict(set)
    meta = {}
    for r in block_rows:
        code = ticker(r.get("ticker"))
        reasons_by[code].add(r.get("blocker_reason") or "")
        meta[code] = {
            "name": r.get("name") or "",
            "market": r.get("market") or "",
        }

    if set(reasons_by) != selected:
        raise RuntimeError("V8172_SELECTED_SET_MISMATCH")

    fin_rows = read_rows(FIN)
    fin_map = {
        ticker(r.get("ticker")): r
        for r in fin_rows if ticker(r.get("ticker"))
    }

    raw_rows = read_rows(RAW)
    raw_codes = {
        ticker(r.get("ticker"))
        for r in raw_rows if ticker(r.get("ticker"))
    }

    lane_tickers = defaultdict(list)
    lane_occ = Counter()
    out_rows = []

    for code in sorted(selected):
        fin = fin_map.get(code)
        lane, note = classify(fin, reasons_by[code])
        if lane == "UNEXPECTED_FINANCIAL_LANE":
            raise RuntimeError(
                "V8172_UNEXPECTED_LANE:"
                + code + ":"
                + json.dumps(fin or {}, ensure_ascii=False, sort_keys=True)
            )

        lane_tickers[lane].append(code)
        lane_occ[lane] += len(reasons_by[code])

        out_rows.append({
            "ticker": code,
            "name": meta[code]["name"],
            "market": meta[code]["market"],
            "financial_blocker_occurrences": len(reasons_by[code]),
            "financial_blocker_reasons": ";".join(sorted(reasons_by[code])),
            "recovery_lane": lane,
            "recovery_note": note,
            "financial_cache_row_present": "TRUE" if fin else "FALSE",
            "source_cache_row_present": "TRUE" if code in raw_codes else "FALSE",
            "corp_code": "" if fin is None else (fin.get("corp_code") or ""),
            "corp_name": "" if fin is None else (fin.get("corp_name") or ""),
            "corp_identity_status": "" if fin is None else (fin.get("corp_identity_status") or ""),
            "corp_identity_reason": "" if fin is None else (fin.get("corp_identity_reason") or ""),
            "financial_source_status": "" if fin is None else (fin.get("financial_source_status") or ""),
            "financial_data_status": "" if fin is None else (fin.get("financial_data_status") or ""),
            "valuation_data_status": "" if fin is None else (fin.get("valuation_data_status") or ""),
            "financial_basis": "" if fin is None else (fin.get("financial_basis") or ""),
            "net_income": "" if fin is None else (fin.get("net_income") or ""),
            "per_annualized": "" if fin is None else (fin.get("per_annualized") or ""),
        })

    lanes = {
        lane: {
            "ticker_count": len(codes),
            "blocker_occurrences": int(lane_occ[lane]),
            "tickers": sorted(codes),
        }
        for lane, codes in lane_tickers.items()
    }

    if set(lanes) != set(EXPECTED_LANES):
        raise RuntimeError("V8172_LANE_SET_CHANGED:" + ",".join(sorted(lanes)))

    for lane, (tc, bc) in EXPECTED_LANES.items():
        if lanes[lane]["ticker_count"] != tc:
            raise RuntimeError("V8172_LANE_TICKER_COUNT:" + lane)
        if lanes[lane]["blocker_occurrences"] != bc:
            raise RuntimeError("V8172_LANE_BLOCKER_COUNT:" + lane)

    missing = set(lanes["CURRENT_UNIVERSE_FINANCIAL_CACHE_ROW_MISSING"]["tickers"])
    if missing & raw_codes:
        raise RuntimeError(
            "V8172_MISSING_FIN_ROWS_PRESENT_IN_SOURCE_CACHE:"
            + ",".join(sorted(missing & raw_codes))
        )

    if len(fin_rows) != 240:
        raise RuntimeError("V8172_FIN_CACHE_ROWS_NOT_240:" + str(len(fin_rows)))
    if len(raw_rows) != 227:
        raise RuntimeError("V8172_SOURCE_CACHE_ROWS_NOT_227:" + str(len(raw_rows)))

    if fl.get("STATUS") != "OK":
        raise RuntimeError("V8172_FIN_RUN_NOT_OK")
    if fl.get("CACHE_OUTPUT_ROWS") != "240":
        raise RuntimeError("V8172_FIN_LOG_ROWS_NOT_240")
    if fl.get("PRODUCTION_TWO_TABLE_TARGET_TICKERS") != "120":
        raise RuntimeError("V8172_FIN_TWO_TABLE_TARGET_NOT_120")

    if rl.get("SOURCE_RETENTION_GUARD") != "PASS":
        raise RuntimeError("V8172_SOURCE_RETENTION_NOT_PASS")
    if rl.get("OUTPUT_ROWS") != "227":
        raise RuntimeError("V8172_SOURCE_LOG_ROWS_NOT_227")

    fin_time = parse_time(fl["RUN_AT_KST"])
    raw_time = parse_time(rl["RUN_AT_KST"])
    api_time = build_time(mf["source_build_id"])

    if not (fin_time < raw_time < api_time):
        raise RuntimeError(
            "V8172_REFRESH_ORDER_CHANGED:"
            f"{fin_time.isoformat()}|{raw_time.isoformat()}|{api_time.isoformat()}"
        )

    current_scorer_universe = int(s["scorer_universe_count"])
    if current_scorer_universe != 157:
        raise RuntimeError("V8172_SCORER_UNIVERSE_NOT_157")
    if int(fl["PRODUCTION_TWO_TABLE_TARGET_TICKERS"]) >= current_scorer_universe:
        raise RuntimeError("V8172_NO_UNIVERSE_EXPANSION_GAP")

    fields = list(out_rows[0].keys())
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY_FINANCIAL_MULTIBLOCKER_ROOT_CAUSE",
        "policy_version": POLICY,
        "v8171a_version": V8171A_VERSION,
        "v8171a_result_commit": V8171A_COMMIT,
        "source_group": GROUP,
        "target_ticker_count": 73,
        "blocker_occurrence_count": 561,
        "blocker_reason_counts": dict(reasons),
        "financial_cache_row_count": len(fin_rows),
        "source_cache_row_count": len(raw_rows),
        "lane_counts": lanes,
        "refresh_order_evidence": {
            "financial_run_at_kst": fin_time.isoformat(),
            "financial_two_table_target_tickers": int(fl["PRODUCTION_TWO_TABLE_TARGET_TICKERS"]),
            "source_run_at_kst": raw_time.isoformat(),
            "current_api_build_at_kst": api_time.isoformat(),
            "current_api_build_id": mf["source_build_id"],
            "current_scorer_target_universe_count": current_scorer_universe,
            "financial_before_source_before_current_api": True,
            "universe_expanded_after_financial_refresh": True,
            "missing_financial_rows": 68,
            "same_68_absent_from_source_cache": True,
        },
        "highest_actionable_recovery_lane": "CURRENT_UNIVERSE_FINANCIAL_CACHE_ROW_MISSING",
        "highest_actionable_recovery_ticker_count": 68,
        "highest_actionable_recovery_blocker_occurrences": 536,
        "non_refresh_lanes": {
            "official_no_corp_code": lanes["OFFICIAL_NO_CORP_CODE"]["tickers"],
            "corp_identity_mismatch_review": lanes["CORP_IDENTITY_MISMATCH_REVIEW"]["tickers"],
            "intentional_loss_per_na": lanes["INTENTIONAL_LOSS_PER_NA"]["tickers"],
        },
        "automatic_promotion": {
            "allowed": False,
            "promoted_ticker_count": 0,
        },
        "hard_guards": {
            "production_financial_cache_modified": False,
            "production_source_cache_modified": False,
            "production_api_modified": False,
            "production_score_written": False,
            "scoring_policy_modified": False,
            "corp_identity_policy_modified": False,
            "issuer_alias_inferred": False,
            "loss_per_fabricated": False,
            "source_value_imputed": False,
        },
        "next_step": "SHADOW_REFRESH_CURRENT_FINANCIAL_CACHE_V8173",
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text("\n".join([
        f"VERSION={VERSION}",
        "STATUS=AUDIT_ONLY_FINANCIAL_MULTIBLOCKER_ROOT_CAUSE",
        "TARGET_TICKERS=73",
        "BLOCKER_OCCURRENCES=561",
        "LANE_CURRENT_UNIVERSE_FINANCIAL_CACHE_ROW_MISSING_TICKERS=68",
        "LANE_CURRENT_UNIVERSE_FINANCIAL_CACHE_ROW_MISSING_BLOCKERS=536",
        "LANE_OFFICIAL_NO_CORP_CODE_TICKERS=2",
        "LANE_OFFICIAL_NO_CORP_CODE_BLOCKERS=15",
        "LANE_CORP_IDENTITY_MISMATCH_REVIEW_TICKERS=1",
        "LANE_CORP_IDENTITY_MISMATCH_REVIEW_BLOCKERS=8",
        "LANE_INTENTIONAL_LOSS_PER_NA_TICKERS=2",
        "LANE_INTENTIONAL_LOSS_PER_NA_BLOCKERS=2",
        "FINANCIAL_CACHE_ROWS=240",
        "SOURCE_CACHE_ROWS=227",
        "FINANCIAL_TWO_TABLE_TARGET_TICKERS=120",
        "CURRENT_SCORER_TARGET_UNIVERSE=157",
        "FINANCIAL_BEFORE_SOURCE_BEFORE_CURRENT_API=true",
        "UNIVERSE_EXPANDED_AFTER_FINANCIAL_REFRESH=true",
        "MISSING_FINANCIAL_ROWS_ALSO_ABSENT_FROM_SOURCE_CACHE=68",
        "AUTOMATIC_PROMOTION=false",
        "PRODUCTION_DATA_MODIFIED=false",
        "STATUS_OK=true",
        "NEXT_STEP=SHADOW_REFRESH_CURRENT_FINANCIAL_CACHE_V8173",
    ]) + "\n", encoding="utf-8")

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text("\n".join([
        "# V8.17.2 financial valuation multi-blocker root-cause audit",
        "",
        "- Selected group: FINANCIAL_VALUATION_CACHE.",
        "- Targets: 73 tickers / 561 blocker occurrences.",
        "- 68 tickers / 536 blockers are absent from both the current financial cache and downstream source cache.",
        "- The financial refresh used a 120-ticker two-table target set; the current scorer universe is 157.",
        "- Refresh order is financial -> source -> current API, so the dominant gap is a dependency refresh-order issue after universe expansion.",
        "- 2 tickers / 15 blockers are official NO_CORP_CODE cases.",
        "- 1 ticker / 8 blockers is the LS ELECTRIC identity mismatch review lane.",
        "- 2 tickers / 2 blockers are intentional loss-PER N/A cases.",
        "- No production cache, API, score, policy, identity rule, or issuer alias is modified.",
        "",
        "Next: SHADOW_REFRESH_CURRENT_FINANCIAL_CACHE_V8173",
        "",
    ]), encoding="utf-8")

    print("V8172_FINANCIAL_ROOT_CAUSE_AUDIT=PASS")

if __name__ == "__main__":
    main()
