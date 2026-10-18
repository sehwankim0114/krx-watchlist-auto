"""Audit exact official OCF recovery for the current two-table universe.

Writes candidate source files only. Does not replace the production OCF cache or
publish an investment score.
"""
from __future__ import annotations

import csv
import json
import math
import os
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer


ROOT = Path(__file__).resolve().parent
VERSION = "2026-10-18-current-universe-exact-ocf-candidate-audit"
IFRS_OCF_ID = "ifrs-full_CashFlowsFromUsedInOperatingActivities"
DART_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
OCF_SOURCE = ROOT / "latest/investment_score_ocf_source_latest.csv"
FIN_SOURCE = ROOT / "latest/financial_valuation_cache_latest.csv"
RAW_SOURCE = ROOT / "latest/investment_score_source_cache_latest.csv"
CANDIDATE_CSV = ROOT / "latest/investment_score_current_ocf_candidate_latest.csv"
SUMMARY_JSON = ROOT / "latest/investment_score_current_ocf_candidate_latest.json"
SOURCE_FIELDS = [
    "ticker", "name", "source_mode", "source_ticker", "source_corp_code",
    "source_fs_div", "account_id", "account_nm", "operating_cash_flow_annual",
    "source_status", "inheritance_evidence", "note",
]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def current_universe():
    result = {}
    for table in ("kospi", "decliners", "decliners24"):
        payload = read_json(ROOT / f"api/two_table_v1/{table}.json")
        for row in payload["rows"]:
            code = scorer.ticker(row.get("ticker"))
            if code:
                result[code] = str(row.get("name") or "")
    return result


def exact_dart_ocf(api_key: str, corp_code: str, fs_div: str):
    errors = []
    for fs_div in (fs_div,):
        query = urllib.parse.urlencode({
            "crtfc_key": api_key, "corp_code": corp_code, "bsns_year": "2025",
            "reprt_code": "11011", "fs_div": fs_div,
        })
        request = urllib.request.Request(
            DART_URL + "?" + query,
            headers={"User-Agent": "krx-current-ocf-candidate-audit",
                     "Accept": "application/json"},
        )
        payload = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(request, timeout=35) as response:
                    payload = json.loads(response.read(12_000_000).decode("utf-8"))
                break
            except Exception as exc:
                errors.append(f"{fs_div}:{attempt}:{type(exc).__name__}")
                if attempt < 3:
                    time.sleep(attempt)
        if payload is None:
            continue
        status = str(payload.get("status") or "")
        if status == "020":
            return None, "DART_RATE_LIMIT", errors
        if status != "000":
            errors.append(f"{fs_div}:DART_STATUS_{status}")
            continue
        items = payload.get("list")
        if not isinstance(items, list):
            items = []
        matches = [
            item for item in items
            if str(item.get("sj_div") or "") == "CF"
            and str(item.get("account_id") or "") == IFRS_OCF_ID
        ]
        values = {
            scorer.num(item.get("thstrm_amount")) for item in matches
        }
        values.discard(None)
        if len(values) == 1:
            account_names = sorted({
                str(item.get("account_nm") or "") for item in matches
                if item.get("account_nm")
            })
            return {
                "amount": next(iter(values)),
                "fs_div": fs_div,
                "account_name": account_names[0] if account_names else "",
            }, "READY", errors
        if len(values) > 1:
            return None, "CONFLICTING_EXACT_OCF_VALUES", errors
        errors.append(f"{fs_div}:NO_EXACT_OCF")
    return None, "NO_UNIQUE_EXACT_OCF", errors


def score_with_ocf(path: Path, tmp: Path, label: str):
    scorer.OCF = path
    scorer.OUT_CSV = tmp / f"{label}_scores.csv"
    scorer.OUT_JSON = tmp / f"{label}_summary.json"
    scorer.OUT_LOG = tmp / f"{label}_run_log.txt"
    scorer.OUT_DOC = tmp / f"{label}_explanation.md"
    scorer.main()
    rows = {
        row["ticker"]: row for row in read_csv(scorer.OUT_CSV)
    }
    return rows, read_json(scorer.OUT_JSON)


def ocf_missing(summary):
    return sum(
        count for reason, count in summary["top_missing_reasons"]
        if reason.startswith("영업현금흐름:")
    )


