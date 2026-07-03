#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
patch_us_watchlist_production_routes.py v1.0.0

미관종표 운영 API·Custom GPT Action·13개 경로 등록부를 연결한다.
'''

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
    "patch_us_watchlist_production_routes.py "
"v1.0.0-thirteen-of-thirteen-r1-flexible-schema-anchor"
)
POLICY_VERSION = (
    "2026-07-03-v6.0-us-watchlist-production"
)

API_BEGIN = "# US_WATCHLIST_API_TABLE_SPECS_V6_BEGIN"
API_END = "# US_WATCHLIST_API_TABLE_SPECS_V6_END"
ACTION_BEGIN = "# US_WATCHLIST_ACTION_PATHS_V6_BEGIN"
ACTION_END = "# US_WATCHLIST_ACTION_PATHS_V6_END"
REGISTRY_MARKER = "# US_WATCHLIST_ROUTE_READY_V6"


class PatchError(RuntimeError):
    pass


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def api_block() -> str:
    return (
        f"{API_BEGIN}\n"
        "    TableSpec(\n"
        '        "us_watchlist",\n'
        '        "미관종표 S&P500 후보 30",\n'
        '        "us_watchlist.json",\n'
        '        ("us_sp500_watchlist_latest.csv",),\n'
        "        required=True,\n"
        "        exact_rows=30,\n"
        "    ),\n"
        "    TableSpec(\n"
        '        "us_watchlist_recommend_7",\n'
        '        "별도 요청용 미관종표 추천 7",\n'
        '        "us_watchlist_recommend_7.json",\n'
        '        ("us_sp500_recommend_7_latest.csv",),\n'
        "        required=False,\n"
        "        exact_rows=7,\n"
        "        default_output=False,\n"
        "        explicit_request_only=True,\n"
        "    ),\n"
        f"{API_END}\n"
    )


def patch_build_api(text: str) -> Tuple[str, bool]:
    original = normalize(text)
    if API_BEGIN in original:
        verify_build_api(original)
        return original, False

    anchor = "# ONE_MONTH_API_TABLE_SPECS_V6_END\n"
    if original.count(anchor) != 1:
        raise PatchError(
            "build_api_json.py 삽입 기준점 오류: "
            f"{original.count(anchor)}"
        )

    patched = original.replace(
        anchor,
        anchor + api_block(),
        1,
    )

    if "us_watchlist_v6" not in patched:
        patched = re.sub(
            r'SCRIPT_VERSION\s*=\s*"([^"]+)"',
            lambda m: (
                'SCRIPT_VERSION = "'
                + m.group(1)
                + '_us_watchlist_v6"'
            ),
            patched,
            count=1,
        )

    verify_build_api(patched)
    return patched, True


def verify_build_api(text: str) -> None:
    required = [
        API_BEGIN,
        API_END,
        '"us_watchlist"',
        '"us_watchlist.json"',
        '"us_sp500_watchlist_latest.csv"',
        '"us_watchlist_recommend_7"',
        '"us_watchlist_recommend_7.json"',
        '"us_sp500_recommend_7_latest.csv"',
        "exact_rows=30",
        "exact_rows=7",
    ]
    for marker in required:
        if marker not in text:
            raise PatchError(
                f"build API 필수 문구 누락: {marker}"
            )

    if text.count('"us_watchlist"') != 1:
        raise PatchError("us_watchlist table_id 개수 오류")
    if text.count('"us_watchlist_recommend_7"') != 1:
        raise PatchError(
            "us_watchlist_recommend_7 table_id 개수 오류"
        )


def action_block() -> str:
    return (
        f"  {ACTION_BEGIN}\n"
        "  /sehwankim0114/krx-watchlist-auto/main/api/us_watchlist.json:\n"
        "    get:\n"
        "      operationId: getUsWatchlist\n"
        "      summary: Get the S&P500 candidate table with seven embedded recommendation markings\n"
        "      responses:\n"
        "        '200':\n"
        "          description: US S&P500 watchlist candidate rows\n"
        "          content:\n"
        "            application/json:\n"
        "              schema:\n"
        "                $ref: '#/components/schemas/AnyObject'\n"
        "  /sehwankim0114/krx-watchlist-auto/main/api/us_watchlist_recommend_7.json:\n"
        "    get:\n"
        "      operationId: getUsWatchlistRecommendations\n"
        "      summary: Get the explicit-request-only US S&P500 recommendation shortlist\n"
        "      responses:\n"
        "        '200':\n"
        "          description: US S&P500 recommendation rows\n"
        "          content:\n"
        "            application/json:\n"
        "              schema:\n"
        "                $ref: '#/components/schemas/AnyObject'\n"
        f"  {ACTION_END}\n"
    )


def patch_action_schema(text: str) -> Tuple[str, bool]:
    original = normalize(text)
    if ACTION_BEGIN in original:
        verify_action_schema(original)
        return original, False

    # 특정 주석과 들여쓰기에 의존하지 않는다.
    # 최상위 또는 fixture 내부의 components: 직전에
    # 미관종표 paths 항목을 삽입한다.
    components_pattern = re.compile(
        r"^[ \t]*components:\s*$",
        flags=re.MULTILINE,
    )
    matches = list(components_pattern.finditer(original))
    if len(matches) != 1:
        raise PatchError(
            "Action 스키마 components 기준점 오류: "
            f"{len(matches)}"
        )

    match = matches[0]
    patched = (
        original[:match.start()]
        + action_block()
        + original[match.start():]
    )

    verify_action_schema(patched)
    return patched, True


def verify_action_schema(text: str) -> None:
    required = [
        ACTION_BEGIN,
        ACTION_END,
        "/api/us_watchlist.json:",
        "operationId: getUsWatchlist",
        "/api/us_watchlist_recommend_7.json:",
        "operationId: getUsWatchlistRecommendations",
    ]
    for marker in required:
        if marker not in text:
            raise PatchError(
                f"Action 스키마 필수 문구 누락: {marker}"
            )

    for operation_id in (
        "getUsWatchlist",
        "getUsWatchlistRecommendations",
    ):
        count = len(
            re.findall(
                rf"^\s*operationId:\s*"
                rf"{re.escape(operation_id)}\s*$",
                text,
                flags=re.MULTILINE,
            )
        )
        if count != 1:
            raise PatchError(
                f"operationId 개수 오류: "
                f"{operation_id}={count}"
            )


def route_pattern() -> re.Pattern[str]:
    return re.compile(
        r'(?P<block>^    RouteContract\(\n'
        r'        route_id="us_watchlist",'
        r'.*?^    \),$)',
        flags=re.DOTALL | re.MULTILINE,
    )


def patch_us_route(text: str) -> str:
    match = route_pattern().search(text)
    if not match:
        raise PatchError(
            "us_watchlist RouteContract 블록 누락"
        )

    block = match.group("block")
    if "required_now=True," in block:
        if "planned_missing=True," in block:
            raise PatchError(
                "us_watchlist ready/missing 동시 존재"
            )
        return text

    if "planned_missing=True," not in block:
        raise PatchError(
            "us_watchlist planned_missing 기준점 누락"
        )

    updated = block.replace(
        "planned_missing=True,",
        "required_now=True,",
        1,
    )
    updated = re.sub(
        r'\n        next_step=\(\n.*?\n        \),',
        "",
        updated,
        count=1,
        flags=re.DOTALL,
    )

    return (
        text[:match.start("block")]
        + updated
        + text[match.end("block"):]
    )


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
        f"{label}: old_count={count}, "
        f"new_present={new in text}"
    )


def patch_registry(text: str) -> Tuple[str, bool]:
    original = normalize(text)
    patched = original

    if REGISTRY_MARKER not in patched:
        anchor = "# HOLDINGS_PRIVATE_RUNTIME_READY_V6\n"
        if patched.count(anchor) != 1:
            raise PatchError(
                "registry marker 삽입 기준점 오류"
            )
        patched = patched.replace(
            anchor,
            anchor + REGISTRY_MARKER + "\n",
            1,
        )

    patched = patch_us_route(patched)

    replacements = [
        (
            '        "next_build_order": [\n'
            '            "us_watchlist",\n'
            '        ],\n',
            '        "next_build_order": [],\n',
            "next_build_order",
        ),
        (
            '"EXPECTED_CURRENT_READY_COUNT=12"',
            '"EXPECTED_CURRENT_READY_COUNT=13"',
            "ready log",
        ),
        (
            '"EXPECTED_CURRENT_MISSING_COUNT=1"',
            '"EXPECTED_CURRENT_MISSING_COUNT=0"',
            "missing log",
        ),
        (
            '"EXPECTED_MISSING_ROUTES=us_watchlist"',
            '"EXPECTED_MISSING_ROUTES="',
            "missing routes log",
        ),
        (
            '"NEXT_BUILD_ORDER=us_watchlist"',
            '"NEXT_BUILD_ORDER="',
            "next build log",
        ),
        (
            "assert sum(route.required_now for route in ROUTES) == 12",
            "assert sum(route.required_now for route in ROUTES) == 13",
            "self-test ready",
        ),
        (
            "assert sum(route.planned_missing for route in ROUTES) == 1",
            "assert sum(route.planned_missing for route in ROUTES) == 0",
            "self-test missing",
        ),
        (
            '"twelve_current_routes,"',
            '"thirteen_current_routes,"',
            "self-test ready label",
        ),
        (
            '"one_planned_missing_route,"',
            '"zero_planned_missing_routes,"',
            "self-test missing label",
        ),
        (
            'if counts["ready_total"] != 12:',
            'if counts["ready_total"] != 13:',
            "strict ready",
        ),
        (
            'f"Expected 12 ready routes, got '
            '{counts[\'ready_total\']}"',
            'f"Expected 13 ready routes, got '
            '{counts[\'ready_total\']}"',
            "strict ready message",
        ),
        (
            'if counts["missing"] != 1:',
            'if counts["missing"] != 0:',
            "strict missing",
        ),
        (
            'f"Expected 1 missing route, got '
            '{counts[\'missing\']}"',
            'f"Expected 0 missing routes, got '
            '{counts[\'missing\']}"',
            "strict missing message",
        ),
    ]

    for old, new, label in replacements:
        patched = replace_once_or_done(
            patched,
            old,
            new,
            label,
        )

    missing_set_pattern = re.compile(
        r'^(?P<indent>[ \t]+)expected_missing = \{\n'
        r'(?P=indent)    "us_watchlist",\n'
        r'(?P=indent)\}\n',
        flags=re.MULTILINE,
    )
    missing_matches = list(missing_set_pattern.finditer(patched))
    if len(missing_matches) == 1:
        match = missing_matches[0]
        replacement = (
            match.group("indent")
            + "expected_missing = set()\n"
        )
        patched = (
            patched[:match.start()]
            + replacement
            + patched[match.end():]
        )
    elif (
        len(missing_matches) == 0
        and "expected_missing = set()" not in patched
    ):
        raise PatchError(
            "strict expected missing 기준점 누락"
        )
    elif len(missing_matches) > 1:
        raise PatchError(
            "strict expected missing 기준점 중복"
        )

    validate_pattern = re.compile(
        r'    planned_missing = \{\n'
        r'        route\.route_id for route in ROUTES\n'
        r'        if route\.planned_missing\n'
        r'    \}\n'
        r'    if planned_missing != \{\n'
        r'        "us_watchlist",\n'
        r'    \}:\n'
        r'        raise RuntimeError\(\n'
        r'            "Planned missing routes must be exactly one"\n'
        r'        \)\n',
        flags=re.MULTILINE,
    )
    validate_new = (
        "    planned_missing = {\n"
        "        route.route_id for route in ROUTES\n"
        "        if route.planned_missing\n"
        "    }\n"
        "    if planned_missing:\n"
        "        raise RuntimeError(\n"
        '            "No planned missing routes are allowed"\n'
        "        )\n"
    )
    matches = validate_pattern.findall(patched)
    if len(matches) == 1:
        patched = validate_pattern.sub(
            validate_new,
            patched,
            count=1,
        )
    elif (
        len(matches) == 0
        and "No planned missing routes are allowed"
        not in patched
    ):
        raise PatchError(
            "planned_missing 검증 기준점 누락"
        )

    self_pattern = re.compile(
        r'    for route_id in \(\n'
        r'        "us_watchlist",\n'
        r'    \):\n'
        r'        route = next\(\n'
        r'            item for item in ROUTES\n'
        r'            if item\.route_id == route_id\n'
        r'        \)\n'
        r'        assert route\.planned_missing is True\n'
        r'        assert route\.next_step\n',
        flags=re.MULTILINE,
    )
    self_new = (
        '    us_route = next(\n'
        '        item for item in ROUTES\n'
        '        if item.route_id == "us_watchlist"\n'
        '    )\n'
        '    assert us_route.required_now is True\n'
        '    assert us_route.planned_missing is False\n'
    )
    matches = self_pattern.findall(patched)
    if len(matches) == 1:
        patched = self_pattern.sub(
            self_new,
            patched,
            count=1,
        )
    elif (
        len(matches) == 0
        and "assert us_route.required_now is True"
        not in patched
    ):
        raise PatchError(
            "us_watchlist 자체시험 기준점 누락"
        )

    verify_registry(patched)
    return patched, patched != original


def verify_registry(text: str) -> None:
    required = [
        REGISTRY_MARKER,
        '"EXPECTED_CURRENT_READY_COUNT=13"',
        '"EXPECTED_CURRENT_MISSING_COUNT=0"',
        '"EXPECTED_MISSING_ROUTES="',
        '"NEXT_BUILD_ORDER="',
        "assert sum(route.required_now for route in ROUTES) == 13",
        "assert sum(route.planned_missing for route in ROUTES) == 0",
        '"thirteen_current_routes,"',
        '"zero_planned_missing_routes,"',
        'if counts["ready_total"] != 13:',
        'if counts["missing"] != 0:',
        "expected_missing = set()",
        "No planned missing routes are allowed",
        "assert us_route.required_now is True",
    ]
    for marker in required:
        if marker not in text:
            raise PatchError(
                f"registry 필수 문구 누락: {marker}"
            )

    match = route_pattern().search(text)
    if not match:
        raise PatchError("us route ready 블록 누락")
    block = match.group("block")
    if "required_now=True," not in block:
        raise PatchError(
            "us route required_now=True 누락"
        )
    if "planned_missing=True," in block:
        raise PatchError(
            "us route planned_missing 잔존"
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


def apply_patch(
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
            raise PatchError(
                f"아직 패치되지 않은 파일: {path}"
            )
        if compile_after:
            compile_python(path)
        return False

    if changed:
        temp = path.with_suffix(path.suffix + ".us.tmp")
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
        SCRIPT_VERSION = "build_api_json.py fixture"

        class TableSpec:
            def __init__(self, *args, **kwargs):
                pass

        TABLE_SPECS = (
            # ONE_MONTH_API_TABLE_SPECS_V6_END
            TableSpec(
                "kospi_gainers_1m",
                "코급표",
                "kospi_gainers_1m.json",
                ("kospi_gainers_1m_latest.csv",),
            ),
        )
        '''
    ).lstrip()


