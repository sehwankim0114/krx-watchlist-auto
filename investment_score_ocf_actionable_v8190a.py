#!/usr/bin/env python3
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

VERSION="2026-09-24-v8.19.0A-current-actionable-ocf-single-blocker-audit"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8189A_VERSION="2026-09-24-v8.18.9A-post-bulk-elasticity-dynamic-blocker-reaudit"
V8189A_COMMIT="729b7d22e9ffa3bcfe90eb6f38dde8d7821b5b90"
OCF_CONTRACT_VERSION="2026-09-12-v8.7.4-audited-operating-cash-flow-source"

IFRS_OCF_ID="ifrs-full_CashFlowsFromUsedInOperatingActivities"
DART_URL="https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
ROOT=Path(".")
KST=ZoneInfo("Asia/Seoul")

BLOCKERS=ROOT/"latest/investment_score_current_blockers_v8189a.csv"
PRIOR=ROOT/"latest/investment_score_current_blockers_v8189a_summary_latest.json"
SOURCE=ROOT/"latest/investment_score_source_cache_latest.csv"
FIN=ROOT/"latest/financial_valuation_cache_latest.csv"
PROD_OCF=ROOT/"latest/investment_score_ocf_source_latest.csv"
PROD_META=ROOT/"latest/investment_score_ocf_source_latest.json"

OUT_CSV=ROOT/"latest/investment_score_ocf_actionable_v8190a.csv"
OUT_JSON=ROOT/"latest/investment_score_ocf_actionable_v8190a_summary_latest.json"
OUT_LOG=ROOT/"latest/investment_score_ocf_actionable_v8190a_run_log_latest.txt"
OUT_DOC=ROOT/"docs/investment_score_ocf_actionable_v8190a.md"

EXPECTED={
    "000100":"유한양행",
    "005850":"에스엘",
    "006110":"삼아알미늄",
    "013870":"지엠비코리아",
    "014710":"사조씨푸드",
    "120110":"코오롱인더",
    "271560":"오리온",
}

def ticker(v):
    s=re.sub(r"[^0-9]","",str(v or "").strip())
    return s.zfill(6) if s else ""

def norm(v):
    return str(v or "").strip()

def num(v):
    s=norm(v).replace(",","")
    if s in {"","-","None","null","nan","NaN"}:
        return None
    neg=s.startswith("(") and s.endswith(")")
    if neg:
        s=s[1:-1]
    s=re.sub(r"[^0-9eE+\-.]","",s)
    if s in {"","-","+","."}:
        return None
    try:
        x=float(s)
    except ValueError:
        return None
    return -abs(x) if neg else x

def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def rows(p):
    with Path(p).open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def rmap(p):
    return {ticker(r.get("ticker")):r for r in rows(p) if ticker(r.get("ticker"))}

def request(api_key,corp_code,fs_div):
    params=urllib.parse.urlencode({
        "crtfc_key":api_key,
        "corp_code":corp_code,
        "bsns_year":"2025",
        "reprt_code":"11011",
        "fs_div":fs_div,
    })
    req=urllib.request.Request(
        f"{DART_URL}?{params}",
        headers={
            "User-Agent":"krx-watchlist-v8190a-ocf-audit",
            "Accept":"application/json",
            "Cache-Control":"no-cache",
        },
    )
    errors=[]
    for attempt in range(1,4):
        try:
            with urllib.request.urlopen(req,timeout=30) as response:
                payload=json.loads(response.read(12_000_000).decode("utf-8"))
            return payload,errors
        except Exception as exc:
            errors.append(f"{attempt}:{type(exc).__name__}:{exc}")
            if attempt<3:
                time.sleep(attempt)
    return None,errors

def audit_one(api_key,code,corp_code):
    attempts=[]
    for fs_div in ("CFS","OFS"):
        payload,transport_errors=request(api_key,corp_code,fs_div)
        if payload is None:
            attempts.append({
                "fs_div":fs_div,
                "transport_status":"ERROR",
                "transport_errors":transport_errors,
                "dart_status":"",
                "dart_message":"",
                "exact_match_count":0,
                "unique_numeric_values":[],
                "account_names":[],
            })
            continue

        status=norm(payload.get("status"))
        message=norm(payload.get("message"))
        items=payload.get("list")
        if not isinstance(items,list):
            items=[]

        matches=[
            item for item in items
            if norm(item.get("sj_div"))=="CF"
            and norm(item.get("account_id"))==IFRS_OCF_ID
        ]
        values=sorted({
            num(item.get("thstrm_amount"))
            for item in matches
            if num(item.get("thstrm_amount")) is not None
        })
        names=sorted({
            norm(item.get("account_nm"))
            for item in matches
            if norm(item.get("account_nm"))
        })

        attempts.append({
            "fs_div":fs_div,
            "transport_status":"OK",
            "transport_errors":transport_errors,
            "dart_status":status,
            "dart_message":message,
            "exact_match_count":len(matches),
            "unique_numeric_values":values,
            "account_names":names,
        })

        if status!="000":
            continue

        if len(values)==1:
            return {
                "classification":"RECOVERABLE_EXACT_OCF_MARGIN_INPUT",
                "source_status":"READY",
                "source_fs_div":fs_div,
                "amount":values[0],
                "account_names":names,
                "attempts":attempts,
            }

        if len(values)>1:
            return {
                "classification":"EXACT_OCF_VALUE_CONFLICT",
                "source_status":"LIMITED",
                "source_fs_div":fs_div,
                "amount":None,
                "account_names":names,
                "attempts":attempts,
            }

    official_success=any(
        a["transport_status"]=="OK" and a["dart_status"]=="000"
        for a in attempts
    )
    return {
        "classification":"NO_APPROVED_EXACT_OCF" if official_success else "OFFICIAL_QUERY_INCOMPLETE",
        "source_status":"LIMITED",
        "source_fs_div":"",
        "amount":None,
        "account_names":[],
        "attempts":attempts,
    }

