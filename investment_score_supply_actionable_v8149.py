#!/usr/bin/env python3
from __future__ import annotations

import ast
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

VERSION = "2026-09-22-v8.14.9-uangel-current-actionable-supply-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
SUPPLY_POLICY_VERSION = "2026-07-01-v6.0-supply-status-separated"
V8148_VERSION = "2026-09-22-v8.14.8-post-elasticity-dynamic-blocker-reaudit"
V8148_RESULT_COMMIT = "6cfff69c2645ae2e344c58c672b8919c9dfcebf0"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8148.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8148_summary_latest.json"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"
PROD_SUPPLY = ROOT / "latest/investment_score_supply_source_latest.csv"
SUPPLY_ENRICHER = ROOT / "supply_burden_enricher.py"

OUT_CSV = ROOT / "latest/investment_score_supply_actionable_v8149.csv"
OUT_JSON = ROOT / "latest/investment_score_supply_actionable_v8149_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_supply_actionable_v8149_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_supply_actionable_v8149.md"

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
LIST_URL = "https://opendart.fss.or.kr/api/list.json"

TARGET = "072130"
TARGET_NAME = "유엔젤"
EXPECTED_CORP_CODE = "00416654"
TARGET_REASON = "수급·공시부담:SUPPLY_LIMITED_NO_POSITIVE_EVIDENCE"

REQUESTED_LOOKBACK_DAYS = 180
CHUNK_DAYS = 90
REQUEST_TIMEOUT = 35
REQUEST_ATTEMPTS = 4
PAGE_COUNT = 100

def read_json(path):
    return json.loads(
        Path(path).read_text(encoding="utf-8-sig")
    )

def read_csv(path):
    with Path(path).open(
        encoding="utf-8-sig",
        newline="",
    ) as f:
        return list(csv.DictReader(f))

def ticker(value):
    s = "".join(
        ch for ch in str(value or "")
        if ch.isdigit()
    )
    return s.zfill(6) if s else ""

def literal_constant_from_python(path, name):
    tree = ast.parse(
        Path(path).read_text(encoding="utf-8")
    )
    for node in tree.body:
        if isinstance(
            node,
            (ast.Assign, ast.AnnAssign),
        ):
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            else:
                targets = [node.target]
                value = node.value

            for target in targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == name
                ):
                    return ast.literal_eval(value)

    raise RuntimeError(
        "V8149_SUPPLY_CONTRACT_CONSTANT_NOT_FOUND:"
        + name
    )

def load_supply_contract():
    text = Path(SUPPLY_ENRICHER).read_text(
        encoding="utf-8"
    )
    if SUPPLY_POLICY_VERSION not in text:
        raise RuntimeError(
            "V8149_SUPPLY_POLICY_VERSION_NOT_FOUND"
        )

    rules = literal_constant_from_python(
        SUPPLY_ENRICHER,
        "KEYWORD_RULES",
    )
    relief = literal_constant_from_python(
        SUPPLY_ENRICHER,
        "RELIEF_KEYWORDS",
    )

    if not rules:
        raise RuntimeError(
            "V8149_SUPPLY_KEYWORD_RULES_EMPTY"
        )

    return rules, relief

