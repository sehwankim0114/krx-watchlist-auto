#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V7.8 price-range position normalization and validation."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

VERSION = "2026-07-14-v7.8-price-range-position"
REPORT_NAME = "price_position_validation.json"

PRICE_FIELDS = (
    "static_price", "current_price", "last_price", "price",
    "close", "last_close", "현재가", "종가",
)
LOW_FIELDS = (
    "low_3m", "three_month_low", "low_90d",
    "3개월저가", "3개월_저가", "3개월최저",
)
HIGH_FIELDS = (
    "high_3m", "three_month_high", "high_90d",
    "3개월고가", "3개월_고가", "3개월최고",
)
BUY_RANGE_FIELDS = (
    "value_buy_range", "value_buy_range_markdown", "가치매수구간",
)
TARGET_RANGE_FIELDS = (
    "first_sell_target_range",
    "first_sell_target_range_markdown",
    "1차_매도_익절가",
    "1차매도익절가",
)

NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
FORBIDDEN_PATTERNS = (
    re.compile(r"3개월\s*저가\s*하회\s*0(?:\.0+)?%"),
    re.compile(r"3개월\s*고가\s*돌파\s*100(?:\.0+)?%"),
)

PRICE_POSITION_POLICY: Dict[str, Any] = {
    "version": VERSION,
    "effective_price_priority": [
        "request_time_price_when_lookup_succeeds",
        "static_price_when_request_time_lookup_fails",
    ],
    "recalculate_after_request_time_overlay": True,
    "range_position_formula": (
        "(effective_price-low_3m)/(high_3m-low_3m)*100"
    ),
    "clamp_to_zero_hundred": False,
    "below_low_display": (
        "3개월 저가 대비 X.X% 하회 · 범위위치 -Y.Y%"
    ),
    "above_high_display": (
        "3개월 고가 대비 X.X% 돌파 · 범위위치 1YY.Y%"
    ),
    "static_reference_fields": [
        "current_position",
        "current_position_pct",
        "price_zone",
    ],
    "forbidden_displays": [
        "3개월 저가 하회 0%",
        "3개월 고가 돌파 100%",
    ],
}


class PricePositionError(RuntimeError):
    pass


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PricePositionError(f"JSON read failed: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PricePositionError(f"JSON root is not an object: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    match = NUMBER_RE.search(str(value).strip())
    if not match:
        return None
    try:
        number = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def first_number(
    row: Mapping[str, Any],
    fields: Sequence[str],
) -> Tuple[Optional[float], Optional[str]]:
    for field in fields:
        if field in row:
            number = parse_number(row.get(field))
            if number is not None:
                return number, field
    return None, None


def parse_range(value: Any) -> Optional[Tuple[float, float]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        first = parse_number(value[0])
        second = parse_number(value[1])
        if first is not None and second is not None:
            return min(first, second), max(first, second)
        return None
    numbers = [
        float(item.replace(",", ""))
        for item in NUMBER_RE.findall(str(value))
    ]
    if len(numbers) < 2:
        return None
    return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])


def first_range(
    row: Mapping[str, Any],
    fields: Sequence[str],
) -> Optional[Tuple[float, float]]:
    for field in fields:
        if field in row:
            parsed = parse_range(row.get(field))
            if parsed is not None:
                return parsed
    return None


def range_position_pct(price: float, low: float, high: float) -> float:
    if high <= low:
        raise PricePositionError(
            f"Invalid 3-month range: low={low}, high={high}"
        )
    return ((price - low) / (high - low)) * 100.0


def format_current_position(price: float, low: float, high: float) -> str:
    raw = range_position_pct(price, low, high)
    epsilon = 1e-9

    if price < low - epsilon:
        below_pct = ((low - price) / low) * 100.0
        return (
            f"3개월 저가 대비 {below_pct:.1f}% 하회"
            f" · 범위위치 {raw:.1f}%"
        )
    if price > high + epsilon:
        above_pct = ((price - high) / high) * 100.0
        return (
            f"3개월 고가 대비 {above_pct:.1f}% 돌파"
            f" · 범위위치 {raw:.1f}%"
        )
    if abs(price - low) <= epsilon:
        return "3개월 저가선 0.0%"
    if abs(price - high) <= epsilon:
        return "3개월 고가선 100.0%"

    if raw < 20:
        label = "저점권"
    elif raw < 40:
        label = "저점권~중간권"
    elif raw < 60:
        label = "중간권"
    elif raw < 80:
        label = "중간권~고점권"
    else:
        label = "고점권"
    return f"{label} {raw:.1f}%"


