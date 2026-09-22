#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer
from investment_score_current_blocker_reaudit_v8148 import classify

VERSION = "2026-09-22-v8.15.6-mastern-q2-exhausted-dynamic-reaudit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8154_VERSION = "2026-09-22-v8.15.4-current-actionable-exact-da-3-audit"
V8155_VERSION = "2026-09-22-v8.15.5-mastern-q2-score-cache-audit"
V8155_RESULT_COMMIT = "8cbbc7bf7dcfc6213501d8564eecd07648dfe671"
V8143_VERSION = "2026-09-22-v8.14.3-esr-kendall-q2-score-cache-audit"
V8104_VERSION = "2026-09-15-v8.10.4-next-single-source-recoverability-audit"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

DA_JSON = ROOT / "latest/investment_score_exact_da_actionable_v8154_summary_latest.json"
ESR_JSON = ROOT / "latest/investment_score_score_cache_actionable_v8143_summary_latest.json"
MASTERN_JSON = ROOT / "latest/investment_score_score_cache_actionable_v8155_summary_latest.json"
V8104_JSON = ROOT / "latest/investment_score_next_single_source_v8104_summary_latest.json"
MANIFEST = ROOT / "api/two_table_v1/manifest.json"

TMP_CSV = Path("/tmp/v8156_score.csv")
TMP_JSON = Path("/tmp/v8156_score_summary.json")
TMP_LOG = Path("/tmp/v8156_score.log")
TMP_DOC = Path("/tmp/v8156_score.md")

OUT_CSV = ROOT / "latest/investment_score_current_blockers_v8156.csv"
OUT_JSON = ROOT / "latest/investment_score_current_blockers_v8156_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_current_blockers_v8156_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_current_blockers_v8156.md"

ESR = "365550"
MASTERN = "357430"
Q2_REASON = "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT"
UANGEL = "072130"

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

def split_reasons(value):
    return [
        x
        for x in str(value or "").split(";")
        if x
    ]

def recovery_status(
    code,
    reason,
    group,
    single,
    da_exhausted,
    v8104_exhausted,
):
    if group == "V880_SCORING_CONTRACT":
        return "POLICY_SEMANTIC_DEFER"

    if (
        group == "EXACT_DA_SOURCE"
        and code in da_exhausted
    ):
        return "EXHAUSTED_APPROVED_OFFICIAL_DA_PATHS"

    if (
        code in {ESR, MASTERN}
        and group == "INVESTMENT_SCORE_SOURCE_CACHE"
        and reason == Q2_REASON
    ):
        return "EXHAUSTED_OFFICIAL_Q2_ACCEL_PATH"

    if (
        code == "001020"
        and code in v8104_exhausted
        and group == "PRODUCTION_PRICE_METRICS"
    ):
        return "EXHAUSTED_V8104_OFFICIAL_KRX_OHLC_INCOMPLETE"

    if (
        code == "357250"
        and code in v8104_exhausted
        and group == "INVESTMENT_SCORE_SOURCE_CACHE"
    ):
        return "EXHAUSTED_V8104_OFFICIAL_FULL_ACCOUNT_INCOMPLETE"

    if single:
        return "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"

    return "MULTI_BLOCKER_SOURCE_LANE"

