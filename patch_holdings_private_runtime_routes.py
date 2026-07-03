#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_holdings_private_runtime_routes.py v1.0.0

보유종목표를 개인정보 비저장 런타임 경로로 연결한다.
- build_api_json.py: 공개 종목 참고 shard 생성기 호출
- docs/custom_gpt_action_schema.yaml: manifest/shard 호출 경로 추가
- table_route_registry.py: holdings를 READY_PRIVATE_RUNTIME 계약으로 전환
- docs/holdings_private_runtime_contract.md: 개인정보 비저장 계약 생성
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Callable, Tuple


SCRIPT_VERSION = (
    "patch_holdings_private_runtime_routes.py "
    "v1.0.0"
)
POLICY_VERSION = (
    "2026-07-03-v6.0-holdings-private-runtime"
)

BUILD_BEGIN = "# HOLDINGS_PRIVATE_RUNTIME_BUILD_V6_BEGIN"
BUILD_END = "# HOLDINGS_PRIVATE_RUNTIME_BUILD_V6_END"
SCHEMA_BEGIN = "# HOLDINGS_PRIVATE_RUNTIME_ACTION_V6_BEGIN"
SCHEMA_END = "# HOLDINGS_PRIVATE_RUNTIME_ACTION_V6_END"
REGISTRY_MARKER = "# HOLDINGS_PRIVATE_RUNTIME_READY_V6"
CONTRACT_MARKER = "holdings_private_runtime_contract v1.0.0"


class PatchError(RuntimeError):
    pass


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def patch_build_api(text: str) -> Tuple[str, bool]:
    original = normalize(text)
    if BUILD_BEGIN in original:
        verify_build_api(original)
        return original, False

    patched = original
    if "import sys\n" not in patched:
        if patched.count("import subprocess\n") != 1:
            raise PatchError("build_api_json.py import subprocess 기준점 오류")
        patched = patched.replace(
            "import subprocess\n",
            "import subprocess\nimport sys\n",
            1,
        )

    anchor = "def main() -> int:\n"
    if patched.count(anchor) != 1:
        raise PatchError(
            "build_api_json.py main 기준점 오류: "
            f"{patched.count(anchor)}"
        )

    function = f'''{BUILD_BEGIN}
def build_holdings_public_reference_api() -> None:
    command = [
        sys.executable,
        str(ROOT / "build_stock_reference_api.py"),
        "--kospi-summary",
        str(LATEST / "kospi_universe_summary_latest.csv"),
        "--kosdaq-summary",
        str(LATEST / "kosdaq_universe_summary_latest.csv"),
        "--api-dir",
        str(API),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Stock reference API build failed: "
            f"{{completed.returncode}}"
        )
    print("HOLDINGS_PUBLIC_REFERENCE_API=OK")
{BUILD_END}

'''
    patched = patched.replace(anchor, function + anchor, 1)

    main_anchor = "def main() -> int:\n    now = kst_now()\n"
    main_new = (
        "def main() -> int:\n"
        "    build_holdings_public_reference_api()\n"
        "    now = kst_now()\n"
    )
    if patched.count(main_anchor) != 1:
        raise PatchError(
            "build_api_json.py main 첫줄 기준점 오류: "
            f"{patched.count(main_anchor)}"
        )
    patched = patched.replace(main_anchor, main_new, 1)

    version_pattern = re.compile(
        r'SCRIPT_VERSION\s*=\s*"build_api_json\.py ([^"]+)"'
    )
    match = version_pattern.search(patched)
    if match and "holdings_private_runtime_v6" not in match.group(1):
        replacement = (
            'SCRIPT_VERSION = "build_api_json.py '
            + match.group(1)
            + '_holdings_private_runtime_v6"'
        )
        patched = (
            patched[:match.start()]
            + replacement
            + patched[match.end():]
        )

    verify_build_api(patched)
    return patched, True


def verify_build_api(text: str) -> None:
    required = (
        BUILD_BEGIN,
        BUILD_END,
        "def build_holdings_public_reference_api() -> None:",
        'str(ROOT / "build_stock_reference_api.py")',
        "HOLDINGS_PUBLIC_REFERENCE_API=OK",
        "build_holdings_public_reference_api()",
        "holdings_private_runtime_v6",
    )
    for item in required:
        if item not in text:
            raise PatchError(f"build_api 필수 문구 누락: {item}")
    if text.count(BUILD_BEGIN) != 1:
        raise PatchError("build_api holdings marker 중복")
    if text.count("    build_holdings_public_reference_api()\n") != 1:
        raise PatchError("build_api holdings 호출 개수 오류")


