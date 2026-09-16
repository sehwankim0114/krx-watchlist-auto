#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import investment_score_source_enricher_v854 as src

VERSION = "2026-09-16-v8.11.0-annual-quarter-official-revenue-recovery-audit"
V8109_VERSION = "2026-09-16-v8.10.9-freeze-v8106-source-against-frozen-v8102-validation-fix"
V8105_VERSION = "2026-09-15-v8.10.5-investment-source-cache-root-cause-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
SOURCE_CONTRACT_VERSION = "2026-09-10-v8.5.4-investment-score-source-contract"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

V8109_JSON = ROOT / "latest/investment_score_remaining_blockers_v8109_summary_latest.json"
V8105_CSV = ROOT / "latest/investment_score_source_cache_root_causes_v8105.csv"
V8105_JSON = ROOT / "latest/investment_score_source_cache_root_causes_v8105_summary_latest.json"
SOURCE_CACHE = ROOT / "latest/investment_score_source_cache_latest.csv"
FIN_CACHE = ROOT / "latest/financial_valuation_cache_latest.csv"

OUT_CSV = ROOT / "latest/investment_score_annual_quarter_reaudit_v8110.csv"
OUT_JSON = ROOT / "latest/investment_score_annual_quarter_reaudit_v8110_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_annual_quarter_reaudit_v8110_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_annual_quarter_reaudit_v8110.md"

TARGET_LANE = "ANNUAL_AND_QUARTER_OFFICIAL_REAUDIT"
EXPECTED_TARGETS = {
    "000810", "005830", "006370", "029780", "105560", "138930",
}
EXPECTED_BLOCKER_OCCURRENCES = 18

REASON_REVENUE_GROWTH = "매출 성장과 안정성:MISSING_REVENUE_GROWTH_INPUT"
REASON_3Y_REVENUE = "최근 3년 매출 성장률:MISSING_3Y_REVENUE"
REASON_ACCEL = "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT"
EXPECTED_REASONS = {
    REASON_REVENUE_GROWTH,
    REASON_3Y_REVENUE,
    REASON_ACCEL,
}


def ticker(value):
    text = "".join(ch for ch in str(value or "") if ch.isdigit())
    return text.zfill(6) if text else ""


