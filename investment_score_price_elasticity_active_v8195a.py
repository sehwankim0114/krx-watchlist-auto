import csv
import json
import math
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import collect_universe as universe

VERSION="2026-09-24-v8.19.5A-current-actionable-price-elasticity-single-audit"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8194A_VERSION="2026-09-24-v8.19.4A-post-ocf-dynamic-blocker-reaudit"
V8194A_COMMIT="d50d2d13f107de7af32f27bcf57a055c0d46ec1d"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")

BLOCK_CSV=ROOT/"latest/investment_score_current_blockers_v8194a.csv"
BLOCK_JSON=ROOT/"latest/investment_score_current_blockers_v8194a_summary_latest.json"
PRICE_CACHE=ROOT/"latest/investment_score_price_elasticity_20d_latest.csv"
PRICE_META=ROOT/"latest/investment_score_price_elasticity_20d_latest.json"
MANIFEST=ROOT/"api/two_table_v1/manifest.json"

OUT_CSV=ROOT/"latest/investment_score_price_elasticity_active_v8195a.csv"
OUT_JSON=ROOT/"latest/investment_score_price_elasticity_active_v8195a_summary_latest.json"
OUT_LOG=ROOT/"latest/investment_score_price_elasticity_active_v8195a_run_log_latest.txt"
OUT_DOC=ROOT/"docs/investment_score_price_elasticity_active_v8195a.md"

TARGET="034730"
TARGET_NAME="SK"
PRICE_REASON="하루평균 절대등락률:MISSING_ELASTICITY"
WINDOW_RETURNS=20
MIN_VALID_CLOSES=21
DESIRED_OFFICIAL_SESSIONS=30
CALENDAR_LOOKBACK_DAYS=70

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
    returns=[]
    return_dates=[]
    for i in range(1,len(ordered)):
        prev=ordered[i-1][1]
        cur=ordered[i][1]
        if prev<=0 or cur<=0:
            continue
        returns.append(cur/prev-1.0)
        return_dates.append(ordered[i][0])
    if len(returns)<WINDOW_RETURNS:
        return None,returns,return_dates,ordered
    last=returns[-WINDOW_RETURNS:]
    pct=round(sum(abs(x) for x in last)/WINDOW_RETURNS*100.0,4)
    return pct,returns,return_dates,ordered

key=os.environ.get("KRX_AUTH_KEY","").strip()
if not key:
    raise RuntimeError("V8195A_KRX_AUTH_KEY_MISSING")

summary=read_json(BLOCK_JSON)
manifest=read_json(MANIFEST)
price_meta=read_json(PRICE_META)

assert summary["version"]==V8194A_VERSION
assert summary["status"]=="AUDIT_ONLY_DYNAMIC_POST_OCF_BLOCKERS"
assert summary["policy_version"]==POLICY
assert summary["selection_mode"]=="ACTIONABLE_SINGLE_BLOCKER"
assert summary["selected_source_group"]=="PRICE_ELASTICITY_20D"
assert summary["selected_ticker_count"]==1
assert summary["selected_tickers"]==[TARGET]
assert summary["next_step"]=="AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8195A"

pm=summary["production_manifest"]
assert manifest["release_stage"]=="PRODUCTION"
assert manifest["safe_to_analyze_as_latest"] is True
assert manifest.get("basis_date")==pm.get("basis_date")
assert manifest.get("source_build_id")==pm.get("source_build_id")
assert manifest.get("source_commit")==pm.get("source_commit")

assert price_meta["refresh_version"]=="2026-09-24-v8.18.8A-controlled-current-basis-bulk-price-elasticity-apply"
assert price_meta["production_unique_tickers"]==217
assert price_meta["ready_tickers"]==217

blockers=read_rows(BLOCK_CSV)
selected=[
    r for r in blockers
    if ticker(r.get("ticker"))==TARGET
    and r.get("source_group")=="PRICE_ELASTICITY_20D"
    and r.get("single_blocker_ticker")=="TRUE"
    and r.get("recovery_status")=="ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
    and r.get("blocker_reason")==PRICE_REASON
]
if len(selected)!=1:
    raise RuntimeError("V8195A_SELECTED_BLOCKER_NOT_EXACTLY_ONE")
if selected[0].get("name")!=TARGET_NAME:
    raise RuntimeError("V8195A_TARGET_NAME_CHANGED:"+str(selected[0].get("name")))

