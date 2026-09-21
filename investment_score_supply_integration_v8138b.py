#!/usr/bin/env python3
from __future__ import annotations

import copy
import csv
import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer
import investment_score_supply_actionable_v8136 as supplyaudit

VERSION = "2026-09-21-v8.13.8b-stage-current-universe-supply-source-integration"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
SUPPLY_POLICY_VERSION = "2026-07-01-v6.0-supply-status-separated"
V8101_VERSION = "2026-09-15-v8.10.1-freeze-complete-supply-evidence-and-dry-run"
V8137_VERSION = "2026-09-21-v8.13.7-freeze-current-actionable-supply-and-shadow-score"
V8137_RESULT_COMMIT = "4c334c6b4210ccfe05bd990da19597a6d21da9ba"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

OLD_SOURCE = ROOT / "latest/investment_score_supply_source_v8101.csv"
OLD_SUMMARY = ROOT / "latest/investment_score_supply_source_v8101_summary_latest.json"
NEW_SOURCE = ROOT / "latest/investment_score_supply_source_v8137.csv"
NEW_SUMMARY = ROOT / "latest/investment_score_supply_shadow_v8137_summary_latest.json"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"

SOURCE_OUT = ROOT / "latest/investment_score_supply_candidate_v8138b.csv"
COMPARE_OUT = ROOT / "latest/investment_score_supply_candidate_v8138b_regression.csv"
SUMMARY_OUT = ROOT / "latest/investment_score_supply_candidate_v8138b_summary_latest.json"
LOG_OUT = ROOT / "latest/investment_score_supply_candidate_v8138b_run_log_latest.txt"
DOC_OUT = ROOT / "docs/investment_score_supply_candidate_v8138b.md"

BASE_CSV = Path("/tmp/v8138b_baseline_score.csv")
BASE_JSON = Path("/tmp/v8138b_baseline_score.json")
BASE_LOG = Path("/tmp/v8138b_baseline_score.log")
BASE_DOC = Path("/tmp/v8138b_baseline_score.md")
CAND_CSV = Path("/tmp/v8138b_candidate_score.csv")
CAND_JSON = Path("/tmp/v8138b_candidate_score.json")
CAND_LOG = Path("/tmp/v8138b_candidate_score.log")
CAND_DOC = Path("/tmp/v8138b_candidate_score.md")

CURRENT_OLD = {
    "001440": "대한전선",
    "066570": "LG전자",
    "071840": "롯데하이마트",
    "086280": "현대글로비스",
}
CURRENT_NEW = {
    "007540": "샘표",
    "029780": "삼성카드",
    "084690": "대상홀딩스",
    "114090": "GKL",
}
ALL_TARGETS = {**CURRENT_OLD, **CURRENT_NEW}
SUPPLY_REASON = "수급·공시부담:SUPPLY_LIMITED_NO_POSITIVE_EVIDENCE"

