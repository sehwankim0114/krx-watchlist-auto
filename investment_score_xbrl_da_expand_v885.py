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
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

VERSION = "2026-09-14-v8.8.5-expanded-xbrl-da-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
PRIOR_AUDIT_VERSION = "2026-09-13-v8.8.3-da-exact-id-audit"
PROBE_VERSION = "2026-09-13-v8.8.4-xbrl-da-source-path-probe"

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(".")

AUDIT_CSV = ROOT / "latest/investment_score_da_exact_id_audit_v883.csv"
AUDIT_JSON = ROOT / "latest/investment_score_da_exact_id_audit_v883_summary_latest.json"
PROBE_JSON = ROOT / "latest/investment_score_xbrl_da_probe_v884_summary_latest.json"
RAW_CSV = ROOT / "latest/investment_score_source_cache_latest.csv"
POLICY_JSON = ROOT / "config/investment_score_policy_v880.json"

OUT_CSV = ROOT / "latest/investment_score_xbrl_da_expand_v885.csv"
OUT_JSON = ROOT / "latest/investment_score_xbrl_da_expand_v885_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_xbrl_da_expand_v885_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_xbrl_da_expand_v885.md"

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
XBRL_URL = "https://opendart.fss.or.kr/api/fnlttXbrl.xml"

FINANCIAL_BENCHMARKS = {"1021", "1024", "1025"}
APPROVED_LOCAL_NAMES = {
    "AdjustmentsForDepreciationExpense",
    "AdjustmentsForAmortisationExpense",
}
DA_NAME_RE = re.compile(
    r"(Depreciation|Amortisation|Amortization)",
    re.IGNORECASE,
)

