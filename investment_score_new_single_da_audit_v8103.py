#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_xbrl_retry_v892 as retry
import investment_score_source_enricher_v854 as src

VERSION = "2026-09-15-v8.10.3-audit-new-single-da-blockers"
V8102_VERSION = "2026-09-15-v8.10.2-combined-validated-source-reconciliation"
V897_VERSION = "2026-09-15-v8.9.7-refresh-single-blocker-da-xbrl"
V885_VERSION = "2026-09-14-v8.8.5-expanded-xbrl-da-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_remaining_blockers_v8102.csv"
BLOCK_JSON = ROOT / "latest/investment_score_remaining_blockers_v8102_summary_latest.json"
V897_JSON = ROOT / "latest/investment_score_single_da_xbrl_refresh_v897_summary_latest.json"
V885_CSV = ROOT / "latest/investment_score_xbrl_da_expand_v885.csv"
V885_JSON = ROOT / "latest/investment_score_xbrl_da_expand_v885_summary_latest.json"
FIN_CACHE = ROOT / "latest/financial_valuation_cache_latest.csv"

OUT_CSV = ROOT / "latest/investment_score_new_single_da_audit_v8103.csv"
OUT_JSON = ROOT / "latest/investment_score_new_single_da_audit_v8103_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_new_single_da_audit_v8103_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_new_single_da_audit_v8103.md"