def num(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        text = str(value).strip().replace(",", "")
        if text in {"", "-", "None", "null", "nan", "NaN"}:
            return None
        x = float(text)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def has_number(value):
    return num(value) is not None


def split_reasons(text):
    return [x for x in str(text or "").split(";") if x]


def safe_yoy(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100.0, 2)


def fetch_period(client, target, year, report_code, label):
    order = []
    for fs in (target.get("preferred_fs_div") or "CFS", "CFS", "OFS"):
        fs = str(fs or "").strip()
        if fs and fs not in order:
            order.append(fs)

    by_fs = {}
    attempts = []
    for fs in order:
        payload = client.get_json(
            src.FULL_ACCOUNT_URL,
            {
                "corp_code": target["corp_code"],
                "bsns_year": str(year),
                "reprt_code": report_code,
                "fs_div": fs,
            },
            f"v8110:{target['ticker']}:{label}:{year}:{report_code}:{fs}",
        )
        status = src.norm_text(payload.get("status"))
        rows = payload.get("list") if isinstance(payload.get("list"), list) else []
        by_fs[fs] = [dict(x) for x in rows]
        attempts.append({
            "year": year,
            "report_code": report_code,
            "fs_div": fs,
            "dart_status": status,
            "dart_message": src.norm_text(payload.get("message")),
            "row_count": len(rows),
        })
        time.sleep(0.08)

    selected_fs, rows = src.select_fs_rows(
        by_fs, target.get("preferred_fs_div") or "CFS"
    )
    accounts = src.account_values(rows) if rows else {
        key: {"found": False} for key in src.ACCOUNT_SPECS
    }
    return {
        "year": year,
        "report_code": report_code,
        "selected_fs_div": selected_fs,
        "row_count": len(rows),
        "rows": rows,
        "accounts": accounts,
        "attempts": attempts,
    }


def revenue_diagnostics(rows):
    spec = src.ACCOUNT_SPECS["revenue"]
    exact_compact = {src.compact(x) for x in spec["exact"]}
    include = tuple(src.compact(x) for x in spec["include"])
    exclude = tuple(src.compact(x) for x in spec["exclude"])

    current_statement_rows = [
        r for r in rows if src.norm_text(r.get("sj_div")) == spec["statement"]
    ]

    exact_hits_is = []
    fuzzy_hits_is = []
    exact_hits_other_statement = []
    broad_revenue_like = []

    for row in rows:
        name_raw = src.norm_text(row.get("account_nm"))
        name = src.compact(name_raw)
        statement = src.norm_text(row.get("sj_div"))
        rec = {
            "sj_div": statement,
            "account_id": src.norm_text(row.get("account_id")),
            "account_nm": name_raw,
            "thstrm_amount": src.norm_text(row.get("thstrm_amount")),
            "frmtrm_amount": src.norm_text(row.get("frmtrm_amount")),
            "bfefrmtrm_amount": src.norm_text(row.get("bfefrmtrm_amount")),
            "thstrm_add_amount": src.norm_text(row.get("thstrm_add_amount")),
            "frmtrm_q_amount": src.norm_text(row.get("frmtrm_q_amount")),
        }

        if name in exact_compact:
            if statement == spec["statement"]:
                exact_hits_is.append(rec)
            else:
                exact_hits_other_statement.append(rec)

        if statement == spec["statement"]:
            if include and any(term in name for term in include):
                if not any(term in name for term in exclude):
                    fuzzy_hits_is.append(rec)

        # Audit-only broad evidence. This never promotes or changes the contract.
        if any(term in name for term in ("매출", "수익", "보험", "이자", "카드")):
            if not any(term in name for term in ("원가", "비용", "법인세")):
                broad_revenue_like.append(rec)

    chosen = src.choose_account(rows, spec)
    chosen_info = None
    if chosen:
        chosen_info = {
            "sj_div": src.norm_text(chosen.get("sj_div")),
            "account_id": src.norm_text(chosen.get("account_id")),
            "account_nm": src.norm_text(chosen.get("account_nm")),
        }

    return {
        "current_contract_chosen": chosen_info,
        "is_statement_row_count": len(current_statement_rows),
        "exact_hits_is_count": len(exact_hits_is),
        "fuzzy_hits_is_count": len(fuzzy_hits_is),
        "exact_hits_other_statement_count": len(exact_hits_other_statement),
        "broad_revenue_like_count": len(broad_revenue_like),
        "exact_hits_is": exact_hits_is[:20],
        "fuzzy_hits_is": fuzzy_hits_is[:20],
        "exact_hits_other_statement": exact_hits_other_statement[:20],
        "broad_revenue_like": broad_revenue_like[:40],
    }


def cumulative(period, account_key):
    account = (period["accounts"].get(account_key) or {})
    return src.cumulative_value(account)


def annual_values(period):
    revenue = period["accounts"].get("revenue") or {}
    op = period["accounts"].get("operating_profit") or {}
    return {
        "annual_revenue_y0": num(revenue.get("thstrm_amount")),
        "annual_revenue_y1": num(revenue.get("frmtrm_amount")),
        "annual_revenue_y2": num(revenue.get("bfefrmtrm_amount")),
        "annual_operating_profit_y0": num(op.get("thstrm_amount")),
        "annual_operating_profit_y1": num(op.get("frmtrm_amount")),
        "annual_operating_profit_y2": num(op.get("bfefrmtrm_amount")),
    }


def audit_target(client, target, root_row, source_row, fin_row):
    annual = fetch_period(client, target, 2025, "11011", "annual")
    h1_cur = fetch_period(client, target, 2026, "11012", "h1_current")
    q1_cur = fetch_period(client, target, 2026, "11013", "q1_current")
    h1_prev = fetch_period(client, target, 2025, "11012", "h1_previous")
    q1_prev = fetch_period(client, target, 2025, "11013", "q1_previous")

    values = annual_values(annual)

    h1_rev_cur = cumulative(h1_cur, "revenue")
    q1_rev_cur = cumulative(q1_cur, "revenue")
    h1_rev_prev = cumulative(h1_prev, "revenue")
    q1_rev_prev = cumulative(q1_prev, "revenue")

    h1_op_cur = cumulative(h1_cur, "operating_profit")
    q1_op_cur = cumulative(q1_cur, "operating_profit")
    h1_op_prev = cumulative(h1_prev, "operating_profit")
    q1_op_prev = cumulative(q1_prev, "operating_profit")

    q2_rev_cur = (
        h1_rev_cur - q1_rev_cur
        if h1_rev_cur is not None and q1_rev_cur is not None else None
    )
    q2_rev_prev = (
        h1_rev_prev - q1_rev_prev
        if h1_rev_prev is not None and q1_rev_prev is not None else None
    )
    q2_op_cur = (
        h1_op_cur - q1_op_cur
        if h1_op_cur is not None and q1_op_cur is not None else None
    )
    q2_op_prev = (
        h1_op_prev - q1_op_prev
        if h1_op_prev is not None and q1_op_prev is not None else None
    )

    values.update({
        "q2_revenue_current": q2_rev_cur,
        "q2_revenue_previous": q2_rev_prev,
        "q2_revenue_yoy_pct": safe_yoy(q2_rev_cur, q2_rev_prev),
        "q2_operating_profit_current": q2_op_cur,
        "q2_operating_profit_previous": q2_op_prev,
        "q2_operating_profit_yoy_pct": safe_yoy(q2_op_cur, q2_op_prev),
        "financial_revenue_yoy_pct": num(fin_row.get("revenue_yoy_pct")),
    })

    annual_revenue_complete = all(
        values.get(k) is not None
        for k in ("annual_revenue_y0", "annual_revenue_y1", "annual_revenue_y2")
    ) and values["annual_revenue_y1"] > 0 and values["annual_revenue_y2"] > 0

    q2_revenue_complete = all(
        values.get(k) is not None
        for k in (
            "q2_revenue_current",
            "q2_revenue_previous",
            "q2_revenue_yoy_pct",
        )
    )

    annual_op_available = all(
        values.get(k) is not None
        for k in ("annual_operating_profit_y0", "annual_operating_profit_y1")
    ) or str(root_row.get("annual_operating_profit_3y_complete") or "").upper() == "TRUE"

    q2_op_available = all(
        values.get(k) is not None
        for k in (
            "q2_operating_profit_current",
            "q2_operating_profit_previous",
            "q2_operating_profit_yoy_pct",
        )
    ) or str(root_row.get("q2_operating_profit_complete") or "").upper() == "TRUE"

    blocker_recoverability = {
        REASON_REVENUE_GROWTH: (
            annual_revenue_complete
            and values["financial_revenue_yoy_pct"] is not None
        ),
        REASON_3Y_REVENUE: annual_revenue_complete,
        REASON_ACCEL: (
            annual_revenue_complete
            and q2_revenue_complete
            and annual_op_available
            and q2_op_available
        ),
    }

    reasons = set(split_reasons(root_row.get("blocker_reasons")))
    if reasons != EXPECTED_REASONS:
        raise RuntimeError(
            f"V8110_TARGET_REASON_SET_CHANGED:{target['ticker']}:"
            + "|".join(sorted(reasons))
        )

    recoverable_count = sum(
        1 for reason in reasons if blocker_recoverability[reason]
    )

    period_map = {
        "annual": annual,
        "h1_current": h1_cur,
        "q1_current": q1_cur,
        "h1_previous": h1_prev,
        "q1_previous": q1_prev,
    }
    diagnostics = {
        label: revenue_diagnostics(period["rows"])
        for label, period in period_map.items()
    }

    broad_evidence_count = sum(
        d["broad_revenue_like_count"] for d in diagnostics.values()
    )
    contract_chosen_count = sum(
        1 for d in diagnostics.values()
        if d["current_contract_chosen"] is not None
    )

    if recoverable_count == 3:
        classification = "CURRENT_V854_CONTRACT_FULLY_RECOVERABLE"
    elif recoverable_count > 0:
        classification = "CURRENT_V854_CONTRACT_PARTIALLY_RECOVERABLE"
    elif broad_evidence_count > 0:
        classification = "OFFICIAL_REVENUE_LIKE_FACTS_OUTSIDE_USABLE_CURRENT_CONTRACT"
    else:
        classification = "NO_USABLE_OFFICIAL_REVENUE_FACTS_FOUND"

    return {
        "classification": classification,
        "recoverable_blocker_count": recoverable_count,
        "blocker_recoverability": blocker_recoverability,
        "values": values,
        "period_diagnostics": diagnostics,
        "contract_chosen_period_count": contract_chosen_count,
        "broad_revenue_evidence_count": broad_evidence_count,
        "current_source_cache_status": source_row.get("source_cache_status") or "",
        "current_source_cache_reason": source_row.get("source_cache_reason") or "",
        "current_three_year_source_status": source_row.get("three_year_source_status") or "",
        "current_quarter_source_status": source_row.get("quarter_source_status") or "",
    }


def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DART_API_KEY_MISSING")

    required = [
        V8109_JSON, V8105_CSV, V8105_JSON,
        SOURCE_CACHE, FIN_CACHE,
    ]
    for path in required:
        if not path.is_file():
            raise RuntimeError("MISSING_REQUIRED_SOURCE:" + str(path))

    s8109 = read_json(V8109_JSON)
    if s8109.get("version") != V8109_VERSION:
        raise RuntimeError("V8109_VERSION_MISMATCH")
    if s8109.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8109_STATUS_MISMATCH")
    if int(s8109.get("limited_blocker_occurrences") or 0) != 280:
        raise RuntimeError("V8109_BLOCKER_COUNT_NOT_280")
    if int((s8109.get("source_group_counts") or {}).get("INVESTMENT_SCORE_SOURCE_CACHE") or 0) != 57:
        raise RuntimeError("V8109_SOURCE_CACHE_BLOCKERS_NOT_57")
    if s8109.get("next_actionable_lane") != "V8105_ANNUAL_AND_QUARTER_OFFICIAL_REAUDIT":
        raise RuntimeError("V8109_NEXT_LANE_CHANGED")
    if set(s8109.get("next_actionable_lane_tickers") or []) != EXPECTED_TARGETS:
        raise RuntimeError("V8109_TARGET_SET_CHANGED")
    if int(s8109.get("next_actionable_lane_prior_blocker_occurrences") or 0) != EXPECTED_BLOCKER_OCCURRENCES:
        raise RuntimeError("V8109_PRIOR_BLOCKER_OCCURRENCES_NOT_18")

    s8105 = read_json(V8105_JSON)
    if s8105.get("version") != V8105_VERSION:
        raise RuntimeError("V8105_VERSION_MISMATCH")
    if s8105.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8105_STATUS_MISMATCH")
    if s8105.get("source_contract_version") != SOURCE_CONTRACT_VERSION:
        raise RuntimeError("V8105_SOURCE_CONTRACT_MISMATCH")

    root_rows = read_csv(V8105_CSV)
    root_map = {
        ticker(r.get("ticker")): r
        for r in root_rows
        if ticker(r.get("ticker"))
    }
    target_root = {
        code: root_map.get(code)
        for code in EXPECTED_TARGETS
    }
    if any(v is None for v in target_root.values()):
        raise RuntimeError("V8110_TARGET_ROOT_ROW_MISSING")
    if any(v.get("recovery_lane") != TARGET_LANE for v in target_root.values()):
        raise RuntimeError("V8110_RECOVERY_LANE_CHANGED")
    if sum(int(v.get("source_cache_blocker_count") or 0) for v in target_root.values()) != 18:
        raise RuntimeError("V8110_ROOT_BLOCKER_SUM_NOT_18")

    source_rows = read_csv(SOURCE_CACHE)
    source_map = {
        ticker(r.get("ticker")): r
        for r in source_rows
        if ticker(r.get("ticker"))
    }
    for code in EXPECTED_TARGETS:
        if code not in source_map:
            raise RuntimeError("V8110_SOURCE_CACHE_ROW_MISSING:" + code)
        row = source_map[code]
        if row.get("source_cache_status") != "LIMITED_RAW_SOURCE":
            raise RuntimeError(
                f"V8110_SOURCE_STATUS_CHANGED:{code}:{row.get('source_cache_status')}"
            )
        reason = row.get("source_cache_reason") or ""
        if "3Y_ANNUAL_LIMITED" not in reason or "QUARTER_LIMITED" not in reason:
            raise RuntimeError(
                f"V8110_SOURCE_REASON_CHANGED:{code}:{reason}"
            )

    fin_df = src.read_csv(FIN_CACHE)
    targets = src.load_targets(fin_df)
    target_map = {t["ticker"]: t for t in targets}
    if not EXPECTED_TARGETS <= set(target_map):
        missing = sorted(EXPECTED_TARGETS - set(target_map))
        raise RuntimeError(
            "V8110_FINANCIAL_TARGET_MISSING:" + ",".join(missing)
        )

    fin_rows = read_csv(FIN_CACHE)
    fin_map = {
        ticker(r.get("ticker")): r
        for r in fin_rows
        if ticker(r.get("ticker"))
    }

    client = src.OpenDartClient(api_key, timeout=30)

    out_rows = []
    class_counter = Counter()
    recoverable_tickers = []
    partially_recoverable_tickers = []
    semantic_audit_tickers = []
    exhausted_tickers = []
    recoverable_blockers_total = 0

    for code in sorted(EXPECTED_TARGETS):
        target = target_map[code]
        audit = audit_target(
            client,
            target,
            target_root[code],
            source_map[code],
            fin_map[code],
        )
        cls = audit["classification"]
        class_counter[cls] += 1
        recoverable_blockers_total += audit["recoverable_blocker_count"]

        if cls == "CURRENT_V854_CONTRACT_FULLY_RECOVERABLE":
            recoverable_tickers.append(code)
        elif cls == "CURRENT_V854_CONTRACT_PARTIALLY_RECOVERABLE":
            partially_recoverable_tickers.append(code)
        elif cls == "OFFICIAL_REVENUE_LIKE_FACTS_OUTSIDE_USABLE_CURRENT_CONTRACT":
            semantic_audit_tickers.append(code)
        else:
            exhausted_tickers.append(code)

        root = target_root[code]
        out_rows.append({
            "ticker": code,
            "name": root.get("name") or target.get("name") or "",
            "market": root.get("market") or target.get("market") or "",
            "corp_code": target.get("corp_code") or "",
            "preferred_fs_div": target.get("preferred_fs_div") or "",
            "blocker_count": int(root.get("source_cache_blocker_count") or 0),
            "blocker_reasons": root.get("blocker_reasons") or "",
            "classification": cls,
            "recoverable_blocker_count": audit["recoverable_blocker_count"],
            "all_three_blockers_recoverable": (
                "TRUE" if audit["recoverable_blocker_count"] == 3 else "FALSE"
            ),
            "contract_chosen_period_count": audit["contract_chosen_period_count"],
            "broad_revenue_evidence_count": audit["broad_revenue_evidence_count"],
            "current_source_cache_status": audit["current_source_cache_status"],
            "current_source_cache_reason": audit["current_source_cache_reason"],
            "current_three_year_source_status": audit["current_three_year_source_status"],
            "current_quarter_source_status": audit["current_quarter_source_status"],
            "blocker_recoverability_json": json.dumps(
                audit["blocker_recoverability"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "official_values_json": json.dumps(
                audit["values"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "period_diagnostics_json": json.dumps(
                audit["period_diagnostics"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        })

    fields = list(out_rows[0].keys())
    write_csv(OUT_CSV, out_rows, fields)

    if recoverable_blockers_total < 0 or recoverable_blockers_total > 18:
        raise RuntimeError(
            f"V8110_RECOVERABLE_BLOCKER_COUNT_INVALID:{recoverable_blockers_total}"
        )

    if recoverable_tickers or partially_recoverable_tickers:
        next_step = "FREEZE_V8110_CURRENT_CONTRACT_RECOVERABLE_FIELDS_SOURCE_ONLY_THEN_SHADOW_DRY_RUN"
    elif semantic_audit_tickers:
        next_step = "AUDIT_V8110_OFFICIAL_REVENUE_ACCOUNT_SEMANTICS_WITHOUT_CONTRACT_CHANGE"
    else:
        next_step = "DEFER_V8110_LANE_AND_MOVE_TO_NEXT_RECOVERABLE_SOURCE_GROUP"

    summary = {
        "version": VERSION,
        "v8109_version": V8109_VERSION,
        "v8105_version": V8105_VERSION,
        "policy_version": POLICY_VERSION,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "source_script_version": src.SCRIPT_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY",
        "target_lane": TARGET_LANE,
        "target_ticker_count": len(out_rows),
        "target_tickers": sorted(EXPECTED_TARGETS),
        "target_blocker_occurrences": EXPECTED_BLOCKER_OCCURRENCES,
        "classification_counts": dict(class_counter),
        "current_contract_fully_recoverable_count": len(recoverable_tickers),
        "current_contract_fully_recoverable_tickers": sorted(recoverable_tickers),
        "current_contract_partially_recoverable_count": len(partially_recoverable_tickers),
        "current_contract_partially_recoverable_tickers": sorted(partially_recoverable_tickers),
        "official_revenue_semantic_audit_count": len(semantic_audit_tickers),
        "official_revenue_semantic_audit_tickers": sorted(semantic_audit_tickers),
        "no_usable_official_revenue_fact_count": len(exhausted_tickers),
        "no_usable_official_revenue_fact_tickers": sorted(exhausted_tickers),
        "recoverable_blocker_occurrence_count": recoverable_blockers_total,
        "api_telemetry": {
            "attempted": client.attempted,
            "successful": client.successful,
            "transport_failures": client.transport_failures,
            "dart_status_failures": client.dart_status_failures,
        },
        "automatic_promotion": {
            "allowed": False,
            "promoted_ticker_count": 0,
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "source_cache_mutated": False,
            "financial_cache_mutated": False,
            "account_spec_changed": False,
            "new_revenue_account_name_approved": False,
            "financial_sector_exception_created": False,
            "source_value_imputed": False,
            "h1_used_directly_as_q2": False,
            "ambiguous_account_promoted": False,
        },
        "next_step": next_step,
    }
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    log = [
        f"VERSION={VERSION}",
        "STATUS=AUDIT_ONLY",
        "TARGET_TICKER_COUNT=6",
        "TARGET_BLOCKER_OCCURRENCES=18",
        f"FULLY_RECOVERABLE_TICKERS={len(recoverable_tickers)}",
        "FULLY_RECOVERABLE_CODES=" + ",".join(sorted(recoverable_tickers)),
        f"PARTIALLY_RECOVERABLE_TICKERS={len(partially_recoverable_tickers)}",
        "PARTIALLY_RECOVERABLE_CODES=" + ",".join(sorted(partially_recoverable_tickers)),
        f"SEMANTIC_AUDIT_TICKERS={len(semantic_audit_tickers)}",
        "SEMANTIC_AUDIT_CODES=" + ",".join(sorted(semantic_audit_tickers)),
        f"NO_USABLE_OFFICIAL_REVENUE_FACT_TICKERS={len(exhausted_tickers)}",
        "NO_USABLE_OFFICIAL_REVENUE_FACT_CODES=" + ",".join(sorted(exhausted_tickers)),
        f"RECOVERABLE_BLOCKER_OCCURRENCES={recoverable_blockers_total}",
        f"DART_API_ATTEMPTED={client.attempted}",
        f"DART_API_SUCCESSFUL={client.successful}",
        "PRODUCTION_API_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "SCORING_POLICY_CHANGED=false",
        "SOURCE_CACHE_MUTATED=false",
        "FINANCIAL_CACHE_MUTATED=false",
        "ACCOUNT_SPEC_CHANGED=false",
        "NEW_REVENUE_ACCOUNT_NAME_APPROVED=false",
        "FINANCIAL_SECTOR_EXCEPTION_CREATED=false",
        "SOURCE_VALUE_IMPUTED=false",
        "H1_USED_DIRECTLY_AS_Q2=false",
        "AMBIGUOUS_ACCOUNT_PROMOTED=false",
        "STATUS_OK=true",
        f"NEXT_STEP={next_step}",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.11.0 annual + quarter official revenue recovery audit",
            "",
            f"- Version: `{VERSION}`",
            "- Status: AUDIT_ONLY",
            "- Targets: 삼성화재, DB손해보험, 대구백화점, 삼성카드, KB금융, BNK금융지주.",
            "- Existing 18 source-cache blockers only.",
            "- Reuses the current V8.5.4 `ACCOUNT_SPECS['revenue']` contract exactly.",
            "- Fresh OpenDART full-account data are checked for 2025 annual, 2026 H1/Q1 and 2025 H1/Q1.",
            "- Q2 remains H1 cumulative minus Q1 cumulative.",
            "- Revenue-like official accounts outside the current contract are evidence only; they are never promoted automatically.",
            "",
            "## Safety",
            "",
            "- No account-spec change.",
            "- No financial-sector exception.",
            "- No production/cache mutation.",
            "- No imputation.",
            "- No ambiguous account promotion.",
            "",
            "## Next",
            "",
            f"`{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8110_ANNUAL_QUARTER_OFFICIAL_REVENUE_RECOVERY_AUDIT=PASS")
    print("\n".join(log))


if __name__ == "__main__":
    main()
