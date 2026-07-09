#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build compact KOSPI/KOSDAQ watchlist APIs for Custom GPT Actions."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

CONTRACT_VERSION = "2026-07-08-v6.6-lightweight-watchlists"
MAX_PAYLOAD_BYTES = 65000

SPECS = (
    {
        "source_name": "kospi_candidates_30.json",
        "output_name": "kospi_watchlist.json",
        "table_id": "kospi_watchlist",
        "display_name": "코피표 — 코스피 후보 30개",
        "operation_id": "getKospiWatchlist",
        "exact_rows": 30,
        "market": "KOSPI",
    },
    {
        "source_name": "kosdaq_candidates_10.json",
        "output_name": "kosdaq_watchlist.json",
        "table_id": "kosdaq_watchlist",
        "display_name": "코닥표 — 코스닥 후보 10개",
        "operation_id": "getKosdaqWatchlist",
        "exact_rows": 10,
        "market": "KOSDAQ",
    },
)


class BuildError(RuntimeError):
    pass


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise BuildError(f"필수 JSON 누락: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BuildError(f"JSON 읽기 실패: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"JSON 최상위 객체 오류: {path}")
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> int:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def clean_number(value: Any) -> Optional[float]:
    value = clean_scalar(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("원", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def clean_int(value: Any) -> Optional[int]:
    number = clean_number(value)
    if number is None:
        return None
    return int(round(number))


def clean_bool(value: Any) -> bool:
    value = clean_scalar(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {
        "1", "true", "yes", "y", "t", "예", "있음", "경계", "위험"
    }


def normalize_code(value: Any) -> str:
    value = clean_scalar(value)
    if value is None:
        return ""
    text = str(value).replace(".0", "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[-6:].zfill(6) if digits else text


def latest_text(values: Iterable[Any]) -> Optional[str]:
    cleaned = sorted(
        {
            str(value).strip()
            for value in values
            if clean_scalar(value) is not None
        }
    )
    return cleaned[-1] if cleaned else None


def earliest_text(values: Iterable[Any]) -> Optional[str]:
    cleaned = sorted(
        {
            str(value).strip()
            for value in values
            if clean_scalar(value) is not None
        }
    )
    return cleaned[0] if cleaned else None


def format_krw_amount(value: Any) -> Optional[str]:
    number = clean_number(value)
    if number is None:
        return None
    absolute = abs(number)
    sign = "-" if number < 0 else ""
    if absolute >= 1_000_000_000_000:
        return f"{sign}{absolute / 1_000_000_000_000:.2f}조원"
    if absolute >= 100_000_000:
        return f"{sign}{absolute / 100_000_000:.0f}억원"
    if absolute >= 10_000:
        return f"{sign}{absolute / 10_000:.0f}만원"
    return f"{sign}{absolute:,.0f}원"


# ACTIVITY_ELASTICITY_V75_BEGIN
ACTIVITY_ELASTICITY_POLICY = {
    "version": "2026-07-09-v7.5-activity-elasticity",
    "preserve_existing_labels": True,
    "derive_only_when_missing": True,
    "trading_activity_source": "avg_trading_value",
    "trading_activity_thresholds_krw": {
        "매우활발": 100000000000,
        "활발": 30000000000,
        "보통": 5000000000,
        "부족": 1000000000,
        "매우부족": 0,
    },
    "price_elasticity_source_priority": [
        "price_elasticity_basis_pct",
        "avg_daily_move_text",
    ],
    "price_elasticity_thresholds_pct": {
        "탄력 불안정": 5.0,
        "탄력 높음": 3.0,
        "탄력 보통": 1.5,
        "탄력 낮음": 0.0,
    },
}


def derive_trading_activity_label(value: Any) -> Optional[str]:
    number = clean_number(value)
    if number is None:
        return None
    number = abs(number)
    if number >= 100_000_000_000:
        return "매우활발"
    if number >= 30_000_000_000:
        return "활발"
    if number >= 5_000_000_000:
        return "보통"
    if number >= 1_000_000_000:
        return "부족"
    return "매우부족"


def extract_elasticity_pct(source: Mapping[str, Any]) -> Optional[float]:
    explicit = clean_number(source.get("price_elasticity_basis_pct"))
    if explicit is not None:
        return abs(explicit)

    text = clean_scalar(source.get("avg_daily_move_text"))
    if text is None:
        return None

    matches = re.findall(r"([+-]?\d+(?:\.\d+)?)\s*%", str(text))
    if not matches:
        return None
    try:
        return abs(float(matches[-1]))
    except (TypeError, ValueError):
        return None


def derive_price_elasticity_label(value: Any) -> Optional[str]:
    number = clean_number(value)
    if number is None:
        return None
    number = abs(number)
    if number >= 5.0:
        return "탄력 불안정"
    if number >= 3.0:
        return "탄력 높음"
    if number >= 1.5:
        return "탄력 보통"
    return "탄력 낮음"
# ACTIVITY_ELASTICITY_V75_END


def compact_row(source: Mapping[str, Any], default_market: str) -> Dict[str, Any]:
    code = normalize_code(source.get("code"))
    name = str(clean_scalar(source.get("name")) or "").strip()
    market = str(clean_scalar(source.get("market")) or default_market).upper()
    operating_loss = clean_bool(source.get("operating_loss_flag"))
    supply_burden = clean_bool(
        source.get("supply_burden_flag")
        if source.get("supply_burden_flag") is not None
        else source.get("supply_burden_detected")
    )
    recommend_flag = str(clean_scalar(source.get("recommend_flag")) or "")
    marker = (
        ("-" if operating_loss else "")
        + recommend_flag
        + ("_" if supply_burden else "")
    )
    recommendation_display = f"{marker} {name}".strip() if marker else name
    trading_activity = (
        clean_scalar(source.get("trading_activity_label"))
        or derive_trading_activity_label(source.get("avg_trading_value"))
    )
    price_elasticity_pct = extract_elasticity_pct(source)
    price_elasticity = (
        clean_scalar(source.get("price_elasticity_label"))
        or derive_price_elasticity_label(price_elasticity_pct)
    )

    return {
        "rank": clean_int(source.get("rank")),
        "recommendation_display": recommendation_display,
        "name": name,
        "code": code,
        "quote_key": code,
        "quote_market": market,
        "analysis_date": clean_scalar(source.get("asof_date")),
        "static_price": clean_scalar(source.get("close")),
        "value_buy_range": clean_scalar(source.get("buy_range")),
        "first_sell_target_range": clean_scalar(source.get("sell_range")),
        "low_3m": clean_number(source.get("low_3m")),
        "high_3m": clean_number(source.get("high_3m")),
        "return_1m_pct": clean_number(source.get("return_1m_pct")),
        "avg_volume": clean_int(source.get("avg_volume")),
        "avg_trading_value_krw": clean_int(source.get("avg_trading_value")),
        "trading_activity": trading_activity,
        "price_elasticity": price_elasticity,
        "price_elasticity_pct": price_elasticity_pct,
        "avg_daily_move": clean_scalar(source.get("avg_daily_move_text")),
        "current_position": clean_scalar(source.get("current_position_label")),
        "current_position_pct": clean_number(
            source.get("current_position_basis_pct")
            if source.get("current_position_basis_pct") is not None
            else source.get("position_in_3m_range_pct")
        ),
        "operating_profit_text": format_krw_amount(source.get("operating_profit")),
        "operating_loss": operating_loss,
        "earnings_trend": clean_scalar(source.get("earnings_trend")),
        "revenue_yoy_pct": clean_number(source.get("revenue_yoy_pct")),
        "operating_profit_yoy_pct": clean_number(
            source.get("operating_profit_yoy_pct")
        ),
        "per_annualized": clean_number(source.get("per_annualized")),
        "pbr": clean_number(source.get("pbr")),
        "supply_check_status": clean_scalar(source.get("supply_check_status")),
        "supply_burden": supply_burden,
        "supply_burden_level": clean_scalar(
            source.get("supply_burden_level")
        ),
        "supply_burden_keywords": clean_scalar(
            source.get("supply_burden_keywords")
        ),
        "score": clean_number(source.get("score")),
        "score_reason": clean_scalar(source.get("reason")),
    }


def source_rules_meta(source: Mapping[str, Any]) -> Dict[str, Any]:
    rules = source.get("rules")
    if isinstance(rules, dict):
        return dict(rules)
    return {
        "version": source.get("rules_version"),
        "sha256": source.get("rules_sha256"),
    }


def build_one(api_dir: Path, spec: Mapping[str, Any]) -> Dict[str, Any]:
    source_path = api_dir / str(spec["source_name"])
    source = read_json(source_path)

    if source.get("status") != "OK":
        raise BuildError(
            f"{spec['source_name']} status={source.get('status')}"
        )

    source_rows = source.get("rows")
    if not isinstance(source_rows, list):
        raise BuildError(f"{spec['source_name']} rows 형식 오류")

    exact_rows = int(spec["exact_rows"])
    if len(source_rows) != exact_rows:
        raise BuildError(
            f"{spec['source_name']} 행 수 오류: "
            f"{len(source_rows)} != {exact_rows}"
        )

    rows = [
        compact_row(row, str(spec["market"]))
        for row in source_rows
        if isinstance(row, dict)
    ]
    if len(rows) != exact_rows:
        raise BuildError(
            f"{spec['output_name']} 변환 행 수 오류: "
            f"{len(rows)} != {exact_rows}"
        )

    for row in rows:
        if not row["name"]:
            raise BuildError(f"{spec['output_name']} 종목명 누락")
        if len(row["quote_key"]) != 6 or not row["quote_key"].isdigit():
            raise BuildError(
                f"{spec['output_name']} 종목코드 오류: {row['quote_key']}"
            )
        if not row["value_buy_range"] or not row["first_sell_target_range"]:
            raise BuildError(
                f"{spec['output_name']} 가격구간 누락: {row['name']}"
            )

    analysis_date = latest_text(row["analysis_date"] for row in rows)
    valuation_date_min = earliest_text(
        row.get("valuation_price_basis_date") for row in source_rows
    )
    valuation_date_max = latest_text(
        row.get("valuation_price_basis_date") for row in source_rows
    )
    financial_basis_values = sorted(
        {
            str(value).strip()
            for value in (
                row.get("financial_basis") for row in source_rows
            )
            if clean_scalar(value) is not None
        }
    )
    supply_limited_reasons = sorted(
        {
            str(value).strip()
            for value in (
                row.get("supply_check_limited_reason")
                for row in source_rows
            )
            if clean_scalar(value) is not None
        }
    )
    rules = source_rules_meta(source)

    payload: Dict[str, Any] = {
        "schema_version": source.get("schema_version"),
        "compact_contract_version": CONTRACT_VERSION,
        "compact_payload": True,
        "preferred_default_action": True,
        "operation_id": spec["operation_id"],
        "build_id": source.get("build_id"),
        "script": "build_lightweight_watchlist_api_v66.py",
        "table_id": spec["table_id"],
        "display_name": spec["display_name"],
        "generated_at_kst": source.get("generated_at_kst"),
        "source_commit_sha": source.get("source_commit_sha"),
        "status": "OK",
        "required": False,
        "lightweight_required": True,
        "default_output": True,
        "explicit_request_only": False,
        "source_api_file": f"api/{spec['source_name']}",
        "source_file": source.get("source_file"),
        "source_priority": source.get("source_priority"),
        "current_basis_selected": source.get("current_basis_selected"),
        "row_count": len(rows),
        "row_count_ok": len(rows) == exact_rows,
        "expected_rows": {"exact": exact_rows, "minimum": None},
        "validation_message": "OK",
        "activity_elasticity_policy": ACTIVITY_ELASTICITY_POLICY,
        "candidate_analysis_date": analysis_date,
        "data_date_min": analysis_date,
        "data_date_max": analysis_date,
        "valuation_basis_date_min": valuation_date_min,
        "valuation_basis_date_max": valuation_date_max,
        "financial_basis_values": financial_basis_values,
        "supply_check_limited_reasons": supply_limited_reasons,
        "sector_theme_available": False,
        "official_data": source.get("official_data"),
        "current_price_basis": source.get("current_price_basis"),
        "rules_version": source.get("rules_version"),
        "rules_sha256": source.get("rules_sha256"),
        "rules": rules,
        "presentation_policy": source.get("presentation_policy"),
        "request_time_price_policy": source.get(
            "request_time_price_policy"
        ),
        "fallback_policy": {
            "csv_fallback_allowed": False,
            "legacy_full_api_fallback_allowed": False,
            "on_action_failure": (
                "stop_and_report_action_failure_without_reconstructing_rows"
            ),
        },
        "date_display_policy": {
            "analysis_data_date_field": "candidate_analysis_date",
            "valuation_date_field": (
                "valuation_basis_date_min/valuation_basis_date_max"
            ),
            "do_not_use_valuation_date_as_candidate_analysis_date": True,
        },
        "action_usage_rule": (
            f"Use {spec['operation_id']} for the default "
            f"{spec['display_name']} request. Read rows directly, query "
            "request-time prices with quote_key and quote_market, preserve "
            "the original row order, and never reconstruct this table from "
            "CSV or the legacy full candidate endpoint."
        ),
        "columns": list(rows[0].keys()) if rows else [],
        "rows": rows,
        "payload_size_limit_bytes": MAX_PAYLOAD_BYTES,
    }

    output_path = api_dir / str(spec["output_name"])
    initial_text = json.dumps(
        payload, ensure_ascii=False, indent=2, allow_nan=False
    ) + "\n"
    payload["payload_size_bytes"] = len(initial_text.encode("utf-8"))
    final_size = write_json(output_path, payload)
    payload["payload_size_bytes"] = final_size
    final_size = write_json(output_path, payload)

    if final_size > MAX_PAYLOAD_BYTES:
        raise BuildError(
            f"{spec['output_name']} 응답 크기 초과: "
            f"{final_size} > {MAX_PAYLOAD_BYTES}"
        )

    return {
        "table_id": spec["table_id"],
        "display_name": spec["display_name"],
        "api_file": f"api/{spec['output_name']}",
        "source_file": source.get("source_file"),
        "source_api_file": f"api/{spec['source_name']}",
        "status": "OK",
        "row_count": len(rows),
        "required": False,
        "lightweight_required": True,
        "default_output": True,
        "explicit_request_only": False,
        "compact_payload": True,
        "preferred_default_action": True,
        "operation_id": spec["operation_id"],
        "payload_size_bytes": final_size,
        "candidate_analysis_date": analysis_date,
        "current_basis_selected": source.get("current_basis_selected"),
        "presentation_policy": source.get("presentation_policy"),
        "request_time_price_policy": source.get(
            "request_time_price_policy"
        ),
    }


def update_manifest(
    api_dir: Path,
    entries: List[Dict[str, Any]],
) -> None:
    manifest_path = api_dir / "manifest.json"
    manifest = read_json(manifest_path)
    tables = manifest.get("tables")
    if not isinstance(tables, list):
        raise BuildError("manifest.json tables 형식 오류")

    ids = {entry["table_id"] for entry in entries}
    filtered = [
        item
        for item in tables
        if not isinstance(item, dict) or item.get("table_id") not in ids
    ]
    filtered.extend(entries)
    manifest["tables"] = filtered
    manifest["lightweight_watchlists"] = {
        "contract_version": CONTRACT_VERSION,
        "preferred_actions": {
            "KOSPI": "getKospiWatchlist",
            "KOSDAQ": "getKosdaqWatchlist",
        },
        "csv_fallback_allowed": False,
        "legacy_full_api_fallback_allowed": False,
        "entries": [
            {
                "table_id": entry["table_id"],
                "api_file": entry["api_file"],
                "operation_id": entry["operation_id"],
                "row_count": entry["row_count"],
                "payload_size_bytes": entry["payload_size_bytes"],
                "candidate_analysis_date": entry[
                    "candidate_analysis_date"
                ],
            }
            for entry in entries
        ],
    }
    write_json(manifest_path, manifest)


def build_lightweight_watchlists(api_dir: Path) -> List[Dict[str, Any]]:
    entries = [build_one(api_dir, spec) for spec in SPECS]
    update_manifest(api_dir, entries)
    return entries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api-dir",
        default="api",
        help="Generated API directory",
    )
    args = parser.parse_args()
    entries = build_lightweight_watchlists(Path(args.api_dir))
    print("LIGHTWEIGHT_WATCHLIST_V66=OK")
    for entry in entries:
        print(
            f"{entry['table_id']}="
            f"rows:{entry['row_count']},"
            f"bytes:{entry['payload_size_bytes']},"
            f"date:{entry['candidate_analysis_date']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
