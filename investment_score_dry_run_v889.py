#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import investment_score_dry_run_v882 as base

VERSION = "2026-09-15-v8.8.9-investment-score-da-dry-run-recheck"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
BASE_V882_VERSION = "2026-09-13-v8.8.2-investment-score-dry-run-gate-reconciliation"
V888_VERSION = "2026-09-15-v8.8.8-freeze-xbrl-da-source-layer"

ROOT = Path(".")
V888_CSV = ROOT / "latest/investment_score_da_source_v888.csv"
V888_JSON = ROOT / "latest/investment_score_da_source_v888_summary_latest.json"
BASELINE_CSV = ROOT / "latest/investment_score_v880_dry_run_v882_latest.csv"
BASELINE_JSON = ROOT / "latest/investment_score_v880_dry_run_v882_summary_latest.json"
RAW = ROOT / "latest/investment_score_source_cache_latest.csv"

SHADOW_RAW = Path("/tmp/investment_score_source_cache_v889_shadow.csv")

OUT_CSV = ROOT / "latest/investment_score_v880_dry_run_v889_latest.csv"
OUT_JSON = ROOT / "latest/investment_score_v880_dry_run_v889_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_v880_dry_run_v889_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_v880_dry_run_da_recheck_v889.md"

DEP_ID = "ifrs-full_AdjustmentsForDepreciationExpense"
AMO_ID = "ifrs-full_AdjustmentsForAmortisationExpense"

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

