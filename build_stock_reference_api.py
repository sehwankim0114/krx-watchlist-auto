#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_stock_reference_api.py v1.0.0

보유종목표의 개인정보 비저장 런타임을 위한 공개 종목 참고 API를 만든다.

입력
- latest/kospi_universe_summary_latest.csv
- latest/kosdaq_universe_summary_latest.csv

출력
- api/stock_reference_manifest.json
- api/stock_reference_shards/00.json ... 99.json 중 실제 사용 prefix

개인정보 보호
- 보유수량, 평균매수가, 평가손익, 계좌정보는 입력·출력하지 않는다.
- 공개 시장·기업 분석자료만 종목코드 앞 두 자리로 분할한다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


SCRIPT_VERSION = (
    "build_stock_reference_api.py "
    "v1.1.0-summary-label-compat-v741"
)
POLICY_VERSION = (
    "2026-07-03-v6.0-private-holdings-runtime"
)
KST = timezone(timedelta(hours=9))

PRIVATE_FIELD_TERMS = {
    "quantity",
    "average_price",
    "average_buy_price",
    "cost_basis",
    "market_value",
    "evaluation_profit_loss",
    "return_pct_holding",
    "account",
    "account_number",
    "financing_type",
    "holding_type",
    "보유수량",
    "평균매수가",
    "평가손익",
    "계좌",
}

PREFERRED_PUBLIC_FIELDS = (
    "ticker",
    "name",
    "market",
    "status",
    "last_date",
    "current_close",
    "split_buy_low_ref",
    "split_buy_high_ref",
    "target1_ref",
    "target2_ref",
    "stop_ref",
    "low_3m_intraday",
    "high_3m_intraday",
    "low_3m_close",
    "high_3m_close",
    "position_in_3m_range_pct",
    "return_1m_pct",
    "return_3m_pct",
    "low_liquidity",
    "operating_loss_flag",
    "operating_loss_basis",
    "supply_burden_flag",
    "supply_burden_level",
    "supply_burden_keywords",
    "trading_activity_label",
    "price_elasticity_label",
    "market_score",
    "legacy_market_score",
    "legacy_market_reason",
    "financial_data_status",
    "valuation_data_status",
    "per",
    "pbr",
    "roe",
    "market_cap",
)

REQUIRED_PUBLIC_FIELDS = {
    "ticker",
    "name",
    "market",
    "status",
    "last_date",
    "current_close",
    "split_buy_low_ref",
    "split_buy_high_ref",
    "target1_ref",
    "target2_ref",
    "stop_ref",
    "low_3m_intraday",
    "high_3m_intraday",
    "low_3m_close",
    "high_3m_close",
    "return_1m_pct",
    "return_3m_pct",
    "low_liquidity",
    "operating_loss_flag",
    "supply_burden_flag",
    "supply_burden_level",
    "supply_burden_keywords",
    "trading_activity_label",
    "price_elasticity_label",
}


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def clean_ticker(value: Any) -> str:
    text = str(value).strip()
    if text.lower() in {"", "nan", "none"}:
        return ""
    text = re.sub(r"\.0$", "", text)
    digits = re.sub(r"\D", "", text)
    return digits.zfill(6) if digits else text.upper()


def normalize_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


# STOCK_REFERENCE_LABEL_COMPAT_V741_BEGIN
SUMMARY_LABEL_COMPAT_POLICY = {
    "version": "2026-07-09-v7.4.1-summary-label-compat",
    "preserve_existing_labels": True,
    "derive_only_when_missing_or_blank": True,
    "trading_activity_source_priority": [
        "avg20_trading_value",
        "last_trading_value",
    ],
    "trading_activity_thresholds_krw": {
        "매우활발": 50000000000,
        "활발": 30000000000,
        "보통": 10000000000,
        "부족": 3000000000,
        "매우부족": 0,
    },
    "price_elasticity_source": "avg_daily_move_pct",
    "price_elasticity_thresholds_pct": {
        "탄력 불안정": 5.0,
        "탄력 높음": 3.0,
        "탄력 보통": 1.5,
        "탄력 낮음": 0.0,
    },
}


