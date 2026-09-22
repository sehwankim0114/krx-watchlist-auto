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
import investment_score_score_cache_actionable_v8143 as prior

VERSION = "2026-09-22-v8.15.5-mastern-q2-score-cache-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
SOURCE_CONTRACT_VERSION = (
    "2026-09-16-v8.11.7-five-financial-cis-interest-revenue-contract"
)
V8153_VERSION = "2026-09-22-v8.15.3-post-supply-dynamic-blocker-reaudit"
V8154_VERSION = "2026-09-22-v8.15.4-current-actionable-exact-da-3-audit"
V8154_RESULT_COMMIT = "529565ddca697516610dcf3e2dd379ec7146a6db"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8153.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8153_summary_latest.json"
DA_JSON = ROOT / "latest/investment_score_exact_da_actionable_v8154_summary_latest.json"
RAW = ROOT / "latest/investment_score_source_cache_latest.csv"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"

OUT_CSV = ROOT / "latest/investment_score_score_cache_actionable_v8155.csv"
OUT_JSON = ROOT / "latest/investment_score_score_cache_actionable_v8155_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_score_cache_actionable_v8155_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_score_cache_actionable_v8155.md"

TICKER = "357430"
NAME = "마스턴프리미어리츠"
CORP_CODE = "01442966"

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

