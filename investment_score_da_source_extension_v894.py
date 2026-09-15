#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-15-v8.9.4-freeze-v893-da-source-extension"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V893_VERSION = "2026-09-15-v8.9.3-v892-exact-context-audit"
V888_VERSION = "2026-09-15-v8.8.8-freeze-xbrl-da-source-layer"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

V893_CSV = ROOT / "latest/investment_score_da_context_v893.csv"
V893_JSON = ROOT / "latest/investment_score_da_context_v893_summary_latest.json"
V888_CSV = ROOT / "latest/investment_score_da_source_v888.csv"
V888_JSON = ROOT / "latest/investment_score_da_source_v888_summary_latest.json"

OUT_CSV = ROOT / "latest/investment_score_da_source_extension_v894.csv"
OUT_JSON = ROOT / "latest/investment_score_da_source_extension_v894_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_da_source_extension_v894_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_da_source_extension_v894.md"

DEP_LOCAL = "AdjustmentsForDepreciationExpense"
AMO_LOCAL = "AdjustmentsForAmortisationExpense"

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def ticker(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def num(v):
    try:
        s = str(v or "").strip().replace(",", "")
        return None if not s else float(s)
    except Exception:
        return None

def parse_json_list(v):
    try:
        data = json.loads(str(v or ""))
    except Exception:
        return []
    return data if isinstance(data, list) else []

def exact_unique_values(selected_facts):
    values = defaultdict(set)
    for fact in selected_facts:
        local = str(fact.get("local_name") or "")
        if local not in {DEP_LOCAL, AMO_LOCAL}:
            continue
        value = num(fact.get("normalized_value"))
        if value is None:
            raise RuntimeError(f"V894_NONNUMERIC_EXACT_FACT:{local}")
        values[local].add(value)

    if set(values) != {DEP_LOCAL, AMO_LOCAL}:
        raise RuntimeError(
            "V894_BOTH_EXACT_FACTS_NOT_PRESENT:" +
            ",".join(sorted(values))
        )
    if any(len(v) != 1 for v in values.values()):
        raise RuntimeError("V894_EXACT_FACT_VALUE_NOT_UNIQUE")

    return {
        DEP_LOCAL: next(iter(values[DEP_LOCAL])),
        AMO_LOCAL: next(iter(values[AMO_LOCAL])),
    }

def main():
    for p in (V893_CSV, V893_JSON, V888_CSV, V888_JSON):
        if not p.is_file():
            raise RuntimeError("MISSING_REQUIRED_SOURCE:" + str(p))

    s893 = read_json(V893_JSON)
    s888 = read_json(V888_JSON)
    rows893 = read_csv(V893_CSV)
    rows888 = read_csv(V888_CSV)

    if s893.get("version") != V893_VERSION:
        raise RuntimeError("V893_VERSION_MISMATCH")
    if s893.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V893_POLICY_VERSION_MISMATCH")
    if s893.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V893_STATUS_MISMATCH")
    if int(s893.get("source_promotion_candidate_count") or 0) != 1:
        raise RuntimeError("V893_PROMOTION_CANDIDATE_COUNT_NOT_1")
    if s893.get("source_promotion_candidate_tickers") != ["002450"]:
        raise RuntimeError("V893_PROMOTION_CANDIDATE_NOT_002450")
    if int(s893.get("single_blocker_source_promotion_candidate_count") or 0) != 1:
        raise RuntimeError("V893_SINGLE_PROMOTION_CANDIDATE_COUNT_NOT_1")

    if s888.get("version") != V888_VERSION:
        raise RuntimeError("V888_VERSION_MISMATCH")
    if s888.get("status") != "SOURCE_ONLY_READY":
        raise RuntimeError("V888_STATUS_MISMATCH")
    if int(s888.get("source_only_ready_count") or 0) != 66:
        raise RuntimeError("V888_SOURCE_COUNT_NOT_66")

    base_tickers = {ticker(r.get("ticker")) for r in rows888}
    if "002450" in base_tickers:
        raise RuntimeError("V894_EXTENSION_TICKER_ALREADY_IN_V888")

    candidates = [
        r for r in rows893
        if str(r.get("v893_source_promotion_candidate") or "").upper() == "TRUE"
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"V894_CANDIDATE_ROWS:{len(candidates)}")

    row = candidates[0]
    code = ticker(row.get("ticker"))
    if code != "002450":
        raise RuntimeError(f"V894_UNEXPECTED_TICKER:{code}")
    if row.get("single_blocker_ticker") != "TRUE":
        raise RuntimeError("V894_002450_NOT_SINGLE_BLOCKER")
    if row.get("selection_classification") != "MATCHED_FS_MEMBER_BOTH_FACTS_UNIQUE":
        raise RuntimeError("V894_SELECTION_CLASSIFICATION_MISMATCH")
    if row.get("both_approved_facts_unique") != "TRUE":
        raise RuntimeError("V894_BOTH_APPROVED_FACTS_NOT_UNIQUE")
    if row.get("selected_value_conflict") != "FALSE":
        raise RuntimeError("V894_VALUE_CONFLICT")
    if row.get("selected_context_conflict") != "FALSE":
        raise RuntimeError("V894_CONTEXT_CONFLICT")
    if row.get("source_fs_status") not in {"CONSISTENT", "MISMATCH"}:
        raise RuntimeError("V894_SOURCE_FS_STATUS_INVALID")
    if row.get("source_fs_div") not in {"CFS", "OFS"}:
        raise RuntimeError("V894_SOURCE_FS_DIV_INVALID")

    selected = parse_json_list(row.get("selected_facts_json"))
    exact = exact_unique_values(selected)

    dep = exact[DEP_LOCAL]
    amo = exact[AMO_LOCAL]
    total = dep + amo
    evidence_total = num(row.get("evidence_da_sum"))
    if evidence_total is None or abs(total - evidence_total) > 0.5:
        raise RuntimeError(
            f"V894_EVIDENCE_TOTAL_MISMATCH:{total}:{evidence_total}"
        )

    out_row = {
        "ticker": code,
        "name": row.get("name") or "",
        "market": row.get("market") or "",
        "target_year": row.get("target_year") or "",
        "fs_div": row.get("source_fs_div") or "",
        "source_layer": "V893_VALIDATED_EXACT_CONTEXT_EXTENSION",
        "source_status": "READY_EXACT_DA_SOURCE_EXTENSION",
        "depreciation_value": dep,
        "amortisation_value": amo,
        "da_total": total,
        "approved_exact_fact_count": 2,
        "both_exact_facts_present": "TRUE",
        "single_blocker_ticker": "TRUE",
        "evidence_ref": "latest/investment_score_da_context_v893.csv",
        "evidence_rcept_no": row.get("rcept_no") or "",
        "evidence_classification": row.get("selection_classification") or "",
    }

    fields = list(out_row.keys())
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow(out_row)

    summary = {
        "version": VERSION,
        "policy_version": POLICY_VERSION,
        "v893_version": V893_VERSION,
        "v888_version": V888_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "SOURCE_EXTENSION_ONLY_READY",
        "base_v888_source_count": 66,
        "extension_source_count": 1,
        "combined_source_count_if_shadow_merged": 67,
        "extension_tickers": [code],
        "extension_values": {
            code: {
                "target_year": out_row["target_year"],
                "fs_div": out_row["fs_div"],
                "depreciation_value": dep,
                "amortisation_value": amo,
                "da_total": total,
            }
        },
        "automatic_production_activation": {
            "allowed": False,
            "activated_ticker_count": 0,
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "new_da_id_approved": False,
            "v888_source_layer_mutated": False,
            "v893_evidence_mutated": False,
            "missing_da_assumed_zero": False,
            "preferred_issuer_mapping_created": False,
            "duplicate_with_v888": False,
        },
        "next_step": "DRY_RUN_V895_WITH_V888_PLUS_V894_EXTENSION",
    }
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    log = [
        f"VERSION={VERSION}",
        "STATUS=SOURCE_EXTENSION_ONLY_READY",
        "BASE_V888_SOURCE_COUNT=66",
        "EXTENSION_SOURCE_COUNT=1",
        "COMBINED_SOURCE_COUNT_IF_SHADOW_MERGED=67",
        "EXTENSION_TICKER=002450",
        f"DEPRECIATION_VALUE={dep}",
        f"AMORTISATION_VALUE={amo}",
        f"DA_TOTAL={total}",
        "PRODUCTION_API_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "SCORING_POLICY_CHANGED=false",
        "NEW_DA_ID_APPROVED=false",
        "V888_SOURCE_LAYER_MUTATED=false",
        "V893_EVIDENCE_MUTATED=false",
        "MISSING_DA_ASSUMED_ZERO=false",
        "PREFERRED_ISSUER_MAPPING_CREATED=false",
        "STATUS_OK=true",
        "NEXT_STEP=DRY_RUN_V895_WITH_V888_PLUS_V894_EXTENSION",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    doc = [
        "# V8.9.4 V8.9.3 검증 D&A source extension 동결",
        "",
        f"- 버전: `{VERSION}`",
        "- 상태: SOURCE_EXTENSION_ONLY_READY",
        "- base V8.8.8은 변경하지 않음",
        "",
        "## 동결 대상",
        "",
        "- 002450 삼익악기",
        "- 2025 CFS",
        "- V8.9.3에서 depreciation/amortisation 각각 단일 값 확인",
        "- value/context conflict 없음",
        "",
        "## 안전 원칙",
        "",
        "- V8.8.8 66종목 source layer는 수정하지 않는다.",
        "- production API와 investment_score_100을 수정하지 않는다.",
        "- 새 D&A ID를 승인하지 않는다.",
        "- 누락 D&A를 0으로 간주하지 않는다.",
        "- 우선주 issuer mapping을 새로 만들지 않는다.",
        "",
        "## 다음 단계",
        "",
        "V8.9.5에서 V8.8.8 66종목 + V8.9.4 1종목을 shadow raw에만 합쳐 "
        "기존 V8.8.2 scorer로 투자종합점수를 dry-run 재검증한다.",
        "",
    ]
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text("\n".join(doc), encoding="utf-8")

    print("V894_SOURCE_EXTENSION_FREEZE=PASS")
    print("\n".join(log))

if __name__ == "__main__":
    main()
