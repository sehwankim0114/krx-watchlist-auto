#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V7.6: connect OpenDART financial/valuation data to KR compact tables."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILDER = ROOT / "build_lightweight_watchlist_api_v66.py"
HEALTH = ROOT / "validate_daily_integrated_health_v731.py"
COLLECT_WORKFLOW = ROOT / ".github" / "workflows" / "collect-krx-watchlist.yml"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"

RULES_VERSION = "2026-07-10-v7.6-financial-valuation-link"
POLICY_VERSION = RULES_VERSION
BUILDER_BEGIN = "# FINANCIAL_VALUATION_LINK_V76_BEGIN"
BUILDER_END = "# FINANCIAL_VALUATION_LINK_V76_END"
HEALTH_BEGIN = "# FINANCIAL_VALUATION_HEALTH_V76_BEGIN"
HEALTH_END = "# FINANCIAL_VALUATION_HEALTH_V76_END"
WORKFLOW_MARKER = "FINANCIAL_VALUATION_V76_OFFICIAL"
RULES_MARKER = "<!-- FINANCIAL_VALUATION_LINK_V76 -->"


class PatchError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label} 기준점 오류: {count}")
    return text.replace(old, new, 1)


def patch_builder() -> None:
    if not BUILDER.exists():
        raise FileNotFoundError(BUILDER)

    text = BUILDER.read_text(encoding="utf-8")

    if BUILDER_BEGIN not in text:
        anchor = "def compact_row("
        if text.count(anchor) != 1:
            raise PatchError(f"compact_row 기준점 오류: {text.count(anchor)}")
        policy = f'''{BUILDER_BEGIN}
FINANCIAL_VALUATION_LINK_POLICY = {{
    "version": "{POLICY_VERSION}",
    "source": "OpenDART+KRX_MARKET_METRICS",
    "preserve_missing_values": True,
    "do_not_estimate_missing_financials": True,
    "loss_company_per_policy": "PER_NULL_WHEN_ANNUALIZED_NET_INCOME_NOT_POSITIVE",
    "row_fields": [
        "financial_data_status",
        "financial_basis",
        "revenue_yoy_pct",
        "operating_profit_yoy_pct",
        "earnings_trend",
        "valuation_data_status",
        "valuation_price_basis_date",
        "per_annualized",
        "pbr",
    ],
}}
{BUILDER_END}


'''
        text = text.replace(anchor, policy + anchor, 1)

    if '"financial_data_status": clean_scalar(' not in text:
        anchor = '        "earnings_trend": clean_scalar(source.get("earnings_trend")),\n'
        insertion = anchor + '''        "financial_data_status": clean_scalar(
            source.get("financial_data_status")
        ),
        "financial_basis": clean_scalar(source.get("financial_basis")),
        "valuation_data_status": clean_scalar(
            source.get("valuation_data_status")
        ),
        "valuation_price_basis_date": clean_scalar(
            source.get("valuation_price_basis_date")
        ),
'''
        text = replace_once(text, anchor, insertion, "compact row financial fields")

    if '"financial_valuation_link_policy": FINANCIAL_VALUATION_LINK_POLICY' not in text:
        preferred_anchors = (
            '        "activity_elasticity_policy": ACTIVITY_ELASTICITY_POLICY,',
            '        "validation_message": "OK",',
        )
        selected = next((item for item in preferred_anchors if item in text), None)
        if selected is None:
            raise PatchError("payload policy 삽입 기준점을 찾지 못했습니다.")
        text = text.replace(
            selected,
            selected
            + "\n"
            + '        "financial_valuation_link_policy": '
            + "FINANCIAL_VALUATION_LINK_POLICY,",
            1,
        )

    required = (
        BUILDER_BEGIN,
        BUILDER_END,
        '"financial_data_status": clean_scalar(',
        '"financial_basis": clean_scalar(',
        '"valuation_data_status": clean_scalar(',
        '"valuation_price_basis_date": clean_scalar(',
        '"financial_valuation_link_policy": FINANCIAL_VALUATION_LINK_POLICY',
    )
    for token in required:
        if token not in text:
            raise PatchError(f"builder 필수 토큰 누락: {token}")

    BUILDER.write_text(text, encoding="utf-8")


