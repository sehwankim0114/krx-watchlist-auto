"""Refresh the source-only 20-session price elasticity for the current two-table build.

A stale history cache leaves the previous source untouched; the score audit will flag
its basis mismatch. A current cache must produce a complete, internally consistent
source, or the API build fails before any score is published.
"""

import csv
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "api/two_table_v1/manifest.json"
HISTORY_META = ROOT / "latest/active_stock_long_history_260d_meta_latest.json"
SOURCE_META = ROOT / "latest/investment_score_price_elasticity_20d_latest.json"
SOURCE_CSV = ROOT / "latest/investment_score_price_elasticity_20d_latest.csv"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def tickers():
    result = set()
    for table in ("kospi", "decliners", "decliners24"):
        data = read_json(ROOT / f"api/two_table_v1/{table}.json")
        for row in data["rows"]:
            ticker = str(row["ticker"]).zfill(6)
            if len(ticker) != 6 or not ticker.isdigit():
                raise ValueError("INVALID_TWO_TABLE_TICKER")
            result.add(ticker)
    return result


def main():
    manifest = read_json(MANIFEST)
    history = read_json(HISTORY_META)
    basis = str(manifest["basis_date"])
    if history.get("status") != "READY" or history.get("source_only") is not True:
        print("CURRENT_ELASTICITY_REFRESH=SKIPPED_HISTORY_NOT_READY")
        return
    if history.get("cache_max_date") != basis:
        print("CURRENT_ELASTICITY_REFRESH=SKIPPED_HISTORY_BASIS_MISMATCH")
        return

    subprocess.run([sys.executable, "investment_score_price_elasticity_v875.py"],
                   cwd=ROOT, check=True)
    meta = read_json(SOURCE_META)
    with SOURCE_CSV.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    expected = tickers()
    actual = {row["ticker"] for row in rows}
    if meta["basis_date"] != basis or actual != expected or len(rows) != len(expected):
        raise ValueError("CURRENT_ELASTICITY_UNIVERSE_OR_BASIS_MISMATCH")
    if meta["production_unique_tickers"] != len(rows):
        raise ValueError("CURRENT_ELASTICITY_META_COUNT_MISMATCH")
    ready = [row for row in rows if row["source_status"] == "READY"]
    if len(ready) != meta["ready_tickers"]:
        raise ValueError("CURRENT_ELASTICITY_READY_COUNT_MISMATCH")
    if len(rows) - len(ready) != meta["limited_tickers"]:
        raise ValueError("CURRENT_ELASTICITY_LIMITED_COUNT_MISMATCH")
    if any(row["basis_date"] != basis for row in rows):
        raise ValueError("CURRENT_ELASTICITY_ROW_BASIS_MISMATCH")
    if any(row["window_end_date"] != basis or
           int(row["daily_return_observation_count"]) != 20 for row in ready):
        raise ValueError("CURRENT_ELASTICITY_READY_ROW_NOT_CURRENT")
    print("CURRENT_ELASTICITY_REFRESH=PASS")
    print("CURRENT_ELASTICITY_BASIS=" + basis)
    print("CURRENT_ELASTICITY_READY=" + str(len(ready)))
    print("CURRENT_ELASTICITY_LIMITED=" + str(len(rows) - len(ready)))


if __name__ == "__main__":
    main()