def action_endpoint_block() -> str:
    return f'''{SCHEMA_BEGIN}
  /sehwankim0114/krx-watchlist-auto/main/api/stock_reference_manifest.json:
    get:
      operationId: getHoldingsReferenceManifest
      summary: Get privacy-safe holdings runtime reference manifest
      responses:
        '200':
          description: Public stock-reference shard manifest with no user holdings
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AnyObject'
  /sehwankim0114/krx-watchlist-auto/main/api/stock_reference_shards/{{prefix}}.json:
    get:
      operationId: getStockReferenceShard
      summary: Get a public stock-reference shard by the first two ticker digits
      parameters:
        - name: prefix
          in: path
          required: true
          description: First two digits of a six-digit Korean ticker
          schema:
            type: string
            pattern: '^[0-9]{{2}}$'
      responses:
        '200':
          description: Public market and company reference rows; no user holdings
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AnyObject'
{SCHEMA_END}
'''


def patch_schema(text: str) -> Tuple[str, bool]:
    original = normalize(text)
    if SCHEMA_BEGIN in original:
        verify_schema(original)
        return original, False

    anchor = "components:\n"
    if original.count(anchor) != 1:
        raise PatchError(
            "Action schema components 기준점 오류: "
            f"{original.count(anchor)}"
        )
    patched = original.replace(
        anchor,
        action_endpoint_block() + anchor,
        1,
    )
    verify_schema(patched)
    return patched, True


def verify_schema(text: str) -> None:
    required = (
        SCHEMA_BEGIN,
        SCHEMA_END,
        "operationId: getHoldingsReferenceManifest",
        "operationId: getStockReferenceShard",
        "api/stock_reference_manifest.json",
        "api/stock_reference_shards/{prefix}.json",
        "pattern: '^[0-9]{2}$'",
    )
    for item in required:
        if item not in text:
            raise PatchError(f"Action schema 필수 문구 누락: {item}")
    for operation_id in (
        "getHoldingsReferenceManifest",
        "getStockReferenceShard",
    ):
        if text.count(f"operationId: {operation_id}") != 1:
            raise PatchError(
                f"Action operationId 중복/누락: {operation_id}"
            )


def route_pattern(route_id: str) -> re.Pattern[str]:
    return re.compile(
        rf'(?P<block>^    RouteContract\(\n'
        rf'        route_id="{re.escape(route_id)}",'
        rf'.*?^    \),$)',
        flags=re.DOTALL | re.MULTILINE,
    )


def holdings_route_block() -> str:
    return '''    RouteContract(
        route_id="holdings",
        display_name="보유종목표",
        request_terms=("보유종목표", "보유주식표"),
        generation_mode="PRIVATE_RUNTIME",
        source_candidates=(
            "holdings_table.py",
            "build_stock_reference_api.py",
            "docs/holdings_private_runtime_contract.md",
        ),
        api_files=(
            "api/stock_reference_manifest.json",
        ),
        operation_ids=(
            "getHoldingsReferenceManifest",
            "getStockReferenceShard",
        ),
        required_now=True,
        next_step=(
            "사용자 보유수량·평균매수가는 대화에서만 사용하고 "
            "공개 종목 참고 shard와 결합해 응답 시점에 계산한다."
        ),
    ),'''


def private_status_function() -> str:
    return '''def private_runtime_status(
    contract: RouteContract,
    schema_text: str,
) -> dict:
    source_existing = existing_paths(contract.source_candidates)
    api_existing = existing_paths(contract.api_files)
    operation_existing, operation_missing = operation_presence(
        contract.operation_ids,
        schema_text,
    )
    source_ok = (
        len(source_existing) == len(contract.source_candidates)
    )
    api_ok = len(api_existing) == len(contract.api_files)
    operation_ok = (
        len(operation_existing) == len(contract.operation_ids)
    )
    if source_ok and api_ok and operation_ok:
        status = "READY_PRIVATE_RUNTIME"
    elif contract.required_now:
        status = "BROKEN"
    else:
        status = "MISSING"
    missing_components = []
    if not source_ok:
        missing_components.append("SOURCE")
    if not api_ok:
        missing_components.append("API")
    if not operation_ok:
        missing_components.append("ACTION")
    return {
        "status": status,
        "source_existing": source_existing,
        "source_missing": missing_paths(
            contract.source_candidates
        ),
        "api_existing": api_existing,
        "api_missing": missing_paths(contract.api_files),
        "operation_existing": operation_existing,
        "operation_missing": operation_missing,
        "missing_components": missing_components,
    }


'''