def main():
    api_key = os.environ.get(
        "DART_API_KEY",
        "",
    ).strip()
    if not api_key:
        raise RuntimeError(
            "V8155_DART_API_KEY_MISSING"
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
                "V8155_MISSING_INPUT:" + str(p)
            )

    subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            V8154_RESULT_COMMIT,
            "HEAD",
        ],
        check=True,
    )

    block_summary = read_json(BLOCK_JSON)
    da_summary = read_json(DA_JSON)

    if block_summary.get("version") != V8153_VERSION:
        raise RuntimeError(
            "V8155_V8153_VERSION_MISMATCH"
        )
    if block_summary.get("status") != (
        "AUDIT_ONLY_POST_SUPPLY_DYNAMIC_CURRENT_BLOCKERS"
    ):
        raise RuntimeError(
            "V8155_V8153_STATUS_MISMATCH"
        )
    if block_summary.get("policy_version") != POLICY_VERSION:
        raise RuntimeError(
            "V8155_POLICY_VERSION_MISMATCH"
        )

    actionable = (
        block_summary.get("actionable_single_priority")
        or []
    )
    source_cache_entry = next(
        (
            x for x in actionable
            if x.get("source_group")
            == "INVESTMENT_SCORE_SOURCE_CACHE"
        ),
        None,
    )
    if not source_cache_entry:
        raise RuntimeError(
            "V8155_SOURCE_CACHE_ACTIONABLE_GROUP_MISSING"
        )
    if source_cache_entry.get(
        "actionable_single_blocker_tickers"
    ) != [TICKER]:
        raise RuntimeError(
            "V8155_SOURCE_CACHE_TARGET_CHANGED"
        )

    if da_summary.get("version") != V8154_VERSION:
        raise RuntimeError(
            "V8155_V8154_VERSION_MISMATCH"
        )
    if da_summary.get("status") != (
        "AUDIT_ONLY_CURRENT_ACTIONABLE_EXACT_DA"
    ):
        raise RuntimeError(
            "V8155_V8154_STATUS_MISMATCH"
        )
    if da_summary.get("next_step") != (
        "AUDIT_NEXT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8155"
    ):
        raise RuntimeError(
            "V8155_PREDECESSOR_NEXT_STEP_MISMATCH"
        )
    if int(
        da_summary.get(
            "post_audit_exhausted_union_count"
        ) or 0
    ) != 67:
        raise RuntimeError(
            "V8155_DA_EXHAUSTED_UNION_NOT_67"
        )
    if int(
        da_summary.get(
            "both_approved_exact_recoverable_count"
        ) or 0
    ) != 0:
        raise RuntimeError(
            "V8155_V8154_RECOVERABLE_NOT_ZERO"
        )

    block_rows = [
        r
        for r in read_rows(BLOCK_CSV)
        if ticker(r.get("ticker")) == TICKER
    ]
    if len(block_rows) != 1:
        raise RuntimeError(
            "V8155_TARGET_BLOCKER_ROW_COUNT_NOT_1"
        )
    blocker = block_rows[0]
    if blocker.get("name") != NAME:
        raise RuntimeError(
            "V8155_TARGET_NAME_MISMATCH"
        )
    if blocker.get("source_group") != (
        "INVESTMENT_SCORE_SOURCE_CACHE"
    ):
        raise RuntimeError(
            "V8155_SOURCE_GROUP_CHANGED"
        )
    if blocker.get("blocker_reason") != (
        "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT"
    ):
        raise RuntimeError(
            "V8155_BLOCKER_REASON_CHANGED:"
            + str(blocker.get("blocker_reason"))
        )
    if blocker.get("single_blocker_ticker") != "TRUE":
        raise RuntimeError(
            "V8155_TARGET_NOT_SINGLE_BLOCKER"
        )
    if blocker.get("recovery_status") != (
        "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
    ):
        raise RuntimeError(
            "V8155_TARGET_NOT_ACTIONABLE"
        )

    raw_rows = {
        ticker(r.get("ticker")): r
        for r in read_rows(RAW)
        if ticker(r.get("ticker"))
    }
    raw = raw_rows.get(TICKER)
    if not raw:
        raise RuntimeError(
            "V8155_SOURCE_CACHE_TARGET_MISSING"
        )
    if raw.get("name") != NAME:
        raise RuntimeError(
            "V8155_SOURCE_CACHE_NAME_MISMATCH"
        )
    if raw.get("corp_code") != CORP_CODE:
        raise RuntimeError(
            "V8155_SOURCE_CACHE_CORP_MISMATCH"
        )
    if raw.get("source_contract_version") != (
        SOURCE_CONTRACT_VERSION
    ):
        raise RuntimeError(
            "V8155_SOURCE_CONTRACT_VERSION_MISMATCH"
        )
    if raw.get("source_cache_status") != (
        "LIMITED_RAW_SOURCE"
    ):
        raise RuntimeError(
            "V8155_SOURCE_CACHE_STATUS_CHANGED"
        )
    if "QUARTER_LIMITED" not in (
        raw.get("source_cache_reason") or ""
    ):
        raise RuntimeError(
            "V8155_SOURCE_CACHE_REASON_CHANGED"
        )
    if raw.get("quarter_source_status") != "LIMITED":
        raise RuntimeError(
            "V8155_QUARTER_STATUS_CHANGED"
        )
    if raw.get("three_year_source_status") != "READY":
        raise RuntimeError(
            "V8155_3Y_SOURCE_NOT_READY"
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
                "V8155_EXPECTED_Q2_FIELD_ALREADY_PRESENT:"
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
            "V8155_FIN_TARGET_MISSING"
        )
    if fin.get("name") != NAME:
        raise RuntimeError(
            "V8155_FIN_NAME_MISMATCH"
        )
    if fin.get("corp_code") != CORP_CODE:
        raise RuntimeError(
            "V8155_FIN_CORP_MISMATCH"
        )
    if fin.get("corp_identity_status") not in {
        "MATCH",
        "MATCH_NORMALIZED",
    }:
        raise RuntimeError(
            "V8155_FIN_IDENTITY_NOT_MATCH"
        )
    if fin.get("financial_report_year") != "2026":
        raise RuntimeError(
            "V8155_FIN_YEAR_CHANGED"
        )
    if fin.get("financial_report_code") != "11012":
        raise RuntimeError(
            "V8155_FIN_REPORT_CODE_CHANGED"
        )

    financial_df = src.read_csv(FIN)
    targets = src.load_targets(
        financial_df
    )
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
            "V8155_DOMINANT_PERIOD_CHANGED"
        )

    target_map = {
        t["ticker"]: t
        for t in targets
    }
    target = target_map.get(TICKER)
    if not target:
        raise RuntimeError(
            "V8155_TARGET_MAPPING_MISSING"
        )
    if target.get("corp_code") != CORP_CODE:
        raise RuntimeError(
            "V8155_TARGET_MAPPING_CORP_MISMATCH"
        )
    if target.get("preferred_fs_div") != "CFS":
        raise RuntimeError(
            "V8155_PREFERRED_FS_CHANGED:"
            + str(target.get("preferred_fs_div"))
        )

    # Reuse the already-reviewed V8.14.3 official-query contract.
    prior.TICKER = TICKER
    prior.NAME = NAME
    prior.CORP_CODE = CORP_CODE

    multi_client = src.OpenDartClient(
        api_key,
        timeout=30,
    )
    multi_periods, multi_hard = (
        prior.query_multi_current_contract(
            multi_client,
            target,
        )
    )
    if multi_client.transport_failures:
        raise RuntimeError(
            "V8155_MULTI_TRANSPORT_FAILURE:"
            + "|".join(
                multi_client.transport_failures
            )
        )
    if multi_hard:
        raise RuntimeError(
            "V8155_MULTI_HARD_DART_FAILURE:"
            + "|".join(multi_hard)
        )

    multi_values = prior.period_values(
        multi_periods
    )
    multi_required_ready = (
        prior.required_recoverable(
            multi_values
        )
    )
    multi_full_ready = (
        prior.full_quarter_contract_recoverable(
            multi_values
        )
    )
    multi_candidate = prior.q2_candidate(
        multi_values
    )

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
    ) in prior.PERIODS:
        period, hard = (
            prior.query_full_account_period(
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
            "V8155_FULL_TRANSPORT_FAILURE:"
            + "|".join(
                full_client.transport_failures
            )
        )
    if full_hard:
        raise RuntimeError(
            "V8155_FULL_HARD_DART_FAILURE:"
            + "|".join(full_hard)
        )

    full_values = prior.period_values(
        full_periods
    )
    full_required_ready = (
        prior.required_recoverable(
            full_values
        )
    )
    full_full_ready = (
        prior.full_quarter_contract_recoverable(
            full_values
        )
    )
    full_candidate = prior.q2_candidate(
        full_values
    )

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
        shadow = dict(raw)
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
            "V8155_CANDIDATE_STILL_MISSING_ACCEL:"
            + str(accel_reason)
        )

    if multi_required_ready:
        classification = (
            "RECOVERABLE_CURRENT_SOURCE_CONTRACT"
        )
        next_step = (
            "FREEZE_RECOVERABLE_MASTERN_Q2_AND_SHADOW_SCORE_V8156"
        )
    elif full_required_ready:
        classification = (
            "RECOVERABLE_FULL_ACCOUNT_NARROW_EXTENSION_CANDIDATE"
        )
        next_step = (
            "STAGE_NARROW_MASTERN_Q2_SOURCE_EXTENSION_AND_SHADOW_V8156"
        )
    else:
        classification = (
            "NO_COMPLETE_OFFICIAL_Q2_ACCEL_INPUT_PATH"
        )
        next_step = (
            "MARK_MASTERN_Q2_PATH_EXHAUSTED_AND_DYNAMIC_REAUDIT_V8156"
        )

    row = {
        "ticker": TICKER,
        "name": NAME,
        "corp_code": CORP_CODE,
        "blocker_reason": (
            blocker.get("blocker_reason") or ""
        ),
        "source_cache_status": (
            raw.get("source_cache_status") or ""
        ),
        "source_cache_reason": (
            raw.get("source_cache_reason") or ""
        ),
        "quarter_source_status": (
            raw.get("quarter_source_status") or ""
        ),
        "multi_required_recoverable": (
            "TRUE"
            if multi_required_ready
            else "FALSE"
        ),
        "multi_full_quarter_ready": (
            "TRUE"
            if multi_full_ready
            else "FALSE"
        ),
        "full_required_recoverable": (
            "TRUE"
            if full_required_ready
            else "FALSE"
        ),
        "full_full_quarter_ready": (
            "TRUE"
            if full_full_ready
            else "FALSE"
        ),
        "selected_candidate_source": (
            candidate_source
        ),
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
        "candidate_accel_reason": (
            accel_reason
        ),
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
        "source_contract_version": (
            SOURCE_CONTRACT_VERSION
        ),
        "v8154_version": V8154_VERSION,
        "v8154_result_commit": (
            V8154_RESULT_COMMIT
        ),
        "target_ticker": TICKER,
        "target_name": NAME,
        "target_corp_code": CORP_CODE,
        "blocker_reason": (
            "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT"
        ),
        "exact_da_exhausted_union_count": 67,
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
            "three_year_source_status": raw.get(
                "three_year_source_status"
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
            "exhausted_da_lane_requeried": False,
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
            "EXACT_DA_EXHAUSTED_UNION=67",
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
            (
                "MULTI_HTTP_ATTEMPTED="
                + str(multi_client.attempted)
            ),
            (
                "MULTI_HTTP_SUCCESSFUL="
                + str(multi_client.successful)
            ),
            (
                "FULL_HTTP_ATTEMPTED="
                + str(full_client.attempted)
            ),
            (
                "FULL_HTTP_SUCCESSFUL="
                + str(full_client.successful)
            ),
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
            "# V8.15.5 Mastern Premier REIT Q2 score-cache audit",
            "",
            "- Target: 마스턴프리미어리츠 (357430).",
            "- Current sole blocker: `최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT`.",
            "- Existing V8.11.7 multi-account contract is audited first.",
            "- Official full-account endpoint is independently audited using the same account selector.",
            "- Q2 is reconstructed only as H1 cumulative minus Q1 cumulative for 2026 and 2025.",
            "- Revenue and operating profit are the scorer-required inputs; net-income completeness is reported separately.",
            "- No Q2 value or source-contract change is promoted in this audit step.",
            "- Exact-D&A exhausted union 67 is preserved and not queried.",
            "",
            f"Classification: `{classification}`",
            f"Next: `{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        "V8155_MASTERN_Q2_SCORE_CACHE_AUDIT=PASS"
    )

if __name__ == "__main__":
    main()
