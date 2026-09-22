#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import subprocess
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_source_enricher_v854 as src
import investment_score_exact_da_actionable_v8142 as prior

VERSION = "2026-09-22-v8.15.4-current-actionable-exact-da-3-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8153_VERSION = "2026-09-22-v8.15.3-post-supply-dynamic-blocker-reaudit"
V8153_RESULT_COMMIT = "82dd6da357eb6477bccb69cc4f7b09a18bf99142"
V8142_VERSION = "2026-09-22-v8.14.2-current-actionable-exact-da-single-blocker-audit"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8153.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8153_summary_latest.json"
V8142_JSON = ROOT / "latest/investment_score_exact_da_actionable_v8142_summary_latest.json"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"

OUT_CSV = ROOT / "latest/investment_score_exact_da_actionable_v8154.csv"
OUT_JSON = ROOT / "latest/investment_score_exact_da_actionable_v8154_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_exact_da_actionable_v8154_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_exact_da_actionable_v8154.md"

EXPECTED = {
    "001790": "대한제당",
    "053690": "한미글로벌",
    "204320": "HL만도",
}

EXPECTED_CORP = {
    "001790": "00113234",
    "053690": "00413523",
    "204320": "01042775",
}

ALLOWED_BLOCKERS = {
    "EV/EBITDA:EV_EBITDA_INPUT:OK:NO_EXACT_CANDIDATE",
    "EV/EBITDA:EV_EBITDA_INPUT:EMPTY_AS_ZERO:NO_EXACT_CANDIDATE",
}

def ticker(value):
    s = "".join(
        ch for ch in str(value or "")
        if ch.isdigit()
    )
    return s.zfill(6) if s else ""

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

def parse_list(value):
    try:
        data = json.loads(str(value or ""))
    except Exception:
        return []
    return data if isinstance(data, list) else []

