#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-21-v8.12.2-freeze-price-elasticity-source-and-shadow-score"
V8121_VERSION = "2026-09-17-v8.12.1-current-actionable-price-elasticity-20d-official-recovery-audit"
V8121_RESULT_COMMIT = "a464f5f069fcdf5f22b1df6fab495fbfd010e889"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

AUDIT_CSV = ROOT / "latest/investment_score_price_elasticity_actionable_v8121.csv"
AUDIT_JSON = ROOT / "latest/investment_score_price_elasticity_actionable_v8121_summary_latest.json"
PROD_CACHE = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"

SOURCE_OUT = ROOT / "latest/investment_score_price_elasticity_source_v8122.csv"
COMPARE_OUT = ROOT / "latest/investment_score_price_elasticity_shadow_v8122.csv"
SUMMARY_OUT = ROOT / "latest/investment_score_price_elasticity_shadow_v8122_summary_latest.json"
LOG_OUT = ROOT / "latest/investment_score_price_elasticity_shadow_v8122_run_log_latest.txt"
DOC_OUT = ROOT / "docs/investment_score_price_elasticity_shadow_v8122.md"

TMP_CACHE = Path("/tmp/v8122_shadow_elasticity.csv")
BASE_CSV = Path("/tmp/v8122_baseline_score.csv")
BASE_JSON = Path("/tmp/v8122_baseline_score.json")
BASE_LOG = Path("/tmp/v8122_baseline_score.log")
BASE_DOC = Path("/tmp/v8122_baseline_score.md")
SHADOW_CSV = Path("/tmp/v8122_shadow_score.csv")
SHADOW_JSON = Path("/tmp/v8122_shadow_score.json")
SHADOW_LOG = Path("/tmp/v8122_shadow_score.log")
SHADOW_DOC = Path("/tmp/v8122_shadow_score.md")

EXPECTED = {
    "003530": "한화투자증권",
    "004800": "효성",
    "006260": "LS",
    "006800": "미래에셋증권",
    "008060": "대덕",
    "010060": "OCI홀딩스",
    "027410": "BGF",
    "034730": "SK",
}

MISSING_REASON = "하루평균 절대등락률:MISSING_ELASTICITY"


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


