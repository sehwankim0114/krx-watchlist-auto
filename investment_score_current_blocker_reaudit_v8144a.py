#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-22-v8.14.4A-dynamic-exhaustion-aware-current-blocker-reaudit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8142_VERSION = "2026-09-22-v8.14.2-current-actionable-exact-da-single-blocker-audit"
V8143_VERSION = "2026-09-22-v8.14.3-esr-kendall-q2-score-cache-audit"
V8143_RESULT_COMMIT = "76b8ae6c544bf13678794def600e2111d2f2ddd1"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")
ESR_TICKER = "365550"
ESR_REASON = "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT"

DA_JSON = ROOT / "latest/investment_score_exact_da_actionable_v8142_summary_latest.json"
SCORE_JSON = ROOT / "latest/investment_score_score_cache_actionable_v8143_summary_latest.json"
V8104_JSON = ROOT / "latest/investment_score_next_single_source_v8104_summary_latest.json"
MANIFEST = ROOT / "api/two_table_v1/manifest.json"

TMP_CSV = Path("/tmp/v8144a_score.csv")
TMP_JSON = Path("/tmp/v8144a_score_summary.json")
TMP_LOG = Path("/tmp/v8144a_score.log")
TMP_DOC = Path("/tmp/v8144a_score.md")

OUT_CSV = ROOT / "latest/investment_score_current_blockers_v8144a.csv"
OUT_JSON = ROOT / "latest/investment_score_current_blockers_v8144a_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_current_blockers_v8144a_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_current_blockers_v8144a.md"

def ticker(v):
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s.zfill(6) if s else ""

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def split_reasons(v):
    return [x for x in str(v or "").split(";") if x]

def classify(reason):
    if reason == "수급·공시부담:SUPPLY_LIMITED_NO_POSITIVE_EVIDENCE":
        return "SOURCE_EVIDENCE_GAP", "PRODUCTION_ANALYSIS_SUPPLY"
    if reason == "최근 분기 실적 가속·둔화:ANNUAL_OP_DENOM_NONPOSITIVE":
        return "POLICY_SEMANTIC_BLOCKER", "V880_SCORING_CONTRACT"
    if reason.startswith(("PER:", "PBR:")):
        return "SOURCE_DATA_GAP", "FINANCIAL_VALUATION_CACHE"
    if reason.startswith("EV/EBITDA:"):
        tail = reason.split("EV/EBITDA:", 1)[1]
        parts = tail.split(":")
        debt = parts[-2] if len(parts) >= 2 else ""
        da = parts[-1] if parts else ""
        if da == "NO_EXACT_CANDIDATE":
            return "SOURCE_DATA_GAP", "EXACT_DA_SOURCE"
        if debt == "NO_EXACT_CANDIDATE":
            return "SOURCE_DATA_GAP", "EXACT_CORE_DEBT_SOURCE"
        if debt in {"OK", "EMPTY_AS_ZERO"} and da in {"OK", "EMPTY_AS_ZERO"}:
            return "SOURCE_DATA_GAP", "EV_EBITDA_OTHER_INPUT"
        return "SOURCE_DATA_GAP", "EV_EBITDA_INPUT"
    if reason.startswith("PSR 또는 대체 가치지표:"):
        return "SOURCE_DATA_GAP", "FINANCIAL_AND_RAW_SOURCE"
    if reason.startswith((
        "매출 성장과 안정성:",
        "최근 3년 매출 성장률:",
        "최근 3년 영업이익 성장률:",
        "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT",
    )):
        return "SOURCE_DATA_GAP", "INVESTMENT_SCORE_SOURCE_CACHE"
    if reason.startswith((
        "영업이익 성장과 흑자 여부:",
        "순이익 흐름:",
        "영업이익률:",
        "ROE:",
        "부채비율:",
        "흑자 지속성과 이익 안정성:",
    )):
        return "SOURCE_DATA_GAP", "FINANCIAL_VALUATION_CACHE"
    if reason.startswith("영업현금흐름:"):
        return "SOURCE_DATA_GAP", "OCF_AND_REVENUE_SOURCE"
    if reason.startswith((
        "1개월 가격흐름:",
        "3개월 가격흐름:",
        "기간 저가·고가 대비 현재위치:",
        "과열·급락 위험:",
        "20일 평균 거래대금과 거래량:",
    )):
        return "SOURCE_DATA_GAP", "PRODUCTION_PRICE_METRICS"
    if reason.startswith("하루평균 절대등락률:"):
        return "SOURCE_DATA_GAP", "PRICE_ELASTICITY_20D"
    if reason.startswith("순현금·기업가치 상태:"):
        return "SOURCE_DATA_GAP", "NETCASH_INPUT"
    return "UNCLASSIFIED_REVIEW", "UNKNOWN"

