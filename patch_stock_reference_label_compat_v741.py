#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Make stock-reference API compatible with current universe summary CSVs.

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "build_stock_reference_api.py"

PATCH_VERSION = "2026-07-09-v7.4.1-summary-label-compat"
BEGIN = "# STOCK_REFERENCE_LABEL_COMPAT_V741_BEGIN"
END = "# STOCK_REFERENCE_LABEL_COMPAT_V741_END"


class PatchError(RuntimeError):
    pass


HELPERS = r'''
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
'''


def patch_version(text: str) -> str:
    pattern = re.compile(
        r'SCRIPT_VERSION\s*=\s*\(\s*'
        r'"build_stock_reference_api\.py "\s*'
        r'"[^"]+"\s*\)',
        re.MULTILINE,
    )
    replacement = (
        'SCRIPT_VERSION = (\n'
        '    "build_stock_reference_api.py "\n'
        '    "v1.1.0-summary-label-compat-v741"\n'
        ')'
    )
    patched, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise PatchError(f"SCRIPT_VERSION 교체 수 오류: {count}")
    return patched


def patch_helpers(text: str) -> str:
    if BEGIN in text and END in text:
        return text
    anchor = "def read_summary(path: Path) -> pd.DataFrame:"
    if text.count(anchor) != 1:
        raise PatchError(
            f"read_summary 삽입 기준점 오류: {text.count(anchor)}"
        )
    return text.replace(anchor, HELPERS.strip() + "\n\n\n" + anchor, 1)


def patch_read_summary(text: str) -> str:
    if "frame = ensure_summary_labels(frame)" in text:
        return text

    anchor = '''    frame = pd.read_csv(
        path,
        encoding="utf-8-sig",
        dtype={"ticker": str},
    )
    missing = REQUIRED_PUBLIC_FIELDS - set(frame.columns)
'''
    replacement = '''    frame = pd.read_csv(
        path,
        encoding="utf-8-sig",
        dtype={"ticker": str},
    )
    frame = ensure_summary_labels(frame)
    missing = REQUIRED_PUBLIC_FIELDS - set(frame.columns)
'''
    count = text.count(anchor)
    if count != 1:
        raise PatchError(f"read_summary 보정 기준점 오류: {count}")
    return text.replace(anchor, replacement, 1)


def patch_manifest(text: str) -> str:
    token = '"summary_label_compat_policy": SUMMARY_LABEL_COMPAT_POLICY'
    if token in text:
        return text

    anchor = '        "public_columns": fields,'
    count = text.count(anchor)
    if count != 1:
        raise PatchError(f"manifest 정책 기준점 오류: {count}")
    replacement = (
        anchor
        + "\n"
        + '        "summary_label_compat_policy": '
        + "SUMMARY_LABEL_COMPAT_POLICY,"
    )
    return text.replace(anchor, replacement, 1)


def verify(text: str) -> None:
    required = (
        "v1.1.0-summary-label-compat-v741",
        BEGIN,
        END,
        "frame = ensure_summary_labels(frame)",
        '"summary_label_compat_policy": SUMMARY_LABEL_COMPAT_POLICY',
        '"avg20_trading_value"',
        '"avg_daily_move_pct"',
    )
    for token in required:
        if token not in text:
            raise PatchError(f"필수 토큰 누락: {token}")


def main() -> int:
    if not TARGET.exists():
        raise FileNotFoundError(TARGET)

    text = TARGET.read_text(encoding="utf-8")
    text = patch_version(text)
    text = patch_helpers(text)
    text = patch_read_summary(text)
    text = patch_manifest(text)
    verify(text)
    TARGET.write_text(text, encoding="utf-8")

    print("PATCH_STOCK_REFERENCE_LABEL_COMPAT_V741=OK")
    print(f"PATCH_VERSION={PATCH_VERSION}")
    print("DERIVED_TRADING_ACTIVITY=avg20_trading_value")
    print("DERIVED_PRICE_ELASTICITY=avg_daily_move_pct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
