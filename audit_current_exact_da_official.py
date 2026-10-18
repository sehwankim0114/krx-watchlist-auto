#!/usr/bin/env python3
"""Read-only current-universe annual XBRL exact D&A audit.

No source cache, production API, or score is changed here.
"""
from __future__ import annotations

import csv
import json
import os
import time
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_xbrl_cfs_ofs_v887 as xbrl

ROOT = Path(__file__).resolve().parent
INVENTORY = ROOT / "latest/investment_score_current_blockers_latest.json"
RAW = ROOT / "latest/investment_score_source_cache_latest.csv"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"
STATUS = ROOT / "api/status.json"
OUT = ROOT / "latest/investment_score_current_exact_da_official_audit_latest.json"
VERSION = "2026-10-18-current-exact-da-official-xbrl-audit"
KST = ZoneInfo("Asia/Seoul")
LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DEP = "AdjustmentsForDepreciationExpense"
AMO = "AdjustmentsForAmortisationExpense"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv_map(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    return {row["ticker"]: row for row in rows if row.get("ticker")}


def lookup_annual(api_key, corp_code, year):
    today = datetime.now(KST).strftime("%Y%m%d")
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": f"{year + 1}0101",
        "end_de": today,
        "pblntf_ty": "A",
        "sort": "date",
        "sort_mth": "desc",
        "page_no": "1",
        "page_count": "100",
    }
    request = urllib.request.Request(
        LIST_URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "krx-current-exact-da-audit", "Accept": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except Exception as exc:
            if attempt == 2:
                return {"status": "LIST_TRANSPORT_FAILURE", "error_type": type(exc).__name__}
            time.sleep(attempt + 1)
    status = str(payload.get("status") or "")
    if status not in {"000", "013"}:
        return {"status": "LIST_DART_STATUS_" + status}
    if status == "013":
        return {"status": "NO_ANNUAL_REPORT"}
    matches = [
        item for item in (payload.get("list") or [])
        if "사업보고서" in str(item.get("report_nm") or "")
        and str(year) in str(item.get("report_nm") or "")
        and str(item.get("rcept_no") or "").isdigit()
    ]
    if not matches:
        return {"status": "NO_ANNUAL_REPORT"}
    item = max(matches, key=lambda row: (str(row.get("rcept_dt") or ""), str(row["rcept_no"])))
    return {
        "status": "OK",
        "rcept_no": str(item["rcept_no"]),
        "rcept_dt": str(item.get("rcept_dt") or ""),
        "report_nm": str(item.get("report_nm") or ""),
    }


def exact_candidate(evidence):
    if (evidence.get("source_fs_status") != "CONSISTENT"
            or evidence.get("selection_classification") != "MATCHED_FS_MEMBER_BOTH_FACTS_UNIQUE"
            or evidence.get("selected_value_conflict") != "FALSE"
            or evidence.get("selected_context_conflict") != "FALSE"
            or evidence.get("both_approved_facts_unique") != "TRUE"):
        return None
    try:
        units = json.loads(evidence.get("selected_unit_signatures_json") or "[]")
        facts = json.loads(evidence.get("selected_facts_json") or "[]")
    except (TypeError, ValueError):
        return None
    if units != ["iso4217:KRW"]:
        return None
    values = {DEP: set(), AMO: set()}
    for fact in facts:
        local = fact.get("local_name")
        if local in values:
            value = xbrl.raw_number(fact.get("normalized_value"))
            if value is not None:
                values[local].add(value)
    if any(len(values[name]) != 1 for name in (DEP, AMO)):
        return None
    dep, amo = next(iter(values[DEP])), next(iter(values[AMO]))
    total = xbrl.raw_number(evidence.get("evidence_da_sum"))
    if dep < 0 or amo < 0 or total is None or abs(dep + amo - total) > 0.5:
        return None
    return {"depreciation_value": dep, "amortisation_value": amo, "da_total": total}


def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DART_API_KEY_MISSING")
    inventory, status = read_json(INVENTORY), read_json(STATUS)
    if inventory.get("source_build_id") != status.get("build_id") or not status.get("api_sync_ok"):
        raise RuntimeError("CURRENT_DA_AUDIT_BUILD_NOT_SYNCED")
    raw_map, fin_map = read_csv_map(RAW), read_csv_map(FIN)
    prior = read_json(OUT) if OUT.is_file() else {}
    prior_rows = {
        row["ticker"]: row for row in prior.get("rows") or []
        if row.get("ticker")
    }
    targets = [
        row for row in inventory.get("rows") or []
        if row.get("da_recovery_lane") == "CURRENT_OFFICIAL_DA_AUDIT_REQUIRED"
    ]
    if len(targets) > 40 or len({row["ticker"] for row in targets}) != len(targets):
        raise RuntimeError("CURRENT_DA_AUDIT_TARGET_SET_INVALID")

    results = []
    to_xbrl = []
    for item in targets:
        ticker = item["ticker"]
        raw_ticker = item["raw_source_ticker"]
        raw, fin = raw_map.get(raw_ticker) or {}, fin_map.get(raw_ticker) or {}
        year_text = raw.get("annual_source_year") or ""
        base = {
            "ticker": ticker, "name": item["name"], "raw_source_ticker": raw_ticker,
            "annual_source_year": year_text, "source_fs_div": raw.get("deep_fs_div") or "",
            "corp_code": raw.get("corp_code") or "", "source_build_id": status["build_id"],
        }
        if (not year_text.isdigit()
                or raw.get("source_cache_status") != "READY_RAW_SOURCE"
                or raw.get("deep_source_status") != "OK"
                or raw.get("deep_source_year") != year_text
                or raw.get("annual_fs_div") != raw.get("deep_fs_div")
                or raw.get("deep_fs_div") not in {"CFS", "OFS"}
                or fin.get("corp_identity_status") not in {"MATCH", "MATCH_NORMALIZED"}
                or not base["corp_code"] or fin.get("corp_code") != base["corp_code"]):
            results.append({**base, "audit_status": "SOURCE_IDENTITY_OR_PERIOD_UNVERIFIED"})
            continue
        year = int(year_text)
        report = lookup_annual(api_key, base["corp_code"], year)
        if report["status"] != "OK":
            results.append({**base, "audit_status": report["status"]})
            continue
        base.update(report)
        old = prior_rows.get(ticker) or {}
        if (old.get("rcept_no") == report["rcept_no"]
                and old.get("annual_source_year") == year_text
                and old.get("source_fs_div") == base["source_fs_div"]
                and old.get("audit_status") not in {"XBRL_REQUEST_FAILED", "LIST_TRANSPORT_FAILURE"}):
            results.append({**old, "source_build_id": status["build_id"], "reused_unchanged_receipt": True})
            continue
        to_xbrl.append((base, raw, year))
        time.sleep(0.2)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                xbrl.process_one,
                {
                    "ticker": base["ticker"], "name": base["name"], "market": "KOSPI",
                    "rcept_no": base["rcept_no"], "target_year": year,
                },
                raw,
                api_key,
            ): base for base, raw, year in to_xbrl
        }
        for future in as_completed(futures):
            base = futures[future]
            try:
                evidence = future.result()
            except Exception as exc:
                results.append({**base, "audit_status": "XBRL_REQUEST_FAILED", "error_type": type(exc).__name__})
                continue
            candidate = exact_candidate(evidence)
            results.append({
                **base,
                "audit_status": "RECOVERABLE_EXACT_CANDIDATE" if candidate else evidence["selection_classification"],
                "source_fs_status": evidence["source_fs_status"],
                "selection_classification": evidence["selection_classification"],
                "selected_value_conflict": evidence["selected_value_conflict"],
                "selected_context_conflict": evidence["selected_context_conflict"],
                "selected_unit_signatures_json": evidence["selected_unit_signatures_json"],
                "selected_facts_json": evidence["selected_facts_json"],
                "exact_candidate": candidate,
                "reused_unchanged_receipt": False,
            })

    results.sort(key=lambda row: row["ticker"])
    if len(results) != len(targets):
        raise RuntimeError("CURRENT_DA_AUDIT_RESULT_COUNT_MISMATCH")
    counts = dict(Counter(row["audit_status"] for row in results))
    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY_NOT_FOR_GPT_DISPLAY",
        "source_build_id": status["build_id"],
        "basis_date": inventory["basis_date"],
        "target_count": len(targets),
        "new_xbrl_queries": len(to_xbrl),
        "reused_receipt_count": sum(bool(row.get("reused_unchanged_receipt")) for row in results),
        "classification_counts": counts,
        "recoverable_exact_tickers": [
            row["ticker"] for row in results
            if row["audit_status"] == "RECOVERABLE_EXACT_CANDIDATE"
        ],
        "production_source_cache_modified": False,
        "production_score_written": False,
        "rows": results,
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CURRENT_EXACT_DA_AUDIT=PASS")
    print("TARGETS=" + str(len(targets)))
    print("RECOVERABLE=" + str(len(summary["recoverable_exact_tickers"])))
    print("CLASSIFICATION_COUNTS=" + json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
