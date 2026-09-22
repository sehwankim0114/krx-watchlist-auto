#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-22-v8.14.7A-narrow-production-price-elasticity-patch"
SOURCE_CONTRACT_VERSION = "2026-09-12-v8.7.5-price-elasticity-20-session-source"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8146_VERSION = "2026-09-22-v8.14.6-freeze-current-actionable-price-elasticity-and-shadow"
V8146_RESULT_COMMIT = "0f090fff696b0e21f5ace88891a706d08a781a61"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

PROD_CSV = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"
PROD_META = ROOT / "latest/investment_score_price_elasticity_20d_latest.json"
PROD_LOG = ROOT / "latest/investment_score_price_elasticity_20d_run_log_latest.txt"

SOURCE_CSV = ROOT / "latest/investment_score_price_elasticity_source_v8146.csv"
SHADOW_JSON = ROOT / "latest/investment_score_price_elasticity_shadow_v8146_summary_latest.json"

SUMMARY_OUT = ROOT / "latest/investment_score_price_elasticity_production_patch_v8147a_summary_latest.json"
LOG_OUT = ROOT / "latest/investment_score_price_elasticity_production_patch_v8147a_run_log_latest.txt"
DOC_OUT = ROOT / "docs/investment_score_price_elasticity_production_patch_v8147a.md"

CAND_CACHE = Path("/tmp/v8147a_candidate_elasticity.csv")
BASE_CSV = Path("/tmp/v8147a_base_score.csv")
BASE_JSON = Path("/tmp/v8147a_base_score.json")
BASE_LOG = Path("/tmp/v8147a_base_score.log")
BASE_DOC = Path("/tmp/v8147a_base_score.md")
CAND_CSV = Path("/tmp/v8147a_candidate_score.csv")
CAND_JSON = Path("/tmp/v8147a_candidate_score.json")
CAND_LOG = Path("/tmp/v8147a_candidate_score.log")
CAND_DOC = Path("/tmp/v8147a_candidate_score.md")
POST_CSV = Path("/tmp/v8147a_post_score.csv")
POST_JSON = Path("/tmp/v8147a_post_score.json")
POST_LOG = Path("/tmp/v8147a_post_score.log")
POST_DOC = Path("/tmp/v8147a_post_score.md")

EXPECTED = {
    "006260": ("LS", 2.70),
    "267250": ("HD현대", 2.91),
}
EXPECTED_PRE_CACHE_ROWS = 149
EXPECTED_POST_CACHE_ROWS = 151
EXPECTED_BASE_UNIVERSE = 120
EXPECTED_BASE_READY = 16
EXPECTED_BASE_LIMITED = 104
EXPECTED_BASE_BLOCKERS = 794
EXPECTED_POST_READY = 18
EXPECTED_POST_LIMITED = 102
EXPECTED_POST_BLOCKERS = 792

