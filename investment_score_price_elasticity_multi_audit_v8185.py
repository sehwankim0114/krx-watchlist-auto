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

VERSION="2026-09-23-v8.18.5-top-multi-price-elasticity-official-audit"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8184_VERSION="2026-09-23-v8.18.4-dynamic-post-elasticity-blocker-reaudit"
V8184_COMMIT="f88707312e12c6eb0af2c36da2ca2f63f7d3afa1"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")

BLOCK_CSV=ROOT/"latest/investment_score_current_blockers_v8184.csv"
BLOCK_JSON=ROOT/"latest/investment_score_current_blockers_v8184_summary_latest.json"
PRICE_CACHE=ROOT/"latest/investment_score_price_elasticity_20d_latest.csv"
MANIFEST=ROOT/"api/two_table_v1/manifest.json"

OUT_CSV=ROOT/"latest/investment_score_price_elasticity_multi_audit_v8185.csv"
OUT_JSON=ROOT/"latest/investment_score_price_elasticity_multi_audit_v8185_summary_latest.json"
OUT_LOG=ROOT/"latest/investment_score_price_elasticity_multi_audit_v8185_run_log_latest.txt"
OUT_DOC=ROOT/"docs/investment_score_price_elasticity_multi_audit_v8185.md"

PRICE_REASON="하루평균 절대등락률:MISSING_ELASTICITY"
WINDOW_RETURNS=20
MIN_VALID_CLOSES=21
CALENDAR_LOOKBACK_DAYS=70
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
        raise RuntimeError("V8185_KRX_AUTH_KEY_MISSING")

    audit=read_json(BLOCK_JSON)
    manifest=read_json(MANIFEST)

    assert audit["version"]==V8184_VERSION
    assert audit["status"]=="AUDIT_ONLY_DYNAMIC_POST_ELASTICITY_BLOCKERS"
    assert audit["policy_version"]==POLICY
    assert audit["selection_mode"]=="MULTI_BLOCKER_GROUP"
    assert audit["selected_source_group"]=="PRICE_ELASTICITY_20D"
    assert audit["selected_ticker_count"]==100
    assert len(audit["selected_tickers"])==100
    assert audit["next_step"]=="AUDIT_TOP_MULTI_BLOCKER_GROUP_V8185"

    targets=list(audit["selected_tickers"])
    target_set=set(targets)
    if len(target_set)!=100:
        raise RuntimeError("V8185_SELECTED_TARGET_DUPLICATE")

    pm=audit["production_manifest"]
    assert manifest["release_stage"]=="PRODUCTION"
    assert manifest["safe_to_analyze_as_latest"] is True
    assert manifest.get("basis_date")==pm.get("basis_date")
    assert manifest.get("source_build_id")==pm.get("source_build_id")
    assert manifest.get("source_commit")==pm.get("source_commit")

    blockers=read_rows(BLOCK_CSV)
    selected={}
    for r in blockers:
        code=ticker(r.get("ticker"))
        if (
            code in target_set
            and r.get("source_group")=="PRICE_ELASTICITY_20D"
            and r.get("blocker_reason")==PRICE_REASON
        ):
            selected[code]=r

    if set(selected)!=target_set:
        missing=sorted(target_set-set(selected))
        extra=sorted(set(selected)-target_set)
        raise RuntimeError(
            "V8185_BLOCKER_TARGET_SET_MISMATCH:"
            +"MISSING="+",".join(missing[:20])
            +":EXTRA="+",".join(extra[:20])
        )

    prod_rows=read_rows(PRICE_CACHE)
    prod_cache={
        ticker(r.get("ticker")):r
        for r in prod_rows if ticker(r.get("ticker"))
    }
    if len(prod_cache)!=155:
        raise RuntimeError("V8185_PRODUCTION_CACHE_NOT_155:"+str(len(prod_cache)))

    existing=sorted(target_set & set(prod_cache))
    if existing:
        raise RuntimeError(
            "V8185_SELECTED_TARGET_ALREADY_IN_PRODUCTION_CACHE:"
            +",".join(existing[:30])
        )

    basis_iso=str(manifest.get("basis_date") or "")
    if not basis_iso:
        raise RuntimeError("V8185_MANIFEST_BASIS_MISSING")
    basis=datetime.strptime(basis_iso,"%Y-%m-%d").date()

    official_sessions=[]
    series={code:[] for code in targets}
    no_target_dates={code:[] for code in targets}
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
                    "V8185_KOSPI_STOCK",
                )
                request_count+=1
                norm=universe.normalize_stock_rows(
                    raw,"KOSPI",bas_dd,logs
                )
            except Exception:
                request_count+=1
                transport_or_parse_fail_dates.append(cursor.isoformat())
                norm=None

            if norm is not None and not norm.empty:
                official_sessions.append(cursor.isoformat())
                close_map={}
                for _,row in norm.iterrows():
                    code=ticker(row.get("ticker"))
                    if code in target_set:
                        close=num(row.get("close"))
                        if close is not None and close>0:
                            close_map[code]=close
                for code in targets:
                    if code in close_map:
                        series[code].append((cursor.isoformat(),close_map[code]))
                    else:
                        no_target_dates[code].append(cursor.isoformat())
            time.sleep(0.08)
        cursor-=timedelta(days=1)

    official_sessions=sorted(set(official_sessions))
    audit_rows=[]
    recoverable=[]
    insufficient=[]
    calculated={}

    for code in targets:
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
            "name":selected[code].get("name",""),
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
            "used_close_dates_json":json.dumps(
                [d for d,_ in used],ensure_ascii=False,separators=(",",":")
            ),
            "last20_return_dates_json":json.dumps(
                return_dates[-WINDOW_RETURNS:],ensure_ascii=False,separators=(",",":")
            ),
            "last20_returns_json":json.dumps(
                [round(x,10) for x in returns[-WINDOW_RETURNS:]],
                ensure_ascii=False,separators=(",",":")
            ),
            "official_sessions_without_valid_target_close_count":len(no_target_dates[code]),
            "official_sessions_without_valid_target_close_dates_json":json.dumps(
                no_target_dates[code],ensure_ascii=False,separators=(",",":")
            ),
            "source":"KRX_OFFICIAL_STK_BYDD_TRD",
        })

    recoverable=sorted(recoverable)
    insufficient=sorted(insufficient)
    audit_rows.sort(key=lambda r:r["ticker"])

    if recoverable:
        next_step="FREEZE_RECOVERABLE_MULTI_PRICE_ELASTICITY_AND_SHADOW_V8186"
    else:
        next_step="AUDIT_NEXT_MULTI_BLOCKER_SOURCE_GROUP_V8186"

    OUT_CSV.parent.mkdir(parents=True,exist_ok=True)
    with OUT_CSV.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(
            f,fieldnames=list(audit_rows[0].keys()),lineterminator="\n"
        )
        w.writeheader()
        w.writerows(audit_rows)

    result={
        "version":VERSION,
        "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
        "status":"AUDIT_ONLY_TOP_MULTI_PRICE_ELASTICITY",
        "policy_version":POLICY,
        "v8184_version":V8184_VERSION,
        "v8184_result_commit":V8184_COMMIT,
        "target_count":100,
        "target_tickers":targets,
        "production_price_elasticity_row_count":len(prod_cache),
        "selected_target_present_in_production_cache_count":0,
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
        "recoverable_count":len(recoverable),
        "recoverable_tickers":recoverable,
        "insufficient_count":len(insufficient),
        "insufficient_tickers":insufficient,
        "classification":(
            "ALL_RECOVERABLE" if len(recoverable)==100
            else ("PARTIAL_RECOVERABLE" if recoverable else "NONE_RECOVERABLE")
        ),
        "target_results":{
            r["ticker"]:{
                "name":r["name"],
                "valid_close_count":int(r["target_valid_close_count"]),
                "classification":r["classification"],
                "recoverable":r["recoverable"]=="TRUE",
                "avg_daily_move_pct":calculated[r["ticker"]],
                "official_sessions_without_valid_target_close_count":int(
                    r["official_sessions_without_valid_target_close_count"]
                ),
            }
            for r in audit_rows
        },
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

    OUT_JSON.write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )
    OUT_LOG.write_text("\n".join([
        f"VERSION={VERSION}",
        "STATUS=AUDIT_ONLY_TOP_MULTI_PRICE_ELASTICITY",
        "TARGET_COUNT=100",
        f"BASIS_DATE={basis_iso}",
        f"PRODUCTION_PRICE_ELASTICITY_ROWS={len(prod_cache)}",
        f"OFFICIAL_REQUEST_COUNT={request_count}",
        f"OFFICIAL_SESSION_COUNT={len(official_sessions)}",
        f"TRANSPORT_OR_PARSE_FAIL_COUNT={len(transport_or_parse_fail_dates)}",
        f"RECOVERABLE_COUNT={len(recoverable)}",
        f"INSUFFICIENT_COUNT={len(insufficient)}",
        "ATR_SUBSTITUTION_USED=false",
        "NONOFFICIAL_PRICE_SOURCE_USED=false",
        "PRODUCTION_PRICE_ELASTICITY_CACHE_MODIFIED=false",
        "PRODUCTION_DATA_MODIFIED=false",
        "SOURCE_PROMOTED=false",
        "STATUS_OK=true",
        f"NEXT_STEP={next_step}",
    ])+"\n",encoding="utf-8")

    OUT_DOC.parent.mkdir(parents=True,exist_ok=True)
    OUT_DOC.write_text(
        "# V8.18.5 top multi-blocker price-elasticity audit\n\n"
        "- Selected lane: PRICE_ELASTICITY_20D.\n"
        "- Target multi-blocker tickers: 100.\n"
        f"- Official KRX sessions collected: {len(official_sessions)}.\n"
        f"- Recoverable: {len(recoverable)}.\n"
        f"- Insufficient official close history: {len(insufficient)}.\n"
        "- Metric uses 20 close-to-close absolute returns from 21 official closes.\n"
        "- ATR and non-official price substitution are forbidden.\n"
        "- Production cache, API, score, and policy remain unchanged.\n\n"
        f"Next: {next_step}\n",
        encoding="utf-8"
    )

    print("V8185_MULTI_PRICE_ELASTICITY_AUDIT=PASS")
    print(f"V8185_RECOVERABLE_COUNT={len(recoverable)}")
    print(f"V8185_INSUFFICIENT_COUNT={len(insufficient)}")
    print(f"V8185_NEXT_STEP={next_step}")

if __name__=="__main__":
    main()
