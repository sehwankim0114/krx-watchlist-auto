#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V7.9 recommendation-icon integrity normalizer."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

VERSION = "2026-07-14-v7.9-recommendation-icon-integrity"
REPORT_NAME = "recommendation_icon_validation.json"

ALLOWED_ICONS: Tuple[str, ...] = ("✅", "🟡", "⚠️", "🔻", "⚪")
DEFAULT_ICON = "🟡"

TARGETS: Tuple[Dict[str, Any], ...] = (
    {
        "filename": "kospi_watchlist.json",
        "table_id": "kospi_watchlist",
        "expected_rows": 30,
        "max_payload_bytes": 70000,
    },
    {
        "filename": "kosdaq_watchlist.json",
        "table_id": "kosdaq_watchlist",
        "expected_rows": 10,
        "max_payload_bytes": 50000,
    },
    {
        "filename": "us_watchlist.json",
        "table_id": "us_watchlist",
        "expected_rows": 30,
        "max_payload_bytes": 110000,
    },
)

ICON_PATTERN = re.compile(
    "(" + "|".join(re.escape(icon) for icon in ALLOWED_ICONS) + ")"
)
DISPLAY_PATTERN = re.compile(
    r"^(?P<loss>-)?(?P<icon>"
    + "|".join(re.escape(icon) for icon in ALLOWED_ICONS)
    + r")(?P<supply>_)?\s+(?P<name>.+)$"
)
LEADING_RANK_PATTERN = re.compile(r"^\s*\d+\s*[.)-]\s*")
STRIP_MARK_PATTERN = re.compile(
    r"[-_\s]+|"
    + "|".join(re.escape(icon) for icon in ALLOWED_ICONS)
)

RECOMMENDATION_ICON_POLICY: Dict[str, Any] = {
    "version": VERSION,
    "allowed_icons": list(ALLOWED_ICONS),
    "default_candidate_icon": DEFAULT_ICON,
    "icon_required_for_every_row": True,
    "preserve_existing_valid_icon": True,
    "missing_icon_behavior": "assign_yellow_watch_icon",
    "loss_marker_position": "left_of_recommendation_icon",
    "supply_marker_position": "right_of_recommendation_icon",
    "rank_number_prefix_allowed": False,
    "display_format": "[-][ICON][_ ]종목명",
}


class RecommendationIconError(RuntimeError):
    pass


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RecommendationIconError(
            f"JSON read failed: {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise RecommendationIconError(
            f"JSON root is not an object: {path}"
        )
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def row_name(row: Mapping[str, Any]) -> str:
    direct = (
        clean_text(row.get("name"))
        or clean_text(row.get("종목명"))
        or clean_text(row.get("company_name"))
    )
    if direct:
        return LEADING_RANK_PATTERN.sub("", direct).strip()

    current = clean_text(row.get("recommendation_display")) or ""
    current = STRIP_MARK_PATTERN.sub("", current)
    current = LEADING_RANK_PATTERN.sub("", current).strip()
    return current or "종목명 미제공"


def existing_icon(row: Mapping[str, Any]) -> Optional[str]:
    current = clean_text(row.get("recommendation_display")) or ""
    match = ICON_PATTERN.search(current)
    if match:
        return match.group(1)

    for field in (
        "recommendation_icon",
        "recommendation_status_icon",
        "추천표시",
    ):
        value = clean_text(row.get(field))
        if value in ALLOWED_ICONS:
            return value
    return None


def canonical_display(
    row: Mapping[str, Any],
) -> Tuple[str, str, bool]:
    found = existing_icon(row)
    icon = found or DEFAULT_ICON
    defaulted = found is None

    left = "-" if bool(row.get("operating_loss")) else ""
    right = "_" if bool(row.get("supply_burden")) else ""
    return f"{left}{icon}{right} {row_name(row)}", icon, defaulted


def update_contracts(payload: MutableMapping[str, Any]) -> None:
    contract = payload.get("output_contract")
    if not isinstance(contract, MutableMapping):
        contract = {}
        payload["output_contract"] = contract
    contract.update(
        {
            "recommendation_icon_policy_version": VERSION,
            "recommendation_icon_required": True,
            "allowed_recommendation_icons": list(ALLOWED_ICONS),
            "default_candidate_icon": DEFAULT_ICON,
            "recommendation_display_format": "[-][ICON][_ ]종목명",
            "loss_marker_position": "left_of_recommendation_icon",
            "supply_marker_position": "right_of_recommendation_icon",
            "rank_field_use": "sorting_only",
            "do_not_prefix_rank_to_recommendation": True,
        }
    )

    policy = payload.get("presentation_policy")
    if not isinstance(policy, MutableMapping):
        policy = {}
        payload["presentation_policy"] = policy
    policy.update(
        {
            "recommendation_icon_policy_version": VERSION,
            "recommendation_icon_required": True,
            "allowed_recommendation_icons": list(ALLOWED_ICONS),
            "default_candidate_icon": DEFAULT_ICON,
            "show_rank_numbers_default": False,
            "rank_field_use": "sorting_only",
        }
    )


