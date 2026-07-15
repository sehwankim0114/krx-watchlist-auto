#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install the V8.2 command-route contract into build_api_json.py."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "build_api_json.py"
MODULE = ROOT / "table_command_routes_v82.py"
IMPORT_LINE = (
    "from table_command_routes_v82 import "
    "attach_command_route_contract_v82"
)
CALL_LINE = (
    "manifest_payload = "
    "attach_command_route_contract_v82(manifest_payload)"
)


class PatchError(RuntimeError):
    """Raised when a safe, unique patch anchor cannot be found."""


def patch_text(text: str) -> str:
    updated = text

    if IMPORT_LINE not in updated:
        updated, count = re.subn(
            r"^(import pandas as pd\s*)$",
            r"\1\n" + IMPORT_LINE,
            updated,
            count=1,
            flags=re.M,
        )
        if count != 1:
            raise PatchError(f"pandas import anchor count={count}")

    if CALL_LINE not in updated:
        pattern = (
            r"^(?P<indent>[ \t]*)"
            r"write_json\(API\s*/\s*[\"']manifest\.json[\"']\s*,\s*"
            r"manifest_payload\)\s*$"
        )

        def replacement(match: re.Match[str]) -> str:
            indent = match.group("indent")
            return (
                f"{indent}{CALL_LINE}\n"
                f"{match.group(0)}"
            )

        updated, count = re.subn(
            pattern,
            replacement,
            updated,
            count=1,
            flags=re.M,
        )
        if count != 1:
            raise PatchError(f"manifest write anchor count={count}")

    if updated.count(IMPORT_LINE) != 1:
        raise PatchError("V8.2 import must appear exactly once")
    if updated.count(CALL_LINE) != 1:
        raise PatchError("V8.2 attachment call must appear exactly once")
    return updated


def self_test() -> None:
    sample = '''import json
import pandas as pd

def main():
    manifest_payload = {"tables": [], "snapshots": []}
    write_json(API / "manifest.json", manifest_payload)
'''
    first = patch_text(sample)
    second = patch_text(first)
    assert first == second
    assert first.count(IMPORT_LINE) == 1
    assert first.count(CALL_LINE) == 1
    print("PATCH_TABLE_COMMAND_ROUTES_V82_SELF_TEST=PASS")


def apply_patch() -> None:
    if not TARGET.exists():
        raise PatchError(f"missing target: {TARGET}")
    if not MODULE.exists():
        raise PatchError(f"missing contract module: {MODULE}")
    before = TARGET.read_text(encoding="utf-8")
    after = patch_text(before)
    TARGET.write_text(after, encoding="utf-8")
    print(f"TARGET={TARGET.relative_to(ROOT)}")
    print(f"CHANGED={str(before != after).lower()}")
    print("TABLE_COMMAND_ROUTE_PATCH_V82=PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        apply_patch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