def replace_once_or_done(
    text: str,
    old: str,
    new: str,
    label: str,
) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0 and new in text:
        return text
    raise PatchError(
        f"{label}: old_count={count}, new_present={new in text}"
    )


def patch_registry(text: str) -> Tuple[str, bool]:
    original = normalize(text)
    patched = original

    if REGISTRY_MARKER not in patched:
        anchor = "SCRIPT_VERSION ="
        index = patched.find(anchor)
        if index < 0:
            raise PatchError("registry SCRIPT_VERSION 기준점 누락")
        patched = (
            patched[:index]
            + REGISTRY_MARKER
            + "\n"
            + patched[index:]
        )

    match = route_pattern("holdings").search(patched)
    if not match:
        raise PatchError("holdings RouteContract 누락")
    current_block = match.group("block")
    desired_block = holdings_route_block()
    if current_block != desired_block:
        patched = (
            patched[:match.start("block")]
            + desired_block
            + patched[match.end("block"):]
        )

    if "def private_runtime_status(" not in patched:
        anchor = "def evaluate_routes() -> list[dict]:\n"
        if patched.count(anchor) != 1:
            raise PatchError("evaluate_routes 기준점 오류")
        patched = patched.replace(
            anchor,
            private_status_function() + anchor,
            1,
        )

    old_branch = '''        elif contract.generation_mode == "COMPOSITE":
            check = composite_status(contract, schema_text)
        else:
            check = direct_status(contract, schema_text)
'''
    new_branch = '''        elif contract.generation_mode == "PRIVATE_RUNTIME":
            check = private_runtime_status(
                contract,
                schema_text,
            )
        elif contract.generation_mode == "COMPOSITE":
            check = composite_status(contract, schema_text)
        else:
            check = direct_status(contract, schema_text)
'''
    if 'elif contract.generation_mode == "PRIVATE_RUNTIME":' not in patched:
        if patched.count(old_branch) != 1:
            raise PatchError(
                "evaluate private branch anchor count error: "
                f"{patched.count(old_branch)}"
            )
        patched = patched.replace(
            old_branch,
            new_branch,
            1,
        )

    if '"ready_private_runtime": sum(' not in patched:
        pattern = re.compile(
            r'(?P<block>^[ \t]+"ready_composite": sum\(\n'
            r'^[ \t]+row\["status"\] == "READY_COMPOSITE"\n'
            r'^[ \t]+for row in results\n'
            r'^[ \t]+\),\n)',
            flags=re.MULTILINE,
        )
        match = pattern.search(patched)
        if not match:
            raise PatchError("private count insertion anchor missing")
        indent_match = re.match(
            r'(?P<indent>[ \t]+)',
            match.group("block"),
        )
        if not indent_match:
            raise PatchError("private count indentation missing")
        indent = indent_match.group("indent")
        inner = indent + "    "
        addition = (
            f'{indent}"ready_private_runtime": sum(\n'
            f'{inner}row["status"] == "READY_PRIVATE_RUNTIME"\n'
            f'{inner}for row in results\n'
            f'{indent}),\n'
        )
        patched = (
            patched[:match.end("block")]
            + addition
            + patched[match.end("block"):]
        )

    old_total = '''        counts["ready_direct"]
        + counts["ready_shared"]
        + counts["ready_composite"]
    )
'''
    new_total = '''        counts["ready_direct"]
        + counts["ready_shared"]
        + counts["ready_composite"]
        + counts["ready_private_runtime"]
    )
'''
    patched = replace_once_or_done(
        patched,
        old_total,
        new_total,
        "ready total",
    )

    changes = (
        (
            '        "next_build_order": [\n'
            '            "holdings",\n'
            '            "us_watchlist",\n'
            '        ],\n',
            '        "next_build_order": [\n'
            '            "us_watchlist",\n'
            '        ],\n',
            "next build order",
        ),
        (
            '        f"READY_COMPOSITE_COUNT={counts[\'ready_composite\']}",\n'
            '        f"READY_TOTAL_COUNT={counts[\'ready_total\']}",\n',
            '        f"READY_COMPOSITE_COUNT={counts[\'ready_composite\']}",\n'
            '        f"READY_PRIVATE_RUNTIME_COUNT={counts[\'ready_private_runtime\']}",\n'
            '        f"READY_TOTAL_COUNT={counts[\'ready_total\']}",\n',
            "ready log field",
        ),
        (
            '        "EXPECTED_CURRENT_READY_COUNT=11",\n',
            '        "EXPECTED_CURRENT_READY_COUNT=12",\n',
            "expected ready",
        ),
        (
            '        "EXPECTED_CURRENT_MISSING_COUNT=2",\n',
            '        "EXPECTED_CURRENT_MISSING_COUNT=1",\n',
            "expected missing",
        ),
        (
            '        "EXPECTED_MISSING_ROUTES=holdings,us_watchlist",\n',
            '        "EXPECTED_MISSING_ROUTES=us_watchlist",\n',
            "expected missing routes",
        ),
        (
            '        "NEXT_BUILD_ORDER=holdings,us_watchlist",\n',
            '        "NEXT_BUILD_ORDER=us_watchlist",\n',
            "next log",
        ),
        (
            '    if planned_missing != {\n'
            '        "holdings",\n'
            '        "us_watchlist",\n'
            '    }:\n',
            '    if planned_missing != {\n'
            '        "us_watchlist",\n'
            '    }:\n',
            "planned missing set",
        ),
        (
            '"Planned missing routes must be exactly two"',
            '"Planned missing routes must be exactly one"',
            "planned missing text",
        ),
        (
            'assert sum(route.required_now for route in ROUTES) == 11',
            'assert sum(route.required_now for route in ROUTES) == 12',
            "self ready",
        ),
        (
            'assert sum(route.planned_missing for route in ROUTES) == 2',
            'assert sum(route.planned_missing for route in ROUTES) == 1',
            "self missing",
        ),
        (
            '    for route_id in (\n'
            '        "holdings",\n'
            '        "us_watchlist",\n'
            '    ):\n',
            '    for route_id in (\n'
            '        "us_watchlist",\n'
            '    ):\n',
            "self missing loop",
        ),
        (
            '"eleven_current_routes,"',
            '"twelve_current_routes,"',
            "self ready label",
        ),
        (
            '"two_planned_missing_routes,"',
            '"one_planned_missing_route,"',
            "self missing label",
        ),
        (
            'if counts["ready_total"] != 11:',
            'if counts["ready_total"] != 12:',
            "strict ready",
        ),
        (
            'f"Expected 11 ready routes, got {counts[\'ready_total\']}"',
            'f"Expected 12 ready routes, got {counts[\'ready_total\']}"',
            "strict ready text",
        ),
        (
            'if counts["missing"] != 2:',
            'if counts["missing"] != 1:',
            "strict missing",
        ),
        (
            'f"Expected 2 missing routes, got {counts[\'missing\']}"',
            'f"Expected 1 missing route, got {counts[\'missing\']}"',
            "strict missing text",
        ),
        (
            '        expected_missing = {\n'
            '            "holdings",\n'
            '            "us_watchlist",\n'
            '        }\n',
            '        expected_missing = {\n'
            '            "us_watchlist",\n'
            '        }\n',
            "strict missing set",
        ),
    )
    for old, new, label in changes:
        patched = replace_once_or_done(
            patched,
            old,
            new,
            label,
        )

    verify_registry(patched)
    return patched, patched != original