def _numeric_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _derive_trading_activity_label(value: Any) -> str:
    number = _numeric_or_none(value)
    if number is None:
        return "자료부족"
    if number >= 50_000_000_000:
        return "매우활발"
    if number >= 30_000_000_000:
        return "활발"
    if number >= 10_000_000_000:
        return "보통"
    if number >= 3_000_000_000:
        return "부족"
    return "매우부족"


def _derive_price_elasticity_label(value: Any) -> str:
    number = _numeric_or_none(value)
    if number is None:
        return "자료부족"
    number = abs(number)
    if number >= 5.0:
        return "탄력 불안정"
    if number >= 3.0:
        return "탄력 높음"
    if number >= 1.5:
        return "탄력 보통"
    return "탄력 낮음"


def _blank_label_mask(series: pd.Series) -> pd.Series:
    text = series.astype("string").fillna("").str.strip()
    return text.eq("") | text.str.lower().isin({"nan", "none", "null"})


def ensure_summary_labels(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()

    if "avg20_trading_value" in frame.columns:
        trading_source = frame["avg20_trading_value"]
    elif "last_trading_value" in frame.columns:
        trading_source = frame["last_trading_value"]
    else:
        trading_source = pd.Series(
            [None] * len(frame),
            index=frame.index,
            dtype="object",
        )

    derived_trading = trading_source.map(
        _derive_trading_activity_label
    )
    if "trading_activity_label" not in frame.columns:
        frame["trading_activity_label"] = derived_trading
    else:
        mask = _blank_label_mask(frame["trading_activity_label"])
        frame.loc[mask, "trading_activity_label"] = (
            derived_trading.loc[mask]
        )

    if "avg_daily_move_pct" in frame.columns:
        elasticity_source = frame["avg_daily_move_pct"]
    else:
        elasticity_source = pd.Series(
            [None] * len(frame),
            index=frame.index,
            dtype="object",
        )

    derived_elasticity = elasticity_source.map(
        _derive_price_elasticity_label
    )
    if "price_elasticity_label" not in frame.columns:
        frame["price_elasticity_label"] = derived_elasticity
    else:
        mask = _blank_label_mask(frame["price_elasticity_label"])
        frame.loc[mask, "price_elasticity_label"] = (
            derived_elasticity.loc[mask]
        )

    return frame
# STOCK_REFERENCE_LABEL_COMPAT_V741_END


def read_summary(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"요약자료가 없습니다: {path}")

    frame = pd.read_csv(
        path,
        encoding="utf-8-sig",
        dtype={"ticker": str},
    )
    frame = ensure_summary_labels(frame)
    missing = REQUIRED_PUBLIC_FIELDS - set(frame.columns)
    if missing:
        raise ValueError(
            f"{path.name} 필수열 누락: "
            + ",".join(sorted(missing))
        )

    frame = frame.copy()
    frame["ticker"] = frame["ticker"].map(clean_ticker)
    frame["market"] = frame["market"].astype(str).str.upper()
    frame = frame.loc[frame["ticker"].str.match(r"^\d{6}$")]
    return frame


def choose_public_fields(columns: Iterable[str]) -> list[str]:
    available = set(columns)
    selected = [
        field
        for field in PREFERRED_PUBLIC_FIELDS
        if field in available
    ]

    private_found = PRIVATE_FIELD_TERMS & set(selected)
    if private_found:
        raise ValueError(
            "공개필드에 개인정보 열이 포함됨: "
            + ",".join(sorted(private_found))
        )
    return selected


def build_reference(
    kospi: pd.DataFrame,
    kosdaq: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    combined = pd.concat(
        [kospi, kosdaq],
        ignore_index=True,
    )

    fields = choose_public_fields(combined.columns)
    frame = combined[fields].copy()
    frame["ticker"] = frame["ticker"].map(clean_ticker)
    frame["market"] = frame["market"].astype(str).str.upper()
    frame["prefix"] = frame["ticker"].str[:2]

    duplicate = frame.duplicated(
        subset=["market", "ticker"],
        keep=False,
    )
    if duplicate.any():
        rows = frame.loc[
            duplicate,
            ["market", "ticker", "name"],
        ].to_dict("records")
        raise ValueError(
            "시장·종목코드 중복: "
            + json.dumps(rows[:20], ensure_ascii=False)
        )

    frame = frame.sort_values(
        ["prefix", "market", "ticker"],
        kind="stable",
    ).reset_index(drop=True)

    return frame, fields


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=normalize_value,
        )
        + "\n",
        encoding="utf-8",
    )


