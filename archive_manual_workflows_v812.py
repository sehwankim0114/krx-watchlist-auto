#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Archive completed manual-only workflows while preserving live schedules."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set

try:
    import yaml
except ImportError as exc:  # pragma: no cover - checked by workflow
    raise SystemExit(
        "PyYAML is required: python -m pip install PyYAML"
    ) from exc

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


ROOT = Path(__file__).resolve().parent
WORKFLOW_DIR = ROOT / ".github" / "workflows"
ARCHIVE_DIR = ROOT / "docs" / "workflow_archive" / "2026-07-15"
MANIFEST_PATH = ARCHIVE_DIR / "workflow_archive_manifest.json"
README_PATH = ARCHIVE_DIR / "README.md"

EXPECTED_KEEP_TRIGGERS: Dict[str, Set[str]] = {
    "build_api_json.yml": {
        "schedule",
        "workflow_dispatch",
        "workflow_run",
    },
    "collect-krx-watchlist.yml": {
        "schedule",
        "workflow_dispatch",
    },
    "dart-fx-exposure-safe.yml": {
        "schedule",
        "workflow_dispatch",
    },
    "maintenance-repair.yml": {"workflow_dispatch"},
    "safe-repository-cleanup.yml": {"workflow_dispatch"},
    "v6-apply-us-sp500-production.yml": {
        "schedule",
        "workflow_dispatch",
    },
    "v731-daily-integrated-health.yml": {
        "schedule",
        "workflow_dispatch",
    },
    "v77-runtime-freshness-gate.yml": {
        "schedule",
        "workflow_dispatch",
    },
}

ARCHIVE_WORKFLOWS = [
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
    "v78-price-range-position-upgrade.yml",
    "v79-recommendation-icon-integrity.yml",
    "v80-request-time-position-alignment.yml",
    "v81-archive-obsolete-workflows.yml",
    "v811-inspect-workflow-triggers.yml",
    "v812-archive-manual-workflows.yml",
]


class ArchiveError(RuntimeError):
    """Raised before push when safe archival conditions are not met."""


