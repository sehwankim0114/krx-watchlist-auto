#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import investment_score_dry_run_v882 as base

VERSION = "2026-09-15-v8.9.5-v888-plus-v894-da-extension-dry-run"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
BASE_V882_VERSION = "2026-09-13-v8.8.2-investment-score-dry-run-gate-reconciliation"
V888_VERSION = "2026-09-15-v8.8.8-freeze-xbrl-da-source-layer"
V894_VERSION = "2026-09-15-v8.9.4-freeze-v893-da-source-extension"
V889_VERSION = "2026-09-15-v8.8.9-investment-score-da-dry-run-recheck"

ROOT = Path(".")
V888_CSV = ROOT / "latest/investment_score_da_source_v888.csv"
V888_JSON = ROOT / "latest/investment_score_da_source_v888_summary_latest.json"
V894_CSV = ROOT / "latest/investment_score_da_source_extension_v894.csv"
V894_JSON = ROOT / "latest/investment_score_da_source_extension_v894_summary_latest.json"
BASELINE_CSV = ROOT / "latest/investment_score_v880_dry_run_v889_latest.csv"
BASELINE_JSON = ROOT / "latest/investment_score_v880_dry_run_v889_summary_latest.json"
RAW = ROOT / "latest/investment_score_source_cache_latest.csv"

SHADOW_RAW = Path("/tmp/investment_score_source_cache_v895_shadow.csv")

OUT_CSV = ROOT / "latest/investment_score_v880_dry_run_v895_latest.csv"
OUT_JSON = ROOT / "latest/investment_score_v880_dry_run_v895_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_v880_dry_run_v895_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_v880_dry_run_v895.md"

DEP_ID = "ifrs-full_AdjustmentsForDepreciationExpense"
AMO_ID = "ifrs-full_AdjustmentsForAmortisationExpense"
TARGET = "002450"
TARGET_PRIOR_BLOCKER = "EV/EBITDA:EV_EBITDA_INPUT:OK:NO_EXACT_CANDIDATE"