def request_bytes(url):
    last = None

    for attempt in range(
        1,
        REQUEST_ATTEMPTS + 1,
    ):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "krx-watchlist-v8149-uangel-supply-audit"
                ),
                "Accept": "*/*",
                "Cache-Control": "no-cache",
            },
        )

        try:
            with urllib.request.urlopen(
                req,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                return response.read()
        except Exception as exc:
            last = exc
            if attempt < REQUEST_ATTEMPTS:
                time.sleep(
                    0.8 * attempt
                )

    raise RuntimeError(
        "V8149_HTTP_REQUEST_FAILED:"
        + type(last).__name__
        + ":"
        + str(last)
    )

def request_json(url):
    blob = request_bytes(url)
    try:
        return json.loads(
            blob.decode(
                "utf-8",
                errors="replace",
            )
        )
    except Exception as exc:
        raise RuntimeError(
            "V8149_JSON_DECODE_FAILED:"
            + type(exc).__name__
            + ":"
            + str(exc)
        )

def fetch_corp_code_map(api_key):
    url = (
        CORP_CODE_URL
        + "?"
        + urllib.parse.urlencode({
            "crtfc_key": api_key,
        })
    )
    blob = request_bytes(url)

    try:
        zf = zipfile.ZipFile(
            io.BytesIO(blob)
        )
    except zipfile.BadZipFile as exc:
        raise RuntimeError(
            "V8149_DART_CORPCODE_NOT_ZIP"
        ) from exc

    xml_names = [
        n
        for n in zf.namelist()
        if n.lower().endswith(".xml")
    ]
    if not xml_names:
        raise RuntimeError(
            "V8149_DART_CORPCODE_XML_MISSING"
        )

    root = ET.fromstring(
        zf.read(xml_names[0])
    )
    duplicates = defaultdict(list)

    for item in root.findall(".//list"):
        stock = ticker(
            item.findtext(
                "stock_code"
            ) or ""
        )
        corp_code = str(
            item.findtext(
                "corp_code"
            ) or ""
        ).strip()
        corp_name = str(
            item.findtext(
                "corp_name"
            ) or ""
        ).strip()

        if not stock or not corp_code:
            continue

        duplicates[stock].append(
            (
                corp_code,
                corp_name,
            )
        )

    values = sorted(
        set(
            duplicates.get(
                TARGET,
                [],
            )
        )
    )

    return {
        "values": values,
        "exact_stock_match_count": len(
            values
        ),
    }

def classify_report(
    report_name,
    keyword_rules,
    relief_keywords,
):
    title = str(
        report_name or ""
    )
    matched = []
    severity = 0

    for (
        keyword,
        label,
        level,
    ) in keyword_rules:
        if keyword in title:
            matched.append(label)
            severity = max(
                severity,
                int(level),
            )

    relief = any(
        keyword in title
        for keyword in relief_keywords
    )

    return (
        bool(matched),
        sorted(set(matched)),
        severity,
        relief,
    )

def severity_to_level(
    severity,
    count,
):
    if severity >= 3:
        return "위험"
    if severity == 2:
        return (
            "위험"
            if count >= 3
            else "경계"
        )
    if severity == 1:
        return (
            "경계"
            if count >= 3
            else "주의"
        )
    return "없음"

def date_chunks(start, end):
    chunks = []
    cur = start

    while cur <= end:
        chunk_end = min(
            cur
            + timedelta(
                days=CHUNK_DAYS - 1
            ),
            end,
        )
        chunks.append(
            (
                cur,
                chunk_end,
            )
        )
        cur = (
            chunk_end
            + timedelta(days=1)
        )

    return chunks

def fetch_corp_reports(
    api_key,
    corp_code,
    start,
    end,
):
    all_reports = []
    calls = 0
    summaries = []
    errors = []

    chunks = date_chunks(
        start,
        end,
    )

    for (
        chunk_start,
        chunk_end,
    ) in chunks:
        page = 1
        chunk_reports = 0
        chunk_pages = 0
        chunk_complete = True
        total_page_seen = None
        chunk_013 = False

        while True:
            params = {
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bgn_de": (
                    chunk_start.strftime(
                        "%Y%m%d"
                    )
                ),
                "end_de": (
                    chunk_end.strftime(
                        "%Y%m%d"
                    )
                ),
                "page_no": page,
                "page_count": PAGE_COUNT,
            }
            url = (
                LIST_URL
                + "?"
                + urllib.parse.urlencode(
                    params
                )
            )

            try:
                payload = request_json(
                    url
                )
                calls += 1
            except Exception as exc:
                chunk_complete = False
                errors.append(
                    f"{chunk_start}:{chunk_end}:"
                    f"page={page}:"
                    f"{type(exc).__name__}:{exc}"
                )
                break

            status = str(
                payload.get(
                    "status"
                ) or ""
            )

            if status == "013":
                # Exact issuer/date chunk official no-data.
                chunk_013 = True
                total_page_seen = 0
                break

            if status != "000":
                chunk_complete = False
                errors.append(
                    f"{chunk_start}:{chunk_end}:"
                    f"page={page}:"
                    f"DART_STATUS={status}:"
                    f"{payload.get('message') or ''}"
                )
                break

            rows = (
                payload.get("list")
                or []
            )
            if not isinstance(
                rows,
                list,
            ):
                chunk_complete = False
                errors.append(
                    f"{chunk_start}:{chunk_end}:"
                    f"page={page}:"
                    "LIST_NOT_ARRAY"
                )
                break

            chunk_pages += 1
            chunk_reports += len(
                rows
            )
            all_reports.extend(
                rows
            )

            try:
                total_page = int(
                    payload.get(
                        "total_page"
                    ) or 1
                )
            except Exception:
                chunk_complete = False
                errors.append(
                    f"{chunk_start}:{chunk_end}:"
                    f"page={page}:"
                    "TOTAL_PAGE_INVALID"
                )
                break

            total_page_seen = (
                total_page
            )

            if page >= total_page:
                break

            page += 1

            if page > 100:
                chunk_complete = False
                errors.append(
                    f"{chunk_start}:{chunk_end}:"
                    "PAGE_SAFETY_LIMIT"
                )
                break

            time.sleep(0.05)

        summaries.append({
            "start": (
                chunk_start.isoformat()
            ),
            "end": (
                chunk_end.isoformat()
            ),
            "complete": (
                chunk_complete
            ),
            "official_013_no_data": (
                chunk_013
            ),
            "pages_fetched": (
                chunk_pages
            ),
            "total_page_seen": (
                total_page_seen
            ),
            "report_count": (
                chunk_reports
            ),
        })

    complete = (
        len(summaries)
        == len(chunks)
        and all(
            x["complete"]
            for x in summaries
        )
        and not errors
    )

    return {
        "complete": complete,
        "reports": all_reports,
        "api_calls": calls,
        "chunks": summaries,
        "api_errors": errors,
    }