def schema_fixture() -> str:
    return textwrap.dedent(
        '''
        openapi: 3.1.0
        paths:
          /sehwankim0114/krx-watchlist-auto/main/api/bubble_risk.json:
            get:
              operationId: getBubbleRisk
          # HOLDINGS_PRIVATE_RUNTIME_ACTION_V6_BEGIN
          /sehwankim0114/krx-watchlist-auto/main/api/stock_reference_manifest.json:
            get:
              operationId: getHoldingsReferenceManifest
          # HOLDINGS_PRIVATE_RUNTIME_ACTION_V6_END
        components:
          schemas:
            AnyObject:
              type: object
        '''
    ).lstrip()


def registry_fixture() -> str:
    return textwrap.dedent(
        '''
        from dataclasses import dataclass

        # ONE_MONTH_ROUTES_READY_V6
        # HOLDINGS_PRIVATE_RUNTIME_READY_V6
        SCRIPT_VERSION = "fixture"

        @dataclass(frozen=True)
        class RouteContract:
            route_id: str
            display_name: str = ""
            request_terms: tuple[str, ...] = ()
            generation_mode: str = "DIRECT"
            source_candidates: tuple[str, ...] = ()
            api_files: tuple[str, ...] = ()
            operation_ids: tuple[str, ...] = ()
            required_now: bool = False
            planned_missing: bool = False
            next_step: str = ""

        ROUTES = (
            RouteContract(
                route_id="us_watchlist",
                display_name="미관종표",
                request_terms=("미관종표", "미국 관종표"),
                generation_mode="DIRECT",
                source_candidates=(
                    "latest/us_sp500_watchlist_latest.csv",
                ),
                api_files=("api/us_watchlist.json",),
                operation_ids=("getUsWatchlist",),
                planned_missing=True,
                next_step=(
                    "S&P500 전체 수집·점수화 후 코피표형 후보표를 만드는 "
                    "미국시장 전용 저장소 또는 생성기 필요"
                ),
            ),
        )

        def write_outputs(results):
            payload = {
                "next_build_order": [
                    "us_watchlist",
                ],
            }
            log_lines = [
                "EXPECTED_CURRENT_READY_COUNT=12",
                "EXPECTED_CURRENT_MISSING_COUNT=1",
                "EXPECTED_MISSING_ROUTES=us_watchlist",
                "NEXT_BUILD_ORDER=us_watchlist",
            ]
            return payload, log_lines

        def validate_contract_definition():
            planned_missing = {
                route.route_id for route in ROUTES
                if route.planned_missing
            }
            if planned_missing != {
                "us_watchlist",
            }:
                raise RuntimeError(
                    "Planned missing routes must be exactly one"
                )

        def run_self_test():
            assert sum(route.required_now for route in ROUTES) == 12
            assert sum(route.planned_missing for route in ROUTES) == 1

            for route_id in (
                "us_watchlist",
            ):
                route = next(
                    item for item in ROUTES
                    if item.route_id == route_id
                )
                assert route.planned_missing is True
                assert route.next_step

            tested = (
                "twelve_current_routes,"
                "one_planned_missing_route,"
            )
            return tested

        def strict_check(counts, results):
            if counts["ready_total"] != 12:
                raise SystemExit(
                    f"Expected 12 ready routes, got {counts['ready_total']}"
                )
            if counts["missing"] != 1:
                raise SystemExit(
                    f"Expected 1 missing route, got {counts['missing']}"
                )
            missing_ids = {
                row["route_id"] for row in results
                if row["status"] == "MISSING"
            }
            expected_missing = {
                "us_watchlist",
            }
            return missing_ids == expected_missing
        '''
    ).lstrip()


