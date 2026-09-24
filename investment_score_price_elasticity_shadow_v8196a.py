import csv
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION="2026-09-24-v8.19.6A-freeze-current-actionable-price-elasticity-shadow"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8195A_VERSION="2026-09-24-v8.19.5A-current-actionable-price-elasticity-single-audit"
V8195A_COMMIT="276ef141fee759234525f8fe97ada1dffbdc6089"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")

TARGET="034730"
TARGET_NAME="SK"
TARGET_PCT=2.9064
MISSING_REASON="하루평균 절대등락률:MISSING_ELASTICITY"

AUDIT_CSV=ROOT/"latest/investment_score_price_elasticity_active_v8195a.csv"
AUDIT_JSON=ROOT/"latest/investment_score_price_elasticity_active_v8195a_summary_latest.json"
PROD_CACHE=ROOT/"latest/investment_score_price_elasticity_20d_latest.csv"

SOURCE_OUT=ROOT/"latest/investment_score_price_elasticity_source_v8196a.csv"
CAND_OUT=ROOT/"latest/investment_score_price_elasticity_candidate_v8196a.csv"
COMPARE_OUT=ROOT/"latest/investment_score_price_elasticity_shadow_v8196a.csv"
SUMMARY_OUT=ROOT/"latest/investment_score_price_elasticity_shadow_v8196a_summary_latest.json"
LOG_OUT=ROOT/"latest/investment_score_price_elasticity_shadow_v8196a_run_log_latest.txt"
DOC_OUT=ROOT/"docs/investment_score_price_elasticity_shadow_v8196a.md"

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

def write_rows(p,rs,fields):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    with Path(p).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader()
        w.writerows(rs)

def row_map(p):
    return {ticker(r.get("ticker")):r for r in read_rows(p) if ticker(r.get("ticker"))}

def stable(r):
    return json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def split_missing(v):
    return [x for x in str(v or "").split(";") if x]

def blocker_count(m):
    return sum(int(r.get("missing_component_count") or 0) for r in m.values())

def run_scorer(elasticity_path,tag):
    oc=Path(f"/tmp/{tag}.csv")
    oj=Path(f"/tmp/{tag}.json")
    ol=Path(f"/tmp/{tag}.log")
    od=Path(f"/tmp/{tag}.md")
    old={k:getattr(scorer,k) for k in ("VERSION","ELASTICITY","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC")}
    try:
        scorer.VERSION=VERSION
        scorer.ELASTICITY=Path(elasticity_path)
        scorer.OUT_CSV=oc
        scorer.OUT_JSON=oj
        scorer.OUT_LOG=ol
        scorer.OUT_DOC=od
        rc=scorer.main()
    finally:
        for k,v in old.items():
            setattr(scorer,k,v)
    if rc not in (None,0):
        raise RuntimeError("V8196A_SCORER_FAILED:"+str(rc))
    return row_map(oc),read_json(oj)

audit=read_json(AUDIT_JSON)

assert audit["version"]==V8195A_VERSION
assert audit["status"]=="AUDIT_ONLY_CURRENT_ACTIONABLE_PRICE_ELASTICITY_SINGLE"
assert audit["policy_version"]==POLICY
assert audit["target_tickers"]==[TARGET]
assert audit["target_names"]==[TARGET_NAME]
assert audit["recoverable_count"]==1
assert audit["recoverable_tickers"]==[TARGET]
assert audit["classification"]=="RECOVERABLE"
assert audit["next_step"]=="FREEZE_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AND_SHADOW_V8196A"
assert audit["metric_contract"]["atr_substitution_allowed"] is False
assert audit["basis_date"]=="2026-09-23"
assert audit["transport_or_parse_fail_count"]==0

tr=audit["target_result"]
assert tr["ticker"]==TARGET
assert tr["name"]==TARGET_NAME
assert tr["recoverable"] is True
assert tr["classification"]=="OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE_CURRENT_BASIS"
assert int(tr["valid_close_count"])==30
if abs(float(tr["avg_daily_move_pct"])-TARGET_PCT)>1e-8:
    raise RuntimeError("V8196A_AUDIT_VALUE_DRIFT")

