#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as base

VERSION = "2026-09-15-v8.9.4-extend-da-source-and-rerun-dry-run"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
BASE_V882_VERSION = "2026-09-13-v8.8.2-investment-score-dry-run-gate-reconciliation"
V888_VERSION = "2026-09-15-v8.8.8-freeze-xbrl-da-source-layer"
V889_VERSION = "2026-09-15-v8.8.9-investment-score-da-dry-run-recheck"
V893_VERSION = "2026-09-15-v8.9.3-recovered-xbrl-context-audit"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

V888_CSV = ROOT / "latest/investment_score_da_source_v888.csv"
V888_JSON = ROOT / "latest/investment_score_da_source_v888_summary_latest.json"
V889_CSV = ROOT / "latest/investment_score_v880_dry_run_v889_latest.csv"
V889_JSON = ROOT / "latest/investment_score_v880_dry_run_v889_summary_latest.json"
V893_CSV = ROOT / "latest/investment_score_xbrl_recovered_context_v893.csv"
V893_JSON = ROOT / "latest/investment_score_xbrl_recovered_context_v893_summary_latest.json"
RAW = ROOT / "latest/investment_score_source_cache_latest.csv"

SOURCE_OUT_CSV = ROOT / "latest/investment_score_da_source_v894.csv"
SOURCE_OUT_JSON = ROOT / "latest/investment_score_da_source_v894_summary_latest.json"

SHADOW_RAW = Path("/tmp/investment_score_source_cache_v894_shadow.csv")
DRY_OUT_CSV = ROOT / "latest/investment_score_v880_dry_run_v894_latest.csv"
DRY_OUT_JSON = ROOT / "latest/investment_score_v880_dry_run_v894_summary_latest.json"
DRY_OUT_LOG = ROOT / "latest/investment_score_v880_dry_run_v894_run_log_latest.txt"
DRY_OUT_DOC = ROOT / "docs/investment_score_da_source_and_dry_run_v894.md"

DEP_ID = "ifrs-full_AdjustmentsForDepreciationExpense"
AMO_ID = "ifrs-full_AdjustmentsForAmortisationExpense"
TARGET_TICKER = "002450"

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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def parse_selected_facts(row):
    try:
        facts = json.loads(row.get("selected_facts_json") or "[]")
    except Exception as exc:
        raise RuntimeError(
            f"V893_SELECTED_FACTS_JSON_INVALID:{type(exc).__name__}:{exc}"
        )
    if not isinstance(facts, list):
        raise RuntimeError("V893_SELECTED_FACTS_NOT_LIST")

    values = {}
    for fact in facts:
        local = str(fact.get("local_name") or "")
        value = num(fact.get("normalized_value"))
        if local in {
            "AdjustmentsForDepreciationExpense",
            "AdjustmentsForAmortisationExpense",
        } and value is not None:
            values.setdefault(local, set()).add(value)

    dep_values = values.get("AdjustmentsForDepreciationExpense", set())
    amo_values = values.get("AdjustmentsForAmortisationExpense", set())

    if len(dep_values) != 1 or len(amo_values) != 1:
        raise RuntimeError(
            f"V893_EXACT_VALUE_NOT_UNIQUE:DEP={sorted(dep_values)}:"
            f"AMO={sorted(amo_values)}"
        )

    return next(iter(dep_values)), next(iter(amo_values))