def format_price_zone(
    price: float,
    buy_range: Optional[Tuple[float, float]],
    target_range: Optional[Tuple[float, float]],
) -> Optional[str]:
    if buy_range is not None:
        buy_low, buy_high = buy_range
        if price < buy_low:
            return "가치매수구간 아래"
        if price <= buy_high:
            return "가치매수구간 안"
        if target_range is None:
            return "가치매수구간 위"
        target_low, target_high = target_range
        if price < target_low:
            return "가치매수구간 위 · 1차 익절구간 전"
        if price <= target_high:
            return "1차 익절구간 진입"
        return "1차 익절구간 상단 돌파"

    if target_range is not None:
        target_low, target_high = target_range
        if price < target_low:
            return "1차 익절구간 전"
        if price <= target_high:
            return "1차 익절구간 진입"
        return "1차 익절구간 상단 돌파"
    return None


def eligible_values(
    row: Mapping[str, Any],
) -> Optional[Tuple[float, float, float, str]]:
    price, price_field = first_number(row, PRICE_FIELDS)
    low, _ = first_number(row, LOW_FIELDS)
    high, _ = first_number(row, HIGH_FIELDS)
    if (
        price is None
        or low is None
        or high is None
        or price_field is None
        or low <= 0
        or high <= low
    ):
        return None
    return price, low, high, price_field


def update_row(row: MutableMapping[str, Any]) -> Optional[str]:
    values = eligible_values(row)
    if values is None:
        return None
    price, low, high, _ = values

    raw = range_position_pct(price, low, high)
    row["current_position_pct"] = round(raw, 2)
    row["current_position"] = format_current_position(price, low, high)

    zone = format_price_zone(
        price,
        first_range(row, BUY_RANGE_FIELDS),
        first_range(row, TARGET_RANGE_FIELDS),
    )
    if zone is not None:
        row["price_zone"] = zone

    if price < low:
        return "BELOW_LOW"
    if price > high:
        return "ABOVE_HIGH"
    return "IN_RANGE"


def update_columns(payload: MutableMapping[str, Any]) -> None:
    columns = payload.get("columns")
    if not isinstance(columns, list):
        return
    for field in ("current_position", "current_position_pct", "price_zone"):
        if field not in columns:
            columns.append(field)