APPROVED_IDS = {
    "ifrs-full_AdjustmentsForDepreciationExpense",
    "ifrs-full_AdjustmentsForAmortisationExpense",
}
APPROVED_LOCAL = {
    "AdjustmentsForDepreciationExpense",
    "AdjustmentsForAmortisationExpense",
}
EXPECTED_NEW_TARGETS = {"011200", "012690"}

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def ticker(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def parse_list(value):
    try:
        data = json.loads(str(value or ""))
    except Exception:
        return []
    return data if isinstance(data, list) else []

def number(v):
    try:
        if v in (None, "", "null", "None"):
            return None
        return float(v)
    except Exception:
        return None

def full_account_exact_stats(candidates):
    grouped = defaultdict(list)
    for item in candidates:
        aid = str(item.get("account_id") or "").strip()
        if aid in APPROVED_IDS:
            grouped[aid].append(item)

    out = {}
    for aid in sorted(APPROVED_IDS):
        nums = [
            number(x.get("amount"))
            for x in grouped.get(aid, [])
            if number(x.get("amount")) is not None
        ]
        out[aid] = {
            "occurrence_count": len(grouped.get(aid, [])),
            "unique_numeric_values": sorted(set(nums)),
            "account_names": sorted({
                str(x.get("account_nm") or "").strip()
                for x in grouped.get(aid, [])
                if str(x.get("account_nm") or "").strip()
            }),
        }
    return out

def full_account_class(stats):
    present = {
        aid for aid, info in stats.items()
        if info["occurrence_count"] > 0
    }
    unique = {
        aid for aid, info in stats.items()
        if len(info["unique_numeric_values"]) == 1
    }
    conflicts = {
        aid for aid, info in stats.items()
        if len(info["unique_numeric_values"]) > 1
    }
    if conflicts:
        return "APPROVED_EXACT_VALUE_CONFLICT"
    if present == APPROVED_IDS and unique == APPROVED_IDS:
        return "BOTH_APPROVED_EXACT_UNIQUE_NUMERIC"
    if present and unique == present:
        return "PARTIAL_APPROVED_EXACT_UNIQUE_NUMERIC"
    if present:
        return "APPROVED_EXACT_PRESENT_NONUNIQUE_OR_NONNUMERIC"
    return "NO_APPROVED_EXACT"

def xbrl_class(attempts):
    zip_rows = [x for x in attempts if x.get("zip_status") == "ZIP_OK"]
    both = []
    partial = []
    no_exact = []
    for item in zip_rows:
        names = set(item.get("approved_exact_local_names") or [])
        if APPROVED_LOCAL.issubset(names):
            both.append(item)
        elif names:
            partial.append(item)
        else:
            no_exact.append(item)

    if both:
        return "BOTH_APPROVED_EXACT_RECOVERED", both
    if partial:
        return "PARTIAL_APPROVED_EXACT_ONLY", partial
    if no_exact:
        return "ZIP_OK_NO_APPROVED_EXACT", no_exact
    if attempts:
        return "NO_VALID_XBRL_ZIP", []
    return "NO_REPORT_CANDIDATE", []

def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DART_API_KEY_MISSING")

    for p in (BLOCK_CSV, BLOCK_JSON, V897_JSON, V885_CSV, V885_JSON, FIN_CACHE):
        if not p.is_file():
            raise RuntimeError("MISSING_REQUIRED_SOURCE:" + str(p))

    bsum = read_json(BLOCK_JSON)
    if bsum.get("version") != V8102_VERSION:
        raise RuntimeError("V8102_VERSION_MISMATCH")
    if bsum.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8102_STATUS_MISMATCH")
    if bsum.get("highest_impact_source_group") != "EXACT_DA_SOURCE":
        raise RuntimeError("V8102_TOP_SOURCE_NOT_EXACT_DA")
    if int(bsum.get("highest_impact_single_blocker_ticker_count") or 0) != 10:
        raise RuntimeError("V8102_EXACT_DA_SINGLE_COUNT_NOT_10")

    block_rows = read_csv(BLOCK_CSV)
    current_da_single = {
        ticker(r.get("ticker"))
        for r in block_rows
        if r.get("source_group") == "EXACT_DA_SOURCE"
        and str(r.get("single_blocker_ticker") or "").upper() == "TRUE"
    }
    if len(current_da_single) != 10:
        raise RuntimeError("V8102_CURRENT_DA_SINGLE_SET_NOT_10")

    s897 = read_json(V897_JSON)
    if s897.get("version") != V897_VERSION:
        raise RuntimeError("V897_VERSION_MISMATCH")
    prior_targets = set(s897.get("target_tickers") or [])
    if len(prior_targets) != 8:
        raise RuntimeError("V897_PRIOR_TARGET_COUNT_NOT_8")

    new_targets = current_da_single - prior_targets
    if new_targets != EXPECTED_NEW_TARGETS:
        raise RuntimeError(
            "NEW_DA_SINGLE_TARGET_SET_CHANGED:" + repr(sorted(new_targets))
        )

    s885 = read_json(V885_JSON)
    if s885.get("version") != V885_VERSION:
        raise RuntimeError("V885_VERSION_MISMATCH")
    rows885 = read_csv(V885_CSV)
    m885 = {ticker(r.get("ticker")): r for r in rows885 if ticker(r.get("ticker"))}

    financial_df = src.read_csv(FIN_CACHE)
    targets854 = src.load_targets(financial_df)
    dominant_year, dominant_code = src.dominant_period(targets854)
    annual_year = dominant_year - 1
    t854 = {t["ticker"]: t for t in targets854}
    client = src.OpenDartClient(api_key, timeout=30)

    outputs = []
    xbrl_both = []
    full_both = []

    for code in sorted(new_targets):
        prior = m885.get(code)
        target = t854.get(code)
        if not prior:
            raise RuntimeError("V885_ROW_MISSING:" + code)
        if not target:
            raise RuntimeError("V854_TARGET_MISSING:" + code)

        corp_code = str(prior.get("corp_code") or "").strip()
        prior_rcept = str(prior.get("rcept_no") or "").strip()
        if not corp_code or not prior_rcept:
            raise RuntimeError("PRIOR_CORP_OR_RCEPT_MISSING:" + code)

        reports = retry.list_business_reports(api_key, corp_code)

        candidates = []
        seen = set()
        def add_candidate(rcept_no, source, rcept_dt="", report_nm=""):
            if not rcept_no or rcept_no in seen:
                return
            seen.add(rcept_no)
            candidates.append({
                "rcept_no": rcept_no,
                "candidate_source": source,
                "rcept_dt": rcept_dt,
                "report_nm": report_nm,
            })

        add_candidate(
            prior_rcept,
            "V885_PRIOR",
            str(prior.get("rcept_dt") or ""),
            str(prior.get("report_nm") or ""),
        )
        for r in reports.get("reports") or []:
            add_candidate(
                str(r.get("rcept_no") or ""),
                "DART_LIST_REFRESH",
                str(r.get("rcept_dt") or ""),
                str(r.get("report_nm") or ""),
            )

        attempts = []
        for cand in candidates:
            result = retry.try_xbrl(api_key, cand["rcept_no"])
            attempts.append({**cand, **result})
            time.sleep(0.3)

        xclass, best_rows = xbrl_class(attempts)
        if xclass == "BOTH_APPROVED_EXACT_RECOVERED":
            xbrl_both.append(code)

        fresh = src.fetch_deep_one(client, target, annual_year)
        fresh_candidates = parse_list(fresh.get("da_json"))
        fstats = full_account_exact_stats(fresh_candidates)
        fclass = full_account_class(fstats)
        if fclass == "BOTH_APPROVED_EXACT_UNIQUE_NUMERIC":
            full_both.append(code)

        best = {}
        if best_rows:
            best = sorted(
                best_rows,
                key=lambda x: (
                    str(x.get("rcept_dt") or ""),
                    str(x.get("rcept_no") or ""),
                ),
                reverse=True,
            )[0]

        outputs.append({
            "ticker": code,
            "name": prior.get("name") or target.get("name") or "",
            "market": prior.get("market") or target.get("market") or "",
            "corp_code": corp_code,
            "prior_rcept_no": prior_rcept,
            "prior_xbrl_status": prior.get("xbrl_status") or "",
            "prior_audit_result": prior.get("audit_result") or "",
            "prior_approved_exact_count": prior.get("approved_exact_fact_count") or "",
            "candidate_rcept_count": len(candidates),
            "xbrl_zip_success_count": sum(
                1 for x in attempts if x.get("zip_status") == "ZIP_OK"
            ),
            "xbrl_refresh_classification": xclass,
            "xbrl_best_rcept_no": best.get("rcept_no") or "",
            "xbrl_best_report_nm": best.get("report_nm") or "",
            "xbrl_best_approved_exact_local_names": "|".join(
                sorted(set(best.get("approved_exact_local_names") or []))
            ),
            "full_account_status": fresh.get("status") or "",
            "full_account_fs_div": fresh.get("fs_div") or "",
            "full_account_message": fresh.get("message") or "",
            "full_account_classification": fclass,
            "full_account_exact_stats_json": json.dumps(
                fstats, ensure_ascii=False, separators=(",", ":")
            ),
            "xbrl_attempts_json": json.dumps(
                attempts, ensure_ascii=False, separators=(",", ":")
            ),
        })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_fields = list(outputs[0].keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=write_fields)
        w.writeheader()
        w.writerows(outputs)

    xbrl_both = sorted(xbrl_both)
    full_both = sorted(full_both)
    any_both = sorted(set(xbrl_both) | set(full_both))

    if xbrl_both:
        next_step = "AUDIT_V8103_RECOVERED_XBRL_CONTEXTS_BEFORE_DA_SOURCE_PROMOTION"
    elif full_both:
        next_step = "AUDIT_V8103_FULL_ACCOUNT_EXACT_VALUES_BEFORE_DA_SOURCE_PROMOTION"
    else:
        next_step = "KEEP_NEW_DA_SINGLE_BLOCKERS_LIMITED_AND_MOVE_TO_NEXT_RECOVERABLE_SOURCE"

    summary = {
        "version": VERSION,
        "policy_version": POLICY_VERSION,
        "v8102_version": V8102_VERSION,
        "v897_version": V897_VERSION,
        "v885_version": V885_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY",
        "current_exact_da_single_blocker_count": len(current_da_single),
        "prior_v897_target_count": len(prior_targets),
        "new_target_count": len(new_targets),
        "new_target_tickers": sorted(new_targets),
        "dominant_financial_period": f"{dominant_year}_{dominant_code}",
        "annual_source_year": annual_year,
        "xbrl_both_exact_recovered_count": len(xbrl_both),
        "xbrl_both_exact_recovered_tickers": xbrl_both,
        "full_account_both_exact_unique_count": len(full_both),
        "full_account_both_exact_unique_tickers": full_both,
        "any_official_both_exact_candidate_count": len(any_both),
        "any_official_both_exact_candidate_tickers": any_both,
        "api_telemetry": {
            "full_account_attempted": client.attempted,
            "full_account_successful": client.successful,
            "full_account_transport_failures": client.transport_failures,
            "full_account_dart_status_failures": client.dart_status_failures,
        },
        "automatic_promotion": {
            "allowed": False,
            "promoted_ticker_count": 0,
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "approved_da_ids_changed": False,
            "da_source_layer_mutated": False,
            "raw_source_cache_mutated": False,
            "missing_da_assumed_zero": False,
            "prior_v897_targets_reaudited": False,
        },
        "next_step": next_step,
    }
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=OK",
            "CURRENT_EXACT_DA_SINGLE_BLOCKERS=10",
            "PRIOR_V897_TARGETS=8",
            "NEW_TARGET_COUNT=2",
            "NEW_TARGET_TICKERS=" + ",".join(sorted(new_targets)),
            f"XBRL_BOTH_EXACT_RECOVERED={len(xbrl_both)}",
            "XBRL_BOTH_EXACT_TICKERS=" + ",".join(xbrl_both),
            f"FULL_ACCOUNT_BOTH_EXACT_UNIQUE={len(full_both)}",
            "FULL_ACCOUNT_BOTH_EXACT_TICKERS=" + ",".join(full_both),
            f"ANY_OFFICIAL_BOTH_EXACT_CANDIDATE={len(any_both)}",
            "AUTO_PROMOTION=false",
            "PRODUCTION_DATA_CHANGED=false",
            "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
            "SCORING_POLICY_CHANGED=false",
            "APPROVED_DA_IDS_CHANGED=false",
            "RAW_SOURCE_CACHE_MUTATED=false",
            "MISSING_DA_ASSUMED_ZERO=false",
            "PRIOR_V897_TARGETS_REAUDITED=false",
            "NEXT_STEP=" + next_step,
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.10.3 신규 D&A 단일 blocker 감사",
            "",
            f"- 버전: `{VERSION}`",
            "- 대상: HMM(011200), 모나리자(012690)",
            "- 기존 V8.9.7의 8종목은 재감사하지 않음",
            "",
            "## 공식 소스",
            "",
            "- DART 사업보고서 접수번호 재탐색 + XBRL 재검사",
            "- V8.5.4 OpenDART 전체계정 API 교차검증",
            "",
            "## 안전 원칙",
            "",
            "- 승인 D&A ID 변경 없음",
            "- partial fact 자동 승격 없음",
            "- 누락 D&A=0 가정 없음",
            "- production/점수 미반영",
            "",
            "## 다음 단계",
            "",
            f"`{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8103_NEW_SINGLE_DA_AUDIT=PASS")
    print(OUT_LOG.read_text(encoding="utf-8"))

if __name__ == "__main__":
    main()