audit_rows=read_rows(AUDIT_CSV)
if len(audit_rows)!=1:
    raise RuntimeError("V8196A_AUDIT_ROW_COUNT_NOT_1")
a=audit_rows[0]
assert ticker(a["ticker"])==TARGET
assert a["name"]==TARGET_NAME
assert a["source"]=="KRX_OFFICIAL_STK_BYDD_TRD"
assert a["classification"]=="OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE_CURRENT_BASIS"
assert a["recoverable"]=="TRUE"

pct=num(a["avg_daily_move_pct"])
if pct is None or abs(pct-TARGET_PCT)>1e-8:
    raise RuntimeError("V8196A_ELASTICITY_VALUE_CHANGED:"+str(pct))

close_dates=json.loads(a.get("used_close_dates_json") or "[]")
return_dates=json.loads(a.get("last20_return_dates_json") or "[]")
returns=json.loads(a.get("last20_returns_json") or "[]")
if len(close_dates)!=21:
    raise RuntimeError("V8196A_CLOSE_EVIDENCE_NOT_21")
if len(return_dates)!=20 or len(returns)!=20:
    raise RuntimeError("V8196A_RETURN_EVIDENCE_NOT_20")

source_fields=[
    "ticker","name","basis_date","basis_source",
    "window_start_date","window_end_date",
    "close_observation_count","daily_return_observation_count",
    "avg_daily_move_pct","classification","source",
    "last20_return_dates_json","last20_returns_json",
]
source_row={
    "ticker":TARGET,
    "name":TARGET_NAME,
    "basis_date":a["basis_date"],
    "basis_source":a["basis_source"],
    "window_start_date":close_dates[0],
    "window_end_date":close_dates[-1],
    "close_observation_count":"21",
    "daily_return_observation_count":"20",
    "avg_daily_move_pct":f"{TARGET_PCT:.4f}",
    "classification":a["classification"],
    "source":a["source"],
    "last20_return_dates_json":json.dumps(return_dates,ensure_ascii=False,separators=(",",":")),
    "last20_returns_json":json.dumps(returns,ensure_ascii=False,separators=(",",":")),
}
write_rows(SOURCE_OUT,[source_row],source_fields)

prod_rows=read_rows(PROD_CACHE)
if len(prod_rows)!=217:
    raise RuntimeError("V8196A_PRODUCTION_CACHE_NOT_217:"+str(len(prod_rows)))
prod_fields=list(prod_rows[0].keys())
prod_map={ticker(r.get("ticker")):r for r in prod_rows if ticker(r.get("ticker"))}
if len(prod_map)!=217:
    raise RuntimeError("V8196A_PRODUCTION_DUPLICATE_TICKER")
if TARGET in prod_map:
    raise RuntimeError("V8196A_TARGET_ALREADY_IN_PRODUCTION")

candidate_map=dict(prod_map)
new_row={f:"" for f in prod_fields}
new_row.update({
    "ticker":TARGET,
    "name":TARGET_NAME,
    "basis_date":source_row["basis_date"],
    "window_start_date":source_row["window_start_date"],
    "window_end_date":source_row["window_end_date"],
    "close_observation_count":"21",
    "daily_return_observation_count":"20",
    "avg_daily_move_abs":"",
    "avg_daily_move_pct":f"{TARGET_PCT:.4f}",
    "source_status":"READY",
})
candidate_map[TARGET]=new_row

candidate_rows=[candidate_map[k] for k in sorted(candidate_map)]
if len(candidate_rows)!=218:
    raise RuntimeError("V8196A_CANDIDATE_CACHE_NOT_218")
write_rows(CAND_OUT,candidate_rows,prod_fields)