api_key=os.environ.get("DART_API_KEY","").strip()
if not api_key:
    raise RuntimeError("V8190A_DART_API_KEY_MISSING")

prior=read_json(PRIOR)
meta=read_json(PROD_META)

assert prior["version"]==V8189A_VERSION
assert prior["status"]=="AUDIT_ONLY_DYNAMIC_POST_BULK_ELASTICITY_BLOCKERS"
assert prior["policy_version"]==POLICY
assert prior["selection_mode"]=="ACTIONABLE_SINGLE_BLOCKER"
assert prior["selected_source_group"]=="OCF_AND_REVENUE_SOURCE"
assert prior["selected_ticker_count"]==7
assert set(prior["selected_tickers"])==set(EXPECTED)
assert prior["next_step"]=="AUDIT_CURRENT_ACTIONABLE_SINGLE_BLOCKER_GROUP_V8190A"

assert meta["version"]==OCF_CONTRACT_VERSION
assert meta["account_id_policy"]=="EXACT_ONLY:"+IFRS_OCF_ID
assert meta["production_unique_tickers"]==149

blocker_rows=[
    r for r in rows(BLOCKERS)
    if ticker(r.get("ticker")) in EXPECTED
]
assert len(blocker_rows)==7
for r in blocker_rows:
    assert r["source_group"]=="OCF_AND_REVENUE_SOURCE"
    assert r["single_blocker_ticker"]=="TRUE"
    assert r["recovery_status"]=="ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
    assert r["blocker_reason"]=="영업현금흐름:MISSING_OCF_MARGIN_INPUT"
    assert int(r["missing_component_count"])==1

src=rmap(SOURCE)
fin=rmap(FIN)
ocf=rmap(PROD_OCF)

assert not (set(EXPECTED)&set(ocf))

results=[]
counts=Counter()
recoverable=[]
no_exact=[]
incomplete=[]
conflict=[]

for code in sorted(EXPECTED):
    if code not in src or code not in fin:
        raise RuntimeError("V8190A_REQUIRED_SOURCE_ROW_MISSING:"+code)

    s=src[code]
    f=fin[code]

    revenue=num(s.get("annual_revenue_y0"))
    if revenue is None or revenue<=0:
        raise RuntimeError("V8190A_ANNUAL_REVENUE_INPUT_MISSING:"+code)

    if s.get("annual_source_year")!="2025":
        raise RuntimeError("V8190A_ANNUAL_SOURCE_YEAR_DRIFT:"+code)

    corp_code=norm(f.get("corp_code"))
    if not re.fullmatch(r"\d{8}",corp_code):
        raise RuntimeError("V8190A_CORP_CODE_INVALID:"+code)

    if f.get("corp_identity_status") not in {"MATCH","MATCH_NORMALIZED"}:
        raise RuntimeError("V8190A_CORP_IDENTITY_NOT_APPROVED:"+code)

    if norm(f.get("name"))!=EXPECTED[code]:
        raise RuntimeError("V8190A_TARGET_NAME_DRIFT:"+code)

    result=audit_one(api_key,code,corp_code)
    cls=result["classification"]
    counts[cls]+=1

    if cls=="RECOVERABLE_EXACT_OCF_MARGIN_INPUT":
        recoverable.append(code)
    elif cls=="NO_APPROVED_EXACT_OCF":
        no_exact.append(code)
    elif cls=="OFFICIAL_QUERY_INCOMPLETE":
        incomplete.append(code)
    elif cls=="EXACT_OCF_VALUE_CONFLICT":
        conflict.append(code)

    amount=result["amount"]
    margin=None if amount is None else round(amount/revenue*100.0,6)

    results.append({
        "ticker":code,
        "name":EXPECTED[code],
        "corp_code":corp_code,
        "corp_identity_status":f.get("corp_identity_status",""),
        "annual_source_year":"2025",
        "annual_revenue_y0":revenue,
        "report_code":"11011",
        "account_id":IFRS_OCF_ID,
        "classification":cls,
        "source_status":result["source_status"],
        "source_fs_div":result["source_fs_div"],
        "operating_cash_flow_annual":"" if amount is None else amount,
        "ocf_margin_pct_if_promoted":"" if margin is None else margin,
        "account_names_json":json.dumps(
            result["account_names"],ensure_ascii=False,separators=(",",":")
        ),
        "official_attempts_json":json.dumps(
            result["attempts"],ensure_ascii=False,separators=(",",":")
        ),
    })

