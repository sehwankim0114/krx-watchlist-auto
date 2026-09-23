#!/usr/bin/env python3
import csv
import json
import math
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import collect_universe as universe

VERSION="2026-09-23-v8.18.0-current-actionable-price-elasticity-official-audit"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8179_VERSION="2026-09-23-v8.17.9-dynamic-post-source-apply-blocker-reaudit"
V8179_COMMIT="0fafd339f3795dba1c20819c037ce9e9567a455a"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")

BLOCK_CSV=ROOT/"latest/investment_score_current_blockers_v8179.csv"
BLOCK_JSON=ROOT/"latest/investment_score_current_blockers_v8179_summary_latest.json"
PRICE_CACHE=ROOT/"latest/investment_score_price_elasticity_20d_latest.csv"
MANIFEST=ROOT/"api/two_table_v1/manifest.json"

OUT_CSV=ROOT/"latest/investment_score_price_elasticity_active_v8180.csv"
OUT_JSON=ROOT/"latest/investment_score_price_elasticity_active_v8180_summary_latest.json"
OUT_LOG=ROOT/"latest/investment_score_price_elasticity_active_v8180_run_log_latest.txt"
OUT_DOC=ROOT/"docs/investment_score_price_elasticity_active_v8180.md"

TARGETS={
    "006040":"동원산업",
    "012630":"HDC",
    "078930":"GS",
}
TARGET_ORDER=["006040","012630","078930"]
PRICE_REASON="하루평균 절대등락률:MISSING_ELASTICITY"
WINDOW_RETURNS=20
MIN_VALID_CLOSES=21
CALENDAR_LOOKBACK_DAYS=60
DESIRED_OFFICIAL_SESSIONS=30

def ticker(v):
    s="".join(c for c in str(v or "") if c.isdigit())
    return s.zfill(6) if s else ""

def num(v):
    try:
        if v is None or isinstance(v,bool):
            return None
        s=str(v).strip().replace(",","")
        if s in {"","-","None","null","nan","NaN"}:
            return None
        x=float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None

def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def read_rows(p):
    with Path(p).open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def calc(series):
    ordered=sorted(series,key=lambda x:x[0])
    if len(ordered)<MIN_VALID_CLOSES:
        return None,[],[],ordered
    returns=[]; return_dates=[]
    for i in range(1,len(ordered)):
        prev=ordered[i-1][1]; cur=ordered[i][1]
        if prev<=0 or cur<=0:
            continue
        returns.append(cur/prev-1.0)
        return_dates.append(ordered[i][0])
    if len(returns)<WINDOW_RETURNS:
        return None,returns,return_dates,ordered
    last=returns[-WINDOW_RETURNS:]
    pct=round(sum(abs(x) for x in last)/WINDOW_RETURNS*100.0,4)
    return pct,returns,return_dates,ordered

