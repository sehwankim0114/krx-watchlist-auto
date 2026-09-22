#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-22-v8.14.6-freeze-current-actionable-price-elasticity-and-shadow"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8145_VERSION = "2026-09-22-v8.14.5-current-actionable-price-elasticity-20d-official-audit"
V8145_RESULT_COMMIT = "c04b44d4"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

AUDIT_CSV = ROOT / "latest/investment_score_price_elasticity_active_v8145.csv"
AUDIT_JSON = ROOT / "latest/investment_score_price_elasticity_active_v8145_summary_latest.json"
PROD_CACHE = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"

SOURCE_OUT = ROOT / "latest/investment_score_price_elasticity_source_v8146.csv"
COMPARE_OUT = ROOT / "latest/investment_score_price_elasticity_shadow_v8146.csv"
SUMMARY_OUT = ROOT / "latest/investment_score_price_elasticity_shadow_v8146_summary_latest.json"
LOG_OUT = ROOT / "latest/investment_score_price_elasticity_shadow_v8146_run_log_latest.txt"
DOC_OUT = ROOT / "docs/investment_score_price_elasticity_shadow_v8146.md"

TMP_CACHE = Path("/tmp/v8146_shadow_elasticity.csv")
BASE_CSV = Path("/tmp/v8146_baseline_score.csv")
BASE_JSON = Path("/tmp/v8146_baseline_score.json")
BASE_LOG = Path("/tmp/v8146_baseline_score.log")
BASE_DOC = Path("/tmp/v8146_baseline_score.md")
SHADOW_CSV = Path("/tmp/v8146_shadow_score.csv")
SHADOW_JSON = Path("/tmp/v8146_shadow_score.json")
SHADOW_LOG = Path("/tmp/v8146_shadow_score.log")
SHADOW_DOC = Path("/tmp/v8146_shadow_score.md")

EXPECTED = {
    "006260": "LS",
    "267250": "HD현대",
}
MISSING_REASON = "하루평균 절대등락률:MISSING_ELASTICITY"

def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def num(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        s = str(value).strip().replace(",", "")
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

def write_rows(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0].keys()) if rows else []
    with path.open(
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

def split_missing(text):
    return [
        x
        for x in str(text or "").split(";")
        if x
    ]

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
        scorer.ELASTICITY = Path(
            elasticity_path
        )
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
            "V8146_SCORER_FAILED:"
            + str(rc)
        )

def stable(row):
    return json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

