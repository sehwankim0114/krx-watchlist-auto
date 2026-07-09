#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V7.6.1: compact row-level financial status metadata without losing data."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SECTOR = ROOT / "apply_kr_sector_theme_v72.py"
HEALTH = ROOT / "validate_daily_integrated_health_v731.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"

VERSION = "2026-07-10-v7.6.1-financial-payload-compact"
SECTOR_BEGIN = "# FINANCIAL_PAYLOAD_COMPACT_V761_BEGIN"
SECTOR_END = "# FINANCIAL_PAYLOAD_COMPACT_V761_END"
HEALTH_BEGIN = "# FINANCIAL_VALUATION_HEALTH_V76_BEGIN"
HEALTH_END = "# FINANCIAL_VALUATION_HEALTH_V76_END"
RULES_MARKER = "<!-- FINANCIAL_PAYLOAD_COMPACT_V761 -->"


class PatchError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label} 기준점 오류: {count}")
    return text.replace(old, new, 1)


SECTOR_HELPERS = r'''
# FINANCIAL_PAYLOAD_COMPACT_V761_BEGIN
FINANCIAL_PAYLOAD_COMPACT_VERSION = (
    "2026-07-10-v7.6.1-financial-payload-compact"
)
FINANCIAL_ROW_STATUS_FIELDS = (
    "financial_data_status",
    "valuation_data_status",
)
FINANCIAL_ROW_BASIS_FIELDS = (
    "financial_basis",
    "valuation_price_basis_date",
)
FINANCIAL_ROW_COMPACT_FIELDS = (
    *FINANCIAL_ROW_STATUS_FIELDS,
    *FINANCIAL_ROW_BASIS_FIELDS,
)


def _status_counts(
    rows: List[MutableMapping[str, Any]],
    field: str,
) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        value = str(row.get(field) or "").strip() or "MISSING"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def compact_financial_status_metadata(
    payload: MutableMapping[str, Any],
    rows: List[MutableMapping[str, Any]],
) -> None:
    financial_counts = _status_counts(rows, "financial_data_status")
    valuation_counts = _status_counts(rows, "valuation_data_status")
    financial_basis_coverage = sum(
        1
        for row in rows
        if str(row.get("financial_basis") or "").strip()
    )
    valuation_basis_coverage = sum(
        1
        for row in rows
        if str(row.get("valuation_price_basis_date") or "").strip()
    )

    for row in rows:
        for field in FINANCIAL_ROW_COMPACT_FIELDS:
            row.pop(field, None)

    columns = payload.get("columns")
    if isinstance(columns, list):
        payload["columns"] = [
            field
            for field in columns
            if field not in FINANCIAL_ROW_COMPACT_FIELDS
        ]

    payload["financial_status_counts"] = financial_counts
    payload["valuation_status_counts"] = valuation_counts
    payload["financial_basis_coverage_count"] = (
        financial_basis_coverage
    )
    payload["valuation_basis_coverage_count"] = (
        valuation_basis_coverage
    )
    payload["financial_payload_compact_version"] = (
        FINANCIAL_PAYLOAD_COMPACT_VERSION
    )

    policy = payload.get("financial_valuation_link_policy")
    if isinstance(policy, MutableMapping):
        row_fields = policy.get("row_fields")
        if isinstance(row_fields, list):
            policy["row_fields"] = [
                field
                for field in row_fields
                if field not in FINANCIAL_ROW_COMPACT_FIELDS
            ]
        policy["status_storage"] = "payload_level_counts"
        policy["basis_storage"] = "payload_level_summary"
        policy["status_count_fields"] = [
            "financial_status_counts",
            "valuation_status_counts",
        ]

    compact_policy = payload.get("compact_response_policy")
    if isinstance(compact_policy, MutableMapping):
        compact_policy["financial_status_storage"] = (
            "payload_level_counts"
        )
        compact_policy["financial_status_count_fields"] = [
            "financial_status_counts",
            "valuation_status_counts",
        ]
# FINANCIAL_PAYLOAD_COMPACT_V761_END
'''


