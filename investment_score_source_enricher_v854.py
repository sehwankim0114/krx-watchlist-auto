#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
investment_score_source_enricher_v854.py

V8.5.4 investment-score source cache only.

Purpose
- Persist only official/raw inputs that were validated by the V8.5.4 read-only probes.
- Do NOT create investment_score_100.
- Do NOT invent raw-value -> point thresholds.
- Do NOT calculate net cash until debt-scope policy is explicitly defined.
- Do NOT calculate EV/EBITDA while depreciation/amortization extraction is not validated.

Outputs
- latest/investment_score_source_cache_latest.csv
- latest/investment_score_source_run_log_latest.txt
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import socket
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import pandas as pd


SCRIPT_VERSION = "investment_score_source_enricher_v854.py v1.0.0-source-cache-only"
SOURCE_CONTRACT_VERSION = "2026-09-10-v8.5.4-investment-score-source-contract"
SCORE_POLICY_VERSION = "2026-07-01-v6.0-score-policy"
KST = ZoneInfo("Asia/Seoul")

MULTI_ACCOUNT_URL = "https://opendart.fss.or.kr/api/fnlttMultiAcnt.json"
FULL_ACCOUNT_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

FINANCIAL_CACHE = "financial_valuation_cache_latest.csv"
SOURCE_CACHE = "investment_score_source_cache_latest.csv"
RUN_LOG = "investment_score_source_run_log_latest.txt"

VALID_IDENTITY = {"MATCH", "MATCH_NORMALIZED", "NAME_NOT_AVAILABLE"}
VALID_FINANCIAL_STATUS = {"READY", "PARTIAL"}

ACCOUNT_SPECS = {
    "revenue": {
        "statement": "IS",
        "exact": (
            "매출액",
            "수익(매출액)",
            "영업수익",
            "영업수익(매출액)",
            "매출",
        ),
        "include": ("매출", "수익"),
        "exclude": (
            "원가",
            "비용",
            "금융수익",
            "기타수익",
            "이자수익",
            "법인세",
        ),
    },
    "operating_profit": {
        "statement": "IS",
        "exact": (
            "영업이익",
            "영업이익(손실)",
            "영업손익",
            "영업손실",
        ),
        "include": ("영업",),
        "exclude": ("중단", "수익", "비용"),
    },
    "net_income": {
        "statement": "IS",
        "exact": (
            "당기순이익",
            "당기순이익(손실)",
            "분기순이익",
            "분기순이익(손실)",
            "반기순이익",
            "반기순이익(손실)",
            "연결당기순이익",
            "연결당기순이익(손실)",
        ),
        "include": ("순이익",),
        "exclude": (
            "지배기업",
            "비지배지분",
            "주당",
            "계속영업",
            "중단영업",
        ),
    },
}

CASH_ACCOUNT_IDS = {
    "ifrs-full_CashAndCashEquivalents",
}
CASH_EXACT_NAMES = {
    "현금및현금성자산",
}

CORE_DEBT_ACCOUNT_IDS = {
    "ifrs-full_ShorttermBorrowings",
    "ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
    "ifrs-full_CurrentPortionOfLongtermBorrowings",
    "ifrs-full_CurrentPortionOfNoncurrentBondsIssued",
    "dart_CurrentPortionOfBonds",
    "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued",
    "ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived",
    "ifrs-full_LongtermBorrowings",
}
CORE_DEBT_EXACT_NAMES = {
    "단기차입금",
    "장기차입금",
    "차입금",
    "사채",
    "유동성장기부채",
}

LEASE_ACCOUNT_IDS = {
    "ifrs-full_CurrentLeaseLiabilities",
    "ifrs-full_NoncurrentLeaseLiabilities",
}
LEASE_TERMS = ("리스부채", "리스채무")

OTHER_FINANCIAL_LIABILITY_ACCOUNT_IDS = {
    "ifrs-full_OtherCurrentFinancialLiabilities",
    "ifrs-full_OtherNoncurrentFinancialLiabilities",
}
OTHER_FINANCIAL_LIABILITY_TERMS = ("기타금융부채",)

DA_TERMS = (
    "감가상각비",
    "무형자산상각비",
    "감가상각",
    "depreciation",
    "amortization",
)