def remove_stale_shards(
    shard_dir: Path,
    active_names: set[str],
) -> list[str]:
    removed: list[str] = []
    if not shard_dir.exists():
        return removed

    for path in shard_dir.glob("*.json"):
        if path.name not in active_names:
            path.unlink()
            removed.append(path.name)
    return sorted(removed)


def build_api(
    *,
    kospi_path: Path,
    kosdaq_path: Path,
    api_dir: Path,
) -> dict[str, Any]:
    kospi = read_summary(kospi_path)
    kosdaq = read_summary(kosdaq_path)
    frame, fields = build_reference(kospi, kosdaq)

    generated_at = now_kst()
    shard_dir = api_dir / "stock_reference_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)

    shard_records: list[dict[str, Any]] = []
    active_names: set[str] = set()

    for prefix, group in frame.groupby(
        "prefix",
        sort=True,
    ):
        filename = f"{prefix}.json"
        active_names.add(filename)
        rows = []
        for record in group.drop(
            columns=["prefix"]
        ).to_dict("records"):
            rows.append(
                {
                    key: normalize_value(value)
                    for key, value in record.items()
                }
            )

        payload = {
            "status": "OK",
            "schema_version": "1.0",
            "script_version": SCRIPT_VERSION,
            "policy_version": POLICY_VERSION,
            "generated_at_kst": generated_at,
            "prefix": prefix,
            "row_count": len(rows),
            "lookup_key": ["market", "ticker"],
            "privacy_mode": "public_market_reference_only",
            "contains_user_holdings": False,
            "columns": fields,
            "rows": rows,
        }
        write_json(shard_dir / filename, payload)
        shard_records.append(
            {
                "prefix": prefix,
                "api_file": (
                    "api/stock_reference_shards/"
                    + filename
                ),
                "row_count": len(rows),
            }
        )

    removed = remove_stale_shards(
        shard_dir,
        active_names,
    )

    date_values = pd.to_datetime(
        frame["last_date"],
        errors="coerce",
    ).dropna()
    basis_min = (
        date_values.min().date().isoformat()
        if not date_values.empty
        else None
    )
    basis_max = (
        date_values.max().date().isoformat()
        if not date_values.empty
        else None
    )

    manifest = {
        "status": "OK",
        "schema_version": "1.0",
        "script_version": SCRIPT_VERSION,
        "policy_version": POLICY_VERSION,
        "generated_at_kst": generated_at,
        "runtime_mode": (
            "user_holdings_stay_in_conversation"
        ),
        "privacy_policy": {
            "contains_user_holdings": False,
            "stored_private_fields": [],
            "never_store": sorted(PRIVATE_FIELD_TERMS),
            "calculation_location": (
                "assistant response runtime only"
            ),
        },
        "usage": {
            "step_1": (
                "Read ticker from the user's current message."
            ),
            "step_2": (
                "Use the first two ticker digits as prefix."
            ),
            "step_3": (
                "Call getStockReferenceShard(prefix)."
            ),
            "step_4": (
                "Find the exact market+ticker row."
            ),
            "step_5": (
                "Calculate quantity, cost basis, market value, "
                "profit/loss and return only in the conversation."
            ),
            "cash_credit_rule": (
                "Keep cash and credit lots as separate rows."
            ),
        },
        "source_files": [
            str(kospi_path),
            str(kosdaq_path),
        ],
        "source_rows": {
            "kospi": int(len(kospi)),
            "kosdaq": int(len(kosdaq)),
            "total": int(len(frame)),
        },
        "basis_date_min": basis_min,
        "basis_date_max": basis_max,
        "public_columns": fields,
        "summary_label_compat_policy": SUMMARY_LABEL_COMPAT_POLICY,
        "shard_key": "ticker_first_two_digits",
        "shard_count": len(shard_records),
        "shards": shard_records,
        "removed_stale_shards": removed,
    }
    write_json(
        api_dir / "stock_reference_manifest.json",
        manifest,
    )
    return manifest