HEALTH_BLOCK = r'''        # FINANCIAL_VALUATION_HEALTH_V76_BEGIN
        if spec["market"] == "KR":
            total_rows = len(rows)
            minimum_financial_rows = max(1, int(total_rows * 0.60 + 0.999))
            minimum_growth_rows = max(1, int(total_rows * 0.50 + 0.999))
            minimum_valuation_rows = max(1, int(total_rows * 0.50 + 0.999))

            financial_counts = payload.get("financial_status_counts")
            financial_status_total = (
                sum(
                    int(value)
                    for value in financial_counts.values()
                )
                if isinstance(financial_counts, Mapping)
                else 0
            )
            if financial_status_total == total_rows:
                report.pass_check(
                    f"{table_id}_financial_status_coverage",
                    f"{table_id} 재무수집 상태 집계가 전 행과 일치합니다.",
                    {
                        "counts": financial_counts,
                        "total": total_rows,
                    },
                )
            else:
                report.fail(
                    f"{table_id}_financial_status_coverage",
                    f"{table_id} 재무수집 상태 집계가 행 수와 다릅니다.",
                    {
                        "counts": financial_counts,
                        "count_total": financial_status_total,
                        "total": total_rows,
                    },
                )

            financial_basis_coverage = int(
                payload.get("financial_basis_coverage_count") or 0
            )
            financial_basis_values = payload.get(
                "financial_basis_values"
            )
            if (
                financial_basis_coverage >= minimum_financial_rows
                and isinstance(financial_basis_values, list)
                and bool(financial_basis_values)
            ):
                report.pass_check(
                    f"{table_id}_financial_basis_coverage",
                    f"{table_id} 재무기준 연결률이 최소 기준 이상입니다.",
                    {
                        "covered": financial_basis_coverage,
                        "total": total_rows,
                        "minimum": minimum_financial_rows,
                        "basis_values": financial_basis_values,
                    },
                )
            else:
                report.fail(
                    f"{table_id}_financial_basis_coverage",
                    f"{table_id} 재무기준 연결률이 부족합니다.",
                    {
                        "covered": financial_basis_coverage,
                        "total": total_rows,
                        "minimum": minimum_financial_rows,
                        "basis_values": financial_basis_values,
                    },
                )

            growth_rows = [
                index
                for index, row in enumerate(rows, start=1)
                if isinstance(row, Mapping)
                and (
                    row.get("revenue_yoy_pct") is not None
                    or row.get("operating_profit_yoy_pct") is not None
                )
            ]
            if len(growth_rows) >= minimum_growth_rows:
                report.pass_check(
                    f"{table_id}_financial_growth_coverage",
                    f"{table_id} 재무증감률 연결률이 최소 기준 이상입니다.",
                    {
                        "covered": len(growth_rows),
                        "total": total_rows,
                        "minimum": minimum_growth_rows,
                    },
                )
            else:
                report.fail(
                    f"{table_id}_financial_growth_coverage",
                    f"{table_id} 재무증감률 연결률이 부족합니다.",
                    {
                        "covered": len(growth_rows),
                        "total": total_rows,
                        "minimum": minimum_growth_rows,
                    },
                )

            valuation_counts = payload.get("valuation_status_counts")
            valuation_status_total = (
                sum(
                    int(value)
                    for value in valuation_counts.values()
                )
                if isinstance(valuation_counts, Mapping)
                else 0
            )
            valuation_basis_coverage = int(
                payload.get("valuation_basis_coverage_count") or 0
            )
            valuation_basis_min = payload.get(
                "valuation_basis_date_min"
            )
            valuation_basis_max = payload.get(
                "valuation_basis_date_max"
            )
            pbr_rows = [
                index
                for index, row in enumerate(rows, start=1)
                if isinstance(row, Mapping) and row.get("pbr") is not None
            ]
            if (
                valuation_status_total == total_rows
                and valuation_basis_coverage >= minimum_valuation_rows
                and bool(valuation_basis_min)
                and bool(valuation_basis_max)
                and len(pbr_rows) >= minimum_valuation_rows
            ):
                report.pass_check(
                    f"{table_id}_valuation_coverage",
                    f"{table_id} 밸류에이션 상태·기준일·PBR 연결이 정상입니다.",
                    {
                        "status_counts": valuation_counts,
                        "basis_date": valuation_basis_coverage,
                        "basis_min": valuation_basis_min,
                        "basis_max": valuation_basis_max,
                        "pbr": len(pbr_rows),
                        "total": total_rows,
                    },
                )
            else:
                report.fail(
                    f"{table_id}_valuation_coverage",
                    f"{table_id} 밸류에이션 연결이 불완전합니다.",
                    {
                        "status_counts": valuation_counts,
                        "status_total": valuation_status_total,
                        "basis_date": valuation_basis_coverage,
                        "basis_min": valuation_basis_min,
                        "basis_max": valuation_basis_max,
                        "pbr": len(pbr_rows),
                        "total": total_rows,
                        "minimum": minimum_valuation_rows,
                    },
                )

            invalid_per_rows = []
            for index, row in enumerate(rows, start=1):
                if not isinstance(row, Mapping):
                    continue
                per_value = row.get("per_annualized")
                if per_value is None:
                    continue
                try:
                    if float(per_value) <= 0:
                        invalid_per_rows.append(index)
                except (TypeError, ValueError):
                    invalid_per_rows.append(index)
            if invalid_per_rows:
                report.fail(
                    f"{table_id}_per_loss_policy",
                    f"{table_id}에 0 이하 또는 비정상 PER 값이 있습니다.",
                    {"rows": invalid_per_rows},
                )
            else:
                report.pass_check(
                    f"{table_id}_per_loss_policy",
                    f"{table_id} 적자기업 PER 공란 정책이 정상입니다.",
                )
        # FINANCIAL_VALUATION_HEALTH_V76_END
'''


