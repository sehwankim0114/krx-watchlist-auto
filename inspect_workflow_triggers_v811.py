#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only inspection of top-level GitHub Actions workflow triggers."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

try:
    import yaml
except ImportError as exc:  # pragma: no cover - checked by workflow
    raise SystemExit(
        "PyYAML is required: python -m pip install PyYAML"
    ) from exc


ROOT = Path(__file__).resolve().parent
WORKFLOW_DIR = ROOT / ".github" / "workflows"

KEEP_WORKFLOWS = {
    "build_api_json.yml",
    "collect-krx-watchlist.yml",
    "dart-fx-exposure-safe.yml",
    "maintenance-repair.yml",
    "safe-repository-cleanup.yml",
    "v731-daily-integrated-health.yml",
}

ARCHIVE_CANDIDATES = {
    "apply-custom-gpt-v5-hardening.yml",
    "apply-request-time-price-v51.yml",
    "dart-fx-exposure.yml",
    "fix-rules-version-contract.yml",
    "v6-apply-explanation-manual-policy.yml",
    "v6-apply-explanation-policy-and-quote-keys.yml",
    "v6-apply-holdings-private-runtime.yml",
    "v6-apply-lightweight-kospi-kosdaq-watchlists-v66.yml",
    "v6-apply-one-month-production-routes.yml",
    "v6-apply-one-month-routes-no-workflow-write.yml",
    "v6-apply-one-month-universe-metrics-patch.yml",
    "v6-apply-output-order-and-price-retry-v65.yml",
    "v6-apply-quote-key-aliases-v64.yml",
    "v6-apply-us-sp500-production.yml",
    "v6-financial-valuation-enricher-test.yml",
    "v6-holdings-generator-test.yml",
    "v6-kosdaq-one-month-generator-test.yml",
    "v6-kospi-one-month-generator-test.yml",
    "v6-legacy-market-score-alias-test.yml",
    "v6-market-metric-standards-test.yml",
    "v6-request-time-explanation-refresh-test.yml",
    "v6-supply-burden-status-separation-test.yml",
    "v6-thirteen-table-route-registry-test.yml",
    "v6-us-sp500-live-collector-test.yml",
    "v6-us-sp500-watchlist-generator-test.yml",
    "v7-apply-final-display-contract-v71.yml",
    "v72-apply-korean-sector-theme.yml",
    "v75-restore-activity-elasticity.yml",
    "v76-link-financial-valuation.yml",
    "v761-compact-financial-payload.yml",
    "v762-complete-financial-link-after-manual-workflow-update.yml",
    "v77-runtime-freshness-gate.yml",
    "v78-price-range-position-upgrade.yml",
    "v79-recommendation-icon-integrity.yml",
    "v80-request-time-position-alignment.yml",
    "v81-archive-obsolete-workflows.yml",
}

DIAGNOSTIC_WORKFLOWS = {
    "v811-inspect-workflow-triggers.yml",
}

AUTOMATIC_TRIGGERS = {
    "schedule",
    "workflow_run",
    "push",
    "pull_request",
    "pull_request_target",
    "repository_dispatch",
    "workflow_call",
}