def recovery(code, reason, group, single, da_exhausted, v8104_exhausted):
    if group == "V880_SCORING_CONTRACT":
        return "POLICY_SEMANTIC_DEFER"
    if group == "EXACT_DA_SOURCE" and code in da_exhausted:
        return "EXHAUSTED_APPROVED_OFFICIAL_DA_PATHS"
    if (
        code == ESR_TICKER
        and group == "INVESTMENT_SCORE_SOURCE_CACHE"
        and reason == ESR_REASON
    ):
        return "EXHAUSTED_OFFICIAL_Q2_ACCEL_PATH"
    if code == "001020" and code in v8104_exhausted and group == "PRODUCTION_PRICE_METRICS":
        return "EXHAUSTED_V8104_OFFICIAL_KRX_OHLC_INCOMPLETE"
    if code == "357250" and code in v8104_exhausted and group == "INVESTMENT_SCORE_SOURCE_CACHE":
        return "EXHAUSTED_V8104_OFFICIAL_FULL_ACCOUNT_INCOMPLETE"
    if single:
        return "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
    return "MULTI_BLOCKER_SOURCE_LANE"

def run_scorer():
    old = {
        "VERSION": scorer.VERSION,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = VERSION
        scorer.OUT_CSV = TMP_CSV
        scorer.OUT_JSON = TMP_JSON
        scorer.OUT_LOG = TMP_LOG
        scorer.OUT_DOC = TMP_DOC
        rc = scorer.main()
    finally:
        for k, v in old.items():
            setattr(scorer, k, v)
    if rc not in (None, 0):
        raise RuntimeError("V8144A_SCORER_FAILED:" + str(rc))

def main():
    for p in (DA_JSON, SCORE_JSON, V8104_JSON, MANIFEST):
        if not p.is_file():
            raise RuntimeError("V8144A_MISSING_INPUT:" + str(p))

    s8142 = read_json(DA_JSON)
    s8143 = read_json(SCORE_JSON)
    s8104 = read_json(V8104_JSON)
    manifest = read_json(MANIFEST)

    if s8142.get("version") != V8142_VERSION:
        raise RuntimeError("V8144A_V8142_VERSION_MISMATCH")
    if s8143.get("version") != V8143_VERSION:
        raise RuntimeError("V8144A_V8143_VERSION_MISMATCH")
    if s8143.get("classification") != "NO_COMPLETE_OFFICIAL_Q2_ACCEL_INPUT_PATH":
        raise RuntimeError("V8144A_ESR_Q2_NOT_EXHAUSTED")
    if s8143.get("next_step") != "MARK_SCORE_CACHE_Q2_PATH_EXHAUSTED_AND_REAUDIT_V8144":
        raise RuntimeError("V8144A_PREDECESSOR_NEXT_STEP_MISMATCH")

    da_exhausted = set(
        s8142.get("post_audit_exhausted_union_tickers") or []
    )
    if len(da_exhausted) != 64:
        raise RuntimeError("V8144A_DA_EXHAUSTED_NOT_64")

    if s8104.get("version") != "2026-09-15-v8.10.4-next-single-source-recoverability-audit":
        raise RuntimeError("V8144A_V8104_VERSION_MISMATCH")
    v8104_exhausted = set(
        s8104.get("not_recoverable_now_tickers") or []
    )
    if v8104_exhausted != {"001020", "357250"}:
        raise RuntimeError("V8144A_V8104_EXHAUSTED_SET_CHANGED")

    if manifest.get("release_stage") != "PRODUCTION":
        raise RuntimeError("V8144A_MANIFEST_NOT_PRODUCTION")
    if manifest.get("safe_to_analyze_as_latest") is not True:
        raise RuntimeError("V8144A_MANIFEST_NOT_SAFE_LATEST")

    run_scorer()
    rows = read_csv(TMP_CSV)
    score_summary = read_json(TMP_JSON)

    if not rows:
        raise RuntimeError("V8144A_SCORER_EMPTY")

    ready = [r for r in rows if r.get("score_status") == "READY"]
    limited = [r for r in rows if r.get("score_status") == "LIMITED"]

    if len(ready) + len(limited) != len(rows):
        raise RuntimeError("V8144A_SCORE_STATUS_MISMATCH")
    if int(score_summary.get("ready_count") or 0) != len(ready):
        raise RuntimeError("V8144A_READY_SUMMARY_MISMATCH")
    if int(score_summary.get("limited_count") or 0) != len(limited):
        raise RuntimeError("V8144A_LIMITED_SUMMARY_MISMATCH")

    out_rows = []
    category_counts = Counter()
    source_counts = Counter()
    recovery_counts = Counter()
    source_tickers = defaultdict(set)
    actionable_counts = Counter()
    actionable_tickers = defaultdict(set)
    multi_counts = Counter()
    multi_tickers = defaultdict(set)

    for row in limited:
        reasons = split_reasons(row.get("missing_components"))
        code = ticker(row.get("ticker"))
        if not reasons:
            raise RuntimeError("V8144A_LIMITED_WITHOUT_REASON:" + code)
        single = len(reasons) == 1

        for reason in reasons:
            category, group = classify(reason)
            if group == "UNKNOWN":
                raise RuntimeError(
                    "V8144A_UNCLASSIFIED_REASON:" + code + ":" + reason
                )

            status = recovery(
                code,
                reason,
                group,
                single,
                da_exhausted,
                v8104_exhausted,
            )

            category_counts[category] += 1
            source_counts[group] += 1
            source_tickers[group].add(code)
            recovery_counts[status] += 1

            if single and status == "ACTIONABLE_SINGLE_BLOCKER_REAUDIT":
                actionable_counts[group] += 1
                actionable_tickers[group].add(code)
            if not single:
                multi_counts[group] += 1
                multi_tickers[group].add(code)

            out_rows.append({
                "ticker": code,
                "name": row.get("name") or "",
                "market": row.get("market") or "",
                "missing_component_count": len(reasons),
                "blocker_reason": reason,
                "blocker_category": category,
                "source_group": group,
                "single_blocker_ticker": "TRUE" if single else "FALSE",
                "recovery_status": status,
            })

    single_priority = sorted(
        [
            {
                "source_group": group,
                "actionable_single_blocker_count": count,
                "actionable_single_blocker_tickers": sorted(
                    actionable_tickers[group]
                ),
                "total_group_blocker_occurrences": source_counts[group],
            }
            for group, count in actionable_counts.items()
            if count > 0
        ],
        key=lambda x: (
            -x["actionable_single_blocker_count"],
            -x["total_group_blocker_occurrences"],
            x["source_group"],
        ),
    )

    multi_priority = sorted(
        [
            {
                "source_group": group,
                "multi_blocker_occurrences": count,
                "multi_blocker_ticker_count": len(
                    multi_tickers[group]
                ),
                "multi_blocker_tickers": sorted(
                    multi_tickers[group]
                ),
                "total_group_blocker_occurrences": source_counts[group],
            }
            for group, count in multi_counts.items()
            if count > 0 and group != "V880_SCORING_CONTRACT"
        ],
        key=lambda x: (
            -x["multi_blocker_occurrences"],
            -x["multi_blocker_ticker_count"],
            x["source_group"],
        ),
    )

    if single_priority:
        selection_mode = "ACTIONABLE_SINGLE_BLOCKER"
        selected = single_priority[0]
        selected_group = selected["source_group"]
        selected_tickers = selected[
            "actionable_single_blocker_tickers"
        ]
        next_step = "AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8145"
    elif multi_priority:
        selection_mode = "MULTI_BLOCKER_GROUP"
        selected = multi_priority[0]
        selected_group = selected["source_group"]
        selected_tickers = selected["multi_blocker_tickers"]
        next_step = "AUDIT_TOP_MULTI_BLOCKER_GROUP_V8145"
    else:
        selection_mode = "NO_SOURCE_LANE"
        selected_group = ""
        selected_tickers = []
        next_step = "REVIEW_REMAINING_POLICY_ONLY_BLOCKERS"

    out_rows.sort(
        key=lambda r: (
            int(r["missing_component_count"]),
            r["ticker"],
            r["blocker_reason"],
        )
    )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        fields = [
            "ticker",
            "name",
            "market",
            "missing_component_count",
            "blocker_reason",
            "blocker_category",
            "source_group",
            "single_blocker_ticker",
            "recovery_status",
        ]
        w = csv.DictWriter(
            f,
            fieldnames=fields,
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(out_rows)

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(
            timespec="seconds"
        ),
        "status": "AUDIT_ONLY_DYNAMIC_EXHAUSTION_AWARE_CURRENT_BLOCKERS",
        "policy_version": POLICY_VERSION,
        "v8143_result_commit": V8143_RESULT_COMMIT,
        "production_manifest": {
            "basis_date": manifest.get("basis_date"),
            "source_build_id": manifest.get("source_build_id"),
            "source_commit": manifest.get("source_commit"),
            "kospi_rows": manifest["tables"]["kospi"]["row_count"],
            "decliners_rows": manifest["tables"]["decliners"]["row_count"],
            "decliners24_rows": manifest["tables"]["decliners24"]["row_count"],
        },
        "scorer_universe_count": len(rows),
        "ready_count": len(ready),
        "limited_count": len(limited),
        "limited_blocker_occurrences": len(out_rows),
        "blocker_category_counts": dict(category_counts),
        "source_group_counts": dict(source_counts),
        "recovery_status_counts": dict(recovery_counts),
        "known_exhausted_evidence": {
            "exact_da_exhausted_union_count": 64,
            "exact_da_exhausted_union_tickers": sorted(da_exhausted),
            "score_cache_q2_exhausted_tickers": [ESR_TICKER],
            "v8104_exhausted_tickers": sorted(v8104_exhausted),
        },
        "actionable_single_priority": single_priority,
        "multi_blocker_priority": multi_priority,
        "selection_mode": selection_mode,
        "selected_source_group": selected_group,
        "selected_ticker_count": len(selected_tickers),
        "selected_tickers": selected_tickers,
        "hard_guards": {
            "production_source_cache_modified": False,
            "production_financial_cache_modified": False,
            "production_price_elasticity_cache_modified": False,
            "production_ocf_cache_modified": False,
            "production_supply_source_modified": False,
            "production_api_modified": False,
            "production_score_written": False,
            "scoring_policy_modified": False,
            "source_value_imputed": False,
            "exhausted_lane_auto_requeried": False,
            "stale_universe_assumption_used": False,
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
            "STATUS=AUDIT_ONLY_DYNAMIC_EXHAUSTION_AWARE_CURRENT_BLOCKERS",
            f"PRODUCTION_BASIS_DATE={manifest.get('basis_date')}",
            f"SCORER_UNIVERSE={len(rows)}",
            f"READY={len(ready)}",
            f"LIMITED={len(limited)}",
            f"BLOCKER_OCCURRENCES={len(out_rows)}",
            "EXACT_DA_EXHAUSTED_UNION=64",
            "SCORE_CACHE_Q2_EXHAUSTED=1",
            f"ACTIONABLE_SINGLE_BLOCKERS={sum(actionable_counts.values())}",
            f"SELECTION_MODE={selection_mode}",
            f"SELECTED_SOURCE_GROUP={selected_group}",
            f"SELECTED_TICKER_COUNT={len(selected_tickers)}",
            "PRODUCTION_DATA_MODIFIED=false",
            "SCORING_POLICY_MODIFIED=false",
            "STALE_UNIVERSE_ASSUMPTION_USED=false",
            "STATUS_OK=true",
            f"NEXT_STEP={next_step}",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.14.4A dynamic exhaustion-aware current blocker reaudit",
            "",
            f"- Production basis date: {manifest.get('basis_date')}",
            f"- Current scorer universe: {len(rows)}",
            f"- READY / LIMITED: {len(ready)} / {len(limited)}",
            f"- Blocker occurrences: {len(out_rows)}",
            "- Exact-D&A exhausted union: 64",
            "- ESR Kendall Q2 official acceleration path: exhausted",
            f"- Actionable single blockers: {sum(actionable_counts.values())}",
            f"- Selection mode: `{selection_mode}`",
            f"- Selected source group: `{selected_group}`",
            f"- Selected ticker count: {len(selected_tickers)}",
            "",
            "No frozen 149-row assumption is used.",
            "No production source, API, score, or scoring policy is modified.",
            "",
            f"Next: `{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8144A_DYNAMIC_EXHAUSTION_AWARE_REAUDIT=PASS")

if __name__ == "__main__":
    main()
