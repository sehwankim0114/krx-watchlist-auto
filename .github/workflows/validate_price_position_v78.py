#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone V7.8 price-position validator."""

from __future__ import annotations

import argparse
from pathlib import Path

from apply_price_position_v78 import VERSION, audit_api_directory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", default="api")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()

    result = audit_api_directory(
        Path(args.api_dir),
        write_report=args.write_report,
    )
    print(f"PRICE_POSITION_VALIDATION_V78={result['status']}")
    print(f"VERSION={VERSION}")
    print(f"FILES_CHECKED={result['files_checked']}")
    print(f"ELIGIBLE_ROWS={result['eligible_rows']}")
    print(f"BELOW_LOW_ROWS={result['below_low_rows']}")
    print(f"ABOVE_HIGH_ROWS={result['above_high_rows']}")
    print(f"ERROR_COUNT={result['error_count']}")
    if result["status"] != "PASS":
        for item in result.get("errors", [])[:20]:
            print(f"ERROR={item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