cand_map=row_map(CAND_OUT)
changed_existing=[
    c for c in sorted(prod_map)
    if stable(prod_map[c])!=stable(cand_map[c])
]
if changed_existing:
    raise RuntimeError(
        "V8196A_EXISTING_CACHE_ROW_CHANGED:"+",".join(changed_existing[:20])
    )

base,bsum=run_scorer(PROD_CACHE,"v8196a_base")
shadow,ssum=run_scorer(CAND_OUT,"v8196a_shadow")

if set(base)!=set(shadow) or len(base)!=198:
    raise RuntimeError("V8196A_SCORER_UNIVERSE_DRIFT")

b_ready=int(bsum.get("ready_count") or 0)
s_ready=int(ssum.get("ready_count") or 0)
b_limited=int(bsum.get("limited_count") or 0)
s_limited=int(ssum.get("limited_count") or 0)
b_blockers=blocker_count(base)
s_blockers=blocker_count(shadow)

if (b_ready,b_limited,b_blockers)!=(22,176,1618):
    raise RuntimeError(
        f"V8196A_BASELINE_DRIFT:{b_ready}:{b_limited}:{b_blockers}"
    )
if (s_ready,s_limited,s_blockers)!=(23,175,1617):
    raise RuntimeError(
        f"V8196A_SHADOW_RESULT_BAD:{s_ready}:{s_limited}:{s_blockers}"
    )

bm=split_missing(base[TARGET].get("missing_components"))
sm=split_missing(shadow[TARGET].get("missing_components"))

if base[TARGET].get("score_status")!="LIMITED":
    raise RuntimeError("V8196A_BASE_TARGET_NOT_LIMITED")
if bm!=[MISSING_REASON]:
    raise RuntimeError("V8196A_BASE_NOT_SINGLE_ELASTICITY:"+"|".join(bm))
if shadow[TARGET].get("score_status")!="READY":
    raise RuntimeError("V8196A_SHADOW_TARGET_NOT_READY")
if MISSING_REASON in sm:
    raise RuntimeError("V8196A_ELASTICITY_REASON_NOT_REMOVED")

non_target_changed=[
    c for c in sorted(set(base)-{TARGET})
    if stable(base[c])!=stable(shadow[c])
]
if non_target_changed:
    raise RuntimeError(
        "V8196A_NON_TARGET_SCORE_DRIFT:"+",".join(non_target_changed[:30])
    )

compare_row={
    "ticker":TARGET,
    "name":TARGET_NAME,
    "avg_daily_move_pct":f"{TARGET_PCT:.4f}",
    "baseline_status":base[TARGET].get("score_status",""),
    "shadow_status":shadow[TARGET].get("score_status",""),
    "baseline_missing_components":";".join(bm),
    "shadow_missing_components":";".join(sm),
    "baseline_score_total":base[TARGET].get("score_total",""),
    "shadow_score_total":shadow[TARGET].get("score_total",""),
}
write_rows(COMPARE_OUT,[compare_row],list(compare_row.keys()))

summary={
    "version":VERSION,
    "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
    "status":"SOURCE_ONLY_FROZEN_SHADOW_PASS",
    "policy_version":POLICY,
    "v8195a_version":V8195A_VERSION,
    "v8195a_result_commit":V8195A_COMMIT,
    "source_frozen_count":1,
    "source_frozen_tickers":[TARGET],
    "frozen_avg_daily_move_pct":{TARGET:TARGET_PCT},
    "basis_date":audit["basis_date"],
    "basis_source":audit["basis_source"],
    "production_cache_row_count":217,
    "shadow_candidate_row_count":218,
    "cache_row_delta":1,
    "existing_elasticity_row_changed_count":0,
    "current_scorer_universe_count":198,
    "baseline_ready_count":22,
    "shadow_ready_count":23,
    "ready_delta":1,
    "baseline_limited_count":176,
    "shadow_limited_count":175,
    "limited_delta":-1,
    "baseline_blocker_occurrences":1618,
    "shadow_blocker_occurrences":1617,
    "blocker_occurrences_reduced_by":1,
    "newly_ready_count":1,
    "newly_ready_tickers":[TARGET],
    "elasticity_reason_removed_count":1,
    "elasticity_reason_removed_tickers":[TARGET],
    "non_target_score_row_changed_count":0,
    "hard_guards":{
        "production_price_elasticity_cache_modified":False,
        "production_price_elasticity_metadata_modified":False,
        "production_price_elasticity_run_log_modified":False,
        "production_ocf_cache_modified":False,
        "production_source_cache_modified":False,
        "production_financial_cache_modified":False,
        "production_api_modified":False,
        "production_score_written":False,
        "scoring_policy_modified":False,
        "atr_used_as_elasticity_substitute":False,
        "nonofficial_price_source_used":False,
        "non_target_score_row_changed":False,
    },
    "automatic_promotion":False,
    "next_step":"STAGE_CURRENT_SINGLE_PRICE_ELASTICITY_PATCH_V8197A",
}

