#!/usr/bin/env python3
"""Source-only earnings outlook changes from explicit OpenDART correction rows.

Only an issuer's old/new values for an unchanged target period, scope and unit
are comparable. Unknown or differently formatted filings remain missing.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

CONTRACT = "2026-10-21-company-outlook-official-correction-v1"
LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DOC_URL = "https://opendart.fss.or.kr/api/document.xml"
LOOKBACK_DAYS = 730
METRICS = {"revenue": "매출액", "operating_profit": "영업이익"}


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = {"id": dict(attrs).get("id", ""), "rows": []}
            self.tables.append(self.table)
        elif tag == "tr" and self.table is not None:
            self.row = []
            self.table["rows"].append(self.row)
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
            self.row.append(self.cell)
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.cell = None
        elif tag == "tr":
            self.row = None
        elif tag == "table":
            self.table = None


def tables_from_html(html):
    parser = TableParser()
    parser.feed(html)
    return [
        [[" ".join("".join(cell).split()) for cell in row] for row in table["rows"]]
        for table in parser.tables
    ]


def amount(raw):
    value = raw.replace(",", "").replace(" ", "")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return None
    return float(value)


def parse_correction(html, report_name):
    if not report_name.lstrip().startswith("[기재정정]"):
        return None
    scope = "consolidated" if "연결재무제표" in report_name else "separate" if "재무제표" in report_name else None
    if scope is None:
        return None
    tables = tables_from_html(html)
    correction = next((table for table in tables if any(
        len(row) == 3 and row == ["정정항목", "정정전", "정정후"] for row in table)), None)
    if correction is None:
        return None
    # A changed period or reporting scope makes the before/after amounts incomparable.
    if any(any(word in row[0] for word in ("대상기간", "사업연도", "연결범위", "재무제표 기준"))
           for row in correction if row and row[0] != "정정항목"):
        return None
    outlook = next((table for table in tables if any("영업실적 전망 내용" in " ".join(row) for row in table)), None)
    if outlook is None:
        return None
    starts = [row for row in outlook if len(row) >= 3 and row[0] == "대상기간" and row[1] == "시작일"]
    ends = [row for row in outlook if len(row) >= 2 and row[0] == "종료일"]
    if len(starts) != 1 or len(ends) != 1:
        return None
    start = starts[0][2]
    end = ends[0][1]
    if not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", end)):
        return None
    if start[:4] != end[:4] or start[5:] != "01-01" or end[5:] != "12-31":
        return None
    if not any("구분(단위 : 억원)" in " ".join(row) and start[:4] in row for row in outlook):
        return None
    result = {}
    for key, korean in METRICS.items():
        matches = [row for row in correction if len(row) == 3 and "영업실적 전망내용" in row[0]
                   and korean in row[0] and "억원" in row[0]
                   and (("연결" in row[0]) == (scope == "consolidated"))]
        if len(matches) != 1:
            continue
        old, new = amount(matches[0][1]), amount(matches[0][2])
        body_rows = [row for row in outlook if len(row) >= 2 and row[0] == korean]
        if old is None or new is None or len(body_rows) != 1 or amount(body_rows[0][1]) != new:
            continue
        result[key] = {"before_100m_krw": old, "after_100m_krw": new,
                       "change_100m_krw": round(new - old, 6),
                       "change_pct": round((new / old - 1) * 100, 4) if old else None,
                       "direction": "UP" if new > old else "DOWN" if new < old else "UNCHANGED"}
    return {"target_period_start": start, "target_period_end": end,
            "reporting_scope": scope, "unit": "100m_KRW", "metrics": result} if result else None


def fetch(url, params):
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": "krx-watchlist-official-outlook/1.0"})
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read(12_000_000)


def list_filings(key, corp_code, start, end):
    found = []
    page = 1
    while True:
        payload = json.loads(fetch(LIST_URL, {"crtfc_key": key, "corp_code": corp_code,
            "bgn_de": start, "end_de": end, "pblntf_detail_ty": "I002",
            "last_reprt_at": "N", "page_no": str(page), "page_count": "100"}).decode("utf-8"))
        status = payload.get("status")
        if status == "013":
            return found
        if status != "000":
            raise RuntimeError("OPENDART_LIST_STATUS:" + str(status))
        found.extend(item for item in payload.get("list") or [] if
                     "영업실적" in str(item.get("report_nm")) and "전망" in str(item.get("report_nm")))
        if page >= int(payload.get("total_page") or 1):
            return found
        page += 1


def document_html(key, receipt):
    raw = fetch(DOC_URL, {"crtfc_key": key, "rcept_no": receipt})
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise RuntimeError("OPENDART_DOCUMENT_NOT_ZIP:" + receipt)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith((".xml", ".html", ".htm"))]
        if len(members) != 1:
            raise RuntimeError("OPENDART_DOCUMENT_MEMBER_AMBIGUOUS:" + receipt)
        blob = archive.read(members[0])
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return blob.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError("OPENDART_DOCUMENT_ENCODING_UNKNOWN:" + receipt)


def corp_codes(map_path, rows):
    by_stock = defaultdict(list)
    with map_path.open(encoding="utf-8-sig", newline="") as stream:
        for item in csv.DictReader(stream):
            by_stock[item["stock_code"].zfill(6)].append(item)
    mapping = {}
    for row in rows:
        matches = [item for item in by_stock.get(row["ticker"], []) if item["corp_name"] == row["name"]]
        mapping[row["ticker"]] = matches[0]["corp_code"] if len(matches) == 1 else None
    return mapping


def build(source_path, map_path, key, as_of=None, only_tickers=None):
    source = json.loads(source_path.read_text(encoding="utf-8-sig"))
    if source.get("status") != "READY_SOURCE_ONLY" or source.get("standalone_swing_table_enabled") is not False:
        raise ValueError("SWING_SOURCE_NOT_READY_SOURCE_ONLY")
    basis = date.fromisoformat(source["basis_date"])
    as_of = as_of or date.today()
    if as_of < basis:
        raise ValueError("AS_OF_BEFORE_SOURCE_BASIS")
    start = (as_of - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = as_of.strftime("%Y%m%d")
    source_rows = source["rows"]
    if len(source_rows) != source["row_count"]:
        raise ValueError("SWING_SOURCE_ROW_COUNT_MISMATCH")
    mapping = corp_codes(map_path, source_rows)
    rows = []
    for row in source_rows:
        ticker = row["ticker"]
        if only_tickers and ticker not in only_tickers:
            continue
        corp = mapping[ticker]
        result = {"ticker": ticker, "name": row["name"], "corp_code": corp,
                  "status": "CORP_CODE_UNRESOLVED" if not corp else "NO_COMPARABLE_OFFICIAL_CORRECTION",
                  "latest_change": None}
        if corp:
            candidates = sorted(list_filings(key, corp, start, end), key=lambda x: x["rcept_no"], reverse=True)
            for filing in candidates:
                if not str(filing["report_nm"]).lstrip().startswith("[기재정정]"):
                    continue
                parsed = parse_correction(document_html(key, filing["rcept_no"]), filing["report_nm"])
                if not parsed:
                    continue
                result["status"] = "COMPARABLE_OFFICIAL_CORRECTION"
                result["latest_change"] = {**parsed, "filing_date": filing["rcept_dt"],
                    "receipt_no": filing["rcept_no"],
                    "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + filing["rcept_no"]}
                break
        rows.append(result)
    counts = dict(Counter(row["status"] for row in rows))
    return {"contract_version": CONTRACT, "status": "READY_SOURCE_ONLY", "basis_date": str(basis),
            "disclosure_as_of_date": str(as_of), "lookback_days": LOOKBACK_DAYS,
            "row_count": len(rows), "status_counts": counts,
            "comparison_policy": "EXPLICIT_ISSUER_CORRECTION_SAME_ANNUAL_PERIOD_SCOPE_UNIT",
            "uncomparable_display": "자료 미제공", "production_activation_allowed": False,
            "standalone_swing_table_enabled": False, "rows": rows}


def self_test(sample_path):
    html = sample_path.read_text(encoding="utf-8-sig")
    parsed = parse_correction(html, "[기재정정]연결재무제표기준영업실적등에대한전망(공정공시)")
    assert parsed["target_period_start"] == "2025-01-01"
    assert parsed["target_period_end"] == "2025-12-31"
    assert parsed["metrics"]["revenue"]["before_100m_krw"] == 5463
    assert parsed["metrics"]["revenue"]["after_100m_krw"] == 5332
    assert parsed["metrics"]["operating_profit"]["before_100m_krw"] == 260
    assert parsed["metrics"]["operating_profit"]["after_100m_krw"] == 101
    assert parse_correction(html.replace("2025-12-31", "2026-12-31", 1),
                            "[기재정정]연결재무제표기준영업실적등에대한전망(공정공시)") is None
    print("OFFICIAL_OUTLOOK_SAMPLE_TEST=PASS")


def probe_official_receipt(key):
    receipt = "20251222900202"
    parsed = parse_correction(document_html(key, receipt),
                              "[기재정정]연결재무제표기준영업실적등에대한전망(공정공시)")
    if not parsed or parsed["target_period_start"] != "2025-01-01" or \
            parsed["metrics"]["revenue"]["before_100m_krw"] != 5463 or \
            parsed["metrics"]["revenue"]["after_100m_krw"] != 5332 or \
            parsed["metrics"]["operating_profit"]["before_100m_krw"] != 260 or \
            parsed["metrics"]["operating_profit"]["after_100m_krw"] != 101:
        raise ValueError("KNOWN_OFFICIAL_CORRECTION_MISMATCH")
    print("OFFICIAL_OUTLOOK_LIVE_RECEIPT_TEST=PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("latest/standalone_swing_source_latest.json"))
    parser.add_argument("--corp-map", type=Path, default=Path("latest/dart_corp_code_map_latest.csv"))
    parser.add_argument("--out", type=Path, default=Path("latest/company_outlook_change_official_latest.json"))
    parser.add_argument("--self-test-sample", type=Path)
    parser.add_argument("--probe-official-receipt", action="store_true")
    parser.add_argument("--only-ticker", action="append")
    args = parser.parse_args()
    if args.self_test_sample:
        self_test(args.self_test_sample)
        return
    key = os.environ.get("DART_API_KEY", "").strip()
    if not key:
        raise SystemExit("DART_API_KEY_MISSING")
    if args.probe_official_receipt:
        probe_official_receipt(key)
        return
    output = build(args.source, args.corp_map, key, only_tickers=set(args.only_ticker or []))
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("OFFICIAL_OUTLOOK_STATUS_COUNTS=" + json.dumps(output["status_counts"], sort_keys=True))
    print("OFFICIAL_OUTLOOK_BASIS_DATE=" + output["basis_date"])
    print("PRODUCTION_ACTIVATION_ALLOWED=false")


if __name__ == "__main__":
    main()

