#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
patch_one_month_runtime_hook_and_registry.py v1.0.0

workflow 파일을 수정하지 않고:
- run_universe_latest.py에 코피·코닥 1개월표 자동생성 호출을 추가한다.
- table_route_registry.py를 11개 정상·2개 누락 기준으로 전환한다.
'''

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Tuple


SCRIPT_VERSION = (
    "patch_one_month_runtime_hook_and_registry.py "
    "v1.0.0-no-workflow-write"
)

RUNNER_BEGIN = "# ONE_MONTH_RUNTIME_HOOK_V6_BEGIN"
RUNNER_END = "# ONE_MONTH_RUNTIME_HOOK_V6_END"
REGISTRY_MARKER = "# ONE_MONTH_ROUTES_READY_V6"


class PatchError(RuntimeError):
    pass


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def runtime_function() -> str:
    return f'''
{RUNNER_BEGIN}
def run_one_month_tables(output_dir: Path) -> int:
    # 현재 KOSPI/KOSDAQ 요약으로 두 1개월표를 생성한다.
    jobs = (
        (
            "KOSPI_ONE_MONTH",
            [
                sys.executable,
                "kospi_one_month.py",
                "--input",
                str(
                    output_dir
                    / "kospi_universe_summary_latest.csv"
                ),
                "--output-dir",
                str(output_dir),
                "--candidate-n",
                "30",
                "--recommend-n",
                "7",
            ],
        ),
        (
            "KOSDAQ_ONE_MONTH",
            [
                sys.executable,
                "kosdaq_one_month.py",
                "--input",
                str(
                    output_dir
                    / "kosdaq_universe_summary_latest.csv"
                ),
                "--output-dir",
                str(output_dir),
                "--candidate-n",
                "10",
                "--recommend-n",
                "5",
            ],
        ),
    )

    for label, command in jobs:
        print(
            f"[{{label}}] RUN: {{' '.join(command)}}",
            flush=True,
        )
        completed = subprocess.run(
            command,
            check=False,
        )
        if completed.returncode != 0:
            print(
                f"[{{label}}] FAILED="
                f"{{completed.returncode}}",
                flush=True,
            )
            return int(completed.returncode)

    print("ONE_MONTH_RUNTIME_HOOK=OK", flush=True)
    return 0
{RUNNER_END}

