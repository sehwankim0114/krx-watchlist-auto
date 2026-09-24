import csv, json, math, os, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import collect_universe as universe
import investment_score_dry_run_v882 as scorer

VERSION="2026-09-24-v8.18.6A-current-basis-rebase-multi-elasticity-shadow"
POLICY="2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
ROOT=Path('.')
KST=ZoneInfo('Asia/Seoul')
REASON='하루평균 절대등락률:MISSING_ELASTICITY'

OLDJ=ROOT/'latest/investment_score_price_elasticity_multi_audit_v8185_summary_latest.json'
OLDC=ROOT/'latest/investment_score_price_elasticity_multi_audit_v8185.csv'
MAN=ROOT/'api/two_table_v1/manifest.json'
PROD=ROOT/'latest/investment_score_price_elasticity_20d_latest.csv'
SRCLOG=ROOT/'latest/investment_score_source_run_log_latest.txt'
FINLOG=ROOT/'latest/financial_valuation_run_log_latest.txt'

SOURCE=ROOT/'latest/investment_score_price_elasticity_multi_source_v8186a.csv'
CAND=ROOT/'latest/investment_score_price_elasticity_candidate_v8186a.csv'
CMP=ROOT/'latest/investment_score_price_elasticity_multi_shadow_v8186a.csv'
SUM=ROOT/'latest/investment_score_price_elasticity_multi_shadow_v8186a_summary_latest.json'
LOG=ROOT/'latest/investment_score_price_elasticity_multi_shadow_v8186a_run_log_latest.txt'
DOC=ROOT/'docs/investment_score_price_elasticity_multi_shadow_v8186a.md'

def tick(v):
    s=''.join(c for c in str(v or '') if c.isdigit())
    return s.zfill(6) if s else ''
def num(v):
    try:
        s=str(v or '').strip().replace(',','')
        if s in {'','-','None','null','nan','NaN'}: return None
        x=float(s); return x if math.isfinite(x) else None
    except: return None
