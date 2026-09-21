#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-21-v8.13.0-current-actionable-ocf-single-blocker-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8128_VERSION = "2026-09-21-v8.12.8-post-apply-current-blocker-reaudit"
V8128_RESULT_COMMIT = "282b37236be05eb7ecbc04356f8c305cc0bcccbe"
V8129_VERSION = "2026-09-21-v8.12.9-current-actionable-exact-da-single-blocker-audit"
V8129_RESULT_COMMIT = "658b08079bc45110271a85d799722950b024e8ed"
OCF_CONTRACT_VERSION = "2026-09-12-v8.7.4-audited-operating-cash-flow-source"

IFRS_OCF_ID = "ifrs-full_CashFlowsFromUsedInOperatingActivities"
DART_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8128.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8128_summary_latest.json"
V8129_JSON = ROOT / "latest/investment_score_exact_da_actionable_v8129_summary_latest.json"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"
PROD_OCF = ROOT / "latest/investment_score_ocf_source_latest.csv"
PROD_OCF_META = ROOT / "latest/investment_score_ocf_source_latest.json"

OUT_CSV = ROOT / "latest/investment_score_ocf_actionable_v8130.csv"
OUT_JSON = ROOT / "latest/investment_score_ocf_actionable_v8130_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_ocf_actionable_v8130_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_ocf_actionable_v8130.md"

EXPECTED = {
    "000080": "하이트진로",
    "002710": "TCC스틸",
    "007690": "국도화학",
    "042700": "한미반도체",
}
EXPECTED_CORP = {
    "000080": "00150244",
    "002710": "00117300",
    "007690": "00104388",
    "042700": "00161383",
}
ANNUAL_YEAR = "2025"
REPORT_CODE = "11011"
MAX_TRANSPORT_RETRIES = 3

def ticker(value):
    s = re.sub(r"[^0-9]", "", str(value or "").strip())
    return s.zfill(6) if s else ""

def corp(value):
    s = re.sub(r"[^0-9]", "", str(value or "").strip())
    return s.zfill(8) if s else ""

def norm(value):
    return str(value or "").strip()