OUTPUT_COLUMNS = [
    "ticker",
    "name",
    "market",
    "corp_code",
    "corp_name",
    "source_contract_version",
    "score_policy_version",
    "source_cache_status",
    "source_cache_reason",
    "financial_basis_at_source",
    "preferred_fs_div",
    "annual_source_year",
    "annual_fs_div",
    "annual_revenue_y0",
    "annual_revenue_y1",
    "annual_revenue_y2",
    "annual_operating_profit_y0",
    "annual_operating_profit_y1",
    "annual_operating_profit_y2",
    "annual_net_income_y0",
    "annual_net_income_y1",
    "annual_net_income_y2",
    "three_year_source_status",
    "quarter_source_status",
    "quarter_current_year",
    "q2_revenue_current",
    "q2_revenue_previous",
    "q2_operating_profit_current",
    "q2_operating_profit_previous",
    "q2_net_income_current",
    "q2_net_income_previous",
    "q2_revenue_yoy_pct",
    "q2_operating_profit_yoy_pct",
    "q2_net_income_yoy_pct",
    "quarter_acceleration_classification",
    "quarter_acceleration_policy_status",
    "deep_source_year",
    "deep_fs_div",
    "deep_source_status",
    "cash_and_cash_equivalents",
    "core_debt_candidates_json",
    "lease_liability_candidates_json",
    "other_financial_liability_candidates_json",
    "depreciation_amortization_candidates_json",
    "net_cash_value",
    "net_cash_policy_status",
    "ev_ebitda_value",
    "ev_ebitda_source_status",
    "investment_score_100",
    "investment_score_status",
    "score_threshold_policy_status",
    "fetched_at_kst",
]


def now_kst_text() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def norm_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def clean_ticker(value: Any) -> str:
    text = re.sub(r"[^0-9]", "", norm_text(value))
    return text.zfill(6) if text else ""


def clean_corp_code(value: Any) -> str:
    text = re.sub(r"[^0-9]", "", norm_text(value))
    return text.zfill(8) if text else ""


def compact(value: Any) -> str:
    return re.sub(
        r"[\s·ㆍ()\[\]{}_\-/,]+",
        "",
        norm_text(value),
    ).upper()


def parse_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    text = norm_text(value).replace(",", "")
    if text in {"", "-"}:
        return None
    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = text[1:-1]
    text = re.sub(r"[^0-9eE+\-.]", "", text)
    if text in {"", "-", "+", ".", "-.", "+."}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return -abs(number) if negative_parentheses else number


def safe_yoy_pct(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100.0, 2)


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def read_csv(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, dtype=str, encoding=encoding).fillna("")
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"CSV_READ_FAILED:{path}")


def write_csv_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        df.to_csv(temp_path, index=False, encoding="utf-8-sig")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def chunks(values: Sequence[str], size: int) -> Iterable[List[str]]:
    for index in range(0, len(values), size):
        yield list(values[index:index + size])


def choose_account(rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]):
    statement = spec["statement"]
    candidates = [
        row for row in rows
        if norm_text(row.get("sj_div")) == statement
    ]
    if not candidates:
        return None

    exact_order = {
        compact(name): index
        for index, name in enumerate(spec["exact"])
    }
    exact_hits = []
    for row in candidates:
        name = compact(row.get("account_nm"))
        if name in exact_order:
            exact_hits.append((exact_order[name], row))
    if exact_hits:
        exact_hits.sort(key=lambda item: item[0])
        return exact_hits[0][1]

    include = tuple(compact(term) for term in spec["include"])
    exclude = tuple(compact(term) for term in spec["exclude"])
    fuzzy = []
    for row in candidates:
        name = compact(row.get("account_nm"))
        if include and not any(term in name for term in include):
            continue
        if any(term in name for term in exclude):
            continue
        fuzzy.append(row)
    return fuzzy[0] if len(fuzzy) == 1 else None


