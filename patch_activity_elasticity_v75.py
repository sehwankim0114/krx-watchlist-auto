#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''V7.5 patch: restore trading activity and price elasticity in compact KR tables.'''

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
BUILDER = ROOT / "build_lightweight_watchlist_api_v66.py"
STOCK_REFERENCE = ROOT / "build_stock_reference_api.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"

RULES_VERSION = "2026-07-09-v7.5-activity-elasticity"
POLICY_VERSION = "2026-07-09-v7.5-activity-elasticity"
BEGIN = "# ACTIVITY_ELASTICITY_V75_BEGIN"
END = "# ACTIVITY_ELASTICITY_V75_END"
RULES_MARKER = "<!-- ACTIVITY_ELASTICITY_V75 -->"


class PatchError(RuntimeError):
    pass


HELPERS = r'''
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
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label} 기준점 오류: {count}")
    return text.replace(old, new, 1)


def patch_builder() -> None:
    if not BUILDER.exists():
        raise FileNotFoundError(BUILDER)

    text = BUILDER.read_text(encoding="utf-8")

    if "import re" not in text:
        text = replace_once(
            text,
            "import math\n",
            "import math\nimport re\n",
            "re import",
        )

    if BEGIN not in text:
        anchor = (
            "def compact_row("
            "source: Mapping[str, Any], "
            "default_market: str"
            ") -> Dict[str, Any]:"
        )
        text = replace_once(
            text,
            anchor,
            HELPERS.strip() + "\n\n\n" + anchor,
            "compact_row helper insertion",
        )

    if "trading_activity = (" not in text:
        anchor = (
            '    recommendation_display = '
            'f"{marker} {name}".strip() '
            'if marker else name\n'
        )
        insertion = (
            anchor
            + "    trading_activity = (\n"
            + "        clean_scalar(source.get(\"trading_activity_label\"))\n"
            + "        or derive_trading_activity_label(source.get(\"avg_trading_value\"))\n"
            + "    )\n"
            + "    price_elasticity_pct = extract_elasticity_pct(source)\n"
            + "    price_elasticity = (\n"
            + "        clean_scalar(source.get(\"price_elasticity_label\"))\n"
            + "        or derive_price_elasticity_label(price_elasticity_pct)\n"
            + "    )\n"
        )
        text = replace_once(
            text,
            anchor,
            insertion,
            "compact_row derived variables",
        )

    old_activity = (
        '        "trading_activity": '
        'clean_scalar(source.get("trading_activity_label")),\n'
    )
    if old_activity in text:
        text = text.replace(
            old_activity,
            '        "trading_activity": trading_activity,\n',
            1,
        )

    old_elasticity = (
        '        "price_elasticity": '
        'clean_scalar(source.get("price_elasticity_label")),\n'
    )
    if old_elasticity in text:
        text = text.replace(
            old_elasticity,
            '        "price_elasticity": price_elasticity,\n',
            1,
        )

    old_pct = (
        '        "price_elasticity_pct": clean_number(\n'
        '            source.get("price_elasticity_basis_pct")\n'
        '        ),\n'
    )
    if old_pct in text:
        text = text.replace(
            old_pct,
            '        "price_elasticity_pct": price_elasticity_pct,\n',
            1,
        )

    if '"activity_elasticity_policy": ACTIVITY_ELASTICITY_POLICY' not in text:
        anchor = '        "validation_message": "OK",'
        replacement = (
            anchor
            + "\n"
            + '        "activity_elasticity_policy": '
            + "ACTIVITY_ELASTICITY_POLICY,"
        )
        text = replace_once(
            text,
            anchor,
            replacement,
            "payload policy",
        )

    required = (
        BEGIN,
        END,
        "derive_trading_activity_label",
        "extract_elasticity_pct",
        "derive_price_elasticity_label",
        '"trading_activity": trading_activity',
        '"price_elasticity": price_elasticity',
        '"price_elasticity_pct": price_elasticity_pct',
        '"activity_elasticity_policy": ACTIVITY_ELASTICITY_POLICY',
    )
    for token in required:
        if token not in text:
            raise PatchError(f"builder 필수 토큰 누락: {token}")

    BUILDER.write_text(text, encoding="utf-8")


def patch_stock_reference_thresholds() -> None:
    if not STOCK_REFERENCE.exists():
        raise FileNotFoundError(STOCK_REFERENCE)

    text = STOCK_REFERENCE.read_text(encoding="utf-8")

    replacements = (
        ('"매우활발": 50000000000', '"매우활발": 100000000000'),
        ('"보통": 10000000000', '"보통": 5000000000'),
        ('"부족": 3000000000', '"부족": 1000000000'),
        (
            "if number >= 50_000_000_000:",
            "if number >= 100_000_000_000:",
        ),
        (
            "if number >= 10_000_000_000:",
            "if number >= 5_000_000_000:",
        ),
        (
            "if number >= 3_000_000_000:",
            "if number >= 1_000_000_000:",
        ),
    )

    for old, new in replacements:
        if old in text:
            text = text.replace(old, new, 1)
        elif new not in text:
            raise PatchError(
                f"stock reference threshold 기준점 누락: {old}"
            )

    STOCK_REFERENCE.write_text(text, encoding="utf-8")


def patch_rules() -> None:
    if not RULES.exists():
        raise FileNotFoundError(RULES)

    text = RULES.read_text(encoding="utf-8")
    text, count = re.subn(
        r'(- 규칙 버전:\s*`)[^`]+(`)',
        rf'\g<1>{RULES_VERSION}\g<2>',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(f"규칙 버전 교체 수 오류: {count}")

    if RULES_MARKER not in text:
        text = text.rstrip() + r'''