class InspectionError(RuntimeError):
    """Raised when a workflow cannot be inspected safely."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def workflow_files(directory: Path) -> List[Path]:
    paths = list(directory.glob("*.yml"))
    paths.extend(directory.glob("*.yaml"))
    return sorted(set(paths), key=lambda path: path.name)


def parse_yaml(text: str, filename: str) -> Mapping[str, Any]:
    try:
        payload = yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        raise InspectionError(
            f"YAML parse failed for {filename}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise InspectionError(
            f"Workflow root must be a mapping: {filename}"
        )
    return payload


def trigger_names(on_value: Any) -> List[str]:
    if on_value is None:
        return []
    if isinstance(on_value, str):
        return [on_value]
    if isinstance(on_value, Mapping):
        return sorted(str(key) for key in on_value)
    if isinstance(on_value, Sequence) and not isinstance(
        on_value, (str, bytes)
    ):
        return sorted(str(item) for item in on_value)
    raise InspectionError(
        f"Unsupported top-level on value: {type(on_value).__name__}"
    )


def category_for(filename: str) -> str:
    if filename in KEEP_WORKFLOWS:
        return "KEEP_OPERATIONAL"
    if filename in ARCHIVE_CANDIDATES:
        return "ARCHIVE_CANDIDATE"
    if filename in DIAGNOSTIC_WORKFLOWS:
        return "DIAGNOSTIC"
    return "UNKNOWN_REVIEW"


def disposition(category: str, triggers: Iterable[str]) -> str:
    trigger_set = set(triggers)
    automatic = sorted(trigger_set & AUTOMATIC_TRIGGERS)
    if category == "KEEP_OPERATIONAL":
        return "KEEP"
    if category == "DIAGNOSTIC":
        return "KEEP_UNTIL_DIAGNOSIS_COMPLETE"
    if category == "UNKNOWN_REVIEW":
        return "BLOCK_UNKNOWN"
    if automatic:
        return "BLOCK_AUTOMATIC"
    if "workflow_dispatch" not in trigger_set:
        return "BLOCK_UNCLASSIFIED"
    return "READY_TO_ARCHIVE"


def inspect_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    payload = parse_yaml(text, path.name)
    triggers = trigger_names(payload.get("on"))
    automatic = sorted(set(triggers) & AUTOMATIC_TRIGGERS)
    category = category_for(path.name)
    return {
        "filename": path.name,
        "category": category,
        "triggers": triggers,
        "automatic_triggers": automatic,
        "has_workflow_dispatch": "workflow_dispatch" in triggers,
        "disposition": disposition(category, triggers),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def summarize(records: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    dispositions = [str(record["disposition"]) for record in records]
    return {
        "workflow_count": len(records),
        "keep_count": dispositions.count("KEEP"),
        "diagnostic_count": dispositions.count(
            "KEEP_UNTIL_DIAGNOSIS_COMPLETE"
        ),
        "manual_archive_ready_count": dispositions.count(
            "READY_TO_ARCHIVE"
        ),
        "blocked_automatic_count": dispositions.count(
            "BLOCK_AUTOMATIC"
        ),
        "blocked_unclassified_count": dispositions.count(
            "BLOCK_UNCLASSIFIED"
        ),
        "unknown_count": dispositions.count("BLOCK_UNKNOWN"),
    }


def run_inspection(directory: Path) -> Dict[str, Any]:
    if not directory.exists():
        raise InspectionError(f"Workflow directory missing: {directory}")
    paths = workflow_files(directory)
    if not paths:
        raise InspectionError(f"No workflow files found: {directory}")
    records = [inspect_file(path) for path in paths]
    present = {path.name for path in paths}
    missing_keep = sorted(KEEP_WORKFLOWS - present)
    summary = summarize(records)
    summary["missing_keep_count"] = len(missing_keep)
    return {
        "schema_version": "1.0",
        "tool_version": "2026-07-15-v8.1.1-read-only-trigger-inspection",
        "mode": "READ_ONLY",
        "workflow_directory": str(directory),
        "summary": summary,
        "missing_keep_workflows": missing_keep,
        "records": records,
    }


def self_test() -> None:
    manual = """
name: Manual only
on:
  workflow_dispatch:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo 'push:'
          echo 'schedule:'
"""
    automatic = """
name: Scheduled
on:
  workflow_dispatch:
  schedule:
    - cron: '0 0 * * *'
jobs: {}
"""
    compact = """
name: Push
on: [push, workflow_dispatch]
jobs: {}
"""
    assert trigger_names(parse_yaml(manual, "manual.yml").get("on")) == [
        "workflow_dispatch"
    ]
    assert trigger_names(
        parse_yaml(automatic, "automatic.yml").get("on")
    ) == ["schedule", "workflow_dispatch"]
    assert trigger_names(parse_yaml(compact, "compact.yml").get("on")) == [
        "push",
        "workflow_dispatch",
    ]
    assert disposition(
        "ARCHIVE_CANDIDATE", ["workflow_dispatch"]
    ) == "READY_TO_ARCHIVE"
    assert disposition(
        "ARCHIVE_CANDIDATE", ["workflow_dispatch", "schedule"]
    ) == "BLOCK_AUTOMATIC"
    assert disposition("UNKNOWN_REVIEW", ["workflow_dispatch"]) == (
        "BLOCK_UNKNOWN"
    )
    print("V811_SELF_TEST=PASS")


def print_report(report: Mapping[str, Any]) -> None:
    summary = report["summary"]
    print("WORKFLOW_TRIGGER_INSPECTION_BEGIN")
    for record in report["records"]:
        triggers = ",".join(record["triggers"]) or "NONE"
        automatic = ",".join(record["automatic_triggers"]) or "NONE"
        print(
            "WORKFLOW_TRIGGER_RECORD="
            f"{record['filename']}|{record['category']}|"
            f"{triggers}|{automatic}|{record['disposition']}"
        )
    print("WORKFLOW_TRIGGER_INSPECTION_END")
    for key, value in summary.items():
        print(f"{key.upper()}={value}")
    missing_keep = report.get("missing_keep_workflows", [])
    print(
        "MISSING_KEEP_WORKFLOWS="
        + (",".join(missing_keep) if missing_keep else "NONE")
    )
    print("WORKFLOW_TRIGGER_INSPECTION=PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workflow-dir",
        type=Path,
        default=WORKFLOW_DIR,
    )
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0

    report = run_inspection(args.workflow_dir)
    print_report(report)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"JSON_REPORT={args.json_out}")
    print("DRY_RUN_NO_REPOSITORY_CHANGES=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InspectionError as exc:
        print(f"WORKFLOW_TRIGGER_INSPECTION=FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