def num(value):
    text = norm(value).replace(",", "")
    if text in {"", "-", "None", "null", "nan", "NaN"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = re.sub(r"[^0-9eE+\-.]", "", text)
    if text in {"", "-", "+", ".", "-.", "+."}:
        return None
    try:
        x = float(text)
    except ValueError:
        return None
    return -abs(x) if negative else x

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def request_payload(api_key, corp_code, fs_div):
    query = urllib.parse.urlencode({
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": ANNUAL_YEAR,
        "reprt_code": REPORT_CODE,
        "fs_div": fs_div,
    })
    req = urllib.request.Request(
        f"{DART_URL}?{query}",
        headers={
            "User-Agent": "krx-watchlist-v8130-ocf-audit-retry",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
    )
    errors = []
    for attempt in range(1, MAX_TRANSPORT_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                payload = json.loads(
                    response.read(12_000_000).decode("utf-8")
                )
            return payload, errors
        except Exception as exc:
            errors.append(
                f"attempt{attempt}:{type(exc).__name__}:{exc}"
            )
            if attempt < MAX_TRANSPORT_RETRIES:
                time.sleep(1.0 * attempt)
    return None, errors

def fetch_exact_ocf(api_key, corp_code):
    attempts = []

    for fs_div in ("CFS", "OFS"):
        payload, errors = request_payload(api_key, corp_code, fs_div)
        if payload is None:
            attempts.append({
                "fs_div": fs_div,
                "transport_status": "ERROR",
                "transport_errors": errors,
                "dart_status": "",
                "message": "",
                "exact_match_count": 0,
                "unique_numeric_values": [],
                "account_names": [],
            })
            continue

        status = norm(payload.get("status"))
        message = norm(payload.get("message"))
        items = payload.get("list")
        if not isinstance(items, list):
            items = []

        matches = [
            item for item in items
            if norm(item.get("sj_div")) == "CF"
            and norm(item.get("account_id")) == IFRS_OCF_ID
        ]
        values = sorted({
            num(item.get("thstrm_amount"))
            for item in matches
            if num(item.get("thstrm_amount")) is not None
        })
        names = sorted({
            norm(item.get("account_nm"))
            for item in matches
            if norm(item.get("account_nm"))
        })

        attempts.append({
            "fs_div": fs_div,
            "transport_status": "OK",
            "transport_errors": errors,
            "dart_status": status,
            "message": message,
            "exact_match_count": len(matches),
            "unique_numeric_values": values,
            "account_names": names,
        })

        if status != "000":
            continue

        if len(values) == 1:
            return {
                "classification": "RECOVERABLE_EXACT_OCF",
                "source_status": "READY",
                "amount": values[0],
                "fs_div": fs_div,
                "account_names": names,
                "attempts": attempts,
            }

        if len(values) > 1:
            return {
                "classification": "EXACT_OCF_VALUE_CONFLICT",
                "source_status": "LIMITED",
                "amount": None,
                "fs_div": fs_div,
                "account_names": names,
                "attempts": attempts,
            }

    successful_official_query = any(
        a["transport_status"] == "OK"
        and a.get("dart_status") == "000"
        for a in attempts
    )

    return {
        "classification": (
            "NO_APPROVED_EXACT_OCF"
            if successful_official_query
            else "OFFICIAL_QUERY_INCOMPLETE"
        ),
        "source_status": "LIMITED",
        "amount": None,
        "fs_div": "",
        "account_names": [],
        "attempts": attempts,
    }

def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("V8130_DART_API_KEY_MISSING")

    for p in (
        BLOCK_CSV,
        BLOCK_JSON,
        V8129_JSON,
        FIN,
        PROD_OCF,
        PROD_OCF_META,
    ):
        if not p.is_file():
            raise RuntimeError("V8130_MISSING_INPUT:" + str(p))

    s8128 = read_json(BLOCK_JSON)
    s8129 = read_json(V8129_JSON)
    ocf_meta = read_json(PROD_OCF_META)

    if s8128.get("version") != V8128_VERSION:
        raise RuntimeError("V8130_V8128_VERSION_MISMATCH")
    if s8128.get("v8127_result_commit") != "7a8e5dbe9729aeda98c4be5c10d9b90255fbc81c":
        raise RuntimeError("V8130_V8128_LINEAGE_MISMATCH")
    if int(s8128.get("ready_count") or 0) != 19:
        raise RuntimeError("V8130_V8128_READY_CHANGED")
    if int(s8128.get("limited_blocker_occurrences") or 0) != 796:
        raise RuntimeError("V8130_V8128_BLOCKER_COUNT_CHANGED")

    if s8129.get("version") != V8129_VERSION:
        raise RuntimeError("V8130_V8129_VERSION_MISMATCH")
    if s8129.get("status") != "AUDIT_ONLY_CURRENT_ACTIONABLE_EXACT_DA":
        raise RuntimeError("V8130_V8129_STATUS_MISMATCH")
    if int(s8129.get("both_approved_exact_recoverable_count") or 0) != 0:
        raise RuntimeError("V8130_V8129_RECOVERABLE_NOT_ZERO")
    if int(s8129.get("newly_exhausted_no_approved_exact_count") or 0) != 5:
        raise RuntimeError("V8130_V8129_EXHAUSTED_COUNT_CHANGED")
    if s8129.get("next_step") != "AUDIT_CURRENT_ACTIONABLE_OCF_SINGLE_BLOCKERS_V8130":
        raise RuntimeError("V8130_V8129_NEXT_STEP_MISMATCH")

    if ocf_meta.get("version") != OCF_CONTRACT_VERSION:
        raise RuntimeError("V8130_OCF_CONTRACT_VERSION_MISMATCH")
    if ocf_meta.get("status") != "READY_SOURCE_ONLY":
        raise RuntimeError("V8130_OCF_SOURCE_STATUS_MISMATCH")
    if ocf_meta.get("account_id_policy") != "EXACT_ONLY:" + IFRS_OCF_ID:
        raise RuntimeError("V8130_OCF_ACCOUNT_POLICY_MISMATCH")

    block_rows = read_rows(BLOCK_CSV)
    actionable = {
        ticker(r.get("ticker")): r
        for r in block_rows
        if r.get("source_group") == "OCF_AND_REVENUE_SOURCE"
        and str(r.get("single_blocker_ticker") or "").upper() == "TRUE"
        and r.get("recovery_status") == "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
    }
    if set(actionable) != set(EXPECTED):
        raise RuntimeError(
            "V8130_ACTIONABLE_SET_MISMATCH:"
            + ",".join(sorted(actionable))
        )

    prod_ocf_rows = {
        ticker(r.get("ticker")): r
        for r in read_rows(PROD_OCF)
        if ticker(r.get("ticker"))
    }
    overlap = sorted(set(EXPECTED) & set(prod_ocf_rows))
    if overlap:
        raise RuntimeError(
            "V8130_TARGET_UNEXPECTEDLY_ALREADY_IN_OCF_CACHE:"
            + ",".join(overlap)
        )

    fin_rows = {
        ticker(r.get("ticker")): r
        for r in read_rows(FIN)
        if ticker(r.get("ticker"))
    }
    for code in EXPECTED:
        r = fin_rows.get(code)
        if not r:
            raise RuntimeError("V8130_FIN_TARGET_MISSING:" + code)
        if r.get("corp_identity_status") != "MATCH":
            raise RuntimeError("V8130_CORP_IDENTITY_NOT_MATCH:" + code)
        if corp(r.get("corp_code")) != EXPECTED_CORP[code]:
            raise RuntimeError("V8130_CORP_CODE_CHANGED:" + code)

    rows = []
    class_counts = Counter()
    recoverable = []
    no_exact = []
    incomplete = []
    conflict = []

    for code in sorted(EXPECTED):
        result = fetch_exact_ocf(api_key, EXPECTED_CORP[code])
        classification = result["classification"]
        class_counts[classification] += 1

        if classification == "RECOVERABLE_EXACT_OCF":
            recoverable.append(code)
        elif classification == "NO_APPROVED_EXACT_OCF":
            no_exact.append(code)
        elif classification == "OFFICIAL_QUERY_INCOMPLETE":
            incomplete.append(code)
        elif classification == "EXACT_OCF_VALUE_CONFLICT":
            conflict.append(code)

        rows.append({
            "ticker": code,
            "name": EXPECTED[code],
            "corp_code": EXPECTED_CORP[code],
            "annual_source_year": ANNUAL_YEAR,
            "report_code": REPORT_CODE,
            "account_id": IFRS_OCF_ID,
            "classification": classification,
            "source_status": result["source_status"],
            "source_fs_div": result["fs_div"],
            "operating_cash_flow_annual": (
                "" if result["amount"] is None else result["amount"]
            ),
            "account_names_json": json.dumps(
                result["account_names"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "official_attempts_json": json.dumps(
                result["attempts"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        })

    if len(rows) != 4:
        raise RuntimeError("V8130_OUTPUT_COUNT_NOT_4")
    if incomplete:
        raise RuntimeError(
            "V8130_OFFICIAL_QUERY_INCOMPLETE:"
            + ",".join(sorted(incomplete))
        )
    if conflict:
        raise RuntimeError(
            "V8130_EXACT_OCF_CONFLICT:"
            + ",".join(sorted(conflict))
        )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=fields,
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(rows)

    next_step = (
        "FREEZE_RECOVERABLE_OCF_AND_SHADOW_SCORE_V8131"
        if recoverable
        else "AUDIT_CURRENT_ACTIONABLE_SUPPLY_SINGLE_BLOCKERS_V8131"
    )

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY_CURRENT_ACTIONABLE_OCF",
        "policy_version": POLICY_VERSION,
        "v8128_version": V8128_VERSION,
        "v8128_result_commit": V8128_RESULT_COMMIT,
        "v8129_version": V8129_VERSION,
        "v8129_result_commit": V8129_RESULT_COMMIT,
        "ocf_contract_version": OCF_CONTRACT_VERSION,
        "approved_exact_account_id": IFRS_OCF_ID,
        "target_count": 4,
        "target_tickers": sorted(EXPECTED),
        "target_names": [EXPECTED[c] for c in sorted(EXPECTED)],
        "targets_absent_from_existing_ocf_cache": sorted(EXPECTED),
        "annual_source_year": int(ANNUAL_YEAR),
        "report_code": REPORT_CODE,
        "classification_counts": dict(class_counts),
        "recoverable_count": len(recoverable),
        "recoverable_tickers": sorted(recoverable),
        "no_approved_exact_count": len(no_exact),
        "no_approved_exact_tickers": sorted(no_exact),
        "official_query_incomplete_count": 0,
        "official_query_incomplete_tickers": [],
        "conflict_count": 0,
        "conflict_tickers": [],
        "retry_policy": {
            "transport_attempts_per_fs_div": MAX_TRANSPORT_RETRIES,
            "fs_div_order": ["CFS", "OFS"],
            "fail_closed_on_incomplete": True,
        },
        "hard_guards": {
            "production_ocf_cache_modified": False,
            "production_ocf_metadata_modified": False,
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_price_elasticity_cache_modified": False,
            "production_api_modified": False,
            "production_investment_score_written": False,
            "scoring_policy_modified": False,
            "source_value_imputed": False,
            "alternate_ocf_account_id_approved": False,
            "target_force_inserted": False,
            "source_promoted": False,
        },
        "next_step": next_step,
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY_CURRENT_ACTIONABLE_OCF",
            "TARGET_COUNT=4",
            f"RECOVERABLE={len(recoverable)}",
            f"NO_APPROVED_EXACT={len(no_exact)}",
            "OFFICIAL_QUERY_INCOMPLETE=0",
            "CONFLICT=0",
            "TRANSPORT_RETRIES_PER_FS_DIV=3",
            "TARGETS_ALREADY_IN_OCF_CACHE=0",
            "PRODUCTION_OCF_CACHE_MODIFIED=false",
            "SOURCE_PROMOTED=false",
            "SCORING_POLICY_MODIFIED=false",
            "STATUS_OK=true",
            f"NEXT_STEP={next_step}",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.13.0 current actionable OCF single-blocker audit",
            "",
            "- Robust retry edition; source contract is unchanged.",
            "- Targets: 하이트진로, TCC스틸, 국도화학, 한미반도체.",
            f"- Accepted account ID only: `{IFRS_OCF_ID}`.",
            "- 2025 annual OpenDART statement; CFS then OFS.",
            "- Up to 3 transport attempts per fs_div.",
            "- Missing value is never imputed as zero.",
            "- Alternate/similar OCF account IDs are not approved.",
            "- Incomplete or conflicting official evidence fails closed.",
            "- AUDIT_ONLY: production sources are not changed.",
            "",
            f"- Recoverable: {len(recoverable)}",
            f"- No approved exact: {len(no_exact)}",
            f"- Next: `{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8130_CURRENT_ACTIONABLE_OCF_AUDIT=PASS")

if __name__ == "__main__":
    main()