def main():
    api_key = os.environ.get(
        "DART_API_KEY",
        "",
    ).strip()

    if not api_key:
        raise RuntimeError(
            "V8149_DART_API_KEY_MISSING"
        )

    for p in (
        BLOCK_CSV,
        BLOCK_JSON,
        FIN,
        PROD_SUPPLY,
        SUPPLY_ENRICHER,
    ):
        if not Path(p).is_file():
            raise RuntimeError(
                "V8149_MISSING_INPUT:"
                + str(p)
            )

    s8148 = read_json(
        BLOCK_JSON
    )

    if s8148.get(
        "version"
    ) != V8148_VERSION:
        raise RuntimeError(
            "V8149_V8148_VERSION_MISMATCH"
        )
    if s8148.get(
        "status"
    ) != (
        "AUDIT_ONLY_POST_ELASTICITY_DYNAMIC_CURRENT_BLOCKERS"
    ):
        raise RuntimeError(
            "V8149_V8148_STATUS_MISMATCH"
        )
    if s8148.get(
        "policy_version"
    ) != POLICY_VERSION:
        raise RuntimeError(
            "V8149_POLICY_VERSION_MISMATCH"
        )
    if s8148.get(
        "selection_mode"
    ) != (
        "ACTIONABLE_SINGLE_BLOCKER"
    ):
        raise RuntimeError(
            "V8149_SELECTION_MODE_CHANGED"
        )
    if s8148.get(
        "selected_source_group"
    ) != (
        "PRODUCTION_ANALYSIS_SUPPLY"
    ):
        raise RuntimeError(
            "V8149_SELECTED_GROUP_CHANGED"
        )
    if s8148.get(
        "selected_tickers"
    ) != [TARGET]:
        raise RuntimeError(
            "V8149_SELECTED_TARGET_CHANGED"
        )
    if s8148.get(
        "next_step"
    ) != (
        "AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8149"
    ):
        raise RuntimeError(
            "V8149_PREDECESSOR_NEXT_STEP_MISMATCH"
        )

    block_rows = read_csv(
        BLOCK_CSV
    )

    action = [
        r
        for r in block_rows
        if ticker(
            r.get("ticker")
        ) == TARGET
        and r.get(
            "source_group"
        ) == (
            "PRODUCTION_ANALYSIS_SUPPLY"
        )
        and r.get(
            "single_blocker_ticker"
        ) == "TRUE"
        and r.get(
            "recovery_status"
        ) == (
            "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
        )
    ]

    if len(action) != 1:
        raise RuntimeError(
            "V8149_TARGET_BLOCKER_ROW_COUNT_NOT_1"
        )

    blocker = action[0]

    if blocker.get(
        "name"
    ) != TARGET_NAME:
        raise RuntimeError(
            "V8149_TARGET_NAME_MISMATCH"
        )
    if blocker.get(
        "blocker_reason"
    ) != TARGET_REASON:
        raise RuntimeError(
            "V8149_TARGET_REASON_MISMATCH"
        )

    fin_rows = {
        ticker(
            r.get("ticker")
        ): r
        for r in read_csv(FIN)
        if ticker(
            r.get("ticker")
        )
    }

    fin = fin_rows.get(
        TARGET
    )
    if not fin:
        raise RuntimeError(
            "V8149_FIN_TARGET_MISSING"
        )
    if fin.get(
        "name"
    ) != TARGET_NAME:
        raise RuntimeError(
            "V8149_FIN_NAME_MISMATCH"
        )
    if fin.get(
        "corp_identity_status"
    ) not in {
        "MATCH",
        "MATCH_NORMALIZED",
    }:
        raise RuntimeError(
            "V8149_FIN_IDENTITY_NOT_MATCH"
        )
    if str(
        fin.get(
            "corp_code"
        ) or ""
    ) != EXPECTED_CORP_CODE:
        raise RuntimeError(
            "V8149_FIN_CORP_CODE_CHANGED"
        )

    prod_supply_codes = {
        ticker(
            r.get("ticker")
        )
        for r in read_csv(
            PROD_SUPPLY
        )
        if ticker(
            r.get("ticker")
        )
    }

    if TARGET in prod_supply_codes:
        raise RuntimeError(
            "V8149_TARGET_ALREADY_IN_PROD_SUPPLY_SOURCE"
        )

    (
        keyword_rules,
        relief_keywords,
    ) = load_supply_contract()

    corp = fetch_corp_code_map(
        api_key
    )

    if int(
        corp[
            "exact_stock_match_count"
        ]
    ) != 1:
        raise RuntimeError(
            "V8149_DART_EXACT_STOCK_NOT_UNIQUE:"
            + str(
                corp[
                    "exact_stock_match_count"
                ]
            )
        )

    dart_code, dart_name = (
        corp["values"][0]
    )

    if (
        dart_code
        != EXPECTED_CORP_CODE
    ):
        raise RuntimeError(
            "V8149_DART_CORP_CODE_CHANGED:"
            + str(dart_code)
        )
    if (
        dart_code
        != str(
            fin.get(
                "corp_code"
            ) or ""
        )
    ):
        raise RuntimeError(
            "V8149_CORP_CODE_CROSSCHECK_MISMATCH"
        )

    audit_end = datetime.now(
        KST
    ).date()
    audit_start = (
        audit_end
        - timedelta(
            days=(
                REQUESTED_LOOKBACK_DAYS
                - 1
            )
        )
    )

    fetched = fetch_corp_reports(
        api_key,
        dart_code,
        audit_start,
        audit_end,
    )

    evidence = []
    max_severity = 0
    keyword_set = set()
    relief_count = 0

    if fetched[
        "complete"
    ]:
        for item in fetched[
            "reports"
        ]:
            report_name = str(
                item.get(
                    "report_nm"
                ) or ""
            )

            (
                is_risk,
                labels,
                severity,
                relief,
            ) = classify_report(
                report_name,
                keyword_rules,
                relief_keywords,
            )

            if relief:
                relief_count += 1

            if not is_risk:
                continue

            max_severity = max(
                max_severity,
                severity,
            )
            keyword_set.update(
                labels
            )

            evidence.append({
                "rcept_dt": str(
                    item.get(
                        "rcept_dt"
                    ) or ""
                ),
                "rcept_no": str(
                    item.get(
                        "rcept_no"
                    ) or ""
                ),
                "report_nm": (
                    report_name
                ),
                "corp_name": str(
                    item.get(
                        "corp_name"
                    ) or ""
                ),
                "keywords": labels,
                "severity": severity,
                "relief_flag": (
                    relief
                ),
            })

    evidence.sort(
        key=lambda x: (
            x[
                "rcept_dt"
            ],
            x[
                "rcept_no"
            ],
        ),
        reverse=True,
    )

    if not fetched[
        "complete"
    ]:
        classification = (
            "TARGETED_DART_180D_INCOMPLETE"
        )
        proposed_status = ""
        proposed_level = ""
        overlay_candidate = False
    elif evidence:
        classification = (
            "COMPLETE_180D_POSITIVE_BURDEN"
        )
        proposed_status = "OK"
        proposed_level = (
            severity_to_level(
                max_severity,
                len(evidence),
            )
        )
        overlay_candidate = True
    else:
        classification = (
            "COMPLETE_180D_NO_POSITIVE_BURDEN"
        )
        proposed_status = "OK"
        proposed_level = "없음"
        overlay_candidate = True

    latest = (
        evidence[0]
        if evidence
        else {}
    )

    row = {
        "ticker": TARGET,
        "name": TARGET_NAME,
        "market": (
            blocker.get(
                "market"
            )
            or ""
        ),
        "baseline_blocker_reason": (
            TARGET_REASON
        ),
        "baseline_supply_status": "LIMITED",
        "baseline_supply_level": "없음",
        "corp_code": dart_code,
        "corp_name_dart": dart_name,
        "corp_code_exact_stock_match_count": 1,
        "audit_start_date": (
            audit_start.isoformat()
        ),
        "audit_end_date": (
            audit_end.isoformat()
        ),
        "requested_lookback_days": (
            REQUESTED_LOOKBACK_DAYS
        ),
        "chunk_days": (
            CHUNK_DAYS
        ),
        "chunk_count": len(
            fetched[
                "chunks"
            ]
        ),
        "dart_list_api_calls": (
            fetched[
                "api_calls"
            ]
        ),
        "dart_report_count": len(
            fetched[
                "reports"
            ]
        ),
        "risk_report_count": len(
            evidence
        ),
        "relief_report_match_count": (
            relief_count
        ),
        "classification": (
            classification
        ),
        "proposed_supply_status": (
            proposed_status
        ),
        "proposed_supply_level": (
            proposed_level
        ),
        "risk_keywords": ",".join(
            sorted(
                keyword_set
            )
        ),
        "latest_risk_report_date": (
            latest.get(
                "rcept_dt"
            ) or ""
        ),
        "latest_risk_report_name": (
            latest.get(
                "report_nm"
            ) or ""
        ),
        "latest_risk_rcept_no": (
            latest.get(
                "rcept_no"
            ) or ""
        ),
        "source_overlay_candidate": (
            "TRUE"
            if overlay_candidate
            else "FALSE"
        ),
        "chunk_summaries_json": json.dumps(
            fetched[
                "chunks"
            ],
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        ),
        "evidence_reports_json": json.dumps(
            evidence,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        ),
        "api_errors_json": json.dumps(
            fetched[
                "api_errors"
            ],
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        ),
    }

    OUT_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUT_CSV.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        w = csv.DictWriter(
            f,
            fieldnames=list(
                row.keys()
            ),
            lineterminator="\n",
        )
        w.writeheader()
        w.writerow(row)

    if fetched[
        "complete"
    ]:
        next_step = (
            "FREEZE_UANGEL_SUPPLY_AND_SHADOW_SCORE_V8150"
        )
    else:
        next_step = (
            "REVIEW_INCOMPLETE_UANGEL_SUPPLY_BEFORE_PROMOTION"
        )

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(
            KST
        ).isoformat(
            timespec="seconds"
        ),
        "status": (
            "AUDIT_ONLY_CURRENT_ACTIONABLE_SUPPLY"
        ),
        "policy_version": (
            POLICY_VERSION
        ),
        "supply_policy_version": (
            SUPPLY_POLICY_VERSION
        ),
        "v8148_version": (
            V8148_VERSION
        ),
        "v8148_result_commit": (
            V8148_RESULT_COMMIT
        ),
        "target_count": 1,
        "target_tickers": [
            TARGET
        ],
        "target_names": [
            TARGET_NAME
        ],
        "corp_code_exact_resolved_count": 1,
        "corp_code_unresolved_count": 0,
        "audit_start_date": (
            audit_start.isoformat()
        ),
        "audit_end_date": (
            audit_end.isoformat()
        ),
        "requested_lookback_days": (
            REQUESTED_LOOKBACK_DAYS
        ),
        "chunk_days": (
            CHUNK_DAYS
        ),
        "chunk_count": len(
            fetched[
                "chunks"
            ]
        ),
        "complete_180d_count": (
            1
            if fetched[
                "complete"
            ]
            else 0
        ),
        "complete_180d_positive_burden_count": (
            1
            if (
                fetched[
                    "complete"
                ]
                and evidence
            )
            else 0
        ),
        "complete_180d_no_positive_burden_count": (
            1
            if (
                fetched[
                    "complete"
                ]
                and not evidence
            )
            else 0
        ),
        "incomplete_180d_count": (
            0
            if fetched[
                "complete"
            ]
            else 1
        ),
        "source_overlay_candidate_count": (
            1
            if overlay_candidate
            else 0
        ),
        "classification_counts": {
            classification: 1
        },
        "proposed_supply_status": (
            proposed_status
        ),
        "proposed_supply_level": (
            proposed_level
        ),
        "risk_keywords": sorted(
            keyword_set
        ),
        "dart_activity": {
            "corp_code_download_count": 1,
            "list_api_call_count": (
                fetched[
                    "api_calls"
                ]
            ),
            "report_count": len(
                fetched[
                    "reports"
                ]
            ),
            "recognized_risk_report_count": len(
                evidence
            ),
            "official_013_chunk_count": sum(
                1
                for x in fetched[
                    "chunks"
                ]
                if x[
                    "official_013_no_data"
                ]
            ),
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_supply_source_modified": False,
            "scoring_policy_changed": False,
            "supply_policy_changed": False,
            "limited_absence_treated_as_complete": False,
            "incomplete_query_treated_as_absence": False,
            "issuer_mapping_guessed": False,
            "production_supply_status_overridden": False,
        },
        "next_step": (
            next_step
        ),
    }

    OUT_JSON.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY_CURRENT_ACTIONABLE_SUPPLY",
            "TARGET_COUNT=1",
            "TARGET_TICKER=072130",
            "CORP_CODE_EXACT_RESOLVED_COUNT=1",
            (
                "COMPLETE_180D_COUNT="
                + str(
                    summary[
                        "complete_180d_count"
                    ]
                )
            ),
            (
                "COMPLETE_180D_POSITIVE_BURDEN_COUNT="
                + str(
                    summary[
                        "complete_180d_positive_burden_count"
                    ]
                )
            ),
            (
                "COMPLETE_180D_NO_POSITIVE_BURDEN_COUNT="
                + str(
                    summary[
                        "complete_180d_no_positive_burden_count"
                    ]
                )
            ),
            (
                "INCOMPLETE_180D_COUNT="
                + str(
                    summary[
                        "incomplete_180d_count"
                    ]
                )
            ),
            (
                "SOURCE_OVERLAY_CANDIDATE_COUNT="
                + str(
                    summary[
                        "source_overlay_candidate_count"
                    ]
                )
            ),
            (
                "PROPOSED_SUPPLY_STATUS="
                + proposed_status
            ),
            (
                "PROPOSED_SUPPLY_LEVEL="
                + proposed_level
            ),
            "PRODUCTION_API_CHANGED=false",
            "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
            "PRODUCTION_SUPPLY_SOURCE_MODIFIED=false",
            "SCORING_POLICY_CHANGED=false",
            "SUPPLY_POLICY_CHANGED=false",
            "ISSUER_MAPPING_GUESSED=false",
            "STATUS_OK=true",
            f"NEXT_STEP={next_step}",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUT_DOC.write_text(
        "\n".join([
            "# V8.14.9 UANGEL current actionable supply audit",
            "",
            "- Target: 유엔젤 (072130).",
            "- Current blocker: `SUPPLY_LIMITED_NO_POSITIVE_EVIDENCE` only.",
            "- Existing supply policy is reused unchanged.",
            "- OpenDART is queried for the exact issuer over 180 days in 90-day chunks.",
            "- Every page and chunk must be complete before absence can become `OK/없음`.",
            "- Exact DART stock-code identity is cross-checked with financial cache corp_code 00416654.",
            "- Official DART status 013 is accepted only as no-data evidence for the exact issuer/date chunk.",
            "- This step is audit-only; production source/API/score is not modified.",
            "",
            f"- Complete 180d: {summary['complete_180d_count']}/1",
            f"- Positive burden: {summary['complete_180d_positive_burden_count']}",
            f"- No positive burden: {summary['complete_180d_no_positive_burden_count']}",
            f"- Incomplete: {summary['incomplete_180d_count']}",
            f"- Proposed level: `{proposed_level}`",
            "",
            f"Next: `{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        "V8149_UANGEL_SUPPLY_AUDIT=PASS"
    )

if __name__ == "__main__":
    main()
