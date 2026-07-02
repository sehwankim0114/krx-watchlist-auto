#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_one_month_production_routes.py v1.0.0

코피표1개월·코닥표1개월을 실제 운영 경로에 연결한다.

수정 대상
1. .github/workflows/collect-krx-watchlist.yml
   - 공식 KRX 수집 후 두 1개월표를 자동 생성
2. build_api_json.py
   - 후보표 2개와 별도 요청용 추천표 2개 API 등록
3. docs/custom_gpt_action_schema.yaml
   - Custom GPT 호출 operationId 4개 등록

이 프로그램은 실제 데이터 파일을 직접 만들지 않는다.
패치 적용 후 별도 Actions가 생성기 실행·API 빌드·경로 등록부 검증을 수행한다.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, Tuple


SCRIPT_VERSION = (
    "patch_one_month_production_routes.py "
    "v1.0.0"
)
POLICY_VERSION = (
    "2026-07-03-v6.0-one-month-production-routes"
)

COLLECT_BEGIN = "# ONE_MONTH_PRODUCTION_ROUTES_V6_BEGIN"
COLLECT_END = "# ONE_MONTH_PRODUCTION_ROUTES_V6_END"
API_BEGIN = "# ONE_MONTH_API_TABLE_SPECS_V6_BEGIN"
API_END = "# ONE_MONTH_API_TABLE_SPECS_V6_END"
SCHEMA_BEGIN = "# ONE_MONTH_ACTION_PATHS_V6_BEGIN"
SCHEMA_END = "# ONE_MONTH_ACTION_PATHS_V6_END"

DEFAULT_TARGETS = {
    "collect": Path(
        ".github/workflows/collect-krx-watchlist.yml"
    ),
    "api": Path("build_api_json.py"),
    "schema": Path(
        "docs/custom_gpt_action_schema.yaml"
    ),
}


class PatchError(RuntimeError):
    pass


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def patch_collect_workflow(text: str) -> Tuple[str, bool]:
    original = normalize_newlines(text)

    if COLLECT_BEGIN in original:
        return original, False

    pattern = re.compile(
        r"^(?P<indent>[ \t]*)python -m py_compile "
        r"operating_loss_enricher\.py\s*$",
        flags=re.MULTILINE,
    )
    match = pattern.search(original)
    if not match:
        raise PatchError(
            "collect workflow에서 operating_loss_enricher "
            "삽입 기준을 찾지 못했습니다."
        )

    indent = match.group("indent")
    block_lines = [
        f"{indent}{COLLECT_BEGIN}",
        (
            f"{indent}python -m py_compile "
            "kospi_one_month.py"
        ),
        (
            f"{indent}python kospi_one_month.py "
            "--input "
            "latest/kospi_universe_summary_latest.csv "
            "--output-dir latest "
            "--candidate-n 30 "
            "--recommend-n 7"
        ),
        (
            f"{indent}python -m py_compile "
            "kosdaq_one_month.py"
        ),
        (
            f"{indent}python kosdaq_one_month.py "
            "--input "
            "latest/kosdaq_universe_summary_latest.csv "
            "--output-dir latest "
            "--candidate-n 10 "
            "--recommend-n 5"
        ),
        (
            f'{indent}echo "----- 코피표1개월 자동산출 결과 -----"'
        ),
        (
            f"{indent}cat "
            "latest/kospi_1m_run_log_latest.txt "
            "|| true"
        ),
        (
            f'{indent}echo "----- 코닥표1개월 자동산출 결과 -----"'
        ),
        (
            f"{indent}cat "
            "latest/kosdaq_1m_run_log_latest.txt "
            "|| true"
        ),
        f"{indent}{COLLECT_END}",
        "",
    ]
    block = "\n".join(block_lines)

    patched = (
        original[: match.start()]
        + block
        + original[match.start() :]
    )
    return patched, True