prod_rows=read_rows(PRICE_CACHE)
prod_cache={ticker(r.get("ticker")):r for r in prod_rows if ticker(r.get("ticker"))}
if len(prod_cache)!=217:
    raise RuntimeError("V8195A_PRODUCTION_ELASTICITY_ROWS_DRIFT:"+str(len(prod_cache)))
row=prod_cache.get(TARGET)
if row and row.get("source_status")=="READY" and num(row.get("avg_daily_move_pct")) is not None:
    raise RuntimeError("V8195A_TARGET_ALREADY_READY_IN_PRODUCTION_CACHE")

basis_iso=str(manifest.get("basis_date") or "")
if not basis_iso:
    raise RuntimeError("V8195A_MANIFEST_BASIS_MISSING")
basis=datetime.strptime(basis_iso,"%Y-%m-%d").date()

official_sessions=[]
series=[]
missing_target_dates=[]
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
                "V8195A_KOSPI_STOCK",
            )
            request_count+=1
            norm=universe.normalize_stock_rows(raw,"KOSPI",bas_dd,logs)
        except Exception:
            request_count+=1
            transport_or_parse_fail_dates.append(cursor.isoformat())
            norm=None

        if norm is not None and not norm.empty:
            official_sessions.append(cursor.isoformat())
            match=norm[norm["ticker"]==TARGET]
            if not match.empty:
                close=num(match.iloc[-1].get("close"))
                if close is not None and close>0:
                    series.append((cursor.isoformat(),close))
                else:
                    missing_target_dates.append(cursor.isoformat())
            else:
                missing_target_dates.append(cursor.isoformat())
        time.sleep(0.08)
    cursor-=timedelta(days=1)

if transport_or_parse_fail_dates:
    raise RuntimeError(
        "V8195A_OFFICIAL_TRANSPORT_OR_PARSE_FAILURE:"
        + ",".join(transport_or_parse_fail_dates)
    )

official_sessions=sorted(set(official_sessions))
target_series=sorted({d:c for d,c in series}.items())
pct,returns,return_dates,ordered=calc(target_series)
used=ordered[-MIN_VALID_CLOSES:] if len(ordered)>=MIN_VALID_CLOSES else ordered

if pct is not None:
    classification="OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE_CURRENT_BASIS"
    recoverable=True
    next_step="FREEZE_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AND_SHADOW_V8196A"
else:
    classification="INSUFFICIENT_OFFICIAL_CLOSE_SESSIONS"
    recoverable=False
    next_step="AUDIT_NEXT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8196A"

audit_row={
    "ticker":TARGET,
    "name":TARGET_NAME,
    "basis_date":basis_iso,
    "basis_source":"CURRENT_PRODUCTION_MANIFEST_BASIS_DATE",
    "official_request_count":request_count,
    "official_session_count":len(official_sessions),
    "target_valid_close_count":len(target_series),
    "required_valid_close_count":MIN_VALID_CLOSES,
    "elasticity_window_sessions":WINDOW_RETURNS,
    "avg_daily_move_pct":f"{pct:.4f}" if pct is not None else "",
    "classification":classification,
    "recoverable":"TRUE" if recoverable else "FALSE",
    "used_close_dates_json":json.dumps([d for d,_ in used],ensure_ascii=False,separators=(",",":")),
    "last20_return_dates_json":json.dumps(return_dates[-WINDOW_RETURNS:],ensure_ascii=False,separators=(",",":")),
    "last20_returns_json":json.dumps([round(x,10) for x in returns[-WINDOW_RETURNS:]],ensure_ascii=False,separators=(",",":")),
    "official_sessions_without_valid_target_close_count":len(missing_target_dates),
    "official_sessions_without_valid_target_close_dates_json":json.dumps(missing_target_dates,ensure_ascii=False,separators=(",",":")),
    "source":"KRX_OFFICIAL_STK_BYDD_TRD",
}

OUT_CSV.parent.mkdir(parents=True,exist_ok=True)
with OUT_CSV.open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(audit_row.keys()),lineterminator="\n")
    w.writeheader()
    w.writerow(audit_row)