def ticker(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def num(v):
    try:
        s = str(v or "").strip().replace(",", "")
        return None if not s else float(s)
    except Exception:
        return None

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def load_combined_da_source():
    s888 = read_json(V888_JSON)
    s894 = read_json(V894_JSON)

    if s888.get("version") != V888_VERSION:
        raise RuntimeError("V888_VERSION_MISMATCH")
    if s888.get("status") != "SOURCE_ONLY_READY":
        raise RuntimeError("V888_STATUS_NOT_READY")
    if int(s888.get("source_only_ready_count") or 0) != 66:
        raise RuntimeError("V888_SOURCE_COUNT_NOT_66")

    if s894.get("version") != V894_VERSION:
        raise RuntimeError("V894_VERSION_MISMATCH")
    if s894.get("status") != "SOURCE_EXTENSION_ONLY_READY":
        raise RuntimeError("V894_STATUS_NOT_READY")
    if int(s894.get("extension_source_count") or 0) != 1:
        raise RuntimeError("V894_EXTENSION_COUNT_NOT_1")
    if s894.get("extension_tickers") != [TARGET]:
        raise RuntimeError("V894_EXTENSION_TICKER_MISMATCH")
    if int(s894.get("combined_source_count_if_shadow_merged") or 0) != 67:
        raise RuntimeError("V894_COMBINED_COUNT_NOT_67")

    base_rows = read_csv(V888_CSV)
    ext_rows = read_csv(V894_CSV)

    if len(base_rows) != 66:
        raise RuntimeError(f"V888_ROW_COUNT:{len(base_rows)}")
    if len(ext_rows) != 1:
        raise RuntimeError(f"V894_ROW_COUNT:{len(ext_rows)}")
    if ticker(ext_rows[0].get("ticker")) != TARGET:
        raise RuntimeError("V894_ROW_TARGET_MISMATCH")

    combined = list(base_rows) + list(ext_rows)
    codes = [ticker(r.get("ticker")) for r in combined]
    if len(codes) != 67 or len(set(codes)) != 67:
        raise RuntimeError("V895_COMBINED_SOURCE_DUPLICATE_OR_COUNT_MISMATCH")
    if TARGET in {ticker(r.get("ticker")) for r in base_rows}:
        raise RuntimeError("V895_TARGET_ALREADY_IN_V888")

    return combined

def build_shadow_raw():
    source_rows = load_combined_da_source()

    raw_targets = {}
    preferred_inheritance = {}

    for src in source_rows:
        code = ticker(src.get("ticker"))
        if not code:
            raise RuntimeError("V895_SOURCE_WITHOUT_TICKER")

        evidence = str(src.get("evidence_ref") or "")
        raw_code = code
        marker = "#PREFERRED_COMMON:"

        if marker in evidence:
            inherited = ticker(evidence.split(marker, 1)[1].split("#", 1)[0])
            if not inherited:
                raise RuntimeError(
                    f"V895_INVALID_PREFERRED_COMMON_REF:{code}:{evidence}"
                )
            raw_code = inherited
            preferred_inheritance[code] = raw_code

        dep = num(src.get("depreciation_value"))
        amo = num(src.get("amortisation_value"))
        if dep is None and amo is None:
            raise RuntimeError(f"V895_SOURCE_WITHOUT_DA_VALUE:{code}")

        signature = (dep, amo)
        if raw_code in raw_targets:
            prior = raw_targets[raw_code]
            if prior["signature"] != signature:
                raise RuntimeError(
                    f"V895_SHARED_RAW_DA_CONFLICT:{raw_code}:"
                    f"{prior['source_tickers']}:{code}"
                )
            prior["source_tickers"].append(code)
        else:
            raw_targets[raw_code] = {
                "signature": signature,
                "source_tickers": [code],
            }

    if preferred_inheritance != {"003495": "003490"}:
        raise RuntimeError(
            "V895_PREFERRED_INHERITANCE_UNEXPECTED:" +
            json.dumps(
                preferred_inheritance,
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    if TARGET not in raw_targets:
        raise RuntimeError("V895_TARGET_NOT_IN_RAW_TARGETS")

    raw_rows = read_csv(RAW)
    if not raw_rows:
        raise RuntimeError("RAW_SOURCE_EMPTY")

    fields = list(raw_rows[0].keys())
    if "depreciation_amortization_candidates_json" not in fields:
        raise RuntimeError("RAW_DA_FIELD_MISSING")

    seen = set()
    patched_ready = 0
    patched_nonready = 0

    for row in raw_rows:
        code = ticker(row.get("ticker"))
        target = raw_targets.get(code)
        if not target:
            continue

        dep, amo = target["signature"]
        candidates = []
        if dep is not None:
            candidates.append({
                "account_id": DEP_ID,
                "account_nm": "validated exact depreciation source",
                "amount": dep,
            })
        if amo is not None:
            candidates.append({
                "account_id": AMO_ID,
                "account_nm": "validated exact amortisation source",
                "amount": amo,
            })

        row["depreciation_amortization_candidates_json"] = json.dumps(
            candidates,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        seen.add(code)

        if row.get("source_cache_status") == "READY_RAW_SOURCE":
            patched_ready += 1
        else:
            patched_nonready += 1

    missing = sorted(set(raw_targets) - seen)
    if missing:
        raise RuntimeError(
            "V895_RAW_TARGET_MISSING:" + ",".join(missing)
        )

    if TARGET not in seen:
        raise RuntimeError("V895_TARGET_RAW_NOT_PATCHED")

    write_csv(SHADOW_RAW, raw_rows, fields)

    return {
        "combined_source_count": len(source_rows),
        "shadow_unique_raw_target_count": len(raw_targets),
        "shadow_patched_ready_raw_count": patched_ready,
        "shadow_patched_nonready_raw_count": patched_nonready,
        "preferred_inheritance_count": len(preferred_inheritance),
        "preferred_inheritance": preferred_inheritance,
    }

def count_ev_blockers(rows):
    n = 0
    for r in rows:
        parts = str(r.get("missing_components") or "").split(";")
        if any(p.startswith("EV/EBITDA:") for p in parts if p):
            n += 1
    return n

def main():
    if base.VERSION != BASE_V882_VERSION:
        raise RuntimeError("BASE_V882_VERSION_MISMATCH")
    if base.POLICY_VERSION != POLICY_VERSION:
        raise RuntimeError("BASE_POLICY_VERSION_MISMATCH")

    baseline_summary = read_json(BASELINE_JSON)
    if baseline_summary.get("version") != V889_VERSION:
        raise RuntimeError("V889_BASELINE_VERSION_MISMATCH")
    if baseline_summary.get("status") != "DRY_RUN_ONLY":
        raise RuntimeError("V889_BASELINE_STATUS_MISMATCH")
    if int(baseline_summary.get("ready_count") or 0) != 41:
        raise RuntimeError("V889_READY_COUNT_NOT_41")
    if int(baseline_summary.get("limited_count") or 0) != 71:
        raise RuntimeError("V889_LIMITED_COUNT_NOT_71")

    old_rows = read_csv(BASELINE_CSV)
    if len(old_rows) != 112:
        raise RuntimeError(f"V889_ROW_COUNT:{len(old_rows)}")
    old_map = {ticker(r.get("ticker")): r for r in old_rows}

    target_before = old_map.get(TARGET)
    if not target_before:
        raise RuntimeError("V895_TARGET_MISSING_FROM_V889")
    if target_before.get("score_status") != "LIMITED":
        raise RuntimeError(
            f"V895_TARGET_PRIOR_STATUS:{target_before.get('score_status')}"
        )
    if int(target_before.get("missing_component_count") or 0) != 1:
        raise RuntimeError(
            "V895_TARGET_PRIOR_MISSING_COUNT_NOT_1"
        )
    if target_before.get("missing_components") != TARGET_PRIOR_BLOCKER:
        raise RuntimeError(
            "V895_TARGET_PRIOR_BLOCKER_MISMATCH:" +
            str(target_before.get("missing_components") or "")
        )

    shadow_stats = build_shadow_raw()

    base.VERSION = VERSION
    base.RAW = SHADOW_RAW
    base.OUT_CSV = OUT_CSV
    base.OUT_JSON = OUT_JSON
    base.OUT_LOG = OUT_LOG
    base.OUT_DOC = OUT_DOC

    rc = base.main()
    if rc not in (None, 0):
        raise RuntimeError(f"BASE_SCORER_FAILED:{rc}")

    new_summary = read_json(OUT_JSON)
    new_rows = read_csv(OUT_CSV)

    if len(new_rows) != 112:
        raise RuntimeError(f"V895_ROW_COUNT:{len(new_rows)}")

    new_map = {ticker(r.get("ticker")): r for r in new_rows}
    if set(new_map) != set(old_map):
        raise RuntimeError("V895_TICKER_UNIVERSE_CHANGED")

    target_after = new_map[TARGET]

    # The only shadow-input delta vs V8.8.9 is the validated D&A extension
    # for 002450. Every other scorer output row must therefore be identical.
    other_changed = []
    for code in sorted(old_map):
        if code == TARGET:
            continue
        if old_map[code] != new_map[code]:
            other_changed.append(code)
    if other_changed:
        raise RuntimeError(
            "V895_NON_TARGET_ROW_CHANGED:" + ",".join(other_changed)
        )

    old_ready = {
        k for k, r in old_map.items()
        if r.get("score_status") == "READY"
    }
    new_ready = {
        k for k, r in new_map.items()
        if r.get("score_status") == "READY"
    }
    newly_ready = sorted(new_ready - old_ready)
    lost_ready = sorted(old_ready - new_ready)

    if lost_ready:
        raise RuntimeError(
            "V895_READY_REGRESSION:" + ",".join(lost_ready)
        )
    if any(code != TARGET for code in newly_ready):
        raise RuntimeError(
            "V895_UNEXPECTED_NEW_READY:" + ",".join(newly_ready)
        )

    existing_ready_score_changes = []
    for code in sorted(old_ready & new_ready):
        if old_map[code].get("score_total") != new_map[code].get("score_total"):
            existing_ready_score_changes.append(code)
    if existing_ready_score_changes:
        raise RuntimeError(
            "V895_EXISTING_READY_SCORE_CHANGED:" +
            ",".join(existing_ready_score_changes)
        )

    target_became_ready = target_after.get("score_status") == "READY"
    target_remaining_missing = str(
        target_after.get("missing_components") or ""
    )
    target_score = num(target_after.get("score_total"))

    ev_before = count_ev_blockers(old_rows)
    ev_after = count_ev_blockers(new_rows)

    top_missing = Counter()
    for r in new_rows:
        for item in str(r.get("missing_components") or "").split(";"):
            if item:
                top_missing[item] += 1

    new_summary["version"] = VERSION
    new_summary["status"] = "DRY_RUN_ONLY"
    new_summary["source_recheck"] = {
        "base_scorer_version": BASE_V882_VERSION,
        "baseline_v889_version": V889_VERSION,
        "v888_da_source_version": V888_VERSION,
        "v894_extension_version": V894_VERSION,
        "base_v888_source_count": 66,
        "v894_extension_source_count": 1,
        "combined_source_count": shadow_stats["combined_source_count"],
        "shadow_unique_raw_target_count":
            shadow_stats["shadow_unique_raw_target_count"],
        "shadow_patched_ready_raw_count":
            shadow_stats["shadow_patched_ready_raw_count"],
        "shadow_patched_nonready_raw_count":
            shadow_stats["shadow_patched_nonready_raw_count"],
        "preferred_inheritance_count":
            shadow_stats["preferred_inheritance_count"],
        "preferred_inheritance":
            shadow_stats["preferred_inheritance"],
        "baseline_ready_count": len(old_ready),
        "new_ready_count": len(new_ready),
        "ready_delta": len(new_ready) - len(old_ready),
        "newly_ready_tickers": newly_ready,
        "lost_ready_tickers": lost_ready,
        "non_target_row_changed_count": len(other_changed),
        "existing_ready_score_changed_count":
            len(existing_ready_score_changes),
        "target_ticker": TARGET,
        "target_status_before": target_before.get("score_status"),
        "target_status_after": target_after.get("score_status"),
        "target_became_ready": target_became_ready,
        "target_score_after": target_score,
        "target_score_band_after": target_after.get("score_band") or "",
        "target_missing_before": target_before.get("missing_components") or "",
        "target_missing_after": target_remaining_missing,
        "ev_ebitda_blocker_before": ev_before,
        "ev_ebitda_blocker_after": ev_after,
        "ev_ebitda_blocker_reduced_by": ev_before - ev_after,
    }
    new_summary["top_missing_reasons"] = top_missing.most_common(30)
    new_summary["hard_guards"] = {
        "production_api_changed": False,
        "production_investment_score_written": False,
        "scoring_policy_changed": False,
        "new_da_id_approved": False,
        "v888_source_layer_mutated": False,
        "v894_extension_mutated": False,
        "raw_source_cache_mutated": False,
        "base_v882_scorer_reused": True,
        "non_target_rows_unchanged": len(other_changed) == 0,
        "existing_ready_scores_unchanged":
            len(existing_ready_score_changes) == 0,
        "ready_regression_count": len(lost_ready),
    }
    new_summary["next_step"] = (
        "RECHECK_REMAINING_BLOCKERS_AFTER_V895_NEW_READY"
        if target_became_ready
        else "AUDIT_V895_TARGET_REMAINING_BLOCKER_BEFORE_ANY_SOURCE_CHANGE"
    )
    OUT_JSON.write_text(
        json.dumps(new_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    log = [
        f"VERSION={VERSION}",
        "STATUS=DRY_RUN_ONLY",
        f"BASE_SCORER_VERSION={BASE_V882_VERSION}",
        f"BASELINE_V889_VERSION={V889_VERSION}",
        f"V888_SOURCE_COUNT=66",
        f"V894_EXTENSION_SOURCE_COUNT=1",
        f"COMBINED_SOURCE_COUNT={shadow_stats['combined_source_count']}",
        f"SHADOW_UNIQUE_RAW_TARGET_COUNT={shadow_stats['shadow_unique_raw_target_count']}",
        f"BASELINE_READY_COUNT={len(old_ready)}",
        f"NEW_READY_COUNT={len(new_ready)}",
        f"READY_DELTA={len(new_ready)-len(old_ready)}",
        f"NEWLY_READY_TICKERS={','.join(newly_ready)}",
        f"TARGET_TICKER={TARGET}",
        f"TARGET_STATUS_BEFORE={target_before.get('score_status')}",
        f"TARGET_STATUS_AFTER={target_after.get('score_status')}",
        f"TARGET_BECAME_READY={'true' if target_became_ready else 'false'}",
        f"TARGET_SCORE_AFTER={'' if target_score is None else target_score}",
        f"TARGET_MISSING_AFTER={target_remaining_missing}",
        f"EV_EBITDA_BLOCKER_BEFORE={ev_before}",
        f"EV_EBITDA_BLOCKER_AFTER={ev_after}",
        f"EV_EBITDA_BLOCKER_REDUCED_BY={ev_before-ev_after}",
        "NON_TARGET_ROW_CHANGED_COUNT=0",
        "EXISTING_READY_SCORE_CHANGED_COUNT=0",
        "READY_REGRESSION_COUNT=0",
        "PRODUCTION_API_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "SCORING_POLICY_CHANGED=false",
        "NEW_DA_ID_APPROVED=false",
        "V888_SOURCE_LAYER_MUTATED=false",
        "V894_EXTENSION_MUTATED=false",
        "RAW_SOURCE_CACHE_MUTATED=false",
        "STATUS_OK=true",
        f"NEXT_STEP={new_summary['next_step']}",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    doc = [
        "# V8.9.5 V8.8.8 + V8.9.4 D&A extension 투자종합점수 dry-run",
        "",
        f"- 버전: `{VERSION}`",
        f"- scorer: `{BASE_V882_VERSION}` 재사용",
        f"- baseline: `{V889_VERSION}`",
        "- 상태: DRY_RUN_ONLY",
        "",
        "## 목적",
        "",
        "- V8.8.8 66종목과 V8.9.4 삼익악기 1종목을 shadow raw에서만 결합한다.",
        "- 002450의 유일한 V8.8.9 blocker였던 exact D&A 누락이 해소될 때 "
        "LIMITED → READY가 되는지 검증한다.",
        "- 002450 이외 111종목 출력은 V8.8.9와 완전히 동일해야 한다.",
        "",
        "## 안전 원칙",
        "",
        "- production API와 investment_score_100을 수정하지 않는다.",
        "- V8.8.8, V8.9.4, 원본 raw cache를 수정하지 않는다.",
        "- V8.8.2 scorer 공식·구간·가중치·threshold를 그대로 재사용한다.",
        "- 새 D&A ID를 승인하지 않는다.",
        "- READY 회귀 또는 비대상 종목 변화가 있으면 실패한다.",
        "",
    ]
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text("\n".join(doc), encoding="utf-8")

    print("V895_DA_EXTENSION_DRY_RUN=PASS")
    print("\n".join(log))

if __name__ == "__main__":
    main()
