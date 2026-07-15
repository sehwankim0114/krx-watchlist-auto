#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prevent the scheduled V7.7 runtime gate from downgrading global rules."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Match


ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "v77-runtime-freshness-gate.yml"
PATCHER = ROOT / "patch_runtime_freshness_v77.py"
RULES = ROOT / "docs" / "stock_table_rules_latest.md"
GLOBAL_RULES_VERSION = "2026-07-14-v8.0-request-time-position-alignment"
V77_COMPONENT_VERSION = "2026-07-14-v7.7-runtime-freshness-gate"
PROTECTION_MARKER = "V822_GLOBAL_RULES_VERSION_PROTECTION"


class RepairError(RuntimeError):
    """Raised when a unique and safe repair anchor cannot be found."""


def replace_once(
    text: str,
    pattern: str,
    replacement: str,
    *,
    label: str,
    flags: int = 0,
) -> str:
    updated, count = re.subn(
        pattern,
        replacement,
        text,
        count=1,
        flags=flags,
    )
    if count != 1:
        raise RepairError(f"{label} replacement count={count}")
    return updated


def patch_workflow_text(text: str) -> str:
    updated = text

    # Installation belongs to the original one-time rollout.  A scheduled
    # freshness refresh must not rewrite build_api_json.py or the rules file.
    install_pattern = (
        r"^      - name: Install V7\.7 into full API build\n"
        r".*?"
        r"(?=^      - name: Verify stale scenario self-test\n)"
    )
    if re.search(install_pattern, updated, flags=re.M | re.S):
        updated = replace_once(
            updated,
            install_pattern,
            "",
            label="scheduled install step",
            flags=re.M | re.S,
        )

    if "python patch_runtime_freshness_v77.py" in updated:
        raise RepairError("scheduled workflow still invokes the V7.7 patcher")

    git_add_pattern = (
        r"^(?P<indent>[ \t]*)git add[ \t]+\\\n"
        r"(?:^[ \t]+.*\\\n)*"
        r"^[ \t]+api[ \t]*$"
    )

    def git_add_replacement(match: Match[str]) -> str:
        return f"{match.group('indent')}git add api"

    if re.search(r"^[ \t]*git add api[ \t]*$", updated, flags=re.M):
        count = 1
    else:
        updated, count = re.subn(
            git_add_pattern,
            git_add_replacement,
            updated,
            count=1,
            flags=re.M | re.S,
        )
        if count != 1:
            raise RepairError(f"scheduled git add replacement count={count}")

    updated = updated.replace(
        'git commit -m "Add current-time official freshness gate v7.7"',
        'git commit -m "Refresh current-time official freshness status"',
    )

    if PROTECTION_MARKER not in updated:
        anchor = "      - name: Commit and push\n"
        if updated.count(anchor) != 1:
            raise RepairError(
                f"commit step anchor count={updated.count(anchor)}"
            )
        protection = r'''      - name: Protect global rules version
        run: |
          set -euo pipefail
          python - <<'PY'
          import json
          import re
          from pathlib import Path

          marker = "V822_GLOBAL_RULES_VERSION_PROTECTION"
          rules_text = Path(
              "docs/stock_table_rules_latest.md"
          ).read_text(encoding="utf-8")
          match = re.search(
              r"- 규칙 버전:\s*`([^`]+)`",
              rules_text,
          )
          if not match:
              raise SystemExit("global rules version header missing")
          global_version = match.group(1)
          if global_version == (
              "2026-07-14-v7.7-runtime-freshness-gate"
          ):
              raise SystemExit("global rules version downgraded to V7.7")

          for filename in (
              "status.json",
              "stock_table_rules.json",
              "manifest.json",
          ):
              payload = json.loads(
                  (Path("api") / filename).read_text(encoding="utf-8")
              )
              if filename == "manifest.json":
                  api_version = (payload.get("rules") or {}).get("version")
              else:
                  api_version = payload.get("rules_version")
              if api_version != global_version:
                  raise SystemExit(
                      f"{filename}: rules version mismatch "
                      f"{api_version} != {global_version}"
                  )

          print(f"{marker}=PASS")
          print(f"GLOBAL_RULES_VERSION={global_version}")
          PY

'''
        updated = updated.replace(anchor, protection + anchor, 1)

    required = (
        "schedule:",
        "python refresh_runtime_freshness_v77.py --repo-root .",
        "git add api",
        PROTECTION_MARKER,
        "Refresh current-time official freshness status",
    )
    for token in required:
        if token not in updated:
            raise RepairError(f"workflow token missing: {token}")
    return updated


