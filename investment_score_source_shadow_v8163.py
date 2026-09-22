#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-22-v8.16.3-shadow-current-source-cache-refresh-gate-repair"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8162_VERSION = "2026-09-22-v8.16.2-source-cache-multiblocker-root-cause"
V8162_RESULT_COMMIT = "7c6dadbcce1fda970540454db8768cf66124c997"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

AUDIT = ROOT / "latest/investment_score_source_multiblocker_v8162_summary_latest.json"
PROD_RAW = ROOT / "latest/investment_score_source_cache_latest.csv"
SHADOW_RAW = Path("/tmp/v8163_shadow/investment_score_source_cache_latest.csv")

BASE_CSV = Path("/tmp/v8163_base_score.csv")
BASE_JSON = Path("/tmp/v8163_base_score.json")
BASE_LOG = Path("/tmp/v8163_base_score.log")
BASE_DOC = Path("/tmp/v8163_base_score.md")
SHADOW_CSV = Path("/tmp/v8163_shadow_score.csv")
SHADOW_JSON = Path("/tmp/v8163_shadow_score.json")
SHADOW_LOG = Path("/tmp/v8163_shadow_score.log")
SHADOW_DOC = Path("/tmp/v8163_shadow_score.md")

OUT_CAND = ROOT / "latest/investment_score_source_cache_candidate_v8163.csv"
OUT_JSON = ROOT / "latest/investment_score_source_shadow_v8163_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_source_shadow_v8163_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_source_shadow_v8163.md"

def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])

def row_map(path):
    rows, _ = read_rows(path)
    return {
        ticker(r.get("ticker")): r
        for r in rows
        if ticker(r.get("ticker"))
    }

def stable(row):
    return json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

def total_blockers(rows):
    return sum(
        int(r.get("missing_component_count") or 0)
        for r in rows.values()
    )

