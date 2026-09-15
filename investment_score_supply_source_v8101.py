#!/usr/bin/env python3
from __future__ import annotations

import copy
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as base
import investment_score_dry_run_v895 as v895

VERSION = "2026-09-15-v8.10.1-freeze-complete-supply-evidence-and-dry-run"
CONTROL_VERSION = "2026-09-15-v8.10.1-control-reproduce-v895"
V8100_VERSION = "2026-09-15-v8.10.0-targeted-dart-supply-completeness-audit"
V896_VERSION = "2026-09-15-v8.9.6-investment-score-remaining-blocker-reaudit"
V895_VERSION = "2026-09-15-v8.9.5-v888-plus-v894-da-extension-dry-run"
BASE_V882_VERSION = "2026-09-13-v8.8.2-investment-score-dry-run-gate-reconciliation"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
SUPPLY_POLICY_VERSION = "2026-07-01-v6.0-supply-status-separated"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

V8100_CSV = ROOT / "latest/investment_score_supply_targeted_dart_v8100.csv"
V8100_JSON = ROOT / "latest/investment_score_supply_targeted_dart_v8100_summary_latest.json"
V896_JSON = ROOT / "latest/investment_score_remaining_blockers_v896_summary_latest.json"
V895_CSV = ROOT / "latest/investment_score_v880_dry_run_v895_latest.csv"
V895_JSON = ROOT / "latest/investment_score_v880_dry_run_v895_summary_latest.json"

SOURCE_CSV = ROOT / "latest/investment_score_supply_source_v8101.csv"
SOURCE_JSON = ROOT / "latest/investment_score_supply_source_v8101_summary_latest.json"
SOURCE_LOG = ROOT / "latest/investment_score_supply_source_v8101_run_log_latest.txt"
SOURCE_DOC = ROOT / "docs/investment_score_supply_source_v8101.md"

OUT_CSV = ROOT / "latest/investment_score_v880_dry_run_v8101_latest.csv"
OUT_JSON = ROOT / "latest/investment_score_v880_dry_run_v8101_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_v880_dry_run_v8101_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_v880_dry_run_v8101.md"

CONTROL_CSV = Path("/tmp/investment_score_v8101_control.csv")
CONTROL_JSON = Path("/tmp/investment_score_v8101_control.json")
CONTROL_LOG = Path("/tmp/investment_score_v8101_control.log")
CONTROL_DOC = Path("/tmp/investment_score_v8101_control.md")

SUPPLY_BLOCKER = "수급·공시부담:SUPPLY_LIMITED_NO_POSITIVE_EVIDENCE"
EXPECTED_SINGLE = {
    "003280",
    "063160",
    "066570",
    "071840",
    "081000",
    "086280",
    "100250",
    "286940",
}
ALLOWED_COMPLETE = {
    "COMPLETE_180D_NO_POSITIVE_BURDEN",
    "COMPLETE_180D_POSITIVE_BURDEN",
}
ALLOWED_LEVELS = {"없음", "주의", "경계", "위험"}


def ticker(value):
    text = "".join(ch for ch in str(value or "") if ch.isdigit())
    return text.zfill(6) if text else ""


def truthy(value):
    return str(value or "").strip().upper() == "TRUE"


def num(value):
    try:
        text = str(value or "").strip().replace(",", "")
        if text in {"", "-", "None", "null", "nan", "NaN"}:
            return None
        return float(text)
    except Exception:
        return None


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def missing_items(row):
    return {
        item
        for item in str(row.get("missing_components") or "").split(";")
        if item
    }


def supply_blocker_count(rows):
    return sum(SUPPLY_BLOCKER in missing_items(r) for r in rows)


