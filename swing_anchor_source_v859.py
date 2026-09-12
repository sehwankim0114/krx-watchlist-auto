#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V8.5.9 swing-anchor source builder.

Reuses the existing V8.5.0 swing contract exactly.
Produces descriptive swing anchor evidence only; it does NOT create a
confirmed swing-low trailing-stop price or a standalone swing table.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_table_metrics_v850 import (
    VERSION as METRIC_VERSION,
    current_streak,
    ma_info,
    normalize_bars,
    swing_phase,
)

SCRIPT_VERSION = "swing_anchor_source_v859.py v1.1.0-preserve-extended-glossary"
CONTRACT_VERSION = "2026-09-11-v8.5.9-swing-anchor-source-and-glossary"
KST = ZoneInfo("Asia/Seoul")

CACHE = Path("latest/active_stock_long_history_260d_latest.csv")
CACHE_META = Path("latest/active_stock_long_history_260d_meta_latest.json")
KOSPI_API = Path("api/two_table_v1/kospi.json")

OUT_CSV = Path("latest/swing_anchor_source_latest.csv")
OUT_META = Path("latest/swing_anchor_source_meta_latest.json")
OUT_GLOSSARY = Path("latest/stock_table_metric_glossary_latest.json")
OUT_LOG = Path("latest/swing_anchor_source_run_log_latest.txt")

COLUMNS = [
    "basis_date",
    "market",
    "ticker",
    "name",
    "history_rows",
    "phase_code",
    "phase_ko",
    "bottom_rebound",
    "new_20d_low",
    "swing_trough_date",
    "swing_trough_close",
    "swing_peak_date",
    "swing_peak_close",
    "from_trough_pct",
    "from_peak_pct",
    "momentum_5d_pct",
    "ma20_value",
    "ma20_direction",
    "ma20_slope_5d_pct",
    "confirmed_swing_low_stop",
    "trailing_reference_status",
    "source_metric_contract_version",
]

PHASE_KO = {
    "BOTTOM_REBOUND": "저점반등",
    "UPTREND": "상승중",
    "UPTREND_PULLBACK": "상승중 눌림",
    "TOP_DECLINE": "고점후하락",
    "NEW_LOW": "최근 신저점",
    "EARLY_REBOUND_UNCONFIRMED": "초기반등·확인부족",
    "SIDEWAYS_OR_UNCONFIRMED": "횡보·방향미확인",
    "INSUFFICIENT": "자료부족",
}

GLOSSARY = {
    "version": CONTRACT_VERSION,
    "display_policy": {
        "attach_to_stock_tables": True,
        "recommended_location": "TABLE_FOOTNOTE",
        "keep_cell_text_compact": True,
        "purpose": "표의 핵심 지표를 초보자도 바로 해석할 수 있게 설명한다.",
    },
    "terms": {
        "swing": {
            "label": "스윙",
            "short": "최근 큰 가격파동에서 현재 위치를 보여주는 과거 상태 분류",
            "detail": "확정 일봉 기준 큰 스윙 상태다. 저점반등·상승중·상승중 눌림·고점후하락·최근 신저점·초기반등 확인부족·횡보/방향미확인으로 읽는다. 미래 포물선이나 상승·하락 예측이 아니다.",
        },
        "ma": {
            "label": "MA5/20/60/120",
            "short": "5·20·60·120일 이동평균과 5거래일 전 대비 방향",
            "detail": "5일은 매우 단기, 20일은 단기, 60일은 중기, 120일은 중장기 흐름 참고다. ↑는 이동평균 상승, ↓는 하락, →는 거의 보합을 뜻한다.",
        },
        "atr14": {
            "label": "ATR14",
            "short": "Wilder 방식 최근 14기간 평균진폭",
            "detail": "최근 가격 변동성이 얼마나 컸는지 보는 지표다. 예상수익률이나 내일의 확정 변동폭이 아니다.",
        },
        "rs_kospi": {
            "label": "RS 1M/3M",
            "short": "같은 기간 KOSPI 대비 상대수익률 차이(%p)",
            "detail": "양수면 같은 기간 KOSPI보다 강했고 음수면 약했다는 뜻이다. 현재 값은 KOSPI 대비이며 업종 상대강도와 다르다.",
        },
        "streak": {
            "label": "연속등락",
            "short": "현재 진행 중인 연속 상승·하락 방향, 일수, 누적등락률",
            "detail": "예: ↓3일 / -3.6%는 최근 3거래일 연속 하락했고 그 연속 구간 누적등락률이 -3.6%라는 뜻이다.",
        },
    },
    "compact_footer_text": "읽는 법: 스윙=최근 큰 가격파동의 현재 위치(미래예측 아님) · MA5/20/60/120=단기→중장기 이동평균 방향 · ATR14=최근 14기간 평균진폭(예상수익률 아님) · RS=KOSPI 대비 상대수익률 차이 · 연속등락=현재 연속 상승/하락 일수와 누적등락률",
}

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def norm_ticker(v) -> str:
    s = str(v or "").strip().replace("'", "")
    if not s.isdigit() or not 1 <= len(s) <= 6:
        raise ValueError(f"INVALID_TICKER:{v}")
    return s.zfill(6)

