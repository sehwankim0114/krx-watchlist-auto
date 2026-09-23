#!/usr/bin/env python3
import csv
import json
import math
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION="2026-09-23-v8.18.1-freeze-actionable-price-elasticity-and-shadow"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8180_VERSION="2026-09-23-v8.18.0-current-actionable-price-elasticity-official-audit"
V8180_COMMIT="caa411f86cdcaf326322d9e4703ac27cd3888cf5"

ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")
TARGETS={
    "006040":{"name":"동원산업","pct":0.9959},
    "012630":{"name":"HDC","pct":2.5720},
    "078930":{"name":"GS","pct":2.2485},
}
TARGET_ORDER=["006040","012630","078930"]
MISSING_REASON="하루평균 절대등락률:MISSING_ELASTICITY"

AUDIT_CSV=ROOT/"latest/investment_score_price_elasticity_active_v8180.csv"
AUDIT_JSON=ROOT/"latest/investment_score_price_elasticity_active_v8180_summary_latest.json"
PROD_CACHE=ROOT/"latest/investment_score_price_elasticity_20d_latest.csv"

SOURCE_OUT=ROOT/"latest/investment_score_price_elasticity_source_v8181.csv"
CAND_OUT=ROOT/"latest/investment_score_price_elasticity_candidate_v8181.csv"
COMPARE_OUT=ROOT/"latest/investment_score_price_elasticity_shadow_v8181.csv"
SUMMARY_OUT=ROOT/"latest/investment_score_price_elasticity_shadow_v8181_summary_latest.json"
LOG_OUT=ROOT/"latest/investment_score_price_elasticity_shadow_v8181_run_log_latest.txt"
DOC_OUT=ROOT/"docs/investment_score_price_elasticity_shadow_v8181.md"

BASE_CSV=Path("/tmp/v8181_base.csv")
BASE_JSON=Path("/tmp/v8181_base.json")
BASE_LOG=Path("/tmp/v8181_base.log")
BASE_DOC=Path("/tmp/v8181_base.md")
SHADOW_CSV=Path("/tmp/v8181_shadow.csv")
SHADOW_JSON=Path("/tmp/v8181_shadow.json")
SHADOW_LOG=Path("/tmp/v8181_shadow.log")
SHADOW_DOC=Path("/tmp/v8181_shadow.md")

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

def write_rows(p,rows,fields):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    with Path(p).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader(); w.writerows(rows)

def row_map(p):
    return {ticker(r.get("ticker")):r for r in read_rows(p) if ticker(r.get("ticker"))}

def stable(r):
    return json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def split_missing(v):
    return [x for x in str(v or "").split(";") if x]

def blocker_count(m):
    return sum(int(r.get("missing_component_count") or 0) for r in m.values())

def run_scorer(elasticity_path,out_csv,out_json,out_log,out_doc):
    old={k:getattr(scorer,k) for k in ("VERSION","ELASTICITY","OUT_CSV","OUT_JSON","OUT_LOG","OUT_DOC")}
    try:
        scorer.VERSION=VERSION
        scorer.ELASTICITY=Path(elasticity_path)
        scorer.OUT_CSV=Path(out_csv)
        scorer.OUT_JSON=Path(out_json)
        scorer.OUT_LOG=Path(out_log)
        scorer.OUT_DOC=Path(out_doc)
        rc=scorer.main()
    finally:
        for k,v in old.items():
            setattr(scorer,k,v)
    if rc not in (None,0):
        raise RuntimeError("V8181_SCORER_FAILED:"+str(rc))