def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DART_API_KEY_MISSING")
    status = read_json(ROOT / "api/status.json")
    manifest = read_json(ROOT / "api/two_table_v1/manifest.json")
    if not status.get("api_sync_ok") or status.get("critical_errors"):
        raise RuntimeError("API_NOT_SYNCED")
    if manifest["source_build_id"] != status["build_id"]:
        raise RuntimeError("BUILD_ID_MISMATCH")

    universe = current_universe()
    existing_rows = read_csv(OCF_SOURCE)
    existing = {
        scorer.ticker(row.get("ticker")): row for row in existing_rows
        if scorer.ticker(row.get("ticker"))
    }
    financial = scorer.read_csv_map(FIN_SOURCE)
    raw = scorer.read_csv_map(RAW_SOURCE)

    recovered = []
    limited = []
    for code, name in sorted(universe.items()):
        old = existing.get(code) or {}
        if (
            old.get("source_status") == "READY"
            and old.get("account_id") == IFRS_OCF_ID
            and scorer.num(old.get("operating_cash_flow_annual")) is not None
        ):
            continue
        fin = financial.get(code) or {}
        source = raw.get(code) or {}
        reason = ""
        if source.get("source_cache_status") != "READY_RAW_SOURCE":
            reason = "ANNUAL_SOURCE_NOT_READY"
        elif source.get("annual_fs_div") not in {"CFS", "OFS"}:
            reason = "ANNUAL_FS_DIV_NOT_VERIFIED"
        elif source.get("annual_source_year") != "2025" or (
            scorer.num(source.get("annual_revenue_y0")) or 0
        ) <= 0:
            reason = "NO_MATCHING_2025_ANNUAL_REVENUE"
        elif fin.get("financial_data_status") != "READY":
            reason = "FINANCIAL_SOURCE_NOT_READY"
        elif fin.get("corp_identity_status") not in {"MATCH", "MATCH_NORMALIZED"}:
            reason = "CORP_IDENTITY_NOT_VERIFIED"
        elif str(fin.get("name") or "") != name:
            reason = "CORP_NAME_NOT_MATCHED_TO_TABLE"
        elif not str(fin.get("corp_code") or "").isdigit() or len(fin["corp_code"]) != 8:
            reason = "CORP_CODE_NOT_EIGHT_DIGITS"
        if reason:
            limited.append({"ticker": code, "name": name, "reason": reason})
            continue

        result, reason, errors = exact_dart_ocf(
            api_key, fin["corp_code"], source["annual_fs_div"]
        )
        if result is None:
            limited.append({"ticker": code, "name": name, "reason": reason,
                            "query_errors": errors})
            continue
        amount = result["amount"]
        if not isinstance(amount, (int, float)) or not math.isfinite(amount):
            raise RuntimeError("NONFINITE_EXACT_OCF:" + code)
        recovered.append({
            "ticker": code,
            "name": name,
            "source_mode": "CURRENT_DART_EXACT_2025_ANNUAL",
            "source_ticker": code,
            "source_corp_code": fin["corp_code"],
            "source_fs_div": result["fs_div"],
            "account_id": IFRS_OCF_ID,
            "account_nm": result["account_name"],
            "operating_cash_flow_annual": amount,
            "source_status": "READY",
            "inheritance_evidence": "",
            "note": "2025 annual business report 11011; exact IFRS CF account",
            "source_report_year": "2025",
            "source_report_code": "11011",
        })
        time.sleep(0.1)

    if set(row["ticker"] for row in recovered) & {
        code for code, row in existing.items() if row.get("source_status") == "READY"
    }:
        raise RuntimeError("CANDIDATE_OVERWRITES_READY_OCF")

    write_csv(
        CANDIDATE_CSV, recovered, SOURCE_FIELDS + [
            "source_report_year", "source_report_code"
        ],
    )
    combined = dict(existing)
    for row in recovered:
        combined[row["ticker"]] = {
            field: row.get(field, "") for field in SOURCE_FIELDS
        }

    old_paths = {
        key: getattr(scorer, key)
        for key in ("OCF", "OUT_CSV", "OUT_JSON", "OUT_LOG", "OUT_DOC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="current_ocf_candidate_") as name:
            tmp = Path(name)
            combined_path = tmp / "combined_ocf.csv"
            write_csv(combined_path, [
                {field: row.get(field, "") for field in SOURCE_FIELDS}
                for _, row in sorted(combined.items())
            ], SOURCE_FIELDS)
            baseline_rows, baseline = score_with_ocf(OCF_SOURCE, tmp, "baseline")
            candidate_rows, candidate = score_with_ocf(
                combined_path, tmp, "candidate"
            )
    finally:
        for key, value in old_paths.items():
            setattr(scorer, key, value)

    if set(baseline_rows) != set(candidate_rows) or set(baseline_rows) != set(universe):
        raise RuntimeError("SCORE_UNIVERSE_DRIFT")
    changed_ready = [
        code for code in baseline_rows
        if baseline_rows[code]["score_status"] == "READY"
        and (
            candidate_rows[code]["score_status"] != "READY"
            or candidate_rows[code]["score_total"] != baseline_rows[code]["score_total"]
            or candidate_rows[code]["score_band"] != baseline_rows[code]["score_band"]
        )
    ]
    if changed_ready:
        raise RuntimeError("PREVIOUS_READY_SCORE_CHANGED:" + ",".join(changed_ready))
    if candidate["ready_count"] < baseline["ready_count"]:
        raise RuntimeError("READY_COUNT_REGRESSED")
    base_ocf_missing = ocf_missing(baseline)
    cand_ocf_missing = ocf_missing(candidate)
    if cand_ocf_missing > base_ocf_missing:
        raise RuntimeError("OCF_BLOCKERS_INCREASED")

    payload = {
        "version": VERSION,
        "generated_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(
            timespec="seconds"
        ),
        "status": "AUDIT_CANDIDATE_ONLY_NOT_PRODUCTION",
        "source_build_id": status["build_id"],
        "source_basis_date": manifest["basis_date"],
        "production_unique_tickers": len(universe),
        "prior_source_rows": len(existing_rows),
        "new_exact_ocf_candidate_count": len(recovered),
        "new_exact_ocf_candidate_tickers": [row["ticker"] for row in recovered],
        "unresolved_count": len(limited),
        "unresolved_reason_counts": dict(Counter(
            row["reason"] for row in limited
        )),
        "unresolved": limited,
        "baseline_ready_count": baseline["ready_count"],
        "candidate_ready_count": candidate["ready_count"],
        "baseline_ocf_missing_count": base_ocf_missing,
        "candidate_ocf_missing_count": cand_ocf_missing,
        "previous_ready_scores_unchanged": True,
        "production_ocf_cache_changed": False,
        "production_score_written": False,
    }
    SUMMARY_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("CURRENT_OCF_CANDIDATE_AUDIT=PASS")
    print("CURRENT_OCF_RECOVERED=" + str(len(recovered)))
    print("CURRENT_OCF_READY_BASE=" + str(baseline["ready_count"]))
    print("CURRENT_OCF_READY_CANDIDATE=" + str(candidate["ready_count"]))


if __name__ == "__main__":
    main()