def component_points(row):
    try:
        data = json.loads(str(row.get("component_points_json") or "{}"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def main():
    if base.VERSION != BASE_V882_VERSION:
        raise RuntimeError(f"BASE_V882_VERSION_MISMATCH:{base.VERSION}")
    if base.POLICY_VERSION != POLICY_VERSION:
        raise RuntimeError("BASE_POLICY_VERSION_MISMATCH")
    if v895.VERSION != V895_VERSION:
        raise RuntimeError(f"V895_MODULE_VERSION_MISMATCH:{v895.VERSION}")

    baseline_summary = read_json(V895_JSON)
    if baseline_summary.get("version") != V895_VERSION:
        raise RuntimeError("V895_SUMMARY_VERSION_MISMATCH")
    if baseline_summary.get("status") != "DRY_RUN_ONLY":
        raise RuntimeError("V895_STATUS_NOT_DRY_RUN_ONLY")
    if int(baseline_summary.get("production_unique_tickers") or 0) != 112:
        raise RuntimeError("V895_PRODUCTION_COUNT_NOT_112")
    if int(baseline_summary.get("ready_count") or 0) != 42:
        raise RuntimeError("V895_READY_COUNT_NOT_42")
    if int(baseline_summary.get("limited_count") or 0) != 70:
        raise RuntimeError("V895_LIMITED_COUNT_NOT_70")

    baseline_rows = read_csv(V895_CSV)
    if len(baseline_rows) != 112:
        raise RuntimeError(f"V895_ROW_COUNT:{len(baseline_rows)}")
    baseline_map = {ticker(r.get("ticker")): r for r in baseline_rows}
    if len(baseline_map) != 112:
        raise RuntimeError("V895_TICKER_UNIVERSE_NOT_UNIQUE")
    if supply_blocker_count(baseline_rows) != 33:
        raise RuntimeError("V895_SUPPLY_BLOCKER_COUNT_NOT_33")

    v896 = read_json(V896_JSON)
    if v896.get("version") != V896_VERSION:
        raise RuntimeError("V896_VERSION_MISMATCH")
    if int(v896.get("ready_count") or 0) != 42:
        raise RuntimeError("V896_READY_COUNT_NOT_42")
    if int(v896.get("single_blocker_impact", {}).get("PRODUCTION_ANALYSIS_SUPPLY") or 0) != 8:
        raise RuntimeError("V896_SUPPLY_SINGLE_BLOCKER_COUNT_NOT_8")

    s8100 = read_json(V8100_JSON)
    if s8100.get("version") != V8100_VERSION:
        raise RuntimeError("V8100_VERSION_MISMATCH")
    if s8100.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8100_STATUS_NOT_AUDIT_ONLY")
    if s8100.get("supply_policy_version") != SUPPLY_POLICY_VERSION:
        raise RuntimeError("V8100_SUPPLY_POLICY_VERSION_MISMATCH")
    expected_counts = {
        "target_count": 33,
        "single_blocker_target_count": 8,
        "corp_code_exact_resolved_count": 23,
        "corp_code_unresolved_count": 10,
        "complete_180d_count": 23,
        "complete_180d_positive_burden_count": 10,
        "complete_180d_no_positive_burden_count": 13,
        "incomplete_180d_count": 0,
        "source_overlay_candidate_count": 23,
        "single_blocker_complete_180d_count": 8,
        "single_blocker_positive_burden_count": 2,
        "single_blocker_no_positive_burden_count": 6,
    }
    for key, expected in expected_counts.items():
        actual = int(s8100.get(key) or 0)
        if actual != expected:
            raise RuntimeError(f"V8100_{key.upper()}:{actual}!={expected}")

    if set(s8100.get("single_blocker_targets") or []) != EXPECTED_SINGLE:
        raise RuntimeError("V8100_SINGLE_BLOCKER_TARGET_SET_MISMATCH")

    unresolved = set(s8100.get("corp_code_unresolved_tickers") or [])
    if len(unresolved) != 10:
        raise RuntimeError("V8100_UNRESOLVED_SET_NOT_10")

    guards8100 = s8100.get("hard_guards") or {}
    bad_guard = [k for k, v in guards8100.items() if v is not False]
    if bad_guard:
        raise RuntimeError("V8100_HARD_GUARD_NOT_FALSE:" + ",".join(sorted(bad_guard)))

    rows8100 = read_csv(V8100_CSV)
    if len(rows8100) != 33:
        raise RuntimeError(f"V8100_CSV_ROW_COUNT:{len(rows8100)}")
    map8100 = {ticker(r.get("ticker")): r for r in rows8100}
    if len(map8100) != 33:
        raise RuntimeError("V8100_CSV_TICKER_NOT_UNIQUE")

    expected_candidates = set(s8100.get("source_overlay_candidate_tickers") or [])
    if len(expected_candidates) != 23:
        raise RuntimeError("V8100_CANDIDATE_SET_NOT_23")

    source_rows = []
    source_fields = [
        "ticker",
        "name",
        "market",
        "source_status",
        "source_version",
        "source_classification",
        "single_blocker_ticker",
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

    for code in sorted(map8100):
        row = map8100[code]
        candidate = truthy(row.get("source_overlay_candidate"))
        classification = str(row.get("audit_classification") or "")
        complete = truthy(row.get("query_complete_180d"))

        if candidate:
            if code not in expected_candidates:
                raise RuntimeError(f"V8100_UNEXPECTED_CANDIDATE:{code}")
            if not complete:
                raise RuntimeError(f"V8100_CANDIDATE_NOT_COMPLETE:{code}")
            if classification not in ALLOWED_COMPLETE:
                raise RuntimeError(f"V8100_CANDIDATE_CLASS_INVALID:{code}:{classification}")
            if not str(row.get("corp_code") or "").strip():
                raise RuntimeError(f"V8100_CANDIDATE_CORP_CODE_MISSING:{code}")
            if int(row.get("corp_code_exact_stock_match_count") or 0) != 1:
                raise RuntimeError(f"V8100_CANDIDATE_CORP_NOT_UNIQUE:{code}")
            if str(row.get("proposed_supply_status") or "") != "OK":
                raise RuntimeError(f"V8100_CANDIDATE_STATUS_NOT_OK:{code}")

            level = str(row.get("proposed_supply_level") or "")
            if level not in ALLOWED_LEVELS:
                raise RuntimeError(f"V8100_CANDIDATE_LEVEL_INVALID:{code}:{level}")

            risk_count = int(row.get("risk_report_count") or 0)
            if classification == "COMPLETE_180D_NO_POSITIVE_BURDEN":
                if risk_count != 0 or level != "없음":
                    raise RuntimeError(f"V8100_NO_POSITIVE_INCONSISTENT:{code}")
            elif risk_count <= 0 or level == "없음":
                raise RuntimeError(f"V8100_POSITIVE_INCONSISTENT:{code}")

            source_rows.append({
                "ticker": code,
                "name": row.get("name", ""),
                "market": row.get("market", ""),
                "source_status": "SOURCE_ONLY_READY",
                "source_version": VERSION,
                "source_classification": classification,
                "single_blocker_ticker": "TRUE" if truthy(row.get("single_blocker_ticker")) else "FALSE",
                "corp_code": row.get("corp_code", ""),
                "corp_name_dart": row.get("corp_name_dart", ""),
                "audit_start_date": row.get("audit_start_date", ""),
                "audit_end_date": row.get("audit_end_date", ""),
                "requested_lookback_days": row.get("requested_lookback_days", ""),
                "chunk_count": row.get("chunk_count", ""),
                "dart_list_api_calls": row.get("dart_list_api_calls", ""),
                "dart_report_count": row.get("dart_report_count", ""),
                "risk_report_count": row.get("risk_report_count", ""),
                "supply_status": "OK",
                "supply_level": level,
                "risk_keywords": row.get("risk_keywords", ""),
                "latest_risk_report_date": row.get("latest_risk_report_date", ""),
                "latest_risk_report_name": row.get("latest_risk_report_name", ""),
                "latest_risk_rcept_no": row.get("latest_risk_rcept_no", ""),
                "relief_report_match_count": row.get("relief_report_match_count", ""),
                "evidence_reports_json": row.get("evidence_reports_json", "[]"),
                "chunk_summaries_json": row.get("chunk_summaries_json", "[]"),
                "evidence_ref": f"V8100:DART_LIST_180D_EXACT_STOCK:{code}",
            })
        else:
            if code not in unresolved:
                raise RuntimeError(f"V8100_NONCANDIDATE_NOT_UNRESOLVED:{code}")
            if classification != "CORP_CODE_EXACT_STOCK_UNRESOLVED":
                raise RuntimeError(f"V8100_UNRESOLVED_CLASS_INVALID:{code}:{classification}")
            if complete:
                raise RuntimeError(f"V8100_UNRESOLVED_MARKED_COMPLETE:{code}")
            if str(row.get("proposed_supply_status") or "").strip():
                raise RuntimeError(f"V8100_UNRESOLVED_STATUS_IMPUTED:{code}")

    source_codes = {r["ticker"] for r in source_rows}
    if source_codes != expected_candidates:
        raise RuntimeError("V8101_SOURCE_SET_MISMATCH")
    if len(source_rows) != 23:
        raise RuntimeError("V8101_SOURCE_COUNT_NOT_23")

    single_source = {r["ticker"] for r in source_rows if r["single_blocker_ticker"] == "TRUE"}
    if single_source != EXPECTED_SINGLE:
        raise RuntimeError("V8101_SINGLE_SOURCE_SET_MISMATCH")

    class_counts = Counter(r["source_classification"] for r in source_rows)
    if class_counts["COMPLETE_180D_POSITIVE_BURDEN"] != 10:
        raise RuntimeError("V8101_POSITIVE_SOURCE_COUNT_NOT_10")
    if class_counts["COMPLETE_180D_NO_POSITIVE_BURDEN"] != 13:
        raise RuntimeError("V8101_NO_POSITIVE_SOURCE_COUNT_NOT_13")

    write_csv(SOURCE_CSV, source_rows, source_fields)

    source_summary = {
        "version": VERSION,
        "v8100_version": V8100_VERSION,
        "v896_version": V896_VERSION,
        "v895_version": V895_VERSION,
        "policy_version": POLICY_VERSION,
        "supply_policy_version": SUPPLY_POLICY_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "SOURCE_ONLY_READY",
        "source_count": len(source_rows),
        "source_tickers": sorted(source_codes),
        "classification_counts": dict(sorted(class_counts.items())),
        "single_blocker_source_count": len(single_source),
        "single_blocker_source_tickers": sorted(single_source),
        "unresolved_excluded_count": len(unresolved),
        "unresolved_excluded_tickers": sorted(unresolved),
        "source_contract": {
            "corp_code_resolution": "DART_CORPCODE_EXACT_STOCK_ONLY",
            "lookback_days": 180,
            "all_chunks_complete_required": True,
            "supply_status_for_frozen_rows": "OK",
            "no_issuer_mapping_guess": True,
            "no_missing_or_incomplete_absence_imputation": True,
        },
        "automatic_production_patch": {
            "allowed": False,
            "patched_ticker_count": 0,
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "supply_policy_changed": False,
            "v8100_evidence_mutated": False,
            "unresolved_issuer_mapping_guessed": False,
            "incomplete_query_promoted": False,
        },
        "next_step": "SHADOW_DRY_RUN_ONLY_WITH_V895_BASELINE",
    }
    write_json(SOURCE_JSON, source_summary)

    source_log = [
        f"VERSION={VERSION}",
        "STATUS=SOURCE_ONLY_READY",
        f"SOURCE_COUNT={len(source_rows)}",
        f"POSITIVE_BURDEN_SOURCE_COUNT={class_counts['COMPLETE_180D_POSITIVE_BURDEN']}",
        f"NO_POSITIVE_BURDEN_SOURCE_COUNT={class_counts['COMPLETE_180D_NO_POSITIVE_BURDEN']}",
        f"SINGLE_BLOCKER_SOURCE_COUNT={len(single_source)}",
        f"UNRESOLVED_EXCLUDED_COUNT={len(unresolved)}",
        "PRODUCTION_DATA_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "ISSUER_MAPPING_GUESSED=false",
    ]
    SOURCE_LOG.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_LOG.write_text("\n".join(source_log) + "\n", encoding="utf-8")

    SOURCE_DOC.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_DOC.write_text(
        "\n".join([
            "# V8.10.1 180일 완전조회 수급 evidence source freeze",
            "",
            f"- 버전: `{VERSION}`",
            "- 상태: `SOURCE_ONLY_READY`",
            "- V8.10.0에서 180일 모든 구간이 완결된 23종목만 고정한다.",
            "- DART exact stock_code issuer가 풀리지 않은 10종목은 제외한다.",
            "- 위험공시 없음은 전 구간 완전조회일 때만 `OK/없음`으로 고정한다.",
            "- 위험공시가 확인된 종목은 기존 supply keyword contract의 실제 level을 보존한다.",
            "- production API 및 investment_score_100은 수정하지 않는다.",
            "",
        ]),
        encoding="utf-8",
    )

    # Reproduce V8.9.5 exactly before applying any supply overlay.
    shadow_stats = v895.build_shadow_raw()
    original_production_rows = base.production_rows

    base.VERSION = CONTROL_VERSION
    base.RAW = v895.SHADOW_RAW
    base.OUT_CSV = CONTROL_CSV
    base.OUT_JSON = CONTROL_JSON
    base.OUT_LOG = CONTROL_LOG
    base.OUT_DOC = CONTROL_DOC
    base.production_rows = original_production_rows

    rc = base.main()
    if rc not in (None, 0):
        raise RuntimeError(f"V8101_CONTROL_SCORER_FAILED:{rc}")

    control_rows = read_csv(CONTROL_CSV)
    control_summary = read_json(CONTROL_JSON)
    control_map = {ticker(r.get("ticker")): r for r in control_rows}
    if len(control_rows) != 112 or len(control_map) != 112:
        raise RuntimeError("V8101_CONTROL_ROW_COUNT_NOT_112")
    if set(control_map) != set(baseline_map):
        raise RuntimeError("V8101_CONTROL_TICKER_UNIVERSE_DRIFT")

    baseline_drift = [
        code for code in sorted(baseline_map)
        if baseline_map[code] != control_map[code]
    ]
    if baseline_drift:
        raise RuntimeError(
            "V8101_BASELINE_DRIFT_VS_V895:" + ",".join(baseline_drift)
        )
    if int(control_summary.get("ready_count") or 0) != 42:
        raise RuntimeError("V8101_CONTROL_READY_NOT_42")
    if int(control_summary.get("limited_count") or 0) != 70:
        raise RuntimeError("V8101_CONTROL_LIMITED_NOT_70")

    prod = original_production_rows()
    if len(prod) != 112:
        raise RuntimeError(f"V8101_PRODUCTION_COUNT:{len(prod)}")
    shadow_prod = copy.deepcopy(prod)

    overlay_audit = {}
    source_by_code = {r["ticker"]: r for r in source_rows}
    for code in sorted(source_by_code):
        if code not in shadow_prod:
            raise RuntimeError(f"V8101_SOURCE_NOT_IN_PRODUCTION:{code}")
        src = source_by_code[code]
        row = shadow_prod[code]
        analysis = copy.deepcopy(row.get("analysis") or {})
        before_status = str(analysis.get("supply_status") or "")
        before_level = str(analysis.get("supply_level") or "")
        analysis["supply_status"] = "OK"
        analysis["supply_level"] = src["supply_level"]
        row["analysis"] = analysis
        overlay_audit[code] = {
            "before_supply_status": before_status,
            "before_supply_level": before_level,
            "after_supply_status": "OK",
            "after_supply_level": src["supply_level"],
            "source_classification": src["source_classification"],
        }

    base.VERSION = VERSION
    base.RAW = v895.SHADOW_RAW
    base.OUT_CSV = OUT_CSV
    base.OUT_JSON = OUT_JSON
    base.OUT_LOG = OUT_LOG
    base.OUT_DOC = OUT_DOC
    base.production_rows = lambda: copy.deepcopy(shadow_prod)

    rc = base.main()
    base.production_rows = original_production_rows
    if rc not in (None, 0):
        raise RuntimeError(f"V8101_DRY_RUN_SCORER_FAILED:{rc}")

    after_rows = read_csv(OUT_CSV)
    after_summary = read_json(OUT_JSON)
    if len(after_rows) != 112:
        raise RuntimeError(f"V8101_AFTER_ROW_COUNT:{len(after_rows)}")
    after_map = {ticker(r.get("ticker")): r for r in after_rows}
    if set(after_map) != set(baseline_map):
        raise RuntimeError("V8101_AFTER_TICKER_UNIVERSE_CHANGED")

    non_source_changed = [
        code for code in sorted(baseline_map)
        if code not in source_codes and baseline_map[code] != after_map[code]
    ]
    if non_source_changed:
        raise RuntimeError(
            "V8101_NON_SOURCE_ROW_CHANGED:" + ",".join(non_source_changed)
        )

    source_changed = [
        code for code in sorted(source_codes)
        if baseline_map[code] != after_map[code]
    ]
    if set(source_changed) != source_codes:
        missing_change = sorted(source_codes - set(source_changed))
        raise RuntimeError(
            "V8101_SOURCE_ROW_DID_NOT_CHANGE:" + ",".join(missing_change)
        )

    old_ready = {
        code for code, row in baseline_map.items()
        if row.get("score_status") == "READY"
    }
    new_ready = {
        code for code, row in after_map.items()
        if row.get("score_status") == "READY"
    }
    newly_ready = sorted(new_ready - old_ready)
    lost_ready = sorted(old_ready - new_ready)

    if lost_ready:
        raise RuntimeError("V8101_READY_REGRESSION:" + ",".join(lost_ready))
    if set(newly_ready) != EXPECTED_SINGLE:
        raise RuntimeError(
            "V8101_NEW_READY_SET_MISMATCH:" + ",".join(newly_ready)
        )
    if len(new_ready) != 50:
        raise RuntimeError(f"V8101_READY_COUNT:{len(new_ready)}!=50")

    after_limited = 112 - len(new_ready)
    if after_limited != 62:
        raise RuntimeError(f"V8101_LIMITED_COUNT:{after_limited}!=62")

    supply_before = supply_blocker_count(baseline_rows)
    supply_after = supply_blocker_count(after_rows)
    if supply_before != 33 or supply_after != 10:
        raise RuntimeError(
            f"V8101_SUPPLY_BLOCKER_COUNT:{supply_before}->{supply_after}"
        )

    unresolved_with_blocker = {
        code for code in unresolved
        if SUPPLY_BLOCKER in missing_items(after_map[code])
    }
    if unresolved_with_blocker != unresolved:
        raise RuntimeError("V8101_UNRESOLVED_BLOCKER_SET_CHANGED")

    candidate_with_blocker = {
        code for code in source_codes
        if SUPPLY_BLOCKER in missing_items(after_map[code])
    }
    if candidate_with_blocker:
        raise RuntimeError(
            "V8101_SOURCE_STILL_SUPPLY_BLOCKED:" +
            ",".join(sorted(candidate_with_blocker))
        )

    existing_ready_score_changes = [
        code for code in sorted(old_ready & new_ready)
        if baseline_map[code].get("score_total") != after_map[code].get("score_total")
    ]
    if existing_ready_score_changes:
        raise RuntimeError(
            "V8101_EXISTING_READY_SCORE_CHANGED:" +
            ",".join(existing_ready_score_changes)
        )

    impact_rows = {}
    for code in sorted(source_codes):
        before = baseline_map[code]
        after = after_map[code]
        src = source_by_code[code]
        pts = component_points(after).get("수급·공시부담")
        impact_rows[code] = {
            "name": after.get("name", ""),
            "single_blocker_ticker": code in EXPECTED_SINGLE,
            "source_classification": src["source_classification"],
            "supply_level": src["supply_level"],
            "supply_points_after": pts,
            "status_before": before.get("score_status", ""),
            "status_after": after.get("score_status", ""),
            "missing_before": before.get("missing_components", ""),
            "missing_after": after.get("missing_components", ""),
            "score_before": num(before.get("score_total")),
            "score_after": num(after.get("score_total")),
        }

    single_ready_scores = {
        code: num(after_map[code].get("score_total"))
        for code in sorted(EXPECTED_SINGLE)
    }

    after_summary["version"] = VERSION
    after_summary["status"] = "DRY_RUN_ONLY"
    after_summary["source_recheck"] = {
        "base_scorer_version": BASE_V882_VERSION,
        "baseline_v895_version": V895_VERSION,
        "v8100_evidence_version": V8100_VERSION,
        "supply_source_version": VERSION,
        "source_count": len(source_rows),
        "positive_burden_source_count": class_counts["COMPLETE_180D_POSITIVE_BURDEN"],
        "no_positive_burden_source_count": class_counts["COMPLETE_180D_NO_POSITIVE_BURDEN"],
        "unresolved_excluded_count": len(unresolved),
        "baseline_control_exact_match": True,
        "baseline_ready_count": len(old_ready),
        "new_ready_count": len(new_ready),
        "ready_delta": len(new_ready) - len(old_ready),
        "newly_ready_tickers": newly_ready,
        "lost_ready_tickers": lost_ready,
        "single_blocker_expected_tickers": sorted(EXPECTED_SINGLE),
        "single_blocker_newly_ready_count": len(set(newly_ready) & EXPECTED_SINGLE),
        "single_blocker_scores_after": single_ready_scores,
        "supply_blocker_before": supply_before,
        "supply_blocker_after": supply_after,
        "supply_blocker_reduced_by": supply_before - supply_after,
        "remaining_supply_blocker_tickers": sorted(unresolved),
        "source_row_changed_count": len(source_changed),
        "non_source_row_changed_count": len(non_source_changed),
        "existing_ready_score_changed_count": len(existing_ready_score_changes),
        "v895_da_shadow_reproduction": shadow_stats,
        "financial_trend_v899_shadow_layered": False,
        "financial_trend_note": (
            "V8.9.9 financial earnings-trend shadow fix is intentionally not "
            "layered here; this run isolates the V8.10.1 supply source effect."
        ),
        "overlay_audit": overlay_audit,
        "source_impact": impact_rows,
    }
    after_summary["hard_guards"] = {
        "production_api_changed": False,
        "production_investment_score_written": False,
        "scoring_policy_changed": False,
        "supply_policy_changed": False,
        "v8100_evidence_mutated": False,
        "v895_baseline_mutated": False,
        "raw_source_cache_mutated": False,
        "financial_valuation_cache_mutated": False,
        "issuer_mapping_guessed": False,
        "incomplete_query_promoted": False,
        "baseline_control_exact_match": True,
        "non_source_rows_unchanged": True,
        "existing_ready_scores_unchanged": True,
        "ready_regression_count": 0,
    }
    after_summary["next_step"] = (
        "REAUDIT_REMAINING_BLOCKERS_AFTER_V8101_SUPPLY_SHADOW_"
        "THEN_KEEP_V899_FINANCIAL_FIX_SEPARATE_UNTIL_SOURCE_PATCH_VALIDATED"
    )
    write_json(OUT_JSON, after_summary)

    log = [
        f"VERSION={VERSION}",
        f"BASELINE_V895_READY={len(old_ready)}",
        f"V8101_READY={len(new_ready)}",
        f"V8101_LIMITED={after_limited}",
        f"READY_DELTA={len(new_ready) - len(old_ready)}",
        "NEWLY_READY_TICKERS=" + ",".join(newly_ready),
        f"SUPPLY_BLOCKER_BEFORE={supply_before}",
        f"SUPPLY_BLOCKER_AFTER={supply_after}",
        f"SUPPLY_BLOCKER_REDUCED_BY={supply_before - supply_after}",
        f"SOURCE_COUNT={len(source_rows)}",
        f"UNRESOLVED_EXCLUDED_COUNT={len(unresolved)}",
        "BASELINE_CONTROL_EXACT_MATCH=true",
        "NON_SOURCE_ROWS_UNCHANGED=true",
        "EXISTING_READY_SCORES_UNCHANGED=true",
        "READY_REGRESSION_COUNT=0",
        "FINANCIAL_TREND_V899_SHADOW_LAYERED=false",
        "PRODUCTION_DATA_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "STATUS_OK=true",
        "NEXT_STEP=" + after_summary["next_step"],
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    OUT_DOC.write_text(
        "\n".join([
            "# V8.10.1 수급 source-only freeze + 격리 dry-run",
            "",
            f"- 버전: `{VERSION}`",
            f"- 기준선: `{V895_VERSION}`",
            "- V8.10.0 180일 완전조회 23종목만 shadow supply source로 사용한다.",
            "- 먼저 현재 입력으로 V8.9.5 결과 112행을 정확히 재현한 뒤에만 overlay를 적용한다.",
            "- corp_code exact stock이 풀리지 않은 10종목은 그대로 LIMITED로 유지한다.",
            "- V8.9.9 earnings-trend shadow fix는 일부러 합치지 않아 수급 효과만 격리한다.",
            "- production API와 investment_score_100은 수정하지 않는다.",
            "",
            f"- READY: {len(old_ready)} → {len(new_ready)}",
            f"- LIMITED: {112-len(old_ready)} → {after_limited}",
            f"- 수급 blocker: {supply_before} → {supply_after}",
            "- 새 READY: " + ", ".join(newly_ready),
            "",
        ]),
        encoding="utf-8",
    )

    print("V8101_SUPPLY_SOURCE_AND_DRY_RUN=PASS")
    print("\n".join(log))


if __name__ == "__main__":
    main()
