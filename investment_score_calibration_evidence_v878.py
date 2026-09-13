#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

VERSION = "2026-09-13-v8.7.8-investment-score-calibration-evidence"
KST = ZoneInfo("Asia/Seoul")
ROOT = Path(".")

POLICY_EVIDENCE = ROOT / "latest/investment_score_policy_evidence_latest.json"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"
RAW = ROOT / "latest/investment_score_source_cache_latest.csv"
OCF = ROOT / "latest/investment_score_ocf_source_latest.csv"
ELASTICITY = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"

OUT_JSON = ROOT / "latest/investment_score_calibration_evidence_latest.json"
OUT_CSV = ROOT / "latest/investment_score_calibration_universe_latest.csv"
OUT_LOG = ROOT / "latest/investment_score_calibration_evidence_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_calibration_evidence_v878.md"

NUMERIC_FIELDS = {
    "revenue_yoy_pct": "최근 확정 재무 매출 YoY",
    "operating_profit_yoy_pct": "최근 확정 재무 영업이익 YoY",
    "net_income_yoy_pct": "최근 확정 재무 순이익 YoY",
    "operating_margin_pct": "영업이익률",
    "roe_annualized_pct": "ROE 연환산",
    "debt_ratio_pct": "부채비율",
    "per_annualized": "PER 연환산",
    "pbr": "PBR",
    "q2_revenue_yoy_pct": "최근 분기 매출 YoY",
    "q2_operating_profit_yoy_pct": "최근 분기 영업이익 YoY",
    "q2_net_income_yoy_pct": "최근 분기 순이익 YoY",
    "operating_cash_flow_annual": "연간 영업현금흐름 원천",
    "return_1m_pct": "1개월 수익률",
    "return_3m_pct": "3개월 수익률",
    "position_3m_pct": "3개월 저고점 대비 현재위치",
    "atr14_pct": "ATR14 비율",
    "avg20_trading_value_krw": "20일 평균 거래대금",
    "volume_vs_20d": "20일 평균 대비 거래량 배율",
    "elasticity_20d_pct": "최근 20거래일 하루평균 절대등락률",
}

CATEGORICAL_FIELDS = {
    "earnings_trend": "이익 추세",
    "supply_level": "수급부담 수준",
    "swing_phase": "스윙 국면",
}

def clean_ticker(value):
    text = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    return text.zfill(6) if text else ""

def number(value):
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "None", "null", "nan", "NaN"}:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    return out if math.isfinite(out) else None

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv_map(path, key="ticker"):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return {
        clean_ticker(row.get(key)): row
        for row in rows
        if clean_ticker(row.get(key))
    }

def percentile(values, q):
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    frac = pos - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac

def summarize(values):
    xs = [x for x in values if x is not None and math.isfinite(x)]
    if not xs:
        return {
            "count": 0,
            "min": None,
            "p10": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p90": None,
            "max": None,
            "mean": None,
        }
    return {
        "count": len(xs),
        "min": round(min(xs), 6),
        "p10": round(percentile(xs, 0.10), 6),
        "p25": round(percentile(xs, 0.25), 6),
        "p50": round(percentile(xs, 0.50), 6),
        "p75": round(percentile(xs, 0.75), 6),
        "p90": round(percentile(xs, 0.90), 6),
        "max": round(max(xs), 6),
        "mean": round(mean(xs), 6),
    }

def production_rows():
    rows = {}
    for table in ("kospi", "decliners", "decliners24"):
        payload = read_json(ROOT / f"api/two_table_v1/{table}.json")
        for row in payload.get("rows") or []:
            ticker = clean_ticker(row.get("ticker"))
            if ticker:
                rows[ticker] = row
    return rows