class OpenDartClient:
    def __init__(self, api_key: str, timeout: int = 30):
        self.api_key = api_key
        self.timeout = max(10, int(timeout))
        self.attempted = 0
        self.successful = 0
        self.transport_failures: List[str] = []
        self.dart_status_failures: List[str] = []

    def get_json(self, url: str, params: Mapping[str, Any], label: str) -> Dict[str, Any]:
        timeouts = (
            self.timeout,
            max(self.timeout + 15, 45),
            max(self.timeout + 30, 60),
        )
        sleeps = (1.5, 3.0)
        query_params = dict(params)
        query_params["crtfc_key"] = self.api_key
        request_url = f"{url}?{urllib.parse.urlencode(query_params)}"
        last_error = ""

        for attempt, timeout in enumerate(timeouts, start=1):
            self.attempted += 1
            request = urllib.request.Request(
                request_url,
                headers={
                    "User-Agent": "krx-watchlist-investment-score-source-v854",
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                    "Connection": "close",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read(12_000_000)
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("OPENDART_RESPONSE_NOT_OBJECT")
                self.successful += 1
                status = norm_text(payload.get("status"))
                if status and status != "000":
                    self.dart_status_failures.append(
                        f"{label}|{status}|{norm_text(payload.get('message'))}"
                    )
                return payload
            except (
                TimeoutError,
                socket.timeout,
                urllib.error.URLError,
                urllib.error.HTTPError,
                json.JSONDecodeError,
                ValueError,
            ) as exc:
                last_error = f"{type(exc).__name__}:{exc}"
                if attempt < len(timeouts):
                    time.sleep(sleeps[min(attempt - 1, len(sleeps) - 1)])

        self.transport_failures.append(f"{label}|{last_error}")
        return {
            "status": "TRANSPORT_ERROR",
            "message": last_error,
            "list": [],
        }


def load_targets(financial_df: pd.DataFrame) -> List[Dict[str, str]]:
    targets: List[Dict[str, str]] = []
    for _, row in financial_df.iterrows():
        ticker = clean_ticker(row.get("ticker"))
        corp_code = clean_corp_code(row.get("corp_code"))
        if not ticker or not corp_code:
            continue
        if norm_text(row.get("financial_source_status")) != "OK":
            continue
        if norm_text(row.get("financial_data_status")) not in VALID_FINANCIAL_STATUS:
            continue
        if norm_text(row.get("corp_identity_status")) not in VALID_IDENTITY:
            continue
        targets.append({
            "ticker": ticker,
            "name": norm_text(row.get("name")),
            "market": norm_text(row.get("market")),
            "corp_code": corp_code,
            "corp_name": norm_text(row.get("corp_name")),
            "financial_basis": norm_text(row.get("financial_basis")),
            "financial_report_year": norm_text(row.get("financial_report_year")),
            "financial_report_code": norm_text(row.get("financial_report_code")),
            "preferred_fs_div": norm_text(row.get("financial_fs_div")) or "CFS",
        })
    targets.sort(key=lambda item: item["ticker"])
    return targets


def dominant_period(targets: Sequence[Mapping[str, str]]) -> Tuple[int, str]:
    counts = Counter(
        (item["financial_report_year"], item["financial_report_code"])
        for item in targets
        if item["financial_report_year"].isdigit()
        and item["financial_report_code"] in {"11011", "11012", "11013", "11014"}
    )
    if not counts:
        raise RuntimeError("NO_VALID_FINANCIAL_PERIOD")
    (year, code), _ = counts.most_common(1)[0]
    return int(year), code


def query_multi_period(
    client: OpenDartClient,
    targets: Sequence[Mapping[str, str]],
    year: int,
    report_code: str,
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    result: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    corp_codes = [item["corp_code"] for item in targets]
    for batch_index, batch in enumerate(chunks(corp_codes, 100), start=1):
        payload = client.get_json(
            MULTI_ACCOUNT_URL,
            {
                "corp_code": ",".join(batch),
                "bsns_year": str(year),
                "reprt_code": report_code,
            },
            f"multi:{year}:{report_code}:batch{batch_index}",
        )
        items = payload.get("list") if isinstance(payload.get("list"), list) else []
        for item in items:
            corp_code = clean_corp_code(item.get("corp_code"))
            fs_div = norm_text(item.get("fs_div"))
            if corp_code and fs_div:
                result[corp_code][fs_div].append(dict(item))
        time.sleep(0.08)
    return result


def select_fs_rows(
    by_fs: Mapping[str, Sequence[Mapping[str, Any]]],
    preferred: str,
) -> Tuple[str, List[Dict[str, Any]]]:
    order: List[str] = []
    for fs in (preferred, "CFS", "OFS"):
        if fs in {"CFS", "OFS"} and fs not in order:
            order.append(fs)
    for fs in order:
        rows = by_fs.get(fs) or []
        if rows:
            return fs, [dict(row) for row in rows]
    return "", []


def account_values(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    output: Dict[str, Dict[str, Any]] = {}
    for key, spec in ACCOUNT_SPECS.items():
        chosen = choose_account(rows, spec)
        if chosen is None:
            output[key] = {"found": False}
            continue
        output[key] = {
            "found": True,
            "account_nm": norm_text(chosen.get("account_nm")),
            "thstrm_amount": parse_number(chosen.get("thstrm_amount")),
            "thstrm_add_amount": parse_number(chosen.get("thstrm_add_amount")),
            "frmtrm_amount": parse_number(chosen.get("frmtrm_amount")),
            "frmtrm_add_amount": parse_number(chosen.get("frmtrm_add_amount")),
            "bfefrmtrm_amount": parse_number(chosen.get("bfefrmtrm_amount")),
        }
    return output


def cumulative_value(account: Mapping[str, Any]) -> Optional[float]:
    if not account.get("found"):
        return None
    value = account.get("thstrm_add_amount")
    return value if value is not None else account.get("thstrm_amount")


def deep_candidates(items: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    cash_value: Optional[float] = None
    core: List[Dict[str, Any]] = []
    leases: List[Dict[str, Any]] = []
    other_financial: List[Dict[str, Any]] = []
    da: List[Dict[str, Any]] = []

    def candidate(item: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "account_id": norm_text(item.get("account_id")),
            "account_nm": norm_text(item.get("account_nm")),
            "amount": parse_number(item.get("thstrm_amount")),
        }

    for item in items:
        sj_div = norm_text(item.get("sj_div"))
        account_id = norm_text(item.get("account_id"))
        account_nm = norm_text(item.get("account_nm"))
        name_compact = compact(account_nm)
        haystack = compact(f"{account_id} {account_nm}")

        if sj_div == "BS":
            if (
                account_id in CASH_ACCOUNT_IDS
                or account_nm in CASH_EXACT_NAMES
            ):
                amount = parse_number(item.get("thstrm_amount"))
                if amount is not None:
                    cash_value = amount

            if (
                account_id in CORE_DEBT_ACCOUNT_IDS
                or account_nm in CORE_DEBT_EXACT_NAMES
            ):
                if len(core) < 40:
                    core.append(candidate(item))
            elif (
                account_id in LEASE_ACCOUNT_IDS
                or any(compact(term) in name_compact for term in LEASE_TERMS)
            ):
                if len(leases) < 20:
                    leases.append(candidate(item))
            elif (
                account_id in OTHER_FINANCIAL_LIABILITY_ACCOUNT_IDS
                or any(
                    compact(term) in name_compact
                    for term in OTHER_FINANCIAL_LIABILITY_TERMS
                )
            ):
                if len(other_financial) < 20:
                    other_financial.append(candidate(item))

        if sj_div in {"CF", "IS", "CIS"}:
            if any(compact(term) in haystack for term in DA_TERMS):
                # Raw candidate only. No EBITDA calculation is allowed here.
                if len(da) < 30:
                    da.append(candidate(item))

    return {
        "cash": cash_value,
        "core": core,
        "leases": leases,
        "other_financial": other_financial,
        "da": da,
    }


def fetch_deep_one(
    client: OpenDartClient,
    target: Mapping[str, str],
    year: int,
) -> Dict[str, Any]:
    order: List[str] = []
    for fs in (target["preferred_fs_div"], "CFS", "OFS"):
        if fs in {"CFS", "OFS"} and fs not in order:
            order.append(fs)

    last_status = ""
    last_message = ""
    for fs_div in order:
        payload = client.get_json(
            FULL_ACCOUNT_URL,
            {
                "corp_code": target["corp_code"],
                "bsns_year": str(year),
                "reprt_code": "11011",
                "fs_div": fs_div,
            },
            f"full:{target['ticker']}:{year}:{fs_div}",
        )
        status = norm_text(payload.get("status"))
        message = norm_text(payload.get("message"))
        items = payload.get("list") if isinstance(payload.get("list"), list) else []
        last_status, last_message = status, message
        if status == "000" and items:
            values = deep_candidates(items)
            return {
                "status": "OK",
                "fs_div": fs_div,
                "cash": values["cash"],
                "core_json": json_compact(values["core"]),
                "leases_json": json_compact(values["leases"]),
                "other_financial_json": json_compact(values["other_financial"]),
                "da_json": json_compact(values["da"]),
                "message": "",
            }

    return {
        "status": "LIMITED",
        "fs_div": "",
        "cash": None,
        "core_json": "[]",
        "leases_json": "[]",
        "other_financial_json": "[]",
        "da_json": "[]",
        "message": f"{last_status}:{last_message}",
    }


def load_existing_cache(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    try:
        df = read_csv(path)
    except Exception:
        return {}
    rows = {}
    for _, row in df.iterrows():
        ticker = clean_ticker(row.get("ticker"))
        if ticker:
            rows[ticker] = {column: norm_text(row.get(column)) for column in df.columns}
    return rows


def build_rows(
    output_dir: Path,
    api_key: str,
    workers: int,
    timeout: int,
    max_full_account_calls: int,
) -> Tuple[pd.DataFrame, List[str]]:
    financial_path = output_dir / FINANCIAL_CACHE
    if not financial_path.exists():
        raise RuntimeError(f"MISSING_FINANCIAL_CACHE:{financial_path}")

    financial_df = read_csv(financial_path)
    targets = load_targets(financial_df)
    if not targets:
        raise RuntimeError("NO_VALID_TARGETS")

    dominant_year, dominant_code = dominant_period(targets)
    annual_year = dominant_year - 1
    existing = load_existing_cache(output_dir / SOURCE_CACHE)
    client = OpenDartClient(api_key, timeout=timeout)

    log = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"SOURCE_CONTRACT_VERSION={SOURCE_CONTRACT_VERSION}",
        f"SCORE_POLICY_VERSION={SCORE_POLICY_VERSION}",
        f"RUN_AT_KST={now_kst_text()}",
        f"TARGETS={len(targets)}",
        f"DOMINANT_FINANCIAL_PERIOD={dominant_year}_{dominant_code}",
        f"ANNUAL_SOURCE_YEAR={annual_year}",
        "SCORE_VALUES_GENERATED=false",
    ]

    # Annual 3-year raw inputs: current / previous / before-previous values.
    annual_data = query_multi_period(
        client,
        targets,
        annual_year,
        "11011",
    )

    # Q2 standalone source is enabled only for the exact period validated by the probe.
    quarter_enabled = dominant_code == "11012"
    quarter_maps: Dict[Tuple[int, str], Any] = {}
    if quarter_enabled:
        for year, report_code in (
            (dominant_year, "11012"),
            (dominant_year, "11013"),
            (dominant_year - 1, "11012"),
            (dominant_year - 1, "11013"),
        ):
            quarter_maps[(year, report_code)] = query_multi_period(
                client,
                targets,
                year,
                report_code,
            )

    annual_output: Dict[str, Dict[str, Any]] = {}
    quarter_output: Dict[str, Dict[str, Any]] = {}

    for target in targets:
        corp_code = target["corp_code"]
        annual_fs, annual_rows = select_fs_rows(
            annual_data.get(corp_code, {}),
            target["preferred_fs_div"],
        )
        annual_accounts = account_values(annual_rows)
        annual_ready = all(
            annual_accounts[key].get("found")
            and annual_accounts[key].get("thstrm_amount") is not None
            and annual_accounts[key].get("frmtrm_amount") is not None
            and annual_accounts[key].get("bfefrmtrm_amount") is not None
            for key in ("revenue", "operating_profit", "net_income")
        )
        annual_output[target["ticker"]] = {
            "fs_div": annual_fs,
            "status": "READY" if annual_ready else "LIMITED",
            "accounts": annual_accounts,
        }

        if not quarter_enabled:
            quarter_output[target["ticker"]] = {
                "status": "UNSUPPORTED_UNVERIFIED_PERIOD",
            }
            continue

        period_accounts: Dict[Tuple[int, str], Dict[str, Dict[str, Any]]] = {}
        period_fs: Dict[Tuple[int, str], str] = {}
        for period in (
            (dominant_year, "11012"),
            (dominant_year, "11013"),
            (dominant_year - 1, "11012"),
            (dominant_year - 1, "11013"),
        ):
            fs_div, rows = select_fs_rows(
                quarter_maps[period].get(corp_code, {}),
                target["preferred_fs_div"],
            )
            period_fs[period] = fs_div
            period_accounts[period] = account_values(rows)

        q2_values: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
        quarter_ready = True
        for key in ("revenue", "operating_profit", "net_income"):
            h1_current = cumulative_value(period_accounts[(dominant_year, "11012")][key])
            q1_current = cumulative_value(period_accounts[(dominant_year, "11013")][key])
            h1_previous = cumulative_value(period_accounts[(dominant_year - 1, "11012")][key])
            q1_previous = cumulative_value(period_accounts[(dominant_year - 1, "11013")][key])
            if None in (h1_current, q1_current, h1_previous, q1_previous):
                quarter_ready = False
                q2_values[key] = (None, None)
            else:
                q2_values[key] = (
                    float(h1_current) - float(q1_current),
                    float(h1_previous) - float(q1_previous),
                )

        quarter_output[target["ticker"]] = {
            "status": "READY_Q2_SOURCE" if quarter_ready else "LIMITED",
            "year": dominant_year,
            "values": q2_values,
        }

    # Annual deep raw source: reuse same-year cache; fetch only misses.
    deep_output: Dict[str, Dict[str, Any]] = {}
    to_fetch: List[Mapping[str, str]] = []
    for target in targets:
        old = existing.get(target["ticker"], {})
        reusable = (
            clean_corp_code(old.get("corp_code")) == target["corp_code"]
            and norm_text(old.get("deep_source_year")) == str(annual_year)
            and norm_text(old.get("deep_source_status")) == "OK"
        )
        if reusable:
            deep_output[target["ticker"]] = {
                "status": "OK",
                "fs_div": norm_text(old.get("deep_fs_div")),
                "cash": parse_number(old.get("cash_and_cash_equivalents")),
                "core_json": norm_text(old.get("core_debt_candidates_json")) or "[]",
                "leases_json": norm_text(old.get("lease_liability_candidates_json")) or "[]",
                "other_financial_json": norm_text(
                    old.get("other_financial_liability_candidates_json")
                ) or "[]",
                "da_json": norm_text(
                    old.get("depreciation_amortization_candidates_json")
                ) or "[]",
                "message": "CACHE_REUSED",
            }
        else:
            to_fetch.append(target)

    if len(to_fetch) > max_full_account_calls:
        raise RuntimeError(
            f"FULL_ACCOUNT_CALL_BUDGET_EXCEEDED:{len(to_fetch)}>{max_full_account_calls}"
        )

    log.append(f"DEEP_CACHE_REUSED={len(deep_output)}")
    log.append(f"DEEP_TO_FETCH={len(to_fetch)}")

    if to_fetch:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            future_map = {
                pool.submit(fetch_deep_one, client, target, annual_year): target
                for target in to_fetch
            }
            for future in as_completed(future_map):
                target = future_map[future]
                try:
                    deep_output[target["ticker"]] = future.result()
                except Exception as exc:
                    deep_output[target["ticker"]] = {
                        "status": "LIMITED",
                        "fs_div": "",
                        "cash": None,
                        "core_json": "[]",
                        "leases_json": "[]",
                        "other_financial_json": "[]",
                        "da_json": "[]",
                        "message": f"{type(exc).__name__}:{exc}",
                    }

    fetched_at = now_kst_text()
    rows: List[Dict[str, Any]] = []

    for target in targets:
        ticker = target["ticker"]
        annual = annual_output[ticker]
        quarter = quarter_output[ticker]
        deep = deep_output.get(ticker, {
            "status": "LIMITED",
            "fs_div": "",
            "cash": None,
            "core_json": "[]",
            "leases_json": "[]",
            "other_financial_json": "[]",
            "da_json": "[]",
            "message": "NO_DEEP_RESULT",
        })

        a = annual["accounts"]
        q_values = quarter.get("values", {})

        def a_value(key: str, field: str):
            return a.get(key, {}).get(field)

        def q_value(key: str, index: int):
            pair = q_values.get(key, (None, None))
            return pair[index] if isinstance(pair, tuple) else None

        core_candidates = []
        try:
            core_candidates = json.loads(deep["core_json"])
        except Exception:
            pass

        source_cache_status = (
            "READY_RAW_SOURCE"
            if annual["status"] == "READY"
            and quarter.get("status") == "READY_Q2_SOURCE"
            and deep.get("status") == "OK"
            else "LIMITED_RAW_SOURCE"
        )
        reasons = []
        if annual["status"] != "READY":
            reasons.append("3Y_ANNUAL_LIMITED")
        if quarter.get("status") != "READY_Q2_SOURCE":
            reasons.append(f"QUARTER_{quarter.get('status')}")
        if deep.get("status") != "OK":
            reasons.append("DEEP_ANNUAL_LIMITED")

        rows.append({
            "ticker": ticker,
            "name": target["name"],
            "market": target["market"],
            "corp_code": target["corp_code"],
            "corp_name": target["corp_name"],
            "source_contract_version": SOURCE_CONTRACT_VERSION,
            "score_policy_version": SCORE_POLICY_VERSION,
            "source_cache_status": source_cache_status,
            "source_cache_reason": ",".join(reasons),
            "financial_basis_at_source": target["financial_basis"],
            "preferred_fs_div": target["preferred_fs_div"],
            "annual_source_year": annual_year,
            "annual_fs_div": annual["fs_div"],
            "annual_revenue_y0": a_value("revenue", "thstrm_amount"),
            "annual_revenue_y1": a_value("revenue", "frmtrm_amount"),
            "annual_revenue_y2": a_value("revenue", "bfefrmtrm_amount"),
            "annual_operating_profit_y0": a_value("operating_profit", "thstrm_amount"),
            "annual_operating_profit_y1": a_value("operating_profit", "frmtrm_amount"),
            "annual_operating_profit_y2": a_value("operating_profit", "bfefrmtrm_amount"),
            "annual_net_income_y0": a_value("net_income", "thstrm_amount"),
            "annual_net_income_y1": a_value("net_income", "frmtrm_amount"),
            "annual_net_income_y2": a_value("net_income", "bfefrmtrm_amount"),
            "three_year_source_status": annual["status"],
            "quarter_source_status": quarter.get("status"),
            "quarter_current_year": quarter.get("year", ""),
            "q2_revenue_current": q_value("revenue", 0),
            "q2_revenue_previous": q_value("revenue", 1),
            "q2_operating_profit_current": q_value("operating_profit", 0),
            "q2_operating_profit_previous": q_value("operating_profit", 1),
            "q2_net_income_current": q_value("net_income", 0),
            "q2_net_income_previous": q_value("net_income", 1),
            "q2_revenue_yoy_pct": safe_yoy_pct(
                q_value("revenue", 0), q_value("revenue", 1)
            ),
            "q2_operating_profit_yoy_pct": safe_yoy_pct(
                q_value("operating_profit", 0),
                q_value("operating_profit", 1),
            ),
            "q2_net_income_yoy_pct": safe_yoy_pct(
                q_value("net_income", 0), q_value("net_income", 1)
            ),
            "quarter_acceleration_classification": "",
            "quarter_acceleration_policy_status": "NOT_DEFINED_NO_CLASSIFICATION",
            "deep_source_year": annual_year,
            "deep_fs_div": deep.get("fs_div", ""),
            "deep_source_status": deep.get("status", "LIMITED"),
            "cash_and_cash_equivalents": deep.get("cash"),
            "core_debt_candidates_json": deep.get("core_json", "[]"),
            "lease_liability_candidates_json": deep.get("leases_json", "[]"),
            "other_financial_liability_candidates_json": deep.get(
                "other_financial_json", "[]"
            ),
            "depreciation_amortization_candidates_json": deep.get("da_json", "[]"),
            "net_cash_value": "",
            "net_cash_policy_status": (
                "RAW_CASH_AND_DEBT_CAPTURED_POLICY_REQUIRED"
                if deep.get("status") == "OK"
                else "SOURCE_LIMITED_POLICY_REQUIRED"
            ),
            "ev_ebitda_value": "",
            "ev_ebitda_source_status": "SOURCE_LIMITED_DA_NOT_VALIDATED",
            "investment_score_100": "",
            "investment_score_status": "SOURCE_ONLY_SCORE_NOT_GENERATED",
            "score_threshold_policy_status": "NOT_DEFINED",
            "fetched_at_kst": fetched_at,
        })

    df = pd.DataFrame(rows)
    for column in OUTPUT_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df = df[OUTPUT_COLUMNS].sort_values(["market", "ticker"])

    ready_3y = int((df["three_year_source_status"] == "READY").sum())
    ready_quarter = int((df["quarter_source_status"] == "READY_Q2_SOURCE").sum())
    ready_deep = int((df["deep_source_status"] == "OK").sum())
    ready_raw = int((df["source_cache_status"] == "READY_RAW_SOURCE").sum())

    log.extend([
        f"OUTPUT_ROWS={len(df)}",
        f"THREE_YEAR_READY={ready_3y}",
        f"QUARTER_SOURCE_READY={ready_quarter}",
        f"DEEP_SOURCE_READY={ready_deep}",
        f"RAW_SOURCE_READY={ready_raw}",
        f"HTTP_ATTEMPTS={client.attempted}",
        f"HTTP_SUCCESSES={client.successful}",
        f"TRANSPORT_FAILURES={len(client.transport_failures)}",
        f"DART_STATUS_FAILURES={len(client.dart_status_failures)}",
        "NET_CASH_CALCULATED=false",
        "EV_EBITDA_CALCULATED=false",
        "INVESTMENT_SCORE_100_CALCULATED=false",
        "SCORE_THRESHOLD_POLICY_STATUS=NOT_DEFINED",
    ])
    for item in client.transport_failures[:20]:
        log.append(f"TRANSPORT_FAILURE={item}")
    for item in client.dart_status_failures[:20]:
        log.append(f"DART_STATUS_FAILURE={item}")

    return df, log


def self_test() -> None:
    assert clean_ticker("5930") == "005930"
    assert clean_corp_code("126380") == "00126380"
    assert parse_number("1,234") == 1234.0
    assert parse_number("(10)") == -10.0
    assert safe_yoy_pct(120, 100) == 20.0

    rows = [
        {
            "sj_div": "IS",
            "account_nm": "매출액",
            "thstrm_amount": "300",
            "frmtrm_amount": "200",
            "bfefrmtrm_amount": "100",
        }
    ]
    chosen = choose_account(rows, ACCOUNT_SPECS["revenue"])
    assert chosen is not None
    assert parse_number(chosen["thstrm_amount"]) == 300.0

    deep = deep_candidates([
        {
            "sj_div": "BS",
            "account_id": "ifrs-full_CashAndCashEquivalents",
            "account_nm": "현금및현금성자산",
            "thstrm_amount": "500",
        },
        {
            "sj_div": "BS",
            "account_id": "ifrs-full_ShorttermBorrowings",
            "account_nm": "단기차입금",
            "thstrm_amount": "100",
        },
        {
            "sj_div": "BS",
            "account_id": "ifrs-full_CurrentLeaseLiabilities",
            "account_nm": "리스부채",
            "thstrm_amount": "20",
        },
    ])
    assert deep["cash"] == 500.0
    assert len(deep["core"]) == 1
    assert len(deep["leases"]) == 1
    assert deep["other_financial"] == []

    # Critical safety contract.
    assert "investment_score_100" in OUTPUT_COLUMNS
    assert "net_cash_value" in OUTPUT_COLUMNS
    assert "ev_ebitda_value" in OUTPUT_COLUMNS

    print("SELF_TEST=PASS")
    print("SCORE_VALUES_GENERATED=false")
    print("NET_CASH_CALCULATED=false")
    print("EV_EBITDA_CALCULATED=false")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-full-account-calls", type=int, default=5000)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DART_API_KEY_MISSING")

    output_dir = Path(args.output_dir)
    df, log = build_rows(
        output_dir=output_dir,
        api_key=api_key,
        workers=max(1, args.workers),
        timeout=max(10, args.timeout),
        max_full_account_calls=max(1, args.max_full_account_calls),
    )

    write_csv_atomic(df, output_dir / SOURCE_CACHE)
    (output_dir / RUN_LOG).write_text("\n".join(log) + "\n", encoding="utf-8")

    limited = int((df["source_cache_status"] != "READY_RAW_SOURCE").sum())
    status = "OK" if len(df) > 0 else "FAILED"
    print(f"INVESTMENT_SCORE_SOURCE_STATUS={status}")
    print(f"OUTPUT_ROWS={len(df)}")
    print(f"LIMITED_RAW_SOURCE_ROWS={limited}")
    print("INVESTMENT_SCORE_100_CALCULATED=false")
    print("NET_CASH_CALCULATED=false")
    print("EV_EBITDA_CALCULATED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