def verify_registry(text: str) -> None:
    required = (
        REGISTRY_MARKER,
        'generation_mode="PRIVATE_RUNTIME"',
        '"api/stock_reference_manifest.json"',
        '"getHoldingsReferenceManifest"',
        '"getStockReferenceShard"',
        "def private_runtime_status(",
        'status = "READY_PRIVATE_RUNTIME"',
        '"ready_private_runtime": sum(',
        'counts["ready_private_runtime"]',
        '"EXPECTED_CURRENT_READY_COUNT=12"',
        '"EXPECTED_CURRENT_MISSING_COUNT=1"',
        '"EXPECTED_MISSING_ROUTES=us_watchlist"',
        '"NEXT_BUILD_ORDER=us_watchlist"',
        'assert sum(route.required_now for route in ROUTES) == 12',
        'assert sum(route.planned_missing for route in ROUTES) == 1',
        'if counts["ready_total"] != 12:',
        'if counts["missing"] != 1:',
        '"twelve_current_routes,"',
        '"one_planned_missing_route,"',
    )
    for item in required:
        if item not in text:
            raise PatchError(f"registry 필수 문구 누락: {item}")

    match = route_pattern("holdings").search(text)
    if not match:
        raise PatchError("holdings route 검증 실패")
    block = match.group("block")
    if "required_now=True," not in block:
        raise PatchError("holdings required_now 누락")
    if "planned_missing=True," in block:
        raise PatchError("holdings planned_missing 잔존")