def run_self_test() -> int:
    cases = (
        (
            build_api_fixture(),
            patch_build_api,
            verify_build_api,
        ),
        (
            schema_fixture(),
            patch_action_schema,
            verify_action_schema,
        ),
        (
            registry_fixture(),
            patch_registry,
            verify_registry,
        ),
    )

    for original, patcher, verifier in cases:
        patched, changed = patcher(original)
        assert changed is True
        verifier(patched)

        patched_again, changed_again = patcher(patched)
        assert changed_again is False
        assert patched_again == patched

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        api_path = root / "build_api_json.py"
        schema_path = root / "schema.yaml"
        registry_path = root / "table_route_registry.py"

        api_path.write_text(
            build_api_fixture(),
            encoding="utf-8",
        )
        schema_path.write_text(
            schema_fixture(),
            encoding="utf-8",
        )
        registry_path.write_text(
            registry_fixture(),
            encoding="utf-8",
        )

        apply_patch(
            api_path,
            patch_build_api,
            verify_build_api,
            check_only=False,
            compile_after=True,
        )
        apply_patch(
            schema_path,
            patch_action_schema,
            verify_action_schema,
            check_only=False,
            compile_after=False,
        )
        apply_patch(
            registry_path,
            patch_registry,
            verify_registry,
            check_only=False,
            compile_after=True,
        )

        apply_patch(
            api_path,
            patch_build_api,
            verify_build_api,
            check_only=True,
            compile_after=True,
        )
        apply_patch(
            schema_path,
            patch_action_schema,
            verify_action_schema,
            check_only=True,
            compile_after=False,
        )
        apply_patch(
            registry_path,
            patch_registry,
            verify_registry,
            check_only=True,
            compile_after=True,
        )

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "us_api_main_30,"
        "us_api_recommend_7,"
        "us_action_operations,"
        "us_route_ready,"
        "thirteen_ready_zero_missing,"
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

    api_changed = apply_patch(
        root / "build_api_json.py",
        patch_build_api,
        verify_build_api,
        check_only=args.check_only,
        compile_after=True,
    )
    schema_changed = apply_patch(
        root / "docs/custom_gpt_action_schema.yaml",
        patch_action_schema,
        verify_action_schema,
        check_only=args.check_only,
        compile_after=False,
    )
    registry_changed = apply_patch(
        root / "table_route_registry.py",
        patch_registry,
        verify_registry,
        check_only=args.check_only,
        compile_after=True,
    )

    status = (
        "ALREADY_APPLIED"
        if args.check_only
        else (
            "APPLIED"
            if any(
                (
                    api_changed,
                    schema_changed,
                    registry_changed,
                )
            )
            else "NO_CHANGE"
        )
    )

    print(
        "US_WATCHLIST_PRODUCTION_PATCH_STATUS="
        + status
    )
    print(f"PATCH_SCRIPT_VERSION={SCRIPT_VERSION}")
    print(f"PATCH_POLICY_VERSION={POLICY_VERSION}")
    print(
        "BUILD_API_CHANGED="
        + str(api_changed).lower()
    )
    print(
        "ACTION_SCHEMA_CHANGED="
        + str(schema_changed).lower()
    )
    print(
        "TABLE_ROUTE_REGISTRY_CHANGED="
        + str(registry_changed).lower()
    )
    print("EXPECTED_READY_ROUTES=13")
    print("EXPECTED_MISSING_ROUTES=0")
    print("ALL_THIRTEEN_ROUTES_COMPLETE=true")
    print("US_WATCHLIST_PRODUCTION_PATCH=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
