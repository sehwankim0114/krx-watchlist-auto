#!/usr/bin/env python3
"""Audit current LIMITED supply rows against a complete, issuer-specific 180-day DART window."""
from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import supply_burden_enricher as policy

ROOT = Path(__file__).resolve().parent
INVENTORY = ROOT / "latest/investment_score_current_blockers_latest.json"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"
STATUS = ROOT / "api/status.json"
OUT = ROOT / "latest/investment_score_current_supply_180d_latest.json"
VERSION = "2026-10-18-current-targeted-180d-supply-audit"
KST = ZoneInfo("Asia/Seoul")
LIST_URL = "https://opendart.fss.or.kr/api/list.json"
CORP_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
SUPPLY_REASON = "수급·공시부담:SUPPLY_LIMITED_NO_POSITIVE_EVIDENCE"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fin_map():
    with FIN.open(encoding="utf-8-sig", newline="") as source:
        return {row["ticker"]: row for row in csv.DictReader(source) if row.get("ticker")}


def request_bytes(url, timeout=45):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "krx-current-targeted-supply-audit",
                "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read(80_000_000)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def corp_map(api_key):
    url = CORP_URL + "?" + urllib.parse.urlencode({"crtfc_key": api_key})
    with zipfile.ZipFile(io.BytesIO(request_bytes(url, timeout=75))) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        if len(names) != 1:
            raise RuntimeError("DART_CORPCODE_XML_NOT_UNIQUE")
        root = ET.fromstring(archive.read(names[0]))
    values = defaultdict(set)
    for item in root.findall(".//list"):
        ticker = policy.normalize_code(item.findtext("stock_code") or "")
        code = str(item.findtext("corp_code") or "").strip()
        if ticker and code:
            values[ticker].add(code)
    return values


def date_chunks(start, end):
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=89), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def fetch_reports(api_key, corp_code, start, end):
    reports = {}
    chunks = []
    for chunk_start, chunk_end in date_chunks(start, end):
        page = 1
        total_page = None
        seen = 0
        complete = True
        while True:
            params = {
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bgn_de": chunk_start.strftime("%Y%m%d"),
                "end_de": chunk_end.strftime("%Y%m%d"),
                "page_no": str(page),
                "page_count": "100",
            }
            try:
                payload = json.loads(request_bytes(
                    LIST_URL + "?" + urllib.parse.urlencode(params)
                ).decode("utf-8"))
            except Exception:
                complete = False
                break
            code = str(payload.get("status") or "")
            if code == "013":
                total_page = 0
                break
            if code != "000":
                complete = False
                break
            try:
                total_page = int(payload.get("total_page") or 1)
            except (TypeError, ValueError):
                complete = False
                break
            if total_page < 1 or total_page > 30:
                complete = False
                break
            for item in payload.get("list") or []:
                if str(item.get("corp_code") or corp_code) != corp_code:
                    complete = False
                    break
                receipt = str(item.get("rcept_no") or "")
                if receipt:
                    reports[receipt] = item
                    seen += 1
            if not complete or page >= total_page:
                break
            page += 1
        chunks.append({
            "start": chunk_start.isoformat(), "end": chunk_end.isoformat(),
            "complete": complete and total_page is not None and (total_page == 0 or page >= total_page),
            "pages_fetched": page if total_page else 0,
            "total_pages": total_page, "reports_seen": seen,
        })
    return list(reports.values()), chunks


def main():
    key = os.environ.get("DART_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DART_API_KEY_MISSING")
    inventory, status = read_json(INVENTORY), read_json(STATUS)
    if inventory.get("source_build_id") != status.get("build_id") or not status.get("api_sync_ok"):
        raise RuntimeError("SUPPLY_AUDIT_BUILD_NOT_SYNCED")
    targets = [
        row for row in inventory.get("rows") or []
        if SUPPLY_REASON in (row.get("missing_components") or [])
    ]
    if len(targets) > 40 or len({row["ticker"] for row in targets}) != len(targets):
        raise RuntimeError("SUPPLY_AUDIT_TARGET_SET_INVALID")
    financial = fin_map()
    exact_corp = corp_map(key)
    end = datetime.now(KST).date()
    start = end - timedelta(days=179)
    rows = []
    for item in targets:
        ticker = item["ticker"]
        fin = financial.get(ticker) or {}
        corp_code = fin.get("corp_code") or ""
        base = {
            "ticker": ticker, "name": item["name"], "corp_code": corp_code,
            "window_start": start.isoformat(), "window_end": end.isoformat(),
            "lookback_days": 180, "source_build_id": status["build_id"],
        }
        matches = exact_corp.get(ticker) or set()
        if (fin.get("corp_identity_status") not in {"MATCH", "MATCH_NORMALIZED"}
                or not corp_code or matches != {corp_code}):
            rows.append({**base, "audit_status": "CORP_IDENTITY_UNRESOLVED",
                         "corp_code_exact_stock_match_count": len(matches)})
            continue
        reports, chunks = fetch_reports(key, corp_code, start, end)
        if len(chunks) != 2 or not all(chunk["complete"] for chunk in chunks):
            rows.append({**base, "audit_status": "DART_180D_INCOMPLETE",
                         "chunk_summaries": chunks})
            continue
        evidence = []
        relief_count = 0
        keywords = set()
        severity = 0
        for report in reports:
            report_name = str(report.get("report_nm") or "")
            is_risk, labels, level, relief = policy.classify_report(report_name)
            if relief:
                relief_count += 1
            if not is_risk:
                continue
            severity = max(severity, level)
            keywords.update(labels)
            evidence.append({
                "rcept_dt": str(report.get("rcept_dt") or ""),
                "rcept_no": str(report.get("rcept_no") or ""),
                "report_nm": report_name,
                "keywords": labels,
                "severity": level,
                "relief_flag": relief,
            })
        evidence.sort(key=lambda row: (row["rcept_dt"], row["rcept_no"]), reverse=True)
        supply_level = policy.severity_to_level(severity, len(evidence))
        rows.append({
            **base,
            "audit_status": "COMPLETE_180D_POSITIVE_BURDEN" if evidence else "COMPLETE_180D_NO_POSITIVE_BURDEN",
            "corp_code_exact_stock_match_count": 1,
            "supply_status": "OK",
            "supply_level": supply_level,
            "risk_keywords": sorted(keywords),
            "risk_report_count": len(evidence),
            "relief_report_match_count": relief_count,
            "evidence_reports": evidence,
            "chunk_summaries": chunks,
        })
    rows.sort(key=lambda row: row["ticker"])
    counts = dict(Counter(row["audit_status"] for row in rows))
    result = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY_NOT_FOR_GPT_DISPLAY",
        "source_build_id": status["build_id"],
        "basis_date": inventory["basis_date"],
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "target_count": len(targets),
        "classification_counts": counts,
        "complete_tickers": [
            row["ticker"] for row in rows if row["audit_status"].startswith("COMPLETE_180D_")
        ],
        "production_api_modified": False,
        "production_score_written": False,
        "rows": rows,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CURRENT_SUPPLY_180D_AUDIT=PASS")
    print("TARGETS=" + str(len(targets)))
    print("CLASSIFICATION_COUNTS=" + json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