def main():
    key=os.environ.get("KRX_AUTH_KEY","").strip()
    if not key:
        raise RuntimeError("V8180_KRX_AUTH_KEY_MISSING")

    summary=read_json(BLOCK_JSON)
    manifest=read_json(MANIFEST)

    assert summary["version"]==V8179_VERSION
    assert summary["status"]=="AUDIT_ONLY_DYNAMIC_CURRENT_PRODUCTION_BLOCKERS"
    assert summary["policy_version"]==POLICY
    assert summary["selection_mode"]=="ACTIONABLE_SINGLE_BLOCKER"
    assert summary["selected_source_group"]=="PRICE_ELASTICITY_20D"
    assert summary["selected_tickers"]==TARGET_ORDER
    assert summary["selected_ticker_count"]==3
    assert summary["next_step"]=="AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8180"

    pm=summary["production_manifest"]
    assert manifest["release_stage"]=="PRODUCTION"
    assert manifest["safe_to_analyze_as_latest"] is True
    assert manifest.get("basis_date")==pm.get("basis_date")
    assert manifest.get("source_build_id")==pm.get("source_build_id")
    assert manifest.get("source_commit")==pm.get("source_commit")

    blockers=read_rows(BLOCK_CSV)
    selected=[
        r for r in blockers
        if ticker(r.get("ticker")) in TARGETS
        and r.get("source_group")=="PRICE_ELASTICITY_20D"
        and r.get("single_blocker_ticker")=="TRUE"
        and r.get("recovery_status")=="ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
        and r.get("blocker_reason")==PRICE_REASON
    ]
    if len(selected)!=3:
        raise RuntimeError("V8180_SELECTED_BLOCKERS_NOT_EXACTLY_THREE")

    seen={ticker(r.get("ticker")):r for r in selected}
    if set(seen)!=set(TARGETS):
        raise RuntimeError("V8180_TARGET_SET_CHANGED")
    for code,name in TARGETS.items():
        if seen[code].get("name")!=name:
            raise RuntimeError("V8180_TARGET_NAME_CHANGED:"+code)

    prod_rows=read_rows(PRICE_CACHE)
    prod_cache={
        ticker(r.get("ticker")):r
        for r in prod_rows if ticker(r.get("ticker"))
    }
    already_ready=[]
    for code in TARGET_ORDER:
        row=prod_cache.get(code)
        if row and row.get("source_status")=="READY" and num(row.get("avg_daily_move_pct")) is not None:
            already_ready.append(code)
    if already_ready:
        raise RuntimeError("V8180_TARGET_ALREADY_READY_IN_PRODUCTION_CACHE:"+",".join(already_ready))

    basis_iso=str(manifest.get("basis_date") or "")
    if not basis_iso:
        raise RuntimeError("V8180_MANIFEST_BASIS_MISSING")
    basis=datetime.strptime(basis_iso,"%Y-%m-%d").date()

    official_sessions=[]
    series={code:[] for code in TARGET_ORDER}
    no_target_dates={code:[] for code in TARGET_ORDER}
    request_count=0
    transport_or_parse_fail_dates=[]

    cursor=basis
    earliest=basis-timedelta(days=CALENDAR_LOOKBACK_DAYS)

    while cursor>=earliest and len(official_sessions)<DESIRED_OFFICIAL_SESSIONS:
        if cursor.weekday()<5:
            bas_dd=cursor.strftime("%Y%m%d")
            logs=[]
            try:
                raw=universe.request_krx_openapi(
                    universe.OPENAPI_STOCK_URLS["KOSPI"],
                    key,
                    bas_dd,
                    logs,
                    "V8180_KOSPI_STOCK",
                )
                request_count+=1
                norm=universe.normalize_stock_rows(raw,"KOSPI",bas_dd,logs)
            except Exception:
                request_count+=1
                transport_or_parse_fail_dates.append(cursor.isoformat())
                norm=None

            if norm is not None and not norm.empty:
                official_sessions.append(cursor.isoformat())
                for code in TARGET_ORDER:
                    match=norm[norm["ticker"]==code]
                    if not match.empty:
                        close=num(match.iloc[-1].get("close"))
                        if close is not None and close>0:
                            series[code].append((cursor.isoformat(),close))
                        else:
                            no_target_dates[code].append(cursor.isoformat())
                    else:
                        no_target_dates[code].append(cursor.isoformat())
            time.sleep(0.08)
        cursor-=timedelta(days=1)

    official_sessions=sorted(set(official_sessions))
    audit_rows=[]
    recoverable=[]
    insufficient=[]
    calculated={}

    for code in TARGET_ORDER:
        target_series=sorted({d:c for d,c in series[code]}.items())
        pct,returns,return_dates,ordered=calc(target_series)
        if pct is not None:
            classification="OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE"
            recoverable.append(code)
        else:
            classification="INSUFFICIENT_OFFICIAL_CLOSE_SESSIONS"
            insufficient.append(code)
        calculated[code]=pct
        used=ordered[-MIN_VALID_CLOSES:] if len(ordered)>=MIN_VALID_CLOSES else ordered

        audit_rows.append({
            "ticker":code,
            "name":TARGETS[code],
            "basis_date":basis_iso,
            "basis_source":"PRODUCTION_MANIFEST_BASIS_DATE",
            "official_request_count":request_count,
            "official_session_count":len(official_sessions),
            "target_valid_close_count":len(target_series),
            "required_valid_close_count":MIN_VALID_CLOSES,
            "elasticity_window_sessions":WINDOW_RETURNS,
            "avg_daily_move_pct":f"{pct:.4f}" if pct is not None else "",
            "classification":classification,
            "recoverable":"TRUE" if pct is not None else "FALSE",
            "used_close_dates_json":json.dumps([d for d,_ in used],ensure_ascii=False,separators=(",",":")),
            "last20_return_dates_json":json.dumps(return_dates[-WINDOW_RETURNS:],ensure_ascii=False,separators=(",",":")),
            "last20_returns_json":json.dumps([round(x,10) for x in returns[-WINDOW_RETURNS:]],ensure_ascii=False,separators=(",",":")),
            "official_sessions_without_valid_target_close_count":len(no_target_dates[code]),
            "official_sessions_without_valid_target_close_dates_json":json.dumps(no_target_dates[code],ensure_ascii=False,separators=(",",":")),
            "source":"KRX_OFFICIAL_STK_BYDD_TRD",
        })

    if len(recoverable)==3:
        next_step="FREEZE_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AND_SHADOW_V8181"
    elif recoverable:
        next_step="FREEZE_RECOVERABLE_PRICE_ELASTICITY_AND_REAUDIT_REMAINDER_V8181"
    else:
        next_step="AUDIT_NEXT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8181"

    OUT_CSV.parent.mkdir(parents=True,exist_ok=True)
    with OUT_CSV.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(audit_rows[0].keys()),lineterminator="\n")
        w.writeheader()
        w.writerows(audit_rows)

    result={
        "version":VERSION,
        "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
        "status":"AUDIT_ONLY_CURRENT_ACTIONABLE_PRICE_ELASTICITY",
        "policy_version":POLICY,
        "v8179_version":V8179_VERSION,
        "v8179_result_commit":V8179_COMMIT,
        "target_count":3,
        "target_tickers":TARGET_ORDER,
        "target_names":[TARGETS[c] for c in TARGET_ORDER],
        "production_price_elasticity_row_count":len(prod_cache),
        "target_present_in_production_cache":{
            c:(c in prod_cache) for c in TARGET_ORDER
        },
        "metric_contract":{
            "metric":"avg_daily_move_pct",
            "definition":"mean(abs(close_t / close_t_minus_1 - 1)) over latest 20 official close returns * 100",
            "return_count":20,
            "minimum_valid_closes":21,
            "atr_substitution_allowed":False,
        },
        "basis_date":basis_iso,
        "basis_source":"PRODUCTION_MANIFEST_BASIS_DATE",
        "official_request_count":request_count,
        "official_session_count":len(official_sessions),
        "official_session_dates":official_sessions,
        "transport_or_parse_fail_count":len(transport_or_parse_fail_dates),
        "transport_or_parse_fail_dates":transport_or_parse_fail_dates,
        "target_results":{
            r["ticker"]:{
                "name":r["name"],
                "valid_close_count":int(r["target_valid_close_count"]),
                "classification":r["classification"],
                "recoverable":r["recoverable"]=="TRUE",
                "avg_daily_move_pct":calculated[r["ticker"]],
                "official_sessions_without_valid_target_close_count":int(r["official_sessions_without_valid_target_close_count"]),
            }
            for r in audit_rows
        },
        "classification":"ALL_RECOVERABLE" if len(recoverable)==3 else ("PARTIAL_RECOVERABLE" if recoverable else "NONE_RECOVERABLE"),
        "recoverable_count":len(recoverable),
        "recoverable_tickers":recoverable,
        "insufficient_count":len(insufficient),
        "insufficient_tickers":insufficient,
        "hard_guards":{
            "production_price_elasticity_cache_modified":False,
            "production_source_cache_modified":False,
            "production_financial_cache_modified":False,
            "production_api_modified":False,
            "production_score_written":False,
            "scoring_policy_modified":False,
            "atr_used_as_elasticity_substitute":False,
            "nonofficial_price_source_used":False,
            "source_promoted":False,
        },
        "next_step":next_step,
    }

    OUT_JSON.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    OUT_LOG.write_text("\n".join([
        f"VERSION={VERSION}",
        "STATUS=AUDIT_ONLY_CURRENT_ACTIONABLE_PRICE_ELASTICITY",
        "TARGET_COUNT=3",
        "TARGET_TICKERS=006040,012630,078930",
        f"BASIS_DATE={basis_iso}",
        f"PRODUCTION_PRICE_ELASTICITY_ROWS={len(prod_cache)}",
        f"OFFICIAL_REQUEST_COUNT={request_count}",
        f"OFFICIAL_SESSION_COUNT={len(official_sessions)}",
        f"TRANSPORT_OR_PARSE_FAIL_COUNT={len(transport_or_parse_fail_dates)}",
        f"RECOVERABLE_COUNT={len(recoverable)}",
        f"RECOVERABLE_TICKERS={','.join(recoverable)}",
        f"INSUFFICIENT_COUNT={len(insufficient)}",
        f"INSUFFICIENT_TICKERS={','.join(insufficient)}",
        "ATR_SUBSTITUTION_USED=false",
        "NONOFFICIAL_PRICE_SOURCE_USED=false",
        "PRODUCTION_PRICE_ELASTICITY_CACHE_MODIFIED=false",
        "PRODUCTION_DATA_MODIFIED=false",
        "SOURCE_PROMOTED=false",
        "STATUS_OK=true",
        f"NEXT_STEP={next_step}",
    ])+"\n",encoding="utf-8")

    OUT_DOC.parent.mkdir(parents=True,exist_ok=True)
    lines=[
        "# V8.18.0 current actionable price-elasticity audit",
        "",
        "- Targets: 동원산업(006040), HDC(012630), GS(078930).",
        "- Source: official KRX daily close only.",
        f"- Production basis date: {basis_iso}.",
        "- Metric: latest 20 close-to-close absolute returns mean.",
        "- 21 valid official closes are required per ticker.",
        "- ATR substitution and non-official price substitution are forbidden.",
        "- Production caches and API are not modified.",
        "",
    ]
    for r in audit_rows:
        lines.append(
            f"- {r['name']} ({r['ticker']}): valid closes {r['target_valid_close_count']}, "
            f"classification {r['classification']}, avg_daily_move_pct {r['avg_daily_move_pct'] or 'N/A'}."
        )
    lines += ["",f"- Next: `{next_step}`",""]
    OUT_DOC.write_text("\n".join(lines),encoding="utf-8")

    print("V8180_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AUDIT=PASS")
    print(f"V8180_RECOVERABLE_COUNT={len(recoverable)}")
    print(f"V8180_RECOVERABLE_TICKERS={','.join(recoverable)}")
    print(f"V8180_INSUFFICIENT_COUNT={len(insufficient)}")
    print(f"V8180_NEXT_STEP={next_step}")

if __name__=="__main__":
    main()