def main():
    for p in (
        AUDIT_CSV,
        AUDIT_JSON,
        PROD_CACHE,
    ):
        if not p.is_file():
            raise RuntimeError(
                "V8146_MISSING_INPUT:"
                + str(p)
            )

    subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            V8145_RESULT_COMMIT,
            "HEAD",
        ],
        check=True,
    )

    s8145 = read_json(AUDIT_JSON)

    if s8145.get("version") != V8145_VERSION:
        raise RuntimeError(
            "V8146_V8145_VERSION_MISMATCH"
        )
    if s8145.get("status") != (
        "AUDIT_ONLY_CURRENT_ACTIONABLE_PRICE_ELASTICITY"
    ):
        raise RuntimeError(
            "V8146_V8145_STATUS_MISMATCH"
        )
    if s8145.get(
        "policy_version"
    ) != POLICY_VERSION:
        raise RuntimeError(
            "V8146_POLICY_VERSION_MISMATCH"
        )
    if int(
        s8145.get(
            "target_count"
        ) or 0
    ) != 2:
        raise RuntimeError(
            "V8146_TARGET_COUNT_NOT_2"
        )
    if int(
        s8145.get(
            "recoverable_count"
        ) or 0
    ) != 2:
        raise RuntimeError(
            "V8146_NOT_ALL_RECOVERABLE"
        )
    if int(
        s8145.get(
            "insufficient_count"
        ) or 0
    ) != 0:
        raise RuntimeError(
            "V8146_INSUFFICIENT_NOT_ZERO"
        )
    if set(
        s8145.get(
            "recoverable_tickers"
        ) or []
    ) != set(EXPECTED):
        raise RuntimeError(
            "V8146_RECOVERABLE_SET_MISMATCH"
        )
    if s8145.get("next_step") != (
        "FREEZE_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AND_SHADOW_V8146"
    ):
        raise RuntimeError(
            "V8146_PREDECESSOR_NEXT_STEP_MISMATCH"
        )

    metric = s8145.get(
        "metric_contract"
    ) or {}
    if int(
        metric.get(
            "return_count"
        ) or 0
    ) != 20:
        raise RuntimeError(
            "V8146_WINDOW_NOT_20"
        )
    if int(
        metric.get(
            "minimum_valid_closes"
        ) or 0
    ) != 21:
        raise RuntimeError(
            "V8146_MIN_CLOSES_NOT_21"
        )
    if metric.get(
        "atr_substitution_allowed"
    ) is not False:
        raise RuntimeError(
            "V8146_ATR_SUBSTITUTION_NOT_FORBIDDEN"
        )

    audit = {
        ticker(r.get("ticker")): r
        for r in read_rows(AUDIT_CSV)
        if ticker(r.get("ticker"))
    }

    if set(audit) != set(EXPECTED):
        raise RuntimeError(
            "V8146_AUDIT_SET_MISMATCH"
        )

    source_rows = []

    for code in sorted(EXPECTED):
        r = audit[code]

        if r.get("name") != EXPECTED[code]:
            raise RuntimeError(
                "V8146_NAME_MISMATCH:"
                + code
            )
        if r.get(
            "classification"
        ) != (
            "OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE"
        ):
            raise RuntimeError(
                "V8146_NOT_RECOVERABLE:"
                + code
            )
        if r.get("source") != (
            "KRX_OFFICIAL_STK_BYDD_TRD"
        ):
            raise RuntimeError(
                "V8146_NONOFFICIAL_SOURCE:"
                + code
            )

        pct = num(
            r.get(
                "avg_daily_move_pct"
            )
        )
        if pct is None or pct < 0:
            raise RuntimeError(
                "V8146_BAD_ELASTICITY:"
                + code
            )

        returns = json.loads(
            r.get(
                "last20_returns_json"
            ) or "[]"
        )
        return_dates = json.loads(
            r.get(
                "last20_return_dates_json"
            ) or "[]"
        )
        close_dates = json.loads(
            r.get(
                "used_close_dates_json"
            ) or "[]"
        )

        if (
            len(returns) != 20
            or len(return_dates) != 20
            or len(close_dates) != 21
        ):
            raise RuntimeError(
                "V8146_WINDOW_EVIDENCE_BAD:"
                + code
            )

        source_rows.append({
            "ticker": code,
            "name": EXPECTED[code],
            "basis_date": r[
                "basis_date"
            ],
            "basis_source": r[
                "basis_source"
            ],
            "window_start_date": (
                close_dates[0]
            ),
            "window_end_date": (
                close_dates[-1]
            ),
            "close_observation_count": 21,
            "daily_return_observation_count": 20,
            "avg_daily_move_pct": (
                f"{pct:.2f}"
            ),
            "classification": r[
                "classification"
            ],
            "source": r["source"],
            "last20_return_dates_json": json.dumps(
                return_dates,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "last20_returns_json": json.dumps(
                returns,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        })

    write_rows(
        SOURCE_OUT,
        source_rows,
    )

    prod_rows = read_rows(
        PROD_CACHE
    )
    if not prod_rows:
        raise RuntimeError(
            "V8146_PRODUCTION_ELASTICITY_CACHE_EMPTY"
        )

    prod_fields = list(
        prod_rows[0].keys()
    )
    prod_map = {
        ticker(r.get("ticker")): r
        for r in prod_rows
        if ticker(r.get("ticker"))
    }

    already_ready = sorted(
        code
        for code in EXPECTED
        if code in prod_map
        and prod_map[code].get(
            "source_status"
        ) == "READY"
        and num(
            prod_map[code].get(
                "avg_daily_move_pct"
            )
        )
        is not None
    )

    if already_ready:
        raise RuntimeError(
            "V8146_TARGET_ALREADY_READY_IN_PROD_CACHE:"
            + ",".join(already_ready)
        )

    shadow_map = dict(
        prod_map
    )

    for r in source_rows:
        row = {
            f: ""
            for f in prod_fields
        }
        row.update({
            "ticker": r["ticker"],
            "name": r["name"],
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
            "avg_daily_move_pct": r[
                "avg_daily_move_pct"
            ],
            "source_status": "READY",
        })
        shadow_map[
            r["ticker"]
        ] = row

    write_rows(
        TMP_CACHE,
        [
            shadow_map[k]
            for k in sorted(
                shadow_map
            )
        ],
        prod_fields,
    )

    run_scorer(
        PROD_CACHE,
        BASE_CSV,
        BASE_JSON,
        BASE_LOG,
        BASE_DOC,
    )
    run_scorer(
        TMP_CACHE,
        SHADOW_CSV,
        SHADOW_JSON,
        SHADOW_LOG,
        SHADOW_DOC,
    )

    base = {
        ticker(r.get("ticker")): r
        for r in read_rows(BASE_CSV)
    }
    shadow = {
        ticker(r.get("ticker")): r
        for r in read_rows(
            SHADOW_CSV
        )
    }

    if set(base) != set(shadow):
        raise RuntimeError(
            "V8146_SCORER_UNIVERSE_CHANGED"
        )

    if not set(
        EXPECTED
    ) <= set(base):
        missing = sorted(
            set(EXPECTED)
            - set(base)
        )
        raise RuntimeError(
            "V8146_TARGET_INACTIVE_NOW:"
            + ",".join(missing)
        )

    non_target_changed = [
        code
        for code in sorted(
            set(base)
            - set(EXPECTED)
        )
        if stable(
            base[code]
        ) != stable(
            shadow[code]
        )
    ]

    if non_target_changed:
        raise RuntimeError(
            "V8146_NON_TARGET_SCORE_DRIFT:"
            + ",".join(
                non_target_changed[
                    :20
                ]
            )
        )

    compare = []
    newly_ready = []

    for code in sorted(EXPECTED):
        b = base[code]
        s = shadow[code]

        bm = split_missing(
            b.get(
                "missing_components"
            )
        )
        sm = split_missing(
            s.get(
                "missing_components"
            )
        )

        if b.get(
            "score_status"
        ) != "LIMITED":
            raise RuntimeError(
                "V8146_BASELINE_NOT_LIMITED:"
                + code
            )

        if bm != [
            MISSING_REASON
        ]:
            raise RuntimeError(
                "V8146_BASELINE_NOT_SINGLE_ELASTICITY:"
                + code
                + ":"
                + "|".join(bm)
            )

        if MISSING_REASON in sm:
            raise RuntimeError(
                "V8146_ELASTICITY_NOT_REMOVED:"
                + code
            )

        if s.get(
            "score_status"
        ) != "READY":
            raise RuntimeError(
                "V8146_SHADOW_NOT_READY:"
                + code
            )

        newly_ready.append(code)

        compare.append({
            "ticker": code,
            "name": EXPECTED[code],
            "avg_daily_move_pct": audit[
                code
            ][
                "avg_daily_move_pct"
            ],
            "baseline_status": b.get(
                "score_status"
            ) or "",
            "shadow_status": s.get(
                "score_status"
            ) or "",
            "baseline_missing_components": (
                ";".join(bm)
            ),
            "shadow_missing_components": (
                ";".join(sm)
            ),
            "baseline_score_total": b.get(
                "score_total"
            ) or "",
            "shadow_score_total": s.get(
                "score_total"
            ) or "",
        })

    write_rows(
        COMPARE_OUT,
        compare,
    )

    bsum = read_json(BASE_JSON)
    ssum = read_json(
        SHADOW_JSON
    )

    b_ready = int(
        bsum.get(
            "ready_count"
        ) or 0
    )
    s_ready = int(
        ssum.get(
            "ready_count"
        ) or 0
    )
    b_limited = int(
        bsum.get(
            "limited_count"
        ) or 0
    )
    s_limited = int(
        ssum.get(
            "limited_count"
        ) or 0
    )

    b_blockers = sum(
        int(
            r.get(
                "missing_component_count"
            ) or 0
        )
        for r in base.values()
    )
    s_blockers = sum(
        int(
            r.get(
                "missing_component_count"
            ) or 0
        )
        for r in shadow.values()
    )

    if s_ready - b_ready != 2:
        raise RuntimeError(
            "V8146_READY_DELTA_NOT_2:"
            + str(
                s_ready - b_ready
            )
        )
    if b_limited - s_limited != 2:
        raise RuntimeError(
            "V8146_LIMITED_DELTA_NOT_2:"
            + str(
                b_limited - s_limited
            )
        )
    if (
        b_blockers
        - s_blockers
    ) != 2:
        raise RuntimeError(
            "V8146_BLOCKER_DELTA_NOT_2:"
            + str(
                b_blockers
                - s_blockers
            )
        )

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(
            KST
        ).isoformat(
            timespec="seconds"
        ),
        "status": (
            "SOURCE_ONLY_FROZEN_SHADOW_PASS"
        ),
        "policy_version": (
            POLICY_VERSION
        ),
        "v8145_version": (
            V8145_VERSION
        ),
        "v8145_result_commit": (
            V8145_RESULT_COMMIT
        ),
        "source_frozen_count": 2,
        "source_frozen_tickers": sorted(
            EXPECTED
        ),
        "basis_date": s8145.get(
            "basis_date"
        ),
        "basis_source": s8145.get(
            "basis_source"
        ),
        "current_scorer_universe_count": len(
            base
        ),
        "baseline_ready_count": (
            b_ready
        ),
        "shadow_ready_count": (
            s_ready
        ),
        "ready_delta": 2,
        "baseline_limited_count": (
            b_limited
        ),
        "shadow_limited_count": (
            s_limited
        ),
        "limited_delta": -2,
        "newly_ready_count": 2,
        "newly_ready_tickers": sorted(
            newly_ready
        ),
        "baseline_blocker_occurrences": (
            b_blockers
        ),
        "shadow_blocker_occurrences": (
            s_blockers
        ),
        "blocker_occurrences_reduced_by": 2,
        "elasticity_reason_removed_count": 2,
        "elasticity_reason_removed_tickers": sorted(
            EXPECTED
        ),
        "non_target_score_row_changed_count": 0,
        "secondary_actionable_single_group": {
            "source_group": (
                "PRODUCTION_ANALYSIS_SUPPLY"
            ),
            "ticker_count": 1,
            "tickers": [
                "072130"
            ],
        },
        "hard_guards": {
            "production_price_elasticity_cache_modified": False,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_ocf_cache_modified": False,
            "production_supply_source_modified": False,
            "production_api_modified": False,
            "scoring_policy_modified": False,
            "atr_used_as_elasticity_substitute": False,
            "nonofficial_price_source_used": False,
            "production_score_written": False,
        },
        "next_step": (
            "STAGE_NARROW_PRODUCTION_PRICE_ELASTICITY_PATCH_V8147"
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
            "STATUS=SOURCE_ONLY_FROZEN_SHADOW_PASS",
            "SOURCE_FROZEN_COUNT=2",
            f"CURRENT_SCORER_UNIVERSE={len(base)}",
            f"BASELINE_READY={b_ready}",
            f"SHADOW_READY={s_ready}",
            "READY_DELTA=2",
            f"BASELINE_LIMITED={b_limited}",
            f"SHADOW_LIMITED={s_limited}",
            "LIMITED_DELTA=-2",
            f"BASELINE_BLOCKERS={b_blockers}",
            f"SHADOW_BLOCKERS={s_blockers}",
            "BLOCKER_REDUCED_BY=2",
            "NON_TARGET_SCORE_ROW_CHANGED_COUNT=0",
            "SECONDARY_SUPPLY_ACTIONABLE=1",
            "PRODUCTION_PRICE_ELASTICITY_CACHE_MODIFIED=false",
            "PRODUCTION_SCORE_WRITTEN=false",
            "ATR_SUBSTITUTION_USED=false",
            "NONOFFICIAL_PRICE_SOURCE_USED=false",
            "STATUS_OK=true",
            "NEXT_STEP=STAGE_NARROW_PRODUCTION_PRICE_ELASTICITY_PATCH_V8147",
        ]) + "\n",
        encoding="utf-8",
    )

    DOC_OUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    DOC_OUT.write_text(
        "\n".join([
            "# V8.14.6 price-elasticity source freeze and shadow score",
            "",
            "- Frozen source: LS (006260), HD현대 (267250).",
            "- Official KRX 20-return elasticity only.",
            "- Both baseline rows must be LIMITED only by MISSING_ELASTICITY.",
            "- Both shadow rows must become READY.",
            "- Non-target score drift must be zero.",
            "- Production elasticity cache is not changed.",
            "",
            f"- Baseline READY / LIMITED: {b_ready} / {b_limited}",
            f"- Shadow READY / LIMITED: {s_ready} / {s_limited}",
            "- READY delta: +2",
            "- Blocker reduction: 2",
            "",
            "Next: `STAGE_NARROW_PRODUCTION_PRICE_ELASTICITY_PATCH_V8147`",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        "V8146_PRICE_ELASTICITY_FREEZE_SHADOW=PASS"
    )

if __name__ == "__main__":
    main()
