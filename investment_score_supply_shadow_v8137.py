#!/usr/bin/env python3
from __future__ import annotations

import copy
import csv
import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-21-v8.13.7-freeze-current-actionable-supply-and-shadow-score"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
SUPPLY_POLICY_VERSION = "2026-07-01-v6.0-supply-status-separated"
V8136_VERSION = "2026-09-21-v8.13.6-current-actionable-supply-single-blocker-audit"
V8136_RESULT_COMMIT = "e6bdc6f98f0eb106c5c1add2a8934d4b77153421"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

AUDIT_CSV = ROOT / "latest/investment_score_supply_actionable_v8136.csv"
AUDIT_JSON = ROOT / "latest/investment_score_supply_actionable_v8136_summary_latest.json"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8134_summary_latest.json"

SOURCE_OUT = ROOT / "latest/investment_score_supply_source_v8137.csv"
COMPARE_OUT = ROOT / "latest/investment_score_supply_shadow_v8137.csv"
SUMMARY_OUT = ROOT / "latest/investment_score_supply_shadow_v8137_summary_latest.json"
LOG_OUT = ROOT / "latest/investment_score_supply_shadow_v8137_run_log_latest.txt"
DOC_OUT = ROOT / "docs/investment_score_supply_shadow_v8137.md"

BASE_CSV = Path("/tmp/v8137_baseline_score.csv")
BASE_JSON = Path("/tmp/v8137_baseline_score.json")
BASE_LOG = Path("/tmp/v8137_baseline_score.log")
BASE_DOC = Path("/tmp/v8137_baseline_score.md")
SHADOW_CSV = Path("/tmp/v8137_shadow_score.csv")
SHADOW_JSON = Path("/tmp/v8137_shadow_score.json")
SHADOW_LOG = Path("/tmp/v8137_shadow_score.log")
SHADOW_DOC = Path("/tmp/v8137_shadow_score.md")

EXPECTED = {
    "007540": ("샘표", "COMPLETE_180D_NO_POSITIVE_BURDEN", "없음"),
    "029780": ("삼성카드", "COMPLETE_180D_POSITIVE_BURDEN", "주의"),
    "084690": ("대상홀딩스", "COMPLETE_180D_POSITIVE_BURDEN", "주의"),
    "114090": ("GKL", "COMPLETE_180D_NO_POSITIVE_BURDEN", "없음"),
}
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
        raise RuntimeError("V8137_SCORER_FAILED:" + str(rc))

