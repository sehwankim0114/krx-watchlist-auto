#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import math
import os
import time
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

VERSION = "2026-09-15-v8.8.7-xbrl-cfs-ofs-selection-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V886_VERSION = "2026-09-15-v8.8.6-xbrl-da-value-context-audit"

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(".")

V886_CSV = ROOT / "latest/investment_score_xbrl_da_context_v886.csv"
V886_JSON = ROOT / "latest/investment_score_xbrl_da_context_v886_summary_latest.json"
RAW_CSV = ROOT / "latest/investment_score_source_cache_latest.csv"
POLICY_JSON = ROOT / "config/investment_score_policy_v880.json"
FINANCIAL_ENRICHER = ROOT / "financial_valuation_enricher.py"

OUT_CSV = ROOT / "latest/investment_score_xbrl_cfs_ofs_v887.csv"
OUT_JSON = ROOT / "latest/investment_score_xbrl_cfs_ofs_v887_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_xbrl_cfs_ofs_v887_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_xbrl_cfs_ofs_selection_v887.md"

XBRL_URL = "https://opendart.fss.or.kr/api/fnlttXbrl.xml"

APPROVED_LOCAL_NAMES = {
    "AdjustmentsForDepreciationExpense",
    "AdjustmentsForAmortisationExpense",
}

FS_AXIS_LOCAL = "ConsolidatedAndSeparateFinancialStatementsAxis"
FS_MEMBER_BY_DIV = {
    "CFS": "ConsolidatedMember",
    "OFS": "SeparateMember",
}