def rj(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def kv(p):
    out={}
    for line in Path(p).read_text(encoding='utf-8-sig').splitlines():
        if '=' in line:
            k,v=line.split('=',1); out[k.strip()]=v.strip()
    return out
def rows(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def wrows(p,rs,fields):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    with Path(p).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n'); w.writeheader(); w.writerows(rs)
def rmap(p): return {tick(r.get('ticker')):r for r in rows(p) if tick(r.get('ticker'))}
def stable(r): return json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def missing(r): return [x for x in str(r.get('missing_components') or '').split(';') if x]
def blockers(m): return sum(int(r.get('missing_component_count') or 0) for r in m.values())
def pdt(v): return datetime.fromisoformat(str(v).replace('Z','+00:00'))
def calc(series):
    o=sorted(series)
    if len(o)<21: return None,[],[],o
    ret=[]; dates=[]
    for i in range(1,len(o)):
        if o[i-1][1]>0 and o[i][1]>0:
            ret.append(o[i][1]/o[i-1][1]-1); dates.append(o[i][0])
    if len(ret)<20: return None,ret,dates,o
    pct=round(sum(abs(x) for x in ret[-20:])/20*100,4)
    return pct,ret,dates,o
def run_score(elasticity,tag):
    oc=Path(f'/tmp/{tag}.csv'); oj=Path(f'/tmp/{tag}.json'); ol=Path(f'/tmp/{tag}.log'); od=Path(f'/tmp/{tag}.md')
    old={k:getattr(scorer,k) for k in ('VERSION','ELASTICITY','OUT_CSV','OUT_JSON','OUT_LOG','OUT_DOC')}
    try:
        scorer.VERSION=VERSION; scorer.ELASTICITY=Path(elasticity)
        scorer.OUT_CSV=oc; scorer.OUT_JSON=oj; scorer.OUT_LOG=ol; scorer.OUT_DOC=od
        rc=scorer.main()
    finally:
        for k,v in old.items(): setattr(scorer,k,v)
    if rc not in (None,0): raise RuntimeError('SCORER_FAILED:'+str(rc))
    return rmap(oc), rj(oj)

old=rj(OLDJ); mf=rj(MAN); src=kv(SRCLOG); fin=kv(FINLOG)
assert old['version']=='2026-09-23-v8.18.5-top-multi-price-elasticity-official-audit'
assert old['status']=='AUDIT_ONLY_TOP_MULTI_PRICE_ELASTICITY'
assert old['recoverable_count']==100 and old['insufficient_count']==0
targets=sorted(old['target_tickers']); target_set=set(targets); assert len(target_set)==100
old_names={tick(r['ticker']):r.get('name','') for r in rows(OLDC)}; assert set(old_names)==target_set

assert mf['release_stage']=='PRODUCTION' and mf['safe_to_analyze_as_latest'] is True
universe_count=int((mf.get('sector_rs_source') or {}).get('unique_ticker_count') or 0); assert universe_count>0
assert src.get('SOURCE_RETENTION_GUARD')=='PASS'
assert int(src.get('OUTPUT_ROWS') or 0)>0 and int(fin.get('CACHE_OUTPUT_ROWS') or 0)>0
assert pdt(src['RUN_AT_KST'])>=pdt(fin['RUN_AT_KST'])
basis=str(mf['basis_date']); basis_d=datetime.strptime(basis,'%Y-%m-%d').date()

prod_rows=rows(PROD); assert len(prod_rows)==155
fields=list(prod_rows[0]); prod_map={tick(r['ticker']):r for r in prod_rows}; assert len(prod_map)==155
assert not (target_set & set(prod_map))

key=os.environ['KRX_AUTH_KEY'].strip(); assert key
sessions=[]; series={c:[] for c in targets}; req=0; fails=[]
cur=basis_d; earliest=basis_d-timedelta(days=70)
while cur>=earliest and len(sessions)<30:
    if cur.weekday()<5:
        d=cur.strftime('%Y%m%d'); logs=[]
        try:
            raw=universe.request_krx_openapi(universe.OPENAPI_STOCK_URLS['KOSPI'],key,d,logs,'V8186A_KOSPI')
            req+=1; norm=universe.normalize_stock_rows(raw,'KOSPI',d,logs)
        except Exception:
            req+=1; fails.append(cur.isoformat()); norm=None
        if norm is not None and not norm.empty:
            sessions.append(cur.isoformat()); cmap={}
            for _,r in norm.iterrows():
                c=tick(r.get('ticker'))
                if c in target_set:
                    x=num(r.get('close'))
                    if x and x>0: cmap[c]=x
            for c,x in cmap.items(): series[c].append((cur.isoformat(),x))
        time.sleep(0.08)
    cur-=timedelta(days=1)
assert len(set(sessions))>=21 and not fails

source_rows=[]; cand_map=dict(prod_map); values={}; insufficient=[]
sfields=['ticker','name','basis_date','basis_source','window_start_date','window_end_date','close_observation_count','daily_return_observation_count','avg_daily_move_pct','classification','source','last20_return_dates_json','last20_returns_json']
for c in targets:
    pct,ret,dates,o=calc(sorted({d:x for d,x in series[c]}.items()))
    if pct is None: insufficient.append(c); continue
    values[c]=pct; used=o[-21:]
    source_rows.append({'ticker':c,'name':old_names[c],'basis_date':basis,'basis_source':'CURRENT_PRODUCTION_MANIFEST_BASIS_DATE','window_start_date':used[0][0],'window_end_date':used[-1][0],'close_observation_count':'21','daily_return_observation_count':'20','avg_daily_move_pct':f'{pct:.4f}','classification':'OFFICIAL_KRX_PRICE_ELASTICITY_RECOVERABLE_CURRENT_BASIS','source':'KRX_OFFICIAL_STK_BYDD_TRD','last20_return_dates_json':json.dumps(dates[-20:],ensure_ascii=False,separators=(',',':')),'last20_returns_json':json.dumps([round(x,10) for x in ret[-20:]],ensure_ascii=False,separators=(',',':'))})
    nr={f:'' for f in fields}; nr.update({'ticker':c,'name':old_names[c],'basis_date':basis,'window_start_date':used[0][0],'window_end_date':used[-1][0],'close_observation_count':'21','daily_return_observation_count':'20','avg_daily_move_abs':'','avg_daily_move_pct':f'{pct:.4f}','source_status':'READY'}); cand_map[c]=nr
if insufficient: raise RuntimeError('CURRENT_BASIS_INSUFFICIENT:'+','.join(insufficient[:30]))
assert len(source_rows)==100
wrows(SOURCE,source_rows,sfields)
cand_rows=[cand_map[c] for c in sorted(cand_map)]; assert len(cand_rows)==255; wrows(CAND,cand_rows,fields)
cm=rmap(CAND); assert set(cm)-set(prod_map)==target_set
assert all(stable(prod_map[c])==stable(cm[c]) for c in prod_map)

base,bs=run_score(PROD,'v8186a_base'); shadow,ss=run_score(CAND,'v8186a_shadow')
assert set(base)==set(shadow) and len(base)==universe_count
br=int(bs['ready_count']); sr=int(ss['ready_count']); bl=int(bs['limited_count']); sl=int(ss['limited_count']); bb=blockers(base); sb=blockers(shadow)

active=sorted(target_set & set(base)); inactive=sorted(target_set-set(base))
eligible=sorted(c for c in active if REASON in missing(base[c]))
single=sorted(c for c in eligible if len(missing(base[c]))==1)
multi=sorted(set(eligible)-set(single))
no_reason=sorted(set(active)-set(eligible))
changed=sorted(c for c in base if stable(base[c])!=stable(shadow[c]))
assert changed==eligible
for c in eligible:
    bm=missing(base[c]); sm=missing(shadow[c]); assert REASON in bm and REASON not in sm and len(sm)==len(bm)-1
newly=sorted(c for c in eligible if base[c].get('score_status')!='READY' and shadow[c].get('score_status')=='READY')
lost=sorted(c for c in base if base[c].get('score_status')=='READY' and shadow[c].get('score_status')!='READY')
assert not lost and newly==single
assert bb-sb==len(eligible)
assert sr-br==len(newly) and bl-sl==len(newly)
external=sorted(c for c,r in shadow.items() if REASON in missing(r) and c not in target_set)

cmp=[]
for c in eligible:
    cmp.append({'ticker':c,'name':base[c].get('name',''),'avg_daily_move_pct':f'{values[c]:.4f}','baseline_status':base[c].get('score_status',''),'shadow_status':shadow[c].get('score_status',''),'baseline_missing_component_count':base[c].get('missing_component_count',''),'shadow_missing_component_count':shadow[c].get('missing_component_count',''),'baseline_missing_components':';'.join(missing(base[c])),'shadow_missing_components':';'.join(missing(shadow[c]))})
wrows(CMP,cmp,list(cmp[0]) if cmp else ['ticker','name','avg_daily_move_pct','baseline_status','shadow_status','baseline_missing_component_count','shadow_missing_component_count','baseline_missing_components','shadow_missing_components'])

summary={'version':VERSION,'generated_at_kst':datetime.now(KST).isoformat(timespec='seconds'),'status':'CURRENT_BASIS_REBASE_SHADOW_PASS','policy_version':POLICY,'v8185_result_commit':'51637a494be1fcd786b357f9fd9035f6ca9edf77','current_production':{'basis_date':basis,'manifest_source_commit':mf.get('source_commit'),'scorer_universe_count':universe_count,'financial_run_at_kst':fin.get('RUN_AT_KST'),'financial_cache_rows':int(fin.get('CACHE_OUTPUT_ROWS') or 0),'source_run_at_kst':src.get('RUN_AT_KST'),'source_cache_rows':int(src.get('OUTPUT_ROWS') or 0),'source_retention_guard':src.get('SOURCE_RETENTION_GUARD'),'production_elasticity_rows':155},'official_refresh':{'target_count':100,'current_basis_recoverable_count':100,'official_request_count':req,'official_session_count':len(set(sessions)),'transport_or_parse_fail_count':0,'basis_date':basis},'candidate':{'production_row_count':155,'candidate_row_count':255,'row_delta':100,'existing_row_changed_count':0,'added_ticker_count':100,'added_tickers':targets},'scorer_regression':{'universe_count':universe_count,'baseline_ready_count':br,'shadow_ready_count':sr,'ready_delta':sr-br,'baseline_limited_count':bl,'shadow_limited_count':sl,'limited_delta':sl-bl,'baseline_blocker_occurrences':bb,'shadow_blocker_occurrences':sb,'blocker_occurrences_reduced_by':bb-sb,'active_old_target_count':len(active),'inactive_old_target_count':len(inactive),'currently_elasticity_blocked_old_target_count':len(eligible),'currently_single_elasticity_old_target_count':len(single),'currently_multi_elasticity_old_target_count':len(multi),'old_targets_no_longer_elasticity_blocked_count':len(no_reason),'changed_score_row_count':len(changed),'changed_score_tickers':changed,'newly_ready_count':len(newly),'newly_ready_tickers':newly,'lost_ready_count':0,'non_target_score_row_changed_count':0,'remaining_external_elasticity_blocker_count':len(external),'remaining_external_elasticity_blocker_tickers':external},'hard_guards':{'production_price_elasticity_cache_modified':False,'production_source_cache_modified':False,'production_financial_cache_modified':False,'production_api_modified':False,'production_score_written':False,'scoring_policy_modified':False,'atr_used_as_elasticity_substitute':False,'nonofficial_price_source_used':False,'non_target_score_row_changed':False,'source_value_imputed':False},'automatic_promotion':False,'next_step':'STAGE_CURRENT_BASIS_BULK_PRICE_ELASTICITY_PATCH_V8187A'}
SUM.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
LOG.write_text('\n'.join([f'VERSION={VERSION}','STATUS=CURRENT_BASIS_REBASE_SHADOW_PASS',f'CURRENT_BASIS_DATE={basis}',f'SCORER_UNIVERSE={universe_count}',f'BASELINE_READY={br}',f'SHADOW_READY={sr}',f'BASELINE_LIMITED={bl}',f'SHADOW_LIMITED={sl}',f'BASELINE_BLOCKERS={bb}',f'SHADOW_BLOCKERS={sb}',f'BLOCKER_REDUCED_BY={bb-sb}',f'ACTIVE_OLD_TARGETS={len(active)}',f'ELASTICITY_BLOCKED_OLD_TARGETS={len(eligible)}',f'SINGLE_ELASTICITY_OLD_TARGETS={len(single)}',f'MULTI_ELASTICITY_OLD_TARGETS={len(multi)}',f'NEWLY_READY={len(newly)}','LOST_READY=0','NON_TARGET_SCORE_ROW_CHANGED_COUNT=0',f'REMAINING_EXTERNAL_ELASTICITY_BLOCKERS={len(external)}','PRODUCTION_DATA_MODIFIED=false','AUTOMATIC_PROMOTION=false','STATUS_OK=true','NEXT_STEP=STAGE_CURRENT_BASIS_BULK_PRICE_ELASTICITY_PATCH_V8187A'])+'\n',encoding='utf-8')
DOC.parent.mkdir(parents=True,exist_ok=True)
DOC.write_text(f'# V8.18.6A current-basis rebase shadow\n\n- Current production basis: {basis}.\n- Current scorer universe: {universe_count}.\n- Re-fetched all 100 prior audited targets from official KRX.\n- Elasticity cache remains 155 rows; candidate is 255 rows.\n- READY: {br} -> {sr}.\n- LIMITED: {bl} -> {sl}.\n- Blockers: {bb} -> {sb}.\n- Eligible old targets: {len(eligible)}.\n- Newly READY: {len(newly)}.\n- External elasticity blockers remaining: {len(external)}.\n- Non-target drift 0; lost READY 0.\n\nNext: STAGE_CURRENT_BASIS_BULK_PRICE_ELASTICITY_PATCH_V8187A\n',encoding='utf-8')
print('V8186A_CURRENT_BASIS_REBASE_SHADOW=PASS')
print(f'V8186A_SCORER_UNIVERSE={universe_count}')
print(f'V8186A_BASELINE_BLOCKERS={bb}')
print(f'V8186A_SHADOW_BLOCKERS={sb}')
print(f'V8186A_ELASTICITY_BLOCKED_OLD_TARGETS={len(eligible)}')
print(f'V8186A_NEWLY_READY={len(newly)}')
print(f'V8186A_EXTERNAL_ELASTICITY_BLOCKERS={len(external)}')