result={
    "version":VERSION,
    "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
    "status":"AUDIT_ONLY_CURRENT_ACTIONABLE_PRICE_ELASTICITY_SINGLE",
    "policy_version":POLICY,
    "v8194a_version":V8194A_VERSION,
    "v8194a_result_commit":V8194A_COMMIT,
    "target_count":1,
    "target_tickers":[TARGET],
    "target_names":[TARGET_NAME],
    "production_price_elasticity_row_count":len(prod_cache),
    "target_present_in_production_cache":TARGET in prod_cache,
    "metric_contract":{
        "metric":"avg_daily_move_pct",
        "definition":"mean(abs(close_t / close_t_minus_1 - 1)) over latest 20 official close returns * 100",
        "return_count":20,
        "minimum_valid_closes":21,
        "atr_substitution_allowed":False,
    },
    "basis_date":basis_iso,
    "basis_source":"CURRENT_PRODUCTION_MANIFEST_BASIS_DATE",
    "official_request_count":request_count,
    "official_session_count":len(official_sessions),
    "official_session_dates":official_sessions,
    "transport_or_parse_fail_count":0,
    "target_result":{
        "ticker":TARGET,
        "name":TARGET_NAME,
        "valid_close_count":len(target_series),
        "classification":classification,
        "recoverable":recoverable,
        "avg_daily_move_pct":pct,
        "official_sessions_without_valid_target_close_count":len(missing_target_dates),
    },
    "classification":"RECOVERABLE" if recoverable else "INSUFFICIENT",
    "recoverable_count":1 if recoverable else 0,
    "recoverable_tickers":[TARGET] if recoverable else [],
    "insufficient_count":0 if recoverable else 1,
    "insufficient_tickers":[] if recoverable else [TARGET],
    "hard_guards":{
        "production_price_elasticity_cache_modified":False,
        "production_ocf_cache_modified":False,
        "production_source_cache_modified":False,
        "production_financial_cache_modified":False,
        "production_api_modified":False,
        "production_score_written":False,
        "scoring_policy_modified":False,
        "atr_used_as_elasticity_substitute":False,
        "nonofficial_price_source_used":False,
        "source_promoted":False,
    },
    "automatic_promotion":False,
    "next_step":next_step,
}

OUT_JSON.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
OUT_LOG.write_text("\n".join([
    f"VERSION={VERSION}",
    "STATUS=AUDIT_ONLY_CURRENT_ACTIONABLE_PRICE_ELASTICITY_SINGLE",
    "TARGET_COUNT=1",
    f"TARGET_TICKER={TARGET}",
    f"TARGET_NAME={TARGET_NAME}",
    f"BASIS_DATE={basis_iso}",
    f"PRODUCTION_PRICE_ELASTICITY_ROWS={len(prod_cache)}",
    f"OFFICIAL_REQUEST_COUNT={request_count}",
    f"OFFICIAL_SESSION_COUNT={len(official_sessions)}",
    "TRANSPORT_OR_PARSE_FAIL_COUNT=0",
    f"VALID_CLOSE_COUNT={len(target_series)}",
    f"RECOVERABLE_COUNT={1 if recoverable else 0}",
    f"AVG_DAILY_MOVE_PCT={'' if pct is None else f'{pct:.4f}'}",
    "ATR_SUBSTITUTION_USED=false",
    "NONOFFICIAL_PRICE_SOURCE_USED=false",
    "PRODUCTION_PRICE_ELASTICITY_CACHE_MODIFIED=false",
    "PRODUCTION_DATA_MODIFIED=false",
    "SOURCE_PROMOTED=false",
    "AUTOMATIC_PROMOTION=false",
    "STATUS_OK=true",
    f"NEXT_STEP={next_step}",
])+"\n",encoding="utf-8")

OUT_DOC.parent.mkdir(parents=True,exist_ok=True)
OUT_DOC.write_text(
    "# V8.19.5A current actionable price-elasticity single audit\n\n"
    f"- Target: {TARGET_NAME} ({TARGET}).\n"
    "- Source: official KRX daily close only.\n"
    f"- Production basis date: {basis_iso}.\n"
    "- Metric: mean absolute close-to-close return over latest 20 official returns.\n"
    "- 21 valid official closes are required.\n"
    "- ATR substitution and non-official price substitution are forbidden.\n"
    "- Production caches, API, score and policy are unchanged.\n\n"
    f"- Valid closes: {len(target_series)}.\n"
    f"- Classification: {classification}.\n"
    f"- avg_daily_move_pct: {pct if pct is not None else 'N/A'}.\n\n"
    f"Next: `{next_step}`\n",
    encoding="utf-8"
)

print("V8195A_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AUDIT=PASS")
print(f"V8195A_RECOVERABLE_COUNT={1 if recoverable else 0}")
print(f"V8195A_AVG_DAILY_MOVE_PCT={'' if pct is None else f'{pct:.4f}'}")
print(f"V8195A_NEXT_STEP={next_step}")
