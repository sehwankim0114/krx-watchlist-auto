#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V7.3 daily integrated health check for krx-watchlist-auto.

Checks:
- synchronized status and rules hash
- exact 30/10/30 compact watchlist rows
- Korean sector/theme 100% coverage
- Markdown buy/target fields
- compact Action payload sizes
- validation report
- Cloudflare Worker health and compact manifest
- non-blocking display-quality warnings
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

SCHEMA_VERSION = "1.0"
CHECKER_VERSION = "2026-08-29-v8.4.0-worker-v138-health-alignment"
DEFAULT_WORKER_BASE = "https://krx-live-price-ksh.diaconos.workers.dev"
EXPECTED_WORKER_BUILD_PREFIX = "1.3.8-"
DEFAULT_MAX_WATCHLIST_BYTES = 90000
MAX_COMPACT_MANIFEST_BYTES = 65000
KRX_SECTOR_SOURCE = "KRX_KIND_LISTED_COMPANY"
ALLOWED_TRADING_ACTIVITY = {
    "매우활발",
    "활발",
    "보통",
    "부족",
    "매우부족",
}
ALLOWED_PRICE_ELASTICITY = {
    "탄력 불안정",
    "탄력 높음",
    "탄력 보통",
    "탄력 낮음",
}

TABLE_SPECS = (
    {
        "table_id": "kospi_watchlist",
        "filename": "kospi_watchlist.json",
        "expected_rows": 30,
        "market": "KR",
        "max_payload_bytes": 90000,
    },
    {
        "table_id": "kosdaq_watchlist",
        "filename": "kosdaq_watchlist.json",
        "expected_rows": 10,
        "market": "KR",
        "max_payload_bytes": 50000,
    },
    {
        "table_id": "us_watchlist",
        "filename": "us_watchlist.json",
        "expected_rows": 30,
        "market": "US",
        "max_payload_bytes": 110000,
    },
)

DISPLAY_DUPLICATE_PATTERNS = (
    re.compile(r"\bCB\s*/\s*CB발행\b", re.IGNORECASE),
    re.compile(r"\bBW\s*/\s*BW발행\b", re.IGNORECASE),
    re.compile(r"(대량보유)(?:\s*[·,/]\s*\1)+"),
    re.compile(r"(주요주주변동)(?:\s*[·,/]\s*\1)+"),
)