def patch_sector() -> None:
    if not SECTOR.exists():
        raise FileNotFoundError(SECTOR)

    text = SECTOR.read_text(encoding="utf-8")

    if SECTOR_BEGIN not in text:
        anchor = "def ensure_columns("
        if text.count(anchor) != 1:
            raise PatchError(
                f"sector helper 기준점 오류: {text.count(anchor)}"
            )
        text = text.replace(
            anchor,
            SECTOR_HELPERS.strip() + "\n\n\n" + anchor,
            1,
        )

    call = "    compact_financial_status_metadata(payload, rows)\n"
    if call not in text:
        anchor = "    coverage_pct = round(matched / exact_rows * 100.0, 2)\n"
        text = replace_once(
            text,
            anchor,
            call + "\n" + anchor,
            "financial compact call",
        )

    required = (
        SECTOR_BEGIN,
        SECTOR_END,
        "compact_financial_status_metadata(payload, rows)",
        '"financial_status_counts"',
        '"valuation_status_counts"',
    )
    for token in required:
        if token not in text:
            raise PatchError(f"sector 필수 토큰 누락: {token}")

    SECTOR.write_text(text, encoding="utf-8")


def patch_health() -> None:
    if not HEALTH.exists():
        raise FileNotFoundError(HEALTH)

    text = HEALTH.read_text(encoding="utf-8")
    text, version_count = re.subn(
        r'CHECKER_VERSION\s*=\s*"[^"]+"',
        'CHECKER_VERSION = '
        '"2026-07-10-v7.6.1-financial-payload-health"',
        text,
        count=1,
    )
    if version_count != 1:
        raise PatchError(
            f"health checker version 교체 수 오류: {version_count}"
        )

    pattern = re.compile(
        rf"        {re.escape(HEALTH_BEGIN)}\n"
        rf".*?"
        rf"        {re.escape(HEALTH_END)}\n",
        re.DOTALL,
    )
    text, count = pattern.subn(HEALTH_BLOCK, text, count=1)
    if count != 1:
        raise PatchError(f"health V7.6 블록 교체 수 오류: {count}")

    required = (
        "financial_status_counts",
        "valuation_status_counts",
        "financial_status_coverage",
        "financial_basis_coverage",
        "financial_growth_coverage",
        "valuation_coverage",
        "per_loss_policy",
    )
    for token in required:
        if token not in text:
            raise PatchError(f"health 필수 토큰 누락: {token}")

    HEALTH.write_text(text, encoding="utf-8")


def patch_rules() -> None:
    if not RULES.exists():
        raise FileNotFoundError(RULES)

    text = RULES.read_text(encoding="utf-8")
    text, count = re.subn(
        r'(- 규칙 버전:\s*`)[^`]+(`)',
        rf'\g<1>{VERSION}\g<2>',
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(f"규칙 버전 교체 수 오류: {count}")

    if RULES_MARKER not in text:
        text = text.rstrip() + f'''

---

## 20. 재무 상태 메타데이터 압축 V7.6.1

{RULES_MARKER}

- 매출·영업이익 증감률, 재무기준, 밸류 기준일, PER·PBR은
  종목별 행에 유지한다.
- `financial_data_status`, `valuation_data_status`는 후보 원본과
  재무 캐시에 유지하되 compact Action 응답에서는 종목별 반복을
  제거하고 표 상단의 상태별 개수 집계로 저장한다.
- 종목별 `financial_basis`, `valuation_price_basis_date`도 원본에
  유지하고 compact 응답에서는 고유 재무기준 목록과 밸류기준
  최소·최대일 및 연결행 수로 한 번만 저장한다.
- 매출·영업이익 증감률, 이익흐름, PER·PBR은 종목별로 유지한다.
- 코피 응답은 70,000바이트, 코닥 응답은 50,000바이트 이내를
  유지한다.
''' + "\n"

    RULES.write_text(text, encoding="utf-8")


def verify() -> None:
    sector = SECTOR.read_text(encoding="utf-8")
    health = HEALTH.read_text(encoding="utf-8")
    rules = RULES.read_text(encoding="utf-8")

    checks = {
        "sector_begin": SECTOR_BEGIN in sector,
        "sector_call": (
            "compact_financial_status_metadata(payload, rows)" in sector
        ),
        "status_counts": (
            '"financial_status_counts"' in sector
            and '"valuation_status_counts"' in sector
        ),
        "health_aggregate": (
            "financial_status_counts" in health
            and "valuation_status_counts" in health
        ),
        "rules_version": VERSION in rules,
        "rules_marker": RULES_MARKER in rules,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise PatchError(f"V7.6.1 검증 실패: {failed}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if not args.verify_only:
        patch_sector()
        patch_health()
        patch_rules()

    verify()
    print("PATCH_FINANCIAL_PAYLOAD_COMPACT_V761=OK")
    print(f"RULES_VERSION={VERSION}")
    print("ROW_STATUS_FIELDS=REMOVED_FROM_COMPACT_ONLY")
    print("STATUS_STORAGE=PAYLOAD_LEVEL_COUNTS")
    print("MAX_KOSPI_PAYLOAD_BYTES=70000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