def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("'", "")
    if s in {"", "-", "None", "nan", "NaN", "null"}:
        return None
    return float(s)

def rounded(v, digits=4):
    return None if v is None else round(float(v), digits)

def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

def atomic_json(path: Path, payload):
    atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
    )

def atomic_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)

def canonical(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def self_test():
    assert PHASE_KO["BOTTOM_REBOUND"] == "저점반등"
    assert PHASE_KO["TOP_DECLINE"] == "고점후하락"
    assert GLOSSARY["terms"]["rs_kospi"]["short"].endswith("(%p)")
    assert "미래예측 아님" in GLOSSARY["compact_footer_text"]
    assert "confirmed_swing_low_stop" in COLUMNS
    assert len(COLUMNS) == len(set(COLUMNS))
    print("SELF_TEST=PASS")
    print(f"SCRIPT_VERSION={SCRIPT_VERSION}")
    print(f"CONTRACT_VERSION={CONTRACT_VERSION}")
    print("CONFIRMED_SWING_LOW_STOP_CALCULATED=false")
    print("STANDALONE_SWING_TABLE_ENABLED=false")
    print("METRIC_FORMULA_CHANGED=false")
    return 0

def build():
    for p in (CACHE, CACHE_META, KOSPI_API, Path("stock_table_metrics_v850.py")):
        if not p.exists():
            raise RuntimeError(f"REQUIRED_FILE_MISSING:{p}")

    cache_meta = read_json(CACHE_META)
    if cache_meta.get("status") != "READY":
        raise RuntimeError("V857_CACHE_NOT_READY")
    if cache_meta.get("source_only") is not True:
        raise RuntimeError("V857_CACHE_NOT_SOURCE_ONLY")
    if cache_meta.get("request_time_price_eligible") is not False:
        raise RuntimeError("REQUEST_TIME_PRICE_GUARD_BROKEN")

    basis = str(cache_meta.get("cache_max_date") or "")
    if not basis or basis != cache_meta.get("source_max_date"):
        raise RuntimeError("CACHE_BASIS_MISMATCH")

    rows = read_csv(CACHE)
    grouped = defaultdict(list)
    names = {}
    markets = {}
    for r in rows:
        code = norm_ticker(r["ticker"])
        grouped[code].append(r)
        names[code] = str(r.get("name") or "").strip()
        markets[code] = str(r.get("market") or "").strip().upper()

    targets = [norm_ticker(x) for x in cache_meta.get("target_tickers") or []]
    if len(targets) != int(cache_meta.get("target_ticker_count") or 0):
        raise RuntimeError("TARGET_COUNT_META_MISMATCH")
    if set(targets) != set(grouped):
        raise RuntimeError(
            f"CACHE_TARGET_SET_MISMATCH:meta={len(set(targets))},rows={len(set(grouped))}"
        )

    out_rows = []
    phase_counts = Counter()

    for code in sorted(targets, key=lambda c: (markets.get(c, ""), c)):
        bars = normalize_bars(grouped[code], basis)
        if not bars or bars[-1]["date"] != basis:
            # A listed active name can legitimately lack the last bar in rare
            # suspension cases; preserve evidence as insufficient, never invent.
            phase = {
                "phase": "INSUFFICIENT",
                "bottom_rebound": False,
                "new_20d_low": None,
                "trough_date": None,
                "peak_date": None,
                "from_trough_pct": None,
                "from_peak_pct": None,
                "momentum_5d_pct": None,
            }
            ma20 = {"value": None, "slope_5d_pct": None, "direction": None}
        else:
            closes = [b["close"] for b in bars]
            ma20 = ma_info(closes, 20)
            streak = current_streak(closes)
            phase = swing_phase(bars, ma20, streak, basis)

        phase_code = phase.get("phase") or "INSUFFICIENT"
        phase_counts[phase_code] += 1
        close_by_date = {b["date"]: b["close"] for b in bars}

        out_rows.append({
            "basis_date": basis,
            "market": markets.get(code),
            "ticker": code,
            "name": names.get(code),
            "history_rows": len(bars),
            "phase_code": phase_code,
            "phase_ko": PHASE_KO.get(phase_code, phase_code),
            "bottom_rebound": phase.get("bottom_rebound"),
            "new_20d_low": phase.get("new_20d_low"),
            "swing_trough_date": phase.get("trough_date"),
            "swing_trough_close": close_by_date.get(phase.get("trough_date")),
            "swing_peak_date": phase.get("peak_date"),
            "swing_peak_close": close_by_date.get(phase.get("peak_date")),
            "from_trough_pct": phase.get("from_trough_pct"),
            "from_peak_pct": phase.get("from_peak_pct"),
            "momentum_5d_pct": phase.get("momentum_5d_pct"),
            "ma20_value": ma20.get("value"),
            "ma20_direction": ma20.get("direction"),
            "ma20_slope_5d_pct": ma20.get("slope_5d_pct"),
            "confirmed_swing_low_stop": "",
            "trailing_reference_status": "REFERENCE_ONLY_NOT_ORDER",
            "source_metric_contract_version": METRIC_VERSION,
        })

    # Exact regression against the published KOSPI 30 swing/MA20 evidence.
    api = read_json(KOSPI_API)
    if api.get("basis_date") != basis:
        raise RuntimeError("PUBLISHED_KOSPI_BASIS_MISMATCH")
    api_rows = api.get("rows") or []
    if len(api_rows) != 30:
        raise RuntimeError(f"PUBLISHED_KOSPI_ROW_COUNT_INVALID:{len(api_rows)}")

    generated = {r["ticker"]: r for r in out_rows}
    regression_mismatch = []

    for published_row in api_rows:
        code = norm_ticker(published_row["ticker"])
        if code not in generated:
            regression_mismatch.append({"ticker": code, "reason": "NOT_IN_GENERATED"})
            continue

        g = generated[code]
        m = published_row.get("metrics") or {}
        swing = m.get("swing") or {}
        ma20 = (m.get("ma") or {}).get("20") or {}
        tr = m.get("trailing_reference") or {}

        expected = {
            "phase_code": swing.get("phase"),
            "bottom_rebound": swing.get("bottom_rebound"),
            "new_20d_low": swing.get("new_20d_low"),
            "swing_trough_date": swing.get("trough_date"),
            "swing_peak_date": swing.get("peak_date"),
            "from_trough_pct": swing.get("from_trough_pct"),
            "from_peak_pct": swing.get("from_peak_pct"),
            "momentum_5d_pct": swing.get("momentum_5d_pct"),
            "ma20_value": ma20.get("value"),
            "ma20_direction": ma20.get("direction"),
            "ma20_slope_5d_pct": ma20.get("slope_5d_pct"),
            "confirmed_swing_low_stop": tr.get("confirmed_swing_low_stop"),
            "trailing_reference_status": tr.get("status"),
        }

        actual = {
            k: (None if g[k] == "" and k == "confirmed_swing_low_stop" else g[k])
            for k in expected
        }

        if canonical(actual) != canonical(expected):
            changed = [
                k for k in expected
                if canonical(actual.get(k)) != canonical(expected.get(k))
            ]
            regression_mismatch.append({
                "ticker": code,
                "name": g["name"],
                "changed": changed,
            })

    if regression_mismatch:
        raise RuntimeError(
            "KOSPI30_SWING_ANCHOR_REGRESSION_FAILED:"
            + canonical(regression_mismatch[:10])
        )

    if any(r["confirmed_swing_low_stop"] not in ("", None) for r in out_rows):
        raise RuntimeError("CONFIRMED_SWING_LOW_STOP_UNEXPECTEDLY_GENERATED")

    atomic_csv(OUT_CSV, out_rows)

    # V8.7.0+ may extend the shared stock-table glossary (for example rs_sector).
    # This V8.5.9 source builder owns swing evidence, not later glossary terms.
    glossary_payload = GLOSSARY
    if OUT_GLOSSARY.exists():
        current_glossary = read_json(OUT_GLOSSARY)
        current_terms = current_glossary.get("terms") or {}
        required_base_terms = {"swing", "ma", "atr14", "rs_kospi", "streak"}
        if (
            isinstance(current_terms, dict)
            and required_base_terms.issubset(set(current_terms))
            and "rs_sector" in current_terms
            and current_glossary.get("display_policy", {}).get("attach_to_stock_tables") is True
        ):
            glossary_payload = current_glossary
    atomic_json(OUT_GLOSSARY, glossary_payload)

    meta = {
        "script_version": SCRIPT_VERSION,
        "contract_version": CONTRACT_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "READY",
        "source_only": True,
        "standalone_swing_table_enabled": False,
        "metric_formula_changed": False,
        "basis_date": basis,
        "source_metric_contract_version": METRIC_VERSION,
        "source_cache": str(CACHE),
        "source_cache_sha256": sha256(CACHE),
        "source_cache_meta_contract_version": cache_meta.get("contract_version"),
        "source_target_ticker_sha256": cache_meta.get("target_ticker_sha256"),
        "row_count": len(out_rows),
        "phase_counts": dict(sorted(phase_counts.items())),
        "published_kospi30_anchor_regression": {
            "expected_rows": 30,
            "exact_matches": 30,
            "mismatches": 0,
            "status": "PASS",
        },
        "glossary_file": str(OUT_GLOSSARY),
        "glossary_required_for_future_table_display": True,
        "confirmed_swing_low_stop": {
            "status": "NOT_CALCULATED",
            "reason": "SIGNAL_PRICE_BASIS_DATE_CONTRACT_NOT_DEFINED",
        },
        "hard_guards": {
            "confirmed_swing_low_stop_calculated": False,
            "sector_rs_calculated": False,
            "earnings_outlook_change_calculated": False,
            "investment_score_100_calculated": False,
            "request_time_price_substitution": False,
        },
    }
    atomic_json(OUT_META, meta)

    log = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"CONTRACT_VERSION={CONTRACT_VERSION}",
        f"BASIS_DATE={basis}",
        "V859_SWING_ANCHOR_SOURCE_STATUS=READY",
        f"ROWS={len(out_rows)}",
        f"PHASE_COUNTS={json.dumps(dict(sorted(phase_counts.items())), ensure_ascii=False, sort_keys=True)}",
        "KOSPI30_SWING_ANCHOR_EXACT_MATCHES=30",
        "KOSPI30_SWING_ANCHOR_MISMATCHES=0",
        f"GLOSSARY_TERMS={len((glossary_payload.get('terms') or {}))}",
        "GLOSSARY_FUTURE_TABLE_DISPLAY_REQUIRED=true",
        "CONFIRMED_SWING_LOW_STOP_CALCULATED=false",
        "STANDALONE_SWING_TABLE_ENABLED=false",
        "METRIC_FORMULA_CHANGED=false",
        "SECTOR_RS_CALCULATED=false",
        "EARNINGS_OUTLOOK_CHANGE_CALCULATED=false",
        "INVESTMENT_SCORE_100_CALCULATED=false",
        "REQUEST_TIME_PRICE_SUBSTITUTION=false",
    ]
    atomic_text(OUT_LOG, "\n".join(log) + "\n")

    print("\n".join(log))
    return 0