class HealthCheckError(RuntimeError):
    """Raised for an unrecoverable checker error."""


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def iso_kst() -> str:
    return kst_now().isoformat(timespec="seconds")


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise HealthCheckError(f"필수 JSON 누락: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HealthCheckError(f"JSON 읽기 실패: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise HealthCheckError(f"JSON 최상위 객체 형식 아님: {path}")
    return payload


def first_defined(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def nested_get(value: Any, path: Sequence[str], default: Any = None) -> Any:
    current = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return default
        current = current[key]
    return current


def normalize_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "ok", "pass", "1"}:
            return True
        if lowered in {"false", "no", "fail", "0"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def normalize_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d-]", "", value)
        if digits:
            try:
                return int(digits)
            except ValueError:
                return None
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_table_entry(manifest: Mapping[str, Any], table_id: str) -> Optional[Mapping[str, Any]]:
    tables = manifest.get("tables")
    if not isinstance(tables, list):
        return None
    for item in tables:
        if not isinstance(item, Mapping):
            continue
        if item.get("table_id") == table_id:
            return item
        api_file = str(item.get("api_file") or "")
        if api_file.endswith(f"/{table_id}.json") or api_file.endswith(f"{table_id}.json"):
            return item
    return None


def row_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from row_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from row_strings(nested)


def has_markdown_range(row: Mapping[str, Any], field: str) -> bool:
    value = row.get(field)
    return (
        isinstance(value, str)
        and value.startswith("**")
        and value.endswith("**")
        and "~" in value
    )


def fetch_json(
    url: str,
    *,
    timeout: int = 20,
    attempts: int = 3,
) -> Tuple[Dict[str, Any], int, Mapping[str, str]]:
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "krx-watchlist-health-v7.3",
                "Cache-Control": "no-cache",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("response JSON is not an object")
                headers = {key.lower(): value for key, value in response.headers.items()}
                return payload, len(body), headers
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise HealthCheckError(f"원격 JSON 조회 실패: {url}: {last_error}")


def expected_trading_activity(value: Any) -> Optional[str]:
    try:
        number = abs(float(value))
    except (TypeError, ValueError):
        return None
    if number >= 100_000_000_000:
        return "매우활발"
    if number >= 30_000_000_000:
        return "활발"
    if number >= 5_000_000_000:
        return "보통"
    if number >= 1_000_000_000:
        return "부족"
    return "매우부족"


def expected_price_elasticity(value: Any) -> Optional[str]:
    try:
        number = abs(float(value))
    except (TypeError, ValueError):
        return None
    if number >= 5.0:
        return "탄력 불안정"
    if number >= 3.0:
        return "탄력 높음"
    if number >= 1.5:
        return "탄력 보통"
    return "탄력 낮음"


class HealthReport:
    def __init__(self) -> None:
        self.checks: List[Dict[str, Any]] = []
        self.context: Dict[str, Any] = {}

    def add(
        self,
        check_id: str,
        passed: bool,
        message: str,
        *,
        severity: str = "ERROR",
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        severity = severity.upper()
        status = "PASS" if passed else ("WARN" if severity == "WARNING" else "FAIL")
        item: Dict[str, Any] = {
            "check_id": check_id,
            "status": status,
            "severity": severity,
            "message": message,
        }
        if details:
            item["details"] = dict(details)
        self.checks.append(item)

    def pass_check(
        self,
        check_id: str,
        message: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.add(check_id, True, message, details=details)

    def fail(
        self,
        check_id: str,
        message: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.add(check_id, False, message, severity="ERROR", details=details)

    def warn(
        self,
        check_id: str,
        message: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.add(check_id, False, message, severity="WARNING", details=details)

    @property
    def critical_count(self) -> int:
        return sum(1 for item in self.checks if item["status"] == "FAIL")

    @property
    def warning_count(self) -> int:
        return sum(1 for item in self.checks if item["status"] == "WARN")

    @property
    def status(self) -> str:
        if self.critical_count:
            return "FAIL"
        if self.warning_count:
            return "WARN"
        return "PASS"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "checker_version": CHECKER_VERSION,
            "generated_at_kst": iso_kst(),
            "status": self.status,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "context": self.context,
            "checks": self.checks,
        }


def validate_local_repository(
    root: Path,
    report: HealthReport,
) -> Dict[str, Any]:
    api_dir = root / "api"
    docs_dir = root / "docs"
    latest_dir = root / "latest"

    required_files = [
        api_dir / "status.json",
        api_dir / "manifest.json",
        api_dir / "validation_report.json",
        api_dir / "kospi_watchlist.json",
        api_dir / "kosdaq_watchlist.json",
        api_dir / "us_watchlist.json",
        docs_dir / "stock_table_rules_latest.md",
    ]
    missing = [str(path.relative_to(root)) for path in required_files if not path.exists()]
    if missing:
        report.fail(
            "required_files",
            "필수 파일이 누락됐습니다.",
            {"missing": missing},
        )
        raise HealthCheckError("필수 파일 누락")
    report.pass_check("required_files", "필수 API·규칙 파일이 모두 존재합니다.")

    status = read_json(api_dir / "status.json")
    manifest = read_json(api_dir / "manifest.json")
    validation = read_json(api_dir / "validation_report.json")

    build_id = first_defined(status.get("build_id"), manifest.get("build_id"))
    rules_version = first_defined(
        status.get("rules_version"),
        manifest.get("rules_version"),
        nested_get(manifest, ("rules", "version")),
    )
    rules_sha256 = first_defined(
        status.get("rules_sha256"),
        manifest.get("rules_sha256"),
        nested_get(manifest, ("rules", "sha256")),
    )
    report.context.update(
        {
            "build_id": build_id,
            "rules_version": rules_version,
            "rules_sha256": rules_sha256,
            "source_commit_sha": first_defined(
                status.get("source_commit_sha"),
                manifest.get("source_commit_sha"),
            ),
            "payload_limits_bytes": {
                str(spec["table_id"]): int(
                    spec.get(
                        "max_payload_bytes",
                        DEFAULT_MAX_WATCHLIST_BYTES,
                    )
                )
                for spec in TABLE_SPECS
            },
        }
    )

    for field in (
        "api_sync_ok",
        "official_fresh_now",
        "safe_to_analyze_as_latest",
    ):
        value = normalize_bool(status.get(field))
        if value is True:
            report.pass_check(f"status_{field}", f"{field}=true")
        else:
            report.fail(
                f"status_{field}",
                f"{field}가 true가 아닙니다.",
                {"actual": status.get(field)},
            )

    validation_status = str(validation.get("status") or "").upper()
    if validation_status == "PASS":
        report.pass_check("validation_report", "validation_report.json 상태가 PASS입니다.")
    else:
        report.fail(
            "validation_report",
            "validation_report.json 상태가 PASS가 아닙니다.",
            {"actual": validation.get("status")},
        )

    rules_path = docs_dir / "stock_table_rules_latest.md"
    actual_rules_sha = sha256_file(rules_path)
    if rules_sha256 and actual_rules_sha == rules_sha256:
        report.pass_check("rules_sha256", "규칙 파일 SHA-256이 status/manifest와 일치합니다.")
    elif rules_sha256:
        report.fail(
            "rules_sha256",
            "규칙 파일 SHA-256이 status/manifest와 다릅니다.",
            {"expected": rules_sha256, "actual": actual_rules_sha},
        )
    else:
        report.warn("rules_sha256", "status/manifest에 규칙 SHA-256이 없습니다.")

    rules_text = rules_path.read_text(encoding="utf-8")
    if rules_version and str(rules_version) in rules_text:
        report.pass_check("rules_version_text", "규칙 문서에 현재 규칙 버전이 표시됩니다.")
    else:
        report.fail(
            "rules_version_text",
            "규칙 문서에서 현재 규칙 버전을 찾지 못했습니다.",
            {"rules_version": rules_version},
        )

    table_payloads: Dict[str, Dict[str, Any]] = {}

    for spec in TABLE_SPECS:
        table_id = spec["table_id"]
        path = api_dir / spec["filename"]
        payload = read_json(path)
        table_payloads[table_id] = payload
        rows = payload.get("rows")
        if not isinstance(rows, list):
            report.fail(f"{table_id}_rows", "rows가 배열이 아닙니다.")
            continue

        actual_rows = len(rows)
        expected_rows = int(spec["expected_rows"])
        if actual_rows == expected_rows:
            report.pass_check(
                f"{table_id}_rows",
                f"{table_id} 행 수가 {expected_rows}개로 정상입니다.",
            )
        else:
            report.fail(
                f"{table_id}_rows",
                f"{table_id} 행 수가 예상과 다릅니다.",
                {"expected": expected_rows, "actual": actual_rows},
            )

        file_bytes = path.stat().st_size
        payload_limit = int(
            spec.get(
                "max_payload_bytes",
                DEFAULT_MAX_WATCHLIST_BYTES,
            )
        )
        if file_bytes <= payload_limit:
            report.pass_check(
                f"{table_id}_payload_size",
                f"{table_id} 응답 크기가 시장별 안전 범위입니다.",
                {
                    "bytes": file_bytes,
                    "limit": payload_limit,
                    "market": spec.get("market"),
                },
            )
        else:
            report.fail(
                f"{table_id}_payload_size",
                f"{table_id} 응답 크기가 시장별 제한을 넘었습니다.",
                {
                    "bytes": file_bytes,
                    "limit": payload_limit,
                    "market": spec.get("market"),
                },
            )

        payload_build = payload.get("build_id")
        if build_id and payload_build and payload_build != build_id:
            report.fail(
                f"{table_id}_build_id",
                f"{table_id} 빌드 ID가 status와 다릅니다.",
                {"status": build_id, "table": payload_build},
            )
        else:
            report.pass_check(
                f"{table_id}_build_id",
                f"{table_id} 빌드 ID가 일치하거나 상위 검증값을 사용합니다.",
            )

        payload_rules = payload.get("rules_version")
        if rules_version and payload_rules and payload_rules != rules_version:
            report.fail(
                f"{table_id}_rules_version",
                f"{table_id} 규칙 버전이 status와 다릅니다.",
                {"status": rules_version, "table": payload_rules},
            )
        else:
            report.pass_check(
                f"{table_id}_rules_version",
                f"{table_id} 규칙 버전이 일치하거나 상위 검증값을 사용합니다.",
            )

        buy_missing = [
            index
            for index, row in enumerate(rows, start=1)
            if not isinstance(row, Mapping)
            or not has_markdown_range(row, "value_buy_range_markdown")
        ]
        target_missing = [
            index
            for index, row in enumerate(rows, start=1)
            if not isinstance(row, Mapping)
            or not has_markdown_range(row, "first_sell_target_range_markdown")
        ]
        if not buy_missing and not target_missing:
            report.pass_check(
                f"{table_id}_bold_ranges",
                f"{table_id}의 매수·익절 Markdown 가격범위가 모두 정상입니다.",
            )
        else:
            report.fail(
                f"{table_id}_bold_ranges",
                f"{table_id}의 Markdown 가격범위 필드가 누락됐습니다.",
                {
                    "buy_missing_rows": buy_missing,
                    "target_missing_rows": target_missing,
                },
            )

        manifest_entry = find_table_entry(manifest, table_id)
        if manifest_entry is None:
            report.fail(
                f"{table_id}_manifest_entry",
                f"manifest에서 {table_id} 항목을 찾지 못했습니다.",
            )
        else:
            manifest_rows = normalize_int(manifest_entry.get("row_count"))
            manifest_status = str(manifest_entry.get("status") or "").upper()
            if manifest_rows == expected_rows and manifest_status == "OK":
                report.pass_check(
                    f"{table_id}_manifest_entry",
                    f"manifest의 {table_id} 행 수와 상태가 정상입니다.",
                )
            else:
                report.fail(
                    f"{table_id}_manifest_entry",
                    f"manifest의 {table_id} 행 수 또는 상태가 비정상입니다.",
                    {
                        "row_count": manifest_entry.get("row_count"),
                        "status": manifest_entry.get("status"),
                    },
                )

        if spec["market"] == "KR":
            sector_values = [
                row.get("sector_theme")
                for row in rows
                if isinstance(row, Mapping)
            ]
            missing_sector = [
                index
                for index, value in enumerate(sector_values, start=1)
                if not isinstance(value, str)
                or not value.strip()
                or value.strip() == "자료 미제공"
            ]
            coverage = payload.get("sector_theme_coverage_pct")
            source = payload.get("sector_theme_source")
            if not missing_sector and float(coverage or 0) == 100.0:
                report.pass_check(
                    f"{table_id}_sector_coverage",
                    f"{table_id} 섹터/테마가 100% 연결됐습니다.",
                )
            else:
                report.fail(
                    f"{table_id}_sector_coverage",
                    f"{table_id} 섹터/테마 연결이 불완전합니다.",
                    {
                        "coverage_pct": coverage,
                        "missing_rows": missing_sector,
                    },
                )
            if source == KRX_SECTOR_SOURCE:
                report.pass_check(
                    f"{table_id}_sector_source",
                    f"{table_id} 섹터 출처가 KRX KIND입니다.",
                )
            else:
                report.fail(
                    f"{table_id}_sector_source",
                    f"{table_id} 섹터 출처가 예상과 다릅니다.",
                    {"actual": source},
                )

            contract = payload.get("output_contract")
            label = (
                contract.get("average_volume_per_minute_value_column_label")
                if isinstance(contract, Mapping)
                else None
            )
            if label == "평균거래량·분당거래금":
                report.pass_check(
                    f"{table_id}_trading_column_label",
                    f"{table_id} 거래 열 이름이 정상입니다.",
                )
            else:
                report.fail(
                    f"{table_id}_trading_column_label",
                    f"{table_id} 거래 열 이름이 예상과 다릅니다.",
                    {"actual": label},
                )

            per_minute_missing = [
                index
                for index, row in enumerate(rows, start=1)
                if not isinstance(row, Mapping)
                or row.get("avg_trading_value_per_minute_krw") is None
                or not row.get("avg_trading_value_per_minute_display")
            ]
            if not per_minute_missing:
                report.pass_check(
                    f"{table_id}_per_minute_value",
                    f"{table_id} 분당거래금 필드가 모두 존재합니다.",
                )
            else:
                report.fail(
                    f"{table_id}_per_minute_value",
                    f"{table_id} 분당거래금 필드가 누락됐습니다.",
                    {"missing_rows": per_minute_missing},
                )

            activity_failures = []
            elasticity_failures = []
            for index, row in enumerate(rows, start=1):
                if not isinstance(row, Mapping):
                    activity_failures.append(
                        {"row": index, "reason": "row_not_object"}
                    )
                    elasticity_failures.append(
                        {"row": index, "reason": "row_not_object"}
                    )
                    continue

                activity = row.get("trading_activity")
                expected_activity = expected_trading_activity(
                    row.get("avg_trading_value_krw")
                )
                if (
                    activity not in ALLOWED_TRADING_ACTIVITY
                    or (
                        expected_activity is not None
                        and activity != expected_activity
                    )
                ):
                    activity_failures.append(
                        {
                            "row": index,
                            "actual": activity,
                            "expected": expected_activity,
                        }
                    )

                elasticity = row.get("price_elasticity")
                expected_elasticity = expected_price_elasticity(
                    row.get("price_elasticity_pct")
                )
                if (
                    elasticity not in ALLOWED_PRICE_ELASTICITY
                    or (
                        expected_elasticity is not None
                        and elasticity != expected_elasticity
                    )
                ):
                    elasticity_failures.append(
                        {
                            "row": index,
                            "actual": elasticity,
                            "expected": expected_elasticity,
                            "pct": row.get("price_elasticity_pct"),
                        }
                    )

            if not activity_failures:
                report.pass_check(
                    f"{table_id}_trading_activity",
                    f"{table_id} 거래활발 등급이 전 행 정상입니다.",
                )
            else:
                report.fail(
                    f"{table_id}_trading_activity",
                    f"{table_id} 거래활발 등급이 누락되거나 기준과 다릅니다.",
                    {"failures": activity_failures},
                )

            if not elasticity_failures:
                report.pass_check(
                    f"{table_id}_price_elasticity",
                    f"{table_id} 가격탄력 등급이 전 행 정상입니다.",
                )
            else:
                report.fail(
                    f"{table_id}_price_elasticity",
                    f"{table_id} 가격탄력 등급이 누락되거나 기준과 다릅니다.",
                    {"failures": elasticity_failures},
                )

        # FINANCIAL_VALUATION_HEALTH_V76_BEGIN
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

        duplicate_hits: List[Dict[str, Any]] = []
        for row_index, row in enumerate(rows, start=1):
            if not isinstance(row, Mapping):
                continue
            for text in row_strings(row):
                for pattern in DISPLAY_DUPLICATE_PATTERNS:
                    match = pattern.search(text)
                    if match:
                        duplicate_hits.append(
                            {
                                "row": row_index,
                                "text": match.group(0),
                            }
                        )
        if duplicate_hits:
            report.warn(
                f"{table_id}_display_duplicates",
                f"{table_id}에 중복 수급표현이 있어 표시 정리가 필요합니다.",
                {"hits": duplicate_hits[:20]},
            )
        else:
            report.pass_check(
                f"{table_id}_display_duplicates",
                f"{table_id}에서 알려진 중복 수급표현이 발견되지 않았습니다.",
            )

    sector_cache_path = latest_dir / "krx_sector_theme_latest.json"
    if sector_cache_path.exists():
        sector_cache = read_json(sector_cache_path)
        row_count = normalize_int(sector_cache.get("row_count"))
        if row_count is not None and row_count >= 1500:
            report.pass_check(
                "krx_sector_cache",
                "KRX KIND 전체 섹터 캐시 행 수가 정상입니다.",
                {"row_count": row_count},
            )
        else:
            report.fail(
                "krx_sector_cache",
                "KRX KIND 전체 섹터 캐시 행 수가 부족합니다.",
                {"row_count": sector_cache.get("row_count")},
            )
    else:
        report.fail("krx_sector_cache", "KRX KIND 섹터 캐시 파일이 없습니다.")

    return {
        "status": status,
        "manifest": manifest,
        "validation": validation,
        "tables": table_payloads,
    }


def validate_worker(
    worker_base: str,
    local: Mapping[str, Any],
    report: HealthReport,
) -> None:
    base = worker_base.rstrip("/")
    health_url = f"{base}/health"
    manifest_url = (
        f"{base}/sehwankim0114/krx-watchlist-auto/main/api/manifest.json"
    )

    try:
        health, health_bytes, health_headers = fetch_json(health_url)
    except Exception as exc:
        report.fail("worker_health", "Cloudflare Worker /health 조회에 실패했습니다.", {"error": str(exc)})
        return

    health_ok = str(health.get("status") or "").upper() == "OK"
    build_version = str(health.get("build_version") or "")
    manifest_mode = nested_get(
        health,
        ("github_proxy_policy", "manifest_response_mode"),
    )
    freshness_merge = nested_get(
        health,
        ("github_proxy_policy", "manifest_freshness_merge"),
    )
    if (
        health_ok
        and build_version.startswith(EXPECTED_WORKER_BUILD_PREFIX)
        and manifest_mode == "COMPACT_FOR_CUSTOM_GPT"
        and freshness_merge == "status.json"
    ):
        report.pass_check(
            "worker_health",
            "Cloudflare Worker 상태와 매니페스트 정책이 정상입니다.",
            {
                "build_version": build_version,
                "bytes": health_bytes,
            },
        )
    else:
        report.fail(
            "worker_health",
            "Cloudflare Worker 상태 또는 정책이 예상과 다릅니다.",
            {
                "status": health.get("status"),
                "build_version": build_version,
                "manifest_response_mode": manifest_mode,
                "manifest_freshness_merge": freshness_merge,
            },
        )

    try:
        compact, compact_bytes, compact_headers = fetch_json(manifest_url)
    except Exception as exc:
        report.fail(
            "worker_compact_manifest",
            "Worker 경량 매니페스트 조회에 실패했습니다.",
            {"error": str(exc)},
        )
        return

    if compact_bytes <= MAX_COMPACT_MANIFEST_BYTES:
        report.pass_check(
            "worker_compact_manifest_size",
            "Worker 경량 매니페스트 응답 크기가 안전 범위입니다.",
            {"bytes": compact_bytes, "limit": MAX_COMPACT_MANIFEST_BYTES},
        )
    else:
        report.fail(
            "worker_compact_manifest_size",
            "Worker 경량 매니페스트가 응답 제한을 넘었습니다.",
            {"bytes": compact_bytes, "limit": MAX_COMPACT_MANIFEST_BYTES},
        )

    expected_values = {
        "manifest_mode": "COMPACT_FOR_CUSTOM_GPT",
        "api_sync_ok": True,
        "official_fresh_now": True,
        "safe_to_analyze_as_latest": True,
        "structure_ok": True,
    }
    bad_values: Dict[str, Any] = {}
    for key, expected in expected_values.items():
        actual = compact.get(key)
        normalized = normalize_bool(actual) if isinstance(expected, bool) else actual
        if normalized != expected:
            bad_values[key] = actual

    if bad_values:
        report.fail(
            "worker_compact_manifest_values",
            "경량 매니페스트의 핵심 상태값이 비정상입니다.",
            bad_values,
        )
    else:
        report.pass_check(
            "worker_compact_manifest_values",
            "경량 매니페스트의 핵심 상태값이 정상입니다.",
        )

    freshness_source = compact.get("freshness_value_source")
    if freshness_source in {"status.json", "manifest.json"}:
        report.pass_check(
            "worker_freshness_source",
            "최신성 값 출처가 확인됐습니다.",
            {"source": freshness_source},
        )
    else:
        report.fail(
            "worker_freshness_source",
            "최신성 값 출처가 확인되지 않았습니다.",
            {"source": freshness_source},
        )

    compact_tables = compact.get("tables")
    compact_table_map: Dict[str, Mapping[str, Any]] = {}
    if isinstance(compact_tables, list):
        for item in compact_tables:
            if isinstance(item, Mapping) and item.get("table_id"):
                compact_table_map[str(item["table_id"])] = item

    for spec in TABLE_SPECS:
        table_id = str(spec["table_id"])
        item = compact_table_map.get(table_id)
        if not item:
            report.fail(
                f"worker_{table_id}",
                f"경량 매니페스트에 {table_id}가 없습니다.",
            )
            continue
        row_count = normalize_int(item.get("row_count"))
        status = str(item.get("status") or "").upper()
        if row_count == spec["expected_rows"] and status == "OK":
            report.pass_check(
                f"worker_{table_id}",
                f"경량 매니페스트의 {table_id} 행 수와 상태가 정상입니다.",
            )
        else:
            report.fail(
                f"worker_{table_id}",
                f"경량 매니페스트의 {table_id}가 비정상입니다.",
                {
                    "row_count": item.get("row_count"),
                    "status": item.get("status"),
                },
            )

    local_build_id = nested_get(local, ("status", "build_id"))
    remote_build_id = compact.get("build_id")
    if local_build_id and remote_build_id and local_build_id == remote_build_id:
        report.pass_check(
            "worker_build_id",
            "Worker 경량 매니페스트 빌드 ID가 저장소와 일치합니다.",
        )
    elif local_build_id and remote_build_id:
        report.warn(
            "worker_build_id",
            "Worker 캐시의 빌드 ID가 저장소와 다릅니다. 120초 캐시 지연일 수 있습니다.",
            {"local": local_build_id, "remote": remote_build_id},
        )
    else:
        report.warn(
            "worker_build_id",
            "저장소 또는 Worker 빌드 ID를 비교할 수 없습니다.",
            {"local": local_build_id, "remote": remote_build_id},
        )


def render_markdown(payload: Mapping[str, Any]) -> str:
    status = payload.get("status")
    critical = payload.get("critical_count")
    warnings = payload.get("warning_count")
    context = payload.get("context") or {}
    checks = payload.get("checks") or []

    lines = [
        "# V7.3 일일 통합 건강검사",
        "",
        f"- 검사시각(KST): {payload.get('generated_at_kst')}",
        f"- 최종상태: **{status}**",
        f"- 치명 오류: {critical}",
        f"- 경고: {warnings}",
        f"- 빌드 ID: `{context.get('build_id')}`",
        f"- 규칙 버전: `{context.get('rules_version')}`",
        "",
        "| 결과 | 검사 항목 | 설명 |",
        "|---|---|---|",
    ]

    icons = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}
    for item in checks:
        item_status = str(item.get("status"))
        message = str(item.get("message") or "").replace("|", "\\|")
        check_id = str(item.get("check_id") or "").replace("|", "\\|")
        lines.append(
            f"| {icons.get(item_status, item_status)} | `{check_id}` | {message} |"
        )

    lines.extend(
        [
            "",
            "## 판정 기준",
            "",
            "- `PASS`: 자동 분석표 사용 가능",
            "- `WARN`: 핵심 기능은 정상이나 표시 또는 캐시 확인 필요",
            "- `FAIL`: 최신표 사용을 중단하고 실패 항목 수정 필요",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(
    report: HealthReport,
    json_path: Path,
    markdown_path: Path,
) -> Dict[str, Any]:
    payload = report.as_dict()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_markdown(payload) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--worker-base", default=DEFAULT_WORKER_BASE)
    parser.add_argument(
        "--output-json",
        default="latest/daily_integrated_health_latest.json",
    )
    parser.add_argument(
        "--output-md",
        default="latest/daily_integrated_health_latest.md",
    )
    parser.add_argument(
        "--skip-remote",
        action="store_true",
        help="Skip Cloudflare Worker checks.",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0 after writing the report.",
    )
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = HealthReport()
    local: Dict[str, Any] = {}

    try:
        local = validate_local_repository(root, report)
    except Exception as exc:
        if not any(item["status"] == "FAIL" for item in report.checks):
            report.fail("checker_local_exception", "로컬 검사 중 예외가 발생했습니다.", {"error": str(exc)})

    # PRICE_POSITION_HEALTH_V78_BEGIN
    try:
        from apply_price_position_v78 import (
            VERSION as PRICE_POSITION_VERSION,
            audit_api_directory,
        )
        price_position = audit_api_directory(
            root / "api",
            write_report=False,
        )
        if price_position.get("status") == "PASS":
            report.pass_check(
                "price_position_v78",
                "3개월 범위 이탈 위치표시가 정상입니다.",
                {
                    "version": PRICE_POSITION_VERSION,
                    "files_checked": price_position.get("files_checked"),
                    "eligible_rows": price_position.get("eligible_rows"),
                    "below_low_rows": price_position.get("below_low_rows"),
                    "above_high_rows": price_position.get("above_high_rows"),
                },
            )
        else:
            report.fail(
                "price_position_v78",
                "3개월 범위 이탈 위치표시에 모순이 있습니다.",
                {"errors": price_position.get("errors", [])[:20]},
            )
    except Exception as exc:
        report.fail(
            "price_position_v78_exception",
            "V7.8 가격위치 검사 중 예외가 발생했습니다.",
            {"error": str(exc)},
        )
    # PRICE_POSITION_HEALTH_V78_END

    # RECOMMENDATION_ICON_HEALTH_V79_BEGIN
    try:
        from apply_recommendation_icon_v79 import (
            VERSION as RECOMMENDATION_ICON_VERSION,
            audit_recommendation_icons,
        )
        recommendation_icons = audit_recommendation_icons(
            root / "api",
            write_report=False,
        )
        if recommendation_icons.get("status") == "PASS":
            report.pass_check(
                "recommendation_icon_v79",
                "추천 아이콘과 손실·수급 표시 순서가 정상입니다.",
                {
                    "version": RECOMMENDATION_ICON_VERSION,
                    "rows_checked": recommendation_icons.get("rows_checked"),
                    "icon_counts": recommendation_icons.get("icon_counts"),
                },
            )
        else:
            report.fail(
                "recommendation_icon_v79",
                "추천 아이콘 누락 또는 표시 순서 오류가 있습니다.",
                {
                    "errors": recommendation_icons.get("errors", [])[:20],
                },
            )
    except Exception as exc:
        report.fail(
            "recommendation_icon_v79_exception",
            "V7.9 추천 아이콘 검사 중 예외가 발생했습니다.",
            {"error": str(exc)},
        )
    # RECOMMENDATION_ICON_HEALTH_V79_END

    if not args.skip_remote and local:
        try:
            validate_worker(args.worker_base, local, report)
        except Exception as exc:
            report.fail(
                "checker_remote_exception",
                "원격 검사 중 예외가 발생했습니다.",
                {"error": str(exc)},
            )

    payload = write_report(
        report,
        root / args.output_json,
        root / args.output_md,
    )

    print(f"DAILY_INTEGRATED_HEALTH_V73={payload['status']}")
    print(f"CRITICAL_COUNT={payload['critical_count']}")
    print(f"WARNING_COUNT={payload['warning_count']}")
    print(f"BUILD_ID={payload['context'].get('build_id')}")
    print(f"RULES_VERSION={payload['context'].get('rules_version')}")
    print(f"OUTPUT_JSON={args.output_json}")
    print(f"OUTPUT_MD={args.output_md}")

    if args.exit_zero:
        return 0
    return 0 if payload["status"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