def now_kst() -> str:
    if ZoneInfo is None:
        return datetime.utcnow().isoformat(timespec="seconds") + "+09:00"
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


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
        raise ArchiveError(f"YAML parse failed for {filename}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ArchiveError(f"Workflow root must be a mapping: {filename}")
    return payload


def trigger_names(payload: Mapping[str, Any], filename: str) -> Set[str]:
    value = payload.get("on")
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        return {str(key) for key in value}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return {str(item) for item in value}
    raise ArchiveError(
        f"Unsupported top-level on value in {filename}: "
        f"{type(value).__name__}"
    )


def inspect_triggers(path: Path) -> Set[str]:
    payload = parse_yaml(path.read_text(encoding="utf-8"), path.name)
    return trigger_names(payload, path.name)


def validate_before_move() -> List[Dict[str, Any]]:
    if not WORKFLOW_DIR.exists():
        raise ArchiveError(f"Workflow directory missing: {WORKFLOW_DIR}")

    current_paths = workflow_files(WORKFLOW_DIR)
    current_names = {path.name for path in current_paths}
    expected_names = set(EXPECTED_KEEP_TRIGGERS) | set(ARCHIVE_WORKFLOWS)

    missing_keep = sorted(set(EXPECTED_KEEP_TRIGGERS) - current_names)
    if missing_keep:
        raise ArchiveError(
            "Required operational workflows missing: " + ", ".join(missing_keep)
        )

    unknown = sorted(current_names - expected_names)
    if unknown:
        raise ArchiveError(
            "Unknown workflow files require manual review: " + ", ".join(unknown)
        )

    build_text = (WORKFLOW_DIR / "build_api_json.yml").read_text(
        encoding="utf-8"
    )
    if "collect-krx-watchlist" not in build_text:
        raise ArchiveError(
            "build_api_json.yml no longer references collect-krx-watchlist"
        )

    for filename, expected in EXPECTED_KEEP_TRIGGERS.items():
        actual = inspect_triggers(WORKFLOW_DIR / filename)
        if actual != expected:
            raise ArchiveError(
                f"Operational workflow trigger drift {filename}: "
                f"actual={sorted(actual)}, expected={sorted(expected)}"
            )

    records: List[Dict[str, Any]] = []
    for filename in ARCHIVE_WORKFLOWS:
        path = WORKFLOW_DIR / filename
        if not path.exists():
            records.append({"filename": filename, "status": "ALREADY_ABSENT"})
            continue

        triggers = inspect_triggers(path)
        if triggers != {"workflow_dispatch"}:
            raise ArchiveError(
                f"Refusing to archive non-manual workflow {filename}: "
                f"{sorted(triggers)}"
            )

        records.append(
            {
                "filename": filename,
                "status": "READY_TO_ARCHIVE",
                "triggers": sorted(triggers),
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )

    return records


def write_readme(moved: List[str], already_absent: List[str]) -> None:
    lines = [
        "# Archived GitHub Actions workflows",
        "",
        "Archive date: 2026-07-15 KST",
        "",
        "Only workflows whose top-level trigger was exactly",
        "`workflow_dispatch` were moved out of `.github/workflows`.",
        "Scheduled and operational workflows remain active.",
        "",
        "## Active operational workflows retained",
        "",
    ]
    lines.extend(
        f"- `{filename}`"
        for filename in sorted(EXPECTED_KEEP_TRIGGERS)
    )
    lines.extend(["", "## Archived manual workflows", ""])
    lines.extend(f"- `{filename}`" for filename in moved)
    if already_absent:
        lines.extend(["", "## Already absent when cleanup ran", ""])
        lines.extend(f"- `{filename}`" for filename in already_absent)
    lines.extend(
        [
            "",
            "Source Python patch and validation files remain in the",
            "repository for auditability. They do not run automatically.",
            "",
        ]
    )
    README_PATH.write_text("\n".join(lines), encoding="utf-8")


def archive_workflows(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    moved: List[str] = []
    already_absent: List[str] = []

    for record in records:
        filename = record["filename"]
        if record["status"] == "ALREADY_ABSENT":
            already_absent.append(filename)
            continue

        source = WORKFLOW_DIR / filename
        destination = ARCHIVE_DIR / filename
        if destination.exists():
            if sha256(destination) != sha256(source):
                raise ArchiveError(f"Archive destination differs: {destination}")
            source.unlink()
        else:
            shutil.move(str(source), str(destination))
        record["status"] = "ARCHIVED"
        record["archive_path"] = str(destination.relative_to(ROOT))
        moved.append(filename)

    remaining = [path.name for path in workflow_files(WORKFLOW_DIR)]
    expected_remaining = sorted(EXPECTED_KEEP_TRIGGERS)
    if remaining != expected_remaining:
        raise ArchiveError(
            f"Unexpected active workflow set: {remaining}; "
            f"expected={expected_remaining}"
        )

    manifest = {
        "schema_version": "1.1",
        "archived_at_kst": now_kst(),
        "status": "PASS",
        "policy": "ARCHIVE_EXACT_MANUAL_TRIGGER_ONLY",
        "keep_workflows": expected_remaining,
        "moved_count": len(moved),
        "already_absent_count": len(already_absent),
        "records": records,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_readme(moved, already_absent)

    return {
        "moved": moved,
        "already_absent": already_absent,
        "remaining": remaining,
    }


def self_test() -> None:
    manual = """
name: Manual
on:
  workflow_dispatch:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo 'schedule:'
          echo 'push:'
"""
    scheduled = """
name: Scheduled
on:
  workflow_dispatch:
  schedule:
    - cron: '0 0 * * *'
jobs: {}
"""
    assert trigger_names(parse_yaml(manual, "manual.yml"), "manual.yml") == {
        "workflow_dispatch"
    }
    assert trigger_names(
        parse_yaml(scheduled, "scheduled.yml"), "scheduled.yml"
    ) == {"schedule", "workflow_dispatch"}
    assert len(ARCHIVE_WORKFLOWS) == len(set(ARCHIVE_WORKFLOWS))
    assert not (set(EXPECTED_KEEP_TRIGGERS) & set(ARCHIVE_WORKFLOWS))
    assert "v6-apply-us-sp500-production.yml" in EXPECTED_KEEP_TRIGGERS
    assert "v77-runtime-freshness-gate.yml" in EXPECTED_KEEP_TRIGGERS
    print("V812_SELF_TEST=PASS")
    print("SCHEDULED_WORKFLOW_PRESERVATION=PASS")
    print("EXACT_TOP_LEVEL_TRIGGER_PARSING=PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0

    records = validate_before_move()
    print("V812_PREFLIGHT=PASS")
    print(f"PREFLIGHT_RECORD_COUNT={len(records)}")
    result = archive_workflows(records)
    print("WORKFLOW_MANUAL_ARCHIVE_V812=PASS")
    print(f"MOVED_COUNT={len(result['moved'])}")
    print(f"ALREADY_ABSENT_COUNT={len(result['already_absent'])}")
    print("ACTIVE_WORKFLOWS_BEGIN")
    for filename in result["remaining"]:
        print(filename)
    print("ACTIVE_WORKFLOWS_END")
    print(f"ACTIVE_WORKFLOW_COUNT={len(result['remaining'])}")
    print(f"MANIFEST={MANIFEST_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArchiveError as exc:
        print(f"WORKFLOW_MANUAL_ARCHIVE_V812=FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
