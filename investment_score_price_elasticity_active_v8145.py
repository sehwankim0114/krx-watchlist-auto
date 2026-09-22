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
import collect_universe as universe

VERSION = "2026-09-22-v8.14.5-current-actionable-price-elasticity-20d-official-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8144A_VERSION = "2026-09-22-v8.14.4A-dynamic-exhaustion-aware-current-blocker-reaudit"
V8144A_RESULT_COMMIT = "1e5e878a5c5b897c2ce8f9ab9e551870bfe4f88e"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8144a.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8144a_summary_latest.json"
HISTORY = ROOT / "latest/universe_raw_history_latest.csv"
PRICE_CACHE = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"
MANIFEST = ROOT / "api/two_table_v1/manifest.json"

OUT_CSV = ROOT / "latest/investment_score_price_elasticity_active_v8145.csv"
OUT_JSON = ROOT / "latest/investment_score_price_elasticity_active_v8145_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_price_elasticity_active_v8145_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_price_elasticity_active_v8145.md"

EXPECTED = {
    "006260": "LS",
    "267250": "HD현대",
}

PRICE_REASON = "하루평균 절대등락률:MISSING_ELASTICITY"
WINDOW_RETURNS = 20
MIN_VALID_CLOSES = 21
CALENDAR_BUFFER_SESSIONS = 40

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

def valid_close(row):
    x = num(row.get("close"))
    return x is not None and x > 0

def calc(rows):
    ordered = sorted(
        rows,
        key=lambda r: pd.Timestamp(r["date"]),
    )
    closes = [num(r.get("close")) for r in ordered]
    if len(closes) < MIN_VALID_CLOSES:
        return None, [], []

    returns = []
    dates = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        if (
            prev is None
            or cur is None
            or prev <= 0
            or cur <= 0
        ):
            continue
        returns.append(cur / prev - 1.0)
        dates.append(
            pd.Timestamp(
                ordered[i]["date"]
            ).date().isoformat()
        )

    if len(returns) < WINDOW_RETURNS:
        return None, returns, dates

    last = returns[-WINDOW_RETURNS:]
    last_dates = dates[-WINDOW_RETURNS:]
    pct = round(
        sum(abs(x) for x in last)
        / WINDOW_RETURNS
        * 100.0,
        2,
    )
    return pct, last, last_dates

