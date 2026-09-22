#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_source_enricher_v854 as src
import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-22-v8.14.3-esr-kendall-q2-score-cache-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
SOURCE_CONTRACT_VERSION = (
    "2026-09-16-v8.11.7-five-financial-cis-interest-revenue-contract"
)
V8141_VERSION = "2026-09-22-v8.14.1-post-supply-current-blocker-reaudit"
V8142_VERSION = "2026-09-22-v8.14.2-current-actionable-exact-da-single-blocker-audit"
V8142_RESULT_COMMIT = "d2827e49cf930b6cf9857897a98ffb512c90a4f5"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8141.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8141_summary_latest.json"
DA_JSON = ROOT / "latest/investment_score_exact_da_actionable_v8142_summary_latest.json"
RAW = ROOT / "latest/investment_score_source_cache_latest.csv"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"

OUT_CSV = ROOT / "latest/investment_score_score_cache_actionable_v8143.csv"
OUT_JSON = ROOT / "latest/investment_score_score_cache_actionable_v8143_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_score_cache_actionable_v8143_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_score_cache_actionable_v8143.md"

TICKER = "365550"
NAME = "ESR켄달스퀘어리츠"
CORP_CODE = "01437186"

PERIODS = (
    (2026, "11012", "H1_CURRENT"),
    (2026, "11013", "Q1_CURRENT"),
    (2025, "11012", "H1_PREVIOUS"),
    (2025, "11013", "Q1_PREVIOUS"),
)

REQUIRED_KEYS = (
    "revenue",
    "operating_profit",
)
OPTIONAL_KEYS = (
    "net_income",
)

def read_json(path):
    return json.loads(
        Path(path).read_text(encoding="utf-8-sig")
    )

def read_rows(path):
    with Path(path).open(
        encoding="utf-8-sig",
        newline="",
    ) as f:
        return list(csv.DictReader(f))

def ticker(value):
    s = "".join(
        ch for ch in str(value or "")
        if ch.isdigit()
    )
    return s.zfill(6) if s else ""

def num(value):
    try:
        if value in (None, "", "null", "None"):
            return None
        return float(value)
    except Exception:
        return None

def selected_account_snapshot(accounts):
    out = {}
    for key in REQUIRED_KEYS + OPTIONAL_KEYS:
        row = accounts.get(key) or {}
        out[key] = {
            "found": bool(row.get("found")),
            "account_nm": row.get("account_nm") or "",
            "thstrm_amount": row.get("thstrm_amount"),
            "thstrm_add_amount": row.get("thstrm_add_amount"),
            "cumulative_value": src.cumulative_value(row),
        }
    return out

def period_values(period_map):
    out = {}
    for label, p in period_map.items():
        out[label] = {
            key: src.cumulative_value(
                (p.get("accounts") or {}).get(key) or {}
            )
            for key in REQUIRED_KEYS + OPTIONAL_KEYS
        }
    return out

def required_recoverable(values):
    needed = (
        values["H1_CURRENT"]["revenue"],
        values["Q1_CURRENT"]["revenue"],
        values["H1_PREVIOUS"]["revenue"],
        values["Q1_PREVIOUS"]["revenue"],
        values["H1_CURRENT"]["operating_profit"],
        values["Q1_CURRENT"]["operating_profit"],
        values["H1_PREVIOUS"]["operating_profit"],
        values["Q1_PREVIOUS"]["operating_profit"],
    )
    return all(v is not None for v in needed)

def full_quarter_contract_recoverable(values):
    if not required_recoverable(values):
        return False
    needed = (
        values["H1_CURRENT"]["net_income"],
        values["Q1_CURRENT"]["net_income"],
        values["H1_PREVIOUS"]["net_income"],
        values["Q1_PREVIOUS"]["net_income"],
    )
    return all(v is not None for v in needed)