def main():
    for p in (AUDIT_CSV, AUDIT_JSON, BLOCK_JSON):
        if not p.is_file():
            raise RuntimeError("V8137_MISSING_INPUT:" + str(p))

    subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            V8136_RESULT_COMMIT,
            "HEAD",
        ],
        check=True,
    )

    audit = read_json(AUDIT_JSON)
    if audit.get("version") != V8136_VERSION:
        raise RuntimeError("V8137_V8136_VERSION_MISMATCH")
    if audit.get("status") != "AUDIT_ONLY_CURRENT_ACTIONABLE_SUPPLY":
        raise RuntimeError("V8137_V8136_STATUS_MISMATCH")
    if audit.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8137_POLICY_VERSION_MISMATCH")
    if audit.get("supply_policy_version") != SUPPLY_POLICY_VERSION:
        raise RuntimeError("V8137_SUPPLY_POLICY_VERSION_MISMATCH")
    if int(audit.get("target_count") or 0) != 4:
        raise RuntimeError("V8137_TARGET_COUNT_NOT_4")
    if int(audit.get("complete_180d_count") or 0) != 4:
        raise RuntimeError("V8137_COMPLETE_180D_NOT_4")
    if int(audit.get("incomplete_180d_count") or 0) != 0:
        raise RuntimeError("V8137_INCOMPLETE_NOT_ZERO")
    if int(audit.get("source_overlay_candidate_count") or 0) != 4:
        raise RuntimeError("V8137_OVERLAY_CANDIDATE_NOT_4")
    if int(audit.get("complete_180d_positive_burden_count") or 0) != 2:
        raise RuntimeError("V8137_POSITIVE_COUNT_NOT_2")
    if int(audit.get("complete_180d_no_positive_burden_count") or 0) != 2:
        raise RuntimeError("V8137_NO_POSITIVE_COUNT_NOT_2")
    if set(audit.get("source_overlay_candidate_tickers") or []) != set(EXPECTED):
        raise RuntimeError("V8137_OVERLAY_SET_MISMATCH")
    if audit.get("next_step") != "FREEZE_CURRENT_ACTIONABLE_SUPPLY_AND_SHADOW_SCORE_V8137":
        raise RuntimeError("V8137_PREDECESSOR_NEXT_STEP_MISMATCH")
    if any(bool(v) for v in (audit.get("hard_guards") or {}).values()):
        raise RuntimeError("V8137_V8136_HARD_GUARD_NOT_FALSE")

    block = read_json(BLOCK_JSON)
    if int(block.get("ready_count") or 0) != 23:
        raise RuntimeError("V8137_BLOCK_BASELINE_READY_NOT_23")
    if int(block.get("limited_count") or 0) != 126:
        raise RuntimeError("V8137_BLOCK_BASELINE_LIMITED_NOT_126")
    if int(block.get("limited_blocker_occurrences") or 0) != 732:
        raise RuntimeError("V8137_BLOCK_BASELINE_BLOCKERS_NOT_732")

    rows = read_rows(AUDIT_CSV)
    amap = {
        ticker(r.get("ticker")): r
        for r in rows
        if ticker(r.get("ticker"))
    }
    if set(amap) != set(EXPECTED):
        raise RuntimeError("V8137_AUDIT_CSV_SET_MISMATCH")

    source_rows = []
    source_fields = [
        "ticker",
        "name",
        "market",
        "source_status",
        "source_version",
        "source_classification",
        "corp_code",
        "corp_name_dart",
        "audit_start_date",
        "audit_end_date",
        "requested_lookback_days",
        "chunk_count",
        "dart_list_api_calls",
        "dart_report_count",
        "risk_report_count",
        "supply_status",
        "supply_level",
        "risk_keywords",
        "latest_risk_report_date",
        "latest_risk_report_name",
        "latest_risk_rcept_no",
        "relief_report_match_count",
        "evidence_reports_json",
        "chunk_summaries_json",
        "evidence_ref",
    ]

    for code in sorted(EXPECTED):
        name, classification, level = EXPECTED[code]
        r = amap[code]
        if r.get("name") != name:
            raise RuntimeError("V8137_NAME_MISMATCH:" + code)
        if r.get("audit_classification") != classification:
            raise RuntimeError("V8137_CLASS_MISMATCH:" + code)
        if r.get("query_complete_180d") != "TRUE":
            raise RuntimeError("V8137_QUERY_NOT_COMPLETE:" + code)
        if r.get("source_overlay_candidate") != "TRUE":
            raise RuntimeError("V8137_NOT_OVERLAY_CANDIDATE:" + code)
        if r.get("proposed_supply_status") != "OK":
            raise RuntimeError("V8137_PROPOSED_STATUS_NOT_OK:" + code)
        if r.get("proposed_supply_level") != level:
            raise RuntimeError("V8137_LEVEL_MISMATCH:" + code)

        risk_count = int(r.get("risk_report_count") or 0)
        if classification == "COMPLETE_180D_NO_POSITIVE_BURDEN":
            if risk_count != 0 or level != "없음":
                raise RuntimeError("V8137_NO_POSITIVE_INCONSISTENT:" + code)
        else:
            if risk_count <= 0 or level == "없음":
                raise RuntimeError("V8137_POSITIVE_INCONSISTENT:" + code)

        source_rows.append({
            "ticker": code,
            "name": name,
            "market": r.get("market") or "",
            "source_status": "SOURCE_ONLY_READY",
            "source_version": VERSION,
            "source_classification": classification,
            "corp_code": r.get("corp_code") or "",
            "corp_name_dart": r.get("corp_name_dart") or "",
            "audit_start_date": r.get("audit_start_date") or "",
            "audit_end_date": r.get("audit_end_date") or "",
            "requested_lookback_days": r.get("requested_lookback_days") or "",
            "chunk_count": r.get("chunk_count") or "",
            "dart_list_api_calls": r.get("dart_list_api_calls") or "",
            "dart_report_count": r.get("dart_report_count") or "",
            "risk_report_count": r.get("risk_report_count") or "",
            "supply_status": "OK",
            "supply_level": level,
            "risk_keywords": r.get("risk_keywords") or "",
            "latest_risk_report_date": r.get("latest_risk_report_date") or "",
            "latest_risk_report_name": r.get("latest_risk_report_name") or "",
            "latest_risk_rcept_no": r.get("latest_risk_rcept_no") or "",
            "relief_report_match_count": r.get("relief_report_match_count") or "",
            "evidence_reports_json": r.get("evidence_reports_json") or "[]",
            "chunk_summaries_json": r.get("chunk_summaries_json") or "[]",
            "evidence_ref": "V8136:DART_LIST_180D_EXACT_STOCK:" + code,
        })

    write_rows(SOURCE_OUT, source_rows, source_fields)

    baseline_prod = scorer.production_rows()
    if len(baseline_prod) != 149:
        raise RuntimeError(
            "V8137_PRODUCTION_UNIVERSE_NOT_149:"
            + str(len(baseline_prod))
        )
    if not set(EXPECTED) <= set(baseline_prod):
        raise RuntimeError("V8137_TARGET_NOT_IN_PRODUCTION")

    shadow_prod = copy.deepcopy(baseline_prod)
    for src in source_rows:
        code = src["ticker"]
        analysis = copy.deepcopy(
            shadow_prod[code].get("analysis") or {}
        )
        if analysis.get("supply_status") != "LIMITED":
            raise RuntimeError(
                "V8137_BASE_SUPPLY_STATUS_NOT_LIMITED:" + code
            )
        if analysis.get("supply_level") != "없음":
            raise RuntimeError(
                "V8137_BASE_SUPPLY_LEVEL_NOT_NONE:" + code
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
        SHADOW_CSV,
        SHADOW_JSON,
        SHADOW_LOG,
        SHADOW_DOC,
    )

    base_rows = {
        ticker(r.get("ticker")): r
        for r in read_rows(BASE_CSV)
    }
    shadow_rows = {
        ticker(r.get("ticker")): r
        for r in read_rows(SHADOW_CSV)
    }
    if set(base_rows) != set(shadow_rows):
        raise RuntimeError("V8137_SCORER_UNIVERSE_CHANGED")

    bsum = read_json(BASE_JSON)
    ssum = read_json(SHADOW_JSON)
    b_ready = int(bsum.get("ready_count") or 0)
    b_limited = int(bsum.get("limited_count") or 0)
    s_ready = int(ssum.get("ready_count") or 0)
    s_limited = int(ssum.get("limited_count") or 0)

    b_blockers = sum(
        int(r.get("missing_component_count") or 0)
        for r in base_rows.values()
    )
    s_blockers = sum(
        int(r.get("missing_component_count") or 0)
        for r in shadow_rows.values()
    )

    if (b_ready, b_limited, b_blockers) != (23, 126, 732):
        raise RuntimeError(
            f"V8137_BASELINE_CHANGED:{b_ready}:{b_limited}:{b_blockers}"
        )
    if (s_ready, s_limited, s_blockers) != (27, 122, 728):
        raise RuntimeError(
            f"V8137_SHADOW_NOT_27_122_728:{s_ready}:{s_limited}:{s_blockers}"
        )

    non_target_changed = []
    existing_ready_changed = []
    compare = []

    for code in sorted(base_rows):
        b = base_rows[code]
        s = shadow_rows[code]

        if code not in EXPECTED and stable(b) != stable(s):
            non_target_changed.append(code)

        if b.get("score_status") == "READY":
            if stable(b) != stable(s):
                existing_ready_changed.append(code)

    if non_target_changed:
        raise RuntimeError(
            "V8137_NON_TARGET_SCORE_DRIFT:"
            + ",".join(non_target_changed[:20])
        )
    if existing_ready_changed:
        raise RuntimeError(
            "V8137_EXISTING_READY_SCORE_CHANGED:"
            + ",".join(existing_ready_changed[:20])
        )

    for code in sorted(EXPECTED):
        b = base_rows[code]
        s = shadow_rows[code]
        bm = split_missing(b.get("missing_components"))
        sm = split_missing(s.get("missing_components"))

        if b.get("score_status") != "LIMITED":
            raise RuntimeError("V8137_BASE_TARGET_NOT_LIMITED:" + code)
        if bm != [SUPPLY_REASON]:
            raise RuntimeError(
                "V8137_BASE_TARGET_NOT_SINGLE_SUPPLY:"
                + code + ":" + "|".join(bm)
            )
        if SUPPLY_REASON in sm:
            raise RuntimeError("V8137_SUPPLY_REASON_NOT_REMOVED:" + code)
        if s.get("score_status") != "READY":
            raise RuntimeError("V8137_TARGET_NOT_NEWLY_READY:" + code)

        src = next(x for x in source_rows if x["ticker"] == code)
        compare.append({
            "ticker": code,
            "name": EXPECTED[code][0],
            "source_classification": src["source_classification"],
            "supply_level": src["supply_level"],
            "risk_keywords": src["risk_keywords"],
            "baseline_status": b.get("score_status") or "",
            "shadow_status": s.get("score_status") or "",
            "baseline_missing_components": ";".join(bm),
            "shadow_missing_components": ";".join(sm),
            "baseline_score_total": b.get("score_total") or "",
            "shadow_score_total": s.get("score_total") or "",
            "shadow_supply_points": (
                json.loads(
                    s.get("component_points_json") or "{}"
                ).get("수급·공시부담")
            ),
        })

    write_rows(COMPARE_OUT, compare)

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(
            timespec="seconds"
        ),
        "status": "SOURCE_ONLY_FROZEN_SHADOW_PASS",
        "policy_version": POLICY_VERSION,
        "supply_policy_version": SUPPLY_POLICY_VERSION,
        "v8136_version": V8136_VERSION,
        "v8136_result_commit": V8136_RESULT_COMMIT,
        "source_frozen_count": 4,
        "source_frozen_tickers": sorted(EXPECTED),
        "source_positive_burden_count": 2,
        "source_positive_burden_tickers": ["029780", "084690"],
        "source_no_positive_burden_count": 2,
        "source_no_positive_burden_tickers": ["007540", "114090"],
        "current_scorer_universe_count": 149,
        "baseline_ready_count": b_ready,
        "baseline_limited_count": b_limited,
        "shadow_ready_count": s_ready,
        "shadow_limited_count": s_limited,
        "ready_delta": s_ready - b_ready,
        "newly_ready_count": 4,
        "newly_ready_tickers": sorted(EXPECTED),
        "baseline_blocker_occurrences": b_blockers,
        "shadow_blocker_occurrences": s_blockers,
        "blocker_occurrences_reduced_by": b_blockers - s_blockers,
        "supply_reason_removed_count": 4,
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
        },
        "next_step": "STAGE_CURRENT_UNIVERSE_SUPPLY_SOURCE_INTEGRATION_V8138",
    }

    SUMMARY_OUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    LOG_OUT.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=SOURCE_ONLY_FROZEN_SHADOW_PASS",
            "SOURCE_FROZEN_COUNT=4",
            "SOURCE_POSITIVE_BURDEN_COUNT=2",
            "SOURCE_NO_POSITIVE_BURDEN_COUNT=2",
            "CURRENT_SCORER_UNIVERSE=149",
            f"BASELINE_READY={b_ready}",
            f"BASELINE_LIMITED={b_limited}",
            f"SHADOW_READY={s_ready}",
            f"SHADOW_LIMITED={s_limited}",
            f"READY_DELTA={s_ready-b_ready}",
            f"BASELINE_BLOCKERS={b_blockers}",
            f"SHADOW_BLOCKERS={s_blockers}",
            f"BLOCKER_REDUCED_BY={b_blockers-s_blockers}",
            "SUPPLY_REASON_REMOVED=4",
            "NON_TARGET_SCORE_ROW_CHANGED=0",
            "EXISTING_READY_SCORE_ROW_CHANGED=0",
            "PRODUCTION_API_MODIFIED=false",
            "PRODUCTION_SCORE_WRITTEN=false",
            "SCORING_POLICY_MODIFIED=false",
            "SUPPLY_POLICY_MODIFIED=false",
            "STATUS_OK=true",
            "NEXT_STEP=STAGE_CURRENT_UNIVERSE_SUPPLY_SOURCE_INTEGRATION_V8138",
        ]) + "\n",
        encoding="utf-8",
    )

    DOC_OUT.parent.mkdir(parents=True, exist_ok=True)
    DOC_OUT.write_text(
        "\n".join([
            "# V8.13.7 current actionable supply freeze + shadow score",
            "",
            "- Four V8.13.6 180-day complete DART supply evidence rows are frozen source-only.",
            "- 삼성카드 and 대상홀딩스 are OK/주의 from positive burden evidence.",
            "- 샘표 and GKL are OK/없음 from complete no-positive evidence.",
            "- Production API and embedded supply values remain unchanged.",
            "- Shadow scorer overlays only these four supply status/level values.",
            "",
            f"- Baseline READY/LIMITED: {b_ready}/{b_limited}",
            f"- Shadow READY/LIMITED: {s_ready}/{s_limited}",
            f"- Blockers: {b_blockers} -> {s_blockers}",
            "- Non-target score drift: 0",
            "- Existing READY score drift: 0",
            "",
            "Next: `STAGE_CURRENT_UNIVERSE_SUPPLY_SOURCE_INTEGRATION_V8138`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8137_SUPPLY_FREEZE_SHADOW=PASS")

if __name__ == "__main__":
    main()
