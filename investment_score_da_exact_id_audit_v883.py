#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-13-v8.8.3-da-exact-id-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
KST = ZoneInfo("Asia/Seoul")
ROOT = Path(".")

RAW = ROOT / "latest/investment_score_source_cache_latest.csv"
OUT_CSV = ROOT / "latest/investment_score_da_exact_id_audit_v883.csv"
OUT_JSON = ROOT / "latest/investment_score_da_exact_id_audit_v883_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_da_exact_id_audit_v883_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_da_exact_id_audit_v883.md"

APPROVED_DA_IDS = {
    "ifrs-full_AdjustmentsForDepreciationExpense",
    "ifrs-full_AdjustmentsForAmortisationExpense",
}
FINANCIAL_BENCHMARKS = {"1021", "1024", "1025"}

def ticker(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_csv_map(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return {
        ticker(r.get("ticker")): r
        for r in rows
        if ticker(r.get("ticker"))
    }

def parse_json_list(text):
    try:
        data = json.loads(str(text or ""))
    except Exception:
        return []
    return data if isinstance(data, list) else []

def production_rows():
    out = {}
    for table in ("kospi", "decliners", "decliners24"):
        payload = read_json(ROOT / f"api/two_table_v1/{table}.json")
        for row in payload.get("rows") or []:
            code = ticker(row.get("ticker"))
            if code:
                out[code] = row
    return out

def get_common_raw(code, raw_map, prod_row):
    direct = raw_map.get(code)
    if direct and direct.get("source_cache_status") == "READY_RAW_SOURCE":
        return direct, "DIRECT"

    metrics = prod_row.get("metrics") or {}
    bench = metrics.get("sector_benchmark") or {}
    mode = str(bench.get("selection_mode") or "")
    common = ticker(bench.get("common_ticker"))

    if mode.startswith("PREFERRED_INHERIT_") and common:
        inherited = raw_map.get(common)
        if inherited and inherited.get("source_cache_status") == "READY_RAW_SOURCE":
            return inherited, f"PREFERRED_COMMON:{common}"

    return direct or {}, "UNAVAILABLE"

def classify_id(account_id):
    if account_id in APPROVED_DA_IDS:
        return "APPROVED_V880"
    if account_id.startswith("ifrs-full_"):
        return "IFRS_STANDARD_UNAPPROVED"
    if account_id.startswith("dart_"):
        return "DART_STANDARD_UNAPPROVED"
    return "CUSTOM_OR_UNSTANDARDIZED"

def main():
    prod = production_rows()
    raw_map = read_csv_map(RAW)

    if len(prod) != 112:
        raise RuntimeError(f"PRODUCTION_TICKER_COUNT_UNEXPECTED:{len(prod)}")

    rows = []
    id_tickers = defaultdict(set)
    id_names = defaultdict(set)
    id_occurrences = Counter()

    status_counter = Counter()
    raw_mode_counter = Counter()
    nonfinancial_count = 0
    financial_neutral_count = 0

    for code in sorted(prod):
        prow = prod[code]
        metrics = prow.get("metrics") or {}
        bench = str(
            ((metrics.get("sector_benchmark") or {}).get("benchmark_ticker") or "")
        )
        is_financial = bench in FINANCIAL_BENCHMARKS

        raw, raw_mode = get_common_raw(code, raw_map, prow)
        raw_mode_counter[raw_mode] += 1

        candidates = parse_json_list(
            raw.get("depreciation_amortization_candidates_json")
        )
        normalized = []
        for item in candidates:
            aid = str(item.get("account_id") or "").strip()
            name = str(item.get("account_nm") or "").strip()
            amount = item.get("amount")
            normalized.append({
                "account_id": aid,
                "account_nm": name,
                "amount": amount,
            })
            if aid:
                id_tickers[aid].add(code)
                if name:
                    id_names[aid].add(name)
                id_occurrences[aid] += 1

        approved = [
            x for x in normalized
            if x["account_id"] in APPROVED_DA_IDS
        ]

        approved_value_sets = defaultdict(set)
        for x in approved:
            if x["amount"] not in (None, "", "null"):
                try:
                    approved_value_sets[x["account_id"]].add(float(x["amount"]))
                except Exception:
                    pass

        approved_conflict = any(
            len(vals) > 1
            for vals in approved_value_sets.values()
        )

        if is_financial:
            audit_status = "FINANCIAL_SECTOR_NEUTRAL"
            financial_neutral_count += 1
        else:
            nonfinancial_count += 1
            if raw_mode == "UNAVAILABLE":
                audit_status = "RAW_SOURCE_UNAVAILABLE"
            elif approved_conflict:
                audit_status = "APPROVED_EXACT_CONFLICT"
            elif approved:
                audit_status = "APPROVED_EXACT_READY"
            elif not normalized:
                audit_status = "NO_DA_CANDIDATE"
            else:
                audit_status = "UNAPPROVED_CANDIDATE_IDS_PRESENT"

        status_counter[audit_status] += 1

        rows.append({
            "ticker": code,
            "name": str(prow.get("name") or ""),
            "market": str(prow.get("market") or ""),
            "benchmark_ticker": bench,
            "financial_sector_neutral": "TRUE" if is_financial else "FALSE",
            "raw_source_mode": raw_mode,
            "audit_status": audit_status,
            "candidate_count": len(normalized),
            "approved_exact_count": len(approved),
            "approved_exact_ids": "|".join(sorted({
                x["account_id"] for x in approved if x["account_id"]
            })),
            "candidate_account_ids": "|".join(sorted({
                x["account_id"] for x in normalized if x["account_id"]
            })),
            "candidate_account_names": "|".join(sorted({
                x["account_nm"] for x in normalized if x["account_nm"]
            })),
        })

    id_frequency = []
    for aid in sorted(
        id_tickers,
        key=lambda x: (-len(id_tickers[x]), x),
    ):
        id_frequency.append({
            "account_id": aid,
            "classification": classify_id(aid),
            "production_ticker_count": len(id_tickers[aid]),
            "raw_occurrence_count": id_occurrences[aid],
            "account_names": sorted(id_names[aid]),
            "sample_tickers": sorted(id_tickers[aid])[:20],
        })

    approved_ready = status_counter["APPROVED_EXACT_READY"]
    unapproved_present = status_counter["UNAPPROVED_CANDIDATE_IDS_PRESENT"]
    no_candidate = status_counter["NO_DA_CANDIDATE"]
    raw_unavailable = status_counter["RAW_SOURCE_UNAVAILABLE"]
    approved_conflict = status_counter["APPROVED_EXACT_CONFLICT"]

    summary = {
        "version": VERSION,
        "policy_version": POLICY_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY",
        "production_unique_tickers": len(prod),
        "financial_sector_neutral_count": financial_neutral_count,
        "nonfinancial_applicable_count": nonfinancial_count,
        "status_counts": dict(status_counter),
        "raw_source_mode_counts": dict(raw_mode_counter),
        "approved_da_ids": sorted(APPROVED_DA_IDS),
        "approved_exact_ready_count": approved_ready,
        "unapproved_candidate_ids_present_count": unapproved_present,
        "no_da_candidate_count": no_candidate,
        "raw_source_unavailable_count": raw_unavailable,
        "approved_exact_conflict_count": approved_conflict,
        "candidate_id_frequency": id_frequency,
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "policy_changed": False,
            "new_da_id_approved": False,
            "legacy_score_rescaled": False,
        },
        "next_step": "REVIEW_DA_ID_EVIDENCE_BEFORE_ANY_POLICY_CHANGE",
    }

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    top_ids = id_frequency[:20]
    doc = [
        "# V8.8.3 EV/EBITDA D&A exact account ID 감사",
        "",
        f"- 버전: `{VERSION}`",
        f"- 기준 점수계약: `{POLICY_VERSION}`",
        "- 상태: AUDIT_ONLY",
        "- 목적: 현재 raw candidate에서 실제 D&A account_id 분포를 확인한다.",
        "- 이 단계에서는 새 account_id를 승인하지 않는다.",
        "- production API 및 investment_score_100을 변경하지 않는다.",
        "",
        "## 현재 계약상 승인된 D&A ID",
        "",
    ]
    for aid in sorted(APPROVED_DA_IDS):
        doc.append(f"- `{aid}`")

    doc += [
        "",
        "## 적용 현황",
        "",
        f"- production 종목: {len(prod)}",
        f"- 금융업 중립처리: {financial_neutral_count}",
        f"- 비금융 적용대상: {nonfinancial_count}",
        f"- 승인 exact ID READY: {approved_ready}",
        f"- 미승인 candidate ID 존재: {unapproved_present}",
        f"- D&A candidate 없음: {no_candidate}",
        f"- raw source unavailable: {raw_unavailable}",
        f"- 승인 exact ID 값 충돌: {approved_conflict}",
        "",
        "## 후보 account_id 상위 빈도",
        "",
        "| account_id | 분류 | 종목수 | raw건수 | 대표 account_nm |",
        "|---|---|---:|---:|---|",
    ]
    for item in top_ids:
        names = ", ".join(item["account_names"][:3])
        doc.append(
            f"| `{item['account_id'] or '(blank)'}` | "
            f"{item['classification']} | "
            f"{item['production_ticker_count']} | "
            f"{item['raw_occurrence_count']} | {names} |"
        )

    doc += [
        "",
        "## 판정 규칙",
        "",
        "- APPROVED_V880: 기존 V8.8.0 계약에 이미 포함된 exact IFRS ID.",
        "- IFRS_STANDARD_UNAPPROVED: ifrs-full_ 형식이지만 아직 점수계약에는 미승인.",
        "- DART_STANDARD_UNAPPROVED: dart_ 형식이지만 아직 점수계약에는 미승인.",
        "- CUSTOM_OR_UNSTANDARDIZED: 회사별 확장 또는 비표준 ID 가능성이 있어 자동 승인 금지.",
        "",
        "## 다음 단계",
        "",
        "반복 빈도와 account_nm을 검토해 공식 표준 ID인지 검증한 뒤, "
        "명시적 계약 변경이 필요한 경우에만 별도 단계에서 승인한다.",
    ]
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text("\n".join(doc) + "\n", encoding="utf-8")

    log_lines = [
        f"VERSION={VERSION}",
        f"POLICY_VERSION={POLICY_VERSION}",
        f"PRODUCTION_UNIQUE_TICKERS={len(prod)}",
        f"FINANCIAL_SECTOR_NEUTRAL={financial_neutral_count}",
        f"NONFINANCIAL_APPLICABLE={nonfinancial_count}",
        f"APPROVED_EXACT_READY={approved_ready}",
        f"UNAPPROVED_CANDIDATE_IDS_PRESENT={unapproved_present}",
        f"NO_DA_CANDIDATE={no_candidate}",
        f"RAW_SOURCE_UNAVAILABLE={raw_unavailable}",
        f"APPROVED_EXACT_CONFLICT={approved_conflict}",
        "POLICY_CHANGED=false",
        "NEW_DA_ID_APPROVED=false",
        "PRODUCTION_DATA_CHANGED=false",
        "PRODUCTION_INVESTMENT_SCORE_WRITTEN=false",
        "STATUS=OK",
        "NEXT_STEP=REVIEW_DA_ID_EVIDENCE_BEFORE_ANY_POLICY_CHANGE",
    ]
    OUT_LOG.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print("V883_DA_EXACT_ID_AUDIT=PASS")
    for line in log_lines:
        print(line)
    for item in id_frequency[:15]:
        print(
            "DA_ID="
            + item["account_id"]
            + "|CLASS="
            + item["classification"]
            + "|TICKERS="
            + str(item["production_ticker_count"])
            + "|RAW="
            + str(item["raw_occurrence_count"])
        )

if __name__ == "__main__":
    main()