def run_scorer(elasticity_path, out_csv, out_json, out_log, out_doc):
    old = {
        "VERSION": scorer.VERSION,
        "ELASTICITY": scorer.ELASTICITY,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = VERSION
        scorer.ELASTICITY = Path(elasticity_path)
        scorer.OUT_CSV = Path(out_csv)
        scorer.OUT_JSON = Path(out_json)
        scorer.OUT_LOG = Path(out_log)
        scorer.OUT_DOC = Path(out_doc)
        rc = scorer.main()
    finally:
        for k, v in old.items():
            setattr(scorer, k, v)
    if rc not in (None, 0):
        raise RuntimeError(f"V8122_SCORER_FAILED:{rc}")


def stable_row(row):
    # Compare all scorer outputs. Target rows may change; non-target rows must not.
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main():
    for p in (AUDIT_CSV, AUDIT_JSON, PROD_CACHE):
        if not p.is_file():
            raise RuntimeError("V8122_MISSING_INPUT:" + str(p))

    # Exact lineage: the evidence file must descend from the actual V8.12.1 result.
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", V8121_RESULT_COMMIT, "HEAD"],
        check=True,
    )

    s8121 = read_json(AUDIT_JSON)
    if s8121.get("version") != V8121_VERSION:
        raise RuntimeError("V8122_V8121_VERSION_MISMATCH")
    if s8121.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8122_V8121_STATUS_MISMATCH")
    if s8121.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8122_POLICY_VERSION_MISMATCH")
    if int(s8121.get("target_count") or 0) != 8:
        raise RuntimeError("V8122_TARGET_COUNT_MISMATCH")
    if int(s8121.get("recoverable_count") or 0) != 8:
        raise RuntimeError("V8122_NOT_ALL_EIGHT_RECOVERABLE")
    if int(s8121.get("insufficient_count") or 0) != 0:
        raise RuntimeError("V8122_INSUFFICIENT_NOT_ZERO")
    if set(s8121.get("recoverable_tickers") or []) != set(EXPECTED):
        raise RuntimeError("V8122_RECOVERABLE_SET_MISMATCH")
    if s8121.get("basis_source") != "OFFICIAL_KRX_HISTORY_MAX_KOSPI_SESSION":
        raise RuntimeError("V8122_BASIS_SOURCE_MISMATCH")
    metric = s8121.get("metric_contract") or {}
    if int(metric.get("return_count") or 0) != 20:
        raise RuntimeError("V8122_WINDOW_NOT_20")
    if metric.get("atr_substitution_allowed") is not False:
        raise RuntimeError("V8122_ATR_SUBSTITUTION_NOT_FORBIDDEN")

    audit_rows = {ticker(r.get("ticker")): r for r in read_rows(AUDIT_CSV)}
    if set(audit_rows) != set(EXPECTED):
        raise RuntimeError("V8122_AUDIT_ROW_SET_MISMATCH")

    # Freeze source-only evidence. No production cache changes here.
    source_rows = []
    for code in sorted(EXPECTED):
        r = audit_rows[code]
        if r.get("classification") != "OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE":
            raise RuntimeError("V8122_NOT_RECOVERABLE:" + code)
        returns = json.loads(r.get("last20_returns_json") or "[]")
        dates = json.loads(r.get("last20_return_dates_json") or "[]")
        closes = json.loads(r.get("used_close_dates_json") or "[]")
        if len(returns) != 20 or len(dates) != 20 or len(closes) != 21:
            raise RuntimeError("V8122_WINDOW_EVIDENCE_BAD:" + code)

        pct = float(r["avg_daily_move_pct"])
        source_rows.append({
            "ticker": code,
            "name": EXPECTED[code],
            "basis_date": r["basis_date"],
            "basis_source": r["basis_source"],
            "window_start_date": closes[0],
            "window_end_date": closes[-1],
            "close_observation_count": 21,
            "daily_return_observation_count": 20,
            "avg_daily_move_pct": f"{pct:.2f}",
            "classification": r["classification"],
            "source": r["source"],
            "last20_return_dates_json": json.dumps(
                dates, ensure_ascii=False, separators=(",", ":")
            ),
            "last20_returns_json": json.dumps(
                returns, ensure_ascii=False, separators=(",", ":")
            ),
        })

    write_rows(SOURCE_OUT, source_rows)

    prod_rows = read_rows(PROD_CACHE)
    prod_fields = list(prod_rows[0].keys())
    prod_map = {ticker(r.get("ticker")): r for r in prod_rows if ticker(r.get("ticker"))}

    # The eight blockers should not already be READY in the production cache.
    existing_ready = sorted(
        code for code in EXPECTED
        if code in prod_map
        and str(prod_map[code].get("source_status") or "") == "READY"
        and str(prod_map[code].get("avg_daily_move_pct") or "").strip()
    )
    if existing_ready:
        raise RuntimeError(
            "V8122_PRODUCTION_CACHE_ALREADY_READY:" + ",".join(existing_ready)
        )

    shadow_map = dict(prod_map)
    for r in source_rows:
        code = r["ticker"]
        row = {field: "" for field in prod_fields}
        row.update({
            "ticker": code,
            "name": r["name"],
            "basis_date": r["basis_date"],
            "window_start_date": r["window_start_date"],
            "window_end_date": r["window_end_date"],
            "close_observation_count": "21",
            "daily_return_observation_count": "20",
            # avg_daily_move_abs intentionally blank: scorer contract uses pct only.
            "avg_daily_move_abs": "",
            "avg_daily_move_pct": r["avg_daily_move_pct"],
            "source_status": "READY",
        })
        shadow_map[code] = row

    shadow_rows = [shadow_map[k] for k in sorted(shadow_map)]
    write_rows(TMP_CACHE, shadow_rows, prod_fields)

    run_scorer(PROD_CACHE, BASE_CSV, BASE_JSON, BASE_LOG, BASE_DOC)
    run_scorer(TMP_CACHE, SHADOW_CSV, SHADOW_JSON, SHADOW_LOG, SHADOW_DOC)

    base_rows = {ticker(r.get("ticker")): r for r in read_rows(BASE_CSV)}
    shadow_score_rows = {ticker(r.get("ticker")): r for r in read_rows(SHADOW_CSV)}
    if set(base_rows) != set(shadow_score_rows):
        raise RuntimeError("V8122_SCORER_UNIVERSE_CHANGED")

    active = sorted(set(EXPECTED) & set(base_rows))
    inactive = sorted(set(EXPECTED) - set(base_rows))

    non_target_changed = []
    for code in sorted(set(base_rows) - set(EXPECTED)):
        if stable_row(base_rows[code]) != stable_row(shadow_score_rows[code]):
            non_target_changed.append(code)
    if non_target_changed:
        raise RuntimeError(
            "V8122_NON_TARGET_SCORE_DRIFT:" + ",".join(non_target_changed[:20])
        )

    compare_rows = []
    newly_ready = []
    reason_removed = []
    active_without_baseline_reason = []
    active_with_remaining = []

    for code in active:
        b = base_rows[code]
        s = shadow_score_rows[code]
        b_missing = split_missing(b.get("missing_components"))
        s_missing = split_missing(s.get("missing_components"))

        baseline_has = MISSING_REASON in b_missing
        shadow_has = MISSING_REASON in s_missing
        if not baseline_has:
            active_without_baseline_reason.append(code)
        if baseline_has and not shadow_has:
            reason_removed.append(code)
        if shadow_has:
            raise RuntimeError("V8122_ELASTICITY_REASON_NOT_REMOVED:" + code)

        if b.get("score_status") == "LIMITED" and s.get("score_status") == "READY":
            newly_ready.append(code)
        if s.get("score_status") == "LIMITED":
            active_with_remaining.append(code)

        compare_rows.append({
            "ticker": code,
            "name": EXPECTED[code],
            "active_in_current_scorer": "TRUE",
            "avg_daily_move_pct": audit_rows[code]["avg_daily_move_pct"],
            "baseline_status": b.get("score_status") or "",
            "shadow_status": s.get("score_status") or "",
            "baseline_missing_count": len(b_missing),
            "shadow_missing_count": len(s_missing),
            "elasticity_missing_before": "TRUE" if baseline_has else "FALSE",
            "elasticity_missing_after": "TRUE" if shadow_has else "FALSE",
            "baseline_missing_components": ";".join(b_missing),
            "shadow_missing_components": ";".join(s_missing),
            "baseline_score_total": b.get("score_total") or "",
            "shadow_score_total": s.get("score_total") or "",
        })

    for code in inactive:
        compare_rows.append({
            "ticker": code,
            "name": EXPECTED[code],
            "active_in_current_scorer": "FALSE",
            "avg_daily_move_pct": audit_rows[code]["avg_daily_move_pct"],
            "baseline_status": "",
            "shadow_status": "",
            "baseline_missing_count": "",
            "shadow_missing_count": "",
            "elasticity_missing_before": "",
            "elasticity_missing_after": "",
            "baseline_missing_components": "",
            "shadow_missing_components": "",
            "baseline_score_total": "",
            "shadow_score_total": "",
        })

    if active_without_baseline_reason:
        raise RuntimeError(
            "V8122_ACTIVE_TARGET_BASELINE_REASON_CHANGED:"
            + ",".join(active_without_baseline_reason)
        )
    if set(reason_removed) != set(active):
        raise RuntimeError("V8122_NOT_ALL_ACTIVE_REASONS_REMOVED")

    write_rows(COMPARE_OUT, compare_rows)

    bsum = read_json(BASE_JSON)
    ssum = read_json(SHADOW_JSON)
    baseline_ready = int(bsum.get("ready_count") or 0)
    shadow_ready = int(ssum.get("ready_count") or 0)

    base_blockers = sum(int(r.get("missing_component_count") or 0) for r in base_rows.values())
    shadow_blockers = sum(
        int(r.get("missing_component_count") or 0)
        for r in shadow_score_rows.values()
    )
    blocker_delta = base_blockers - shadow_blockers
    if blocker_delta != len(active):
        raise RuntimeError(
            f"V8122_BLOCKER_DELTA_NOT_ACTIVE_COUNT:{blocker_delta}!={len(active)}"
        )

    if shadow_ready - baseline_ready != len(newly_ready):
        raise RuntimeError("V8122_READY_DELTA_MISMATCH")

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "SOURCE_ONLY_FROZEN_SHADOW_PASS",
        "policy_version": POLICY_VERSION,
        "v8121_version": V8121_VERSION,
        "v8121_result_commit": V8121_RESULT_COMMIT,
        "source_frozen_count": 8,
        "source_frozen_tickers": sorted(EXPECTED),
        "basis_date": s8121.get("basis_date"),
        "basis_source": s8121.get("basis_source"),
        "current_scorer_universe_count": len(base_rows),
        "active_target_count": len(active),
        "active_target_tickers": active,
        "inactive_target_count": len(inactive),
        "inactive_target_tickers": inactive,
        "baseline_ready_count": baseline_ready,
        "shadow_ready_count": shadow_ready,
        "ready_delta": shadow_ready - baseline_ready,
        "newly_ready_count": len(newly_ready),
        "newly_ready_tickers": sorted(newly_ready),
        "active_remaining_limited_count": len(active_with_remaining),
        "active_remaining_limited_tickers": sorted(active_with_remaining),
        "baseline_blocker_occurrences": base_blockers,
        "shadow_blocker_occurrences": shadow_blockers,
        "blocker_occurrences_reduced_by": blocker_delta,
        "elasticity_reason_removed_count": len(reason_removed),
        "elasticity_reason_removed_tickers": sorted(reason_removed),
        "non_target_score_row_changed_count": 0,
        "hard_guards": {
            "production_price_elasticity_cache_modified": False,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_api_modified": False,
            "scoring_policy_modified": False,
            "atr_used_as_elasticity_substitute": False,
            "nonofficial_price_source_used": False,
            "inactive_target_force_inserted_into_scorer": False,
            "production_score_written": False,
        },
        "next_step": "STAGE_NARROW_PRODUCTION_PRICE_ELASTICITY_CACHE_PATCH_V8123",
    }
    SUMMARY_OUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    LOG_OUT.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=SOURCE_ONLY_FROZEN_SHADOW_PASS",
            "SOURCE_FROZEN_COUNT=8",
            f"CURRENT_SCORER_UNIVERSE={len(base_rows)}",
            f"ACTIVE_TARGET_COUNT={len(active)}",
            f"INACTIVE_TARGET_COUNT={len(inactive)}",
            f"BASELINE_READY={baseline_ready}",
            f"SHADOW_READY={shadow_ready}",
            f"READY_DELTA={shadow_ready-baseline_ready}",
            f"BLOCKER_REDUCED_BY={blocker_delta}",
            "NON_TARGET_SCORE_ROW_CHANGED_COUNT=0",
            "PRODUCTION_PRICE_ELASTICITY_CACHE_MODIFIED=false",
            "PRODUCTION_SCORE_WRITTEN=false",
            "ATR_SUBSTITUTION_USED=false",
            "NONOFFICIAL_PRICE_SOURCE_USED=false",
            "STATUS_OK=true",
            "NEXT_STEP=STAGE_NARROW_PRODUCTION_PRICE_ELASTICITY_CACHE_PATCH_V8123",
        ]) + "\n",
        encoding="utf-8",
    )

    DOC_OUT.parent.mkdir(parents=True, exist_ok=True)
    DOC_OUT.write_text(
        "\n".join([
            "# V8.12.2 price-elasticity source freeze and shadow score",
            "",
            f"- Frozen source tickers: {len(EXPECTED)}",
            f"- Current active targets: {len(active)}",
            f"- Current inactive targets: {len(inactive)}",
            f"- READY delta: {shadow_ready-baseline_ready}",
            f"- Blocker reduction: {blocker_delta}",
            "- Non-target scorer drift: 0",
            "",
            "Production price-elasticity cache is not modified in this step.",
            "ATR is not used as a substitute.",
            "",
            "Next: `STAGE_NARROW_PRODUCTION_PRICE_ELASTICITY_CACHE_PATCH_V8123`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8122_PRICE_ELASTICITY_FREEZE_SHADOW=PASS")


if __name__ == "__main__":
    main()
