#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply the v7.1 final display contract to generated stock-table APIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

DISPLAY_CONTRACT_VERSION = "2026-07-09-v7.1-final-display-cleanup"

TARGETS = (
    {
        "filename": "kospi_watchlist.json",
        "market_scope": "KR",
        "display_name": "코피표 — 코스피 분석 후보 30개",
    },
    {
        "filename": "kosdaq_watchlist.json",
        "market_scope": "KR",
        "display_name": "코닥표 — 코스닥 분석 후보 10개",
    },
    {
        "filename": "us_watchlist.json",
        "market_scope": "US",
        "display_name": "미관종표 — S&P500 기반 미국 분석 후보 30개",
    },
)

BUY_RANGE_KEYS = ("value_buy_range", "buy_range", "가치매수구간")
SELL_RANGE_KEYS = (
    "first_sell_target_range",
    "target1_range",
    "sell_range",
    "1차 매도·익절가",
    "1차 매도/익절가",
)
SECTOR_THEME_KEYS = ("sector_theme", "sector/theme", "섹터/테마")
SECTOR_KEYS = ("sector", "업종", "industry_group")
INDUSTRY_KEYS = ("industry", "industry_name", "세부업종")


class DisplayContractError(RuntimeError):
    pass


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise DisplayContractError(f"필수 API 누락: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DisplayContractError(f"JSON 읽기 실패: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DisplayContractError(f"JSON 최상위 객체 오류: {path}")
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> int:
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def first_text(row: Mapping[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = clean_text(row.get(key))
        if value:
            return value
    return None


def bold_range(value: Any) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    if text.startswith("**") and text.endswith("**"):
        return text
    return f"**{text}**"


def sector_theme_value(row: Mapping[str, Any]) -> Optional[str]:
    direct = first_text(row, SECTOR_THEME_KEYS)
    if direct:
        return direct
    sector = first_text(row, SECTOR_KEYS)
    industry = first_text(row, INDUSTRY_KEYS)
    if sector and industry:
        return f"{sector} / {industry}"
    return sector or industry


def metadata_policy(market_scope: str) -> Dict[str, Any]:
    common: Dict[str, Any] = {
        "required_common_rows": [
            "API 생성시각",
            "자동화 입력 원본 커밋",
            "빌드 ID",
            "규칙 버전",
            "사용 본표 Action",
            "분석자료 기준일",
            "재무·밸류에이션 기준일",
            "정적 현재가 기준시점",
            "요청시점 조회시간",
            "가격 자료시각",
            "현재가 조회 결과",
            "재시도 과정",
            "가격 출처",
            "시간외 반영 여부",
            "공식자료 최신성",
            "분석범위",
            "구조 검증",
            "우회 사용 여부",
        ],
        "price_timestamp_label": (
            "실제 체결시각이 보장되지 않으면 '가격 거래시각' 대신 "
            "'가격 자료시각' 또는 '가격 갱신시각' 사용"
        ),
    }
    if market_scope == "US":
        common.update(
            {
                "visible_market_metadata": "US",
                "omit_by_default": [
                    "KRX 기대 거래일",
                    "KOSPI 실제 기준일",
                    "KOSDAQ 실제 기준일",
                    "KOSPI·KOSDAQ 실제 기준일",
                ],
                "preferred_market_rows": [
                    "미국 분석 기준 거래일",
                    "미국 요청가격 시장상태",
                    "미국 정규장·시간외 상태",
                ],
                "exception": (
                    "한국시장 동기화 정보는 사용자가 전체 자동화 상태를 "
                    "명시적으로 요청한 경우에만 표시"
                ),
            }
        )
    else:
        common.update(
            {
                "visible_market_metadata": "KR",
                "preferred_market_rows": [
                    "KRX 기대 거래일",
                    "KOSPI·KOSDAQ 실제 기준일",
                ],
                "omit_by_default": [
                    "미국 분석 기준 거래일",
                    "미국 요청가격 시장상태",
                ],
            }
        )
    return common


def output_contract(market_scope: str) -> Dict[str, Any]:
    return {
        "version": DISPLAY_CONTRACT_VERSION,
        "output_sequence": [
            "title",
            "metadata_two_column_table",
            "main_stock_table",
            "minimal_required_notes",
        ],
        "current_price_column_label": "요청시점 현재가",
        "bold_price_ranges_required": True,
        "preferred_buy_range_field": "value_buy_range_markdown",
        "preferred_first_sell_range_field": "first_sell_target_range_markdown",
        "markdown_rule": (
            "가격범위 문자열 전체를 **가격~가격** 형식으로 굵게 표시하며 "
            "별표를 표 밖에 분리하지 않는다"
        ),
        "metadata_policy": metadata_policy(market_scope),
        "sector_theme_policy": {
            "column_position": "far_right",
            "do_not_invent": True,
            "missing_value_display": "자료 미제공",
        },
    }


def patch_rows(rows: List[Any]) -> Dict[str, Any]:
    sector_count = 0
    patched_rows = 0

    for raw in rows:
        if not isinstance(raw, MutableMapping):
            continue

        buy = first_text(raw, BUY_RANGE_KEYS)
        sell = first_text(raw, SELL_RANGE_KEYS)
        if buy:
            raw["value_buy_range_markdown"] = bold_range(buy)
        if sell:
            raw["first_sell_target_range_markdown"] = bold_range(sell)

        sector_theme = sector_theme_value(raw)
        if sector_theme:
            raw["sector_theme"] = sector_theme
            sector_count += 1
        elif "sector_theme" not in raw:
            raw["sector_theme"] = None

        patched_rows += 1

    return {
        "patched_rows": patched_rows,
        "sector_theme_nonempty_rows": sector_count,
    }


def apply_one(api_dir: Path, target: Mapping[str, str]) -> Dict[str, Any]:
    path = api_dir / target["filename"]
    payload = read_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise DisplayContractError(f"{path}: rows 형식 오류")

    stats = patch_rows(rows)
    if stats["patched_rows"] != len(rows):
        raise DisplayContractError(
            f"{path}: 패치 행 수 불일치 "
            f"{stats['patched_rows']} != {len(rows)}"
        )

    payload["display_name"] = target["display_name"]
    payload["display_contract_version"] = DISPLAY_CONTRACT_VERSION
    payload["output_contract"] = output_contract(target["market_scope"])
    payload["sector_theme_available"] = (
        stats["sector_theme_nonempty_rows"] == len(rows) and len(rows) > 0
    )
    payload["sector_theme_nonempty_rows"] = stats[
        "sector_theme_nonempty_rows"
    ]

    columns = payload.get("columns")
    if isinstance(columns, list):
        for field in (
            "value_buy_range_markdown",
            "first_sell_target_range_markdown",
            "sector_theme",
        ):
            if field not in columns:
                columns.append(field)

    final_size = write_json(path, payload)

    return {
        "filename": target["filename"],
        "market_scope": target["market_scope"],
        "row_count": len(rows),
        "sector_theme_nonempty_rows": stats["sector_theme_nonempty_rows"],
        "payload_size_bytes": final_size,
    }


def apply_final_display_contract(api_dir: Path) -> List[Dict[str, Any]]:
    entries = [apply_one(api_dir, target) for target in TARGETS]

    manifest_path = api_dir / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        manifest["final_display_contract"] = {
            "version": DISPLAY_CONTRACT_VERSION,
            "current_price_column_label": "요청시점 현재가",
            "bold_price_ranges_required": True,
            "us_metadata_omits_kr_market_rows_by_default": True,
            "sector_theme_do_not_invent": True,
            "entries": entries,
        }
        write_json(manifest_path, manifest)

    return entries


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", default="api")
    args = parser.parse_args()

    entries = apply_final_display_contract(Path(args.api_dir))
    print("FINAL_DISPLAY_CONTRACT_V71=OK")
    for entry in entries:
        print(
            f"{entry['filename']}="
            f"rows:{entry['row_count']},"
            f"sector:{entry['sector_theme_nonempty_rows']},"
            f"bytes:{entry['payload_size_bytes']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