def q2_candidate(values):
    if not required_recoverable(values):
        return {}

    q2_rev_cur = (
        values["H1_CURRENT"]["revenue"]
        - values["Q1_CURRENT"]["revenue"]
    )
    q2_rev_prev = (
        values["H1_PREVIOUS"]["revenue"]
        - values["Q1_PREVIOUS"]["revenue"]
    )
    q2_op_cur = (
        values["H1_CURRENT"]["operating_profit"]
        - values["Q1_CURRENT"]["operating_profit"]
    )
    q2_op_prev = (
        values["H1_PREVIOUS"]["operating_profit"]
        - values["Q1_PREVIOUS"]["operating_profit"]
    )

    return {
        "q2_revenue_current": q2_rev_cur,
        "q2_revenue_previous": q2_rev_prev,
        "q2_operating_profit_current": q2_op_cur,
        "q2_operating_profit_previous": q2_op_prev,
        "q2_revenue_yoy_pct": src.safe_yoy_pct(
            q2_rev_cur,
            q2_rev_prev,
        ),
        "q2_operating_profit_yoy_pct": src.safe_yoy_pct(
            q2_op_cur,
            q2_op_prev,
        ),
    }

def query_multi_current_contract(client, target):
    out = {}
    hard_failures = []

    for year, report_code, label in PERIODS:
        data = src.query_multi_period(
            client,
            [target],
            year,
            report_code,
        )
        fs_div, rows = src.select_fs_rows(
            data.get(CORP_CODE, {}),
            target["preferred_fs_div"],
        )
        accounts = src.account_values(
            rows,
            TICKER,
        )
        out[label] = {
            "year": year,
            "report_code": report_code,
            "fs_div": fs_div,
            "row_count": len(rows),
            "accounts": accounts,
            "selected": selected_account_snapshot(accounts),
        }
        time.sleep(0.05)

    # src.query_multi_period records every non-000 status.
    # 013 is official no-data evidence; other statuses fail closed.
    for entry in client.dart_status_failures:
        parts = str(entry).split("|")
        status = parts[1] if len(parts) > 1 else ""
        if status != "013":
            hard_failures.append(entry)

    return out, hard_failures

def query_full_account_period(client, target, year, report_code, label):
    order = []
    for fs in (
        target["preferred_fs_div"],
        "CFS",
        "OFS",
    ):
        if fs in {"CFS", "OFS"} and fs not in order:
            order.append(fs)

    attempts = []
    hard_failure = ""

    for fs_div in order:
        payload = client.get_json(
            src.FULL_ACCOUNT_URL,
            {
                "corp_code": CORP_CODE,
                "bsns_year": str(year),
                "reprt_code": report_code,
                "fs_div": fs_div,
            },
            f"v8143-full:{TICKER}:{year}:{report_code}:{fs_div}",
        )
        status = src.norm_text(
            payload.get("status")
        )
        message = src.norm_text(
            payload.get("message")
        )
        items = (
            payload.get("list")
            if isinstance(payload.get("list"), list)
            else []
        )

        attempts.append({
            "fs_div": fs_div,
            "status": status,
            "message": message,
            "row_count": len(items),
        })

        if status == "000" and items:
            accounts = src.account_values(
                items,
                TICKER,
            )
            return {
                "label": label,
                "year": year,
                "report_code": report_code,
                "fs_div": fs_div,
                "status": "OK",
                "dart_status": status,
                "message": "",
                "row_count": len(items),
                "accounts": accounts,
                "selected": selected_account_snapshot(accounts),
                "attempts": attempts,
            }, ""

        if status == "013":
            continue

        if status not in {"", "000", "013"}:
            hard_failure = (
                f"{label}:{fs_div}:{status}:{message}"
            )
            break

        if status == "TRANSPORT_ERROR":
            hard_failure = (
                f"{label}:{fs_div}:TRANSPORT_ERROR:{message}"
            )
            break

    return {
        "label": label,
        "year": year,
        "report_code": report_code,
        "fs_div": "",
        "status": "OFFICIAL_NO_USABLE_DATA"
        if not hard_failure
        else "HARD_FAILURE",
        "dart_status": "013"
        if not hard_failure
        else "",
        "message": hard_failure,
        "row_count": 0,
        "accounts": {},
        "selected": {},
        "attempts": attempts,
    }, hard_failure