def build_v894_source_layer():
    s888 = read_json(V888_JSON)
    s893 = read_json(V893_JSON)

    if s888.get("version") != V888_VERSION:
        raise RuntimeError("V888_VERSION_MISMATCH")
    if s888.get("status") != "SOURCE_ONLY_READY":
        raise RuntimeError("V888_STATUS_NOT_READY")
    if s888.get("source_only_ready_count") != 66:
        raise RuntimeError("V888_SOURCE_COUNT_NOT_66")

    if s893.get("version") != V893_VERSION:
        raise RuntimeError("V893_VERSION_MISMATCH")
    if s893.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V893_STATUS_MISMATCH")
    if s893.get("target_ticker") != TARGET_TICKER:
        raise RuntimeError("V893_TARGET_MISMATCH")
    if s893.get("promotion_candidate") is not True:
        raise RuntimeError("V893_NOT_PROMOTION_CANDIDATE")
    if s893.get("selection_classification") != "MATCHED_FS_MEMBER_BOTH_FACTS_UNIQUE":
        raise RuntimeError("V893_SELECTION_NOT_BOTH_UNIQUE")
    if s893.get("selected_value_conflict") is not False:
        raise RuntimeError("V893_VALUE_CONFLICT")
    if s893.get("selected_context_conflict") is not False:
        raise RuntimeError("V893_CONTEXT_CONFLICT")

    rows888 = read_csv(V888_CSV)
    if len(rows888) != 66:
        raise RuntimeError(f"V888_ROW_COUNT:{len(rows888)}")
    if TARGET_TICKER in {ticker(r.get("ticker")) for r in rows888}:
        raise RuntimeError("TARGET_ALREADY_IN_V888")

    rows893 = read_csv(V893_CSV)
    if len(rows893) != 1 or ticker(rows893[0].get("ticker")) != TARGET_TICKER:
        raise RuntimeError("V893_CSV_TARGET_MISMATCH")

    row893 = rows893[0]
    dep, amo = parse_selected_facts(row893)
    total = dep + amo
    evidence_total = num(row893.get("evidence_da_sum"))

    if evidence_total is None or abs(total - evidence_total) > 0.5:
        raise RuntimeError(
            f"V893_DA_SUM_MISMATCH:{total}:{evidence_total}"
        )

    source_fields = list(rows888[0].keys())
    expected_fields = {
        "ticker","name","market","target_year","fs_div","source_layer",
        "source_status","depreciation_value","amortisation_value","da_total",
        "approved_exact_fact_count","both_exact_facts_present","evidence_ref",
    }
    if set(source_fields) != expected_fields:
        raise RuntimeError(
            "V888_SOURCE_SCHEMA_CHANGED:" + repr(source_fields)
        )

    new_row = {
        "ticker": TARGET_TICKER,
        "name": row893.get("name") or "삼익악기",
        "market": row893.get("market") or "KOSPI",
        "target_year": row893.get("target_year") or s893.get("target_year") or "",
        "fs_div": row893.get("source_fs_div") or s893.get("source_fs_div") or "",
        "source_layer": "V893_RECOVERED_XBRL_BOTH_UNIQUE_EXACT",
        "source_status": "READY_EXACT_DA_SOURCE",
        "depreciation_value": dep,
        "amortisation_value": amo,
        "da_total": total,
        "approved_exact_fact_count": 2,
        "both_exact_facts_present": "TRUE",
        "evidence_ref": "latest/investment_score_xbrl_recovered_context_v893.csv",
    }

    rows894 = rows888 + [new_row]
    rows894.sort(key=lambda r: ticker(r.get("ticker")))

    codes = [ticker(r.get("ticker")) for r in rows894]
    if len(rows894) != 67 or len(set(codes)) != 67:
        raise RuntimeError("V894_SOURCE_UNIQUE_COUNT_MISMATCH")

    write_csv(SOURCE_OUT_CSV, rows894, source_fields)

    source_summary = {
        "version": VERSION,
        "policy_version": POLICY_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "SOURCE_ONLY_READY",
        "base_v888_version": V888_VERSION,
        "v893_evidence_version": V893_VERSION,
        "base_source_count": 66,
        "new_validated_ticker_count": 1,
        "new_validated_tickers": [TARGET_TICKER],
        "source_only_ready_count": 67,
        "new_source_details": {
            "ticker": TARGET_TICKER,
            "depreciation_value": dep,
            "amortisation_value": amo,
            "da_total": total,
            "source_fs_div": new_row["fs_div"],
            "evidence_ref": new_row["evidence_ref"],
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "new_da_id_approved": False,
            "v888_source_layer_mutated": False,
            "partial_xbrl_fact_promoted": False,
            "missing_da_assumed_zero": False,
        },
    }
    SOURCE_OUT_JSON.write_text(
        json.dumps(source_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return rows894, source_summary

def build_shadow_raw(source_rows):
    source_map = {
        ticker(r.get("ticker")): r
        for r in source_rows
        if ticker(r.get("ticker"))
    }
    if len(source_map) != 67:
        raise RuntimeError(f"V894_SOURCE_MAP_COUNT:{len(source_map)}")

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
                    f"V894_INVALID_PREFERRED_COMMON_REF:{code}:{evidence}"
                )
            raw_code = inherited
            preferred_inheritance[code] = raw_code

        dep = num(src.get("depreciation_value"))
        amo = num(src.get("amortisation_value"))
        if dep is None and amo is None:
            raise RuntimeError(f"V894_SOURCE_WITHOUT_DA_VALUE:{code}")

        signature = (dep, amo)
        if raw_code in raw_targets:
            prior = raw_targets[raw_code]
            if prior["signature"] != signature:
                raise RuntimeError(
                    f"V894_SHARED_RAW_DA_CONFLICT:{raw_code}:"
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
            "V894_PREFERRED_INHERITANCE_UNEXPECTED:" +
            json.dumps(
                preferred_inheritance,
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    raw_rows = read_csv(RAW)
    if not raw_rows:
        raise RuntimeError("RAW_SOURCE_EMPTY")

    fields = list(raw_rows[0].keys())
    if "depreciation_amortization_candidates_json" not in fields:
        raise RuntimeError("RAW_DA_FIELD_MISSING")

    seen = set()
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
                "account_nm": "validated exact depreciation",
                "amount": dep,
            })
        if amo is not None:
            candidates.append({
                "account_id": AMO_ID,
                "account_nm": "validated exact amortisation",
                "amount": amo,
            })

        row["depreciation_amortization_candidates_json"] = json.dumps(
            candidates,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        seen.add(code)

    missing = sorted(set(raw_targets) - seen)
    if missing:
        raise RuntimeError(
            "V894_RAW_TARGET_MISSING_FROM_RAW:" + ",".join(missing)
        )

    write_csv(SHADOW_RAW, raw_rows, fields)

    return {
        "source_ticker_count": len(source_map),
        "unique_raw_target_count": len(raw_targets),
        "preferred_inheritance": preferred_inheritance,
    }

def count_ev_blockers(rows):
    count = 0
    for row in rows:
        reasons = [
            x for x in str(row.get("missing_components") or "").split(";")
            if x
        ]
        if any(x.startswith("EV/EBITDA:") for x in reasons):
            count += 1
    return count

def main():
    if base.VERSION != BASE_V882_VERSION:
        raise RuntimeError("BASE_V882_VERSION_MISMATCH")
    if base.POLICY_VERSION != POLICY_VERSION:
        raise RuntimeError("BASE_POLICY_VERSION_MISMATCH")

    s889 = read_json(V889_JSON)
    if s889.get("version") != V889_VERSION:
        raise RuntimeError("V889_VERSION_MISMATCH")
    if s889.get("status") != "DRY_RUN_ONLY":
        raise RuntimeError("V889_STATUS_MISMATCH")
    if s889.get("ready_count") != 41 or s889.get("limited_count") != 71:
        raise RuntimeError(
            f"V889_READY_LIMITED_CHANGED:"
            f"{s889.get('ready_count')}:{s889.get('limited_count')}"
        )

    source_rows, source_summary = build_v894_source_layer()
    shadow_stats = build_shadow_raw(source_rows)

    base.VERSION = VERSION
    base.RAW = SHADOW_RAW
    base.OUT_CSV = DRY_OUT_CSV
    base.OUT_JSON = DRY_OUT_JSON
    base.OUT_LOG = DRY_OUT_LOG
    base.OUT_DOC = DRY_OUT_DOC

    rc = base.main()
    if rc not in (None, 0):
        raise RuntimeError(f"BASE_SCORER_FAILED:{rc}")

    new_summary = read_json(DRY_OUT_JSON)
    new_rows = read_csv(DRY_OUT_CSV)
    old_rows = read_csv(V889_CSV)

    if len(new_rows) != 112 or len(old_rows) != 112:
        raise RuntimeError(
            f"DRY_RUN_ROW_COUNT_MISMATCH:{len(old_rows)}:{len(new_rows)}"
        )

    old_map = {ticker(r.get("ticker")): r for r in old_rows}
    new_map = {ticker(r.get("ticker")): r for r in new_rows}

    old_ready = {
        code for code, row in old_map.items()
        if row.get("score_status") == "READY"
    }
    new_ready = {
        code for code, row in new_map.items()
        if row.get("score_status") == "READY"
    }

    newly_ready = sorted(new_ready - old_ready)
    lost_ready = sorted(old_ready - new_ready)

    if lost_ready:
        raise RuntimeError("READY_REGRESSION:" + ",".join(lost_ready))

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

    if newly_ready != [TARGET_TICKER]:
        raise RuntimeError(
            "UNEXPECTED_NEW_READY_SET:" + repr(newly_ready)
        )

    if len(new_ready) != 42:
        raise RuntimeError(f"V894_READY_COUNT_NOT_42:{len(new_ready)}")

    target_new = new_map.get(TARGET_TICKER) or {}
    if target_new.get("score_status") != "READY":
        raise RuntimeError("TARGET_NOT_READY_AFTER_VALIDATED_DA")

    target_score = num(target_new.get("score_total"))
    if target_score is None:
        raise RuntimeError("TARGET_READY_SCORE_MISSING")

    ev_before = count_ev_blockers(old_rows)
    ev_after = count_ev_blockers(new_rows)
    if ev_before != 31:
        raise RuntimeError(f"V889_EV_BLOCKER_BASELINE_CHANGED:{ev_before}")
    if ev_after != 30:
        raise RuntimeError(f"V894_EV_BLOCKER_NOT_30:{ev_after}")

    top_missing = Counter()
    for row in new_rows:
        for reason in str(row.get("missing_components") or "").split(";"):
            if reason:
                top_missing[reason] += 1

    new_summary["version"] = VERSION
    new_summary["status"] = "DRY_RUN_ONLY"
    new_summary["source_extension"] = {
        "base_v888_source_count": 66,
        "v894_source_count": 67,
        "new_validated_ticker": TARGET_TICKER,
        "new_validated_da_total":
            source_summary["new_source_details"]["da_total"],
        "unique_raw_target_count":
            shadow_stats["unique_raw_target_count"],
        "preferred_inheritance":
            shadow_stats["preferred_inheritance"],
    }
    new_summary["v889_comparison"] = {
        "baseline_ready_count": len(old_ready),
        "new_ready_count": len(new_ready),
        "ready_delta": len(new_ready) - len(old_ready),
        "newly_ready_tickers": newly_ready,
        "lost_ready_tickers": lost_ready,
        "existing_ready_score_changed_count":
            len(changed_existing_ready),
        "ev_ebitda_blocker_before": ev_before,
        "ev_ebitda_blocker_after": ev_after,
        "ev_ebitda_blocker_reduced_by": ev_before - ev_after,
        "target_ticker": TARGET_TICKER,
        "target_score_total": target_score,
        "target_score_band": target_new.get("score_band") or "",
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
            row.get("score_total") == ""
            for row in new_rows
            if row.get("score_status") == "LIMITED"
        ),
    }
    new_summary["next_step"] = (
        "REFRESH_REMAINING_BLOCKER_AUDIT_FROM_V894_DRY_RUN_"
        "AND_PRIORITIZE_NEXT_SOURCE_RECOVERY"
    )

    DRY_OUT_JSON.write_text(
        json.dumps(new_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    log = [
        f"VERSION={VERSION}",
        f"POLICY_VERSION={POLICY_VERSION}",
        "SOURCE_BASE_COUNT=66",
        "SOURCE_V894_COUNT=67",
        f"NEW_VALIDATED_TICKER={TARGET_TICKER}",
        f"NEW_VALIDATED_DA_TOTAL={source_summary['new_source_details']['da_total']}",
        f"BASELINE_READY={len(old_ready)}",
        f"DRY_RUN_READY={len(new_ready)}",
        f"DRY_RUN_LIMITED={112-len(new_ready)}",
        f"READY_DELTA={len(new_ready)-len(old_ready)}",
        "NEWLY_READY_TICKERS=" + ",".join(newly_ready),
        f"TARGET_SCORE_TOTAL={target_score}",
        f"TARGET_SCORE_BAND={target_new.get('score_band') or ''}",
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
        "NEXT_STEP=REFRESH_REMAINING_BLOCKER_AUDIT_FROM_V894_DRY_RUN",
    ]
    DRY_OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    DRY_OUT_DOC.write_text(
        "\n".join([
            "# V8.9.4 삼익악기 D&A source-only 승격 + 점수 dry-run",
            "",
            f"- 버전: `{VERSION}`",
            "- production 미적용",
            "",
            "## source-only 확장",
            "",
            "- V8.8.8 66종목을 변경하지 않고 V8.9.4 파생 계층을 새로 생성한다.",
            "- V8.9.3에서 검증된 삼익악기(002450)만 추가한다.",
            "- 새 source-only 계층은 67종목이다.",
            "",
            "## 점수 재검증",
            "",
            "- V8.8.2 scorer의 공식·가중치·구간을 그대로 재사용한다.",
            "- 비교 기준은 V8.8.9 READY 41 / LIMITED 71이다.",
            "- 기존 READY 41종목의 점수가 하나라도 바뀌면 실패한다.",
            "- 삼익악기 외 다른 종목이 새 READY가 되면 실패한다.",
            "- 삼익악기가 READY가 아니어도 실패한다.",
            "",
            "## 다음 단계",
            "",
            "V8.9.4 결과를 기준으로 남은 LIMITED blocker 감사를 새로 계산하고 "
            "정책 변경 없이 복구 가능한 다음 source group을 선택한다.",
            "",
        ]),
        encoding="utf-8",
    )

    print("V894_SOURCE_EXTENSION_AND_DRY_RUN=PASS")
    print("\n".join(log))

if __name__ == "__main__":
    main()