'''


def patch_runner(text: str) -> Tuple[str, bool]:
    original = normalize(text)

    if RUNNER_BEGIN in original:
        verify_runner(original)
        return original, False

    parse_anchor = "def parse_args() -> argparse.Namespace:\n"
    if original.count(parse_anchor) != 1:
        raise PatchError(
            "parse_args 기준점 개수 오류: "
            f"{original.count(parse_anchor)}"
        )

    patched = original.replace(
        parse_anchor,
        runtime_function() + parse_anchor,
        1,
    )

    skip_old = (
        '        print("[SKIP] Official data is already fresh.", '
        "flush=True)\n"
        "        return 0\n"
    )
    skip_new = (
        '        print("[SKIP] Official data is already fresh.", '
        "flush=True)\n"
        "        one_month_return_code = "
        "run_one_month_tables(output_dir)\n"
        "        if one_month_return_code != 0:\n"
        "            return one_month_return_code\n"
        "        return 0\n"
    )
    if patched.count(skip_old) != 1:
        raise PatchError(
            "skip 분기 기준점 개수 오류: "
            f"{patched.count(skip_old)}"
        )
    patched = patched.replace(skip_old, skip_new, 1)

    final_old = (
        "    print(json.dumps(after, ensure_ascii=False, "
        "indent=2), flush=True)\n\n"
        '    if after.get("status") == "NO_VALID_OUTPUT" '
        "and return_code != 0:\n"
    )
    final_new = (
        "    print(json.dumps(after, ensure_ascii=False, "
        "indent=2), flush=True)\n\n"
        "    one_month_return_code = "
        "run_one_month_tables(output_dir)\n"
        "    if one_month_return_code != 0:\n"
        "        return one_month_return_code\n\n"
        '    if after.get("status") == "NO_VALID_OUTPUT" '
        "and return_code != 0:\n"
    )
    if patched.count(final_old) != 1:
        raise PatchError(
            "수집 후 기준점 개수 오류: "
            f"{patched.count(final_old)}"
        )
    patched = patched.replace(final_old, final_new, 1)

    patched = re.sub(
        r'SCRIPT_VERSION\s*=\s*"run_universe_latest\.py [^"]+"',
        (
            'SCRIPT_VERSION = "run_universe_latest.py '
            'v1.5_one_month_runtime_hook"'
        ),
        patched,
        count=1,
    )

    verify_runner(patched)
    return patched, True


def verify_runner(text: str) -> None:
    required = (
        RUNNER_BEGIN,
        RUNNER_END,
        "def run_one_month_tables(output_dir: Path) -> int:",
        '"kospi_one_month.py"',
        '"kosdaq_one_month.py"',
        "ONE_MONTH_RUNTIME_HOOK=OK",
        "v1.5_one_month_runtime_hook",
    )
    for item in required:
        if item not in text:
            raise PatchError(f"runner 필수 문구 누락: {item}")

    call = (
        "one_month_return_code = "
        "run_one_month_tables(output_dir)"
    )
    if text.count(call) != 2:
        raise PatchError(
            f"runtime 호출 개수 오류: {text.count(call)}"
        )


def route_pattern(route_id: str) -> re.Pattern[str]:
    return re.compile(
        rf'(?P<block>^    RouteContract\(\n'
        rf'        route_id="{re.escape(route_id)}",'
        rf'.*?^    \),$)',
        flags=re.DOTALL | re.MULTILINE,
    )


def patch_route(text: str, route_id: str) -> str:
    match = route_pattern(route_id).search(text)
    if not match:
        raise PatchError(f"route 블록 누락: {route_id}")

    block = match.group("block")
    if "required_now=True," in block:
        if "planned_missing=True," in block:
            raise PatchError(
                f"{route_id}: ready/missing 동시존재"
            )
        return text

    if "planned_missing=True," not in block:
        raise PatchError(
            f"{route_id}: planned_missing 기준점 누락"
        )

    new_block = block.replace(
        "planned_missing=True,",
        "required_now=True,",
        1,
    )
    new_block = re.sub(
        r'\n        next_step="[^"]*",',
        "",
        new_block,
        count=1,
    )

    return (
        text[:match.start("block")]
        + new_block
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
        anchor = "SCRIPT_VERSION ="
        index = patched.find(anchor)
        if index < 0:
            raise PatchError("registry SCRIPT_VERSION 누락")
        patched = (
            patched[:index]
            + REGISTRY_MARKER
            + "\n"
            + patched[index:]
        )

    patched = patch_route(patched, "kospi_1m")
    patched = patch_route(patched, "kosdaq_1m")

    changes = (
        (
            '        "next_build_order": [\n'
            '            "kospi_1m",\n'
            '            "kosdaq_1m",\n'
            '            "holdings",\n'
            '            "us_watchlist",\n'
            '        ],\n',
            '        "next_build_order": [\n'
            '            "holdings",\n'
            '            "us_watchlist",\n'
            '        ],\n',
            "next_build_order",
        ),
        (
            '"EXPECTED_CURRENT_READY_COUNT=9"',
            '"EXPECTED_CURRENT_READY_COUNT=11"',
            "ready count",
        ),
        (
            '"EXPECTED_CURRENT_MISSING_COUNT=4"',
            '"EXPECTED_CURRENT_MISSING_COUNT=2"',
            "missing count",
        ),
        (
            '"EXPECTED_MISSING_ROUTES='
            'kospi_1m,kosdaq_1m,holdings,us_watchlist"',
            '"EXPECTED_MISSING_ROUTES=holdings,us_watchlist"',
            "missing routes",
        ),
        (
            '"NEXT_BUILD_ORDER='
            'kospi_1m,kosdaq_1m,holdings,us_watchlist"',
            '"NEXT_BUILD_ORDER=holdings,us_watchlist"',
            "next order",
        ),
        (
            '    if planned_missing != {\n'
            '        "kospi_1m",\n'
            '        "kosdaq_1m",\n'
            '        "holdings",\n'
            '        "us_watchlist",\n'
            '    }:\n',
            '    if planned_missing != {\n'
            '        "holdings",\n'
            '        "us_watchlist",\n'
            '    }:\n',
            "planned missing set",
        ),
        (
            '"Planned missing routes must be exactly four"',
            '"Planned missing routes must be exactly two"',
            "planned missing text",
        ),
        (
            "assert sum(route.required_now for route in ROUTES) == 9",
            "assert sum(route.required_now for route in ROUTES) == 11",
            "self ready",
        ),
        (
            "assert sum(route.planned_missing for route in ROUTES) == 4",
            "assert sum(route.planned_missing for route in ROUTES) == 2",
            "self missing",
        ),
        (
            '    for route_id in (\n'
            '        "kospi_1m",\n'
            '        "kosdaq_1m",\n'
            '        "holdings",\n'
            '        "us_watchlist",\n'
            '    ):\n',
            '    for route_id in (\n'
            '        "holdings",\n'
            '        "us_watchlist",\n'
            '    ):\n',
            "self missing loop",
        ),
        (
            '"nine_current_routes,"',
            '"eleven_current_routes,"',
            "self ready label",
        ),
        (
            '"four_planned_missing_routes,"',
            '"two_planned_missing_routes,"',
            "self missing label",
        ),
        (
            'if counts["ready_total"] != 9:',
            'if counts["ready_total"] != 11:',
            "strict ready",
        ),
        (
            'f"Expected 9 ready routes, got '
            '{counts[\'ready_total\']}"',
            'f"Expected 11 ready routes, got '
            '{counts[\'ready_total\']}"',
            "strict ready text",
        ),
        (
            'if counts["missing"] != 4:',
            'if counts["missing"] != 2:',
            "strict missing",
        ),
        (
            'f"Expected 4 missing routes, got '
            '{counts[\'missing\']}"',
            'f"Expected 2 missing routes, got '
            '{counts[\'missing\']}"',
            "strict missing text",
        ),
        (
            '        expected_missing = {\n'
            '            "kospi_1m",\n'
            '            "kosdaq_1m",\n'
            '            "holdings",\n'
            '            "us_watchlist",\n'
            '        }\n',
            '        expected_missing = {\n'
            '            "holdings",\n'
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
        '"EXPECTED_CURRENT_READY_COUNT=11"',
        '"EXPECTED_CURRENT_MISSING_COUNT=2"',
        '"EXPECTED_MISSING_ROUTES=holdings,us_watchlist"',
        '"NEXT_BUILD_ORDER=holdings,us_watchlist"',
        "assert sum(route.required_now for route in ROUTES) == 11",
        "assert sum(route.planned_missing for route in ROUTES) == 2",
        'if counts["ready_total"] != 11:',
        'if counts["missing"] != 2:',
        '"eleven_current_routes,"',
        '"two_planned_missing_routes,"',
    )
    for item in required:
        if item not in text:
            raise PatchError(f"registry 필수 문구 누락: {item}")

    for route_id in ("kospi_1m", "kosdaq_1m"):
        match = route_pattern(route_id).search(text)
        if not match:
            raise PatchError(f"ready route 누락: {route_id}")
        block = match.group("block")
        if "required_now=True," not in block:
            raise PatchError(f"{route_id}: required_now 누락")
        if "planned_missing=True," in block:
            raise PatchError(
                f"{route_id}: planned_missing 잔존"
            )


def compile_python(path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PatchError(
            f"문법검사 실패: {path}\n{result.stderr}"
        )


def apply_patch(
    path: Path,
    patcher,
    verifier,
    *,
    check_only: bool,
) -> bool:
    original = path.read_text(encoding="utf-8")
    patched, changed = patcher(original)
    verifier(patched)

    if check_only:
        if changed:
            raise PatchError(f"미적용 상태: {path}")
        compile_python(path)
        return False

    if changed:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(patched, encoding="utf-8")
        compile_python(temp)
        temp.replace(path)
    else:
        compile_python(path)

    verifier(path.read_text(encoding="utf-8"))
    return changed


def runner_fixture() -> str:
    return textwrap.dedent(
        '''
        import argparse
        import json
        import subprocess
        import sys
        from pathlib import Path

        SCRIPT_VERSION = "run_universe_latest.py v1.4_publication_cutoff_sync"

        def parse_args() -> argparse.Namespace:
            return argparse.ArgumentParser().parse_args()

        def main() -> int:
            output_dir = Path("latest")
            before = {"fresh": True}
            if before["fresh"]:
                print("[SKIP] Official data is already fresh.", flush=True)
                return 0
            return_code = 0
            after = {"status": "FRESH"}
            print(json.dumps(after, ensure_ascii=False, indent=2), flush=True)

            if after.get("status") == "NO_VALID_OUTPUT" and return_code != 0:
                return return_code
            return 0
        '''
    ).lstrip()


def registry_fixture() -> str:
    return textwrap.dedent(
        '''
        from dataclasses import dataclass
        SCRIPT_VERSION = "fixture"

        @dataclass(frozen=True)
        class RouteContract:
            route_id: str
            source_candidates: tuple[str, ...] = ()
            required_now: bool = False
            planned_missing: bool = False
            next_step: str = ""

        ROUTES = (
            RouteContract(
                route_id="kospi_1m",
                source_candidates=("a", "b"),
                planned_missing=True,
                next_step="a",
            ),
            RouteContract(
                route_id="kosdaq_1m",
                source_candidates=("c", "d"),
                planned_missing=True,
                next_step="b",
            ),
            RouteContract(route_id="holdings", planned_missing=True),
            RouteContract(route_id="us_watchlist", planned_missing=True),
        )

        def output():
            payload = {
                "next_build_order": [
                    "kospi_1m",
                    "kosdaq_1m",
                    "holdings",
                    "us_watchlist",
                ],
            }
            logs = [
                "EXPECTED_CURRENT_READY_COUNT=9",
                "EXPECTED_CURRENT_MISSING_COUNT=4",
                "EXPECTED_MISSING_ROUTES=kospi_1m,kosdaq_1m,holdings,us_watchlist",
                "NEXT_BUILD_ORDER=kospi_1m,kosdaq_1m,holdings,us_watchlist",
            ]
            return payload, logs

        def validate():
            planned_missing = {
                route.route_id for route in ROUTES
                if route.planned_missing
            }
            if planned_missing != {
                "kospi_1m",
                "kosdaq_1m",
                "holdings",
                "us_watchlist",
            }:
                raise RuntimeError(
                    "Planned missing routes must be exactly four"
                )

        def self_test():
            assert sum(route.required_now for route in ROUTES) == 9
            assert sum(route.planned_missing for route in ROUTES) == 4
            for route_id in (
                "kospi_1m",
                "kosdaq_1m",
                "holdings",
                "us_watchlist",
            ):
                pass
            tested = (
                "nine_current_routes,"
                "four_planned_missing_routes,"
            )
            return tested

        def strict(counts):
            if counts["ready_total"] != 9:
                raise SystemExit(
                    f"Expected 9 ready routes, got {counts['ready_total']}"
                )
            if counts["missing"] != 4:
                raise SystemExit(
                    f"Expected 4 missing routes, got {counts['missing']}"
                )
            if True:
                expected_missing = {
                    "kospi_1m",
                    "kosdaq_1m",
                    "holdings",
                    "us_watchlist",
                }
            return expected_missing
        '''
    ).lstrip()


def run_self_test() -> int:
    first, changed = patch_runner(runner_fixture())
    assert changed
    verify_runner(first)
    second, changed = patch_runner(first)
    assert not changed
    assert second == first

    first, changed = patch_registry(registry_fixture())
    assert changed
    verify_registry(first)
    second, changed = patch_registry(first)
    assert not changed
    assert second == first

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        runner = root / "run_universe_latest.py"
        registry = root / "table_route_registry.py"
        runner.write_text(runner_fixture(), encoding="utf-8")
        registry.write_text(registry_fixture(), encoding="utf-8")

        apply_patch(
            runner,
            patch_runner,
            verify_runner,
            check_only=False,
        )
        apply_patch(
            registry,
            patch_registry,
            verify_registry,
            check_only=False,
        )
        apply_patch(
            runner,
            patch_runner,
            verify_runner,
            check_only=True,
        )
        apply_patch(
            registry,
            patch_registry,
            verify_registry,
            check_only=True,
        )

    print("SELF_TEST_STATUS=OK")
    print(
        "TESTED="
        "skip_hook,after_collect_hook,"
        "kospi_30_7,kosdaq_10_5,"
        "registry_11_2,idempotency,"
        "no_workflow_write"
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
    runner = root / "run_universe_latest.py"
    registry = root / "table_route_registry.py"

    runner_changed = apply_patch(
        runner,
        patch_runner,
        verify_runner,
        check_only=args.check_only,
    )
    registry_changed = apply_patch(
        registry,
        patch_registry,
        verify_registry,
        check_only=args.check_only,
    )

    status = (
        "ALREADY_APPLIED"
        if args.check_only
        else (
            "APPLIED"
            if runner_changed or registry_changed
            else "NO_CHANGE"
        )
    )

    print(
        "ONE_MONTH_RUNTIME_HOOK_PATCH_STATUS="
        + status
    )
    print(f"PATCH_SCRIPT_VERSION={SCRIPT_VERSION}")
    print(
        "RUN_UNIVERSE_CHANGED="
        + str(runner_changed).lower()
    )
    print(
        "TABLE_ROUTE_REGISTRY_CHANGED="
        + str(registry_changed).lower()
    )
    print("WORKFLOW_FILES_CHANGED=false")
    print("EXPECTED_READY_ROUTES=11")
    print("EXPECTED_MISSING_ROUTES=2")
    print("REMAINING_MISSING_ROUTES=holdings,us_watchlist")
    print("ONE_MONTH_RUNTIME_HOOK_PATCH=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
