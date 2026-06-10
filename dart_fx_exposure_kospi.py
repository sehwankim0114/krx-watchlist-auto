#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
dart_fx_exposure_kospi.py
v1.0_dart_fx_exposure_precision

목적
- 코스피 전체 종목에 대해 OpenDART 정기보고서 원문을 확인한다.
- 사업보고서/반기/분기보고서 주석에서 환율노출 관련 단서를 추출한다.
- 달러/해외매출, 환헤지, 외화부채, 수입원가 부담, 환율민감도, 공시신뢰도를 점수화한다.
- 기존 GitHub KRX 코스피 가격자료와 결합해 환율약세표 30개 후보와 7개 추천표를 생성한다.

생성 파일
- latest/kospi_fx_exposure_raw_latest.csv
- latest/kospi_fx_exposure_precision_latest.csv
- latest/kospi_fx_weakness_candidates_30_latest.csv
- latest/kospi_fx_weakness_recommend_7_latest.csv
- latest/kospi_fx_exposure_run_log_latest.txt
- latest/kospi_fx_weakness_run_log_latest.txt
- latest/dart_corp_code_cache.csv
- latest/dart_fx_exposure_cache.csv
"""

from __future__ import annotations

import argparse
import html
import io
import json
import math
import os
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import pandas as pd
import requests


KST = timezone(timedelta(hours=9))

DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"

REPORT_PRIORITY = {
    "사업보고서": 100,
    "반기보고서": 80,
    "3분기보고서": 70,
    "분기보고서": 65,
    "1분기보고서": 60,
}

EXPORT_WORDS = [
    "수출", "해외매출", "해외 매출", "국외매출", "국외 매출",
    "외화매출", "외화 매출", "달러매출", "달러 매출",
    "지역별 매출", "미국", "북미", "유럽", "중국", "아시아",
]

FX_ASSET_WORDS = [
    "외화자산", "외화 자산", "외화금융자산", "외화 금융자산",
    "USD", "미달러", "달러", "외환위험", "환위험",
]

FX_LIAB_WORDS = [
    "외화부채", "외화 부채", "외화금융부채", "외화 금융부채",
    "외화차입", "외화 차입", "외화차입금", "외화 차입금",
]

HEDGE_WORDS = [
    "통화선도", "선물환", "환헤지", "환 헤지", "위험회피",
    "파생상품", "통화스왑", "외환파생", "외환 파생",
]

IMPORT_COST_WORDS = [
    "수입원재료", "수입 원재료", "원재료 수입", "수입비중",
    "원재료", "매입", "유가", "원유", "천연가스", "LNG",
    "나프타", "알루미늄", "구리", "동", "철광석", "곡물",
    "팜유", "밀", "설탕", "환율 상승에 따른 원가",
]

ORDER_WORDS = [
    "수주잔고", "수주 잔고", "외화수주", "외화 수주",
    "계약잔액", "계약 잔액", "미청구공사", "선박", "방산",
]

SENSITIVITY_WORDS = [
    "환율 10%", "환율이 10%", "외화에 대한 원화환율",
    "원화 환율", "환율변동", "환율 변동", "민감도",
]


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S%z")


def today_yyyymmdd() -> str:
    return datetime.now(KST).strftime("%Y%m%d")


def date_days_ago_yyyymmdd(days: int) -> str:
    return (datetime.now(KST) - timedelta(days=days)).strftime("%Y%m%d")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def clean_ticker(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(float(value))):
        return ""
    s = str(value).strip()
    s = re.sub(r"\.0$", "", s)
    s = re.sub(r"[^0-9]", "", s)
    return s.zfill(6) if s else ""


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(float(value))):
        return ""
    return str(value).strip()


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not math.isnan(float(value)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", "").replace("원", "").replace("%", "").replace("−", "-")
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def format_won(value: Optional[float]) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return f"{int(round(value)):,}원"


def read_csv_any(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"CSV 읽기 실패: {path} / {last_err}")


def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")


def find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for cand in candidates:
        key = cand.strip().lower()
        if key in lower_map:
            return lower_map[key]
    for col in df.columns:
        col_s = str(col).strip().lower()
        for cand in candidates:
            if cand.strip().lower() in col_s:
                return col
    return None


def normalize_report_text(raw: bytes) -> str:
    texts: List[str] = []

    def decode_bytes(b: bytes) -> str:
        for enc in ["utf-8", "utf-8-sig", "cp949", "euc-kr"]:
            try:
                return b.decode(enc, errors="ignore")
            except Exception:
                pass
        return b.decode("utf-8", errors="ignore")

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.lower().endswith((".xml", ".html", ".htm", ".txt")):
                    try:
                        texts.append(decode_bytes(zf.read(name)))
                    except Exception:
                        continue
    except zipfile.BadZipFile:
        texts.append(decode_bytes(raw))

    joined = "\n".join(texts)
    joined = re.sub(r"<[^>]+>", " ", joined)
    joined = html.unescape(joined)
    joined = re.sub(r"\s+", " ", joined)
    return joined.strip()


def keyword_count(text: str, words: List[str]) -> int:
    if not text:
        return 0
    return sum(text.count(w) for w in words)


def extract_sections(text: str, words: List[str], radius: int = 2500, limit: int = 4) -> str:
    if not text:
        return ""
    spans: List[str] = []
    seen = set()
    for w in words:
        for m in re.finditer(re.escape(w), text):
            start = max(0, m.start() - radius)
            end = min(len(text), m.end() + radius)
            key = (start // 1000, end // 1000)
            if key not in seen:
                spans.append(text[start:end])
                seen.add(key)
            if len(spans) >= limit:
                break
        if len(spans) >= limit:
            break
    return " ".join(spans)


def extract_percent_near(section: str, words: List[str]) -> Optional[float]:
    if not section:
        return None

    found: List[float] = []
    word_pat = "|".join(re.escape(w) for w in words)

    patterns = [
        rf"({word_pat})[^%]{{0,100}}?([0-9]{{1,3}}(?:\.[0-9]+)?)\s*%",
        rf"([0-9]{{1,3}}(?:\.[0-9]+)?)\s*%[^%]{{0,100}}?({word_pat})",
    ]

    for pat in patterns:
        for m in re.finditer(pat, section):
            for g in m.groups():
                try:
                    v = float(g)
                    if 0 <= v <= 100:
                        found.append(v)
                except Exception:
                    pass

    if not found:
        return None

    return max(found)


def classify_sector_proxy(name: str) -> Dict[str, Any]:
    n = name.replace(" ", "").upper()

    rules = [
        {
            "sector": "조선",
            "needles": ["조선", "중공업", "한화오션", "HD한국조선해양", "HD현대중공업", "삼성중공업"],
            "export_proxy": 90,
            "won_cost_proxy": 75,
            "import_burden_proxy": 35,
            "comment": "달러 선박수주·수주잔고 중심",
        },
        {
            "sector": "전력기기",
            "needles": ["일렉트릭", "효성중공업", "LSELECTRIC", "산일전기", "변압", "전선"],
            "export_proxy": 82,
            "won_cost_proxy": 70,
            "import_burden_proxy": 30,
            "comment": "전력기기·변압기 해외수주",
        },
        {
            "sector": "방산",
            "needles": ["한화에어로스페이스", "현대로템", "한국항공우주", "LIG", "디펜스", "풍산"],
            "export_proxy": 78,
            "won_cost_proxy": 68,
            "import_burden_proxy": 25,
            "comment": "방산·항공 수출수주",
        },
        {
            "sector": "반도체/전자부품",
            "needles": ["하이닉스", "삼성전자", "삼성전기", "한미반도체", "이수페타시스", "대덕전자", "LG이노텍", "반도체"],
            "export_proxy": 80,
            "won_cost_proxy": 60,
            "import_burden_proxy": 35,
            "comment": "반도체·AI 부품 수출",
        },
        {
            "sector": "자동차/부품",
            "needles": ["현대차", "기아", "현대모비스", "HL만도", "한국타이어", "타이어"],
            "export_proxy": 72,
            "won_cost_proxy": 55,
            "import_burden_proxy": 35,
            "comment": "완성차·부품 해외매출",
        },
        {
            "sector": "바이오/제약",
            "needles": ["바이오", "셀트리온", "한미약품", "유한양행", "종근당", "녹십자"],
            "export_proxy": 65,
            "won_cost_proxy": 60,
            "import_burden_proxy": 20,
            "comment": "글로벌 의약품·CDMO 매출",
        },
        {
            "sector": "K뷰티/소비재",
            "needles": ["코스맥스", "한국콜마", "아모레", "LG생활건강", "에이피알"],
            "export_proxy": 62,
            "won_cost_proxy": 55,
            "import_burden_proxy": 25,
            "comment": "K뷰티 해외매출",
        },
        {
            "sector": "K푸드",
            "needles": ["삼양식품", "농심", "오리온", "CJ제일제당"],
            "export_proxy": 55,
            "won_cost_proxy": 45,
            "import_burden_proxy": 50,
            "comment": "식품 수출 있으나 원재료 수입부담 동반",
        },
        {
            "sector": "수입원가부담",
            "needles": ["항공", "대한항공", "아시아나", "정유", "화학", "가스", "전력", "한국전력"],
            "export_proxy": 20,
            "won_cost_proxy": 35,
            "import_burden_proxy": 80,
            "comment": "유가·원재료·외화부채 부담 가능",
        },
    ]

    for rule in rules:
        if any(x.upper().replace(" ", "") in n for x in rule["needles"]):
            return rule

    return {
        "sector": "기타",
        "export_proxy": 25,
        "won_cost_proxy": 40,
        "import_burden_proxy": 45,
        "comment": "산업 프록시 약함",
    }


def dart_get_json(url: str, params: Dict[str, Any], retries: int = 3, sleep_sec: float = 0.7) -> Dict[str, Any]:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=25)
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(sleep_sec * (i + 1))
    return {"status": "HTTP_FAIL", "message": last_err or "unknown"}


def download_bytes(url: str, params: Dict[str, Any], retries: int = 3, sleep_sec: float = 0.7) -> Tuple[Optional[bytes], str]:
    last_err = ""
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=40)
            if r.status_code == 200 and r.content:
                return r.content, "OK"
            last_err = f"HTTP_{r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(sleep_sec * (i + 1))
    return None, last_err or "DOWNLOAD_FAIL"


def load_corp_code_map(api_key: str, output_dir: Path, refresh: bool = False) -> pd.DataFrame:
    cache_path = output_dir / "dart_corp_code_cache.csv"

    if cache_path.exists() and not refresh:
        try:
            cached = read_csv_any(cache_path)
            if {"corp_code", "corp_name", "stock_code"}.issubset(set(cached.columns)):
                cached["stock_code"] = cached["stock_code"].apply(clean_ticker)
                return cached
        except Exception:
            pass

    raw, status = download_bytes(DART_CORP_CODE_URL, {"crtfc_key": api_key}, retries=4)
    if raw is None:
        raise RuntimeError(f"DART corpCode.xml 다운로드 실패: {status}")

    rows: List[Dict[str, str]] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        xml_name = zf.namelist()[0]
        xml_bytes = zf.read(xml_name)
        root = ET.fromstring(xml_bytes)

        for item in root.findall(".//list"):
            corp_code = item.findtext("corp_code", default="").strip()
            corp_name = item.findtext("corp_name", default="").strip()
            stock_code = clean_ticker(item.findtext("stock_code", default=""))
            modify_date = item.findtext("modify_date", default="").strip()
            if stock_code:
                rows.append({
                    "corp_code": corp_code,
                    "corp_name": corp_name,
                    "stock_code": stock_code,
                    "modify_date": modify_date,
                })

    df = pd.DataFrame(rows).drop_duplicates(subset=["stock_code"], keep="last")
    write_csv(df, cache_path)
    return df


def choose_latest_report(api_key: str, corp_code: str, lookback_days: int, sleep_sec: float) -> Dict[str, str]:
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": date_days_ago_yyyymmdd(lookback_days),
        "end_de": today_yyyymmdd(),
        "last_reprt_at": "Y",
        "pblntf_ty": "A",
        "sort": "date",
        "sort_mth": "desc",
        "page_no": 1,
        "page_count": 100,
    }

    data = dart_get_json(DART_LIST_URL, params, sleep_sec=sleep_sec)

    if data.get("status") not in ("000", None):
        return {
            "rcept_no": "",
            "report_nm": "",
            "rcept_dt": "",
            "report_status": f"DART_LIST_{data.get('status')}_{data.get('message')}",
        }

    items = data.get("list") or []
    candidates: List[Dict[str, Any]] = []

    for item in items:
        report_nm = clean_text(item.get("report_nm"))
        if not any(k in report_nm for k in REPORT_PRIORITY.keys()):
            continue

        priority = 0
        for key, score in REPORT_PRIORITY.items():
            if key in report_nm:
                priority = max(priority, score)

        candidates.append({
            "rcept_no": clean_text(item.get("rcept_no")),
            "report_nm": report_nm,
            "rcept_dt": clean_text(item.get("rcept_dt")),
            "priority": priority,
        })

    if not candidates:
        return {
            "rcept_no": "",
            "report_nm": "",
            "rcept_dt": "",
            "report_status": "NO_PERIODIC_REPORT",
        }

    candidates.sort(key=lambda x: (x["priority"], x["rcept_dt"]), reverse=True)
    best = candidates[0]

    return {
        "rcept_no": best["rcept_no"],
        "report_nm": best["report_nm"],
        "rcept_dt": best["rcept_dt"],
        "report_status": "OK",
    }


def download_report_text(api_key: str, rcept_no: str, sleep_sec: float) -> Tuple[str, str]:
    if not rcept_no:
        return "", "NO_RCEPT_NO"

    raw, status = download_bytes(
        DART_DOCUMENT_URL,
        {"crtfc_key": api_key, "rcept_no": rcept_no},
        retries=3,
        sleep_sec=sleep_sec,
    )

    if raw is None:
        return "", f"DOCUMENT_{status}"

    text = normalize_report_text(raw)
    if not text:
        return "", "DOCUMENT_TEXT_EMPTY"

    return text, "OK"


@dataclass
class FxSignals:
    export_mentions: int = 0
    fx_asset_mentions: int = 0
    fx_liab_mentions: int = 0
    hedge_mentions: int = 0
    import_mentions: int = 0
    order_mentions: int = 0
    sensitivity_mentions: int = 0
    overseas_revenue_pct: Optional[float] = None
    hedge_pct_proxy: Optional[float] = None
    text_length: int = 0
    confidence: str = "D"
    confidence_reason: str = ""


def extract_fx_signals(text: str, sector_proxy: Dict[str, Any]) -> FxSignals:
    if not text:
        return FxSignals(confidence="D", confidence_reason="보고서 원문 미확보")

    export_sec = extract_sections(text, EXPORT_WORDS, radius=3500, limit=5)
    hedge_sec = extract_sections(text, HEDGE_WORDS, radius=3000, limit=4)
    fx_sec = extract_sections(text, FX_ASSET_WORDS + FX_LIAB_WORDS + SENSITIVITY_WORDS, radius=3500, limit=5)

    export_mentions = keyword_count(text, EXPORT_WORDS)
    fx_asset_mentions = keyword_count(text, FX_ASSET_WORDS)
    fx_liab_mentions = keyword_count(text, FX_LIAB_WORDS)
    hedge_mentions = keyword_count(text, HEDGE_WORDS)
    import_mentions = keyword_count(text, IMPORT_COST_WORDS)
    order_mentions = keyword_count(text, ORDER_WORDS)
    sensitivity_mentions = keyword_count(text, SENSITIVITY_WORDS)

    overseas_pct = extract_percent_near(export_sec, ["수출", "해외", "국외", "외화", "미국", "북미", "유럽", "중국"])
    hedge_pct = extract_percent_near(hedge_sec, ["통화선도", "선물환", "위험회피", "헤지", "파생상품"])

    numeric_sections = 0
    if overseas_pct is not None:
        numeric_sections += 1
    if hedge_pct is not None:
        numeric_sections += 1
    if re.search(r"(외화자산|외화 자산|외화부채|외화 부채).{0,120}[0-9]{1,3}(,[0-9]{3})+", fx_sec):
        numeric_sections += 1
    if re.search(r"(환율|민감도).{0,120}[0-9]{1,3}(,[0-9]{3})+", fx_sec):
        numeric_sections += 1

    if numeric_sections >= 3:
        confidence = "A"
        reason = "주석에서 환율노출 관련 수치 다수 확인"
    elif numeric_sections >= 1 and (fx_asset_mentions + fx_liab_mentions + hedge_mentions) > 0:
        confidence = "B"
        reason = "주석 수치 일부와 환율노출 키워드 확인"
    elif export_mentions + fx_asset_mentions + fx_liab_mentions + hedge_mentions + order_mentions > 3:
        confidence = "C"
        reason = "보고서 텍스트 단서와 산업 프록시 중심"
    else:
        confidence = "D"
        reason = "환율노출 공시 단서 부족"

    return FxSignals(
        export_mentions=export_mentions,
        fx_asset_mentions=fx_asset_mentions,
        fx_liab_mentions=fx_liab_mentions,
        hedge_mentions=hedge_mentions,
        import_mentions=import_mentions,
        order_mentions=order_mentions,
        sensitivity_mentions=sensitivity_mentions,
        overseas_revenue_pct=overseas_pct,
        hedge_pct_proxy=hedge_pct,
        text_length=len(text),
        confidence=confidence,
        confidence_reason=reason,
    )


def pct_to_score(pct: Optional[float], max_score: float, proxy_pct: float) -> float:
    use_pct = proxy_pct if pct is None else pct
    use_pct = max(0.0, min(100.0, float(use_pct)))
    return max_score * use_pct / 100.0


def bounded(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def detect_position_pct(row: pd.Series, price: Optional[float], low: Optional[float], high: Optional[float]) -> Optional[float]:
    for col in row.index:
        c = str(col).lower()
        if ("position" in c or "현재 위치" in c or "현재위치" in c) and ("pct" in c or "%" in c):
            v = to_float(row[col])
            if v is not None:
                return bounded(v, 0, 100)

    if price is not None and low is not None and high is not None and high > low:
        return bounded((price - low) / (high - low) * 100.0, 0, 100)

    return None


def position_label(position_pct: Optional[float]) -> str:
    if position_pct is None:
        return "위치 산출제한"
    if position_pct <= 15:
        return "저점권"
    if position_pct <= 35:
        return "저점권 반등 초입"
    if position_pct <= 65:
        return "중간권"
    if position_pct <= 80:
        return "상단권"
    return "고점권"


def position_score(position_pct: Optional[float]) -> float:
    if position_pct is None:
        return 5.0
    if 15 <= position_pct <= 45:
        return 10.0
    if position_pct < 15:
        return 8.0
    if position_pct <= 65:
        return 7.0
    if position_pct <= 80:
        return 4.0
    return 2.0


def supply_burden_flag(row: pd.Series) -> bool:
    joined = " ".join(clean_text(v) for v in row.values)
    words = [
        "오버행", "대량매도", "블록딜", "유상증자", "전환사채", "CB",
        "BW", "EB", "보호예수", "자사주 처분", "저유동성", "매매곤란",
    ]
    return any(w in joined for w in words)


def operating_loss_flag(row: pd.Series) -> bool:
    joined = " ".join(clean_text(v) for v in row.values)
    if "영업손실" in joined:
        return True
    for col in row.index:
        c = str(col)
        if "영업이익" in c or "operating" in c.lower():
            v = to_float(row[col])
            if v is not None and v < 0:
                return True
    return False


def underline_icon(icon: str) -> str:
    return f"{icon}\u0332"


def compute_scores(
    name: str,
    signals: FxSignals,
    sector_proxy: Dict[str, Any],
    position_pct: Optional[float],
    op_loss: bool,
    supply_risk: bool,
) -> Dict[str, Any]:
    export_proxy = float(sector_proxy.get("export_proxy", 25))
    won_cost_proxy = float(sector_proxy.get("won_cost_proxy", 40))
    import_burden_proxy = float(sector_proxy.get("import_burden_proxy", 45))

    dollar_sales_score = pct_to_score(signals.overseas_revenue_pct, 25, export_proxy)
    won_cost_score = 15 * bounded(won_cost_proxy, 0, 100) / 100.0

    if signals.hedge_pct_proxy is not None:
        hedge_score = 15 * (1 - bounded(signals.hedge_pct_proxy, 0, 100) / 100.0)
    elif signals.hedge_mentions >= 5:
        hedge_score = 8.0
    elif signals.hedge_mentions >= 1:
        hedge_score = 10.0
    else:
        hedge_score = 11.0

    if signals.fx_liab_mentions > signals.fx_asset_mentions * 2 and signals.fx_liab_mentions >= 3:
        foreign_debt_score = 4.0
    elif signals.fx_liab_mentions >= 1:
        foreign_debt_score = 7.0
    else:
        foreign_debt_score = 8.0

    import_keyword_penalty = min(25.0, signals.import_mentions * 1.0)
    import_burden = bounded(import_burden_proxy + import_keyword_penalty, 0, 100)
    import_cost_score = 10 * (1 - import_burden / 100.0)

    backlog_bonus = min(5.0, signals.order_mentions * 0.4)
    sensitivity_bonus = min(5.0, signals.sensitivity_mentions * 0.5)

    earnings_score = 3.0 if op_loss else 8.0
    technical_score = position_score(position_pct)
    risk_score = 2.0 if supply_risk else 5.0

    raw_score = (
        dollar_sales_score
        + won_cost_score
        + hedge_score
        + foreign_debt_score
        + import_cost_score
        + earnings_score
        + technical_score
        + risk_score
        + backlog_bonus
        + sensitivity_bonus
    )

    final_score = bounded(raw_score, 0, 100)

    return {
        "dollar_sales_score": round(dollar_sales_score, 2),
        "won_cost_score": round(won_cost_score, 2),
        "hedge_score": round(hedge_score, 2),
        "foreign_debt_score": round(foreign_debt_score, 2),
        "import_cost_score": round(import_cost_score, 2),
        "earnings_score": round(earnings_score, 2),
        "technical_score": round(technical_score, 2),
        "risk_score": round(risk_score, 2),
        "backlog_bonus": round(backlog_bonus, 2),
        "sensitivity_bonus": round(sensitivity_bonus, 2),
        "fx_net_benefit_score": round(final_score, 2),
    }


def build_buy_sell_ranges(
    price: Optional[float],
    low: Optional[float],
    high: Optional[float],
    avg_pct: Optional[float],
) -> Dict[str, str]:
    if price is None:
        return {
            "buy_range": "",
            "sell_range": "",
            "stop_loss": "",
        }

    avg_decimal = 0.035
    if avg_pct is not None and avg_pct > 0:
        avg_decimal = avg_pct / 100.0
        if avg_decimal > 0.30:
            avg_decimal = avg_decimal / 100.0

    avg_decimal = bounded(avg_decimal, 0.015, 0.12)

    buy_high = price * (1 - avg_decimal * 0.35)
    buy_low = price * (1 - avg_decimal * 1.45)

    sell_low = price * (1 + avg_decimal * 0.90)
    sell_high = price * (1 + avg_decimal * 1.85)

    if low is not None:
        buy_low = max(buy_low, low * 0.98)
    if high is not None:
        sell_high = min(sell_high, high * 1.03)

    stop_loss = buy_low * 0.965

    return {
        "buy_range": f"**{format_won(buy_low)}~{format_won(buy_high)}**",
        "sell_range": f"**{format_won(sell_low)}~{format_won(sell_high)}**",
        "stop_loss": format_won(stop_loss),
    }


def make_fx_structure(signals: FxSignals, sector_proxy: Dict[str, Any]) -> str:
    parts: List[str] = []

    if signals.overseas_revenue_pct is not None:
        parts.append(f"해외/수출비중 약 {signals.overseas_revenue_pct:.1f}% 단서")
    else:
        parts.append(sector_proxy.get("comment", "산업 프록시 기반"))

    if signals.hedge_pct_proxy is not None:
        parts.append(f"헤지비율 약 {signals.hedge_pct_proxy:.1f}% 단서")
    elif signals.hedge_mentions >= 3:
        parts.append("환헤지/파생상품 언급 많음")
    elif signals.hedge_mentions >= 1:
        parts.append("환헤지 언급 일부")
    else:
        parts.append("헤지 공시 단서 약함")

    if signals.fx_liab_mentions >= 3:
        parts.append("외화부채 점검 필요")
    if signals.import_mentions >= 8:
        parts.append("수입원가 부담 큼")
    elif signals.import_mentions >= 3:
        parts.append("수입원가 부담 일부")

    return " · ".join(parts[:4])


def make_reason(
    name: str,
    score: float,
    confidence: str,
    position: str,
    signals: FxSignals,
    sector_proxy: Dict[str, Any],
    op_loss: bool,
    supply_risk: bool,
) -> str:
    reasons = []

    if score >= 75:
        reasons.append("원화 약세 순수혜 점수 상위")
    elif score >= 65:
        reasons.append("환율수혜 가능성 양호")
    else:
        reasons.append("환율수혜는 있으나 감점요인 존재")

    reasons.append(f"{sector_proxy.get('sector', '기타')} 구조")
    reasons.append(position)

    if confidence in ("A", "B"):
        reasons.append(f"공시신뢰도 {confidence}")
    else:
        reasons.append(f"공시신뢰도 {confidence}: 정밀확인 필요")

    if op_loss:
        reasons.append("최근 영업손실 감점")
    if supply_risk:
        reasons.append("수급부담/오버행 점검")

    if signals.import_mentions >= 8:
        reasons.append("수입원가 부담 주의")
    if signals.fx_liab_mentions >= 3:
        reasons.append("외화부채 부담 주의")

    return " · ".join(reasons)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--universe", default="latest/kospi_universe_summary_latest.csv")
    parser.add_argument("--lookback-days", type=int, default=900)
    parser.add_argument("--sleep", type=float, default=0.12)
    parser.add_argument("--refresh-corp-code", action="store_true")
    parser.add_argument("--max-companies", type=int, default=0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    run_log: List[str] = []
    started = now_kst()
    run_log.append("script=dart_fx_exposure_kospi.py v1.0_dart_fx_exposure_precision")
    run_log.append(f"run_at_kst={started}")
    run_log.append(f"output_dir={output_dir}")
    run_log.append(f"universe={args.universe}")
    run_log.append(f"lookback_days={args.lookback_days}")

    api_key = os.environ.get("DART_API_KEY") or os.environ.get("OPENDART_API_KEY") or ""
    if not api_key:
        run_log.append("status=FAIL")
        run_log.append("error=DART_API_KEY_MISSING")
        (output_dir / "kospi_fx_exposure_run_log_latest.txt").write_text("\n".join(run_log), encoding="utf-8")
        raise SystemExit("DART_API_KEY 환경변수가 필요합니다.")

    universe_path = Path(args.universe)
    if not universe_path.exists():
        run_log.append("status=FAIL")
        run_log.append(f"error=UNIVERSE_FILE_NOT_FOUND {universe_path}")
        (output_dir / "kospi_fx_exposure_run_log_latest.txt").write_text("\n".join(run_log), encoding="utf-8")
        raise SystemExit(f"파일 없음: {universe_path}")

    universe = read_csv_any(universe_path)

    ticker_col = find_col(universe, ["종목코드", "ticker", "stock_code", "code", "symbol"])
    name_col = find_col(universe, ["종목명", "name", "stock_name", "corp_name", "company"])
    price_col = find_col(universe, ["현재가 기준", "현재가", "close", "종가", "current_price", "last_price"])
    low_col = find_col(universe, ["최근 3개월 저점", "3개월 저점", "low_3m", "three_month_low", "period_low"])
    high_col = find_col(universe, ["최근 3개월 고점", "3개월 고점", "high_3m", "three_month_high", "period_high"])
    avg_pct_col = find_col(universe, ["하루 평균 변동폭(%)", "avg_daily_range_pct", "daily_avg_pct", "avg_range_pct"])
    avg_abs_col = find_col(universe, ["하루 평균 변동폭(원)", "avg_daily_range_abs", "daily_avg_abs", "avg_range_won"])

    if ticker_col is None or name_col is None:
        run_log.append("status=FAIL")
        run_log.append(f"error=REQUIRED_COLUMNS_NOT_FOUND ticker_col={ticker_col} name_col={name_col}")
        (output_dir / "kospi_fx_exposure_run_log_latest.txt").write_text("\n".join(run_log), encoding="utf-8")
        raise SystemExit("종목코드/종목명 컬럼을 찾지 못했습니다.")

    universe["_ticker"] = universe[ticker_col].apply(clean_ticker)
    universe["_name"] = universe[name_col].apply(clean_text)
    universe = universe[universe["_ticker"].str.len() == 6].copy()

    if args.max_companies and args.max_companies > 0:
        universe = universe.head(args.max_companies).copy()

    corp_df = load_corp_code_map(api_key, output_dir, refresh=args.refresh_corp_code)
    corp_map = dict(zip(corp_df["stock_code"].apply(clean_ticker), corp_df["corp_code"].astype(str)))

    cache_path = output_dir / "dart_fx_exposure_cache.csv"
    if cache_path.exists():
        try:
            cache_df = read_csv_any(cache_path)
        except Exception:
            cache_df = pd.DataFrame()
    else:
        cache_df = pd.DataFrame()

    cache_by_ticker: Dict[str, Dict[str, Any]] = {}
    if not cache_df.empty and "ticker" in cache_df.columns:
        for _, r in cache_df.iterrows():
            cache_by_ticker[clean_ticker(r.get("ticker"))] = r.to_dict()

    raw_rows: List[Dict[str, Any]] = []
    precision_rows: List[Dict[str, Any]] = []

    status_counts: Dict[str, int] = {}

    for _, row in universe.iterrows():
        ticker = clean_ticker(row["_ticker"])
        name = clean_text(row["_name"])
        corp_code = corp_map.get(ticker, "")

        report_status = "OK"
        document_status = "OK"
        report = {"rcept_no": "", "report_nm": "", "rcept_dt": "", "report_status": ""}

        if not corp_code:
            report_status = "NO_CORP_CODE"
            signals = FxSignals(confidence="D", confidence_reason="DART 고유번호 매칭 실패")
        else:
            report = choose_latest_report(api_key, corp_code, args.lookback_days, args.sleep)
            report_status = report.get("report_status", "")

            cached = cache_by_ticker.get(ticker, {})
            cached_rcept_no = clean_text(cached.get("rcept_no"))

            if cached and cached_rcept_no and cached_rcept_no == report.get("rcept_no"):
                document_status = "CACHE_REUSED"
                signals = FxSignals(
                    export_mentions=int(to_float(cached.get("export_mentions")) or 0),
                    fx_asset_mentions=int(to_float(cached.get("fx_asset_mentions")) or 0),
                    fx_liab_mentions=int(to_float(cached.get("fx_liab_mentions")) or 0),
                    hedge_mentions=int(to_float(cached.get("hedge_mentions")) or 0),
                    import_mentions=int(to_float(cached.get("import_mentions")) or 0),
                    order_mentions=int(to_float(cached.get("order_mentions")) or 0),
                    sensitivity_mentions=int(to_float(cached.get("sensitivity_mentions")) or 0),
                    overseas_revenue_pct=to_float(cached.get("overseas_revenue_pct")),
                    hedge_pct_proxy=to_float(cached.get("hedge_pct_proxy")),
                    text_length=int(to_float(cached.get("text_length")) or 0),
                    confidence=clean_text(cached.get("공시신뢰도")) or "D",
                    confidence_reason=clean_text(cached.get("confidence_reason")),
                )
            else:
                if report_status == "OK":
                    text, document_status = download_report_text(api_key, report.get("rcept_no", ""), args.sleep)
                else:
                    text, document_status = "", "NO_REPORT"
                sector_proxy_temp = classify_sector_proxy(name)
                signals = extract_fx_signals(text, sector_proxy_temp)

        sector_proxy = classify_sector_proxy(name)

        price = to_float(row[price_col]) if price_col else None
        low = to_float(row[low_col]) if low_col else None
        high = to_float(row[high_col]) if high_col else None
        avg_pct = to_float(row[avg_pct_col]) if avg_pct_col else None
        avg_abs = to_float(row[avg_abs_col]) if avg_abs_col else None

        position_pct = detect_position_pct(row, price, low, high)
        pos_label = position_label(position_pct)

        op_loss = operating_loss_flag(row)
        supply_risk = supply_burden_flag(row)

        score_parts = compute_scores(name, signals, sector_proxy, position_pct, op_loss, supply_risk)
        score = score_parts["fx_net_benefit_score"]

        status_counts[report_status] = status_counts.get(report_status, 0) + 1

        ranges = build_buy_sell_ranges(price, low, high, avg_pct)

        recent_range = ""
        range_width = ""
        if low is not None and high is not None:
            recent_range = f"{format_won(low)}~{format_won(high)}"
            if low > 0:
                range_width = f"{format_won(high - low)} / {((high - low) / low * 100):.1f}%"

        avg_move = ""
        if avg_abs is not None and avg_pct is not None:
            avg_move = f"약 ±{format_won(avg_abs)} 내외(±{avg_pct:.2f}%)"
        elif avg_pct is not None and price is not None:
            avg_move = f"약 ±{format_won(price * avg_pct / 100)} 내외(±{avg_pct:.2f}%)"
        elif avg_abs is not None:
            avg_move = f"약 ±{format_won(avg_abs)} 내외"
        else:
            avg_move = "산출제한"

        fx_structure = make_fx_structure(signals, sector_proxy)
        reason = make_reason(name, score, signals.confidence, pos_label, signals, sector_proxy, op_loss, supply_risk)

        raw_rows.append({
            "ticker": ticker,
            "종목": name,
            "corp_code": corp_code,
            "rcept_no": report.get("rcept_no", ""),
            "report_nm": report.get("report_nm", ""),
            "rcept_dt": report.get("rcept_dt", ""),
            "report_status": report_status,
            "document_status": document_status,
            "sector_proxy": sector_proxy.get("sector"),
            "export_mentions": signals.export_mentions,
            "fx_asset_mentions": signals.fx_asset_mentions,
            "fx_liab_mentions": signals.fx_liab_mentions,
            "hedge_mentions": signals.hedge_mentions,
            "import_mentions": signals.import_mentions,
            "order_mentions": signals.order_mentions,
            "sensitivity_mentions": signals.sensitivity_mentions,
            "overseas_revenue_pct": signals.overseas_revenue_pct,
            "hedge_pct_proxy": signals.hedge_pct_proxy,
            "text_length": signals.text_length,
            "공시신뢰도": signals.confidence,
            "confidence_reason": signals.confidence_reason,
            **score_parts,
        })

        precision_rows.append({
            "추천표시": "",
            "종목": name,
            "종목코드": ticker,
            "현재가 기준": format_won(price),
            "분할매수 적정가": ranges["buy_range"],
            "1차 매도/익절가": ranges["sell_range"],
            "하루 평균 변동폭": avg_move,
            "평균 파동 기간": "약 15~30거래일",
            "손절 기준": ranges["stop_loss"],
            "최근 3개월 저점~고점": recent_range,
            "구간 변동폭": range_width,
            "현재 위치": pos_label if position_pct is None else f"{pos_label}({position_pct:.1f}%)",
            "환율수혜구조": fx_structure,
            "환율순수혜점수": score,
            "공시신뢰도": signals.confidence,
            "공시근거": signals.confidence_reason,
            "판단/추천·주의사유": reason,
            "_op_loss": op_loss,
            "_supply_risk": supply_risk,
            "_price_position_pct": position_pct,
        })

    raw_df = pd.DataFrame(raw_rows)
    precision_df = pd.DataFrame(precision_rows)

    precision_df = precision_df.sort_values(
        by=["환율순수혜점수", "공시신뢰도"],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)

    candidates = precision_df.head(30).copy()

    recommendation_pool = candidates.copy()
    recommendation_pool["_recommend_penalty"] = 0
    recommendation_pool.loc[recommendation_pool["_price_position_pct"].fillna(50) > 80, "_recommend_penalty"] += 15
    recommendation_pool.loc[recommendation_pool["_supply_risk"] == True, "_recommend_penalty"] += 10
    recommendation_pool.loc[recommendation_pool["_op_loss"] == True, "_recommend_penalty"] += 15
    recommendation_pool.loc[recommendation_pool["공시신뢰도"] == "D", "_recommend_penalty"] += 10
    recommendation_pool["_recommend_score"] = recommendation_pool["환율순수혜점수"] - recommendation_pool["_recommend_penalty"]
    recommendation_pool = recommendation_pool.sort_values("_recommend_score", ascending=False).reset_index(drop=True)
    recommend_names = set(recommendation_pool.head(7)["종목"].tolist())

    def assign_icon(r: pd.Series) -> str:
        base = "✅" if r["종목"] in recommend_names else ("⚠️" if r["_price_position_pct"] is not None and r["_price_position_pct"] > 80 else "🟡")
        if r["_supply_risk"]:
            base = underline_icon(base)
        if r["_op_loss"]:
            base = "-" + base
        return base

    candidates["추천표시"] = candidates.apply(assign_icon, axis=1)
    recommend_7 = candidates[candidates["종목"].isin(recommend_names)].copy()
    recommend_7 = recommend_7.sort_values("환율순수혜점수", ascending=False).head(7)

    drop_cols = ["_op_loss", "_supply_risk", "_price_position_pct"]
    candidates_out = candidates.drop(columns=[c for c in drop_cols if c in candidates.columns])
    recommend_out = recommend_7.drop(columns=[c for c in drop_cols if c in recommend_7.columns])
    precision_out = precision_df.drop(columns=[c for c in drop_cols if c in precision_df.columns])

    write_csv(raw_df, output_dir / "kospi_fx_exposure_raw_latest.csv")
    write_csv(raw_df, output_dir / "dart_fx_exposure_cache.csv")
    write_csv(precision_out, output_dir / "kospi_fx_exposure_precision_latest.csv")
    write_csv(candidates_out, output_dir / "kospi_fx_weakness_candidates_30_latest.csv")
    write_csv(recommend_out, output_dir / "kospi_fx_weakness_recommend_7_latest.csv")

    run_log.append("status=OK")
    run_log.append(f"universe_rows={len(universe)}")
    run_log.append(f"raw_rows={len(raw_df)}")
    run_log.append(f"precision_rows={len(precision_out)}")
    run_log.append(f"candidate_rows={len(candidates_out)}")
    run_log.append(f"recommend_rows={len(recommend_out)}")
    run_log.append(f"status_counts={json.dumps(status_counts, ensure_ascii=False)}")

    confidence_counts = raw_df["공시신뢰도"].value_counts(dropna=False).to_dict() if not raw_df.empty else {}
    run_log.append(f"confidence_counts={json.dumps(confidence_counts, ensure_ascii=False)}")
    run_log.append("outputs=kospi_fx_exposure_raw_latest.csv,kospi_fx_exposure_precision_latest.csv,kospi_fx_weakness_candidates_30_latest.csv,kospi_fx_weakness_recommend_7_latest.csv")

    log_text = "\n".join(run_log)
    (output_dir / "kospi_fx_exposure_run_log_latest.txt").write_text(log_text, encoding="utf-8")
    (output_dir / "kospi_fx_weakness_run_log_latest.txt").write_text(log_text, encoding="utf-8")

    print(log_text)


if __name__ == "__main__":
    main()