def patch_build_api(text: str) -> Tuple[str, bool]:
    original = normalize_newlines(text)

    if API_BEGIN in original:
        return original, False

    pattern = re.compile(
        r"^(?P<indent>[ \t]*)TableSpec\(\s*\n"
        r"(?P=indent)[ \t]+\"kospi_gainers_1m\",",
        flags=re.MULTILINE,
    )
    match = pattern.search(original)
    if not match:
        raise PatchError(
            "build_api_json.py에서 kospi_gainers_1m "
            "TableSpec 삽입 기준을 찾지 못했습니다."
        )

    indent = match.group("indent")
    inner = indent + "    "

    block = f"""{indent}{API_BEGIN}
{indent}TableSpec(
{inner}"kospi_1m_candidates_30",
{inner}"코피표1개월 후보 30",
{inner}"kospi_1m_candidates_30.json",
{inner}("kospi_1m_candidates_30_latest.csv",),
{inner}required=True,
{inner}exact_rows=30,
{indent}),
{indent}TableSpec(
{inner}"kospi_1m_recommend_7",
{inner}"별도 요청용 코피표1개월 추천 7",
{inner}"kospi_1m_recommend_7.json",
{inner}("kospi_1m_recommend_7_latest.csv",),
{inner}required=False,
{inner}exact_rows=7,
{inner}default_output=False,
{inner}explicit_request_only=True,
{indent}),
{indent}TableSpec(
{inner}"kosdaq_1m_candidates_10",
{inner}"코닥표1개월 후보 10",
{inner}"kosdaq_1m_candidates_10.json",
{inner}("kosdaq_1m_candidates_10_latest.csv",),
{inner}required=True,
{inner}exact_rows=10,
{indent}),
{indent}TableSpec(
{inner}"kosdaq_1m_recommend_5",
{inner}"별도 요청용 코닥표1개월 추천 5",
{inner}"kosdaq_1m_recommend_5.json",
{inner}("kosdaq_1m_recommend_5_latest.csv",),
{inner}required=False,
{inner}exact_rows=5,
{inner}default_output=False,
{inner}explicit_request_only=True,
{indent}),
{indent}{API_END}
"""

    patched = (
        original[: match.start()]
        + block
        + original[match.start() :]
    )

    version_pattern = re.compile(
        r'SCRIPT_VERSION\s*=\s*"build_api_json\.py '
        r'([^"]+)"'
    )
    version_match = version_pattern.search(patched)
    if version_match:
        suffix = version_match.group(1)
        if "one_month_routes_v6" not in suffix:
            replacement = (
                'SCRIPT_VERSION = "build_api_json.py '
                + suffix
                + '_one_month_routes_v6"'
            )
            patched = (
                patched[: version_match.start()]
                + replacement
                + patched[version_match.end() :]
            )

    return patched, True


def action_endpoint(
    *,
    api_file: str,
    operation_id: str,
    summary: str,
    description: str,
) -> str:
    return f"""  /sehwankim0114/krx-watchlist-auto/main/api/{api_file}:
    get:
      operationId: {operation_id}
      summary: {summary}
      responses:
        '200':
          description: {description}
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AnyObject'
"""


def patch_action_schema(text: str) -> Tuple[str, bool]:
    original = normalize_newlines(text)

    if SCHEMA_BEGIN in original:
        return original, False

    anchor = (
        "  /sehwankim0114/krx-watchlist-auto/main/"
        "api/kospi_gainers_1m.json:\n"
    )
    index = original.find(anchor)
    if index < 0:
        raise PatchError(
            "Action 스키마에서 kospi_gainers_1m "
            "삽입 기준을 찾지 못했습니다."
        )

    blocks = [
        SCHEMA_BEGIN,
        action_endpoint(
            api_file="kospi_1m_candidates_30.json",
            operation_id="getKospiOneMonthCandidates",
            summary=(
                "Get the single KOSPI one-month candidate "
                "table with embedded recommendation markings"
            ),
            description="KOSPI one-month candidates",
        ).rstrip(),
        action_endpoint(
            api_file="kospi_1m_recommend_7.json",
            operation_id="getKospiOneMonthRecommendations",
            summary=(
                "Get the explicit-request-only KOSPI "
                "one-month recommendation shortlist"
            ),
            description="KOSPI one-month recommendations",
        ).rstrip(),
        action_endpoint(
            api_file="kosdaq_1m_candidates_10.json",
            operation_id="getKosdaqOneMonthCandidates",
            summary=(
                "Get the single KOSDAQ one-month candidate "
                "table with embedded recommendation markings"
            ),
            description="KOSDAQ one-month candidates",
        ).rstrip(),
        action_endpoint(
            api_file="kosdaq_1m_recommend_5.json",
            operation_id="getKosdaqOneMonthRecommendations",
            summary=(
                "Get the explicit-request-only KOSDAQ "
                "one-month recommendation shortlist"
            ),
            description="KOSDAQ one-month recommendations",
        ).rstrip(),
        SCHEMA_END,
        "",
    ]
    block = "\n".join(blocks)

    patched = original[:index] + block + original[index:]

    patched = re.sub(
        r"(?m)^  version:\s*5\.0\.0\s*$",
        "  version: 6.0.0",
        patched,
        count=1,
    )

    return patched, True


