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

VERSION = "2026-09-21-v8.13.0b-independent-ocf-recovery-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8129_VERSION = "2026-09-21-v8.12.9-current-actionable-exact-da-single-blocker-audit"
V8129_RESULT_COMMIT = "658b08079bc45110271a85d799722950b024e8ed"
OCF_CONTRACT_VERSION = "2026-09-12-v8.7.4-audited-operating-cash-flow-source"

IFRS_OCF_ID = "ifrs-full_CashFlowsFromUsedInOperatingActivities"
DART_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8128.csv"
V8129_JSON = ROOT / "latest/investment_score_exact_da_actionable_v8129_summary_latest.json"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"
PROD_OCF = ROOT / "latest/investment_score_ocf_source_latest.csv"
PROD_OCF_META = ROOT / "latest/investment_score_ocf_source_latest.json"

OUT_CSV = ROOT / "latest/investment_score_ocf_recovery_v8130b.csv"
OUT_JSON = ROOT / "latest/investment_score_ocf_recovery_v8130b_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_ocf_recovery_v8130b_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_ocf_recovery_v8130b.md"

EXPECTED = {
    "000080": ("하이트진로", "00150244"),
    "002710": ("TCC스틸", "00117300"),
    "007690": ("국도화학", "00104388"),
    "042700": ("한미반도체", "00161383"),
}

def ticker(value):
    s = re.sub(r"[^0-9]", "", str(value or "").strip())
    return s.zfill(6) if s else ""

def norm(value):
    return str(value or "").strip()