def contract_text() -> str:
    return f'''# 보유종목표 개인정보 비저장 런타임 계약

`{CONTRACT_MARKER}`

## 목적

보유종목표는 사용자가 현재 대화에서 제공한 보유수량·평균매수가·현금/신용 구분과 공개 시장 참고자료를 결합해 응답 시점에 계산한다.

## 절대 저장하지 않는 정보

- 보유수량
- 평균매수가
- 매입원가
- 평가금액
- 평가손익
- 계좌번호와 증권사 계좌 식별정보
- 신용융자 금액과 담보비율 등 개인 계좌 수치

위 정보는 공개 GitHub 저장소, `latest/`, `api/`, 실행로그, 시험 증빙에 기록하지 않는다.

## 공개 API에 저장 가능한 정보

- 종목코드와 종목명
- 시장 구분
- 공개 현재가·기준일
- 가치매수 참고구간과 목표가 참고값
- 3개월 저가·고가·현재위치 계산용 공개 수치
- 공개 재무·수급·유동성·가격탄력 자료

## 요청 처리 순서

1. 현재 대화에서 보유 종목코드, 수량, 평균매수가, 현금/신용 구분을 읽는다.
2. 종목코드 앞 두 자리로 `getStockReferenceShard`를 호출한다.
3. 시장과 6자리 종목코드가 모두 일치하는 공개 참고행을 선택한다.
4. 동일 종목의 현금과 신용은 합치지 않고 별도 행으로 계산한다.
5. 신용행은 추가 신용매수 금지와 비중축소 기준을 더 엄격하게 적용한다.
6. 계산 결과는 응답에만 표시하고 저장소에는 저장하지 않는다.

## 상태명

경로 등록부에서는 이 방식을 `READY_PRIVATE_RUNTIME`으로 표시한다. 이는 정적 `api/holdings.json`에 개인 보유내역을 저장했다는 뜻이 아니다.
'''


def write_contract(
    path: Path,
    *,
    check_only: bool,
) -> bool:
    desired = contract_text()
    current = (
        path.read_text(encoding="utf-8")
        if path.exists()
        else ""
    )
    if current == desired:
        return False
    if check_only:
        raise PatchError("개인정보 계약서가 아직 적용되지 않음")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desired, encoding="utf-8")
    return True