def iter_text(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from iter_text(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from iter_text(nested)


def compact_summary(summary: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "version": VERSION,
        "status": summary.get("status"),
        "files_checked": summary.get("files_checked"),
        "eligible_rows": summary.get("eligible_rows"),
        "below_low_rows": summary.get("below_low_rows"),
        "above_high_rows": summary.get("above_high_rows"),
        "error_count": summary.get("error_count"),
    }


def audit_api_directory(
    api_dir: Path,
    *,
    write_report: bool = False,
) -> Dict[str, Any]:
    api_dir = Path(api_dir)
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    files_checked = eligible_rows = 0
    below_low_rows = above_high_rows = in_range_rows = 0

    for path in sorted(api_dir.glob("*.json")):
        if path.name == REPORT_NAME:
            continue
        try:
            payload = read_json(path)
        except Exception as exc:
            errors.append(
                {"file": path.name, "reason": "JSON_READ", "detail": str(exc)}
            )
            continue

        rows = payload.get("rows")
        if not isinstance(rows, list):
            continue

        file_eligible = 0
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, Mapping):
                continue
            values = eligible_values(row)
            if values is None:
                continue

            file_eligible += 1
            eligible_rows += 1
            price, low, high, _ = values
            expected_pct = round(range_position_pct(price, low, high), 2)
            actual_pct = parse_number(row.get("current_position_pct"))
            expected_display = format_current_position(price, low, high)
            actual_display = str(row.get("current_position") or "").strip()

            if actual_pct is None or abs(actual_pct - expected_pct) > 0.02:
                errors.append({
                    "file": path.name,
                    "row": index,
                    "reason": "PERCENT_MISMATCH",
                    "expected": expected_pct,
                    "actual": actual_pct,
                })
            if actual_display != expected_display:
                errors.append({
                    "file": path.name,
                    "row": index,
                    "reason": "DISPLAY_MISMATCH",
                    "expected": expected_display,
                    "actual": actual_display,
                })

            expected_zone = format_price_zone(
                price,
                first_range(row, BUY_RANGE_FIELDS),
                first_range(row, TARGET_RANGE_FIELDS),
            )
            if (
                expected_zone is not None
                and row.get("price_zone") != expected_zone
            ):
                errors.append({
                    "file": path.name,
                    "row": index,
                    "reason": "PRICE_ZONE_MISMATCH",
                    "expected": expected_zone,
                    "actual": row.get("price_zone"),
                })

            if price < low:
                below_low_rows += 1
                if expected_pct >= 0:
                    errors.append({
                        "file": path.name,
                        "row": index,
                        "reason": "BELOW_LOW_NOT_NEGATIVE",
                    })
            elif price > high:
                above_high_rows += 1
                if expected_pct <= 100:
                    errors.append({
                        "file": path.name,
                        "row": index,
                        "reason": "ABOVE_HIGH_NOT_OVER_100",
                    })
            else:
                in_range_rows += 1
                if not 0 <= expected_pct <= 100:
                    errors.append({
                        "file": path.name,
                        "row": index,
                        "reason": "IN_RANGE_PERCENT_INVALID",
                    })

            for text in iter_text(row):
                for pattern in FORBIDDEN_PATTERNS:
                    if pattern.search(text):
                        errors.append({
                            "file": path.name,
                            "row": index,
                            "reason": "FORBIDDEN_DISPLAY",
                            "text": text,
                        })

        if file_eligible:
            files_checked += 1
            policy = payload.get("price_position_policy")
            if not isinstance(policy, Mapping):
                errors.append({
                    "file": path.name,
                    "reason": "POLICY_MISSING",
                })
            elif policy.get("version") != VERSION:
                errors.append({
                    "file": path.name,
                    "reason": "POLICY_VERSION_MISMATCH",
                    "actual": policy.get("version"),
                })
            elif policy.get("clamp_to_zero_hundred") is not False:
                errors.append({
                    "file": path.name,
                    "reason": "CLAMP_POLICY_INVALID",
                })

    if eligible_rows == 0:
        warnings.append({
            "reason": "NO_ELIGIBLE_ROWS",
            "detail": "No rows with static_price/low_3m/high_3m were found.",
        })

    summary = {
        "version": VERSION,
        "generated_at_kst": kst_now().isoformat(timespec="seconds"),
        "status": "PASS" if not errors else "FAIL",
        "files_checked": files_checked,
        "eligible_rows": eligible_rows,
        "below_low_rows": below_low_rows,
        "above_high_rows": above_high_rows,
        "in_range_rows": in_range_rows,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors[:100],
        "warnings": warnings[:100],
    }
    if write_report:
        write_json(api_dir / REPORT_NAME, summary)
    return summary


def apply_price_position_v78(
    repo_root: Path | str = ".",
    *,
    api_dir: Optional[Path | str] = None,
) -> Dict[str, Any]:
    root = Path(repo_root).resolve()
    api = Path(api_dir).resolve() if api_dir is not None else root / "api"
    if not api.exists():
        raise FileNotFoundError(api)

    modified_files = modified_rows = 0
    below_low_rows = above_high_rows = in_range_rows = 0

    for path in sorted(api.glob("*.json")):
        if path.name == REPORT_NAME:
            continue
        payload = read_json(path)
        rows = payload.get("rows")
        changed = False
        file_modified_rows = 0

        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, MutableMapping):
                    continue
                state = update_row(row)
                if state is None:
                    continue
                changed = True
                file_modified_rows += 1
                modified_rows += 1
                if state == "BELOW_LOW":
                    below_low_rows += 1
                elif state == "ABOVE_HIGH":
                    above_high_rows += 1
                else:
                    in_range_rows += 1

        if file_modified_rows:
            update_columns(payload)
            payload["price_position_policy"] = PRICE_POSITION_POLICY
            payload["price_position_version"] = VERSION
            contract = payload.get("output_contract")
            if isinstance(contract, MutableMapping):
                contract["price_position_policy_version"] = VERSION
                contract[
                    "request_time_position_recalculation_required"
                ] = True
            changed = True

        if path.name in {
            "status.json",
            "manifest.json",
            "stock_table_rules.json",
        }:
            payload["price_position_policy"] = PRICE_POSITION_POLICY
            payload["price_position_version"] = VERSION
            changed = True

        if changed:
            write_json(path, payload)
            modified_files += 1

    audit = audit_api_directory(api, write_report=True)
    if audit["status"] != "PASS":
        raise PricePositionError(
            "V7.8 validation failed: "
            + json.dumps(audit["errors"][:10], ensure_ascii=False)
        )

    compact = compact_summary(audit)
    for name in (
        "status.json",
        "manifest.json",
        "validation_report.json",
    ):
        path = api / name
        if not path.exists():
            continue
        payload = read_json(path)
        payload["price_position_validation"] = compact
        payload["price_position_version"] = VERSION
        write_json(path, payload)

    return {
        **audit,
        "modified_files": modified_files,
        "modified_rows": modified_rows,
        "below_low_rows": below_low_rows,
        "above_high_rows": above_high_rows,
        "in_range_rows": in_range_rows,
        "report_file": str(api / REPORT_NAME),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--api-dir", default=None)
    args = parser.parse_args()

    result = apply_price_position_v78(
        args.repo_root,
        api_dir=args.api_dir,
    )
    print("PRICE_POSITION_V78=PASS")
    print(f"VERSION={VERSION}")
    print(f"MODIFIED_FILES={result['modified_files']}")
    print(f"MODIFIED_ROWS={result['modified_rows']}")
    print(f"BELOW_LOW_ROWS={result['below_low_rows']}")
    print(f"ABOVE_HIGH_ROWS={result['above_high_rows']}")
    print(f"IN_RANGE_ROWS={result['in_range_rows']}")
    print(f"REPORT_FILE={result['report_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