def run_scorer():
    old = {
        "VERSION": scorer.VERSION,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = VERSION
        scorer.OUT_CSV = TMP_CSV
        scorer.OUT_JSON = TMP_JSON
        scorer.OUT_LOG = TMP_LOG
        scorer.OUT_DOC = TMP_DOC
        rc = scorer.main()
    finally:
        for key, value in old.items():
            setattr(scorer, key, value)

    if rc not in (None, 0):
        raise RuntimeError(
            "V8156_SCORER_FAILED:" + str(rc)
        )

def main():
    for p in (
        DA_JSON,
        ESR_JSON,
        MASTERN_JSON,
        V8104_JSON,
        MANIFEST,
    ):
        if not p.is_file():
            raise RuntimeError(
                "V8156_MISSING_INPUT:" + str(p)
            )

    da = read_json(DA_JSON)
    esr = read_json(ESR_JSON)
    mastern = read_json(MASTERN_JSON)
    v8104 = read_json(V8104_JSON)
    manifest = read_json(MANIFEST)

    if da.get("version") != V8154_VERSION:
        raise RuntimeError(
            "V8156_DA_VERSION_MISMATCH"
        )
    if da.get("status") != (
        "AUDIT_ONLY_CURRENT_ACTIONABLE_EXACT_DA"
    ):
        raise RuntimeError(
            "V8156_DA_STATUS_MISMATCH"
        )
    da_exhausted = set(
        da.get(
            "post_audit_exhausted_union_tickers"
        ) or []
    )
    if len(da_exhausted) != 67:
        raise RuntimeError(
            "V8156_DA_EXHAUSTED_NOT_67"
        )
    if not {
        "001790",
        "053690",
        "204320",
    }.issubset(da_exhausted):
        raise RuntimeError(
            "V8156_NEW_DA_EXHAUSTED_MISSING"
        )

    if esr.get("version") != V8143_VERSION:
        raise RuntimeError(
            "V8156_ESR_VERSION_MISMATCH"
        )
    if esr.get("classification") != (
        "NO_COMPLETE_OFFICIAL_Q2_ACCEL_INPUT_PATH"
    ):
        raise RuntimeError(
            "V8156_ESR_NOT_EXHAUSTED"
        )

    if mastern.get("version") != V8155_VERSION:
        raise RuntimeError(
            "V8156_MASTERN_VERSION_MISMATCH"
        )
    if mastern.get("status") != (
        "AUDIT_ONLY_CURRENT_ACTIONABLE_SCORE_CACHE_Q2"
    ):
        raise RuntimeError(
            "V8156_MASTERN_STATUS_MISMATCH"
        )
    if mastern.get("classification") != (
        "NO_COMPLETE_OFFICIAL_Q2_ACCEL_INPUT_PATH"
    ):
        raise RuntimeError(
            "V8156_MASTERN_NOT_EXHAUSTED"
        )
    if mastern.get("next_step") != (
        "MARK_MASTERN_Q2_PATH_EXHAUSTED_AND_DYNAMIC_REAUDIT_V8156"
    ):
        raise RuntimeError(
            "V8156_PREDECESSOR_NEXT_STEP_MISMATCH"
        )
    if mastern.get("target_ticker") != MASTERN:
        raise RuntimeError(
            "V8156_MASTERN_TARGET_CHANGED"
        )
    if (
        mastern.get("multi_account_audit", {}).get(
            "required_accel_inputs_recoverable"
        ) is not False
        or mastern.get("full_account_audit", {}).get(
            "required_accel_inputs_recoverable"
        ) is not False
    ):
        raise RuntimeError(
            "V8156_MASTERN_RECOVERABILITY_CHANGED"
        )
    if (
        mastern.get("multi_account_audit", {}).get(
            "hard_failure_count"
        ) != 0
        or mastern.get("full_account_audit", {}).get(
            "hard_failure_count"
        ) != 0
    ):
        raise RuntimeError(
            "V8156_MASTERN_AUDIT_HARD_FAILURE"
        )
    if any(
        bool(v)
        for v in (
            mastern.get("hard_guards") or {}
        ).values()
    ):
        raise RuntimeError(
            "V8156_MASTERN_HARD_GUARD_NOT_FALSE"
        )

    if v8104.get("version") != V8104_VERSION:
        raise RuntimeError(
            "V8156_V8104_VERSION_MISMATCH"
        )
    v8104_exhausted = set(
        v8104.get(
            "not_recoverable_now_tickers"
        ) or []
    )
    if v8104_exhausted != {
        "001020",
        "357250",
    }:
        raise RuntimeError(
            "V8156_V8104_EXHAUSTED_CHANGED"
        )

    if manifest.get("release_stage") != "PRODUCTION":
        raise RuntimeError(
            "V8156_MANIFEST_NOT_PRODUCTION"
        )
    if manifest.get(
        "production_activation_allowed"
    ) is not True:
        raise RuntimeError(
            "V8156_PRODUCTION_NOT_ALLOWED"
        )
    if manifest.get(
        "safe_to_analyze_as_latest"
    ) is not True:
        raise RuntimeError(
            "V8156_MANIFEST_NOT_SAFE_LATEST"
        )

    run_scorer()

    rows = read_rows(TMP_CSV)
    score_summary = read_json(TMP_JSON)

    if not rows:
        raise RuntimeError(
            "V8156_SCORER_EMPTY"
        )

    ready = [
        r for r in rows
        if r.get("score_status") == "READY"
    ]
    limited = [
        r for r in rows
        if r.get("score_status") == "LIMITED"
    ]

    if len(ready) + len(limited) != len(rows):
        raise RuntimeError(
            "V8156_SCORE_STATUS_MISMATCH"
        )
    if int(
        score_summary.get("ready_count") or 0
    ) != len(ready):
        raise RuntimeError(
            "V8156_READY_SUMMARY_MISMATCH"
        )
    if int(
        score_summary.get("limited_count") or 0
    ) != len(limited):
        raise RuntimeError(
            "V8156_LIMITED_SUMMARY_MISMATCH"
        )

    by_code = {
        ticker(r.get("ticker")): r
        for r in rows
    }
    ready_codes = {
        ticker(r.get("ticker"))
        for r in ready
    }

    if UANGEL in by_code:
        u = by_code[UANGEL]
        if u.get("score_status") != "READY":
            raise RuntimeError(
                "V8156_UANGEL_REGRESSED"
            )
        points = json.loads(
            u.get("component_points_json") or "{}"
        ).get("수급·공시부담")
        if points != 4:
            raise RuntimeError(
                "V8156_UANGEL_SUPPLY_POINTS_NOT_4"
            )

    for code in ("006260", "267250"):
        if (
            code in by_code
            and code not in ready_codes
        ):
            raise RuntimeError(
                "V8156_ELASTICITY_PROMOTION_REGRESSED:"
                + code
            )

    out_rows = []
    category_counts = Counter()
    source_counts = Counter()
    source_tickers = defaultdict(set)
    recovery_counts = Counter()
    actionable_counts = Counter()
    actionable_tickers = defaultdict(set)
    multi_counts = Counter()
    multi_tickers = defaultdict(set)

    for row in limited:
        reasons = split_reasons(
            row.get("missing_components")
        )
        code = ticker(row.get("ticker"))

        if not reasons:
            raise RuntimeError(
                "V8156_LIMITED_WITHOUT_REASON:"
                + code
            )

        single = len(reasons) == 1

        for reason in reasons:
            category, group = classify(reason)
            if group == "UNKNOWN":
                raise RuntimeError(
                    "V8156_UNCLASSIFIED_REASON:"
                    + code + ":" + reason
                )

            status = recovery_status(
                code,
                reason,
                group,
                single,
                da_exhausted,
                v8104_exhausted,
            )

            category_counts[category] += 1
            source_counts[group] += 1
            source_tickers[group].add(code)
            recovery_counts[status] += 1

            if (
                single
                and status
                == "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
            ):
                actionable_counts[group] += 1
                actionable_tickers[group].add(code)

            if not single:
                multi_counts[group] += 1
                multi_tickers[group].add(code)

            out_rows.append({
                "ticker": code,
                "name": row.get("name") or "",
                "market": row.get("market") or "",
                "missing_component_count": len(
                    reasons
                ),
                "blocker_reason": reason,
                "blocker_category": category,
                "source_group": group,
                "single_blocker_ticker": (
                    "TRUE" if single else "FALSE"
                ),
                "recovery_status": status,
            })

    # If these exhausted single blockers remain active, they must
    # no longer be classified as actionable.
    for code in (
        "001790",
        "053690",
        "204320",
        ESR,
        MASTERN,
    ):
        matching = [
            r for r in out_rows
            if r["ticker"] == code
        ]
        for r in matching:
            if r["recovery_status"] == (
                "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
            ):
                raise RuntimeError(
                    "V8156_EXHAUSTED_TARGET_STILL_ACTIONABLE:"
                    + code
                )

    single_priority = sorted(
        [
            {
                "source_group": group,
                "actionable_single_blocker_count": count,
                "actionable_single_blocker_tickers": sorted(
                    actionable_tickers[group]
                ),
                "total_group_blocker_occurrences": (
                    source_counts[group]
                ),
            }
            for group, count in actionable_counts.items()
            if count > 0
        ],
        key=lambda x: (
            -x["actionable_single_blocker_count"],
            -x["total_group_blocker_occurrences"],
            x["source_group"],
        ),
    )

    multi_priority = sorted(
        [
            {
                "source_group": group,
                "multi_blocker_occurrences": count,
                "multi_blocker_ticker_count": len(
                    multi_tickers[group]
                ),
                "multi_blocker_tickers": sorted(
                    multi_tickers[group]
                ),
                "total_group_blocker_occurrences": (
                    source_counts[group]
                ),
            }
            for group, count in multi_counts.items()
            if (
                count > 0
                and group != "V880_SCORING_CONTRACT"
            )
        ],
        key=lambda x: (
            -x["multi_blocker_occurrences"],
            -x["multi_blocker_ticker_count"],
            x["source_group"],
        ),
    )

    if single_priority:
        selection_mode = (
            "ACTIONABLE_SINGLE_BLOCKER"
        )
        selected = single_priority[0]
        selected_group = selected["source_group"]
        selected_tickers = selected[
            "actionable_single_blocker_tickers"
        ]
        next_step = (
            "AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8157"
        )
    elif multi_priority:
        selection_mode = "MULTI_BLOCKER_GROUP"
        selected = multi_priority[0]
        selected_group = selected["source_group"]
        selected_tickers = selected[
            "multi_blocker_tickers"
        ]
        next_step = (
            "AUDIT_TOP_MULTI_BLOCKER_GROUP_V8157"
        )
    else:
        selection_mode = "NO_SOURCE_LANE"
        selected_group = ""
        selected_tickers = []
        next_step = (
            "REVIEW_REMAINING_POLICY_ONLY_BLOCKERS"
        )

    out_rows.sort(
        key=lambda r: (
            int(r["missing_component_count"]),
            r["ticker"],
            r["blocker_reason"],
        )
    )

    OUT_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    fields = [
        "ticker",
        "name",
        "market",
        "missing_component_count",
        "blocker_reason",
        "blocker_category",
        "source_group",
        "single_blocker_ticker",
        "recovery_status",
    ]
    with OUT_CSV.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        w = csv.DictWriter(
            f,
            fieldnames=fields,
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(out_rows)

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(
            KST
        ).isoformat(timespec="seconds"),
        "status": (
            "AUDIT_ONLY_EXHAUSTION_AWARE_DYNAMIC_CURRENT_BLOCKERS"
        ),
        "policy_version": POLICY_VERSION,
        "v8155_version": V8155_VERSION,
        "v8155_result_commit": (
            V8155_RESULT_COMMIT
        ),
        "production_manifest": {
            "basis_date": manifest.get("basis_date"),
            "source_build_id": manifest.get(
                "source_build_id"
            ),
            "source_commit": manifest.get(
                "source_commit"
            ),
            "kospi_rows": manifest["tables"][
                "kospi"
            ]["row_count"],
            "decliners_rows": manifest["tables"][
                "decliners"
            ]["row_count"],
            "decliners24_rows": manifest["tables"][
                "decliners24"
            ]["row_count"],
        },
        "scorer_universe_count": len(rows),
        "ready_count": len(ready),
        "limited_count": len(limited),
        "limited_blocker_occurrences": len(
            out_rows
        ),
        "uangel_state": (
            "READY"
            if UANGEL in ready_codes
            else (
                "INACTIVE"
                if UANGEL not in by_code
                else "NOT_READY"
            )
        ),
        "blocker_category_counts": dict(
            category_counts
        ),
        "source_group_counts": dict(
            source_counts
        ),
        "source_group_tickers": {
            group: sorted(codes)
            for group, codes in source_tickers.items()
        },
        "recovery_status_counts": dict(
            recovery_counts
        ),
        "known_exhausted_evidence": {
            "exact_da_exhausted_union_count": 67,
            "exact_da_exhausted_union_tickers": sorted(
                da_exhausted
            ),
            "score_cache_q2_exhausted_count": 2,
            "score_cache_q2_exhausted_tickers": [
                ESR,
                MASTERN,
            ],
            "v8104_exhausted_tickers": sorted(
                v8104_exhausted
            ),
        },
        "actionable_single_priority": (
            single_priority
        ),
        "multi_blocker_priority": (
            multi_priority
        ),
        "selection_mode": selection_mode,
        "selected_source_group": selected_group,
        "selected_ticker_count": len(
            selected_tickers
        ),
        "selected_tickers": (
            selected_tickers
        ),
        "hard_guards": {
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_price_elasticity_cache_modified": False,
            "production_ocf_cache_modified": False,
            "production_supply_source_modified": False,
            "production_api_modified": False,
            "production_score_written": False,
            "scoring_policy_modified": False,
            "source_value_imputed": False,
            "exhausted_lane_auto_requeried": False,
            "stale_universe_assumption_used": False,
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
            "STATUS=AUDIT_ONLY_EXHAUSTION_AWARE_DYNAMIC_CURRENT_BLOCKERS",
            f"PRODUCTION_BASIS_DATE={manifest.get('basis_date')}",
            f"SCORER_UNIVERSE={len(rows)}",
            f"READY={len(ready)}",
            f"LIMITED={len(limited)}",
            f"BLOCKER_OCCURRENCES={len(out_rows)}",
            "EXACT_DA_EXHAUSTED_UNION=67",
            "SCORE_CACHE_Q2_EXHAUSTED_COUNT=2",
            "SCORE_CACHE_Q2_EXHAUSTED_TICKERS=365550,357430",
            (
                "ACTIONABLE_SINGLE_BLOCKERS="
                + str(sum(actionable_counts.values()))
            ),
            f"SELECTION_MODE={selection_mode}",
            f"SELECTED_SOURCE_GROUP={selected_group}",
            (
                "SELECTED_TICKER_COUNT="
                + str(len(selected_tickers))
            ),
            "PRODUCTION_DATA_MODIFIED=false",
            "SCORING_POLICY_MODIFIED=false",
            "STALE_UNIVERSE_ASSUMPTION_USED=false",
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
            "# V8.15.6 Mastern Q2 exhausted + dynamic blocker reaudit",
            "",
            f"- Current scorer universe: {len(rows)}",
            f"- READY / LIMITED: {len(ready)} / {len(limited)}",
            f"- Current blocker occurrences: {len(out_rows)}",
            "- Exact-D&A exhausted union: 67",
            "- Q2 score-cache exhausted: ESR Kendall (365550), Mastern Premier REIT (357430).",
            f"- Actionable single blockers: {sum(actionable_counts.values())}",
            f"- Selection mode: `{selection_mode}`",
            f"- Selected source group: `{selected_group}`",
            f"- Selected ticker count: {len(selected_tickers)}",
            "",
            "The current production universe is read dynamically.",
            "Exhausted lanes are classified from completed official evidence and are not automatically re-queried.",
            "No production source, API, score, or scoring policy is modified.",
            "",
            f"Next: `{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        "V8156_MASTERN_Q2_EXHAUSTED_DYNAMIC_REAUDIT=PASS"
    )

if __name__ == "__main__":
    main()
