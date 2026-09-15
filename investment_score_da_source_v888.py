#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-15-v8.8.8-source-only-da-promotion"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V887_VERSION = "2026-09-15-v8.8.7-xbrl-cfs-ofs-selection-audit"

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(".")
V887_CSV = ROOT / "latest/investment_score_xbrl_cfs_ofs_v887.csv"
V887_JSON = ROOT / "latest/investment_score_xbrl_cfs_ofs_v887_summary_latest.json"
POLICY_JSON = ROOT / "config/investment_score_policy_v880.json"
FINANCIAL_ENRICHER = ROOT / "financial_valuation_enricher.py"
OUT_CSV = ROOT / "latest/investment_score_da_source_v888.csv"
OUT_JSON = ROOT / "latest/investment_score_da_source_v888_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_da_source_v888_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_da_source_promotion_v888.md"

REQUIRED_NEXT_STEP = (
    "FREEZE_CFS_OFS_CONTEXT_MAPPING_AND_PROMOTE_ONLY_BOTH_UNIQUE_"
    "EXACT_FACTS_TO_A_SOURCE_ONLY_DA_LAYER"
)
REQUIRED_POLICY_TEXT = (
    "연결재무제표(CFS)를 우선하고, 없을 때만 개별재무제표(OFS)를 쓴다."
)
EXPECTED_MEMBER = {"CFS": "ConsolidatedMember", "OFS": "SeparateMember"}
PROMOTION_CLASS = "MATCHED_FS_MEMBER_BOTH_FACTS_UNIQUE"
SOURCE_STATUS = "READY_SOURCE_ONLY_BOTH_EXACT_UNIQUE"
APPROVED = {
    "AdjustmentsForDepreciationExpense": "ifrs-full_AdjustmentsForDepreciationExpense",
    "AdjustmentsForAmortisationExpense": "ifrs-full_AdjustmentsForAmortisationExpense",
}

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def clean_ticker(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def finite(v):
    try:
        x = float(v)
    except Exception:
        return None
    return x if math.isfinite(x) else None

def is_true(v):
    return str(v or "").strip().upper() == "TRUE"

def jlist(v):
    obj = json.loads(str(v or ""))
    if not isinstance(obj, list):
        raise RuntimeError("EXPECTED_JSON_LIST")
    return obj

def canon(x):
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return format(x, ".15g")

def main():
    for path in (V887_CSV, V887_JSON, POLICY_JSON, FINANCIAL_ENRICHER):
        if not path.is_file():
            raise RuntimeError("MISSING_REQUIRED_SOURCE:" + str(path))

    v887 = read_json(V887_JSON)
    rows = read_csv(V887_CSV)
    policy = read_json(POLICY_JSON)
    enricher = FINANCIAL_ENRICHER.read_text(encoding="utf-8")

    if v887.get("version") != V887_VERSION: raise RuntimeError("V887_VERSION_MISMATCH")
    if v887.get("status") != "SELECTION_AUDIT_ONLY": raise RuntimeError("V887_STATUS_MISMATCH")
    if v887.get("target_count") != 57 or len(rows) != 57: raise RuntimeError("V887_TARGET_COUNT_MISMATCH")
    if v887.get("source_fs_mismatch_count") != 0: raise RuntimeError("V887_SOURCE_FS_MISMATCH_NOT_ZERO")
    if v887.get("both_approved_facts_unique_ticker_count") != 52: raise RuntimeError("V887_BOTH_UNIQUE_COUNT_MISMATCH")
    if v887.get("partial_one_fact_ticker_count") != 4: raise RuntimeError("V887_PARTIAL_COUNT_MISMATCH")
    if v887.get("no_matching_fs_member_ticker_count") != 1: raise RuntimeError("V887_NO_MEMBER_COUNT_MISMATCH")
    if v887.get("remaining_value_conflict_ticker_count") != 0: raise RuntimeError("V887_VALUE_CONFLICT_NOT_ZERO")
    if v887.get("remaining_multi_context_ticker_count") != 0: raise RuntimeError("V887_CONTEXT_CONFLICT_NOT_ZERO")
    if v887.get("next_step") != REQUIRED_NEXT_STEP: raise RuntimeError("V887_NEXT_STEP_MISMATCH")

    mapping = v887.get("mapping_under_test") or {}
    if mapping.get("axis") != "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis": raise RuntimeError("V887_FS_AXIS_MISMATCH")
    if mapping.get("CFS") != "ifrs-full:ConsolidatedMember": raise RuntimeError("V887_CFS_MEMBER_MISMATCH")
    if mapping.get("OFS") != "ifrs-full:SeparateMember": raise RuntimeError("V887_OFS_MEMBER_MISMATCH")
    if policy.get("version") != POLICY_VERSION: raise RuntimeError("V880_POLICY_VERSION_MISMATCH")
    if policy.get("status") != "APPROVED_DESIGN_NOT_PRODUCTION": raise RuntimeError("V880_POLICY_STATUS_MISMATCH")
    if REQUIRED_POLICY_TEXT not in enricher: raise RuntimeError("CFS_OFS_POLICY_TEXT_NOT_FOUND")

    promoted, held, seen = [], [], set()
    for row in rows:
        code = clean_ticker(row.get("ticker"))
        if not code or code in seen: raise RuntimeError("INVALID_OR_DUPLICATE_TICKER:" + code)
        seen.add(code)
        cls = str(row.get("selection_classification") or "")
        if cls != PROMOTION_CLASS:
            held.append((code, cls))
            continue

        if str(row.get("source_fs_status") or "") != "CONSISTENT": raise RuntimeError("SOURCE_FS_NOT_CONSISTENT:" + code)
        fs = str(row.get("source_fs_div") or "")
        if fs not in EXPECTED_MEMBER: raise RuntimeError("FS_DIV_INVALID:" + code)
        if str(row.get("target_member") or "") != EXPECTED_MEMBER[fs]: raise RuntimeError("TARGET_MEMBER_MISMATCH:" + code)
        if str(row.get("xbrl_status") or "") != "OK": raise RuntimeError("XBRL_NOT_OK:" + code)
        if not is_true(row.get("both_approved_facts_unique")): raise RuntimeError("BOTH_UNIQUE_FALSE:" + code)
        if is_true(row.get("selected_value_conflict")): raise RuntimeError("VALUE_CONFLICT:" + code)
        if is_true(row.get("selected_context_conflict")): raise RuntimeError("CONTEXT_CONFLICT:" + code)
        if int(row.get("selected_depreciation_unique_values") or 0) != 1: raise RuntimeError("DEP_UNIQUE_COUNT:" + code)
        if int(row.get("selected_amortisation_unique_values") or 0) != 1: raise RuntimeError("AMO_UNIQUE_COUNT:" + code)
        if int(row.get("selected_unit_signature_count") or 0) != 1: raise RuntimeError("UNIT_SIGNATURE_COUNT:" + code)
        if jlist(row.get("selected_unit_signatures_json")) != ["iso4217:KRW"]: raise RuntimeError("UNIT_NOT_KRW:" + code)

        values = defaultdict(set)
        units = set()
        for fact in jlist(row.get("selected_facts_json")):
            local = str(fact.get("local_name") or "")
            if local not in APPROVED:
                continue
            if str(fact.get("value_status") or "") != "OK": raise RuntimeError("FACT_VALUE_NOT_OK:" + code)
            value = finite(fact.get("normalized_value"))
            if value is None: raise RuntimeError("FACT_VALUE_NONNUMERIC:" + code)
            values[local].add(value)
            measures = tuple(sorted((fact.get("unit") or {}).get("measures") or []))
            if measures: units.add(measures)

        dep_set = values["AdjustmentsForDepreciationExpense"]
        amo_set = values["AdjustmentsForAmortisationExpense"]
        if len(dep_set) != 1 or len(amo_set) != 1: raise RuntimeError("FACT_VALUE_SET_MISMATCH:" + code)
        if units != {("iso4217:KRW",)}: raise RuntimeError("FACT_UNIT_SET_MISMATCH:" + code)

        dep, amo = next(iter(dep_set)), next(iter(amo_set))
        total = dep + amo
        evidence = finite(row.get("evidence_da_sum"))
        if evidence is None: raise RuntimeError("EVIDENCE_SUM_MISSING:" + code)
        if abs(total - evidence) > max(1.0, abs(total) * 1e-12): raise RuntimeError("EVIDENCE_SUM_MISMATCH:" + code)

        promoted.append({
            "ticker": code,
            "name": str(row.get("name") or ""),
            "market": str(row.get("market") or ""),
            "target_year": str(row.get("target_year") or ""),
            "rcept_no": str(row.get("rcept_no") or ""),
            "source_fs_selected_from": str(row.get("source_fs_selected_from") or ""),
            "source_fs_div": fs,
            "target_member": str(row.get("target_member") or ""),
            "depreciation_account_id": APPROVED["AdjustmentsForDepreciationExpense"],
            "depreciation_value": canon(dep),
            "amortisation_account_id": APPROVED["AdjustmentsForAmortisationExpense"],
            "amortisation_value": canon(amo),
            "depreciation_amortization_total": canon(total),
            "unit": "KRW",
            "source_status": SOURCE_STATUS,
            "source_contract": VERSION,
            "source_evidence_version": V887_VERSION,
        })

    promoted.sort(key=lambda x: x["ticker"])
    held.sort()
    if len(promoted) != 52: raise RuntimeError(f"PROMOTED_COUNT_MISMATCH:{len(promoted)}")
    held_counts = Counter(cls for _, cls in held)
    expected_held = Counter({"MATCHED_FS_MEMBER_PARTIAL_ONE_FACT": 4, "NO_MATCHING_FS_MEMBER": 1})
    if held_counts != expected_held: raise RuntimeError("HELD_CLASSIFICATION_COUNTS_MISMATCH")

    fields = list(promoted[0].keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(promoted)

    fs_counts = Counter(x["source_fs_div"] for x in promoted)
    market_counts = Counter(x["market"] for x in promoted)
    summary = {
        "version": VERSION,
        "policy_version": POLICY_VERSION,
        "source_evidence_version": V887_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "READY_SOURCE_ONLY",
        "promotion_scope": "SOURCE_ONLY_DA_LAYER",
        "eligibility_contract": {
            "approved_account_ids": list(APPROVED.values()),
            "requires_both_approved_facts": True,
            "requires_each_fact_unique_after_fs_selection": True,
            "requires_source_fs_consistent": True,
            "requires_single_selected_context": True,
            "requires_krw_unit": True,
            "partial_one_fact_is_not_promoted": True,
            "no_matching_fs_member_is_not_promoted": True,
        },
        "frozen_fs_mapping": {
            "axis": "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis",
            "CFS": "ifrs-full:ConsolidatedMember",
            "OFS": "ifrs-full:SeparateMember",
            "financial_policy_text": REQUIRED_POLICY_TEXT,
        },
        "source_target_count": 57,
        "source_only_ready_count": 52,
        "held_count": 5,
        "held_classification_counts": dict(held_counts),
        "promoted_fs_div_counts": dict(fs_counts),
        "promoted_market_counts": dict(market_counts),
        "source_hashes": {
            str(V887_CSV): sha256(V887_CSV),
            str(V887_JSON): sha256(V887_JSON),
            str(POLICY_JSON): sha256(POLICY_JSON),
        },
        "decision": {
            "source_only_da_layer_ready": True,
            "ready_for_ev_ebitda_dry_run": True,
            "ready_for_production_da_use": False,
            "ready_for_production_score_write": False,
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "new_da_id_approved": False,
            "production_da_value_promoted": False,
            "ev_ebitda_recalculated": False,
            "standalone_swing_changed": False,
        },
        "next_step": "DRY_RUN_EV_EBITDA_WITH_V888_SOURCE_ONLY_DA_AND_NO_PRODUCTION_WRITE",
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    OUT_DOC.write_text("\n".join([
        "# V8.8.8 source-only D&A 승격 계약", "",
        f"- 버전: `{VERSION}`", "- 상태: `READY_SOURCE_ONLY`",
        "- 목적: V8.8.7에서 검증된 D&A 값을 production과 분리된 source-only 층으로 고정한다.", "",
        "## 승격 조건", "",
        "- V8.8.0에서 승인된 정확한 두 IFRS 계정 ID만 사용한다.",
        "- 기존 재무정책과 동일한 CFS/OFS member를 사용한다.",
        "- 감가상각과 무형자산상각 값이 각각 유일하고 두 fact가 모두 있어야 한다.",
        "- 값/context 충돌이 없고 단위가 KRW이어야 한다.", "",
        "## 결과", "", "- 57개 중 52개만 source-only D&A READY로 승격한다.",
        "- partial one fact 4개와 matching FS member가 없는 1개는 보류한다.", "",
        "## 이번 단계에서 하지 않는 것", "",
        "- 기존 V8.8.3의 14개 exact-ready와 병합하지 않는다.",
        "- production source cache를 수정하지 않는다.",
        "- EV/EBITDA를 재계산하지 않는다.",
        "- 100점 투자점수를 기록하지 않는다.",
        "- 새로운 D&A 계정 ID를 승인하지 않는다.", "",
        "## 다음 단계", "",
        "- V8.8.9에서 기존 raw D&A와 V8.8.8 source-only D&A의 병합 우선순위를 dry-run으로 검증한다.",
        "- production 반영은 별도 승인 단계까지 금지한다.", "",
    ]), encoding="utf-8")

    log = [
        f"VERSION={VERSION}", "STATUS=READY_SOURCE_ONLY", "SOURCE_TARGETS=57",
        "SOURCE_ONLY_DA_READY=52", "HELD_TOTAL=5",
        f"HELD_PARTIAL_ONE_FACT={held_counts['MATCHED_FS_MEMBER_PARTIAL_ONE_FACT']}",
        f"HELD_NO_MATCHING_FS_MEMBER={held_counts['NO_MATCHING_FS_MEMBER']}",
        f"PROMOTED_CFS={fs_counts['CFS']}", f"PROMOTED_OFS={fs_counts['OFS']}",
        "CFS_OFS_MAPPING_FROZEN=true", "BOTH_APPROVED_FACTS_REQUIRED=true",
        "SOURCE_ONLY_DA_VALUE_PROMOTED=true", "PRODUCTION_DA_VALUE_PROMOTED=false",
        "EV_EBITDA_RECALCULATED=false", "PRODUCTION_DATA_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false", "SCORING_POLICY_CHANGED=false",
        "NEW_DA_ID_APPROVED=false", "STANDALONE_SWING_CHANGED=false",
        "READY_FOR_EV_EBITDA_DRY_RUN=true", "STATUS_OK=true",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("V888_SOURCE_ONLY_DA_PROMOTION=PASS")
    print("\n".join(log))

if __name__ == "__main__":
    main()
