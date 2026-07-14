#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Archive obsolete one-time GitHub Actions workflows safely."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

ROOT = Path(__file__).resolve().parent
WORKFLOW_DIR = ROOT / ".github" / "workflows"
ARCHIVE_DIR = ROOT / "docs" / "workflow_archive" / "2026-07-15"
MANIFEST_PATH = ARCHIVE_DIR / "workflow_archive_manifest.json"
README_PATH = ARCHIVE_DIR / "README.md"

KEEP_WORKFLOWS = [
    "build_api_json.yml",
    "collect-krx-watchlist.yml",
    "dart-fx-exposure-safe.yml",
    "maintenance-repair.yml",
    "safe-repository-cleanup.yml",
    "v731-daily-integrated-health.yml"
]
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
    "v81-archive-obsolete-workflows.yml"
]

AUTOMATIC_TRIGGER_PATTERNS = {
    "schedule": re.compile(r"^\s*schedule\s*:", re.M),
    "workflow_run": re.compile(r"^\s*workflow_run\s*:", re.M),
    "push": re.compile(r"^\s*push\s*:", re.M),
    "pull_request": re.compile(r"^\s*pull_request\s*:", re.M),
    "repository_dispatch": re.compile(
        r"^\s*repository_dispatch\s*:",
        re.M,
    ),
    "workflow_call": re.compile(r"^\s*workflow_call\s*:", re.M),
}


class CleanupError(RuntimeError):
    pass


def now_kst() -> str:
    if ZoneInfo is None:
        return datetime.utcnow().isoformat(timespec="seconds") + "+09:00"
    return datetime.now(
        ZoneInfo("Asia/Seoul")
    ).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def trigger_info(text: str) -> Dict[str, Any]:
    automatic = [
        name
        for name, pattern in AUTOMATIC_TRIGGER_PATTERNS.items()
        if pattern.search(text)
    ]
    manual = bool(
        re.search(r"^\s*workflow_dispatch\s*:", text, re.M)
    )
    return {
        "workflow_dispatch": manual,
        "automatic_triggers": automatic,
    }


def validate_before_move() -> List[Dict[str, Any]]:
    if not WORKFLOW_DIR.exists():
        raise CleanupError(f"Workflow directory missing: {WORKFLOW_DIR}")

    for filename in KEEP_WORKFLOWS:
        path = WORKFLOW_DIR / filename
        if not path.exists():
            raise CleanupError(
                f"Required operational workflow missing: {filename}"
            )

    build_text = (
        WORKFLOW_DIR / "build_api_json.yml"
    ).read_text(encoding="utf-8")
    if "collect-krx-watchlist" not in build_text:
        raise CleanupError(
            "build_api_json.yml no longer references collect-krx-watchlist"
        )

    records: List[Dict[str, Any]] = []
    for filename in ARCHIVE_WORKFLOWS:
        path = WORKFLOW_DIR / filename
        if not path.exists():
            records.append(
                {
                    "filename": filename,
                    "status": "ALREADY_ABSENT",
                }
            )
            continue

        text = path.read_text(encoding="utf-8")
        info = trigger_info(text)
        if info["automatic_triggers"]:
            raise CleanupError(
                f"Refusing to archive automatic workflow {filename}: "
                f"{info['automatic_triggers']}"
            )
        if not info["workflow_dispatch"]:
            raise CleanupError(
                f"Refusing to archive unclassified workflow {filename}"
            )

        records.append(
            {
                "filename": filename,
                "status": "READY_TO_ARCHIVE",
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
                **info,
            }
        )

    current = sorted(
        path.name
        for path in WORKFLOW_DIR.glob("*.y*ml")
    )
    known = set(KEEP_WORKFLOWS) | set(ARCHIVE_WORKFLOWS)
    unknown = [name for name in current if name not in known]
    if unknown:
        raise CleanupError(
            "Unknown workflow files require manual review: "
            + ", ".join(unknown)
        )

    return records


def write_readme(
    moved: List[str],
    already_absent: List[str],
) -> None:
    lines = [
        "# Archived GitHub Actions workflows",
        "",
        "Archive date: 2026-07-15 KST",
        "",
        "These files were moved out of `.github/workflows` after their",
        "one-time patch/test role was completed. GitHub Actions does not",
        "execute workflow YAML files stored under `docs/`.",
        "",
        "## Active operational workflows retained",
        "",
    ]
    lines.extend(f"- `{filename}`" for filename in KEEP_WORKFLOWS)
    lines.extend(
        [
            "",
            "## Archived workflows",
            "",
        ]
    )
    lines.extend(f"- `{filename}`" for filename in moved)
    if already_absent:
        lines.extend(
            [
                "",
                "## Already absent when cleanup ran",
                "",
            ]
        )
        lines.extend(
            f"- `{filename}`"
            for filename in already_absent
        )

    lines.extend(
        [
            "",
            "The source Python patch and validation files remain in the",
            "repository for auditability and rollback. They do not run",
            "automatically.",
            "",
        ]
    )
    README_PATH.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> int:
    records = validate_before_move()
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
                raise CleanupError(
                    f"Archive destination differs: {destination}"
                )
            source.unlink()
        else:
            shutil.move(str(source), str(destination))
        record["status"] = "ARCHIVED"
        record["archive_path"] = str(
            destination.relative_to(ROOT)
        )
        moved.append(filename)

    manifest = {
        "schema_version": "1.0",
        "archived_at_kst": now_kst(),
        "status": "PASS",
        "keep_workflows": KEEP_WORKFLOWS,
        "moved_count": len(moved),
        "already_absent_count": len(already_absent),
        "records": records,
    }
    MANIFEST_PATH.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_readme(moved, already_absent)

    remaining = sorted(
        path.name
        for path in WORKFLOW_DIR.glob("*.y*ml")
    )
    if remaining != sorted(KEEP_WORKFLOWS):
        raise CleanupError(
            f"Unexpected active workflow set: {remaining}"
        )

    print("WORKFLOW_ARCHIVE_CLEANUP=PASS")
    print(f"MOVED_COUNT={len(moved)}")
    print(
        f"ALREADY_ABSENT_COUNT={len(already_absent)}"
    )
    print("ACTIVE_WORKFLOWS_BEGIN")
    for filename in remaining:
        print(filename)
    print("ACTIVE_WORKFLOWS_END")
    print(f"MANIFEST={MANIFEST_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