def verify_collect(text: str) -> None:
    required = [
        COLLECT_BEGIN,
        COLLECT_END,
        "python -m py_compile kospi_one_month.py",
        (
            "python kospi_one_month.py --input "
            "latest/kospi_universe_summary_latest.csv "
            "--output-dir latest --candidate-n 30 "
            "--recommend-n 7"
        ),
        "python -m py_compile kosdaq_one_month.py",
        (
            "python kosdaq_one_month.py --input "
            "latest/kosdaq_universe_summary_latest.csv "
            "--output-dir latest --candidate-n 10 "
            "--recommend-n 5"
        ),
    ]
    for fragment in required:
        if fragment not in text:
            raise PatchError(
                f"수집 Actions 필수 문구 누락: {fragment}"
            )

    if text.count(COLLECT_BEGIN) != 1:
        raise PatchError(
            "수집 Actions 시작 마커는 1개여야 합니다."
        )


def verify_api(text: str) -> None:
    required = [
        API_BEGIN,
        API_END,
        '"kospi_1m_candidates_30"',
        '"kospi_1m_recommend_7"',
        '"kosdaq_1m_candidates_10"',
        '"kosdaq_1m_recommend_5"',
        '"kospi_1m_candidates_30.json"',
        '"kosdaq_1m_candidates_10.json"',
        "required=True",
        "explicit_request_only=True",
    ]
    for fragment in required:
        if fragment not in text:
            raise PatchError(
                f"API 생성기 필수 문구 누락: {fragment}"
            )

    table_ids = (
        "kospi_1m_candidates_30",
        "kospi_1m_recommend_7",
        "kosdaq_1m_candidates_10",
        "kosdaq_1m_recommend_5",
    )
    for table_id in table_ids:
        count = text.count(f'"{table_id}"')
        if count != 1:
            raise PatchError(
                f"API TableSpec 중복/누락: "
                f"{table_id}={count}"
            )


def verify_schema(text: str) -> None:
    required_ops = (
        "getKospiOneMonthCandidates",
        "getKospiOneMonthRecommendations",
        "getKosdaqOneMonthCandidates",
        "getKosdaqOneMonthRecommendations",
    )
    for operation_id in required_ops:
        count = text.count(
            f"operationId: {operation_id}"
        )
        if count != 1:
            raise PatchError(
                f"Action operationId 중복/누락: "
                f"{operation_id}={count}"
            )

    required_paths = (
        "api/kospi_1m_candidates_30.json",
        "api/kospi_1m_recommend_7.json",
        "api/kosdaq_1m_candidates_10.json",
        "api/kosdaq_1m_recommend_5.json",
    )
    for path in required_paths:
        if path not in text:
            raise PatchError(
                f"Action API 경로 누락: {path}"
            )


