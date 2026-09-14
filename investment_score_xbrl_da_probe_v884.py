#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

VERSION = "2026-09-13-v8.8.4-xbrl-da-source-path-probe"
KST = ZoneInfo("Asia/Seoul")
ROOT = Path(".")

AUDIT_CSV = ROOT / "latest/investment_score_da_exact_id_audit_v883.csv"
RAW_CSV = ROOT / "latest/investment_score_source_cache_latest.csv"

OUT_CSV = ROOT / "latest/investment_score_xbrl_da_probe_v884.csv"
OUT_JSON = ROOT / "latest/investment_score_xbrl_da_probe_v884_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_xbrl_da_probe_v884_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_xbrl_da_source_path_probe_v884.md"

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
XBRL_URL = "https://opendart.fss.or.kr/api/fnlttXbrl.xml"

PROBE_LOCALNAME_RE = re.compile(
    r"(Depreciation|Amortisation|Amortization)",
    re.IGNORECASE,
)

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def clean_ticker(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def clean_corp(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(8) if s else ""

def request_json(url, params, timeout=30):
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url + "?" + query,
        headers={
            "User-Agent": "krx-watchlist-v884-xbrl-da-probe",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def request_bytes(url, params, timeout=60):
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url + "?" + query,
        headers={
            "User-Agent": "krx-watchlist-v884-xbrl-da-probe",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(80_000_000)

def pick_samples(audit_rows, raw_map, limit=12):
    eligible = []
    for row in audit_rows:
        if row.get("audit_status") != "NO_DA_CANDIDATE":
            continue
        if row.get("financial_sector_neutral") == "TRUE":
            continue
        code = clean_ticker(row.get("ticker"))
        raw = raw_map.get(code) or {}
        corp = clean_corp(raw.get("corp_code"))
        if not corp:
            continue
        eligible.append({
            "ticker": code,
            "name": row.get("name") or "",
            "benchmark_ticker": row.get("benchmark_ticker") or "",
            "corp_code": corp,
            "raw_source_mode": row.get("raw_source_mode") or "",
        })

    chosen = []
    used_sector = set()
    for item in eligible:
        sector = item["benchmark_ticker"]
        if sector and sector not in used_sector:
            chosen.append(item)
            used_sector.add(sector)
        if len(chosen) >= limit:
            break

    if len(chosen) < limit:
        seen = {x["ticker"] for x in chosen}
        for item in eligible:
            if item["ticker"] in seen:
                continue
            chosen.append(item)
            seen.add(item["ticker"])
            if len(chosen) >= limit:
                break

    return chosen

def find_latest_business_report(api_key, corp_code):
    payload = request_json(
        LIST_URL,
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": "20260101",
            "end_de": "20260913",
            "last_reprt_at": "Y",
            "pblntf_ty": "A",
            "sort": "date",
            "sort_mth": "desc",
            "page_no": "1",
            "page_count": "100",
        },
    )
    status = str(payload.get("status") or "")
    if status != "000":
        return "", "", "", f"LIST_STATUS_{status}:{payload.get('message','')}"

    candidates = []
    for item in payload.get("list") or []:
        report_nm = str(item.get("report_nm") or "")
        if "사업보고서" not in report_nm:
            continue
        candidates.append(item)

    if not candidates:
        return "", "", "", "NO_BUSINESS_REPORT"

    item = candidates[0]
    return (
        str(item.get("rcept_no") or ""),
        str(item.get("rcept_dt") or ""),
        str(item.get("report_nm") or ""),
        "OK",
    )

def namespace_kind(uri):
    low = (uri or "").lower()
    if "ifrs" in low:
        return "IFRS_NAMESPACE"
    if "dart" in low:
        return "DART_NAMESPACE"
    return "OTHER_NAMESPACE"

def scan_xbrl_zip(blob):
    hits = []
    member_count = 0
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        head = blob[:500].decode("utf-8", errors="ignore")
        return [], 0, "NOT_ZIP:" + head[:180].replace("\n", " ")

    for name in zf.namelist():
        lower = name.lower()
        if not lower.endswith((".xml", ".xbrl", ".xhtml", ".html", ".htm")):
            continue
        member_count += 1
        raw = zf.read(name)
        try:
            root = ET.fromstring(raw)
        except Exception:
            continue

        for elem in root.iter():
            tag = str(elem.tag)
            if tag.startswith("{") and "}" in tag:
                uri, local = tag[1:].split("}", 1)
            else:
                uri, local = "", tag.split(":")[-1]

            if not PROBE_LOCALNAME_RE.search(local):
                continue

            text = (elem.text or "").strip()
            if len(text) > 120:
                text = text[:120]

            hits.append({
                "member": name,
                "namespace_uri": uri,
                "namespace_kind": namespace_kind(uri),
                "local_name": local,
                "context_ref": str(elem.attrib.get("contextRef") or ""),
                "unit_ref": str(elem.attrib.get("unitRef") or ""),
                "decimals": str(elem.attrib.get("decimals") or ""),
                "value": text,
            })

    return hits, member_count, "OK"

def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DART_API_KEY_MISSING")

    audit_rows = read_csv(AUDIT_CSV)
    raw_rows = read_csv(RAW_CSV)
    raw_map = {
        clean_ticker(r.get("ticker")): r
        for r in raw_rows
        if clean_ticker(r.get("ticker"))
    }

    samples = pick_samples(audit_rows, raw_map, limit=12)
    if not samples:
        raise RuntimeError("NO_PROBE_SAMPLES")

    output_rows = []
    localname_tickers = defaultdict(set)
    successful_zip = 0
    extra_fact_tickers = 0
    report_found = 0

    for idx, item in enumerate(samples, start=1):
        rcept_no, rcept_dt, report_nm, list_status = find_latest_business_report(
            api_key,
            item["corp_code"],
        )
        time.sleep(0.15)

        hits = []
        member_count = 0
        xbrl_status = "NOT_REQUESTED"

        if rcept_no:
            report_found += 1
            try:
                blob = request_bytes(
                    XBRL_URL,
                    {
                        "crtfc_key": api_key,
                        "rcept_no": rcept_no,
                        "reprt_code": "11011",
                    },
                    timeout=60,
                )
                hits, member_count, xbrl_status = scan_xbrl_zip(blob)
                if xbrl_status == "OK":
                    successful_zip += 1
            except Exception as exc:
                xbrl_status = f"{type(exc).__name__}:{exc}"

        unique_local = sorted({
            h["local_name"] for h in hits
        })
        if unique_local:
            extra_fact_tickers += 1
            for local in unique_local:
                localname_tickers[local].add(item["ticker"])

        output_rows.append({
            "sample_index": idx,
            "ticker": item["ticker"],
            "name": item["name"],
            "benchmark_ticker": item["benchmark_ticker"],
            "corp_code": item["corp_code"],
            "rcept_no": rcept_no,
            "rcept_dt": rcept_dt,
            "report_nm": report_nm,
            "list_status": list_status,
            "xbrl_status": xbrl_status,
            "xbrl_member_count": member_count,
            "da_fact_count": len(hits),
            "da_unique_localname_count": len(unique_local),
            "da_local_names": "|".join(unique_local),
            "sample_hits_json": json.dumps(
                hits[:25],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        })

        time.sleep(0.20)

    localname_frequency = [
        {
            "local_name": local,
            "ticker_count": len(tickers),
            "tickers": sorted(tickers),
        }
        for local, tickers in sorted(
            localname_tickers.items(),
            key=lambda kv: (-len(kv[1]), kv[0]),
        )
    ]

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "PROBE_ONLY",
        "sample_strategy": "ONE_PER_DISTINCT_BENCHMARK_THEN_FILL_FIRST_ELIGIBLE_MAX_12",
        "sample_count": len(samples),
        "report_found_count": report_found,
        "xbrl_zip_success_count": successful_zip,
        "xbrl_additional_da_fact_ticker_count": extra_fact_tickers,
        "xbrl_additional_da_fact_ticker_pct": round(
            extra_fact_tickers / len(samples) * 100, 2
        ),
        "localname_frequency": localname_frequency,
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "new_da_id_approved": False,
            "dry_run_score_changed": False,
        },
        "decision_rule": {
            "promising_if": "additional DA facts found in >=3 sampled tickers",
            "not_promising_if": "additional DA facts found in 0 sampled tickers",
            "ambiguous_if": "additional DA facts found in 1-2 sampled tickers",
        },
        "next_step": (
            "IF_PROMISING_EXPAND_XBRL_DA_EXTRACTION_AUDIT; "
            "ELSE_REVIEW_ALTERNATIVE_OFFICIAL_SOURCE_OR_CONTRACT_FALLBACK"
        ),
    }

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(output_rows[0].keys()))
        writer.writeheader()
        writer.writerows(output_rows)

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    doc = [
        "# V8.8.4 원본 XBRL D&A source-path probe",
        "",
        f"- 버전: `{VERSION}`",
        "- 상태: PROBE_ONLY",
        "- 대상: V8.8.3의 비금융 NO_DA_CANDIDATE 종목 중 업종별 최대 12개 표본",
        "- 목적: fnlttSinglAcntAll에서 잡히지 않은 D&A fact가 원본 XBRL에 존재하는지 확인",
        "- 점수정책, production API, investment_score_100은 변경하지 않음",
        "",
        "## 판정",
        "",
        "- 3개 이상 표본에서 추가 D&A fact 확인: 원본 XBRL 추출 경로 확대 검토",
        "- 0개: 이 경로는 blocker 해소용으로 부적합",
        "- 1~2개: 제한적 효과로 보고 추가 표본감사 후 결정",
        "",
    ]
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text("\n".join(doc), encoding="utf-8")

    log_lines = [
        f"VERSION={VERSION}",
        f"SAMPLE_COUNT={len(samples)}",
        f"REPORT_FOUND={report_found}",
        f"XBRL_ZIP_SUCCESS={successful_zip}",
        f"XBRL_ADDITIONAL_DA_FACT_TICKERS={extra_fact_tickers}",
        f"XBRL_ADDITIONAL_DA_FACT_PCT={summary['xbrl_additional_da_fact_ticker_pct']}",
        "PRODUCTION_DATA_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "SCORING_POLICY_CHANGED=false",
        "NEW_DA_ID_APPROVED=false",
        "STATUS=OK",
    ]
    OUT_LOG.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print("V884_XBRL_DA_SOURCE_PATH_PROBE=PASS")
    for line in log_lines:
        print(line)
    for item in localname_frequency[:20]:
        print(
            "XBRL_DA_LOCAL="
            + item["local_name"]
            + "|TICKERS="
            + str(item["ticker_count"])
        )

if __name__ == "__main__":
    main()

