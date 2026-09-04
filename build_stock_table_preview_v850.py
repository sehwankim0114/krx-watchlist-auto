"""Read-only two-table V8.5.0 data preview. All output must be outside repo.

No API publishing, no Git pushes, no network requests and no live-price fallback.
Missing sector/consensus/score inputs stay null and block production readiness.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from stock_table_metrics_v850 import CONTRACT, VERSION, indicators, number


HEADERS = ["추천/종목", "요청시점 현재가", "평균등락일수", "연속등락",
    "가치매수→1차익절", "3개월 저~고·현재위치", "큰 스윙 위치·방향",
    "추세(5·20·60·120)", "1M/3M 흐름", "거래·탄력/변동폭", "수급·위험",
    "기업가치·실적", "실적전망 변화", "1M/3M 상대강도", "ATR·하루변동폭",
    "추적손절 기준", "투자종합점수·진입판단", "시장·티커", "섹터·업종강도"]
COMPACT_COLUMNS = ["name", "ticker", "official_close", "run", "streak", "range_3m",
    "swing", "ma", "returns", "rs_kospi_pp", "atr14", "activity", "analysis", "sector_theme"]


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def ticker(value):
    value = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,6}", value):
        raise ValueError("INVALID_EXACT_TICKER:" + value)
    return value.zfill(6)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return len(raw)


def compact_row(row):
    m, a = row["metrics"], row["analysis"]
    if m.get("status") != "OK":
        return [row["name"], row["ticker"], None, None, None, None, None, None, None, None, None, None, None, row["sector_theme"]]
    result = [row["name"], row["ticker"], m["official_close"],
        [m["run"][k] for k in ("average", "up_average", "down_average")],
        [m["streak"][k] for k in ("direction", "days", "change_pct")],
        [m["range_3m"][k] for k in ("low", "high", "position_pct")],
        [m["swing"].get(k) for k in ("phase", "from_trough_pct", "from_peak_pct", "trough_date", "peak_date")],
        [[m["ma"][str(p)][k] for k in ("value", "direction")] for p in (5,20,60,120)],
        [m["returns"][str(p)]["pct"] for p in (1,3)], [m["rs_kospi_pp"][str(p)] for p in (1,3)],
        [m["atr14"]["krw"],m["atr14"]["pct"],m["avg_daily_range_20_pct"]],
        [m["activity"]["volume_vs_20d"],m["activity"]["avg20_trading_value_krw"]],
        [a.get(k) for k in ("value_buy_range", "first_sell_target_range", "operating_profit", "earnings_trend", "per", "pbr", "supply_status", "supply_level", "supply_keywords")],
        row["sector_theme"]]
    return result


def build(repo, output):
    repo, output = repo.resolve(), output.resolve()
    if output == repo or output.is_relative_to(repo):
        raise ValueError("OUTPUT_MUST_BE_OUTSIDE_REPOSITORY")
    if output.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW_DIRECTORY")
    inputs = ["api/status.json", "api/kospi_watchlist.json", "latest/universe_raw_history_latest.csv",
        "latest/kospi_universe_summary_latest.csv", "latest/official_index_history_latest.csv"]
    hashes = {p: digest(repo/p) for p in inputs}
    status = json.loads((repo/inputs[0]).read_text(encoding="utf-8"))
    kospi = json.loads((repo/inputs[1]).read_text(encoding="utf-8"))
    if status.get("api_sync_ok") is not True or status.get("critical_errors"):
        raise ValueError("SOURCE_API_NOT_SYNCHRONIZED")
    if not status.get("build_id") or kospi.get("build_id") != status["build_id"]:
        raise ValueError("SOURCE_BUILD_ID_MISMATCH")
    for key in ("rules_version", "rules_sha256"):
        if not status.get(key) or status[key] != kospi.get(key):
            raise ValueError("SOURCE_RULES_MISMATCH:"+key)
    if kospi.get("status") != "OK" or kospi.get("row_count") != 30:
        raise ValueError("SOURCE_KOSPI_STATUS_OR_ROW_COUNT_INVALID")
    if len(kospi.get("rows", [])) != 30:
        raise ValueError("KOSPI_MUST_HAVE_EXACTLY_30_ROWS")
    basis = status["confirmed_basis_date"]
    if any(r.get("analysis_date") != basis for r in kospi["rows"]):
        raise ValueError("SELECTED_ANALYSIS_DATE_MISMATCH")
    bench = [{"date": r["date"], "close": r["official_index_close"]} for r in read_csv(repo/inputs[4])
             if r["market"] == "KOSPI" and r["date"] <= basis]
    sessions = sorted({r["date"] for r in bench})
    if not sessions or sessions[-1] != basis:
        raise ValueError("OFFICIAL_BENCHMARK_BASIS_MISMATCH")
    grouped = defaultdict(list)
    future_bars_ignored = 0
    for row in read_csv(repo/inputs[2]):
        if row["market"] == "KOSPI":
            if row["date"] > basis:
                future_bars_ignored += 1
            else:
                grouped[ticker(row["ticker"])].append(row)
    summary = {ticker(r["ticker"]): r for r in read_csv(repo/inputs[3]) if r["market"] == "KOSPI"}
    if len(summary) < 800:
        raise ValueError("KOSPI_UNIVERSE_TOO_SMALL")
    selected = {ticker(r["code"]): r for r in kospi["rows"]}
    if len(selected) != 30:
        raise ValueError("DUPLICATE_KOSPI_TICKERS")
    rows, skipped = {}, Counter()
    for code, source in summary.items():
        try:
            m = indicators(grouped.get(code, []), basis, sessions, bench)
        except ValueError as exc:
            m = {"status": "INVALID_HISTORY", "reason": str(exc), "basis_date": basis}
        if m["status"] != "OK":
            skipped[m["status"]] += 1
        legacy = selected.get(code, {})
        def source_range(low, high):
            lo, hi = number(source.get(low)), number(source.get(high))
            return f"{lo:g}~{hi:g}" if lo is not None and hi is not None else None
        rows[code] = {"ticker": code, "name": source["name"], "market": "KOSPI", "metrics": m,
            "request_time_price": None, "request_time_price_status": "NOT_QUERIED_IN_OFFLINE_PREVIEW",
            "sector_theme": legacy.get("sector_theme"),
            "analysis": {"basis_date": source.get("last_date"),
                "value_buy_range": legacy.get("value_buy_range") or source_range("split_buy_low_ref", "split_buy_high_ref"),
                "first_sell_target_range": legacy.get("first_sell_target_range") or source_range("target1_ref", "target2_ref"),
                "operating_profit": legacy.get("operating_profit_text") or source.get("operating_profit"),
                "earnings_trend": legacy.get("earnings_trend"), "per": legacy.get("per_annualized"), "pbr": legacy.get("pbr"),
                "supply_status": legacy.get("supply_check_status") or source.get("supply_check_status"),
                "supply_level": legacy.get("supply_burden_level") or source.get("supply_burden_level"),
                "supply_keywords": legacy.get("supply_burden_keywords") or source.get("supply_burden_keywords"),
                "legacy_score_not_100_scale": legacy.get("score")}}
        if source.get("last_date") != basis:
            rows[code]["analysis"] = {"basis_date": source.get("last_date"), "status": "STALE_SUMMARY_NOT_USED"}
    missing_selected = set(selected) - set(rows)
    if missing_selected:
        raise ValueError("SELECTED_TICKERS_MISSING_FROM_SUMMARY:"+str(sorted(missing_selected)))
    kospi_rows = [rows[ticker(r["code"])] for r in kospi["rows"]]
    invalid_selected = [r["ticker"] for r in kospi_rows if r["metrics"].get("status") != "OK"]
    if invalid_selected:
        raise ValueError("KOSPI_SELECTED_HISTORY_INVALID:"+str(invalid_selected))
    decliners = [r for r in rows.values() if r["metrics"].get("status") == "OK"
                 and r["metrics"]["streak"]["direction"] == -1 and r["metrics"]["streak"]["days"] >= 3]
    decliners.sort(key=lambda r: (-r["metrics"]["streak"]["days"], r["metrics"]["streak"]["change_pct"], r["ticker"]))
    decliners24 = [r for r in rows.values() if r["metrics"].get("matches_decliners_24")]
    decliners24.sort(key=lambda r: (-r["metrics"]["streak"]["days"], r["ticker"]))
    meta = {"version": VERSION, "source_build_id": status["build_id"], "basis_date": basis,
        "source_official_fresh_now": status.get("official_fresh_now"),
        "source_safe_to_analyze_as_latest": status.get("safe_to_analyze_as_latest"),
        "production_activation_allowed": False, "status": "PREVIEW_ONLY_NOT_INVESTMENT_OUTPUT",
        "contract": CONTRACT, "headers": HEADERS,
        "explicit_missing": ["investment_score_100", "earnings_outlook_change", "rs_sector", "confirmed_swing_low_stop"],
        "disclosure": "오프라인 개발 검증용. 요청시점 현재가 아님. 최신 자료/완성표/매매지시로 사용 금지."}
    output.mkdir(parents=True)
    compact_sizes = {}
    for label, items in (("kospi", kospi_rows), ("decliners", decliners), ("decliners24", decliners24)):
        header = list(HEADERS)
        if label != "kospi":
            for old, new in (("연속등락", "연속하락"), ("수급·위험", "수급·위험·하락성격"),
                ("투자종합점수·진입판단", "투자종합점수·반등판단"), ("섹터·업종강도", "섹터·업종흐름")):
                header[header.index(old)] = new
        write_json(output/f"{label}.json", {**meta, "table_id":label,"headers":header,"row_count":len(items),"rows":items})
        # Candidate lists are not truncated: previews paginate at 30 rows/page.
        pages = [items[i:i+30] for i in range(0, len(items), 30)] or [[]]
        for i, page in enumerate(pages, 1):
            projection = [compact_row(r) for r in page]
            if any(len(r) != len(COMPACT_COLUMNS) for r in projection):
                raise ValueError("COMPACT_COLUMN_WIDTH_MISMATCH")
            payload = {**meta,"table_id":label,"headers":header,"columns":COMPACT_COLUMNS,
                "total_rows":len(items),"page":i,"page_count":len(pages),"row_count":len(page),"rows":projection}
            name = f"{label}.compact.{i}.json"
            size = write_json(output/name, payload)
            compact_sizes[name] = size
            if size > 30000:
                raise ValueError(f"PREVIEW_COMPACT_TOO_LARGE:{name}:{size}")
    source_unchanged = hashes == {p:digest(repo/p) for p in inputs}
    if not source_unchanged:
        raise ValueError("SOURCE_FILES_CHANGED_DURING_PREVIEW")
    coverage = {}
    for key in ("ma120", "atr14", "run", "return_3m"):
        coverage[key] = sum(key not in r["metrics"]["missing"] for r in kospi_rows)
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    report = {"test_status":"PASS", "version":VERSION, "source_commit":commit,
        "source_build_id":status["build_id"], "basis_date":basis,
        "expected_official_date":status.get("computed_expected_official_trading_date"),
        "source_status":status["status"], "source_official_fresh_now":status.get("official_fresh_now"),
        "production_activation_allowed":False, "standalone_swing_table_enabled":False,
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "universe_count":len(summary), "kospi_rows":len(kospi_rows),"decliners_rows":len(decliners),
        "decliners24_rows":len(decliners24),"skipped_history":dict(skipped),"future_bars_ignored":future_bars_ignored,
        "kospi_coverage_out_of_30":coverage,"compact_sizes":compact_sizes,
        "kospi_order_preserved":[r["ticker"] for r in kospi_rows] == list(selected),
        "source_files_unchanged":source_unchanged,"source_sha256":hashes,
        "pending":meta["explicit_missing"]+["WORKER_DEPLOYMENT", "ACTION_SCHEMA_AND_GPT_INSTRUCTIONS", "FINAL_DISPLAY_TEST"]}
    write_json(output/"report.json", report)
    lines = ["# V8.5.0 코피표·연속하락표 데이터 사전검증", "", "개발 검사 PASS는 운영 배포 완료를 뜻하지 않습니다.",
        "독립 스윙분석표 제외. 두 표 안의 큰 스윙 방향은 포함.",
        f"자료 기준일: {basis}; 기대 거래일: {report['expected_official_date']}",
        f"자료 상태: {status['status']}; 최신성: {status.get('official_fresh_now')}",
        f"코피표 {len(kospi_rows)}행 / 일반 연속하락 {len(decliners)}행 / 2.4 조건 {len(decliners24)}행", "",
        "## 코피표 30종목 지표 확보", "", *[f"- {k}: {v}/30" for k,v in coverage.items()], "",
        "## 다음 단계", "", "100점 점수 기준·업종 RS·실적전망 자료 연결, Worker·Action·지침 동시 반영 후 실제 출력 검사.",
        "현재가 조회와 최종 추천은 이 오프라인 검증에서 실행하지 않았습니다."]
    (output/"report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    report = build(args.repo, args.output_dir)
    for k,v in {"V850_DATA_PREVIEW":"PASS", "KOSPI_ROWS":report["kospi_rows"],
        "DECLINERS_ROWS":report["decliners_rows"],"DECLINERS24_ROWS":report["decliners24_rows"],
        "SOURCE_OFFICIAL_FRESH_NOW":str(report["source_official_fresh_now"]).lower(),
        "SOURCE_BASIS_DATE":report["basis_date"], "EXPECTED_OFFICIAL_DATE":report["expected_official_date"],
        "ALL_PREVIEW_PAGES_UNDER_30000":"PASS", "SOURCE_FILES_UNCHANGED":"PASS",
        "PRODUCTION_ACTIVATION_ALLOWED":"false", "STANDALONE_SWING_TABLE_ENABLED":"false"}.items():
        print(f"{k}={v}")
    print("OUTPUT_REPORT="+str(args.output_dir/"report.json"))


if __name__ == "__main__":
    main()