if incomplete:
    raise RuntimeError("V8190A_OFFICIAL_QUERY_INCOMPLETE:"+",".join(incomplete))
if conflict:
    raise RuntimeError("V8190A_EXACT_OCF_VALUE_CONFLICT:"+",".join(conflict))

OUT_CSV.parent.mkdir(parents=True,exist_ok=True)
with OUT_CSV.open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(results[0].keys()),lineterminator="\n")
    w.writeheader()
    w.writerows(results)

next_step=(
    "FREEZE_RECOVERABLE_OCF_AND_SHADOW_CURRENT_SCORE_V8191A"
    if recoverable
    else "POST_OCF_EXHAUSTION_DYNAMIC_BLOCKER_REAUDIT_V8191A"
)

summary={
    "version":VERSION,
    "generated_at_kst":datetime.now(KST).isoformat(timespec="seconds"),
    "status":"AUDIT_ONLY_CURRENT_ACTIONABLE_OCF_SINGLE_BLOCKERS",
    "policy_version":POLICY,
    "v8189a_version":V8189A_VERSION,
    "v8189a_result_commit":V8189A_COMMIT,
    "ocf_contract_version":OCF_CONTRACT_VERSION,
    "target_count":7,
    "target_tickers":sorted(EXPECTED),
    "annual_revenue_input_ready_count":7,
    "classification_counts":dict(counts),
    "recoverable_count":len(recoverable),
    "recoverable_tickers":sorted(recoverable),
    "no_approved_exact_count":len(no_exact),
    "no_approved_exact_tickers":sorted(no_exact),
    "official_query_incomplete_count":0,
    "conflict_count":0,
    "hard_guards":{
        "production_ocf_cache_modified":False,
        "production_source_cache_modified":False,
        "production_financial_cache_modified":False,
        "production_elasticity_cache_modified":False,
        "production_api_modified":False,
        "production_score_written":False,
        "scoring_policy_modified":False,
        "alternate_ocf_account_id_used":False,
        "source_value_imputed":False,
        "corp_identity_inferred":False,
    },
    "automatic_promotion":False,
    "next_step":next_step,
}

OUT_JSON.write_text(
    json.dumps(summary,ensure_ascii=False,indent=2)+"\n",
    encoding="utf-8"
)

OUT_LOG.write_text("\n".join([
    f"VERSION={VERSION}",
    "STATUS=AUDIT_ONLY_CURRENT_ACTIONABLE_OCF_SINGLE_BLOCKERS",
    "TARGET_COUNT=7",
    "ANNUAL_REVENUE_INPUT_READY=7",
    f"RECOVERABLE={len(recoverable)}",
    f"NO_APPROVED_EXACT={len(no_exact)}",
    "OFFICIAL_QUERY_INCOMPLETE=0",
    "CONFLICT=0",
    "ALTERNATE_OCF_ACCOUNT_ID_USED=false",
    "SOURCE_VALUE_IMPUTED=false",
    "PRODUCTION_MODIFIED=false",
    "AUTOMATIC_PROMOTION=false",
    "STATUS_OK=true",
    f"NEXT_STEP={next_step}",
])+"\n",encoding="utf-8")

OUT_DOC.parent.mkdir(parents=True,exist_ok=True)
OUT_DOC.write_text(
    "# V8.19.0A current actionable OCF single-blocker audit\n\n"
    "- Targets: 7 current single-blocker tickers selected by V8.18.9A.\n"
    "- annual_revenue_y0 is present and positive for all 7 targets.\n"
    f"- Accepted OCF account only: `{IFRS_OCF_ID}`.\n"
    "- OpenDART 2025 annual report, CFS then OFS.\n"
    "- No alternate account IDs, alias inference, or source imputation.\n"
    "- Audit-only; production OCF cache is unchanged.\n\n"
    f"- Recoverable: {len(recoverable)}\n"
    f"- No approved exact OCF: {len(no_exact)}\n"
    f"- Next: `{next_step}`\n",
    encoding="utf-8"
)

print("V8190A_OCF_AUDIT=PASS")
print(f"V8190A_RECOVERABLE={len(recoverable)}")
print(f"V8190A_NO_APPROVED_EXACT={len(no_exact)}")
print(f"V8190A_NEXT_STEP={next_step}")