def patch_patcher_text(text: str) -> str:
    if PROTECTION_MARKER in text:
        return text

    anchor = '    text = RULES.read_text(encoding="utf-8")\n'
    if text.count(anchor) != 1:
        raise RepairError(f"rules read anchor count={text.count(anchor)}")

    guard = r'''    # V822_GLOBAL_RULES_VERSION_PROTECTION
    version_match = re.search(
        r"- 규칙 버전:\s*`([^`]+)`",
        text,
    )
    current_version = version_match.group(1) if version_match else ""

    def version_tuple(value: str):
        match = re.search(r"-v(\d+)\.(\d+)", value)
        return tuple(map(int, match.groups())) if match else (0, 0)

    if version_tuple(current_version) > (7, 7):
        print(
            "PRESERVE_NEWER_GLOBAL_RULES_VERSION="
            + current_version
        )
    else:
        text, count = re.subn(
            r"(- 규칙 버전:\s*`)[^`]+(`)",
            rf"\g<1>{VERSION}\g<2>",
            text,
            count=1,
        )
        if count != 1:
            raise PatchError(f"규칙 버전 교체 수 오류: {count}")
'''
    updated = text.replace(anchor, anchor + guard, 1)

    old_replacement = r'''    text, count = re.subn(
        r"(- 규칙 버전:\s*`)[^`]+(`)",
        rf"\g<1>{VERSION}\g<2>",
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(f"규칙 버전 교체 수 오류: {count}")

'''
    if updated.count(old_replacement) != 1:
        raise RepairError(
            "original V7.7 rules replacement block not found exactly once"
        )
    updated = updated.replace(old_replacement, "", 1)
    return updated


def restore_rules_text(text: str) -> str:
    updated, count = re.subn(
        r"(- 규칙 버전:\s*`)[^`]+(`)",
        rf"\g<1>{GLOBAL_RULES_VERSION}\g<2>",
        text,
        count=1,
    )
    if count != 1:
        raise RepairError(f"global rules restore count={count}")
    if "<!-- REQUEST_TIME_POSITION_V80 -->" not in updated:
        raise RepairError("V8.0 request-time position rule marker missing")
    return updated


def self_test() -> None:
    workflow_sample = r'''name: V77 Runtime Freshness Gate
on:
  workflow_dispatch:
  schedule:
    - cron: "0 0 * * *"
jobs:
  refresh:
    steps:
      - name: Install V7.7 into full API build
        run: |
          python patch_runtime_freshness_v77.py
      - name: Verify stale scenario self-test
        run: echo test
      - name: Refresh runtime freshness now
        run: |
          python refresh_runtime_freshness_v77.py --repo-root .
      - name: Commit and push
        run: |
          git add \
            refresh_runtime_freshness_v77.py \
            patch_runtime_freshness_v77.py \
            build_api_json.py \
            docs/stock_table_rules_latest.md \
            api

          if ! git diff --cached --quiet; then
            git commit -m "Add current-time official freshness gate v7.7"
          fi
'''
    patched = patch_workflow_text(workflow_sample)
    assert "python patch_runtime_freshness_v77.py" not in patched
    assert "git add api" in patched
    assert PROTECTION_MARKER in patched
    assert patch_workflow_text(patched) == patched

    patcher_sample = '''import re
def patch_rules():
    text = RULES.read_text(encoding="utf-8")
    text, count = re.subn(
        r"(- 규칙 버전:\\s*`)[^`]+(`)",
        rf"\\g<1>{VERSION}\\g<2>",
        text,
        count=1,
    )
    if count != 1:
        raise PatchError(f"규칙 버전 교체 수 오류: {count}")

    if RULE_MARKER not in text:
        pass
'''
    hardened = patch_patcher_text(patcher_sample)
    assert PROTECTION_MARKER in hardened
    assert patch_patcher_text(hardened) == hardened
    print("REPAIR_RUNTIME_FRESHNESS_RULES_V822_SELF_TEST=PASS")


def apply_repair() -> None:
    for path in (WORKFLOW, PATCHER, RULES):
        if not path.exists():
            raise RepairError(f"required file missing: {path}")

    workflow_before = WORKFLOW.read_text(encoding="utf-8")
    patcher_before = PATCHER.read_text(encoding="utf-8")
    rules_before = RULES.read_text(encoding="utf-8")

    workflow_after = patch_workflow_text(workflow_before)
    patcher_after = patch_patcher_text(patcher_before)
    rules_after = restore_rules_text(rules_before)

    WORKFLOW.write_text(workflow_after, encoding="utf-8")
    PATCHER.write_text(patcher_after, encoding="utf-8")
    RULES.write_text(rules_after, encoding="utf-8")

    print(f"WORKFLOW_CHANGED={str(workflow_before != workflow_after).lower()}")
    print(f"PATCHER_CHANGED={str(patcher_before != patcher_after).lower()}")
    print(f"RULES_CHANGED={str(rules_before != rules_after).lower()}")
    print(f"RESTORED_GLOBAL_RULES_VERSION={GLOBAL_RULES_VERSION}")
    print("SCHEDULED_V77_PATCHER_DISABLED=PASS")
    print("V77_NEWER_RULES_DOWNGRADE_GUARD=PASS")
    print("RUNTIME_FRESHNESS_RULES_REPAIR_V822=PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        apply_repair()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