SUMMARY_OUT.write_text(
    json.dumps(summary,ensure_ascii=False,indent=2)+"\n",
    encoding="utf-8"
)
LOG_OUT.write_text("\n".join([
    f"VERSION={VERSION}",
    "STATUS=SOURCE_ONLY_FROZEN_SHADOW_PASS",
    "SOURCE_FROZEN_COUNT=1",
    "SOURCE_FROZEN_TICKERS=034730",
    "FROZEN_VALUES=034730:2.9064",
    "PRODUCTION_CACHE_ROWS=217",
    "SHADOW_CANDIDATE_ROWS=218",
    "CACHE_ROW_DELTA=1",
    "EXISTING_ELASTICITY_ROW_CHANGED_COUNT=0",
    "CURRENT_SCORER_UNIVERSE=198",
    "BASELINE_READY=22",
    "SHADOW_READY=23",
    "READY_DELTA=1",
    "BASELINE_LIMITED=176",
    "SHADOW_LIMITED=175",
    "LIMITED_DELTA=-1",
    "BASELINE_BLOCKERS=1618",
    "SHADOW_BLOCKERS=1617",
    "BLOCKER_REDUCED_BY=1",
    "NEWLY_READY=1",
    "NON_TARGET_SCORE_ROW_CHANGED_COUNT=0",
    "PRODUCTION_PRICE_ELASTICITY_CACHE_MODIFIED=false",
    "PRODUCTION_DATA_MODIFIED=false",
    "PRODUCTION_SCORE_WRITTEN=false",
    "ATR_SUBSTITUTION_USED=false",
    "NONOFFICIAL_PRICE_SOURCE_USED=false",
    "AUTOMATIC_PROMOTION=false",
    "STATUS_OK=true",
    "NEXT_STEP=STAGE_CURRENT_SINGLE_PRICE_ELASTICITY_PATCH_V8197A",
])+"\n",encoding="utf-8")

DOC_OUT.parent.mkdir(parents=True,exist_ok=True)
DOC_OUT.write_text(
    "# V8.19.6A current actionable price-elasticity freeze and shadow\n\n"
    "- Frozen official KRX elasticity source: SK (034730) = 2.9064%.\n"
    "- Production elasticity cache remains 217 rows.\n"
    "- Shadow candidate contains 218 rows.\n"
    "- READY / LIMITED: 22 / 176 -> 23 / 175.\n"
    "- Blockers: 1618 -> 1617 (-1).\n"
    "- 034730 changes from the single elasticity blocker to READY.\n"
    "- Existing production elasticity rows changed: 0.\n"
    "- Non-target score drift: 0.\n"
    "- No production cache, API, score or policy is modified.\n\n"
    "Next: STAGE_CURRENT_SINGLE_PRICE_ELASTICITY_PATCH_V8197A\n",
    encoding="utf-8"
)

print("V8196A_PRICE_ELASTICITY_SHADOW=PASS")
print("V8196A_CACHE_ROWS=217->218")
print("V8196A_READY=22->23")
print("V8196A_BLOCKERS=1618->1617")
print("V8196A_NON_TARGET_SCORE_DRIFT=0")