def main():
    api_key = os.environ.get(
        "DART_API_KEY",
        "",
    ).strip()
    if not api_key:
        raise RuntimeError(
            "V8143_DART_API_KEY_MISSING"
        )

    for p in (
        BLOCK_CSV,
        BLOCK_JSON,
        DA_JSON,
        RAW,
        FIN,
    ):
        if not p.is_file():
            raise RuntimeError(
                "V8143_MISSING_INPUT:" + str(p)
            )

    subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            V8142_RESULT_COMMIT,
            "HEAD",
        ],
        check=True,
    )

    block_summary = read_json(BLOCK_JSON)
    da_summary = read_json(DA_JSON)

    if block_summary.get("version") != V8141_VERSION:
        raise RuntimeError(
            "V8143_V8141_VERSION_MISMATCH"
        )
    if block_summary.get(
        "secondary_actionable_groups",
        {},
    ).get(
        "INVESTMENT_SCORE_SOURCE_CACHE"
    ) != [TICKER]:
        raise RuntimeError(
            "V8143_SECONDARY_SCORE_CACHE_TARGET_CHANGED"
        )

    if da_summary.get("version") != V8142_VERSION:
        raise RuntimeError(
            "V8143_V8142_VERSION_MISMATCH"
        )
    if da_summary.get("next_step") != (
        "AUDIT_CURRENT_ACTIONABLE_SCORE_CACHE_SINGLE_BLOCKER_V8143"
    ):
        raise RuntimeError(
            "V8143_PREDECESSOR_NEXT_STEP_MISMATCH"
        )
    if int(
        da_summary.get(
            "post_audit_exhausted_union_count"
        ) or 0
    ) != 64:
        raise RuntimeError(
            "V8143_DA_EXHAUSTED_UNION_NOT_64"
        )

    block_rows = [
        r
        for r in read_rows(BLOCK_CSV)
        if ticker(r.get("ticker")) == TICKER
    ]
    if len(block_rows) != 1:
        raise RuntimeError(
            "V8143_TARGET_BLOCKER_ROW_COUNT_NOT_1"
        )

    blocker = block_rows[0]
    if blocker.get("name") != NAME:
        raise RuntimeError(
            "V8143_TARGET_NAME_MISMATCH"
        )
    if blocker.get("source_group") != (
        "INVESTMENT_SCORE_SOURCE_CACHE"
    ):
        raise RuntimeError(
            "V8143_SOURCE_GROUP_CHANGED"
        )
    if blocker.get("blocker_reason") != (
        "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT"
    ):
        raise RuntimeError(
            "V8143_BLOCKER_REASON_CHANGED:"
            + str(blocker.get("blocker_reason"))
        )
    if blocker.get("single_blocker_ticker") != "TRUE":
        raise RuntimeError(
            "V8143_TARGET_NOT_SINGLE_BLOCKER"
        )
    if blocker.get("recovery_status") != (
        "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
    ):
        raise RuntimeError(
            "V8143_TARGET_NOT_ACTIONABLE"
        )

    raw_rows = {
        ticker(r.get("ticker")): r
        for r in read_rows(RAW)
        if ticker(r.get("ticker"))
    }
    raw = raw_rows.get(TICKER)
    if not raw:
        raise RuntimeError(
            "V8143_SOURCE_CACHE_TARGET_MISSING"
        )
    if raw.get("name") != NAME:
        raise RuntimeError(
            "V8143_SOURCE_CACHE_NAME_MISMATCH"
        )
    if raw.get("corp_code") != CORP_CODE:
        raise RuntimeError(
            "V8143_SOURCE_CACHE_CORP_MISMATCH"
        )
    if raw.get("source_contract_version") != (
        SOURCE_CONTRACT_VERSION
    ):
        raise RuntimeError(
            "V8143_SOURCE_CONTRACT_VERSION_MISMATCH"
        )
    if raw.get("source_cache_status") != (
        "LIMITED_RAW_SOURCE"
    ):
        raise RuntimeError(
            "V8143_SOURCE_CACHE_STATUS_CHANGED"
        )
    if "QUARTER_LIMITED" not in (
        raw.get("source_cache_reason") or ""
    ):
        raise RuntimeError(
            "V8143_SOURCE_CACHE_REASON_CHANGED"
        )
    if raw.get("quarter_source_status") != "LIMITED":
        raise RuntimeError(
            "V8143_QUARTER_STATUS_CHANGED"
        )

    for key in (
        "q2_revenue_current",
        "q2_revenue_previous",
        "q2_operating_profit_current",
        "q2_operating_profit_previous",
        "q2_revenue_yoy_pct",
        "q2_operating_profit_yoy_pct",
    ):
        if str(raw.get(key) or "").strip():
            raise RuntimeError(
                "V8143_EXPECTED_Q2_FIELD_ALREADY_PRESENT:"
                + key
            )

    fin_rows = {
        ticker(r.get("ticker")): r
        for r in read_rows(FIN)
        if ticker(r.get("ticker"))
    }
    fin = fin_rows.get(TICKER)
    if not fin:
        raise RuntimeError(
            "V8143_FIN_TARGET_MISSING"
        )
    if fin.get("corp_code") != CORP_CODE:
        raise RuntimeError(
            "V8143_FIN_CORP_MISMATCH"
        )
    if fin.get("corp_identity_status") not in {
        "MATCH",
        "MATCH_NORMALIZED",
    }:
        raise RuntimeError(
            "V8143_FIN_IDENTITY_NOT_MATCH"
        )
    if fin.get("financial_report_year") != "2026":
        raise RuntimeError(
            "V8143_FIN_YEAR_CHANGED"
        )
    if fin.get("financial_report_code") != "11012":
        raise RuntimeError(
            "V8143_FIN_REPORT_CODE_CHANGED"
        )

    financial_df = src.read_csv(FIN)
    targets = src.load_targets(financial_df)
    dominant_year, dominant_code = src.dominant_period(
        targets
    )
    if (
        dominant_year,
        str(dominant_code),
    ) != (
        2026,
        "11012",
    ):
        raise RuntimeError(
            "V8143_DOMINANT_PERIOD_CHANGED"
        )

    target_map = {
        t["ticker"]: t
        for t in targets
    }
    target = target_map.get(TICKER)
    if not target:
        raise RuntimeError(
            "V8143_TARGET_MAPPING_MISSING"
        )
    if target.get("corp_code") != CORP_CODE:
        raise RuntimeError(
            "V8143_TARGET_MAPPING_CORP_MISMATCH"
        )
    if target.get("preferred_fs_div") != "CFS":
        raise RuntimeError(
            "V8143_PREFERRED_FS_CHANGED:"
            + str(target.get("preferred_fs_div"))
        )

    multi_client = src.OpenDartClient(
        api_key,
        timeout=30,
    )
    multi_periods, multi_hard = (
        query_multi_current_contract(
            multi_client,
            target,
        )
    )
    if multi_client.transport_failures:
        raise RuntimeError(
            "V8143_MULTI_TRANSPORT_FAILURE:"
            + "|".join(
                multi_client.transport_failures
            )
        )
    if multi_hard:
        raise RuntimeError(
            "V8143_MULTI_HARD_DART_FAILURE:"
            + "|".join(multi_hard)
        )

    multi_values = period_values(
        multi_periods
    )
    multi_required_ready = (
        required_recoverable(
            multi_values
        )
    )
    multi_full_ready = (
        full_quarter_contract_recoverable(
            multi_values
        )
    )
    multi_candidate = q2_candidate(
        multi_values
    )

    # Independently query the official full-account endpoint.
    full_client = src.OpenDartClient(
        api_key,
        timeout=30,
    )
    full_periods = {}
    full_hard = []
    for (
        year,
        report_code,
        label,
    ) in PERIODS:
        period, hard = (
            query_full_account_period(
                full_client,
                target,
                year,
                report_code,
                label,
            )
        )
        full_periods[label] = period
        if hard:
            full_hard.append(hard)
        time.sleep(0.08)

    if full_client.transport_failures:
        raise RuntimeError(
            "V8143_FULL_TRANSPORT_FAILURE:"
            + "|".join(
                full_client.transport_failures
            )
        )
    if full_hard:
        raise RuntimeError(
            "V8143_FULL_HARD_DART_FAILURE:"
            + "|".join(full_hard)
        )

    full_values = period_values(
        full_periods
    )
    full_required_ready = (
        required_recoverable(
            full_values
        )
    )
    full_full_ready = (
        full_quarter_contract_recoverable(
            full_values
        )
    )
    full_candidate = q2_candidate(
        full_values
    )

    # Current production row annual inputs are the denominator
    # contract for s_accel; do not replace them here.
    base_raw = dict(raw)

    candidate_source = ""
    candidate = {}
    if multi_required_ready:
        candidate_source = (
            "CURRENT_MULTI_ACCOUNT_CONTRACT"
        )
        candidate = multi_candidate
    elif full_required_ready:
        candidate_source = (
            "FULL_ACCOUNT_SAME_ACCOUNT_SELECTOR_AUDIT"
        )
        candidate = full_candidate

    accel_points = None
    accel_reason = ""
    scorer_required_recoverable = False

    if candidate:
        shadow = dict(base_raw)
        for key, value in candidate.items():
            shadow[key] = value

        accel_points, accel_reason = (
            scorer.s_accel(shadow)
        )
        scorer_required_recoverable = (
            accel_points is not None
            and accel_reason
            != "MISSING_ACCEL_INPUT"
        )

    if (
        candidate
        and not scorer_required_recoverable
    ):
        raise RuntimeError(
            "V8143_CANDIDATE_STILL_MISSING_ACCEL:"
            + str(accel_reason)
        )

    if multi_required_ready:
        classification = (
            "RECOVERABLE_CURRENT_SOURCE_CONTRACT"
        )
        next_step = (
            "FREEZE_RECOVERABLE_SCORE_CACHE_Q2_AND_SHADOW_SCORE_V8144"
        )
    elif full_required_ready:
        classification = (
            "RECOVERABLE_FULL_ACCOUNT_NARROW_EXTENSION_CANDIDATE"
        )
        next_step = (
            "STAGE_NARROW_ESR_Q2_SOURCE_EXTENSION_AND_SHADOW_V8144"
        )
    else:
        classification = (
            "NO_COMPLETE_OFFICIAL_Q2_ACCEL_INPUT_PATH"
        )
        next_step = (
            "MARK_SCORE_CACHE_Q2_PATH_EXHAUSTED_AND_REAUDIT_V8144"
        )

    row = {
        "ticker": TICKER,
        "name": NAME,
        "corp_code": CORP_CODE,
        "blocker_reason": blocker.get("blocker_reason") or "",
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "production_source_cache_status": raw.get(
            "source_cache_status"
        ) or "",
        "production_quarter_source_status": raw.get(
            "quarter_source_status"
        ) or "",
        "multi_required_accel_inputs_recoverable": (
            "TRUE"
            if multi_required_ready
            else "FALSE"
        ),
        "multi_full_quarter_contract_recoverable": (
            "TRUE"
            if multi_full_ready
            else "FALSE"
        ),
        "full_required_accel_inputs_recoverable": (
            "TRUE"
            if full_required_ready
            else "FALSE"
        ),
        "full_full_quarter_contract_recoverable": (
            "TRUE"
            if full_full_ready
            else "FALSE"
        ),
        "selected_candidate_source": candidate_source,
        "candidate_q2_revenue_current": (
            candidate.get(
                "q2_revenue_current",
                "",
            )
        ),
        "candidate_q2_revenue_previous": (
            candidate.get(
                "q2_revenue_previous",
                "",
            )
        ),
        "candidate_q2_operating_profit_current": (
            candidate.get(
                "q2_operating_profit_current",
                "",
            )
        ),
        "candidate_q2_operating_profit_previous": (
            candidate.get(
                "q2_operating_profit_previous",
                "",
            )
        ),
        "candidate_q2_revenue_yoy_pct": (
            candidate.get(
                "q2_revenue_yoy_pct",
                "",
            )
        ),
        "candidate_q2_operating_profit_yoy_pct": (
            candidate.get(
                "q2_operating_profit_yoy_pct",
                "",
            )
        ),
        "candidate_accel_points": (
            ""
            if accel_points is None
            else accel_points
        ),
        "candidate_accel_reason": accel_reason,
        "classification": classification,
        "multi_period_evidence_json": json.dumps(
            multi_periods,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "full_period_evidence_json": json.dumps(
            full_periods,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }

    OUT_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    with OUT_CSV.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        w = csv.DictWriter(
            f,
            fieldnames=list(row.keys()),
            lineterminator="\n",
        )
        w.writeheader()
        w.writerow(row)

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(
            KST
        ).isoformat(
            timespec="seconds"
        ),
        "status": (
            "AUDIT_ONLY_CURRENT_ACTIONABLE_SCORE_CACHE_Q2"
        ),
        "policy_version": POLICY_VERSION,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "v8142_version": V8142_VERSION,
        "v8142_result_commit": V8142_RESULT_COMMIT,
        "target_ticker": TICKER,
        "target_name": NAME,
        "target_corp_code": CORP_CODE,
        "blocker_reason": (
            "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT"
        ),
        "production_source_state": {
            "source_cache_status": raw.get(
                "source_cache_status"
            ),
            "source_cache_reason": raw.get(
                "source_cache_reason"
            ),
            "quarter_source_status": raw.get(
                "quarter_source_status"
            ),
        },
        "multi_account_audit": {
            "required_accel_inputs_recoverable": (
                multi_required_ready
            ),
            "full_quarter_contract_recoverable": (
                multi_full_ready
            ),
            "period_values": multi_values,
            "q2_candidate": multi_candidate,
            "http_attempted": int(
                multi_client.attempted
            ),
            "http_successful": int(
                multi_client.successful
            ),
            "official_013_count": sum(
                1
                for x in multi_client.dart_status_failures
                if "|013|" in str(x)
            ),
            "hard_failure_count": 0,
        },
        "full_account_audit": {
            "required_accel_inputs_recoverable": (
                full_required_ready
            ),
            "full_quarter_contract_recoverable": (
                full_full_ready
            ),
            "period_values": full_values,
            "q2_candidate": full_candidate,
            "http_attempted": int(
                full_client.attempted
            ),
            "http_successful": int(
                full_client.successful
            ),
            "official_013_count": sum(
                1
                for x in full_client.dart_status_failures
                if "|013|" in str(x)
            ),
            "hard_failure_count": 0,
        },
        "selected_candidate_source": (
            candidate_source
        ),
        "candidate_s_accel": {
            "points": accel_points,
            "reason": accel_reason,
            "resolved_missing_accel_input": (
                scorer_required_recoverable
            ),
        },
        "classification": classification,
        "exact_da_exhausted_union_count": 64,
        "hard_guards": {
            "production_source_cache_modified": False,
            "production_source_run_log_modified": False,
            "production_financial_cache_modified": False,
            "production_ocf_cache_modified": False,
            "production_supply_source_modified": False,
            "production_price_elasticity_cache_modified": False,
            "production_api_modified": False,
            "production_score_written": False,
            "scoring_policy_modified": False,
            "source_contract_modified": False,
            "source_value_imputed": False,
            "q2_value_promoted": False,
        },
        "next_step": next_step,
    }

    OUT_JSON.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY_CURRENT_ACTIONABLE_SCORE_CACHE_Q2",
            f"TARGET={TICKER}",
            "BLOCKER=MISSING_ACCEL_INPUT",
            (
                "MULTI_REQUIRED_RECOVERABLE="
                + (
                    "true"
                    if multi_required_ready
                    else "false"
                )
            ),
            (
                "MULTI_FULL_QUARTER_READY="
                + (
                    "true"
                    if multi_full_ready
                    else "false"
                )
            ),
            (
                "FULL_REQUIRED_RECOVERABLE="
                + (
                    "true"
                    if full_required_ready
                    else "false"
                )
            ),
            (
                "FULL_FULL_QUARTER_READY="
                + (
                    "true"
                    if full_full_ready
                    else "false"
                )
            ),
            (
                "SELECTED_CANDIDATE_SOURCE="
                + candidate_source
            ),
            (
                "ACCEL_RESOLVED="
                + (
                    "true"
                    if scorer_required_recoverable
                    else "false"
                )
            ),
            f"CLASSIFICATION={classification}",
            "EXACT_DA_EXHAUSTED_UNION=64",
            "PRODUCTION_DATA_MODIFIED=false",
            "SCORING_POLICY_MODIFIED=false",
            "SOURCE_CONTRACT_MODIFIED=false",
            "Q2_VALUE_PROMOTED=false",
            "STATUS_OK=true",
            f"NEXT_STEP={next_step}",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUT_DOC.write_text(
        "\n".join([
            "# V8.14.3 ESR Kendall Q2 score-cache audit",
            "",
            "- Target: ESR켄달스퀘어리츠 (365550).",
            "- Current blocker: `최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT`.",
            "- First audit lane: existing V8.11.7 multi-account source contract.",
            "- Second audit lane: official full-account endpoint using the same account selector, only as evidence for a possible narrow source extension.",
            "- Q2 standalone is reconstructed only as H1 cumulative minus Q1 cumulative for 2026 and 2025.",
            "- The scorer-required lane uses revenue and operating profit only; net income completeness is reported separately.",
            "- No source value is promoted in this step.",
            "",
            f"Classification: `{classification}`",
            f"Next: `{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        "V8143_ESR_Q2_SCORE_CACHE_AUDIT=PASS"
    )

if __name__ == "__main__":
    main()
