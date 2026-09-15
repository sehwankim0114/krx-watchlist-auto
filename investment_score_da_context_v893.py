#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_xbrl_cfs_ofs_v887 as base

VERSION = "2026-09-15-v8.9.3-v892-exact-context-audit"
V892_VERSION = "2026-09-15-v8.9.2-official-dart-xbrl-da-retry"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

V892_CSV = ROOT / "latest/investment_score_da_official_retry_v892.csv"
V892_JSON = ROOT / "latest/investment_score_da_official_retry_v892_summary_latest.json"
RAW_CSV = ROOT / "latest/investment_score_source_cache_latest.csv"
POLICY_JSON = ROOT / "config/investment_score_policy_v880.json"
FINANCIAL_ENRICHER = ROOT / "financial_valuation_enricher.py"

OUT_CSV = ROOT / "latest/investment_score_da_context_v893.csv"
OUT_JSON = ROOT / "latest/investment_score_da_context_v893_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_da_context_v893_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_da_context_v893.md"

APPROVED_RESULT = "RETRY_APPROVED_EXACT_FACT_FOUND"
REQUIRED_POLICY_TEXT = (
    "연결재무제표(CFS)를 우선하고, 없을 때만 개별재무제표(OFS)를 쓴다."
)

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def ticker(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def bool_text(v):
    return str(v or "").strip().upper() == "TRUE"

def as_int(v):
    try:
        s = str(v or "").strip()
        return int(float(s)) if s else None
    except Exception:
        return None

def report_year(row):
    text = str(row.get("selected_report_nm") or "")
    m = re.search(r"\((20\d{2})\.\d{2}\)", text)
    return int(m.group(1)) if m else None

def choose_target_year(row, raw):
    report = report_year(row)
    deep = as_int(raw.get("deep_source_year"))
    annual = as_int(raw.get("annual_source_year"))

    if report is not None:
        return report, "V892_SELECTED_REPORT_NAME"

    if deep is not None:
        return deep, "RAW_DEEP_SOURCE_YEAR"

    if annual is not None:
        return annual, "RAW_ANNUAL_SOURCE_YEAR"

    return None, "UNAVAILABLE"

def audit_one(row, raw, api_key):
    code = ticker(row.get("ticker"))
    target_year, year_source = choose_target_year(row, raw)
    item = {
        "ticker": code,
        "name": str(row.get("name") or ""),
        "market": str(row.get("market") or ""),
        "rcept_no": str(row.get("selected_rcept_no") or ""),
        "target_year": target_year,
    }

    if not item["rcept_no"]:
        raise RuntimeError(f"V892_SELECTED_RCEPT_MISSING:{code}")
    if target_year is None:
        raise RuntimeError(f"TARGET_YEAR_UNAVAILABLE:{code}")

    result = base.process_one(item, raw, api_key)
    result.update({
        "single_blocker_ticker":
            "TRUE" if bool_text(row.get("single_blocker_ticker")) else "FALSE",
        "target_year_source": year_source,
        "v892_approved_exact_fact_count":
            str(row.get("approved_exact_fact_count") or ""),
        "v892_approved_exact_local_names":
            str(row.get("approved_exact_local_names") or ""),
        "v892_both_approved_exact_local_names_present":
            str(row.get("both_approved_exact_local_names_present") or ""),
        "v892_corp_code_source":
            str(row.get("corp_code_source") or ""),
        "v892_selected_report_nm":
            str(row.get("selected_report_nm") or ""),
    })

    ready = (
        result.get("selection_classification")
        == "MATCHED_FS_MEMBER_BOTH_FACTS_UNIQUE"
        and str(result.get("both_approved_facts_unique") or "").upper() == "TRUE"
        and str(result.get("selected_value_conflict") or "").upper() == "FALSE"
        and str(result.get("selected_context_conflict") or "").upper() == "FALSE"
        and result.get("source_fs_status") in {"CONSISTENT", "MISMATCH"}
        and result.get("source_fs_div") in {"CFS", "OFS"}
    )
    result["v893_source_promotion_candidate"] = "TRUE" if ready else "FALSE"

    if ready:
        result["v893_next_action"] = (
            "검증된 exact D&A source-only 후보; 별도 freeze 단계에서만 반영 가능"
        )
    elif result.get("selection_classification") == "SOURCE_FS_DIV_UNAVAILABLE":
        result["v893_next_action"] = (
            "V8.9.2 exact fact는 확인됐지만 기존 재무제표 CFS/OFS basis가 없어 "
            "자동 source 승격 금지"
        )
    elif result.get("selection_classification") == "MATCHED_FS_MEMBER_PARTIAL_ONE_FACT":
        result["v893_next_action"] = (
            "승인 exact fact 한쪽만 확인됨; missing fact를 0으로 간주하지 않고 "
            "alternate official source 감사로 이동"
        )
    else:
        result["v893_next_action"] = (
            "context/value/source-FS 조건 미충족; 자동 승격 금지"
        )

    return result

def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DART_API_KEY_MISSING")

    for path in (
        V892_CSV,
        V892_JSON,
        RAW_CSV,
        POLICY_JSON,
        FINANCIAL_ENRICHER,
    ):
        if not path.is_file():
            raise RuntimeError("MISSING_REQUIRED_SOURCE:" + str(path))

    s892 = read_json(V892_JSON)
    rows892 = read_csv(V892_CSV)
    raw_rows = read_csv(RAW_CSV)
    policy = read_json(POLICY_JSON)
    enricher_text = FINANCIAL_ENRICHER.read_text(encoding="utf-8")

    if s892.get("version") != V892_VERSION:
        raise RuntimeError("V892_VERSION_MISMATCH")
    if s892.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V892_POLICY_VERSION_MISMATCH")
    if s892.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V892_STATUS_MISMATCH")
    if int(s892.get("approved_exact_fact_ticker_count") or 0) != 4:
        raise RuntimeError("V892_APPROVED_EXACT_COUNT_MISMATCH")
    if int(s892.get("single_blocker_approved_exact_fact_count") or 0) != 2:
        raise RuntimeError("V892_SINGLE_APPROVED_COUNT_MISMATCH")
    if policy.get("version") != POLICY_VERSION:
        raise RuntimeError("POLICY_VERSION_MISMATCH")
    if REQUIRED_POLICY_TEXT not in enricher_text:
        raise RuntimeError("EXISTING_CFS_OFS_POLICY_TEXT_NOT_FOUND")

    targets = [
        r for r in rows892
        if str(r.get("audit_result") or "") == APPROVED_RESULT
    ]
    targets.sort(key=lambda r: ticker(r.get("ticker")))

    if len(targets) != 4:
        raise RuntimeError(f"V893_TARGET_COUNT:{len(targets)}")
    if sum(bool_text(r.get("single_blocker_ticker")) for r in targets) != 2:
        raise RuntimeError("V893_SINGLE_BLOCKER_TARGET_COUNT_MISMATCH")

    expected = {"001530", "002380", "002450", "012450"}
    actual = {ticker(r.get("ticker")) for r in targets}
    if actual != expected:
        raise RuntimeError(
            "V893_TARGET_SET_MISMATCH:" + ",".join(sorted(actual))
        )

    raw_map = {
        ticker(r.get("ticker")): r
        for r in raw_rows
        if ticker(r.get("ticker"))
    }

    results = []
    for row in targets:
        code = ticker(row.get("ticker"))
        raw = raw_map.get(code) or {}
        results.append(audit_one(row, raw, api_key))

    results.sort(key=lambda r: r["ticker"])
    fields = list(results[0].keys())

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    class_counts = Counter(
        r.get("selection_classification") or "" for r in results
    )
    fs_status_counts = Counter(r.get("source_fs_status") or "" for r in results)
    fs_div_counts = Counter(r.get("source_fs_div") or "" for r in results)

    ready = [
        r["ticker"]
        for r in results
        if r.get("v893_source_promotion_candidate") == "TRUE"
    ]
    ready_single = [
        r["ticker"]
        for r in results
        if r.get("v893_source_promotion_candidate") == "TRUE"
        and r.get("single_blocker_ticker") == "TRUE"
    ]
    source_fs_unavailable = [
        r["ticker"]
        for r in results
        if r.get("selection_classification") == "SOURCE_FS_DIV_UNAVAILABLE"
    ]
    partial = [
        r["ticker"]
        for r in results
        if r.get("selection_classification") == "MATCHED_FS_MEMBER_PARTIAL_ONE_FACT"
    ]

    summary = {
        "version": VERSION,
        "policy_version": POLICY_VERSION,
        "v892_version": V892_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY",
        "target_count": len(results),
        "single_blocker_target_count": 2,
        "classification_counts": dict(class_counts),
        "source_fs_status_counts": dict(fs_status_counts),
        "source_fs_div_counts": dict(fs_div_counts),
        "source_promotion_candidate_count": len(ready),
        "source_promotion_candidate_tickers": ready,
        "single_blocker_source_promotion_candidate_count": len(ready_single),
        "single_blocker_source_promotion_candidate_tickers": ready_single,
        "source_fs_unavailable_count": len(source_fs_unavailable),
        "source_fs_unavailable_tickers": source_fs_unavailable,
        "partial_one_fact_count": len(partial),
        "partial_one_fact_tickers": partial,
        "automatic_promotion": {
            "allowed": False,
            "promoted_ticker_count": 0,
            "reason": (
                "V8.9.3은 V8.9.2에서 복구된 승인 exact fact의 기존 CFS/OFS "
                "정책·context·value uniqueness만 감사한다. source layer 반영은 "
                "별도 freeze 단계에서 수행한다."
            ),
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "new_da_id_approved": False,
            "v888_source_layer_mutated": False,
            "v892_evidence_mutated": False,
            "missing_da_assumed_zero": False,
            "source_fs_div_guessed": False,
            "preferred_issuer_mapping_created": False,
        },
        "next_step": (
            "FREEZE_V893_VALIDATED_EXACT_DA_SOURCE_ONLY_THEN_RECHECK_SCORE"
            if ready
            else "AUDIT_REMAINING_PREFERRED_ISSUER_AND_ALTERNATE_DA_SOURCES"
        ),
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    log = [
        f"VERSION={VERSION}",
        "STATUS=AUDIT_ONLY",
        f"TARGET_COUNT={len(results)}",
        "SINGLE_BLOCKER_TARGET_COUNT=2",
        f"SOURCE_PROMOTION_CANDIDATE_COUNT={len(ready)}",
        f"SINGLE_BLOCKER_SOURCE_PROMOTION_CANDIDATE_COUNT={len(ready_single)}",
        f"SOURCE_FS_UNAVAILABLE_COUNT={len(source_fs_unavailable)}",
        f"PARTIAL_ONE_FACT_COUNT={len(partial)}",
        "AUTOMATIC_PROMOTION=false",
        "PRODUCTION_API_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "SCORING_POLICY_CHANGED=false",
        "NEW_DA_ID_APPROVED=false",
        "V888_SOURCE_LAYER_MUTATED=false",
        "V892_EVIDENCE_MUTATED=false",
        "MISSING_DA_ASSUMED_ZERO=false",
        "SOURCE_FS_DIV_GUESSED=false",
        "PREFERRED_ISSUER_MAPPING_CREATED=false",
        "STATUS_OK=true",
        f"NEXT_STEP={summary['next_step']}",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    doc = [
        "# V8.9.3 V8.9.2 복구 exact D&A context 감사",
        "",
        f"- 버전: `{VERSION}`",
        "- 상태: AUDIT_ONLY",
        "- 대상: V8.9.2 승인 exact fact 복구 4종목",
        "",
        "## 감사 계약",
        "",
        "- V8.8.7의 CFS/OFS 선택 및 XBRL context/value uniqueness 로직을 그대로 재사용한다.",
        "- CFS/OFS basis가 기존 raw source에 없으면 추정하지 않는다.",
        "- target year는 V8.9.2에서 실제 선택된 공식 사업보고서 명칭에서 우선 확인한다.",
        "- 승인 exact depreciation/amortisation이 각각 하나의 값으로 선택될 때만 source promotion candidate로 표시한다.",
        "- candidate 표시는 자동 승격이 아니다.",
        "",
        "## 안전 원칙",
        "",
        "- production API와 투자종합점수를 수정하지 않는다.",
        "- V8.8.8 source layer와 V8.9.2 evidence를 수정하지 않는다.",
        "- 새 D&A ID를 승인하지 않는다.",
        "- 누락 D&A를 0으로 간주하지 않는다.",
        "- CFS/OFS 구분을 추정하지 않는다.",
        "- 신규 우선주 issuer mapping을 만들지 않는다.",
        "",
        "## 다음 단계",
        "",
        "BOTH_FACTS_UNIQUE 후보가 있으면 별도 source-only freeze 후 점수 dry-run을 재검증한다.",
        "",
    ]
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text("\n".join(doc), encoding="utf-8")

    print("V893_EXACT_CONTEXT_AUDIT=PASS")
    print("\n".join(log))

if __name__ == "__main__":
    main()