def main():
    subprocess.run(
        ["git","merge-base","--is-ancestor",V8180_COMMIT,"HEAD"],
        check=True,
    )

    audit=read_json(AUDIT_JSON)
    assert audit["version"]==V8180_VERSION
    assert audit["status"]=="AUDIT_ONLY_CURRENT_ACTIONABLE_PRICE_ELASTICITY"
    assert audit["policy_version"]==POLICY
    assert audit["target_tickers"]==TARGET_ORDER
    assert audit["recoverable_count"]==3
    assert audit["recoverable_tickers"]==TARGET_ORDER
    assert audit["classification"]=="ALL_RECOVERABLE"
    assert audit["next_step"]=="FREEZE_CURRENT_ACTIONABLE_PRICE_ELASTICITY_AND_SHADOW_V8181"
    assert audit["metric_contract"]["atr_substitution_allowed"] is False

    audit_rows=read_rows(AUDIT_CSV)
    if len(audit_rows)!=3:
        raise RuntimeError("V8181_AUDIT_ROW_COUNT_NOT_3")
    amap={ticker(r.get("ticker")):r for r in audit_rows}
    if set(amap)!=set(TARGETS):
        raise RuntimeError("V8181_AUDIT_TARGET_SET_MISMATCH")

    source_rows=[]
    source_fields=[
        "ticker","name","basis_date","basis_source",
        "window_start_date","window_end_date",
        "close_observation_count","daily_return_observation_count",
        "avg_daily_move_pct","classification","source",
        "last20_return_dates_json","last20_returns_json",
    ]

    for code in TARGET_ORDER:
        a=amap[code]
        expected=TARGETS[code]
        assert a["name"]==expected["name"]
        assert a["source"]=="KRX_OFFICIAL_STK_BYDD_TRD"
        assert a["classification"]=="OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE"
        assert a["recoverable"]=="TRUE"
        pct=num(a["avg_daily_move_pct"])
        if pct is None or abs(pct-expected["pct"])>1e-8:
            raise RuntimeError("V8181_ELASTICITY_VALUE_CHANGED:"+code+":"+str(pct))

        close_dates=json.loads(a.get("used_close_dates_json") or "[]")
        return_dates=json.loads(a.get("last20_return_dates_json") or "[]")
        returns=json.loads(a.get("last20_returns_json") or "[]")
        if len(close_dates)!=21:
            raise RuntimeError("V8181_CLOSE_EVIDENCE_NOT_21:"+code)
        if len(return_dates)!=20 or len(returns)!=20:
            raise RuntimeError("V8181_RETURN_EVIDENCE_NOT_20:"+code)

        source_rows.append({
            "ticker":code,
            "name":expected["name"],
            "basis_date":a["basis_date"],
            "basis_source":a["basis_source"],
            "window_start_date":close_dates[0],
            "window_end_date":close_dates[-1],
            "close_observation_count":"21",
            "daily_return_observation_count":"20",
            "avg_daily_move_pct":f"{expected['pct']:.4f}",
            "classification":a["classification"],
            "source":a["source"],
            "last20_return_dates_json":json.dumps(return_dates,ensure_ascii=False,separators=(",",":")),
            "last20_returns_json":json.dumps(returns,ensure_ascii=False,separators=(",",":")),
        })

    write_rows(SOURCE_OUT,source_rows,source_fields)

    prod_rows=read_rows(PROD_CACHE)
    if len(prod_rows)!=152:
        raise RuntimeError("V8181_PRODUCTION_CACHE_NOT_152:"+str(len(prod_rows)))
    prod_fields=list(prod_rows[0].keys())
    prod_map={ticker(r.get("ticker")):r for r in prod_rows if ticker(r.get("ticker"))}
    if len(prod_map)!=152:
        raise RuntimeError("V8181_PRODUCTION_DUPLICATE_TICKER")
    existing=sorted(set(prod_map)&set(TARGETS))
    if existing:
        raise RuntimeError("V8181_TARGET_ALREADY_IN_PRODUCTION:"+",".join(existing))

    candidate_map=dict(prod_map)
    for srow in source_rows:
        code=srow["ticker"]
        new_row={f:"" for f in prod_fields}
        new_row.update({
            "ticker":code,
            "name":srow["name"],
            "basis_date":srow["basis_date"],
            "window_start_date":srow["window_start_date"],
            "window_end_date":srow["window_end_date"],
            "close_observation_count":"21",
            "daily_return_observation_count":"20",
            "avg_daily_move_abs":"",
            "avg_daily_move_pct":srow["avg_daily_move_pct"],
            "source_status":"READY",
        })
        candidate_map[code]=new_row

    candidate_rows=[candidate_map[k] for k in sorted(candidate_map)]
    if len(candidate_rows)!=155:
        raise RuntimeError("V8181_CANDIDATE_CACHE_NOT_155")
    write_rows(CAND_OUT,candidate_rows,prod_fields)

    cand_map=row_map(CAND_OUT)
    changed_existing=[
        c for c in sorted(prod_map)
        if stable(prod_map[c])!=stable(cand_map[c])
    ]
    if changed_existing:
        raise RuntimeError(
            "V8181_EXISTING_CACHE_ROW_CHANGED:"+",".join(changed_existing[:20])
        )

    run_scorer(PROD_CACHE,BASE_CSV,BASE_JSON,BASE_LOG,BASE_DOC)
    run_scorer(CAND_OUT,SHADOW_CSV,SHADOW_JSON,SHADOW_LOG,SHADOW_DOC)

    base=row_map(BASE_CSV)
    shadow=row_map(SHADOW_CSV)
    bsum=read_json(BASE_JSON)
    ssum=read_json(SHADOW_JSON)

    if set(base)!=set(shadow) or len(base)!=157:
        raise RuntimeError("V8181_SCORER_UNIVERSE_DRIFT")

    b_ready=int(bsum.get("ready_count") or 0)
    s_ready=int(ssum.get("ready_count") or 0)
    b_limited=int(bsum.get("limited_count") or 0)
    s_limited=int(ssum.get("limited_count") or 0)
    b_blockers=blocker_count(base)
    s_blockers=blocker_count(shadow)

    if (b_ready,b_limited,b_blockers)!=(14,143,543):
        raise RuntimeError(
            f"V8181_BASELINE_DRIFT:{b_ready}:{b_limited}:{b_blockers}"
        )
    if (s_ready,s_limited,s_blockers)!=(17,140,540):
        raise RuntimeError(
            f"V8181_SHADOW_RESULT_BAD:{s_ready}:{s_limited}:{s_blockers}"
        )

    compare_rows=[]
    newly_ready=[]
    removed=[]
    for code in TARGET_ORDER:
        bm=split_missing(base[code].get("missing_components"))
        sm=split_missing(shadow[code].get("missing_components"))
        if base[code].get("score_status")!="LIMITED":
            raise RuntimeError("V8181_BASE_TARGET_NOT_LIMITED:"+code)
        if bm!=[MISSING_REASON]:
            raise RuntimeError("V8181_BASE_NOT_SINGLE_ELASTICITY:"+code+":"+"|".join(bm))
        if shadow[code].get("score_status")!="READY":
            raise RuntimeError("V8181_SHADOW_TARGET_NOT_READY:"+code)
        if MISSING_REASON in sm:
            raise RuntimeError("V8181_ELASTICITY_REASON_NOT_REMOVED:"+code)

        newly_ready.append(code)
        removed.append(code)
        compare_rows.append({
            "ticker":code,
            "name":TARGETS[code]["name"],
            "avg_daily_move_pct":f"{TARGETS[code]['pct']:.4f}",
            "baseline_status":base[code].get("score_status",""),
            "shadow_status":shadow[code].get("score_status",""),
            "baseline_missing_components":";".join(bm),
            "shadow_missing_components":";".join(sm),
            "baseline_score_total":base[code].get("score_total",""),
            "shadow_score_total":shadow[code].get("score_total",""),
        })

    non_target_changed=[
        c for c in sorted(set(base)-set(TARGETS))
        if stable(base[c])!=stable(shadow[c])
    ]
    if non_target_changed:
        raise RuntimeError(
            "V8181_NON_TARGET_SCORE_DRIFT:"+",".join(non_target_changed[:30])
        )

    compare_fields=list(compare_rows[0].keys())
    write_rows(COMPARE_OUT,compare_rows,compare_fields)

    summary={
        "version":VERSION,
        "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
        "status":"SOURCE_ONLY_FROZEN_SHADOW_PASS",
        "policy_version":POLICY,
        "v8180_version":V8180_VERSION,
        "v8180_result_commit":V8180_COMMIT,
        "source_frozen_count":3,
        "source_frozen_tickers":TARGET_ORDER,
        "frozen_avg_daily_move_pct":{
            c:TARGETS[c]["pct"] for c in TARGET_ORDER
        },
        "basis_date":audit["basis_date"],
        "basis_source":audit["basis_source"],
        "production_cache_row_count":152,
        "shadow_candidate_row_count":155,
        "cache_row_delta":3,
        "existing_elasticity_row_changed_count":0,
        "current_scorer_universe_count":157,
        "baseline_ready_count":14,
        "shadow_ready_count":17,
        "ready_delta":3,
        "baseline_limited_count":143,
        "shadow_limited_count":140,
        "limited_delta":-3,
        "baseline_blocker_occurrences":543,
        "shadow_blocker_occurrences":540,
        "blocker_occurrences_reduced_by":3,
        "newly_ready_count":3,
        "newly_ready_tickers":newly_ready,
        "elasticity_reason_removed_count":3,
        "elasticity_reason_removed_tickers":removed,
        "non_target_score_row_changed_count":0,
        "hard_guards":{
            "production_price_elasticity_cache_modified":False,
            "production_price_elasticity_metadata_modified":False,
            "production_price_elasticity_run_log_modified":False,
            "production_source_cache_modified":False,
            "production_financial_cache_modified":False,
            "production_ocf_cache_modified":False,
            "production_supply_source_modified":False,
            "production_api_modified":False,
            "production_score_written":False,
            "scoring_policy_modified":False,
            "atr_used_as_elasticity_substitute":False,
            "nonofficial_price_source_used":False,
            "non_target_score_row_changed":False,
        },
        "automatic_promotion":False,
        "next_step":"STAGE_NARROW_PRODUCTION_PRICE_ELASTICITY_PATCH_V8182",
    }

    SUMMARY_OUT.write_text(
        json.dumps(summary,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )
    LOG_OUT.write_text("\n".join([
        f"VERSION={VERSION}",
        "STATUS=SOURCE_ONLY_FROZEN_SHADOW_PASS",
        "SOURCE_FROZEN_COUNT=3",
        "SOURCE_FROZEN_TICKERS=006040,012630,078930",
        "FROZEN_VALUES=006040:0.9959,012630:2.5720,078930:2.2485",
        "PRODUCTION_CACHE_ROWS=152",
        "SHADOW_CANDIDATE_ROWS=155",
        "CACHE_ROW_DELTA=3",
        "EXISTING_ELASTICITY_ROW_CHANGED_COUNT=0",
        "CURRENT_SCORER_UNIVERSE=157",
        "BASELINE_READY=14",
        "SHADOW_READY=17",
        "READY_DELTA=3",
        "BASELINE_LIMITED=143",
        "SHADOW_LIMITED=140",
        "LIMITED_DELTA=-3",
        "BASELINE_BLOCKERS=543",
        "SHADOW_BLOCKERS=540",
        "BLOCKER_REDUCED_BY=3",
        "NEWLY_READY=3",
        "NON_TARGET_SCORE_ROW_CHANGED_COUNT=0",
        "PRODUCTION_PRICE_ELASTICITY_CACHE_MODIFIED=false",
        "PRODUCTION_DATA_MODIFIED=false",
        "PRODUCTION_SCORE_WRITTEN=false",
        "ATR_SUBSTITUTION_USED=false",
        "NONOFFICIAL_PRICE_SOURCE_USED=false",
        "AUTOMATIC_PROMOTION=false",
        "STATUS_OK=true",
        "NEXT_STEP=STAGE_NARROW_PRODUCTION_PRICE_ELASTICITY_PATCH_V8182",
    ])+"\n",encoding="utf-8")

    DOC_OUT.parent.mkdir(parents=True,exist_ok=True)
    DOC_OUT.write_text(
        "# V8.18.1 price-elasticity source freeze and shadow\n\n"
        "- Frozen official KRX elasticity sources:\n"
        "  - 동원산업 (006040): 0.9959%\n"
        "  - HDC (012630): 2.5720%\n"
        "  - GS (078930): 2.2485%\n"
        "- Production elasticity cache remains unchanged at 152 rows.\n"
        "- Shadow candidate contains 155 rows.\n"
        "- READY: 14 -> 17.\n"
        "- LIMITED: 143 -> 140.\n"
        "- Blockers: 543 -> 540.\n"
        "- Non-target score drift: 0.\n"
        "- No API, policy, or production score is modified.\n\n"
        "Next: STAGE_NARROW_PRODUCTION_PRICE_ELASTICITY_PATCH_V8182\n",
        encoding="utf-8"
    )

    print("V8181_PRICE_ELASTICITY_SHADOW=PASS")
    print("V8181_CACHE_ROWS=152->155")
    print("V8181_READY=14->17")
    print("V8181_LIMITED=143->140")
    print("V8181_BLOCKERS=543->540")
    print("V8181_NON_TARGET_SCORE_DRIFT=0")
    print("V8181_NEXT_STEP=STAGE_NARROW_PRODUCTION_PRICE_ELASTICITY_PATCH_V8182")

if __name__=="__main__":
    main()