def num(value):
    text = norm(value).replace(",", "")
    if text in {"", "-", "None", "null", "nan", "NaN"}:
        return None
    neg = text.startswith("(") and text.endswith(")")
    if neg:
        text = text[1:-1]
    text = re.sub(r"[^0-9eE+\-.]", "", text)
    if text in {"", "-", "+", ".", "-.", "+."}:
        return None
    try:
        x = float(text)
    except ValueError:
        return None
    return -abs(x) if neg else x

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def request(api_key, corp_code, fs_div):
    params = urllib.parse.urlencode({
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": "2025",
        "reprt_code": "11011",
        "fs_div": fs_div,
    })
    req = urllib.request.Request(
        f"{DART_URL}?{params}",
        headers={
            "User-Agent": "krx-watchlist-v8130b-ocf-recovery",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
    )

    errors = []
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(
                    response.read(12_000_000).decode("utf-8")
                )
            return payload, errors
        except Exception as exc:
            errors.append(
                f"{attempt}:{type(exc).__name__}:{exc}"
            )
            if attempt < 3:
                time.sleep(attempt)
    return None, errors

def audit_one(api_key, code, corp_code):
    attempts = []

    for fs_div in ("CFS", "OFS"):
        payload, transport_errors = request(api_key, corp_code, fs_div)

        if payload is None:
            attempts.append({
                "fs_div": fs_div,
                "transport_status": "ERROR",
                "transport_errors": transport_errors,
                "dart_status": "",
                "dart_message": "",
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
            "transport_errors": transport_errors,
            "dart_status": status,
            "dart_message": message,
            "exact_match_count": len(matches),
            "unique_numeric_values": values,
            "account_names": names,
        })

        if status != "000":
            continue

        if len(values) == 1:
            return {
                "ticker": code,
                "classification": "RECOVERABLE_EXACT_OCF",
                "source_status": "READY",
                "source_fs_div": fs_div,
                "amount": values[0],
                "account_names": names,
                "attempts": attempts,
            }

        if len(values) > 1:
            return {
                "ticker": code,
                "classification": "EXACT_OCF_VALUE_CONFLICT",
                "source_status": "LIMITED",
                "source_fs_div": fs_div,
                "amount": None,
                "account_names": names,
                "attempts": attempts,
            }

    official_success = any(
        a["transport_status"] == "OK"
        and a["dart_status"] == "000"
        for a in attempts
    )
    return {
        "ticker": code,
        "classification": (
            "NO_APPROVED_EXACT_OCF"
            if official_success
            else "OFFICIAL_QUERY_INCOMPLETE"
        ),
        "source_status": "LIMITED",
        "source_fs_div": "",
        "amount": None,
        "account_names": [],
        "attempts": attempts,
    }

def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("V8130B_DART_API_KEY_MISSING")

    s8129 = read_json(V8129_JSON)
    if s8129.get("version") != V8129_VERSION:
        raise RuntimeError("V8130B_V8129_VERSION_MISMATCH")
    if s8129.get("next_step") != "AUDIT_CURRENT_ACTIONABLE_OCF_SINGLE_BLOCKERS_V8130":
        raise RuntimeError("V8130B_V8129_NEXT_STEP_MISMATCH")

    ocf_meta = read_json(PROD_OCF_META)
    if ocf_meta.get("version") != OCF_CONTRACT_VERSION:
        raise RuntimeError("V8130B_OCF_CONTRACT_VERSION_MISMATCH")
    if ocf_meta.get("account_id_policy") != "EXACT_ONLY:" + IFRS_OCF_ID:
        raise RuntimeError("V8130B_OCF_ACCOUNT_POLICY_MISMATCH")

    blockers = read_rows(BLOCK_CSV)
    actionable = {
        ticker(r.get("ticker"))
        for r in blockers
        if r.get("source_group") == "OCF_AND_REVENUE_SOURCE"
        and str(r.get("single_blocker_ticker") or "").upper() == "TRUE"
        and r.get("recovery_status") == "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
    }
    if actionable != set(EXPECTED):
        raise RuntimeError(
            "V8130B_ACTIONABLE_SET_MISMATCH:"
            + ",".join(sorted(actionable))
        )

    existing_ocf = {
        ticker(r.get("ticker"))
        for r in read_rows(PROD_OCF)
        if ticker(r.get("ticker"))
    }
    overlap = sorted(existing_ocf & set(EXPECTED))
    if overlap:
        raise RuntimeError(
            "V8130B_TARGET_ALREADY_IN_OCF_CACHE:"
            + ",".join(overlap)
        )

    results = []
    counts = Counter()
    recoverable = []
    no_exact = []
    incomplete = []
    conflict = []

    for code in sorted(EXPECTED):
        name, corp_code = EXPECTED[code]
        result = audit_one(api_key, code, corp_code)
        counts[result["classification"]] += 1

        if result["classification"] == "RECOVERABLE_EXACT_OCF":
            recoverable.append(code)
        elif result["classification"] == "NO_APPROVED_EXACT_OCF":
            no_exact.append(code)
        elif result["classification"] == "OFFICIAL_QUERY_INCOMPLETE":
            incomplete.append(code)
        elif result["classification"] == "EXACT_OCF_VALUE_CONFLICT":
            conflict.append(code)

        results.append({
            "ticker": code,
            "name": name,
            "corp_code": corp_code,
            "annual_source_year": "2025",
            "report_code": "11011",
            "account_id": IFRS_OCF_ID,
            "classification": result["classification"],
            "source_status": result["source_status"],
            "source_fs_div": result["source_fs_div"],
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

    if incomplete:
        raise RuntimeError(
            "V8130B_OFFICIAL_QUERY_INCOMPLETE:"
            + ",".join(sorted(incomplete))
        )
    if conflict:
        raise RuntimeError(
            "V8130B_EXACT_OCF_CONFLICT:"
            + ",".join(sorted(conflict))
        )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=list(results[0].keys()),
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(results)

    next_step = (
        "FREEZE_RECOVERABLE_OCF_AND_SHADOW_SCORE_V8131"
        if recoverable
        else "AUDIT_CURRENT_ACTIONABLE_SUPPLY_SINGLE_BLOCKERS_V8131"
    )

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY_INDEPENDENT_RECOVERY",
        "policy_version": POLICY_VERSION,
        "v8129_result_commit": V8129_RESULT_COMMIT,
        "ocf_contract_version": OCF_CONTRACT_VERSION,
        "target_count": 4,
        "target_tickers": sorted(EXPECTED),
        "classification_counts": dict(counts),
        "recoverable_count": len(recoverable),
        "recoverable_tickers": sorted(recoverable),
        "no_approved_exact_count": len(no_exact),
        "no_approved_exact_tickers": sorted(no_exact),
        "official_query_incomplete_count": 0,
        "conflict_count": 0,
        "production_modified": False,
        "next_step": next_step,
    }
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY_INDEPENDENT_RECOVERY",
            "TARGET_COUNT=4",
            f"RECOVERABLE={len(recoverable)}",
            f"NO_APPROVED_EXACT={len(no_exact)}",
            "OFFICIAL_QUERY_INCOMPLETE=0",
            "CONFLICT=0",
            "PRODUCTION_MODIFIED=false",
            "STATUS_OK=true",
            f"NEXT_STEP={next_step}",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.13.0B independent OCF recovery audit",
            "",
            "- Independent concurrency lane; does not wait for the earlier V8.13.0 run.",
            "- Audit-only; production OCF cache is not changed.",
            f"- Accepted account ID only: `{IFRS_OCF_ID}`.",
            "- 2025 annual OpenDART data; CFS then OFS.",
            "- Up to three transport attempts per fs_div.",
            "- Missing values are not imputed.",
            "",
            f"- Recoverable: {len(recoverable)}",
            f"- No approved exact: {len(no_exact)}",
            f"- Next: `{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8130B_INDEPENDENT_OCF_RECOVERY=PASS")

if __name__ == "__main__":
    main()