def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write_rows(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

def split_missing(text):
    return [x for x in str(text or "").split(";") if x]

def stable(row):
    return json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

def run_scorer(prod_rows, out_csv, out_json, out_log, out_doc):
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
        scorer.OUT_CSV = Path(out_csv)
        scorer.OUT_JSON = Path(out_json)
        scorer.OUT_LOG = Path(out_log)
        scorer.OUT_DOC = Path(out_doc)
        scorer.production_rows = lambda: copy.deepcopy(prod_rows)
        rc = scorer.main()
    finally:
        scorer.production_rows = original
        for key, value in old.items():
            setattr(scorer, key, value)
    if rc not in (None, 0):
        raise RuntimeError("V8138B_SCORER_FAILED:" + str(rc))

def audit_current_supply(
    code,
    name,
    corp_code,
    corp_name,
    keyword_rules,
    relief_keywords,
    api_key,
    audit_start,
    audit_end,
):
    fetched = supplyaudit.fetch_corp_reports(
        api_key,
        corp_code,
        audit_start,
        audit_end,
    )
    if not fetched["complete"]:
        raise RuntimeError(
            "V8138B_REAUDIT_INCOMPLETE:"
            + code
            + ":"
            + json.dumps(
                fetched["api_errors"],
                ensure_ascii=False,
            )
        )

    evidence = []
    max_severity = 0
    keyword_set = set()
    relief_count = 0

    for item in fetched["reports"]:
        report_name = str(item.get("report_nm") or "")
        is_risk, labels, severity, relief = (
            supplyaudit.classify_report(
                report_name,
                keyword_rules,
                relief_keywords,
            )
        )
        if relief:
            relief_count += 1
        if not is_risk:
            continue
        max_severity = max(max_severity, severity)
        keyword_set.update(labels)
        evidence.append({
            "rcept_dt": str(item.get("rcept_dt") or ""),
            "rcept_no": str(item.get("rcept_no") or ""),
            "report_nm": report_name,
            "corp_name": str(item.get("corp_name") or ""),
            "keywords": labels,
            "severity": severity,
            "relief_flag": relief,
        })

    evidence.sort(
        key=lambda x: (x["rcept_dt"], x["rcept_no"]),
        reverse=True,
    )

    if evidence:
        classification = "COMPLETE_180D_POSITIVE_BURDEN"
        level = supplyaudit.severity_to_level(
            max_severity,
            len(evidence),
        )
    else:
        classification = "COMPLETE_180D_NO_POSITIVE_BURDEN"
        level = "없음"

    latest = evidence[0] if evidence else {}

    return {
        "ticker": code,
        "name": name,
        "source_origin": "V8101_CURRENT_OVERLAP_REAUDITED_V8138",
        "source_status": "SOURCE_ONLY_READY",
        "source_version": VERSION,
        "source_classification": classification,
        "corp_code": corp_code,
        "corp_name_dart": corp_name,
        "audit_start_date": audit_start.isoformat(),
        "audit_end_date": audit_end.isoformat(),
        "requested_lookback_days": 180,
        "chunk_count": len(fetched["chunks"]),
        "dart_list_api_calls": fetched["api_calls"],
        "dart_report_count": len(fetched["reports"]),
        "risk_report_count": len(evidence),
        "supply_status": "OK",
        "supply_level": level,
        "risk_keywords": ",".join(sorted(keyword_set)),
        "latest_risk_report_date": latest.get("rcept_dt", ""),
        "latest_risk_report_name": latest.get("report_nm", ""),
        "latest_risk_rcept_no": latest.get("rcept_no", ""),
        "relief_report_match_count": relief_count,
        "evidence_reports_json": json.dumps(
            evidence[:50],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "chunk_summaries_json": json.dumps(
            fetched["chunks"],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "evidence_ref": "V8138B:DART_LIST_180D_EXACT_STOCK:" + code,
    }

def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("V8138B_DART_API_KEY_MISSING")

    for p in (
        OLD_SOURCE,
        OLD_SUMMARY,
        NEW_SOURCE,
        NEW_SUMMARY,
        FIN,
    ):
        if not p.is_file():
            raise RuntimeError("V8138B_MISSING_INPUT:" + str(p))

    old_summary = read_json(OLD_SUMMARY)
    new_summary = read_json(NEW_SUMMARY)

    if old_summary.get("version") != V8101_VERSION:
        raise RuntimeError("V8138B_V8101_VERSION_MISMATCH")
    if old_summary.get("status") != "SOURCE_ONLY_READY":
        raise RuntimeError("V8138B_V8101_STATUS_MISMATCH")
    if old_summary.get("supply_policy_version") != SUPPLY_POLICY_VERSION:
        raise RuntimeError("V8138B_V8101_SUPPLY_POLICY_MISMATCH")

    if new_summary.get("version") != V8137_VERSION:
        raise RuntimeError("V8138B_V8137_VERSION_MISMATCH")
    if new_summary.get("status") != "SOURCE_ONLY_FROZEN_SHADOW_PASS":
        raise RuntimeError("V8138B_V8137_STATUS_MISMATCH")
    if new_summary.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8138B_POLICY_VERSION_MISMATCH")
    if new_summary.get("supply_policy_version") != SUPPLY_POLICY_VERSION:
        raise RuntimeError("V8138B_V8137_SUPPLY_POLICY_MISMATCH")
    if int(new_summary.get("source_frozen_count") or 0) != 4:
        raise RuntimeError("V8138B_V8137_SOURCE_COUNT_NOT_4")
    if int(new_summary.get("shadow_ready_count") or 0) != 27:
        raise RuntimeError("V8138B_V8137_SHADOW_READY_NOT_27")
    if int(new_summary.get("shadow_blocker_occurrences") or 0) != 728:
        raise RuntimeError("V8138B_V8137_SHADOW_BLOCKERS_NOT_728")
    if new_summary.get("next_step") != (
        "STAGE_CURRENT_UNIVERSE_SUPPLY_SOURCE_INTEGRATION_V8138"
    ):
        raise RuntimeError("V8138B_PREDECESSOR_NEXT_STEP_MISMATCH")

    baseline_prod = scorer.production_rows()
    if len(baseline_prod) != 149:
        raise RuntimeError(
            "V8138B_PRODUCTION_UNIVERSE_NOT_149:"
            + str(len(baseline_prod))
        )

    old_rows = {
        ticker(r.get("ticker")): r
        for r in read_rows(OLD_SOURCE)
        if ticker(r.get("ticker"))
    }
    new_rows = {
        ticker(r.get("ticker")): r
        for r in read_rows(NEW_SOURCE)
        if ticker(r.get("ticker"))
    }

    current_new = set(new_rows) & set(baseline_prod)
    # Latest V8.13.7 evidence overrides any older V8.10.1 row
    # for the same ticker (notably 029780 삼성카드).
    current_old = (
        (set(old_rows) & set(baseline_prod))
        - current_new
    )

    if current_old != set(CURRENT_OLD):
        raise RuntimeError(
            "V8138B_CURRENT_V8101_OVERLAP_CHANGED:"
            + ",".join(sorted(current_old))
        )
    if current_new != set(CURRENT_NEW):
        raise RuntimeError(
            "V8138B_CURRENT_V8137_OVERLAP_CHANGED:"
            + ",".join(sorted(current_new))
        )
    if current_old & current_new:
        raise RuntimeError("V8138B_SOURCE_OVERLAP_NOT_EXPECTED")
    if len(current_old | current_new) != 8:
        raise RuntimeError("V8138B_CURRENT_SOURCE_COUNT_NOT_8")

    fin_map = {
        ticker(r.get("ticker")): r
        for r in read_rows(FIN)
        if ticker(r.get("ticker"))
    }
    corp_map = supplyaudit.fetch_corp_code_map(api_key)
    keyword_rules, relief_keywords = supplyaudit.load_supply_contract()

    audit_end = datetime.now(KST).date()
    audit_start = audit_end - timedelta(days=179)

    integrated = []

    for code in sorted(CURRENT_OLD):
        name = CURRENT_OLD[code]
        fin = fin_map.get(code)
        if not fin:
            raise RuntimeError("V8138B_FIN_MISSING:" + code)
        if fin.get("corp_identity_status") not in {
            "MATCH",
            "MATCH_NORMALIZED",
        }:
            raise RuntimeError(
                "V8138B_FIN_IDENTITY_NOT_MATCH:" + code
            )

        corp = corp_map.get(code) or {}
        if int(corp.get("exact_stock_match_count") or 0) != 1:
            raise RuntimeError(
                "V8138B_DART_STOCK_IDENTITY_NOT_UNIQUE:" + code
            )
        if str(corp.get("corp_code") or "") != str(
            fin.get("corp_code") or ""
        ):
            raise RuntimeError(
                "V8138B_CORP_CODE_CROSSCHECK_MISMATCH:" + code
            )

        fresh = audit_current_supply(
            code,
            name,
            corp["corp_code"],
            corp["corp_name"],
            keyword_rules,
            relief_keywords,
            api_key,
            audit_start,
            audit_end,
        )
        integrated.append(fresh)
        time.sleep(0.05)

    for code in sorted(CURRENT_NEW):
        name = CURRENT_NEW[code]
        r = new_rows[code]
        if r.get("name") != name:
            raise RuntimeError("V8138B_V8137_NAME_MISMATCH:" + code)
        if r.get("source_status") != "SOURCE_ONLY_READY":
            raise RuntimeError(
                "V8138B_V8137_SOURCE_NOT_READY:" + code
            )
        if r.get("supply_status") != "OK":
            raise RuntimeError(
                "V8138B_V8137_SUPPLY_NOT_OK:" + code
            )
        if r.get("supply_level") not in {
            "없음",
            "주의",
            "경계",
            "위험",
        }:
            raise RuntimeError(
                "V8138B_V8137_LEVEL_BAD:" + code
            )

        integrated.append({
            "ticker": code,
            "name": name,
            "source_origin": "V8137_CURRENT_SOURCE",
            "source_status": "SOURCE_ONLY_READY",
            "source_version": VERSION,
            "source_classification": r.get(
                "source_classification"
            ) or "",
            "corp_code": r.get("corp_code") or "",
            "corp_name_dart": r.get("corp_name_dart") or "",
            "audit_start_date": r.get("audit_start_date") or "",
            "audit_end_date": r.get("audit_end_date") or "",
            "requested_lookback_days": r.get(
                "requested_lookback_days"
            ) or "",
            "chunk_count": r.get("chunk_count") or "",
            "dart_list_api_calls": r.get(
                "dart_list_api_calls"
            ) or "",
            "dart_report_count": r.get("dart_report_count") or "",
            "risk_report_count": r.get("risk_report_count") or "",
            "supply_status": "OK",
            "supply_level": r.get("supply_level") or "",
            "risk_keywords": r.get("risk_keywords") or "",
            "latest_risk_report_date": r.get(
                "latest_risk_report_date"
            ) or "",
            "latest_risk_report_name": r.get(
                "latest_risk_report_name"
            ) or "",
            "latest_risk_rcept_no": r.get(
                "latest_risk_rcept_no"
            ) or "",
            "relief_report_match_count": r.get(
                "relief_report_match_count"
            ) or "",
            "evidence_reports_json": r.get(
                "evidence_reports_json"
            ) or "[]",
            "chunk_summaries_json": r.get(
                "chunk_summaries_json"
            ) or "[]",
            "evidence_ref": r.get("evidence_ref") or "",
        })

    if len(integrated) != 8:
        raise RuntimeError(
            "V8138B_INTEGRATED_SOURCE_COUNT_NOT_8"
        )
    if {r["ticker"] for r in integrated} != set(ALL_TARGETS):
        raise RuntimeError("V8138B_INTEGRATED_SOURCE_SET_MISMATCH")
    if any(r["supply_status"] != "OK" for r in integrated):
        raise RuntimeError("V8138B_INTEGRATED_STATUS_NOT_OK")

    fields = list(integrated[0].keys())
    write_rows(SOURCE_OUT, integrated, fields)

    shadow_prod = copy.deepcopy(baseline_prod)
    for src in integrated:
        code = src["ticker"]
        analysis = copy.deepcopy(
            shadow_prod[code].get("analysis") or {}
        )
        if analysis.get("supply_status") != "LIMITED":
            raise RuntimeError(
                "V8138B_BASE_STATUS_NOT_LIMITED:" + code
            )
        if analysis.get("supply_level") != "없음":
            raise RuntimeError(
                "V8138B_BASE_LEVEL_NOT_NONE:" + code
            )
        analysis["supply_status"] = "OK"
        analysis["supply_level"] = src["supply_level"]
        analysis["supply_keywords"] = src["risk_keywords"]
        shadow_prod[code]["analysis"] = analysis

    run_scorer(
        baseline_prod,
        BASE_CSV,
        BASE_JSON,
        BASE_LOG,
        BASE_DOC,
    )
    run_scorer(
        shadow_prod,
        CAND_CSV,
        CAND_JSON,
        CAND_LOG,
        CAND_DOC,
    )

    base = {
        ticker(r.get("ticker")): r
        for r in read_rows(BASE_CSV)
    }
    cand = {
        ticker(r.get("ticker")): r
        for r in read_rows(CAND_CSV)
    }

    if set(base) != set(cand):
        raise RuntimeError("V8138B_SCORER_UNIVERSE_CHANGED")

    bsum = read_json(BASE_JSON)
    csum = read_json(CAND_JSON)
    b_ready = int(bsum.get("ready_count") or 0)
    b_limited = int(bsum.get("limited_count") or 0)
    c_ready = int(csum.get("ready_count") or 0)
    c_limited = int(csum.get("limited_count") or 0)
    b_blockers = sum(
        int(r.get("missing_component_count") or 0)
        for r in base.values()
    )
    c_blockers = sum(
        int(r.get("missing_component_count") or 0)
        for r in cand.values()
    )

    if (b_ready, b_limited, b_blockers) != (23, 126, 732):
        raise RuntimeError(
            f"V8138B_BASELINE_CHANGED:{b_ready}:{b_limited}:{b_blockers}"
        )
    if (c_ready, c_limited, c_blockers) != (27, 122, 724):
        raise RuntimeError(
            f"V8138B_CANDIDATE_NOT_27_122_724:"
            f"{c_ready}:{c_limited}:{c_blockers}"
        )

    changed = []
    non_target_changed = []
    existing_ready_changed = []
    removed_supply = 0
    newly_ready = []

    for code in sorted(base):
        b = base[code]
        c = cand[code]
        if stable(b) != stable(c):
            changed.append(code)
            if code not in ALL_TARGETS:
                non_target_changed.append(code)

        if b.get("score_status") == "READY" and stable(b) != stable(c):
            existing_ready_changed.append(code)

        bm = split_missing(b.get("missing_components"))
        cm = split_missing(c.get("missing_components"))
        if SUPPLY_REASON in bm and SUPPLY_REASON not in cm:
            removed_supply += 1

        if (
            b.get("score_status") == "LIMITED"
            and c.get("score_status") == "READY"
        ):
            newly_ready.append(code)

    if set(changed) != set(ALL_TARGETS):
        raise RuntimeError(
            "V8138B_CHANGED_ROW_SET_NOT_8:"
            + ",".join(changed)
        )
    if non_target_changed:
        raise RuntimeError(
            "V8138B_NON_TARGET_DRIFT:"
            + ",".join(non_target_changed)
        )
    if existing_ready_changed:
        raise RuntimeError(
            "V8138B_EXISTING_READY_CHANGED:"
            + ",".join(existing_ready_changed)
        )
    if removed_supply != 8:
        raise RuntimeError(
            "V8138B_SUPPLY_REASON_REMOVED_NOT_8:"
            + str(removed_supply)
        )
    if set(newly_ready) != set(CURRENT_NEW):
        raise RuntimeError(
            "V8138B_NEWLY_READY_SET_MISMATCH:"
            + ",".join(newly_ready)
        )

    for code in CURRENT_OLD:
        if cand[code].get("score_status") != "LIMITED":
            raise RuntimeError(
                "V8138B_OLD_SOURCE_TARGET_UNEXPECTED_READY:" + code
            )
        if SUPPLY_REASON in split_missing(
            cand[code].get("missing_components")
        ):
            raise RuntimeError(
                "V8138B_OLD_SOURCE_SUPPLY_REASON_REMAINS:" + code
            )

    compare_rows = []
    source_map = {r["ticker"]: r for r in integrated}
    for code in sorted(ALL_TARGETS):
        b = base[code]
        c = cand[code]
        src = source_map[code]
        compare_rows.append({
            "ticker": code,
            "name": ALL_TARGETS[code],
            "source_origin": src["source_origin"],
            "source_classification": src["source_classification"],
            "supply_level": src["supply_level"],
            "baseline_status": b.get("score_status") or "",
            "candidate_status": c.get("score_status") or "",
            "baseline_missing_components": b.get(
                "missing_components"
            ) or "",
            "candidate_missing_components": c.get(
                "missing_components"
            ) or "",
            "baseline_score_total": b.get("score_total") or "",
            "candidate_score_total": c.get("score_total") or "",
        })
    write_rows(COMPARE_OUT, compare_rows)

    class_counts = Counter(
        r["source_classification"] for r in integrated
    )
    level_counts = Counter(
        r["supply_level"] for r in integrated
    )

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(
            timespec="seconds"
        ),
        "status": "STAGED_CANDIDATE_REGRESSION_PASS",
        "policy_version": POLICY_VERSION,
        "supply_policy_version": SUPPLY_POLICY_VERSION,
        "v8137_version": V8137_VERSION,
        "v8137_result_commit": V8137_RESULT_COMMIT,
        "current_scorer_universe_count": 149,
        "source_candidate_count": 8,
        "source_candidate_tickers": sorted(ALL_TARGETS),
        "v8101_current_overlap_reaudited_count": 4,
        "v8101_current_overlap_reaudited_tickers": sorted(CURRENT_OLD),
        "latest_source_precedence_excluded_from_v8101": sorted(
            set(old_rows) & current_new
        ),
        "v8137_current_source_count": 4,
        "v8137_current_source_tickers": sorted(CURRENT_NEW),
        "classification_counts": dict(class_counts),
        "supply_level_counts": dict(level_counts),
        "baseline_ready_count": b_ready,
        "baseline_limited_count": b_limited,
        "candidate_ready_count": c_ready,
        "candidate_limited_count": c_limited,
        "ready_delta": c_ready - b_ready,
        "newly_ready_count": len(newly_ready),
        "newly_ready_tickers": sorted(newly_ready),
        "baseline_blocker_occurrences": b_blockers,
        "candidate_blocker_occurrences": c_blockers,
        "blocker_occurrences_reduced_by": b_blockers - c_blockers,
        "supply_reason_removed_count": removed_supply,
        "changed_score_row_count": len(changed),
        "changed_score_tickers": sorted(changed),
        "non_target_score_row_changed_count": 0,
        "existing_ready_score_row_changed_count": 0,
        "hard_guards": {
            "production_api_modified": False,
            "production_supply_status_overridden": False,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_ocf_cache_modified": False,
            "production_price_elasticity_cache_modified": False,
            "production_investment_score_written": False,
            "scoring_policy_modified": False,
            "supply_policy_modified": False,
            "issuer_mapping_guessed": False,
            "incomplete_query_promoted": False,
            "stale_v8101_rows_reused_without_reaudit": False,
        },
        "next_step": "CONTROLLED_PRODUCTION_SUPPLY_INTEGRATION_V8139",
    }

    SUMMARY_OUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    LOG_OUT.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=STAGED_CANDIDATE_REGRESSION_PASS",
            "CURRENT_SCORER_UNIVERSE=149",
            "SOURCE_CANDIDATE_COUNT=8",
            "V8101_CURRENT_OVERLAP_REAUDITED=4",
            "LATEST_SOURCE_PRECEDENCE_EXCLUDED_FROM_V8101=029780",
            "V8137_CURRENT_SOURCE_COUNT=4",
            f"BASELINE_READY={b_ready}",
            f"BASELINE_LIMITED={b_limited}",
            f"CANDIDATE_READY={c_ready}",
            f"CANDIDATE_LIMITED={c_limited}",
            f"READY_DELTA={c_ready-b_ready}",
            f"BASELINE_BLOCKERS={b_blockers}",
            f"CANDIDATE_BLOCKERS={c_blockers}",
            f"BLOCKER_REDUCED_BY={b_blockers-c_blockers}",
            f"SUPPLY_REASON_REMOVED={removed_supply}",
            "NON_TARGET_SCORE_ROW_CHANGED=0",
            "EXISTING_READY_SCORE_ROW_CHANGED=0",
            "PRODUCTION_API_MODIFIED=false",
            "PRODUCTION_SCORE_WRITTEN=false",
            "SCORING_POLICY_MODIFIED=false",
            "SUPPLY_POLICY_MODIFIED=false",
            "STALE_V8101_ROWS_REUSED_WITHOUT_REAUDIT=false",
            "STATUS_OK=true",
            "NEXT_STEP=CONTROLLED_PRODUCTION_SUPPLY_INTEGRATION_V8139",
        ]) + "\n",
        encoding="utf-8",
    )

    DOC_OUT.parent.mkdir(parents=True, exist_ok=True)
    DOC_OUT.write_text(
        "\n".join([
            "# V8.13.8 current-universe supply source integration candidate",
            "",
            "- Integrates eight current-universe supply evidence rows.",
            "- Four V8.10.1 rows that still overlap the 149-ticker universe are re-audited on the current 180-day window before use.",
            "- Four V8.13.7 rows are reused because they were audited on the current date.",
            "- Production API remains unchanged in this stage.",
            "",
            f"- READY/LIMITED: {b_ready}/{b_limited} -> {c_ready}/{c_limited}",
            f"- Blockers: {b_blockers} -> {c_blockers}",
            f"- Supply blockers removed: {removed_supply}",
            "- Non-target score drift: 0",
            "- Existing READY score drift: 0",
            "",
            "Next: `CONTROLLED_PRODUCTION_SUPPLY_INTEGRATION_V8139`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8138B_SUPPLY_INTEGRATION_CANDIDATE=PASS")

if __name__ == "__main__":
    main()
