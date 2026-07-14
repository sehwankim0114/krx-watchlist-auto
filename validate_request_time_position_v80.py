#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate V8.0 request-time position behavior."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

VERSION = "2026-07-14-v8.0-request-time-position-alignment"


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(
        "request_time_explanation_refresher_v80",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        default="request_time_explanation_refresher.py",
    )
    args = parser.parse_args()

    module = load_module(Path(args.file))
    if module.POLICY_VERSION != VERSION:
        raise SystemExit(
            f"POLICY_VERSION_MISMATCH={module.POLICY_VERSION}"
        )

    base = {
        "official_price": 100,
        "low_3m": 80,
        "high_3m": 140,
        "value_buy_low": 95,
        "value_buy_high": 105,
        "take_profit_low": 120,
        "take_profit_high": 130,
        "base_recommendation": "✅",
        "score": 82,
        "static_non_price_reason": "재무흐름 양호",
    }

    cases = [
        (
            {"status": "OK", "price": 70},
            -16.67,
            "BELOW_PERIOD_LOW",
            12.5,
            "3개월 저가 대비 12.5% 하회 · 범위위치 -16.7%",
            "BELOW_BUY_ZONE",
            "가치매수구간 아래",
        ),
        (
            {"status": "OK", "price": 100},
            33.33,
            "IN_PERIOD_RANGE",
            0.0,
            "저점권~중간권 33.3%",
            "BUY_ZONE",
            "가치매수구간 안",
        ),
        (
            {"status": "OK", "price": 125},
            75.0,
            "IN_PERIOD_RANGE",
            0.0,
            "중간권~고점권 75.0%",
            "TAKE_PROFIT_ZONE",
            "1차 익절구간 진입",
        ),
        (
            {"status": "OK", "price": 150},
            116.67,
            "ABOVE_PERIOD_HIGH",
            7.14,
            "3개월 고가 대비 7.1% 돌파 · 범위위치 116.7%",
            "ABOVE_TARGET",
            "1차 익절구간 상단 돌파",
        ),
    ]

    for (
        quote,
        expected_position,
        expected_break_status,
        expected_break_pct,
        expected_display,
        expected_zone,
        expected_zone_label,
    ) in cases:
        result = module.refresh(base, quote)
        assert result["request_time_position_pct"] == expected_position
        assert (
            result["request_time_range_break_status"]
            == expected_break_status
        )
        assert (
            result["request_time_range_break_pct"]
            == expected_break_pct
        )
        assert (
            result["request_time_position_display"]
            == expected_display
        )
        assert result["request_time_price_zone"] == expected_zone
        assert (
            result["request_time_price_zone_label"]
            == expected_zone_label
        )

    failed = module.refresh(base, {"status": "FAILED"})
    assert failed["request_time_position_display"] == "확인 불가"
    assert (
        failed["request_time_range_break_status"]
        == "RANGE_UNAVAILABLE"
    )

    print("REQUEST_TIME_POSITION_VALIDATION_V80=PASS")
    print("CASES_CHECKED=5")
    print("BELOW_LOW_DYNAMIC_DISPLAY=PASS")
    print("ABOVE_HIGH_DYNAMIC_DISPLAY=PASS")
    print("BUY_TARGET_ZONE_LABELS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