def build_shadow_raw():
    v888 = read_json(V888_JSON)
    if v888.get("version") != V888_VERSION:
        raise RuntimeError("V888_VERSION_MISMATCH")
    if v888.get("status") != "SOURCE_ONLY_READY":
        raise RuntimeError("V888_STATUS_NOT_READY")
    if v888.get("source_only_ready_count") != 66:
        raise RuntimeError("V888_SOURCE_COUNT_NOT_66")

    source_rows = read_csv(V888_CSV)
    source_map = {ticker(r.get("ticker")): r for r in source_rows}
    if len(source_map) != 66:
        raise RuntimeError(f"V888_UNIQUE_SOURCE_COUNT:{len(source_map)}")

    raw_targets = {}
    preferred_inheritance = {}

    for code, src in source_map.items():
        evidence = str(src.get("evidence_ref") or "")
        raw_code = code
        marker = "#PREFERRED_COMMON:"

        if marker in evidence:
            inherited = ticker(evidence.split(marker, 1)[1].split("#", 1)[0])
            if not inherited:
                raise RuntimeError(
                    f"V888_INVALID_PREFERRED_COMMON_REF:{code}:{evidence}"
                )
            raw_code = inherited
            preferred_inheritance[code] = raw_code

        dep = num(src.get("depreciation_value"))
        amo = num(src.get("amortisation_value"))
        if dep is None and amo is None:
            raise RuntimeError(f"V888_SOURCE_WITHOUT_DA_VALUE:{code}")

        signature = (dep, amo)

        if raw_code in raw_targets:
            prior = raw_targets[raw_code]
            if prior["signature"] != signature:
                raise RuntimeError(
                    f"V888_SHARED_RAW_DA_CONFLICT:{raw_code}:"
                    f"{prior['source_tickers']}:{code}"
                )
            prior["source_tickers"].append(code)
        else:
            raw_targets[raw_code] = {
                "signature": signature,
                "source_tickers": [code],
            }

    raw_rows = read_csv(RAW)
    if not raw_rows:
        raise RuntimeError("RAW_SOURCE_EMPTY")

    fields = list(raw_rows[0].keys())
    if "depreciation_amortization_candidates_json" not in fields:
        raise RuntimeError("RAW_DA_FIELD_MISSING")

    seen_raw_targets = set()
    patched_ready_raw_count = 0
    patched_nonready_raw_count = 0

    for row in raw_rows:
        raw_code = ticker(row.get("ticker"))
        target = raw_targets.get(raw_code)
        if not target:
            continue

        dep, amo = target["signature"]
        candidates = []

        if dep is not None:
            candidates.append({
                "account_id": DEP_ID,
                "account_nm": "V8.8.8 validated exact depreciation",
                "amount": dep,
            })

        if amo is not None:
            candidates.append({
                "account_id": AMO_ID,
                "account_nm": "V8.8.8 validated exact amortisation",
                "amount": amo,
            })

        row["depreciation_amortization_candidates_json"] = json.dumps(
            candidates,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        seen_raw_targets.add(raw_code)

        if row.get("source_cache_status") == "READY_RAW_SOURCE":
            patched_ready_raw_count += 1
        else:
            patched_nonready_raw_count += 1

    missing_raw = sorted(set(raw_targets) - seen_raw_targets)
    if missing_raw:
        raise RuntimeError(
            "V888_RAW_TARGET_MISSING_FROM_RAW:" + ",".join(missing_raw)
        )

    if preferred_inheritance != {"003495": "003490"}:
        raise RuntimeError(
            "V888_PREFERRED_INHERITANCE_UNEXPECTED:" +
            json.dumps(
                preferred_inheritance,
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    write_csv(SHADOW_RAW, raw_rows, fields)

    return {
        "v888_source_count": len(source_map),
        "shadow_unique_raw_target_count": len(raw_targets),
        "shadow_patched_ready_raw_count": patched_ready_raw_count,
        "shadow_patched_nonready_raw_count": patched_nonready_raw_count,
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
    if baseline_summary.get("version") != BASE_V882_VERSION:
        raise RuntimeError("BASELINE_SUMMARY_VERSION_MISMATCH")
    if baseline_summary.get("ready_count") != 13:
        raise RuntimeError("BASELINE_READY_COUNT_NOT_13")

    shadow_stats = build_shadow_raw()

    # Reuse the audited V8.8.2 scorer. Only the RAW input path and output
    # destinations are redirected. Scoring formulas and thresholds stay intact.
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
    old_rows = read_csv(BASELINE_CSV)

    if len(new_rows) != 112 or len(old_rows) != 112:
        raise RuntimeError(
            f"DRY_RUN_ROW_COUNT_MISMATCH:{len(old_rows)}:{len(new_rows)}"
        )

    old_map = {ticker(r.get("ticker")): r for r in old_rows}
    new_map = {ticker(r.get("ticker")): r for r in new_rows}

    old_ready = {k for k, r in old_map.items() if r.get("score_status") == "READY"}
    new_ready = {k for k, r in new_map.items() if r.get("score_status") == "READY"}
    newly_ready = sorted(new_ready - old_ready)
    lost_ready = sorted(old_ready - new_ready)

    # Existing READY scores must not move: V8.8.9 is a source-coverage recheck,
    # not a scoring-policy change.
    changed_existing_ready = []
    for code in sorted(old_ready & new_ready):
        old_score = num(old_map[code].get("score_total"))
        new_score = num(new_map[code].get("score_total"))
        if old_score != new_score:
            changed_existing_ready.append({
                "ticker": code,
                "old": old_score,
                "new": new_score,
            })
    if changed_existing_ready:
        raise RuntimeError(
            "EXISTING_READY_SCORE_CHANGED:" +
            json.dumps(changed_existing_ready, ensure_ascii=False)
        )
    if lost_ready:
        raise RuntimeError("READY_REGRESSION:" + ",".join(lost_ready))

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
        "v888_da_source_version": V888_VERSION,
        "v888_source_count": shadow_stats["v888_source_count"],
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
        "existing_ready_score_changed_count": len(changed_existing_ready),
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
        "base_v882_scorer_reused": True,
        "legacy_score_rescaled": False,
        "limited_score_total_is_null": all(
            r.get("score_total") == ""
            for r in new_rows
            if r.get("score_status") == "LIMITED"
        ),
    }
    new_summary["next_step"] = (
        "REVIEW_V889_REMAINING_BLOCKERS_BEFORE_ANY_PRODUCTION_ACTIVATION"
    )
    OUT_JSON.write_text(
        json.dumps(new_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    log = [
        f"VERSION={VERSION}",
        f"POLICY_VERSION={POLICY_VERSION}",
        f"BASE_SCORER_VERSION={BASE_V882_VERSION}",
        f"V888_DA_SOURCE_VERSION={V888_VERSION}",
        f"V888_SOURCE_COUNT={shadow_stats['v888_source_count']}",
        f"SHADOW_UNIQUE_RAW_TARGET_COUNT={shadow_stats['shadow_unique_raw_target_count']}",
        f"PREFERRED_INHERITANCE_COUNT={shadow_stats['preferred_inheritance_count']}",
        "PREFERRED_INHERITANCE_003495=003490",
        f"BASELINE_READY={len(old_ready)}",
        f"DRY_RUN_READY={len(new_ready)}",
        f"DRY_RUN_LIMITED={112-len(new_ready)}",
        f"READY_DELTA={len(new_ready)-len(old_ready)}",
        f"NEWLY_READY_COUNT={len(newly_ready)}",
        f"EV_EBITDA_BLOCKER_BEFORE={ev_before}",
        f"EV_EBITDA_BLOCKER_AFTER={ev_after}",
        f"EV_EBITDA_BLOCKER_REDUCED_BY={ev_before-ev_after}",
        "EXISTING_READY_SCORE_CHANGED_COUNT=0",
        "READY_REGRESSION_COUNT=0",
        "PRODUCTION_DATA_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "SCORING_POLICY_CHANGED=false",
        "NEW_DA_ID_APPROVED=false",
        "V888_SOURCE_LAYER_MUTATED=false",
        "STATUS=OK",
        "NEXT_STEP=REVIEW_V889_REMAINING_BLOCKERS_BEFORE_ANY_PRODUCTION_ACTIVATION",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    doc = [
        "# V8.8.9 V8.8.8 D&A source 반영 투자종합점수 dry-run 재검증",
        "",
        f"- 버전: `{VERSION}`",
        f"- 점수정책: `{POLICY_VERSION}`",
        f"- 재사용 scorer: `{BASE_V882_VERSION}`",
        f"- D&A source: `{V888_VERSION}`",
        "- 상태: DRY_RUN_ONLY",
        "",
        "## 원칙",
        "",
        "- V8.8.2의 23개 component 공식·구간·가중치를 그대로 재사용한다.",
        "- V8.8.8에서 검증된 exact D&A 66종목만 shadow raw에 반영한다.",
        "- production API에는 쓰지 않는다.",
        "- investment_score_100 production 필드에는 쓰지 않는다.",
        "- 새 D&A ID를 승인하지 않는다.",
        "- 기존 READY 종목의 점수가 달라지면 실패 처리한다.",
        "- 기존 READY가 LIMITED로 후퇴하면 실패 처리한다.",
        "",
        "## 다음 단계",
        "",
        "READY/LIMITED 변화와 EV/EBITDA blocker 감소량, 남은 결측 사유를 "
        "검토한 뒤 production 활성화 여부가 아니라 남은 blocker 해소 순서를 결정한다.",
        "",
    ]
    OUT_DOC.write_text("\n".join(doc), encoding="utf-8")

    print("V889_INVESTMENT_SCORE_DA_DRY_RUN_RECHECK=PASS")
    print("\n".join(log))

if __name__ == "__main__":
    main()