MAX_WORKERS = 3
request_lock = Lock()
request_counter = Counter()

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def ticker(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def corp_code(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(8) if s else ""

def request(url, params, *, want_json=False, timeout=75, attempts=3):
    query = urllib.parse.urlencode(params)
    full = url + "?" + query
    last = None

    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            full,
            headers={
                "User-Agent": "krx-watchlist-v885-expanded-xbrl-da-audit",
                "Accept": "application/json" if want_json else "*/*",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                blob = r.read(80_000_000)
            with request_lock:
                request_counter["success"] += 1
            if want_json:
                return json.loads(blob.decode("utf-8"))
            return blob
        except Exception as exc:
            last = exc
            with request_lock:
                request_counter[type(exc).__name__] += 1
            if attempt < attempts:
                time.sleep(0.8 * attempt)

    raise RuntimeError(
        f"REQUEST_FAILED:{type(last).__name__}:{last}"
    )

def latest_business_report(api_key, code):
    payload = request(
        LIST_URL,
        {
            "crtfc_key": api_key,
            "corp_code": code,
            "bgn_de": "20260101",
            "end_de": "20260914",
            "last_reprt_at": "Y",
            "pblntf_ty": "A",
            "sort": "date",
            "sort_mth": "desc",
            "page_no": "1",
            "page_count": "100",
        },
        want_json=True,
        timeout=35,
    )

    status = str(payload.get("status") or "")
    if status != "000":
        return {
            "status": f"LIST_STATUS_{status}",
            "message": str(payload.get("message") or ""),
        }

    reports = []
    for item in payload.get("list") or []:
        report_nm = str(item.get("report_nm") or "")
        if "사업보고서" in report_nm:
            reports.append(item)

    if not reports:
        return {"status": "NO_BUSINESS_REPORT"}

    item = reports[0]
    return {
        "status": "OK",
        "rcept_no": str(item.get("rcept_no") or ""),
        "rcept_dt": str(item.get("rcept_dt") or ""),
        "report_nm": str(item.get("report_nm") or ""),
    }

def namespace_kind(uri):
    low = str(uri or "").lower()
    if "ifrs" in low:
        return "IFRS_NAMESPACE"
    if "dart" in low:
        return "DART_NAMESPACE"
    return "OTHER_NAMESPACE"

def parse_xbrl(blob):
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        head = blob[:300].decode("utf-8", errors="ignore")
        return {
            "status": "NOT_ZIP",
            "detail": head.replace("\n", " ")[:180],
            "member_count": 0,
            "facts": [],
        }

    facts = []
    member_count = 0

    for name in zf.namelist():
        lower = name.lower()
        if not lower.endswith(
            (".xml", ".xbrl", ".xhtml", ".html", ".htm")
        ):
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

            if not DA_NAME_RE.search(local):
                continue

            text = (elem.text or "").strip()
            facts.append({
                "member": name,
                "namespace_uri": uri,
                "namespace_kind": namespace_kind(uri),
                "local_name": local,
                "context_ref": str(elem.attrib.get("contextRef") or ""),
                "unit_ref": str(elem.attrib.get("unitRef") or ""),
                "decimals": str(elem.attrib.get("decimals") or ""),
                "value": text[:160],
            })

    return {
        "status": "OK",
        "member_count": member_count,
        "facts": facts,
    }

def process_one(item, api_key):
    out = dict(item)
    out.update({
        "report_status": "",
        "rcept_no": "",
        "rcept_dt": "",
        "report_nm": "",
        "xbrl_status": "",
        "xbrl_member_count": 0,
        "da_fact_count": 0,
        "approved_exact_fact_count": 0,
        "approved_exact_local_names": "",
        "approved_exact_namespace_count": 0,
        "all_da_local_names": "",
        "audit_result": "",
        "sample_approved_facts_json": "[]",
    })

    code = item["corp_code"]
    if not code:
        out["report_status"] = "NO_CORP_CODE"
        out["audit_result"] = "NO_CORP_CODE"
        return out

    try:
        report = latest_business_report(api_key, code)
    except Exception as exc:
        out["report_status"] = "LIST_REQUEST_FAILED"
        out["xbrl_status"] = f"{type(exc).__name__}:{exc}"
        out["audit_result"] = "REPORT_LOOKUP_FAILED"
        return out

    out["report_status"] = report["status"]
    if report["status"] != "OK":
        out["audit_result"] = report["status"]
        return out

    out["rcept_no"] = report["rcept_no"]
    out["rcept_dt"] = report["rcept_dt"]
    out["report_nm"] = report["report_nm"]

    try:
        blob = request(
            XBRL_URL,
            {
                "crtfc_key": api_key,
                "rcept_no": report["rcept_no"],
                "reprt_code": "11011",
            },
            want_json=False,
            timeout=90,
        )
        parsed = parse_xbrl(blob)
    except Exception as exc:
        out["xbrl_status"] = f"REQUEST_FAILED:{type(exc).__name__}:{exc}"
        out["audit_result"] = "XBRL_REQUEST_FAILED"
        return out

    out["xbrl_status"] = parsed["status"]
    out["xbrl_member_count"] = parsed.get("member_count", 0)

    if parsed["status"] != "OK":
        out["audit_result"] = "XBRL_PARSE_FAILED"
        return out

    facts = parsed["facts"]
    out["da_fact_count"] = len(facts)

    exact = [
        fact
        for fact in facts
        if fact["namespace_kind"] == "IFRS_NAMESPACE"
        and fact["local_name"] in APPROVED_LOCAL_NAMES
    ]

    out["approved_exact_fact_count"] = len(exact)
    out["approved_exact_local_names"] = "|".join(
        sorted({x["local_name"] for x in exact})
    )
    out["approved_exact_namespace_count"] = len({
        x["namespace_uri"] for x in exact
    })
    out["all_da_local_names"] = "|".join(
        sorted({x["local_name"] for x in facts})
    )
    out["sample_approved_facts_json"] = json.dumps(
        exact[:12],
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if exact:
        out["audit_result"] = "XBRL_APPROVED_EXACT_FACT_FOUND"
    elif facts:
        out["audit_result"] = "XBRL_DA_FACT_FOUND_NO_APPROVED_EXACT"
    else:
        out["audit_result"] = "XBRL_NO_DA_FACT"

    return out

def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DART_API_KEY_MISSING")

    for path in (
        AUDIT_CSV,
        AUDIT_JSON,
        PROBE_JSON,
        RAW_CSV,
        POLICY_JSON,
    ):
        if not path.is_file():
            raise RuntimeError("MISSING_REQUIRED_SOURCE:" + str(path))

    audit_summary = read_json(AUDIT_JSON)
    probe_summary = read_json(PROBE_JSON)
    policy = read_json(POLICY_JSON)
    audit_rows = read_csv(AUDIT_CSV)
    raw_rows = read_csv(RAW_CSV)

    if audit_summary.get("version") != PRIOR_AUDIT_VERSION:
        raise RuntimeError("V883_VERSION_MISMATCH")
    if probe_summary.get("version") != PROBE_VERSION:
        raise RuntimeError("V884_VERSION_MISMATCH")
    if int(probe_summary.get("xbrl_additional_da_fact_ticker_count") or 0) < 3:
        raise RuntimeError("V884_NOT_PROMISING_ENOUGH_FOR_EXPANSION")
    if policy.get("version") != POLICY_VERSION:
        raise RuntimeError("V880_POLICY_VERSION_MISMATCH")
    if policy.get("status") != "APPROVED_DESIGN_NOT_PRODUCTION":
        raise RuntimeError("V880_POLICY_STATUS_MISMATCH")

    raw_map = {
        ticker(row.get("ticker")): row
        for row in raw_rows
        if ticker(row.get("ticker"))
    }

    targets = []
    prior_ready = 0
    financial_neutral = 0

    for row in audit_rows:
        code = ticker(row.get("ticker"))
        bench = str(row.get("benchmark_ticker") or "")
        status = str(row.get("audit_status") or "")
        is_financial = (
            row.get("financial_sector_neutral") == "TRUE"
            or bench in FINANCIAL_BENCHMARKS
        )

        if is_financial:
            financial_neutral += 1
            continue

        if status == "APPROVED_EXACT_READY":
            prior_ready += 1
            continue

        raw = raw_map.get(code) or {}
        targets.append({
            "ticker": code,
            "name": str(row.get("name") or ""),
            "market": str(row.get("market") or ""),
            "benchmark_ticker": bench,
            "prior_audit_status": status,
            "raw_source_mode": str(row.get("raw_source_mode") or ""),
            "corp_code": corp_code(raw.get("corp_code")),
        })

    if financial_neutral != 15:
        raise RuntimeError(
            f"FINANCIAL_NEUTRAL_COUNT_MISMATCH:{financial_neutral}"
        )
    if prior_ready != 14:
        raise RuntimeError(
            f"PRIOR_APPROVED_READY_COUNT_MISMATCH:{prior_ready}"
        )
    if len(targets) != 83:
        raise RuntimeError(
            f"EXPANSION_TARGET_COUNT_MISMATCH:{len(targets)}"
        )

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(process_one, item, api_key): item["ticker"]
            for item in targets
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                item = next(x for x in targets if x["ticker"] == code)
                results.append({
                    **item,
                    "report_status": "",
                    "rcept_no": "",
                    "rcept_dt": "",
                    "report_nm": "",
                    "xbrl_status": f"UNHANDLED:{type(exc).__name__}:{exc}",
                    "xbrl_member_count": 0,
                    "da_fact_count": 0,
                    "approved_exact_fact_count": 0,
                    "approved_exact_local_names": "",
                    "approved_exact_namespace_count": 0,
                    "all_da_local_names": "",
                    "audit_result": "UNHANDLED_FAILURE",
                    "sample_approved_facts_json": "[]",
                })

    results.sort(key=lambda x: x["ticker"])
    result_counts = Counter(x["audit_result"] for x in results)
    prior_status_counts = Counter(x["prior_audit_status"] for x in results)

    recovered = result_counts["XBRL_APPROVED_EXACT_FACT_FOUND"]
    any_da = sum(
        1
        for x in results
        if int(x.get("da_fact_count") or 0) > 0
    )
    report_found = sum(
        1 for x in results if x.get("report_status") == "OK"
    )
    zip_ok = sum(
        1 for x in results if x.get("xbrl_status") == "OK"
    )
    no_corp = result_counts["NO_CORP_CODE"]

    potential_nonfinancial_da_ready = prior_ready + recovered
    potential_nonfinancial_coverage_pct = round(
        potential_nonfinancial_da_ready / 97 * 100,
        2,
    )
    recovered_pct_of_targets = round(
        recovered / len(targets) * 100,
        2,
    )

    approved_local_frequency = Counter()
    all_local_frequency = defaultdict(set)

    for row in results:
        for local in filter(
            None,
            str(row.get("approved_exact_local_names") or "").split("|"),
        ):
            approved_local_frequency[local] += 1

        for local in filter(
            None,
            str(row.get("all_da_local_names") or "").split("|"),
        ):
            all_local_frequency[local].add(row["ticker"])

    fields = [
        "ticker",
        "name",
        "market",
        "benchmark_ticker",
        "prior_audit_status",
        "raw_source_mode",
        "corp_code",
        "report_status",
        "rcept_no",
        "rcept_dt",
        "report_nm",
        "xbrl_status",
        "xbrl_member_count",
        "da_fact_count",
        "approved_exact_fact_count",
        "approved_exact_local_names",
        "approved_exact_namespace_count",
        "audit_result",
        "all_da_local_names",
        "sample_approved_facts_json",
    ]

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    summary = {
        "version": VERSION,
        "policy_version": POLICY_VERSION,
        "prior_audit_version": PRIOR_AUDIT_VERSION,
        "probe_version": PROBE_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "EXPANDED_AUDIT_ONLY",
        "production_unique_tickers": 112,
        "financial_sector_neutral_count": financial_neutral,
        "nonfinancial_applicable_count": 97,
        "prior_approved_exact_ready_count": prior_ready,
        "expanded_target_count": len(targets),
        "target_prior_status_counts": dict(prior_status_counts),
        "corp_code_available_count": len(targets) - no_corp,
        "corp_code_missing_count": no_corp,
        "business_report_found_count": report_found,
        "xbrl_zip_success_count": zip_ok,
        "xbrl_any_da_fact_ticker_count": any_da,
        "xbrl_approved_exact_fact_recovered_count": recovered,
        "xbrl_approved_exact_fact_recovered_pct_of_targets": recovered_pct_of_targets,
        "potential_nonfinancial_da_ready_count": potential_nonfinancial_da_ready,
        "potential_nonfinancial_da_coverage_pct": potential_nonfinancial_coverage_pct,
        "audit_result_counts": dict(result_counts),
        "approved_exact_local_frequency": dict(approved_local_frequency),
        "all_da_localname_frequency_top50": [
            {
                "local_name": local,
                "ticker_count": len(tickers),
                "sample_tickers": sorted(tickers)[:20],
            }
            for local, tickers in sorted(
                all_local_frequency.items(),
                key=lambda kv: (-len(kv[1]), kv[0]),
            )[:50]
        ],
        "request_stats": dict(request_counter),
        "decision": {
            "approved_exact_source_expansion_promising": recovered >= 3,
            "ready_for_value_context_extraction_design": recovered >= 3,
            "ready_for_production_score_write": False,
            "reason": (
                "Presence audit only. Exact period/context and duplicate-value "
                "selection must be validated before EV/EBITDA input is promoted."
            ),
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "new_da_id_approved": False,
            "legacy_score_rescaled": False,
            "xbrl_fact_presence_treated_as_final_value": False,
        },
        "next_step": (
            "DESIGN_AND_VALIDATE_EXACT_XBRL_DA_VALUE_CONTEXT_EXTRACTION_"
            "THEN_RERUN_V880_SCORE_DRY_RUN"
            if recovered >= 3
            else
            "REVIEW_ALTERNATIVE_OFFICIAL_DA_SOURCE_OR_CONTRACT_FALLBACK"
        ),
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    doc = [
        "# V8.8.5 원본 XBRL D&A 전체 확대 감사",
        "",
        f"- 버전: `{VERSION}`",
        f"- 점수계약: `{POLICY_VERSION}`",
        "- 상태: EXPANDED_AUDIT_ONLY",
        "",
        "## 범위",
        "",
        "- production 고유 종목: 112",
        f"- 금융업 중립처리: {financial_neutral}",
        "- 비금융 적용대상: 97",
        f"- 기존 exact D&A READY: {prior_ready}",
        f"- 확대 감사 대상: {len(targets)}",
        "",
        "## 결과",
        "",
        f"- 사업보고서 확인: {report_found}/{len(targets)}",
        f"- XBRL ZIP 정상 분석: {zip_ok}/{len(targets)}",
        f"- D&A 관련 fact 존재: {any_da}/{len(targets)}",
        f"- V8.8.0 승인 exact IFRS fact 추가 발견: {recovered}/{len(targets)}",
        f"- 잠재 비금융 D&A 원천 READY: {potential_nonfinancial_da_ready}/97",
        f"- 잠재 비금융 D&A 커버리지: {potential_nonfinancial_coverage_pct}%",
        "",
        "## 주의",
        "",
        "- 이 단계는 fact 존재 여부 감사다.",
        "- contextRef, 기간, 연결/별도, 중복값 판정을 완료하기 전에는 EBITDA 값으로 승격하지 않는다.",
        "- 새로운 account/local-name을 자동 승인하지 않는다.",
        "- investment_score_100 또는 production API를 변경하지 않는다.",
        "",
        "## 다음 단계",
        "",
        "- 승인 exact XBRL fact의 연간 값/context 추출 규칙을 검증한다.",
        "- 검증 후 EV/EBITDA 원천을 다시 계산한다.",
        "- 그 다음 V8.8.0 점수 dry-run을 재실행한다.",
        "",
    ]
    OUT_DOC.write_text("\n".join(doc), encoding="utf-8")

    log = [
        f"VERSION={VERSION}",
        f"POLICY_VERSION={POLICY_VERSION}",
        "STATUS=EXPANDED_AUDIT_ONLY",
        "PRODUCTION_UNIQUE_TICKERS=112",
        f"FINANCIAL_SECTOR_NEUTRAL={financial_neutral}",
        "NONFINANCIAL_APPLICABLE=97",
        f"PRIOR_APPROVED_EXACT_READY={prior_ready}",
        f"EXPANDED_TARGETS={len(targets)}",
        f"CORP_CODE_AVAILABLE={len(targets)-no_corp}",
        f"CORP_CODE_MISSING={no_corp}",
        f"REPORT_FOUND={report_found}",
        f"XBRL_ZIP_SUCCESS={zip_ok}",
        f"XBRL_ANY_DA_FACT_TICKERS={any_da}",
        f"XBRL_APPROVED_EXACT_FACT_RECOVERED={recovered}",
        f"POTENTIAL_NONFINANCIAL_DA_READY={potential_nonfinancial_da_ready}/97",
        f"POTENTIAL_NONFINANCIAL_DA_COVERAGE_PCT={potential_nonfinancial_coverage_pct}",
        f"APPROVED_EXACT_SOURCE_EXPANSION_PROMISING={str(recovered >= 3).lower()}",
        "PRODUCTION_DATA_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "SCORING_POLICY_CHANGED=false",
        "NEW_DA_ID_APPROVED=false",
        "XBRL_FACT_PRESENCE_TREATED_AS_FINAL_VALUE=false",
        "STATUS_OK=true",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    print("V885_EXPANDED_XBRL_DA_AUDIT=PASS")
    print("\n".join(log))

if __name__ == "__main__":
    main()