def main():
    policy = read_json(POLICY_EVIDENCE)
    if policy.get("version") != (
        "2026-09-13-v8.7.7-investment-score-policy-evidence-audit"
    ):
        raise RuntimeError("POLICY_EVIDENCE_VERSION_MISMATCH")
    if policy.get("status") != "AUDIT_ONLY":
        raise RuntimeError("POLICY_EVIDENCE_NOT_READY")
    raw_candidate_count = policy.get("raw_to_point_candidate_component_count")
    if raw_candidate_count is None or int(raw_candidate_count) != 0:
        raise RuntimeError("EXISTING_RAW_TO_POINT_RULE_REQUIRES_REVIEW")
    if policy.get("hard_guards", {}).get("new_thresholds_created") is not False:
        raise RuntimeError("POLICY_GUARD_BROKEN")

    prod = production_rows()
    fin = read_csv_map(FIN)
    raw = read_csv_map(RAW)
    ocf = read_csv_map(OCF)
    elasticity = read_csv_map(ELASTICITY)

    rows = []

    for ticker in sorted(prod):
        p = prod[ticker]
        metrics = p.get("metrics") or {}
        analysis = p.get("analysis") or {}
        returns = metrics.get("returns") or {}
        range_3m = metrics.get("range_3m") or {}
        atr14 = metrics.get("atr14") or {}
        activity = metrics.get("activity") or {}
        swing = metrics.get("swing") or {}

        f = fin.get(ticker) or {}
        r = raw.get(ticker) or {}
        o = ocf.get(ticker) or {}
        e = elasticity.get(ticker) or {}

        rows.append({
            "ticker": ticker,
            "name": str(p.get("name") or ""),
            "market": str(p.get("market") or ""),
            "sector_theme": str(p.get("sector_theme") or ""),
            "revenue_yoy_pct": number(f.get("revenue_yoy_pct")),
            "operating_profit_yoy_pct": number(f.get("operating_profit_yoy_pct")),
            "net_income_yoy_pct": number(f.get("net_income_yoy_pct")),
            "operating_margin_pct": number(f.get("operating_margin_pct")),
            "roe_annualized_pct": number(f.get("roe_annualized_pct")),
            "debt_ratio_pct": number(f.get("debt_ratio_pct")),
            "per_annualized": number(f.get("per_annualized")),
            "pbr": number(f.get("pbr")),
            "earnings_trend": str(f.get("earnings_trend") or ""),
            "q2_revenue_yoy_pct": number(r.get("q2_revenue_yoy_pct")),
            "q2_operating_profit_yoy_pct": number(r.get("q2_operating_profit_yoy_pct")),
            "q2_net_income_yoy_pct": number(r.get("q2_net_income_yoy_pct")),
            "operating_cash_flow_annual": number(o.get("operating_cash_flow_annual")),
            "return_1m_pct": number((returns.get("1") or {}).get("pct")),
            "return_3m_pct": number((returns.get("3") or {}).get("pct")),
            "position_3m_pct": number(range_3m.get("position_pct")),
            "atr14_pct": number(atr14.get("pct")),
            "avg20_trading_value_krw": number(activity.get("avg20_trading_value_krw")),
            "volume_vs_20d": number(activity.get("volume_vs_20d")),
            "elasticity_20d_pct": number(e.get("avg_daily_move_pct")),
            "supply_level": str(analysis.get("supply_level") or ""),
            "swing_phase": str(swing.get("phase") or ""),
        })

    distributions = {}
    for field, label in NUMERIC_FIELDS.items():
        values = [row[field] for row in rows if row[field] is not None]
        distributions[field] = {
            "label": label,
            "summary": summarize(values),
            "policy_status": "EMPIRICAL_REFERENCE_ONLY_NOT_SCORE_THRESHOLD",
        }

    categories = {}
    for field, label in CATEGORICAL_FIELDS.items():
        counts = Counter(
            row[field]
            for row in rows
            if str(row[field]).strip()
        )
        categories[field] = {
            "label": label,
            "counts": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
            "policy_status": "EMPIRICAL_REFERENCE_ONLY_NOT_SCORE_MAPPING",
        }

    payload = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "CALIBRATION_EVIDENCE_ONLY",
        "basis_date": policy.get("basis_date"),
        "production_unique_tickers": len(prod),
        "row_count": len(rows),
        "numeric_distributions": distributions,
        "categorical_distributions": categories,
        "known_policy_blockers": policy.get("policy_blockers"),
        "important_limitations": {
            "ev_ebitda": "NOT_INCLUDED_POLICY_UNDEFINED_AND_SOURCE_NOT_READY",
            "net_cash": "NOT_INCLUDED_POLICY_UNDEFINED",
            "psr": "NOT_DERIVED_NO_PROJECT_FORMULA_CONTRACT",
            "three_year_growth": "RAW_ANNUAL_VALUES_EXIST_BUT_NO_PROJECT_GROWTH_FORMULA_CONTRACT",
            "score_thresholds": "NOT_CREATED",
        },
        "hard_guards": {
            "investment_score_100_calculated": False,
            "component_points_calculated": False,
            "new_score_thresholds_created": False,
            "percentiles_used_as_thresholds": False,
            "production_api_changed": False,
        },
        "next_step": (
            "USE_EMPIRICAL_DISTRIBUTIONS_AS_REFERENCE_FOR_USER_APPROVED_SCORE_POLICY; "
            "DO_NOT_ACTIVATE_SCORE_WITHOUT_EXPLICIT_THRESHOLD_CONTRACT"
        ),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)

    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    fields = list(rows[0].keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    log = [
        f"VERSION={VERSION}",
        f"BASIS_DATE={policy.get('basis_date')}",
        f"PRODUCTION_UNIQUE_TICKERS={len(prod)}",
        f"ROW_COUNT={len(rows)}",
        f"NUMERIC_DISTRIBUTION_COUNT={len(distributions)}",
        f"CATEGORICAL_DISTRIBUTION_COUNT={len(categories)}",
        "INVESTMENT_SCORE_100_CALCULATED=false",
        "COMPONENT_POINTS_CALCULATED=false",
        "NEW_SCORE_THRESHOLDS_CREATED=false",
        "PERCENTILES_USED_AS_THRESHOLDS=false",
        "PRODUCTION_DATA_CHANGED=false",
        "STATUS=OK",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    doc = [
        "# V8.7.8 투자종합점수 보정자료",
        "",
        f"버전: `{VERSION}`",
        "",
        "## 목적",
        "",
        "현재 production 종목의 실제 지표 분포를 관찰해 향후 점수정책 설계의 근거자료를 만든다.",
        "분위수는 관찰값이며 점수 컷으로 자동 채택하지 않는다.",
        "",
        "## 포함",
        "",
        "- 최근 재무 YoY, 영업이익률, ROE, 부채비율",
        "- PER, PBR",
        "- 최근 분기 YoY",
        "- 공식 영업현금흐름 원천",
        "- 1개월·3개월 수익률, 현재위치, ATR14",
        "- 20일 평균 거래대금·거래량 배율",
        "- 최근 20거래일 하루평균 절대등락률",
        "- 이익 추세, 수급부담 수준, 스윙 국면 빈도",
        "",
        "## 제외",
        "",
        "- EV/EBITDA: D&A 정책 미정",
        "- 순현금: 부채 포함범위 미정",
        "- PSR: 프로젝트 내 공식 계산계약 없음",
        "- 3년 성장률: 원자료는 있으나 공식 성장률 산식계약 없음",
        "",
        "## 안전장치",
        "",
        "- investment_score_100 미계산",
        "- 세부점수 미계산",
        "- 분위수를 점수구간으로 자동 사용 금지",
        "- production API 미변경",
        "",
    ]
    OUT_DOC.write_text("\n".join(doc), encoding="utf-8")

    print("\n".join(log))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