---

## 18. 거래활발·가격탄력 복구 V7.5

<!-- ACTIVITY_ELASTICITY_V75 -->

### 18-1. 거래활발

후보 API에 완성 표시값이 없으면 `avg_trading_value`에서 계산한다.

- 1,000억원 이상: `매우활발`
- 300억원 이상: `활발`
- 50억원 이상: `보통`
- 10억원 이상: `부족`
- 10억원 미만: `매우부족`

### 18-2. 가격탄력

후보 API에 완성 표시값이 없으면 `avg_daily_move_text`의
절대 변동률을 읽어 계산한다.

- 5% 이상: `탄력 불안정`
- 3% 이상: `탄력 높음`
- 1.5% 이상: `탄력 보통`
- 1.5% 미만: `탄력 낮음`

### 18-3. 출력 원칙

- 표 열 이름은 `거래활발·가격탄력`을 기본으로 사용한다.
- 등급은 가격 방향이나 투자등급이 아니라 거래규모와 변동폭의
  참고표시다.
- 기존 완성 표시값이 있으면 보존하고, 없을 때만 수치에서 복구한다.
- 수치자료까지 없을 때만 `자료 미제공`으로 표시한다.
''' + "\n"

    RULES.write_text(text, encoding="utf-8")


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "lightweight_builder_v75",
        BUILDER,
    )
    if spec is None or spec.loader is None:
        raise PatchError("builder import spec failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def self_test() -> None:
    module = load_builder()

    activity_cases = (
        (150_000_000_000, "매우활발"),
        (50_000_000_000, "활발"),
        (8_000_000_000, "보통"),
        (2_000_000_000, "부족"),
        (500_000_000, "매우부족"),
    )
    for value, expected in activity_cases:
        actual = module.derive_trading_activity_label(value)
        if actual != expected:
            raise PatchError(
                f"activity self-test failed: "
                f"{value} {actual} != {expected}"
            )

    elasticity_cases = (
        (5.5, "탄력 불안정"),
        (3.2, "탄력 높음"),
        (2.4, "탄력 보통"),
        (1.2, "탄력 낮음"),
    )
    for value, expected in elasticity_cases:
        actual = module.derive_price_elasticity_label(value)
        if actual != expected:
            raise PatchError(
                f"elasticity self-test failed: "
                f"{value} {actual} != {expected}"
            )

    row = module.compact_row(
        {
            "rank": 1,
            "recommend_flag": "✅",
            "code": "000001",
            "name": "테스트",
            "market": "KOSDAQ",
            "asof_date": "2026-07-08",
            "close": "10,000",
            "buy_range": "9,000원~9,500원",
            "sell_range": "10,500원~11,000원",
            "low_3m": 8000,
            "high_3m": 12000,
            "return_1m_pct": 5.0,
            "avg_volume": 100000,
            "avg_trading_value": 8_000_000_000,
            "avg_daily_move_text": "약 ±250원 내외 (±2.50%)",
            "operating_loss_flag": False,
            "supply_burden_flag": False,
            "score": 100,
        },
        "KOSDAQ",
    )
    if row["trading_activity"] != "보통":
        raise PatchError(f"compact row activity failed: {row}")
    if row["price_elasticity"] != "탄력 보통":
        raise PatchError(f"compact row elasticity failed: {row}")
    if row["price_elasticity_pct"] != 2.5:
        raise PatchError(f"compact row pct failed: {row}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    patch_builder()
    patch_stock_reference_thresholds()
    patch_rules()

    if args.self_test:
        self_test()

    print("PATCH_ACTIVITY_ELASTICITY_V75=OK")
    print(f"RULES_VERSION={RULES_VERSION}")
    print("TRADING_ACTIVITY_SOURCE=avg_trading_value")
    print("PRICE_ELASTICITY_SOURCE=avg_daily_move_text")
    if args.self_test:
        print("ACTIVITY_ELASTICITY_SELF_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
