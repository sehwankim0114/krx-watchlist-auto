#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
from pathlib import Path

VERSION = "2026-09-21-v8.13.9B-controlled-production-supply-source-integration"
VALID_LEVELS = {"없음", "주의", "경계", "위험"}

def ticker(value):
    s = re.sub(r"[^0-9]", "", str(value or "").strip())
    return s.zfill(6) if s else ""

def load_supply_source(path):
    path = Path(path)
    if not path.is_file():
        return {}

    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    out = {}
    for row in rows:
        code = ticker(row.get("ticker"))
        if not code:
            raise RuntimeError("V8139B_INVALID_TICKER")
        if code in out:
            raise RuntimeError("V8139B_DUPLICATE_TICKER:" + code)
        if row.get("source_status") != "SOURCE_ONLY_READY":
            raise RuntimeError("V8139B_SOURCE_NOT_READY:" + code)
        if row.get("supply_status") != "OK":
            raise RuntimeError("V8139B_SUPPLY_NOT_OK:" + code)
        if row.get("supply_level") not in VALID_LEVELS:
            raise RuntimeError("V8139B_LEVEL_INVALID:" + code)
        out[code] = dict(row)

    return out
