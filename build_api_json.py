#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent
LATEST = ROOT / "latest"
API = ROOT / "api"
API.mkdir(exist_ok=True)

def csv_to_json(csv_name, json_name):
    path = LATEST / csv_name
    out = API / json_name

    if not path.exists():
        payload = {
            "status": "MISSING",
            "source": csv_name,
            "rows": [],
            "message": f"{csv_name} 파일이 없습니다."
        }
    else:
        df = pd.read_csv(path)
        df = df.where(pd.notnull(df), None)

        payload = {
            "status": "OK",
            "source": csv_name,
            "row_count": len(df),
            "columns": list(df.columns),
            "rows": df.to_dict(orient="records")
        }

    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

# 관종표
csv_to_json("watchlist_summary_latest.csv", "watchlist.json")

# 코피표
csv_to_json("kospi_candidates_30_latest.csv", "kospi_candidates_30.json")
csv_to_json("kospi_recommend_7_latest.csv", "kospi_recommend_7.json")

# 코닥표
csv_to_json("kosdaq_candidates_10_latest.csv", "kosdaq_candidates_10.json")
csv_to_json("kosdaq_recommend_5_latest.csv", "kosdaq_recommend_5.json")

# 코급표
csv_to_json("kospi_gainers_1m_latest.csv", "kospi_gainers_1m.json")

# 월사이클표
csv_to_json("kospi_monthly_cycle_latest.csv", "kospi_monthly_cycle.json")

# 환율약세표
csv_to_json("kospi_fx_weakness_candidates_30_latest.csv", "kospi_fx_weakness_candidates_30.json")
