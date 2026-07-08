#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enrich compact Korean watchlist APIs with official KRX industry data."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

from collect_kr_sector_theme_v72 import collect_or_load, normalize_code

CONTRACT_VERSION = "2026-07-09-v7.2-kr-sector-theme"
SOURCE_ID = "KRX_KIND_LISTED_COMPANY"
REGULAR_SESSION_MINUTES = 390
MAX_PAYLOAD_BYTES = 65000

TARGETS = (
    ("kospi_watchlist.json", "kospi_watchlist", 30),
    ("kosdaq_watchlist.json", "kosdaq_watchlist", 10),
)


class EnrichmentError(RuntimeError):
    pass


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise EnrichmentError(f"필수 JSON 누락: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EnrichmentError(f"JSON 최상위 형식 오류: {path}")
    return payload


def clean_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = (
        str(value)
        .replace(",", "")
        .replace("원", "")
        .replace("주", "")
        .strip()
    )
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def format_per_minute_krw(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    absolute = abs(value)
    sign = "-" if value < 0 else ""
    if absolute >= 100_000_000:
        return f"{sign}{absolute / 100_000_000:.2f}억원/분"
    if absolute >= 10_000:
        return f"{sign}{absolute / 10_000:.1f}만원/분"
    return f"{sign}{absolute:,.0f}원/분"


def format_volume(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return f"평균 {int(round(value)):,}주"


def write_payload(path: Path, payload: MutableMapping[str, Any]) -> int:
    payload.pop("payload_size_bytes", None)
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    payload["payload_size_bytes"] = len(text.encode("utf-8"))
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    size = len(text.encode("utf-8"))
    payload["payload_size_bytes"] = size
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    size = len(text.encode("utf-8"))
    if size > MAX_PAYLOAD_BYTES:
        raise EnrichmentError(
            f"{path.name} 응답 크기 초과: {size} > {MAX_PAYLOAD_BYTES}"
        )
    path.write_text(text, encoding="utf-8")
    return size


def ensure_columns(payload: MutableMapping[str, Any], fields: List[str]) -> None:
    columns = payload.get("columns")
    if not isinstance(columns, list):
        columns = []
        payload["columns"] = columns
    for field in fields:
        if field not in columns:
            columns.append(field)


def enrich_one(
    api_dir: Path,
    filename: str,
    table_id: str,
    exact_rows: int,
    mapping: Mapping[str, Mapping[str, Any]],
    source_meta: Mapping[str, Any],
) -> Dict[str, Any]:
    path = api_dir / filename
    payload = read_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != exact_rows:
        raise EnrichmentError(
            f"{filename} 행 수 오류: "
            f"{len(rows) if isinstance(rows, list) else 0} != {exact_rows}"
        )

    matched = 0
    missing_codes: List[str] = []

    for raw in rows:
        if not isinstance(raw, MutableMapping):
            raise EnrichmentError(f"{filename} 행 형식 오류")
        code = normalize_code(raw.get("code") or raw.get("quote_key"))
        official = mapping.get(code)

        if official:
            raw["sector"] = official.get("sector")
            raw["theme"] = official.get("theme")
            raw["sector_theme"] = official.get("sector_theme")
            raw["sector_theme_source"] = SOURCE_ID
            raw["sector_theme_asof_kst"] = source_meta.get("generated_at_kst")
            matched += 1
        else:
            if not raw.get("sector_theme"):
                raw["sector"] = None
                raw["theme"] = None
                raw["sector_theme"] = "자료 미제공"
                raw["sector_theme_source"] = "UNAVAILABLE"
            missing_codes.append(code)

        avg_value = clean_number(raw.get("avg_trading_value_krw"))
        avg_volume = clean_number(raw.get("avg_volume"))
        per_minute = (
            avg_value / REGULAR_SESSION_MINUTES
            if avg_value is not None
            else None
        )
        raw["avg_trading_value_per_minute_krw"] = (
            int(round(per_minute)) if per_minute is not None else None
        )
        raw["avg_trading_value_per_minute_display"] = (
            format_per_minute_krw(per_minute)
        )
        volume_display = format_volume(avg_volume)
        minute_display = format_per_minute_krw(per_minute)
        raw["average_volume_per_minute_value_display"] = (
            f"{volume_display}\n약 {minute_display}"
            if volume_display and minute_display
            else volume_display or minute_display
        )

    coverage_pct = round(matched / exact_rows * 100.0, 2)
    if matched < exact_rows:
        raise EnrichmentError(
            f"{filename} 공식 업종 매칭 부족: {matched}/{exact_rows}; "
            f"missing={','.join(missing_codes)}"
        )

    payload["display_contract_version"] = CONTRACT_VERSION
    payload["sector_theme_available"] = True
    payload["sector_theme_nonempty_rows"] = matched
    payload["sector_theme_coverage_pct"] = coverage_pct
    payload["sector_theme_source"] = SOURCE_ID
    payload["sector_theme_source_url"] = source_meta.get("source_url")
    payload["sector_theme_asof_kst"] = source_meta.get("generated_at_kst")
    payload["sector_theme_cache_mode"] = source_meta.get("cache_mode")
    payload["preferred_column_labels"] = {
        "current_price": "요청시점 현재가",
        "average_volume_per_minute_value": "평균거래량·분당거래금",
        "market_ticker": "시장·티커",
        "sector_theme": "섹터/테마",
    }

    contract = payload.get("output_contract")
    if not isinstance(contract, dict):
        contract = {}
        payload["output_contract"] = contract
    contract.update(
        {
            "version": CONTRACT_VERSION,
            "current_price_column_label": "요청시점 현재가",
            "average_volume_per_minute_value_column_label": (
                "평균거래량·분당거래금"
            ),
            "average_volume_field": "avg_volume",
            "per_minute_trading_value_field": (
                "avg_trading_value_per_minute_krw"
            ),
            "combined_trading_display_field": (
                "average_volume_per_minute_value_display"
            ),
            "regular_session_minutes": REGULAR_SESSION_MINUTES,
            "sector_theme_field": "sector_theme",
            "sector_theme_source": SOURCE_ID,
            "sector_theme_missing_display": "자료 미제공",
            "sector_theme_do_not_invent": True,
            "far_right_columns": ["시장·티커", "섹터/테마"],
            "bold_price_ranges_required": True,
            "preferred_buy_range_field": "value_buy_range_markdown",
            "preferred_first_sell_range_field": (
                "first_sell_target_range_markdown"
            ),
        }
    )

    ensure_columns(
        payload,
        [
            "avg_trading_value_per_minute_krw",
            "avg_trading_value_per_minute_display",
            "average_volume_per_minute_value_display",
            "sector",
            "theme",
            "sector_theme",
            "sector_theme_source",
            "sector_theme_asof_kst",
        ],
    )

    payload["table_id"] = table_id
    size = write_payload(path, payload)
    return {
        "table_id": table_id,
        "api_file": f"api/{filename}",
        "row_count": exact_rows,
        "sector_theme_matched": matched,
        "sector_theme_coverage_pct": coverage_pct,
        "payload_size_bytes": size,
    }


def update_manifest_and_status(
    api_dir: Path,
    entries: List[Dict[str, Any]],
    source_meta: Mapping[str, Any],
) -> None:
    manifest_path = api_dir / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        tables = manifest.get("tables")
        if isinstance(tables, list):
            entry_map = {entry["table_id"]: entry for entry in entries}
            for item in tables:
                if not isinstance(item, MutableMapping):
                    continue
                table_id = item.get("table_id")
                if table_id in entry_map:
                    item.update(
                        {
                            "sector_theme_available": True,
                            "sector_theme_coverage_pct": entry_map[table_id][
                                "sector_theme_coverage_pct"
                            ],
                            "sector_theme_source": SOURCE_ID,
                            "display_contract_version": CONTRACT_VERSION,
                        }
                    )
        manifest["kr_sector_theme"] = {
            "version": CONTRACT_VERSION,
            "status": "OK",
            "source": SOURCE_ID,
            "source_url": source_meta.get("source_url"),
            "generated_at_kst": source_meta.get("generated_at_kst"),
            "cache_mode": source_meta.get("cache_mode"),
            "regular_session_minutes": REGULAR_SESSION_MINUTES,
            "column_label": "평균거래량·분당거래금",
            "entries": entries,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    status_path = api_dir / "status.json"
    if status_path.exists():
        status = read_json(status_path)
        status["kr_sector_theme"] = {
            "version": CONTRACT_VERSION,
            "status": "OK",
            "source": SOURCE_ID,
            "generated_at_kst": source_meta.get("generated_at_kst"),
            "cache_mode": source_meta.get("cache_mode"),
            "coverage": {
                entry["table_id"]: entry["sector_theme_coverage_pct"]
                for entry in entries
            },
        }
        policy = status.get("presentation_policy")
        if not isinstance(policy, dict):
            policy = {}
            status["presentation_policy"] = policy
        policy.update(
            {
                "kr_sector_theme_source": SOURCE_ID,
                "kr_sector_theme_missing_display": "자료 미제공",
                "kr_average_volume_per_minute_value_column_label": (
                    "평균거래량·분당거래금"
                ),
                "kr_regular_session_minutes": REGULAR_SESSION_MINUTES,
            }
        )
        status_path.write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def apply_kr_sector_theme(
    api_dir: Path,
    latest_dir: Path,
) -> List[Dict[str, Any]]:
    mapping, source_meta = collect_or_load(
        latest_dir,
        min_rows=1500,
        refresh=True,
    )
    entries = [
        enrich_one(
            api_dir,
            filename,
            table_id,
            exact_rows,
            mapping,
            source_meta,
        )
        for filename, table_id, exact_rows in TARGETS
    ]
    update_manifest_and_status(api_dir, entries, source_meta)
    return entries


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", default="api")
    parser.add_argument("--latest-dir", default="latest")
    args = parser.parse_args()

    entries = apply_kr_sector_theme(
        Path(args.api_dir),
        Path(args.latest_dir),
    )
    print("KR_SECTOR_THEME_V72=OK")
    for entry in entries:
        print(
            f"{entry['table_id']}="
            f"rows:{entry['row_count']},"
            f"sector:{entry['sector_theme_matched']},"
            f"coverage:{entry['sector_theme_coverage_pct']},"
            f"bytes:{entry['payload_size_bytes']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