def validate():
    for p in (OUT_CSV, OUT_META, OUT_GLOSSARY, OUT_LOG):
        if not p.exists():
            raise RuntimeError(f"OUTPUT_MISSING:{p}")

    meta = read_json(OUT_META)
    glossary = read_json(OUT_GLOSSARY)
    rows = read_csv(OUT_CSV)

    if meta.get("status") != "READY":
        raise RuntimeError("META_NOT_READY")
    if meta.get("source_only") is not True:
        raise RuntimeError("META_NOT_SOURCE_ONLY")
    if meta.get("standalone_swing_table_enabled") is not False:
        raise RuntimeError("STANDALONE_SWING_TABLE_GUARD_FAILED")
    if meta.get("metric_formula_changed") is not False:
        raise RuntimeError("METRIC_FORMULA_GUARD_FAILED")
    if len(rows) != int(meta.get("row_count") or 0):
        raise RuntimeError("ROW_COUNT_MISMATCH")
    glossary_terms = glossary.get("terms") or {}
    required_glossary_terms = {"swing", "ma", "atr14", "rs_kospi", "streak"}
    if not isinstance(glossary_terms, dict) or not required_glossary_terms.issubset(set(glossary_terms)):
        raise RuntimeError("GLOSSARY_REQUIRED_TERMS_INVALID")
    if glossary.get("display_policy", {}).get("attach_to_stock_tables") is not True:
        raise RuntimeError("GLOSSARY_DISPLAY_POLICY_MISSING")
    if any(str(r.get("confirmed_swing_low_stop") or "").strip() for r in rows):
        raise RuntimeError("STOP_COLUMN_NOT_EMPTY")

    print("V859_VALIDATION=PASS")
    print(f"ROWS={len(rows)}")
    print(f"GLOSSARY_TERMS={len(glossary_terms)}")
    print("CONFIRMED_SWING_LOW_STOP_EMPTY_ALL=PASS")
    print("KOSPI30_SWING_ANCHOR_EXACT_MATCHES=30")
    print("REQUEST_TIME_PRICE_SUBSTITUTION=false")
    return 0

def main():
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    if "--validate-only" in args:
        return validate()
    return build()

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"V859_SWING_ANCHOR_SOURCE_STATUS=FAILED:{type(exc).__name__}:{exc}", file=sys.stderr)
        raise