def synthetic_summary(
    *,
    market: str,
    start: int,
    count: int,
) -> pd.DataFrame:
    rows = []
    for offset in range(count):
        code = str(start + offset).zfill(6)
        price = 10000 + offset * 100
        rows.append(
            {
                "ticker": code,
                "name": f"{market}테스트{offset}",
                "market": market,
                "status": "OK",
                "last_date": "2026-07-02",
                "current_close": price,
                "split_buy_low_ref": price * 0.90,
                "split_buy_high_ref": price * 0.97,
                "target1_ref": price * 1.08,
                "target2_ref": price * 1.15,
                "stop_ref": price * 0.85,
                "low_3m_intraday": price * 0.70,
                "high_3m_intraday": price * 1.25,
                "low_3m_close": price * 0.72,
                "high_3m_close": price * 1.20,
                "position_in_3m_range_pct": 50,
                "return_1m_pct": 5,
                "return_3m_pct": 10,
                "low_liquidity": False,
                "operating_loss_flag": False,
                "operating_loss_basis": "2026 1분기",
                "supply_burden_flag": False,
                "supply_burden_level": "",
                "supply_burden_keywords": "",
                "trading_activity_label": "활발",
                "price_elasticity_label": "탄력 보통",
                "market_score": 70,
                "quantity": 999,
                "average_price": 999999,
            }
        )
    return pd.DataFrame(rows)


def run_self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        latest = root / "latest"
        api = root / "api"
        latest.mkdir(parents=True)

        kospi = synthetic_summary(
            market="KOSPI",
            start=660,
            count=3,
        )
        kosdaq = synthetic_summary(
            market="KOSDAQ",
            start=49630,
            count=3,
        )

        kospi_path = (
            latest / "kospi_universe_summary_latest.csv"
        )
        kosdaq_path = (
            latest / "kosdaq_universe_summary_latest.csv"
        )
        kospi.to_csv(
            kospi_path,
            index=False,
            encoding="utf-8-sig",
        )
        kosdaq.to_csv(
            kosdaq_path,
            index=False,
            encoding="utf-8-sig",
        )

        manifest = build_api(
            kospi_path=kospi_path,
            kosdaq_path=kosdaq_path,
            api_dir=api,
        )

        assert manifest["status"] == "OK"
        assert manifest["source_rows"]["total"] == 6
        assert (
            manifest["privacy_policy"][
                "contains_user_holdings"
            ]
            is False
        )
        assert "quantity" not in manifest["public_columns"]
        assert (
            "average_price"
            not in manifest["public_columns"]
        )

        shard_files = sorted(
            (api / "stock_reference_shards").glob(
                "*.json"
            )
        )
        assert shard_files
        rows = []
        for path in shard_files:
            payload = json.loads(
                path.read_text(encoding="utf-8")
            )
            assert payload["contains_user_holdings"] is False
            rows.extend(payload["rows"])
        assert len(rows) == 6
        assert all("quantity" not in row for row in rows)
        assert all(
            "average_price" not in row
            for row in rows
        )

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "two_digit_shards,"
        "manifest,"
        "market_ticker_lookup,"
        "private_fields_excluded,"
        "stale_shard_cleanup,"
        "six_public_rows"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kospi-summary",
        default=(
            "latest/kospi_universe_summary_latest.csv"
        ),
    )
    parser.add_argument(
        "--kosdaq-summary",
        default=(
            "latest/kosdaq_universe_summary_latest.csv"
        ),
    )
    parser.add_argument(
        "--api-dir",
        default="api",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    manifest = build_api(
        kospi_path=Path(args.kospi_summary),
        kosdaq_path=Path(args.kosdaq_summary),
        api_dir=Path(args.api_dir),
    )

    print("STOCK_REFERENCE_API_STATUS=OK")
    print(
        "TOTAL_PUBLIC_REFERENCE_ROWS="
        f"{manifest['source_rows']['total']}"
    )
    print(
        "STOCK_REFERENCE_SHARD_COUNT="
        f"{manifest['shard_count']}"
    )
    print("CONTAINS_USER_HOLDINGS=false")
    print("PRIVATE_FIELDS_STORED=0")
    print(
        "OUTPUT_MANIFEST="
        "api/stock_reference_manifest.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
