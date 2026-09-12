#!/usr/bin/env python3
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(".")
VERSION = "2026-09-12-v8.7.5-price-elasticity-20-session-source"
HISTORY = ROOT / "latest/active_stock_long_history_260d_latest.csv"
META = ROOT / "latest/active_stock_long_history_260d_meta_latest.json"
MANIFEST = ROOT / "api/two_table_v1/manifest.json"
OUTCSV = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"
OUTJSON = ROOT / "latest/investment_score_price_elasticity_20d_latest.json"
OUTLOG = ROOT / "latest/investment_score_price_elasticity_20d_run_log_latest.txt"
OUTDOC = ROOT / "docs/investment_score_price_elasticity_contract_v875.md"

def ticker(value):
    text = "".join(c for c in str(value or "") if c.isdigit())
    return text.zfill(6) if text else ""

def number(value):
    try:
        x = float(str(value).replace(",", ""))
        return x if math.isfinite(x) else None
    except Exception:
        return None

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

meta = read_json(META)
manifest = read_json(MANIFEST)

if meta.get("status") != "READY" or meta.get("source_only") is not True:
    raise SystemExit("HISTORY_NOT_READY")

basis = str(manifest.get("basis_date") or "")
if basis != str(meta.get("cache_max_date") or ""):
    raise SystemExit("HISTORY_BASIS_MISMATCH")

prod = {}
for table in ("kospi", "decliners", "decliners24"):
    for row in read_json(ROOT / f"api/two_table_v1/{table}.json").get("rows") or []:
        code = ticker(row.get("ticker"))
        if code:
            prod[code] = str(row.get("name") or "")

history = {}
with HISTORY.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        code = ticker(row.get("ticker"))
        close = number(row.get("close"))
        date = str(row.get("date") or "")[:10]
        if code and close and close > 0 and date:
            history.setdefault(code, {})[date] = close

rows = []
for code in sorted(prod):
    series = sorted((history.get(code) or {}).items())
    if len(series) < 21:
        rows.append({
            "ticker": code,
            "name": prod[code],
            "basis_date": basis,
            "window_start_date": "",
            "window_end_date": "",
            "close_observation_count": len(series),
            "daily_return_observation_count": max(0, len(series) - 1),
            "avg_daily_move_abs": "",
            "avg_daily_move_pct": "",
            "source_status": "LIMITED_INSUFFICIENT_HISTORY",
        })
        continue

    window = series[-21:]
    dates = [x[0] for x in window]
    closes = [x[1] for x in window]

    absolute_moves = [abs(cur - prev) for prev, cur in zip(closes[:-1], closes[1:])]
    absolute_returns = [
        abs(cur / prev - 1.0) * 100.0
        for prev, cur in zip(closes[:-1], closes[1:])
    ]

    if len(absolute_returns) != 20:
        raise SystemExit(f"RETURN_COUNT_MISMATCH:{code}")

    rows.append({
        "ticker": code,
        "name": prod[code],
        "basis_date": basis,
        "window_start_date": dates[0],
        "window_end_date": dates[-1],
        "close_observation_count": 21,
        "daily_return_observation_count": 20,
        "avg_daily_move_abs": round(sum(absolute_moves) / 20.0, 4),
        "avg_daily_move_pct": round(sum(absolute_returns) / 20.0, 4),
        "source_status": "READY",
    })

ready = sum(row["source_status"] == "READY" for row in rows)
limited = len(rows) - ready

OUTCSV.parent.mkdir(parents=True, exist_ok=True)
with OUTCSV.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

payload = {
    "version": VERSION,
    "generated_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
    "status": "READY_SOURCE_ONLY" if limited == 0 else "PARTIAL_SOURCE_ONLY",
    "basis_date": basis,
    "production_unique_tickers": len(prod),
    "ready_tickers": ready,
    "limited_tickers": limited,
    "formula": "mean(abs(close_t/close_t_minus_1-1)*100) for latest 20 trading-session returns",
    "close_observations_required": 21,
    "daily_return_observations_required": 20,
    "source": "official KRX compact 260-session history cache",
    "hard_guards": {
        "investment_score_100_calculated": False,
        "score_thresholds_defined": False,
        "avg_daily_range_20_pct_substituted": False,
        "production_api_changed": False,
    },
}
OUTJSON.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

log = [
    f"VERSION={VERSION}",
    f"BASIS_DATE={basis}",
    f"PRODUCTION_UNIQUE_TICKERS={len(prod)}",
    f"PRICE_ELASTICITY_20D_READY={ready}",
    f"PRICE_ELASTICITY_20D_LIMITED={limited}",
    "CLOSE_OBSERVATIONS_REQUIRED=21",
    "DAILY_RETURN_OBSERVATIONS_REQUIRED=20",
    "AVG_DAILY_RANGE_20_PCT_SUBSTITUTED=false",
    "INVESTMENT_SCORE_100_CALCULATED=false",
    "SCORE_THRESHOLDS_DEFINED=false",
    "PRODUCTION_DATA_CHANGED=false",
    "STATUS=OK",
]
OUTLOG.write_text("\n".join(log) + "\n", encoding="utf-8")

OUTDOC.parent.mkdir(parents=True, exist_ok=True)
OUTDOC.write_text(
"""# V8.7.5 최근 20거래일 가격탄력 원천 계약

- 정책: 최근 20거래일 하루평균 절대등락률
- 산식: 최근 21개 유효 종가에서 20개 `abs(close_t/close_t-1-1)*100`을 만들고 산술평균
- 원천: V8.5.7 공식 KRX 260거래일 source-only 캐시
- 금지: 3개월 전체 평균 대체, avg_daily_range_20_pct 대체, 투자점수 계산, 점수구간 임의 정의
""",
encoding="utf-8",
)

print("\n".join(log))