def patch_row(row: MutableMapping[str, Any]) -> Dict[str, Any]:
    original = clean_text(row.get("recommendation_display"))
    display, icon, defaulted = canonical_display(row)
    row["recommendation_display"] = display
    row["recommendation_icon"] = icon
    return {
        "changed": original != display,
        "defaulted": defaulted,
        "icon": icon,
    }


def validate_row(
    row: Mapping[str, Any],
    *,
    file_name: str,
    row_index: int,
) -> List[Dict[str, Any]]:
    errors: List[Dict[str, Any]] = []
    display = clean_text(row.get("recommendation_display")) or ""
    match = DISPLAY_PATTERN.fullmatch(display)

    if not match:
        return [
            {
                "file": file_name,
                "row": row_index,
                "reason": "DISPLAY_FORMAT_INVALID",
                "display": display,
            }
        ]

    icons = ICON_PATTERN.findall(display)
    if len(icons) != 1:
        errors.append(
            {
                "file": file_name,
                "row": row_index,
                "reason": "ICON_COUNT_INVALID",
                "icons": icons,
            }
        )

    expected_loss = bool(row.get("operating_loss"))
    actual_loss = bool(match.group("loss"))
    if expected_loss != actual_loss:
        errors.append(
            {
                "file": file_name,
                "row": row_index,
                "reason": "LOSS_MARKER_MISMATCH",
                "expected": expected_loss,
                "actual": actual_loss,
            }
        )

    expected_supply = bool(row.get("supply_burden"))
    actual_supply = bool(match.group("supply"))
    if expected_supply != actual_supply:
        errors.append(
            {
                "file": file_name,
                "row": row_index,
                "reason": "SUPPLY_MARKER_MISMATCH",
                "expected": expected_supply,
                "actual": actual_supply,
            }
        )

    expected_name = row_name(row)
    actual_name = match.group("name").strip()
    if expected_name != actual_name:
        errors.append(
            {
                "file": file_name,
                "row": row_index,
                "reason": "NAME_MISMATCH",
                "expected": expected_name,
                "actual": actual_name,
            }
        )

    if LEADING_RANK_PATTERN.search(actual_name):
        errors.append(
            {
                "file": file_name,
                "row": row_index,
                "reason": "RANK_PREFIX_PRESENT",
                "name": actual_name,
            }
        )

    icon = match.group("icon")
    if row.get("recommendation_icon") != icon:
        errors.append(
            {
                "file": file_name,
                "row": row_index,
                "reason": "ICON_FIELD_MISMATCH",
                "expected": icon,
                "actual": row.get("recommendation_icon"),
            }
        )
    return errors


def audit_recommendation_icons(
    api_dir: Path,
    *,
    write_report: bool = False,
) -> Dict[str, Any]:
    api_dir = Path(api_dir)
    errors: List[Dict[str, Any]] = []
    files_checked = 0
    rows_checked = 0
    icon_counts = {icon: 0 for icon in ALLOWED_ICONS}

    for target in TARGETS:
        path = api_dir / str(target["filename"])
        if not path.exists():
            errors.append({"file": path.name, "reason": "FILE_MISSING"})
            continue

        payload = read_json(path)
        rows = payload.get("rows")
        if not isinstance(rows, list):
            errors.append({"file": path.name, "reason": "ROWS_INVALID"})
            continue

        expected = int(target["expected_rows"])
        if len(rows) != expected:
            errors.append(
                {
                    "file": path.name,
                    "reason": "ROW_COUNT_MISMATCH",
                    "expected": expected,
                    "actual": len(rows),
                }
            )

        policy = payload.get("recommendation_icon_policy")
        if not isinstance(policy, Mapping):
            errors.append({"file": path.name, "reason": "POLICY_MISSING"})
        elif policy.get("version") != VERSION:
            errors.append(
                {
                    "file": path.name,
                    "reason": "POLICY_VERSION_MISMATCH",
                    "actual": policy.get("version"),
                }
            )

        for index, row in enumerate(rows, start=1):
            if not isinstance(row, Mapping):
                errors.append(
                    {
                        "file": path.name,
                        "row": index,
                        "reason": "ROW_NOT_OBJECT",
                    }
                )
                continue

            rows_checked += 1
            errors.extend(
                validate_row(
                    row,
                    file_name=path.name,
                    row_index=index,
                )
            )
            icon = clean_text(row.get("recommendation_icon"))
            if icon in icon_counts:
                icon_counts[icon] += 1

        files_checked += 1

    summary: Dict[str, Any] = {
        "version": VERSION,
        "generated_at_kst": kst_now().isoformat(timespec="seconds"),
        "status": "PASS" if not errors else "FAIL",
        "files_checked": files_checked,
        "rows_checked": rows_checked,
        "icon_counts": icon_counts,
        "error_count": len(errors),
        "errors": errors[:100],
    }

    if write_report:
        write_json(api_dir / REPORT_NAME, summary)
    return summary