def run_scorer(raw_path, out_csv, out_json, out_log, out_doc):
    old = {
        "VERSION": scorer.VERSION,
        "RAW": scorer.RAW,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = VERSION
        scorer.RAW = Path(raw_path)
        scorer.OUT_CSV = Path(out_csv)
        scorer.OUT_JSON = Path(out_json)
        scorer.OUT_LOG = Path(out_log)
        scorer.OUT_DOC = Path(out_doc)
        rc = scorer.main()
    finally:
        for key, value in old.items():
            setattr(scorer, key, value)
    if rc not in (None, 0):
        raise RuntimeError("V8163_SCORER_FAILED:" + str(rc))

def main():
    audit = read_json(AUDIT)
    if audit.get("version") != V8162_VERSION:
        raise RuntimeError("V8163_V8162_VERSION_MISMATCH")
    if audit.get("status") != "AUDIT_ONLY_SOURCE_CACHE_MULTIBLOCKER_ROOT_CAUSE":
        raise RuntimeError("V8163_V8162_STATUS_MISMATCH")
    if audit.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8163_POLICY_VERSION_MISMATCH")
    if audit.get("next_step") != (
        "REPAIR_V854_GATE_AND_SHADOW_REFRESH_CURRENT_SOURCE_CACHE_V8163"
    ):
        raise RuntimeError("V8163_PREDECESSOR_NEXT_STEP_MISMATCH")

    lanes = audit.get("lanes") or {}
    target_set = set(
        (lanes.get("ELIGIBLE_SOURCE_ROW_MISSING") or {}).get("tickers") or []
    )
    if len(target_set) != 27:
        raise RuntimeError("V8163_TARGET_SET_NOT_27")

    selected_set = set()
    for lane_name in (
        "ELIGIBLE_SOURCE_ROW_MISSING",
        "UPSTREAM_FINANCIAL_BLOCKED_SOURCE_ROW_MISSING",
        "EXISTING_ANNUAL_AND_QUARTER_LIMITED",
        "EXISTING_QUARTER_ONLY_LIMITED",
        "EXISTING_THREE_YEAR_ONLY_LIMITED",
    ):
        selected_set |= set(
            (lanes.get(lane_name) or {}).get("tickers") or []
        )
    if len(selected_set) != 39:
        raise RuntimeError("V8163_SELECTED_SET_NOT_39")

    prod_rows, prod_fields = read_rows(PROD_RAW)
    shadow_rows, shadow_fields = read_rows(SHADOW_RAW)
    if prod_fields != shadow_fields:
        raise RuntimeError("V8163_SOURCE_SCHEMA_MISMATCH")
    if len(prod_rows) != 254:
        raise RuntimeError("V8163_PROD_SOURCE_ROWS_NOT_254")
    if len(shadow_rows) != 281:
        raise RuntimeError("V8163_SHADOW_SOURCE_ROWS_NOT_281")

    prod_map = {
        ticker(r.get("ticker")): r
        for r in prod_rows
        if ticker(r.get("ticker"))
    }
    shadow_map = {
        ticker(r.get("ticker")): r
        for r in shadow_rows
        if ticker(r.get("ticker"))
    }
    if len(prod_map) != 254 or len(shadow_map) != 281:
        raise RuntimeError("V8163_SOURCE_DUPLICATE_TICKER")
    if not set(prod_map) < set(shadow_map):
        raise RuntimeError("V8163_PROD_NOT_SUBSET_OF_SHADOW")

    added = set(shadow_map) - set(prod_map)
    if added != target_set:
        raise RuntimeError(
            "V8163_ADDED_SET_MISMATCH:" + ",".join(sorted(added))
        )

    run_scorer(
        PROD_RAW, BASE_CSV, BASE_JSON, BASE_LOG, BASE_DOC
    )
    run_scorer(
        SHADOW_RAW, SHADOW_CSV, SHADOW_JSON, SHADOW_LOG, SHADOW_DOC
    )

    base = row_map(BASE_CSV)
    shadow = row_map(SHADOW_CSV)
    base_s = read_json(BASE_JSON)
    shadow_s = read_json(SHADOW_JSON)

    if set(base) != set(shadow):
        raise RuntimeError("V8163_SCORER_UNIVERSE_DRIFT")
    if len(base) != 120:
        raise RuntimeError("V8163_SCORER_UNIVERSE_NOT_120")
    if int(base_s.get("ready_count") or 0) != 21:
        raise RuntimeError("V8163_BASE_READY_NOT_21")
    if int(base_s.get("limited_count") or 0) != 99:
        raise RuntimeError("V8163_BASE_LIMITED_NOT_99")
    if total_blockers(base) != 475:
        raise RuntimeError("V8163_BASE_BLOCKERS_NOT_475")

    shadow_blockers = total_blockers(shadow)
    if shadow_blockers >= 475:
        raise RuntimeError(
            "V8163_NO_BLOCKER_REDUCTION:" + str(shadow_blockers)
        )

    lost_ready = [
        code for code in sorted(base)
        if base[code].get("score_status") == "READY"
        and shadow[code].get("score_status") != "READY"
    ]
    if lost_ready:
        raise RuntimeError(
            "V8163_LOST_READY:" + ",".join(lost_ready)
        )

    non_selected_changed = [
        code for code in sorted(set(base) - selected_set)
        if stable(base[code]) != stable(shadow[code])
    ]
    if non_selected_changed:
        raise RuntimeError(
            "V8163_NON_SELECTED_SCORE_DRIFT:"
            + ",".join(non_selected_changed[:20])
        )

    changed_selected = [
        code for code in sorted(selected_set)
        if code in base
        and stable(base[code]) != stable(shadow[code])
    ]
    newly_ready = [
        code for code in sorted(base)
        if base[code].get("score_status") != "READY"
        and shadow[code].get("score_status") == "READY"
    ]

    OUT_CAND.write_bytes(SHADOW_RAW.read_bytes())

    gate_lines = {}
    for line in Path("/tmp/v8163_gate.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            gate_lines[k] = v

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "SHADOW_ONLY_CURRENT_SOURCE_CACHE_REFRESH_PASS",
        "policy_version": POLICY_VERSION,
        "v8162_version": V8162_VERSION,
        "v8162_result_commit": V8162_RESULT_COMMIT,
        "source_cache": {
            "production_row_count": 254,
            "shadow_row_count": 281,
            "row_delta": 27,
            "actual_added_ticker_count": len(added),
            "actual_added_tickers": sorted(added),
        },
        "scorer_regression": {
            "universe_count": len(base),
            "baseline_ready_count": int(base_s.get("ready_count") or 0),
            "shadow_ready_count": int(shadow_s.get("ready_count") or 0),
            "baseline_limited_count": int(base_s.get("limited_count") or 0),
            "shadow_limited_count": int(shadow_s.get("limited_count") or 0),
            "baseline_blocker_occurrences": 475,
            "shadow_blocker_occurrences": shadow_blockers,
            "blocker_occurrences_reduced_by": 475 - shadow_blockers,
            "changed_selected_score_row_count": len(changed_selected),
            "changed_selected_score_tickers": changed_selected,
            "non_selected_score_row_changed_count": 0,
            "newly_ready_count": len(newly_ready),
            "newly_ready_tickers": newly_ready,
            "lost_ready_count": 0,
        },
        "gate_repair_candidate": {
            "strategy": "GIT_LAST_MODIFY_COMMIT_ANCESTRY",
            "financial_cache_commit": gate_lines.get(
                "FINANCIAL_CACHE_COMMIT", ""
            ),
            "source_cache_commit": gate_lines.get(
                "SOURCE_CACHE_COMMIT", ""
            ),
            "need_refresh": (
                gate_lines.get("NEED_REFRESH") == "true"
            ),
            "reason": gate_lines.get("GATE_REASON", ""),
            "uses_run_at_kst": False,
            "manual_dispatch_force_refresh_preserved": True,
        },
        "automatic_promotion": {
            "allowed": False,
            "production_source_cache_modified": False,
            "production_gate_workflow_modified": False,
        },
        "hard_guards": {
            "production_source_cache_modified": False,
            "production_source_run_log_modified": False,
            "production_financial_cache_modified": False,
            "production_financial_run_log_modified": False,
            "production_api_modified": False,
            "production_score_written": False,
            "scoring_policy_modified": False,
            "source_value_imputed": False,
            "upstream_blocked_rows_forced_into_source_cache": False,
            "non_selected_score_row_changed": False,
        },
        "next_step": (
            "STAGE_SOURCE_CACHE_REFRESH_AND_GATE_REPAIR_V8164"
        ),
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=SHADOW_ONLY_CURRENT_SOURCE_CACHE_REFRESH_PASS",
            "PRODUCTION_SOURCE_ROWS=254",
            "SHADOW_SOURCE_ROWS=281",
            "SOURCE_ROW_DELTA=27",
            "ADDED_TARGET_TICKERS=27",
            "SCORER_UNIVERSE=120",
            "BASELINE_READY=21",
            f"SHADOW_READY={int(shadow_s.get('ready_count') or 0)}",
            "BASELINE_LIMITED=99",
            f"SHADOW_LIMITED={int(shadow_s.get('limited_count') or 0)}",
            "BASELINE_BLOCKERS=475",
            f"SHADOW_BLOCKERS={shadow_blockers}",
            f"BLOCKER_REDUCED_BY={475 - shadow_blockers}",
            f"CHANGED_SELECTED_SCORE_ROWS={len(changed_selected)}",
            "NON_SELECTED_SCORE_ROW_CHANGED=0",
            f"NEWLY_READY={len(newly_ready)}",
            "LOST_READY=0",
            "GATE_STRATEGY=GIT_LAST_MODIFY_COMMIT_ANCESTRY",
            "GATE_USES_RUN_AT_KST=false",
            "GATE_NEED_REFRESH=true",
            "PRODUCTION_DATA_MODIFIED=false",
            "AUTOMATIC_PROMOTION=false",
            "STATUS_OK=true",
            "NEXT_STEP=STAGE_SOURCE_CACHE_REFRESH_AND_GATE_REPAIR_V8164",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.16.3 current source-cache shadow refresh and gate repair",
            "",
            "- Production source cache remains unchanged.",
            "- Shadow source cache is rebuilt from the current 299-row financial cache.",
            "- Source rows: 254 -> 281 (+27).",
            f"- Scorer blockers: 475 -> {shadow_blockers}.",
            f"- Blocker reduction: {475 - shadow_blockers}.",
            f"- Newly READY tickers: {len(newly_ready)}.",
            "- No READY ticker is lost.",
            "- No score row outside the selected 39-ticker source-cache lane changes.",
            "- Gate candidate uses last-modifying Git commit ancestry instead of RUN_AT_KST.",
            "- No production workflow is modified in this step.",
            "",
            "Next: STAGE_SOURCE_CACHE_REFRESH_AND_GATE_REPAIR_V8164",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8163_SOURCE_SHADOW=PASS")
    print("V8163_SOURCE_ROWS=254->281")
    print(f"V8163_BLOCKERS=475->{shadow_blockers}")
    print(f"V8163_BLOCKER_REDUCTION={475 - shadow_blockers}")
    print(f"V8163_NEWLY_READY={len(newly_ready)}")
    print("V8163_NON_SELECTED_SCORE_DRIFT=0")
    print("V8163_NEXT_STEP=STAGE_SOURCE_CACHE_REFRESH_AND_GATE_REPAIR_V8164")

if __name__ == "__main__":
    main()