def patch_health() -> None:
    if not HEALTH.exists():
        raise FileNotFoundError(HEALTH)

    text = HEALTH.read_text(encoding="utf-8")

    text = re.sub(
        r'CHECKER_VERSION\s*=\s*"[^"]+"',
        'CHECKER_VERSION = "2026-07-10-v7.6-financial-valuation-health"',
        text,
        count=1,
    )

    if HEALTH_BEGIN not in text:
        anchor = "        duplicate_hits: List[Dict[str, Any]] = []\n"
        if text.count(anchor) != 1:
            raise PatchError(
                f"daily health financial 기준점 오류: {text.count(anchor)}"
            )

        block = f'''        {HEALTH_BEGIN}
        if spec["market"] == "KR":
            total_rows = len(rows)
            minimum_financial_rows = max(1, int(total_rows * 0.60 + 0.999))
            minimum_growth_rows = max(1, int(total_rows * 0.50 + 0.999))
            minimum_valuation_rows = max(1, int(total_rows * 0.50 + 0.999))

            financial_status_rows = [
                index
                for index, row in enumerate(rows, start=1)
                if isinstance(row, Mapping)
                and str(row.get("financial_data_status") or "").strip()
            ]
            if len(financial_status_rows) == total_rows:
                report.pass_check(
                    f"{{table_id}}_financial_status_coverage",
                    f"{{table_id}} 재무수집 상태가 전 행에 표시됩니다.",
                    {{"coverage": f"{{len(financial_status_rows)}}/{{total_rows}}"}},
                )
            else:
                report.fail(
                    f"{{table_id}}_financial_status_coverage",
                    f"{{table_id}} 재무수집 상태가 일부 행에서 누락됐습니다.",
                    {{
                        "covered": len(financial_status_rows),
                        "total": total_rows,
                    }},
                )

            financial_basis_rows = [
                index
                for index, row in enumerate(rows, start=1)
                if isinstance(row, Mapping)
                and str(row.get("financial_basis") or "").strip()
            ]
            if len(financial_basis_rows) >= minimum_financial_rows:
                report.pass_check(
                    f"{{table_id}}_financial_basis_coverage",
                    f"{{table_id}} 재무기준 연결률이 최소 기준 이상입니다.",
                    {{
                        "covered": len(financial_basis_rows),
                        "total": total_rows,
                        "minimum": minimum_financial_rows,
                    }},
                )
            else:
                report.fail(
                    f"{{table_id}}_financial_basis_coverage",
                    f"{{table_id}} 재무기준 연결률이 부족합니다.",
                    {{
                        "covered": len(financial_basis_rows),
                        "total": total_rows,
                        "minimum": minimum_financial_rows,
                    }},
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
                    f"{{table_id}}_financial_growth_coverage",
                    f"{{table_id}} 재무증감률 연결률이 최소 기준 이상입니다.",
                    {{
                        "covered": len(growth_rows),
                        "total": total_rows,
                        "minimum": minimum_growth_rows,
                    }},
                )
            else:
                report.fail(
                    f"{{table_id}}_financial_growth_coverage",
                    f"{{table_id}} 재무증감률 연결률이 부족합니다.",
                    {{
                        "covered": len(growth_rows),
                        "total": total_rows,
                        "minimum": minimum_growth_rows,
                    }},
                )

            valuation_status_rows = [
                index
                for index, row in enumerate(rows, start=1)
                if isinstance(row, Mapping)
                and str(row.get("valuation_data_status") or "").strip()
            ]
            valuation_date_rows = [
                index
                for index, row in enumerate(rows, start=1)
                if isinstance(row, Mapping)
                and str(row.get("valuation_price_basis_date") or "").strip()
            ]
            pbr_rows = [
                index
                for index, row in enumerate(rows, start=1)
                if isinstance(row, Mapping) and row.get("pbr") is not None
            ]
            if (
                len(valuation_status_rows) == total_rows
                and len(valuation_date_rows) >= minimum_valuation_rows
                and len(pbr_rows) >= minimum_valuation_rows
            ):
                report.pass_check(
                    f"{{table_id}}_valuation_coverage",
                    f"{{table_id}} 밸류에이션 상태·기준일·PBR 연결이 정상입니다.",
                    {{
                        "status": len(valuation_status_rows),
                        "basis_date": len(valuation_date_rows),
                        "pbr": len(pbr_rows),
                        "total": total_rows,
                    }},
                )
            else:
                report.fail(
                    f"{{table_id}}_valuation_coverage",
                    f"{{table_id}} 밸류에이션 연결이 불완전합니다.",
                    {{
                        "status": len(valuation_status_rows),
                        "basis_date": len(valuation_date_rows),
                        "pbr": len(pbr_rows),
                        "total": total_rows,
                        "minimum": minimum_valuation_rows,
                    }},
                )

            invalid_per_rows = []
            for index, row in enumerate(rows, start=1):
                if not isinstance(row, Mapping):
                    continue
                per_value = row.get("per_annualized")
                valuation_status = str(
                    row.get("valuation_data_status") or ""
                ).upper()
                if per_value is None and valuation_status == "READY":
                    invalid_per_rows.append(index)
            if invalid_per_rows:
                report.fail(
                    f"{{table_id}}_per_loss_policy",
                    f"{{table_id}}에서 READY 상태인데 PER가 누락된 행이 있습니다.",
                    {{"rows": invalid_per_rows}},
                )
            else:
                report.pass_check(
                    f"{{table_id}}_per_loss_policy",
                    f"{{table_id}} 적자기업 PER 공란 정책이 정상입니다.",
                )
        {HEALTH_END}

'''
        text = text.replace(anchor, block + anchor, 1)

    required = (
        HEALTH_BEGIN,
        HEALTH_END,
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


def patch_collect_workflow() -> None:
    if not COLLECT_WORKFLOW.exists():
        raise FileNotFoundError(COLLECT_WORKFLOW)

    text = COLLECT_WORKFLOW.read_text(encoding="utf-8")
    if WORKFLOW_MARKER in text:
        return

    pattern = re.compile(
        r'(?P<indent>[ \t]*)python monthly_cycle\.py '
        r'--output-dir latest --lookback-months 6 --top-n 40[ \t]*\n'
    )
    match = pattern.search(text)
    if match is None:
        raise PatchError("정규수집 monthly_cycle 기준점을 찾지 못했습니다.")

    indent = match.group("indent")
    addition = (
        match.group(0)
        + f"{indent}# {WORKFLOW_MARKER}\n"
        + f"{indent}python -m py_compile financial_valuation_enricher.py\n"
        + f"{indent}python financial_valuation_enricher.py \\\n"
        + f"{indent}  --output-dir latest \\\n"
        + f"{indent}  --workers 4 \\\n"
        + f"{indent}  --timeout 30 \\\n"
        + f"{indent}  --max-api-calls 5000 \\\n"
        + f"{indent}  --retry-hours 20 \\\n"
        + f"{indent}  | tee /tmp/financial_valuation_v76.txt\n"
        + f"{indent}grep -q 'FINANCIAL_VALUATION_STATUS=OK' \\\n"
        + f"{indent}  /tmp/financial_valuation_v76.txt\n"
        + f"{indent}echo '----- 재무·밸류에이션 자동수집 결과 -----'\n"
        + f"{indent}cat latest/financial_valuation_run_log_latest.txt || true\n"
    )
    text = text[: match.start()] + addition + text[match.end() :]

    if WORKFLOW_MARKER not in text:
        raise PatchError("정규 Workflow 재무 단계 삽입 실패")

    COLLECT_WORKFLOW.write_text(text, encoding="utf-8")


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
        text = text.rstrip() + f'''

---

## 19. 재무·밸류에이션 연결 V7.6

{RULES_MARKER}

### 19-1. 공식 자료원

- 재무실적은 OpenDART 최근 확정 보고서를 사용한다.
- 연결재무제표를 우선하고 없을 때만 개별재무제표를 사용한다.
- PER·PBR 계산의 시가총액과 상장주식수는 KRX 시장자료를 사용한다.
- 자료가 없으면 임의 추정값을 만들지 않는다.

### 19-2. 표 전달 필드

- `financial_basis`: 재무 보고서 기준
- `valuation_price_basis_date`: PER·PBR 가격 기준일
- `revenue_yoy_pct`: 매출 전년 동기 대비
- `operating_profit_yoy_pct`: 영업이익 전년 동기 대비
- `earnings_trend`: 흑자·적자 흐름
- `per_annualized`: 연환산 PER
- `pbr`: PBR
- `financial_data_status`, `valuation_data_status`: 자료 상태

### 19-3. 적자기업 PER

- 연환산 순이익이 0 이하이면 숫자 PER를 만들지 않는다.
- 이 경우 `valuation_data_status=PARTIAL_LOSS_PER_NA` 등 자료상태로
  이유를 명확히 전달한다.
- PBR 등 계산 가능한 값은 별도로 유지한다.

### 19-4. 표 출력 방식

- 상단 `재무·밸류에이션 기준일`에는 `financial_basis`와
  `valuation_price_basis_date`를 구분해 표시한다.
- `기업가치·흐름 평가`에는 가능한 범위에서 매출증감률,
  영업이익증감률, 이익흐름, PER, PBR을 우선 표시한다.
- 적자기업은 PER 숫자를 만들지 않고 `적자로 PER 계산 제외`라고 쓴다.
- 값이 실제로 없는 항목만 `자료 미제공`으로 표시한다.

### 19-5. 자동화 순서

정규 공식수집에서는 주요 후보표 생성 후
`financial_valuation_enricher.py`를 실행하고, 그 결과가 반영된 CSV로
API를 생성한다. 일일 건강검사는 재무기준·증감률·밸류에이션 연결률을
자동 점검한다.
'''

    RULES.write_text(text + "\n", encoding="utf-8")


def verify() -> None:
    checks = {
        BUILDER: (
            BUILDER_BEGIN,
            '"financial_data_status": clean_scalar(',
            '"valuation_data_status": clean_scalar(',
            '"financial_valuation_link_policy": FINANCIAL_VALUATION_LINK_POLICY',
        ),
        HEALTH: (
            HEALTH_BEGIN,
            "financial_basis_coverage",
            "valuation_coverage",
        ),
        COLLECT_WORKFLOW: (
            WORKFLOW_MARKER,
            "financial_valuation_enricher.py",
            "FINANCIAL_VALUATION_STATUS=OK",
        ),
        RULES: (RULES_MARKER, RULES_VERSION),
    }
    for path, tokens in checks.items():
        text = path.read_text(encoding="utf-8")
        for token in tokens:
            if token not in text:
                raise PatchError(f"{path}: 검증 토큰 누락 {token}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if not args.verify_only:
        patch_builder()
        patch_health()
        patch_collect_workflow()
        patch_rules()

    verify()
    print("PATCH_FINANCIAL_VALUATION_LINK_V76=OK")
    print(f"RULES_VERSION={RULES_VERSION}")
    print("OFFICIAL_WORKFLOW_FINANCIAL_ENRICHMENT=CONNECTED")
    print("COMPACT_FINANCIAL_STATUS_FIELDS=CONNECTED")
    print("DAILY_FINANCIAL_HEALTH_CHECKS=CONNECTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