def apply_recommendation_icon_v79(
    repo_root: Path | str = ".",
    *,
    api_dir: Optional[Path | str] = None,
) -> Dict[str, Any]:
    root = Path(repo_root).resolve()
    api = Path(api_dir).resolve() if api_dir is not None else root / "api"
    if not api.exists():
        raise FileNotFoundError(api)

    modified_rows = 0
    defaulted_rows = 0

    for target in TARGETS:
        path = api / str(target["filename"])
        payload = read_json(path)
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise RecommendationIconError(f"{path}: rows invalid")

        expected = int(target["expected_rows"])
        if len(rows) != expected:
            raise RecommendationIconError(
                f"{path}: row count {len(rows)} != {expected}"
            )

        for row in rows:
            if not isinstance(row, MutableMapping):
                raise RecommendationIconError(f"{path}: invalid row")
            stats = patch_row(row)
            modified_rows += int(stats["changed"])
            defaulted_rows += int(stats["defaulted"])

        columns = payload.get("columns")
        if isinstance(columns, list) and "recommendation_icon" not in columns:
            columns.append("recommendation_icon")

        payload["recommendation_icon_policy"] = (
            RECOMMENDATION_ICON_POLICY
        )
        payload["recommendation_icon_version"] = VERSION
        update_contracts(payload)

        max_bytes = int(target["max_payload_bytes"])
        payload["payload_size_limit_bytes"] = max_bytes
        size = write_json(path, payload)
        payload["payload_size_bytes"] = size
        size = write_json(path, payload)
        if size > max_bytes:
            raise RecommendationIconError(
                f"{path}: payload size {size} > {max_bytes}"
            )

    audit = audit_recommendation_icons(api, write_report=True)
    if audit["status"] != "PASS":
        raise RecommendationIconError(
            "V7.9 validation failed: "
            + json.dumps(audit["errors"][:20], ensure_ascii=False)
        )

    compact = {
        "version": VERSION,
        "status": audit["status"],
        "files_checked": audit["files_checked"],
        "rows_checked": audit["rows_checked"],
        "icon_counts": audit["icon_counts"],
        "error_count": audit["error_count"],
        "modified_rows": modified_rows,
        "defaulted_rows": defaulted_rows,
    }

    for name in (
        "status.json",
        "manifest.json",
        "validation_report.json",
        "stock_table_rules.json",
    ):
        path = api / name
        if not path.exists():
            continue
        payload = read_json(path)
        payload["recommendation_icon_policy"] = (
            RECOMMENDATION_ICON_POLICY
        )
        payload["recommendation_icon_version"] = VERSION
        payload["recommendation_icon_validation"] = compact
        update_contracts(payload)
        write_json(path, payload)

    return {
        **audit,
        "modified_rows": modified_rows,
        "defaulted_rows": defaulted_rows,
        "report_file": str(api / REPORT_NAME),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--api-dir", default=None)
    args = parser.parse_args()

    result = apply_recommendation_icon_v79(
        args.repo_root,
        api_dir=args.api_dir,
    )
    print("RECOMMENDATION_ICON_V79=PASS")
    print(f"VERSION={VERSION}")
    print(f"FILES_CHECKED={result['files_checked']}")
    print(f"ROWS_CHECKED={result['rows_checked']}")
    print(f"MODIFIED_ROWS={result['modified_rows']}")
    print(f"DEFAULTED_ROWS={result['defaulted_rows']}")
    print(f"ICON_COUNTS={result['icon_counts']}")
    print(f"REPORT_FILE={result['report_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