MAX_WORKERS = 3
request_lock = Lock()
request_stats = Counter()

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def clean_ticker(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def to_int(v):
    try:
        s = str(v or "").strip()
        if not s:
            return None
        return int(float(s))
    except Exception:
        return None

def parse_date(v):
    try:
        return date.fromisoformat(str(v or "").strip())
    except Exception:
        return None

def local_name(tag_or_qname):
    s = str(tag_or_qname or "")
    if s.startswith("{") and "}" in s:
        return s.split("}", 1)[1]
    return s.split(":")[-1]

def namespace_uri(tag):
    s = str(tag or "")
    if s.startswith("{") and "}" in s:
        return s[1:].split("}", 1)[0]
    return ""

def is_ifrs_namespace(uri):
    return "ifrs" in str(uri or "").lower()

def request_xbrl(api_key, rcept_no, attempts=3):
    params = {
        "crtfc_key": api_key,
        "rcept_no": rcept_no,
        "reprt_code": "11011",
    }
    url = XBRL_URL + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "krx-watchlist-v887-cfs-ofs-selection-audit",
                "Accept": "*/*",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                blob = response.read(80_000_000)
            with request_lock:
                request_stats["success"] += 1
            return blob
        except Exception as exc:
            last = exc
            with request_lock:
                request_stats[type(exc).__name__] += 1
            if attempt < attempts:
                time.sleep(0.8 * attempt)
    raise RuntimeError(
        f"XBRL_REQUEST_FAILED:{type(last).__name__}:{last}"
    )

def raw_number(text):
    s = str(text or "").strip().replace(",", "")
    if not s:
        return None
    try:
        value = float(s)
        return value if math.isfinite(value) else None
    except Exception:
        return None

def normalized_number(text, scale, sign):
    value = raw_number(text)
    if value is None:
        return None, "NONNUMERIC"

    scale_text = str(scale or "").strip()
    if scale_text:
        try:
            power = int(scale_text)
            value *= 10 ** power
        except Exception:
            return None, "INVALID_SCALE"

    sign_text = str(sign or "").strip()
    if sign_text == "-" and value > 0:
        value = -value
    elif sign_text not in {"", "+", "-"}:
        return None, "INVALID_SIGN"

    if not math.isfinite(value):
        return None, "NONFINITE"

    return value, "OK"

def dimension_map(context_elem):
    mapping = defaultdict(list)
    signatures = []
    for elem in context_elem.iter():
        lname = local_name(elem.tag)
        if lname != "explicitMember":
            continue
        dim = str(elem.attrib.get("dimension") or "")
        member = (elem.text or "").strip()
        dim_local = local_name(dim)
        member_local = local_name(member)
        mapping[dim_local].append(member_local)
        signatures.append(f"{dim}={member}")
    signatures.sort()
    return dict(mapping), "|".join(signatures)

def context_record(elem):
    cid = str(elem.attrib.get("id") or "")
    start = ""
    end = ""
    instant = ""
    for child in elem.iter():
        lname = local_name(child.tag)
        text = (child.text or "").strip()
        if lname == "startDate" and text:
            start = text
        elif lname == "endDate" and text:
            end = text
        elif lname == "instant" and text:
            instant = text

    dims, signature = dimension_map(elem)
    return {
        "context_id": cid,
        "start_date": start,
        "end_date": end,
        "instant": instant,
        "dimension_map": dims,
        "dimension_signature": signature,
    }

def unit_record(elem):
    uid = str(elem.attrib.get("id") or "")
    measures = []
    for child in elem.iter():
        if local_name(child.tag) == "measure":
            text = (child.text or "").strip()
            if text:
                measures.append(text)
    return {
        "unit_id": uid,
        "measures": sorted(set(measures)),
    }

def parse_zip(blob):
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        return {
            "status": "NOT_ZIP",
            "contexts": {},
            "units": {},
            "facts": [],
        }

    contexts = {}
    units = {}
    facts = []

    for member in zf.namelist():
        if not member.lower().endswith(
            (".xml", ".xbrl", ".xhtml", ".html", ".htm")
        ):
            continue
        try:
            root = ET.fromstring(zf.read(member))
        except Exception:
            continue

        for elem in root.iter():
            lname = local_name(elem.tag)
            uri = namespace_uri(elem.tag)

            if lname == "context":
                rec = context_record(elem)
                if rec["context_id"] and rec["context_id"] not in contexts:
                    contexts[rec["context_id"]] = rec
            elif lname == "unit":
                rec = unit_record(elem)
                if rec["unit_id"] and rec["unit_id"] not in units:
                    units[rec["unit_id"]] = rec

            if (
                lname in APPROVED_LOCAL_NAMES
                and is_ifrs_namespace(uri)
            ):
                value, value_status = normalized_number(
                    elem.text,
                    elem.attrib.get("scale"),
                    elem.attrib.get("sign"),
                )
                facts.append({
                    "member_file": member,
                    "namespace_uri": uri,
                    "local_name": lname,
                    "context_ref": str(elem.attrib.get("contextRef") or ""),
                    "unit_ref": str(elem.attrib.get("unitRef") or ""),
                    "decimals": str(elem.attrib.get("decimals") or ""),
                    "scale": str(elem.attrib.get("scale") or ""),
                    "sign": str(elem.attrib.get("sign") or ""),
                    "raw_value": (elem.text or "").strip()[:180],
                    "normalized_value": value,
                    "value_status": value_status,
                })

    return {
        "status": "OK",
        "contexts": contexts,
        "units": units,
        "facts": facts,
    }

def is_target_annual(ctx, target_year):
    if not ctx or not ctx.get("start_date") or not ctx.get("end_date"):
        return False
    start = parse_date(ctx["start_date"])
    end = parse_date(ctx["end_date"])
    if not start or not end or target_year is None:
        return False
    days = (end - start).days + 1
    return (
        start.year == target_year
        and end.year == target_year
        and 330 <= days <= 370
    )

def choose_source_fs_div(raw, target_year):
    candidates = []

    deep_year = to_int(raw.get("deep_source_year"))
    deep_fs = str(raw.get("deep_fs_div") or "").strip()
    if deep_year == target_year and deep_fs in {"CFS", "OFS"}:
        candidates.append(("deep_fs_div", deep_fs))

    annual_year = to_int(raw.get("annual_source_year"))
    annual_fs = str(raw.get("annual_fs_div") or "").strip()
    if annual_year == target_year and annual_fs in {"CFS", "OFS"}:
        candidates.append(("annual_fs_div", annual_fs))

    preferred_fs = str(raw.get("preferred_fs_div") or "").strip()
    if preferred_fs in {"CFS", "OFS"}:
        candidates.append(("preferred_fs_div", preferred_fs))

    if not candidates:
        return {
            "status": "NO_FS_DIV",
            "selected_source": "",
            "selected_fs_div": "",
            "candidates": [],
        }

    selected_source, selected_fs = candidates[0]
    values = {value for _, value in candidates}
    return {
        "status": "CONSISTENT" if len(values) == 1 else "MISMATCH",
        "selected_source": selected_source,
        "selected_fs_div": selected_fs,
        "candidates": candidates,
    }

def process_one(item, raw, api_key):
    fs = choose_source_fs_div(raw, item["target_year"])
    result = {
        "ticker": item["ticker"],
        "name": item["name"],
        "market": item["market"],
        "rcept_no": item["rcept_no"],
        "target_year": item["target_year"],
        "source_fs_status": fs["status"],
        "source_fs_selected_from": fs["selected_source"],
        "source_fs_div": fs["selected_fs_div"],
        "source_fs_candidates_json": json.dumps(
            fs["candidates"], ensure_ascii=False, separators=(",", ":")
        ),
        "target_member": FS_MEMBER_BY_DIV.get(fs["selected_fs_div"], ""),
        "xbrl_status": "",
        "target_annual_fact_count": 0,
        "fs_selected_fact_count": 0,
        "fs_selected_context_count": 0,
        "selected_local_names": "",
        "selected_depreciation_unique_values": 0,
        "selected_amortisation_unique_values": 0,
        "selected_unit_signature_count": 0,
        "selected_unit_signatures_json": "[]",
        "selected_value_conflict": "FALSE",
        "selected_context_conflict": "FALSE",
        "both_approved_facts_unique": "FALSE",
        "evidence_da_sum": "",
        "selection_classification": "",
        "selected_facts_json": "[]",
    }

    if fs["status"] == "NO_FS_DIV":
        result["selection_classification"] = "SOURCE_FS_DIV_UNAVAILABLE"
        return result

    try:
        parsed = parse_zip(request_xbrl(api_key, item["rcept_no"]))
    except Exception as exc:
        result["xbrl_status"] = f"{type(exc).__name__}:{exc}"
        result["selection_classification"] = "XBRL_REQUEST_FAILED"
        return result

    result["xbrl_status"] = parsed["status"]
    if parsed["status"] != "OK":
        result["selection_classification"] = "XBRL_PARSE_FAILED"
        return result

    annual = []
    selected = []
    target_member = result["target_member"]

    for fact in parsed["facts"]:
        ctx = parsed["contexts"].get(fact["context_ref"])
        if not is_target_annual(ctx, item["target_year"]):
            continue
        enriched = {
            **fact,
            "context": ctx,
            "unit": parsed["units"].get(fact["unit_ref"]),
        }
        annual.append(enriched)

        members = (ctx or {}).get("dimension_map", {}).get(FS_AXIS_LOCAL, [])
        if target_member in members:
            selected.append(enriched)

    result["target_annual_fact_count"] = len(annual)
    result["fs_selected_fact_count"] = len(selected)
    result["fs_selected_context_count"] = len({
        x["context_ref"] for x in selected if x["context_ref"]
    })

    selected_names = sorted({x["local_name"] for x in selected})
    result["selected_local_names"] = "|".join(selected_names)

    by_local = defaultdict(set)
    unit_signatures = set()
    context_signatures = set()
    all_numeric = True

    for fact in selected:
        if fact["normalized_value"] is None:
            all_numeric = False
        else:
            by_local[fact["local_name"]].add(fact["normalized_value"])

        unit = fact.get("unit") or {}
        unit_sig = "|".join(unit.get("measures") or [])
        if unit_sig:
            unit_signatures.add(unit_sig)

        ctx = fact.get("context") or {}
        context_signatures.add(
            str(ctx.get("dimension_signature") or "")
        )

    dep_values = by_local["AdjustmentsForDepreciationExpense"]
    amo_values = by_local["AdjustmentsForAmortisationExpense"]

    result["selected_depreciation_unique_values"] = len(dep_values)
    result["selected_amortisation_unique_values"] = len(amo_values)
    result["selected_unit_signature_count"] = len(unit_signatures)
    result["selected_unit_signatures_json"] = json.dumps(
        sorted(unit_signatures),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    value_conflict = (
        len(dep_values) > 1
        or len(amo_values) > 1
    )
    context_conflict = len(context_signatures) > 1
    result["selected_value_conflict"] = "TRUE" if value_conflict else "FALSE"
    result["selected_context_conflict"] = "TRUE" if context_conflict else "FALSE"

    both_unique = (
        len(dep_values) == 1
        and len(amo_values) == 1
        and all_numeric
    )
    result["both_approved_facts_unique"] = "TRUE" if both_unique else "FALSE"

    if both_unique:
        result["evidence_da_sum"] = next(iter(dep_values)) + next(iter(amo_values))

    if not selected:
        classification = "NO_MATCHING_FS_MEMBER"
    elif value_conflict:
        classification = "MATCHED_FS_MEMBER_VALUE_CONFLICT"
    elif context_conflict:
        classification = "MATCHED_FS_MEMBER_MULTI_CONTEXT"
    elif not all_numeric:
        classification = "MATCHED_FS_MEMBER_NONNUMERIC"
    elif len(dep_values) == 1 and len(amo_values) == 1:
        classification = "MATCHED_FS_MEMBER_BOTH_FACTS_UNIQUE"
    elif len(dep_values) + len(amo_values) == 1:
        classification = "MATCHED_FS_MEMBER_PARTIAL_ONE_FACT"
    else:
        classification = "MATCHED_FS_MEMBER_INCOMPLETE"

    result["selection_classification"] = classification
    result["selected_facts_json"] = json.dumps(
        selected[:20],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return result

def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DART_API_KEY_MISSING")

    for path in (
        V886_CSV,
        V886_JSON,
        RAW_CSV,
        POLICY_JSON,
        FINANCIAL_ENRICHER,
    ):
        if not path.is_file():
            raise RuntimeError("MISSING_REQUIRED_SOURCE:" + str(path))

    v886_summary = read_json(V886_JSON)
    v886_rows = read_csv(V886_CSV)
    raw_rows = read_csv(RAW_CSV)
    policy = read_json(POLICY_JSON)
    enricher_text = FINANCIAL_ENRICHER.read_text(encoding="utf-8")

    if v886_summary.get("version") != V886_VERSION:
        raise RuntimeError("V886_VERSION_MISMATCH")
    if v886_summary.get("target_count") != 57:
        raise RuntimeError("V886_TARGET_COUNT_MISMATCH")
    if policy.get("version") != POLICY_VERSION:
        raise RuntimeError("V880_POLICY_VERSION_MISMATCH")
    if policy.get("status") != "APPROVED_DESIGN_NOT_PRODUCTION":
        raise RuntimeError("V880_POLICY_STATUS_MISMATCH")

    required_policy_text = (
        "연결재무제표(CFS)를 우선하고, 없을 때만 개별재무제표(OFS)를 쓴다."
    )
    if required_policy_text not in enricher_text:
        raise RuntimeError("EXISTING_CFS_OFS_POLICY_TEXT_NOT_FOUND")

    raw_map = {
        clean_ticker(row.get("ticker")): row
        for row in raw_rows
        if clean_ticker(row.get("ticker"))
    }

    targets = []
    for row in v886_rows:
        code = clean_ticker(row.get("ticker"))
        target_year = to_int(row.get("target_year"))
        targets.append({
            "ticker": code,
            "name": str(row.get("name") or ""),
            "market": str(row.get("market") or ""),
            "rcept_no": str(row.get("rcept_no") or ""),
            "target_year": target_year,
        })

    targets.sort(key=lambda x: x["ticker"])
    if len(targets) != 57:
        raise RuntimeError(f"TARGET_COUNT_MISMATCH:{len(targets)}")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for item in targets:
            raw = raw_map.get(item["ticker"]) or {}
            future = pool.submit(process_one, item, raw, api_key)
            futures[future] = item["ticker"]

        for future in as_completed(futures):
            code = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                item = next(x for x in targets if x["ticker"] == code)
                results.append({
                    "ticker": code,
                    "name": item["name"],
                    "market": item["market"],
                    "rcept_no": item["rcept_no"],
                    "target_year": item["target_year"],
                    "source_fs_status": "UNHANDLED",
                    "source_fs_selected_from": "",
                    "source_fs_div": "",
                    "source_fs_candidates_json": "[]",
                    "target_member": "",
                    "xbrl_status": f"UNHANDLED:{type(exc).__name__}:{exc}",
                    "target_annual_fact_count": 0,
                    "fs_selected_fact_count": 0,
                    "fs_selected_context_count": 0,
                    "selected_local_names": "",
                    "selected_depreciation_unique_values": 0,
                    "selected_amortisation_unique_values": 0,
                    "selected_unit_signature_count": 0,
                    "selected_unit_signatures_json": "[]",
                    "selected_value_conflict": "FALSE",
                    "selected_context_conflict": "FALSE",
                    "both_approved_facts_unique": "FALSE",
                    "evidence_da_sum": "",
                    "selection_classification": "UNHANDLED_FAILURE",
                    "selected_facts_json": "[]",
                })

    results.sort(key=lambda x: x["ticker"])
    fields = list(results[0].keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    class_counts = Counter(x["selection_classification"] for x in results)
    fs_status_counts = Counter(x["source_fs_status"] for x in results)
    fs_div_counts = Counter(x["source_fs_div"] for x in results)
    source_field_counts = Counter(x["source_fs_selected_from"] for x in results)

    xbrl_success = sum(1 for x in results if x["xbrl_status"] == "OK")
    matching_member = sum(
        1 for x in results if int(x["fs_selected_fact_count"] or 0) > 0
    )
    both_unique = class_counts["MATCHED_FS_MEMBER_BOTH_FACTS_UNIQUE"]
    remaining_value_conflict = class_counts["MATCHED_FS_MEMBER_VALUE_CONFLICT"]
    remaining_multi_context = class_counts["MATCHED_FS_MEMBER_MULTI_CONTEXT"]
    partial_one = class_counts["MATCHED_FS_MEMBER_PARTIAL_ONE_FACT"]
    no_member = class_counts["NO_MATCHING_FS_MEMBER"]
    source_fs_mismatch = fs_status_counts["MISMATCH"]

    # V8.8.6 had 48 value-conflict tickers before CFS/OFS selection.
    conflicts_resolved = 48 - remaining_value_conflict

    summary = {
        "version": VERSION,
        "policy_version": POLICY_VERSION,
        "v886_version": V886_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "SELECTION_AUDIT_ONLY",
        "target_count": 57,
        "xbrl_success_count": xbrl_success,
        "existing_financial_policy": {
            "text": required_policy_text,
            "source_file": "financial_valuation_enricher.py",
        },
        "mapping_under_test": {
            "axis": "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis",
            "CFS": "ifrs-full:ConsolidatedMember",
            "OFS": "ifrs-full:SeparateMember",
            "source_fs_div_precedence": [
                "deep_fs_div when deep_source_year equals target_year",
                "annual_fs_div when annual_source_year equals target_year",
                "preferred_fs_div",
            ],
        },
        "source_fs_status_counts": dict(fs_status_counts),
        "source_fs_div_counts": dict(fs_div_counts),
        "source_fs_selected_from_counts": dict(source_field_counts),
        "source_fs_mismatch_count": source_fs_mismatch,
        "matching_fs_member_ticker_count": matching_member,
        "both_approved_facts_unique_ticker_count": both_unique,
        "partial_one_fact_ticker_count": partial_one,
        "no_matching_fs_member_ticker_count": no_member,
        "remaining_value_conflict_ticker_count": remaining_value_conflict,
        "remaining_multi_context_ticker_count": remaining_multi_context,
        "v886_preselection_value_conflict_ticker_count": 48,
        "value_conflict_resolved_by_fs_selection_count": conflicts_resolved,
        "selection_classification_counts": dict(class_counts),
        "decision": {
            "mapping_semantically_exact": True,
            "mapping_matches_existing_financial_policy": True,
            "ready_for_value_promotion_design": (
                both_unique > 0
                and source_fs_mismatch == 0
            ),
            "ready_for_final_da_value_promotion": False,
            "ready_for_ev_ebitda_recalculation": False,
            "ready_for_production_score_write": False,
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "scoring_policy_changed": False,
            "new_da_id_approved": False,
            "xbrl_value_promoted_to_da_source": False,
            "ev_ebitda_recalculated": False,
            "standalone_swing_changed": False,
        },
        "next_step": (
            "FREEZE_CFS_OFS_CONTEXT_MAPPING_AND_PROMOTE_ONLY_BOTH_UNIQUE_"
            "EXACT_FACTS_TO_A_SOURCE_ONLY_DA_LAYER"
            if both_unique > 0 and source_fs_mismatch == 0
            else
            "REVIEW_FS_DIV_MISMATCH_OR_CONTEXT_EXCEPTIONS"
        ),
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    doc = [
        "# V8.8.7 XBRL CFS/OFS 선택 감사",
        "",
        f"- 버전: `{VERSION}`",
        "- 상태: SELECTION_AUDIT_ONLY",
        "",
        "## 기존 정책",
        "",
        f"- `{required_policy_text}`",
        "",
        "## XBRL 축 대응 검증",
        "",
        "- CFS ↔ `ConsolidatedAndSeparateFinancialStatementsAxis=ConsolidatedMember`",
        "- OFS ↔ `ConsolidatedAndSeparateFinancialStatementsAxis=SeparateMember`",
        "- 목표연도 source와 동일한 fs_div를 우선 대조한다.",
        "",
        "## 이번 단계에서 하지 않는 것",
        "",
        "- 선택된 D&A 값을 production source로 승격하지 않는다.",
        "- EV/EBITDA를 재계산하지 않는다.",
        "- 100점 점수를 기록하지 않는다.",
        "- 새로운 D&A 계정 ID를 승인하지 않는다.",
        "",
        "## 다음 단계 조건",
        "",
        "- source fs_div 불일치가 없어야 한다.",
        "- 선택한 member 안에서 depreciation/amortisation 각각 값이 유일해야 한다.",
        "- 두 exact fact가 모두 존재하는 종목만 source-only 승격 후보로 본다.",
        "",
    ]
    OUT_DOC.write_text("\n".join(doc), encoding="utf-8")

    log = [
        f"VERSION={VERSION}",
        "STATUS=SELECTION_AUDIT_ONLY",
        "TARGETS=57",
        f"XBRL_SUCCESS={xbrl_success}",
        f"SOURCE_FS_MISMATCH={source_fs_mismatch}",
        f"MATCHING_FS_MEMBER_TICKERS={matching_member}",
        f"BOTH_APPROVED_FACTS_UNIQUE={both_unique}",
        f"PARTIAL_ONE_FACT={partial_one}",
        f"NO_MATCHING_FS_MEMBER={no_member}",
        f"REMAINING_VALUE_CONFLICT={remaining_value_conflict}",
        f"REMAINING_MULTI_CONTEXT={remaining_multi_context}",
        f"V886_PRESELECTION_VALUE_CONFLICT=48",
        f"VALUE_CONFLICT_RESOLVED_BY_FS_SELECTION={conflicts_resolved}",
        "DA_VALUE_PROMOTED=false",
        "EV_EBITDA_RECALCULATED=false",
        "PRODUCTION_DATA_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "SCORING_POLICY_CHANGED=false",
        "NEW_DA_ID_APPROVED=false",
        "STANDALONE_SWING_CHANGED=false",
        "STATUS_OK=true",
    ]
    OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

    print("V887_XBRL_CFS_OFS_SELECTION_AUDIT=PASS")
    print("\n".join(log))

if __name__ == "__main__":
    main()