def compile_python(path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PatchError(
            f"Python 문법검사 실패: {path}\n"
            + completed.stderr
        )


def apply_text_patch(
    path: Path,
    patcher: Callable[[str], Tuple[str, bool]],
    verifier: Callable[[str], None],
    *,
    check_only: bool,
    compile_after: bool,
) -> bool:
    if not path.exists():
        raise PatchError(f"대상 파일 없음: {path}")
    original = path.read_text(encoding="utf-8")
    patched, changed = patcher(original)
    verifier(patched)
    if check_only:
        if changed:
            raise PatchError(f"패치 미적용: {path}")
        if compile_after:
            compile_python(path)
        return False
    if changed:
        temp = path.with_suffix(path.suffix + ".holdings.tmp")
        temp.write_text(patched, encoding="utf-8")
        if compile_after:
            compile_python(temp)
        temp.replace(path)
    elif compile_after:
        compile_python(path)
    verifier(path.read_text(encoding="utf-8"))
    return changed


def build_api_fixture() -> str:
    return textwrap.dedent(
        '''
        import subprocess
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent
        LATEST = ROOT / "latest"
        API = ROOT / "api"
        SCRIPT_VERSION = "build_api_json.py fixture"
        def kst_now():
            return None
        def main() -> int:
            now = kst_now()
            return 0
        '''
    ).lstrip()


def schema_fixture() -> str:
    return textwrap.dedent(
        '''
        openapi: 3.1.0
        info:
          title: Test
          version: 6.0.0
        servers:
          - url: https://raw.githubusercontent.com
        paths:
          /existing.json:
            get:
              operationId: getExisting
        components:
          schemas:
            AnyObject:
              type: object
        '''
    ).lstrip()


def registry_fixture() -> str:
    return textwrap.dedent(
        '''
        from dataclasses import dataclass, asdict
        SCRIPT_VERSION = "table_route_registry.py fixture"
        @dataclass(frozen=True)
        class RouteContract:
            route_id: str
            display_name: str
            request_terms: tuple[str, ...]
            generation_mode: str
            source_candidates: tuple[str, ...]
            api_files: tuple[str, ...]
            operation_ids: tuple[str, ...]
            shared_with: str = ""
            required_now: bool = False
            planned_missing: bool = False
            next_step: str = ""
        ROUTES = (
            RouteContract(
                route_id="holdings",
                display_name="보유종목표",
                request_terms=("보유종목표", "보유주식표"),
                generation_mode="DIRECT",
                source_candidates=("latest/holdings_latest.csv",),
                api_files=("api/holdings.json",),
                operation_ids=("getHoldings",),
                planned_missing=True,
                next_step="need generator",
            ),
            RouteContract(
                route_id="us_watchlist",
                display_name="미관종표",
                request_terms=("미관종표",),
                generation_mode="DIRECT",
                source_candidates=("latest/us.csv",),
                api_files=("api/us.json",),
                operation_ids=("getUs",),
                planned_missing=True,
                next_step="need generator",
            ),
        )
        def existing_paths(values): return list(values)
        def missing_paths(values): return []
        def operation_presence(values, text): return list(values), []
        def direct_status(contract, schema_text): return {"status": "READY_DIRECT"}
        def composite_status(contract, schema_text): return {"status": "READY_COMPOSITE"}
        def evaluate_routes() -> list[dict]:
            schema_text = ""
            results = []
            by_id = {}
            for contract in ROUTES:
                base = asdict(contract)
                if contract.generation_mode == "SHARED":
                    check = {"status": "READY_SHARED"}
                elif contract.generation_mode == "COMPOSITE":
                    check = composite_status(contract, schema_text)
                else:
                    check = direct_status(contract, schema_text)
                result = {**base, **check}
                results.append(result)
                by_id[contract.route_id] = result
            return results
        def write_outputs(results):
            counts = {
                "ready_direct": sum(row["status"] == "READY_DIRECT" for row in results),
                "ready_shared": sum(row["status"] == "READY_SHARED" for row in results),
                "ready_composite": sum(
                    row["status"] == "READY_COMPOSITE"
                    for row in results
                ),
                "missing": sum(row["status"] == "MISSING" for row in results),
                "broken": sum(row["status"] == "BROKEN" for row in results),
            }
            counts["ready_total"] = (
                counts["ready_direct"]
                + counts["ready_shared"]
                + counts["ready_composite"]
            )
            payload = {
                "next_build_order": [
                    "holdings",
                    "us_watchlist",
                ],
            }
            log_lines = [
                f"READY_COMPOSITE_COUNT={counts['ready_composite']}",
                f"READY_TOTAL_COUNT={counts['ready_total']}",
                "EXPECTED_CURRENT_READY_COUNT=11",
                "EXPECTED_CURRENT_MISSING_COUNT=2",
                "EXPECTED_MISSING_ROUTES=holdings,us_watchlist",
                "NEXT_BUILD_ORDER=holdings,us_watchlist",
            ]
            return payload, log_lines
        def validate_contract_definition():
            planned_missing = {
                route.route_id for route in ROUTES
                if route.planned_missing
            }
            if planned_missing != {
                "holdings",
                "us_watchlist",
            }:
                raise RuntimeError(
                    "Planned missing routes must be exactly two"
                )
        def run_self_test():
            assert sum(route.required_now for route in ROUTES) == 11
            assert sum(route.planned_missing for route in ROUTES) == 2
            for route_id in (
                "holdings",
                "us_watchlist",
            ):
                pass
            tested = (
                "eleven_current_routes,"
                "two_planned_missing_routes,"
            )
            return tested
        def strict(counts, results):
            if counts["ready_total"] != 11:
                raise SystemExit(
                    f"Expected 11 ready routes, got {counts['ready_total']}"
                )
            if counts["missing"] != 2:
                raise SystemExit(
                    f"Expected 2 missing routes, got {counts['missing']}"
                )
            if True:
                expected_missing = {
                    "holdings",
                    "us_watchlist",
                }
            return expected_missing
        '''
    ).lstrip()


def run_self_test() -> int:
    api_first, changed = patch_build_api(build_api_fixture())
    assert changed
    verify_build_api(api_first)
    api_second, changed = patch_build_api(api_first)
    assert not changed and api_second == api_first

    schema_first, changed = patch_schema(schema_fixture())
    assert changed
    verify_schema(schema_first)
    schema_second, changed = patch_schema(schema_first)
    assert not changed and schema_second == schema_first

    registry_first, changed = patch_registry(registry_fixture())
    assert changed
    verify_registry(registry_first)
    registry_second, changed = patch_registry(registry_first)
    assert not changed and registry_second == registry_first

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "docs").mkdir()
        build_path = root / "build_api_json.py"
        schema_path = root / "docs/custom_gpt_action_schema.yaml"
        registry_path = root / "table_route_registry.py"
        contract_path = root / "docs/holdings_private_runtime_contract.md"
        build_path.write_text(build_api_fixture(), encoding="utf-8")
        schema_path.write_text(schema_fixture(), encoding="utf-8")
        registry_path.write_text(registry_fixture(), encoding="utf-8")

        apply_text_patch(
            build_path,
            patch_build_api,
            verify_build_api,
            check_only=False,
            compile_after=True,
        )
        apply_text_patch(
            schema_path,
            patch_schema,
            verify_schema,
            check_only=False,
            compile_after=False,
        )
        apply_text_patch(
            registry_path,
            patch_registry,
            verify_registry,
            check_only=False,
            compile_after=True,
        )
        assert write_contract(contract_path, check_only=False)
        assert CONTRACT_MARKER in contract_path.read_text(encoding="utf-8")

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "build_api_hook,"
        "dynamic_shard_action,"
        "private_runtime_registry,"
        "ready_12_missing_1,"
        "privacy_contract,"
        "idempotency"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    root = Path(args.root).resolve()
    build_path = root / "build_api_json.py"
    schema_path = root / "docs/custom_gpt_action_schema.yaml"
    registry_path = root / "table_route_registry.py"
    contract_path = root / "docs/holdings_private_runtime_contract.md"

    build_changed = apply_text_patch(
        build_path,
        patch_build_api,
        verify_build_api,
        check_only=args.check_only,
        compile_after=True,
    )
    schema_changed = apply_text_patch(
        schema_path,
        patch_schema,
        verify_schema,
        check_only=args.check_only,
        compile_after=False,
    )
    registry_changed = apply_text_patch(
        registry_path,
        patch_registry,
        verify_registry,
        check_only=args.check_only,
        compile_after=True,
    )
    contract_changed = write_contract(
        contract_path,
        check_only=args.check_only,
    )

    status = (
        "ALREADY_APPLIED"
        if args.check_only
        else (
            "APPLIED"
            if any(
                (
                    build_changed,
                    schema_changed,
                    registry_changed,
                    contract_changed,
                )
            )
            else "NO_CHANGE"
        )
    )

    print(
        "HOLDINGS_PRIVATE_RUNTIME_PATCH_STATUS="
        + status
    )
    print(f"PATCH_SCRIPT_VERSION={SCRIPT_VERSION}")
    print(f"PATCH_POLICY_VERSION={POLICY_VERSION}")
    print(f"BUILD_API_CHANGED={str(build_changed).lower()}")
    print(f"ACTION_SCHEMA_CHANGED={str(schema_changed).lower()}")
    print(f"REGISTRY_CHANGED={str(registry_changed).lower()}")
    print(f"PRIVACY_CONTRACT_CHANGED={str(contract_changed).lower()}")
    print("EXPECTED_READY_ROUTES=12")
    print("EXPECTED_MISSING_ROUTES=1")
    print("REMAINING_MISSING_ROUTES=us_watchlist")
    print("STATIC_HOLDINGS_API_CREATED=false")
    print("USER_HOLDINGS_PERSISTED=false")
    print("HOLDINGS_PRIVATE_RUNTIME_PATCH=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