def main():
    key = os.environ.get(
        "KRX_AUTH_KEY",
        "",
    ).strip()
    if not key:
        raise RuntimeError(
            "V8145_KRX_AUTH_KEY_MISSING"
        )

    for p in (
        BLOCK_CSV,
        BLOCK_JSON,
        HISTORY,
        PRICE_CACHE,
        MANIFEST,
    ):
        if not p.is_file():
            raise RuntimeError(
                "V8145_MISSING_INPUT:" + str(p)
            )

    summary = read_json(BLOCK_JSON)
    manifest = read_json(MANIFEST)

    if summary.get("version") != V8144A_VERSION:
        raise RuntimeError(
            "V8145_V8144A_VERSION_MISMATCH"
        )
    if summary.get("status") != (
        "AUDIT_ONLY_DYNAMIC_EXHAUSTION_AWARE_CURRENT_BLOCKERS"
    ):
        raise RuntimeError(
            "V8145_V8144A_STATUS_MISMATCH"
        )
    if summary.get("policy_version") != POLICY_VERSION:
        raise RuntimeError(
            "V8145_POLICY_VERSION_MISMATCH"
        )
    if summary.get("selection_mode") != (
        "ACTIONABLE_SINGLE_BLOCKER"
    ):
        raise RuntimeError(
            "V8145_SELECTION_MODE_CHANGED"
        )
    if summary.get("selected_source_group") != (
        "PRICE_ELASTICITY_20D"
    ):
        raise RuntimeError(
            "V8145_SELECTED_GROUP_NOT_ELASTICITY"
        )
    if int(
        summary.get("selected_ticker_count") or 0
    ) != 2:
        raise RuntimeError(
            "V8145_SELECTED_COUNT_NOT_2"
        )
    if set(
        summary.get("selected_tickers") or []
    ) != set(EXPECTED):
        raise RuntimeError(
            "V8145_SELECTED_SET_CHANGED"
        )
    if summary.get("next_step") != (
        "AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8145"
    ):
        raise RuntimeError(
            "V8145_PREDECESSOR_NEXT_STEP_MISMATCH"
        )

    if manifest.get("release_stage") != "PRODUCTION":
        raise RuntimeError(
            "V8145_MANIFEST_NOT_PRODUCTION"
        )
    if manifest.get("safe_to_analyze_as_latest") is not True:
        raise RuntimeError(
            "V8145_MANIFEST_NOT_SAFE_LATEST"
        )

    blockers = read_rows(BLOCK_CSV)
    actionable = {
        ticker(r.get("ticker")): str(
            r.get("name") or ""
        )
        for r in blockers
        if r.get("source_group") == (
            "PRICE_ELASTICITY_20D"
        )
        and r.get(
            "single_blocker_ticker"
        ) == "TRUE"
        and r.get(
            "recovery_status"
        ) == (
            "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
        )
        and r.get("blocker_reason") == PRICE_REASON
    }

    if set(actionable) != set(EXPECTED):
        raise RuntimeError(
            "V8145_ACTIONABLE_SET_MISMATCH:"
            + ",".join(sorted(actionable))
        )

    for code, name in EXPECTED.items():
        if actionable[code] != name:
            raise RuntimeError(
                "V8145_ACTIONABLE_NAME_MISMATCH:"
                + code
                + ":"
                + actionable[code]
            )

    prod_cache = {
        ticker(r.get("ticker")): r
        for r in read_rows(PRICE_CACHE)
        if ticker(r.get("ticker"))
    }

    ready_overlap = sorted(
        code
        for code in EXPECTED
        if code in prod_cache
        and prod_cache[code].get(
            "source_status"
        ) == "READY"
        and num(
            prod_cache[code].get(
                "avg_daily_move_pct"
            )
        )
        is not None
    )

    if ready_overlap:
        raise RuntimeError(
            "V8145_TARGET_ALREADY_READY_IN_PRODUCTION_CACHE:"
            + ",".join(ready_overlap)
        )

    raw = universe.read_csv_if_exists(
        HISTORY
    )
    hist = universe.normalize_history_dtypes(
        raw
    )
    if hist.empty:
        raise RuntimeError(
            "V8145_OFFICIAL_HISTORY_EMPTY"
        )

    kospi_all = hist[
        hist["market"] == "KOSPI"
    ].copy()

    sessions = sorted(
        pd.Timestamp(x).normalize()
        for x in kospi_all[
            "date"
        ].dropna().unique()
    )

    if len(
        sessions
    ) < CALENDAR_BUFFER_SESSIONS:
        raise RuntimeError(
            "V8145_SESSION_CALENDAR_TOO_SHORT:"
            + str(len(sessions))
        )

    basis = sessions[-1]
    basis_iso = basis.date().isoformat()

    if manifest.get(
        "basis_date"
    ) != basis_iso:
        raise RuntimeError(
            "V8145_MANIFEST_HISTORY_BASIS_MISMATCH:"
            + str(manifest.get("basis_date"))
            + ":"
            + basis_iso
        )

    basis_source = (
        "OFFICIAL_KRX_HISTORY_MAX_KOSPI_SESSION"
    )
    target_sessions = sessions[
        -CALENDAR_BUFFER_SESSIONS:
    ]
    target_set = set(target_sessions)

    by_code = {
        code: {}
        for code in EXPECTED
    }

    for _, row in kospi_all.iterrows():
        code = ticker(
            row.get("ticker")
        )
        if code not in EXPECTED:
            continue

        day = pd.Timestamp(
            row["date"]
        ).normalize()
        if day not in target_set:
            continue

        data = row.to_dict()
        data["date"] = day

        if valid_close(data):
            by_code[code][day] = data

    initial_counts = {
        code: len(by_code[code])
        for code in EXPECTED
    }

    missing_dates = sorted({
        day
        for code in EXPECTED
        for day in target_sessions
        if day not in by_code[code]
    })

    fetch_count = 0
    fetch_success = 0

    for day in missing_dates:
        bas_dd = day.strftime("%Y%m%d")
        logs = []

        raw_day = universe.request_krx_openapi(
            universe.OPENAPI_STOCK_URLS[
                "KOSPI"
            ],
            key,
            bas_dd,
            logs,
            "V8145_KOSPI_STOCK",
        )
        fetch_count += 1

        norm = universe.normalize_stock_rows(
            raw_day,
            "KOSPI",
            bas_dd,
            logs,
        )

        if (
            norm is not None
            and not norm.empty
        ):
            fetch_success += 1

            for code in EXPECTED:
                match = norm[
                    norm["ticker"]
                    == code
                ]
                if match.empty:
                    continue

                data = (
                    match.iloc[-1].to_dict()
                )
                data[
                    "date"
                ] = pd.Timestamp(
                    data["date"]
                ).normalize()

                if valid_close(data):
                    by_code[
                        code
                    ][day] = data

        time.sleep(0.08)

    out = []
    recoverable = []
    insufficient = []
    classes = Counter()

    for code in sorted(EXPECTED):
        rows = [
            by_code[code][d]
            for d in target_sessions
            if (
                d in by_code[code]
                and valid_close(
                    by_code[code][d]
                )
            )
        ]

        (
            pct,
            returns,
            return_dates,
        ) = calc(rows)

        if pct is None:
            cls = (
                "INSUFFICIENT_OFFICIAL_CLOSE_SESSIONS"
            )
            insufficient.append(code)
        else:
            cls = (
                "OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE"
            )
            recoverable.append(code)

        classes[cls] += 1

        used = sorted(
            rows,
            key=lambda r: pd.Timestamp(
                r["date"]
            ),
        )[-MIN_VALID_CLOSES:]

        used_dates = [
            pd.Timestamp(
                r["date"]
            ).date().isoformat()
            for r in used
        ]

        out.append({
            "ticker": code,
            "name": EXPECTED[code],
            "basis_date": basis_iso,
            "basis_source": basis_source,
            "calendar_buffer_sessions": len(
                target_sessions
            ),
            "initial_valid_close_count": (
                initial_counts[code]
            ),
            "final_valid_close_count": len(
                rows
            ),
            "required_valid_close_count": (
                MIN_VALID_CLOSES
            ),
            "elasticity_window_sessions": (
                WINDOW_RETURNS
            ),
            "avg_daily_move_pct": (
                f"{pct:.2f}"
                if pct is not None
                else ""
            ),
            "classification": cls,
            "used_close_dates_json": (
                json.dumps(
                    used_dates,
                    ensure_ascii=False,
                    separators=(
                        ",",
                        ":",
                    ),
                )
            ),
            "last20_return_dates_json": (
                json.dumps(
                    return_dates[
                        -WINDOW_RETURNS:
                    ],
                    ensure_ascii=False,
                    separators=(
                        ",",
                        ":",
                    ),
                )
            ),
            "last20_returns_json": (
                json.dumps(
                    [
                        round(x, 10)
                        for x in returns[
                            -WINDOW_RETURNS:
                        ]
                    ],
                    ensure_ascii=False,
                    separators=(
                        ",",
                        ":",
                    ),
                )
            ),
            "source": (
                "KRX_OFFICIAL_STK_BYDD_TRD"
            ),
        })

    if len(out) != 2:
        raise RuntimeError(
            "V8145_OUTPUT_COUNT_NOT_2:"
            + str(len(out))
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
                out[0].keys()
            ),
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(out)

    next_step = (
        "FREEZE_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AND_SHADOW_V8146"
        if recoverable
        else
        "AUDIT_NEXT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8146"
    )

    result = {
        "version": VERSION,
        "generated_at_kst": datetime.now(
            KST
        ).isoformat(
            timespec="seconds"
        ),
        "status": (
            "AUDIT_ONLY_CURRENT_ACTIONABLE_PRICE_ELASTICITY"
        ),
        "policy_version": POLICY_VERSION,
        "v8144a_version": V8144A_VERSION,
        "v8144a_result_commit": (
            V8144A_RESULT_COMMIT
        ),
        "metric_contract": {
            "metric": (
                "avg_daily_move_pct"
            ),
            "definition": (
                "mean(abs(close_t / close_t_minus_1 - 1)) "
                "over latest 20 official close returns * 100"
            ),
            "return_count": (
                WINDOW_RETURNS
            ),
            "minimum_valid_closes": (
                MIN_VALID_CLOSES
            ),
            "atr_substitution_allowed": False,
        },
        "target_count": 2,
        "target_tickers": sorted(
            EXPECTED
        ),
        "target_names": [
            EXPECTED[x]
            for x in sorted(
                EXPECTED
            )
        ],
        "basis_date": basis_iso,
        "basis_source": basis_source,
        "manifest_basis_date": (
            manifest.get(
                "basis_date"
            )
        ),
        "calendar_buffer_sessions": len(
            target_sessions
        ),
        "krx_refetch_date_count": (
            fetch_count
        ),
        "krx_refetch_success_date_count": (
            fetch_success
        ),
        "classification_counts": dict(
            classes
        ),
        "recoverable_count": len(
            recoverable
        ),
        "recoverable_tickers": sorted(
            recoverable
        ),
        "insufficient_count": len(
            insufficient
        ),
        "insufficient_tickers": sorted(
            insufficient
        ),
        "secondary_actionable_single_group": {
            "source_group": (
                "PRODUCTION_ANALYSIS_SUPPLY"
            ),
            "ticker_count": 1,
            "tickers": ["072130"],
        },
        "hard_guards": {
            "production_price_elasticity_cache_modified": False,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_api_modified": False,
            "scoring_policy_modified": False,
            "atr_used_as_elasticity_substitute": False,
            "nonofficial_price_source_used": False,
            "source_promoted": False,
        },
        "next_step": next_step,
    }

    OUT_JSON.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY_CURRENT_ACTIONABLE_PRICE_ELASTICITY",
            "TARGET_COUNT=2",
            f"BASIS_DATE={basis_iso}",
            f"KRX_REFETCH_DATE_COUNT={fetch_count}",
            f"KRX_REFETCH_SUCCESS_DATE_COUNT={fetch_success}",
            f"RECOVERABLE={len(recoverable)}",
            f"INSUFFICIENT={len(insufficient)}",
            "SECONDARY_SUPPLY_ACTIONABLE=1",
            "ATR_SUBSTITUTION_USED=false",
            "NONOFFICIAL_PRICE_SOURCE_USED=false",
            "PRODUCTION_PRICE_ELASTICITY_CACHE_MODIFIED=false",
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
            "# V8.14.5 current actionable price-elasticity audit",
            "",
            "- Targets: LS (006260), HD현대 (267250).",
            "- Source: official KRX daily close only.",
            "- Metric: latest 20 close-to-close absolute returns mean.",
            "- ATR substitution is forbidden.",
            "- Production cache is not modified.",
            "",
            f"- Basis date: {basis_iso}",
            f"- Recoverable: {len(recoverable)}",
            f"- Insufficient: {len(insufficient)}",
            f"- Next: `{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        "V8145_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AUDIT=PASS"
    )

if __name__ == "__main__":
    main()
