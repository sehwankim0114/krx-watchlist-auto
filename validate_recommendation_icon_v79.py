#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone V7.9 recommendation-icon validator."""

from __future__ import annotations

import argparse
from pathlib import Path

from apply_recommendation_icon_v79 import (
    VERSION,
    audit_recommendation_icons,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", default="api")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()

    result = audit_recommendation_icons(
        Path(args.api_dir),
        write_report=args.write_report,
    )
    print(
        f"RECOMMENDATION_ICON_VALIDATION_V79={result['status']}"
    )
    print(f"VERSION={VERSION}")
    print(f"FILES_CHECKED={result['files_checked']}")
    print(f"ROWS_CHECKED={result['rows_checked']}")
    print(f"ICON_COUNTS={result['icon_counts']}")
    print(f"ERROR_COUNT={result['error_count']}")

    if result["status"] != "PASS":
        for item in result.get("errors", [])[:20]:
            print(f"ERROR={item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