def ticker(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def num(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        s = str(v).strip().replace(",", "")
        if s in {"", "-", "None", "null", "nan", "NaN"}:
            return None
        x = float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None

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

def write_rows(path, rows, fields):
    with Path(path).open(
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
        w.writerows(rows)

def row_map(path):
    return {
        ticker(r.get("ticker")): r
        for r in read_rows(path)
        if ticker(r.get("ticker"))
    }

def stable(row):
    return json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

def blocker_count(rows):
    return sum(
        int(r.get("missing_component_count") or 0)
        for r in rows.values()
    )

def run_scorer(
    elasticity_path,
    out_csv,
    out_json,
    out_log,
    out_doc,
):
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
        raise RuntimeError(
            "V8147A_SCORER_FAILED:" + str(rc)
        )

def main():
    for p in (
        PROD_CSV,
        PROD_META,
        PROD_LOG,
        SOURCE_CSV,
        SHADOW_JSON,
    ):
        if not p.is_file():
            raise RuntimeError(
                "V8147A_MISSING_INPUT:" + str(p)
            )

    subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            V8146_RESULT_COMMIT,
            "HEAD",
        ],
        check=True,
    )

    shadow_meta = read_json(SHADOW_JSON)
    prod_meta = read_json(PROD_META)

    if shadow_meta.get("version") != V8146_VERSION:
        raise RuntimeError(
            "V8147A_V8146_VERSION_MISMATCH"
        )
    if shadow_meta.get("status") != (
        "SOURCE_ONLY_FROZEN_SHADOW_PASS"
    ):
        raise RuntimeError(
            "V8147A_V8146_STATUS_MISMATCH"
        )
    if shadow_meta.get("next_step") != (
        "STAGE_NARROW_PRODUCTION_PRICE_ELASTICITY_PATCH_V8147"
    ):
        raise RuntimeError(
            "V8147A_PREDECESSOR_NEXT_STEP_MISMATCH"
        )
    if int(
        shadow_meta.get("source_frozen_count") or 0
    ) != 2:
        raise RuntimeError(
            "V8147A_SOURCE_FROZEN_COUNT_NOT_2"
        )
    if set(
        shadow_meta.get("source_frozen_tickers") or []
    ) != set(EXPECTED):
        raise RuntimeError(
            "V8147A_SOURCE_SET_CHANGED"
        )
    if (
        int(shadow_meta.get("baseline_ready_count") or 0),
        int(shadow_meta.get("baseline_limited_count") or 0),
        int(shadow_meta.get("baseline_blocker_occurrences") or 0),
    ) != (
        EXPECTED_BASE_READY,
        EXPECTED_BASE_LIMITED,
        EXPECTED_BASE_BLOCKERS,
    ):
        raise RuntimeError(
            "V8147A_V8146_BASELINE_CHANGED"
        )
    if (
        int(shadow_meta.get("shadow_ready_count") or 0),
        int(shadow_meta.get("shadow_limited_count") or 0),
        int(shadow_meta.get("shadow_blocker_occurrences") or 0),
    ) != (
        EXPECTED_POST_READY,
        EXPECTED_POST_LIMITED,
        EXPECTED_POST_BLOCKERS,
    ):
        raise RuntimeError(
            "V8147A_V8146_SHADOW_CHANGED"
        )
    if int(
        shadow_meta.get(
            "non_target_score_row_changed_count"
        ) or 0
    ) != 0:
        raise RuntimeError(
            "V8147A_V8146_NON_TARGET_DRIFT"
        )

    if prod_meta.get("version") != SOURCE_CONTRACT_VERSION:
        raise RuntimeError(
            "V8147A_SOURCE_CONTRACT_CHANGED"
        )
    if prod_meta.get("status") != "READY_SOURCE_ONLY":
        raise RuntimeError(
            "V8147A_PROD_STATUS_CHANGED"
        )
    if int(
        prod_meta.get("production_unique_tickers") or 0
    ) != EXPECTED_PRE_CACHE_ROWS:
        raise RuntimeError(
            "V8147A_PROD_META_COUNT_NOT_149"
        )
    if prod_meta.get("basis_date") != "2026-09-18":
        raise RuntimeError(
            "V8147A_PROD_FULL_REFRESH_BASIS_CHANGED"
        )

    prod_rows_list = read_rows(PROD_CSV)
    if len(prod_rows_list) != EXPECTED_PRE_CACHE_ROWS:
        raise RuntimeError(
            "V8147A_PROD_CSV_COUNT_NOT_149:"
            + str(len(prod_rows_list))
        )

    prod_fields = list(prod_rows_list[0].keys())
    expected_fields = [
        "ticker",
        "name",
        "basis_date",
        "window_start_date",
        "window_end_date",
        "close_observation_count",
        "daily_return_observation_count",
        "avg_daily_move_abs",
        "avg_daily_move_pct",
        "source_status",
    ]
    if prod_fields != expected_fields:
        raise RuntimeError(
            "V8147A_PROD_SCHEMA_CHANGED:"
            + ",".join(prod_fields)
        )

    prod = {
        ticker(r.get("ticker")): r
        for r in prod_rows_list
    }
    source = row_map(SOURCE_CSV)

    if set(source) != set(EXPECTED):
        raise RuntimeError(
            "V8147A_SOURCE_CSV_SET_CHANGED"
        )

    overlap = sorted(
        set(prod) & set(EXPECTED)
    )
    if overlap:
        raise RuntimeError(
            "V8147A_TARGET_ALREADY_IN_PROD_CACHE:"
            + ",".join(overlap)
        )

    candidate = dict(prod)

    for code, (name, pct_expected) in EXPECTED.items():
        r = source[code]

        if r.get("name") != name:
            raise RuntimeError(
                "V8147A_SOURCE_NAME_MISMATCH:"
                + code
            )
        pct = num(
            r.get("avg_daily_move_pct")
        )
        if (
            pct is None
            or abs(
                pct - pct_expected
            ) > 1e-9
        ):
            raise RuntimeError(
                "V8147A_SOURCE_VALUE_MISMATCH:"
                + code
            )
        if r.get("basis_date") != "2026-09-21":
            raise RuntimeError(
                "V8147A_SOURCE_BASIS_CHANGED:"
                + code
            )
        if int(
            r.get(
                "close_observation_count"
            ) or 0
        ) != 21:
            raise RuntimeError(
                "V8147A_CLOSE_COUNT_NOT_21:"
                + code
            )
        if int(
            r.get(
                "daily_return_observation_count"
            ) or 0
        ) != 20:
            raise RuntimeError(
                "V8147A_RETURN_COUNT_NOT_20:"
                + code
            )

        candidate[code] = {
            "ticker": code,
            "name": name,
            "basis_date": r[
                "basis_date"
            ],
            "window_start_date": r[
                "window_start_date"
            ],
            "window_end_date": r[
                "window_end_date"
            ],
            "close_observation_count": "21",
            "daily_return_observation_count": "20",
            "avg_daily_move_abs": "",
            "avg_daily_move_pct": (
                f"{pct:.2f}"
            ),
            "source_status": "READY",
        }

    if len(candidate) != EXPECTED_POST_CACHE_ROWS:
        raise RuntimeError(
            "V8147A_CANDIDATE_CACHE_COUNT_NOT_151:"
            + str(len(candidate))
        )

    write_rows(
        CAND_CACHE,
        [
            candidate[k]
            for k in sorted(candidate)
        ],
        prod_fields,
    )

    run_scorer(
        PROD_CSV,
        BASE_CSV,
        BASE_JSON,
        BASE_LOG,
        BASE_DOC,
    )
    run_scorer(
        CAND_CACHE,
        CAND_CSV,
        CAND_JSON,
        CAND_LOG,
        CAND_DOC,
    )

    base = row_map(BASE_CSV)
    cand_score = row_map(CAND_CSV)

    if set(base) != set(cand_score):
        raise RuntimeError(
            "V8147A_SCORER_UNIVERSE_CHANGED"
        )
    if len(base) != EXPECTED_BASE_UNIVERSE:
        raise RuntimeError(
            "V8147A_CURRENT_UNIVERSE_NOT_120:"
            + str(len(base))
        )

    bsum = read_json(BASE_JSON)
    csum = read_json(CAND_JSON)

    b_ready = int(bsum.get("ready_count") or 0)
    b_limited = int(bsum.get("limited_count") or 0)
    c_ready = int(csum.get("ready_count") or 0)
    c_limited = int(csum.get("limited_count") or 0)
    b_blockers = blocker_count(base)
    c_blockers = blocker_count(cand_score)

    if (
        b_ready,
        b_limited,
        b_blockers,
    ) != (
        EXPECTED_BASE_READY,
        EXPECTED_BASE_LIMITED,
        EXPECTED_BASE_BLOCKERS,
    ):
        raise RuntimeError(
            "V8147A_CURRENT_BASELINE_DRIFT:"
            f"{b_ready}:{b_limited}:{b_blockers}"
        )

    if (
        c_ready,
        c_limited,
        c_blockers,
    ) != (
        EXPECTED_POST_READY,
        EXPECTED_POST_LIMITED,
        EXPECTED_POST_BLOCKERS,
    ):
        raise RuntimeError(
            "V8147A_CANDIDATE_RESULT_CHANGED:"
            f"{c_ready}:{c_limited}:{c_blockers}"
        )

    non_target_changed = [
        code
        for code in sorted(
            set(base) - set(EXPECTED)
        )
        if stable(base[code]) != stable(
            cand_score[code]
        )
    ]
    if non_target_changed:
        raise RuntimeError(
            "V8147A_NON_TARGET_SCORE_DRIFT:"
            + ",".join(non_target_changed[:20])
        )

    for code in EXPECTED:
        if base[code].get("score_status") != "LIMITED":
            raise RuntimeError(
                "V8147A_BASE_TARGET_NOT_LIMITED:"
                + code
            )
        if cand_score[code].get(
            "score_status"
        ) != "READY":
            raise RuntimeError(
                "V8147A_CAND_TARGET_NOT_READY:"
                + code
            )

    # Apply exactly the already-tested candidate bytes.
    shutil.copyfile(
        CAND_CACHE,
        PROD_CSV,
    )

    now = datetime.now(
        KST
    ).isoformat(
        timespec="seconds"
    )

    new_meta = dict(prod_meta)
    new_meta.update({
        "version": SOURCE_CONTRACT_VERSION,
        "refresh_version": VERSION,
        "generated_at_kst": now,
        "status": "READY_SOURCE_ONLY",
        # Keep the full-refresh basis truthful. The two narrow
        # rows carry their own newer per-row basis dates.
        "basis_date": "2026-09-18",
        "basis_date_semantics": (
            "full_refresh_basis; per-row basis_date is authoritative "
            "for narrow-patched rows"
        ),
        "latest_row_basis_date": "2026-09-21",
        "production_unique_tickers": (
            EXPECTED_POST_CACHE_ROWS
        ),
        "ready_tickers": (
            EXPECTED_POST_CACHE_ROWS
        ),
        "limited_tickers": 0,
        "source": (
            "official KRX STK_BYDD_TRD; v8.12.7 full refresh "
            "plus validated narrow v8.14.7 additions"
        ),
        "narrow_patch": {
            "version": VERSION,
            "promoted_from_version": V8146_VERSION,
            "promoted_from_commit": V8146_RESULT_COMMIT,
            "ticker_count": 2,
            "tickers": sorted(EXPECTED),
            "basis_date": "2026-09-21",
            "values": {
                "006260": 2.70,
                "267250": 2.91,
            },
        },
    })
    new_meta["hard_guards"] = {
        "investment_score_100_calculated": False,
        "score_thresholds_defined": False,
        "avg_daily_range_20_pct_substituted": False,
        "production_api_changed": False,
        "non_target_elasticity_rows_modified": False,
    }

    PROD_META.write_text(
        json.dumps(
            new_meta,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    PROD_LOG.write_text(
        "\n".join([
            f"VERSION={SOURCE_CONTRACT_VERSION}",
            f"REFRESH_VERSION={VERSION}",
            "FULL_REFRESH_BASIS_DATE=2026-09-18",
            "LATEST_ROW_BASIS_DATE=2026-09-21",
            f"PRODUCTION_UNIQUE_TICKERS={EXPECTED_POST_CACHE_ROWS}",
            f"PRICE_ELASTICITY_20D_READY={EXPECTED_POST_CACHE_ROWS}",
            "PRICE_ELASTICITY_20D_LIMITED=0",
            "NARROW_PATCH_COUNT=2",
            "NARROW_PATCH_TICKERS=006260,267250",
            "CLOSE_OBSERVATIONS_REQUIRED=21",
            "DAILY_RETURN_OBSERVATIONS_REQUIRED=20",
            "AVG_DAILY_RANGE_20_PCT_SUBSTITUTED=false",
            "INVESTMENT_SCORE_100_CALCULATED=false",
            "SCORE_THRESHOLDS_DEFINED=false",
            "NON_TARGET_ELASTICITY_ROWS_MODIFIED=false",
            "PRODUCTION_DATA_CHANGED=true",
            "PRODUCTION_API_CHANGED=false",
            "PRODUCTION_SCORE_WRITTEN=false",
            "STATUS=OK",
        ]) + "\n",
        encoding="utf-8",
    )

    # Verify pre-existing 149 rows are byte-equivalent by field values.
    post_cache = row_map(PROD_CSV)
    if len(post_cache) != EXPECTED_POST_CACHE_ROWS:
        raise RuntimeError(
            "V8147A_POST_CACHE_COUNT_NOT_151"
        )

    changed_old_rows = [
        code
        for code in sorted(prod)
        if stable(prod[code]) != stable(
            post_cache[code]
        )
    ]
    if changed_old_rows:
        raise RuntimeError(
            "V8147A_EXISTING_ELASTICITY_ROW_CHANGED:"
            + ",".join(changed_old_rows[:20])
        )

    run_scorer(
        PROD_CSV,
        POST_CSV,
        POST_JSON,
        POST_LOG,
        POST_DOC,
    )

    post_score = row_map(POST_CSV)
    post_sum = read_json(POST_JSON)

    if set(post_score) != set(cand_score):
        raise RuntimeError(
            "V8147A_POST_SCORE_UNIVERSE_CHANGED"
        )

    score_mismatch = [
        code
        for code in sorted(post_score)
        if stable(post_score[code]) != stable(
            cand_score[code]
        )
    ]
    if score_mismatch:
        raise RuntimeError(
            "V8147A_POST_SCORE_NOT_EQUAL_CANDIDATE:"
            + ",".join(score_mismatch[:20])
        )

    p_ready = int(
        post_sum.get("ready_count") or 0
    )
    p_limited = int(
        post_sum.get("limited_count") or 0
    )
    p_blockers = blocker_count(
        post_score
    )

    if (
        p_ready,
        p_limited,
        p_blockers,
    ) != (
        EXPECTED_POST_READY,
        EXPECTED_POST_LIMITED,
        EXPECTED_POST_BLOCKERS,
    ):
        raise RuntimeError(
            "V8147A_POST_APPLY_STATE_BAD:"
            f"{p_ready}:{p_limited}:{p_blockers}"
        )

    newly_ready = sorted(
        code
        for code in base
        if base[code].get(
            "score_status"
        ) != "READY"
        and post_score[code].get(
            "score_status"
        ) == "READY"
    )

    if newly_ready != sorted(EXPECTED):
        raise RuntimeError(
            "V8147A_NEWLY_READY_SET_CHANGED:"
            + ",".join(newly_ready)
        )

    summary = {
        "version": VERSION,
        "generated_at_kst": now,
        "status": (
            "PRODUCTION_NARROW_ELASTICITY_PATCH_APPLIED_POST_REGRESSION_PASS"
        ),
        "policy_version": POLICY_VERSION,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "v8146_version": V8146_VERSION,
        "v8146_result_commit": V8146_RESULT_COMMIT,
        "production_cache_before": {
            "row_count": EXPECTED_PRE_CACHE_ROWS,
            "full_refresh_basis_date": "2026-09-18",
        },
        "production_cache_after": {
            "row_count": EXPECTED_POST_CACHE_ROWS,
            "full_refresh_basis_date": "2026-09-18",
            "latest_row_basis_date": "2026-09-21",
            "narrow_patch_count": 2,
            "narrow_patch_tickers": sorted(EXPECTED),
        },
        "current_scorer_universe_count": len(
            post_score
        ),
        "baseline_ready_count": b_ready,
        "post_ready_count": p_ready,
        "ready_delta": p_ready - b_ready,
        "baseline_limited_count": b_limited,
        "post_limited_count": p_limited,
        "limited_delta": p_limited - b_limited,
        "baseline_blocker_occurrences": b_blockers,
        "post_blocker_occurrences": p_blockers,
        "blocker_occurrences_reduced_by": (
            b_blockers - p_blockers
        ),
        "newly_ready_count": len(
            newly_ready
        ),
        "newly_ready_tickers": newly_ready,
        "non_target_score_row_changed_count": 0,
        "existing_elasticity_row_changed_count": 0,
        "post_score_equals_tested_candidate": True,
        "hard_guards": {
            "production_price_elasticity_cache_modified": True,
            "production_price_elasticity_metadata_modified": True,
            "production_price_elasticity_run_log_modified": True,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_ocf_cache_modified": False,
            "production_supply_source_modified": False,
            "production_api_modified": False,
            "scoring_policy_modified": False,
            "production_score_written": False,
            "atr_substituted": False,
            "nonofficial_price_source_used": False,
            "non_target_elasticity_rows_modified": False,
            "ready_regression_count": 0,
        },
        "next_step": (
            "POST_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8148"
        ),
    }

    SUMMARY_OUT.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    LOG_OUT.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=PRODUCTION_NARROW_ELASTICITY_PATCH_APPLIED_POST_REGRESSION_PASS",
            "PRODUCTION_ROWS_BEFORE=149",
            "PRODUCTION_ROWS_AFTER=151",
            "NARROW_PATCH_COUNT=2",
            "NARROW_PATCH_TICKERS=006260,267250",
            f"SCORER_UNIVERSE={len(post_score)}",
            f"BASELINE_READY={b_ready}",
            f"POST_APPLY_READY={p_ready}",
            f"READY_DELTA={p_ready-b_ready}",
            f"BASELINE_LIMITED={b_limited}",
            f"POST_APPLY_LIMITED={p_limited}",
            f"LIMITED_DELTA={p_limited-b_limited}",
            f"BASELINE_BLOCKERS={b_blockers}",
            f"POST_APPLY_BLOCKERS={p_blockers}",
            f"BLOCKER_REDUCED_BY={b_blockers-p_blockers}",
            "NON_TARGET_SCORE_ROW_CHANGED_COUNT=0",
            "EXISTING_ELASTICITY_ROW_CHANGED_COUNT=0",
            "POST_SCORE_EQUALS_TESTED_CANDIDATE=true",
            "PRODUCTION_API_MODIFIED=false",
            "PRODUCTION_SCORE_WRITTEN=false",
            "SCORING_POLICY_MODIFIED=false",
            "STATUS_OK=true",
            "NEXT_STEP=POST_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8148",
        ]) + "\n",
        encoding="utf-8",
    )

    DOC_OUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    DOC_OUT.write_text(
        "\n".join([
            "# V8.14.7A narrow production price-elasticity patch",
            "",
            "- Added only LS (006260) and HD현대 (267250) to the production elasticity cache.",
            "- Existing 149 elasticity rows were preserved field-for-field.",
            "- The original full-refresh basis remains 2026-09-18.",
            "- The two narrow-patched rows carry their own 2026-09-21 basis dates.",
            "- Post-apply scorer output exactly equals the pre-tested V8.14.6 candidate state.",
            f"- READY: {b_ready} -> {p_ready}.",
            f"- LIMITED: {b_limited} -> {p_limited}.",
            f"- Blockers: {b_blockers} -> {p_blockers}.",
            "- API and scoring policy were not modified.",
            "",
            "Next: `POST_ELASTICITY_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8148`",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        "V8147A_NARROW_PRODUCTION_ELASTICITY_PATCH=PASS"
    )

if __name__ == "__main__":
    main()