def compile_python(path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PatchError(
            f"Python 문법검사 실패: {path}\n"
            + result.stderr
        )


def apply_one(
    path: Path,
    patcher: Callable[[str], Tuple[str, bool]],
    verifier: Callable[[str], None],
    *,
    backup: bool,
    check_only: bool,
    compile_after: bool = False,
) -> bool:
    if not path.exists():
        raise PatchError(f"대상 파일이 없습니다: {path}")

    original = path.read_text(encoding="utf-8")
    patched, changed = patcher(original)
    verifier(patched)

    if check_only:
        if changed:
            raise PatchError(
                f"아직 패치되지 않은 파일입니다: {path}"
            )
        if compile_after:
            compile_python(path)
        return False

    if changed:
        if backup:
            backup_path = path.with_suffix(
                path.suffix
                + ".before_one_month_routes.bak"
            )
            shutil.copy2(path, backup_path)

        temporary = path.with_suffix(
            path.suffix + ".one_month_routes.tmp"
        )
        temporary.write_text(
            patched,
            encoding="utf-8",
        )
        if compile_after:
            compile_python(temporary)
        temporary.replace(path)
    elif compile_after:
        compile_python(path)

    verifier(path.read_text(encoding="utf-8"))
    return changed


def run_self_test() -> int:
    collect_fixture = """name: collect
jobs:
  collect:
    steps:
      - name: official
        run: |
          python run_universe_latest.py --days 180 --output-dir latest
          python -m py_compile operating_loss_enricher.py
          python operating_loss_enricher.py --output-dir latest
"""

    api_fixture = """#!/usr/bin/env python3
SCRIPT_VERSION = "build_api_json.py v4.2"
TABLE_SPECS = (
    TableSpec(
        "kosdaq_recommend_5",
        "별도 요청용 코닥 추천 5",
        "kosdaq_recommend_5.json",
        ("kosdaq_recommend_5_latest.csv",),
    ),
    TableSpec(
        "kospi_gainers_1m",
        "코급표",
        "kospi_gainers_1m.json",
        ("kospi_gainers_1m_latest.csv",),
    ),
)
"""

    schema_fixture = """openapi: 3.1.0
info:
  version: 5.0.0
paths:
  /sehwankim0114/krx-watchlist-auto/main/api/kosdaq_candidates_10.json:
    get:
      operationId: getKosdaqCandidates
  /sehwankim0114/krx-watchlist-auto/main/api/kospi_gainers_1m.json:
    get:
      operationId: getKospiGainers
components:
  schemas: {}
"""

    collect_first, collect_changed = (
        patch_collect_workflow(collect_fixture)
    )
    api_first, api_changed = patch_build_api(api_fixture)
    schema_first, schema_changed = (
        patch_action_schema(schema_fixture)
    )

    assert collect_changed is True
    assert api_changed is True
    assert schema_changed is True

    verify_collect(collect_first)
    verify_api(api_first)
    verify_schema(schema_first)

    collect_second, changed = patch_collect_workflow(
        collect_first
    )
    assert changed is False
    assert collect_second == collect_first

    api_second, changed = patch_build_api(api_first)
    assert changed is False
    assert api_second == api_first

    schema_second, changed = patch_action_schema(
        schema_first
    )
    assert changed is False
    assert schema_second == schema_first

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        collect_path = (
            root
            / ".github/workflows/"
            / "collect-krx-watchlist.yml"
        )
        api_path = root / "build_api_json.py"
        schema_path = (
            root
            / "docs/custom_gpt_action_schema.yaml"
        )

        collect_path.parent.mkdir(parents=True)
        schema_path.parent.mkdir(parents=True)

        collect_path.write_text(
            collect_fixture,
            encoding="utf-8",
        )
        api_path.write_text(
            api_fixture,
            encoding="utf-8",
        )
        schema_path.write_text(
            schema_fixture,
            encoding="utf-8",
        )

        apply_one(
            collect_path,
            patch_collect_workflow,
            verify_collect,
            backup=False,
            check_only=False,
        )
        apply_one(
            api_path,
            patch_build_api,
            verify_api,
            backup=False,
            check_only=False,
            compile_after=True,
        )
        apply_one(
            schema_path,
            patch_action_schema,
            verify_schema,
            backup=False,
            check_only=False,
        )

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "collect_workflow_patch,"
        "api_table_specs_patch,"
        "action_schema_patch,"
        "four_operation_ids,"
        "idempotency,"
        "api_python_compile"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default=".",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.self_test:
        return run_self_test()

    root = Path(args.root).resolve()
    targets = {
        key: root / path
        for key, path in DEFAULT_TARGETS.items()
    }

    results: Dict[str, bool] = {}
    results["collect"] = apply_one(
        targets["collect"],
        patch_collect_workflow,
        verify_collect,
        backup=not args.no_backup,
        check_only=args.check_only,
    )
    results["api"] = apply_one(
        targets["api"],
        patch_build_api,
        verify_api,
        backup=not args.no_backup,
        check_only=args.check_only,
        compile_after=True,
    )
    results["schema"] = apply_one(
        targets["schema"],
        patch_action_schema,
        verify_schema,
        backup=not args.no_backup,
        check_only=args.check_only,
    )

    status = (
        "ALREADY_APPLIED"
        if args.check_only
        else (
            "APPLIED"
            if any(results.values())
            else "NO_CHANGE"
        )
    )

    print(
        "ONE_MONTH_PRODUCTION_ROUTES_PATCH_STATUS="
        + status
    )
    print(f"PATCH_SCRIPT_VERSION={SCRIPT_VERSION}")
    print(f"PATCH_POLICY_VERSION={POLICY_VERSION}")
    print(
        "COLLECT_WORKFLOW_CHANGED="
        + str(results["collect"]).lower()
    )
    print(
        "BUILD_API_CHANGED="
        + str(results["api"]).lower()
    )
    print(
        "ACTION_SCHEMA_CHANGED="
        + str(results["schema"]).lower()
    )
    print("ONE_MONTH_CANDIDATE_API_COUNT=2")
    print("ONE_MONTH_RECOMMEND_API_COUNT=2")
    print("ONE_MONTH_ACTION_OPERATION_COUNT=4")
    print("ONE_MONTH_PRODUCTION_ROUTE_PATCH=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