def main():
    api_key = os.environ.get(
        "DART_API_KEY",
        "",
    ).strip()
    if not api_key:
        raise RuntimeError(
            "V8154_DART_API_KEY_MISSING"
        )

    for path in (
        BLOCK_CSV,
        BLOCK_JSON,
        V8142_JSON,
        FIN,
    ):
        if not path.is_file():
            raise RuntimeError(
                "V8154_MISSING_INPUT:" + str(path)
            )

    subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            V8153_RESULT_COMMIT,
            "HEAD",
        ],
        check=True,
    )

    s8153 = read_json(BLOCK_JSON)
    s8142 = read_json(V8142_JSON)

    if s8153.get("version") != V8153_VERSION:
        raise RuntimeError(
            "V8154_V8153_VERSION_MISMATCH"
        )
    if s8153.get("status") != (
        "AUDIT_ONLY_POST_SUPPLY_DYNAMIC_CURRENT_BLOCKERS"
    ):
        raise RuntimeError(
            "V8154_V8153_STATUS_MISMATCH"
        )
    if s8153.get("policy_version") != POLICY_VERSION:
        raise RuntimeError(
            "V8154_POLICY_VERSION_MISMATCH"
        )
    if s8153.get("selection_mode") != (
        "ACTIONABLE_SINGLE_BLOCKER"
    ):
        raise RuntimeError(
            "V8154_SELECTION_MODE_CHANGED"
        )
    if s8153.get("selected_source_group") != (
        "EXACT_DA_SOURCE"
    ):
        raise RuntimeError(
            "V8154_SELECTED_GROUP_CHANGED"
        )
    if set(
        s8153.get("selected_tickers") or []
    ) != set(EXPECTED):
        raise RuntimeError(
            "V8154_SELECTED_TARGETS_CHANGED"
        )
    if s8153.get("next_step") != (
        "AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8154"
    ):
        raise RuntimeError(
            "V8154_PREDECESSOR_NEXT_STEP_MISMATCH"
        )

    if s8142.get("version") != V8142_VERSION:
        raise RuntimeError(
            "V8154_V8142_VERSION_MISMATCH"
        )
    exhausted = set(
        s8142.get(
            "post_audit_exhausted_union_tickers"
        ) or []
    )
    if len(exhausted) != 64:
        raise RuntimeError(
            "V8154_PRIOR_EXHAUSTED_NOT_64"
        )
    overlap = set(EXPECTED) & exhausted
    if overlap:
        raise RuntimeError(
            "V8154_TARGET_OVERLAPS_EXHAUSTED:"
            + ",".join(sorted(overlap))
        )

    block_rows = read_rows(BLOCK_CSV)
    actionable = {
        ticker(r.get("ticker")): r
        for r in block_rows
        if r.get("source_group") == "EXACT_DA_SOURCE"
        and str(
            r.get("single_blocker_ticker") or ""
        ).upper() == "TRUE"
        and r.get("recovery_status") == (
            "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
        )
    }

    if set(actionable) != set(EXPECTED):
        raise RuntimeError(
            "V8154_ACTIONABLE_SET_MISMATCH:"
            + ",".join(sorted(actionable))
        )

    for code, name in EXPECTED.items():
        row = actionable[code]
        if row.get("name") != name:
            raise RuntimeError(
                "V8154_NAME_MISMATCH:" + code
            )
        if row.get("blocker_reason") not in ALLOWED_BLOCKERS:
            raise RuntimeError(
                "V8154_BLOCKER_REASON_CHANGED:"
                + code
                + ":"
                + str(row.get("blocker_reason"))
            )

    fin_map = {
        ticker(r.get("ticker")): r
        for r in read_rows(FIN)
        if ticker(r.get("ticker"))
    }

    for code, name in EXPECTED.items():
        row = fin_map.get(code)
        if not row:
            raise RuntimeError(
                "V8154_FIN_TARGET_MISSING:" + code
            )
        if row.get("name") != name:
            raise RuntimeError(
                "V8154_FIN_NAME_CHANGED:" + code
            )
        if row.get("corp_identity_status") not in {
            "MATCH",
            "MATCH_NORMALIZED",
        }:
            raise RuntimeError(
                "V8154_FIN_IDENTITY_NOT_MATCH:" + code
            )
        if str(row.get("corp_code") or "") != EXPECTED_CORP[code]:
            raise RuntimeError(
                "V8154_CORP_CODE_CHANGED:" + code
            )

    financial_df = src.read_csv(FIN)
    all_targets = src.load_targets(
        financial_df
    )
    dominant_year, dominant_code = (
        src.dominant_period(
            all_targets
        )
    )
    annual_year = dominant_year - 1

    if (
        dominant_year != 2026
        or str(dominant_code) != "11012"
        or annual_year != 2025
    ):
        raise RuntimeError(
            "V8154_FINANCIAL_PERIOD_CHANGED:"
            f"{dominant_year}_{dominant_code}_{annual_year}"
        )

    target_map = {
        t["ticker"]: t
        for t in all_targets
    }
    missing = sorted(
        code
        for code in EXPECTED
        if code not in target_map
    )
    if missing:
        raise RuntimeError(
            "V8154_TARGET_MAP_MISSING:"
            + ",".join(missing)
        )

    for code in EXPECTED:
        target = target_map[code]
        if str(
            target.get("corp_code") or ""
        ) != EXPECTED_CORP[code]:
            raise RuntimeError(
                "V8154_TARGET_MAP_CORP_CHANGED:"
                + code
            )

    client = src.OpenDartClient(
        api_key,
        timeout=30,
    )

    out_rows = []
    class_counts = Counter()
    lane_counts = Counter()
    recoverable = []
    partial = []
    no_exact = []
    incomplete = []
    conflict = []

    for code in sorted(EXPECTED):
        target = target_map[code]

        fresh = src.fetch_deep_one(
            client,
            target,
            annual_year,
        )

        candidates = parse_list(
            fresh.get("da_json")
        )
        stats = prior.exact_stats(
            candidates
        )
        classification = prior.classify(
            stats
        )
        lane = prior.recovery_lane(
            classification,
            str(
                fresh.get("status") or ""
            ),
        )

        dep = stats[
            "ifrs-full_AdjustmentsForDepreciationExpense"
        ]
        amo = stats[
            "ifrs-full_AdjustmentsForAmortisationExpense"
        ]

        out_rows.append({
            "ticker": code,
            "name": EXPECTED[code],
            "corp_code": (
                target.get("corp_code") or ""
            ),
            "preferred_fs_div": (
                target.get("preferred_fs_div") or ""
            ),
            "dominant_financial_period": (
                f"{dominant_year}_{dominant_code}"
            ),
            "annual_source_year": annual_year,
            "fresh_deep_status": (
                fresh.get("status") or ""
            ),
            "fresh_deep_fs_div": (
                fresh.get("fs_div") or ""
            ),
            "fresh_deep_message": (
                fresh.get("message") or ""
            ),
            "fresh_exact_classification": (
                classification
            ),
            "recovery_lane": lane,
            "approved_depreciation_occurrences": (
                dep["occurrence_count"]
            ),
            "approved_depreciation_values_json": json.dumps(
                dep["unique_numeric_values"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "approved_amortisation_occurrences": (
                amo["occurrence_count"]
            ),
            "approved_amortisation_values_json": json.dumps(
                amo["unique_numeric_values"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "fresh_exact_stats_json": json.dumps(
                stats,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "fresh_da_candidates_json": json.dumps(
                candidates,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        })

        class_counts[classification] += 1
        lane_counts[lane] += 1

        if lane == (
            "RECOVERABLE_BOTH_EXACT_SHADOW_CANDIDATE"
        ):
            recoverable.append(code)
        elif lane == "PARTIAL_ONLY_DO_NOT_PROMOTE":
            partial.append(code)
        elif lane == (
            "NO_APPROVED_EXACT_CURRENT_OFFICIAL_PATH"
        ):
            no_exact.append(code)
        elif lane == "OFFICIAL_QUERY_INCOMPLETE":
            incomplete.append(code)
        elif lane in {
            "CONFLICT_FAIL_CLOSED",
            "NONUNIQUE_OR_NONNUMERIC_FAIL_CLOSED",
        }:
            conflict.append(code)

        time.sleep(0.20)

    if len(out_rows) != 3:
        raise RuntimeError(
            "V8154_OUTPUT_COUNT_NOT_3"
        )

    if incomplete:
        raise RuntimeError(
            "V8154_OFFICIAL_QUERY_INCOMPLETE:"
            + ",".join(sorted(incomplete))
        )

    if (
        int(client.attempted) != 3
        or int(client.successful) != 3
    ):
        raise RuntimeError(
            "V8154_OPENDART_REQUEST_COUNT_BAD:"
            f"{client.attempted}:{client.successful}"
        )

    if (
        client.transport_failures
        or client.dart_status_failures
    ):
        raise RuntimeError(
            "V8154_OPENDART_FAILURE_PRESENT"
        )

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
            fieldnames=list(
                out_rows[0].keys()
            ),
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(out_rows)

    post_exhausted = exhausted | set(
        no_exact
    )

    if partial or conflict:
        next_step = (
            "REVIEW_EXACT_DA_AMBIGUITY_BEFORE_CONTINUING"
        )
    elif recoverable:
        next_step = (
            "FREEZE_RECOVERABLE_EXACT_DA_AND_SHADOW_SCORE_V8155"
        )
    else:
        next_step = (
            "AUDIT_NEXT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8155"
        )

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(
            KST
        ).isoformat(timespec="seconds"),
        "status": (
            "AUDIT_ONLY_CURRENT_ACTIONABLE_EXACT_DA"
        ),
        "policy_version": POLICY_VERSION,
        "v8153_version": V8153_VERSION,
        "v8153_result_commit": (
            V8153_RESULT_COMMIT
        ),
        "v8142_version": V8142_VERSION,
        "approved_exact_account_ids": sorted(
            prior.APPROVED
        ),
        "target_count": 3,
        "target_tickers": sorted(EXPECTED),
        "target_names": [
            EXPECTED[x]
            for x in sorted(EXPECTED)
        ],
        "prior_exhausted_not_requeried_count": (
            len(exhausted)
        ),
        "prior_exhausted_not_requeried_tickers": sorted(
            exhausted
        ),
        "dominant_financial_period": (
            f"{dominant_year}_{dominant_code}"
        ),
        "annual_source_year": annual_year,
        "classification_counts": dict(
            class_counts
        ),
        "recovery_lane_counts": dict(
            lane_counts
        ),
        "both_approved_exact_recoverable_count": len(
            recoverable
        ),
        "both_approved_exact_recoverable_tickers": sorted(
            recoverable
        ),
        "partial_only_count": len(partial),
        "partial_only_tickers": sorted(
            partial
        ),
        "no_approved_exact_count": len(
            no_exact
        ),
        "no_approved_exact_tickers": sorted(
            no_exact
        ),
        "newly_exhausted_no_approved_exact_count": len(
            no_exact
        ),
        "newly_exhausted_no_approved_exact_tickers": sorted(
            no_exact
        ),
        "post_audit_exhausted_union_count": len(
            post_exhausted
        ),
        "post_audit_exhausted_union_tickers": sorted(
            post_exhausted
        ),
        "official_query_incomplete_count": 0,
        "official_query_incomplete_tickers": [],
        "conflict_or_nonunique_count": len(
            conflict
        ),
        "conflict_or_nonunique_tickers": sorted(
            conflict
        ),
        "opendart_attempted_requests": int(
            client.attempted
        ),
        "opendart_successful_requests": int(
            client.successful
        ),
        "opendart_transport_failure_count": 0,
        "opendart_dart_status_failure_count": 0,
        "remaining_actionable_single_group_hint": {
            "source_group": (
                "INVESTMENT_SCORE_SOURCE_CACHE"
            ),
            "tickers": [
                "357430"
            ],
        },
        "hard_guards": {
            "production_source_cache_modified": False,
            "production_source_run_log_modified": False,
            "production_financial_cache_modified": False,
            "production_price_elasticity_cache_modified": False,
            "production_ocf_cache_modified": False,
            "production_supply_source_modified": False,
            "production_api_modified": False,
            "production_investment_score_written": False,
            "scoring_policy_modified": False,
            "source_value_imputed": False,
            "new_da_account_id_approved": False,
            "prior_exhausted_lane_requeried": False,
            "source_promoted": False,
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
            "STATUS=AUDIT_ONLY_CURRENT_ACTIONABLE_EXACT_DA",
            "TARGET_COUNT=3",
            "TARGET_AVAILABLE=3",
            "TARGET_MISSING=0",
            (
                "BOTH_APPROVED_EXACT_RECOVERABLE="
                + str(len(recoverable))
            ),
            f"PARTIAL_ONLY={len(partial)}",
            f"NO_APPROVED_EXACT={len(no_exact)}",
            "OFFICIAL_QUERY_INCOMPLETE=0",
            f"CONFLICT_OR_NONUNIQUE={len(conflict)}",
            f"OPENDART_ATTEMPTED={client.attempted}",
            f"OPENDART_SUCCESSFUL={client.successful}",
            "OPENDART_TRANSPORT_FAILURES=0",
            "OPENDART_STATUS_FAILURES=0",
            f"PRIOR_EXHAUSTED_COUNT={len(exhausted)}",
            (
                "POST_EXHAUSTED_COUNT="
                + str(len(post_exhausted))
            ),
            "PRIOR_EXHAUSTED_LANE_REQUERIED=false",
            "SOURCE_PROMOTED=false",
            "SCORING_POLICY_MODIFIED=false",
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
            "# V8.15.4 current actionable exact D&A audit",
            "",
            "- Targets: 대한제당 (001790), 한미글로벌 (053690), HL만도 (204320).",
            "- All three are current EXACT_DA_SOURCE single blockers.",
            f"- Prior exhausted exact-D&A targets not re-queried: {len(exhausted)}.",
            f"- Both approved exact recoverable: {len(recoverable)}.",
            f"- Partial only: {len(partial)}.",
            f"- No approved exact: {len(no_exact)}.",
            f"- Conflict/nonunique: {len(conflict)}.",
            "",
            "Only the two already-approved exact D&A account IDs are accepted.",
            "Missing D&A is never treated as zero; partial/conflicting evidence is not promoted.",
            "Any incomplete official query fails before commit.",
            "This step is audit-only and does not modify production.",
            "",
            f"Next: `{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        "V8154_CURRENT_ACTIONABLE_EXACT_DA_AUDIT=PASS"
    )

if __name__ == "__main__":
    main()
