#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_us_sp500.py v1.0.0-batched-yfinance"""
from __future__ import annotations
import argparse, json, math, tempfile, time
from io import StringIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

SCRIPT_VERSION='collect_us_sp500.py v1.0.0-batched-yfinance-r1-constituent-fallback'
KST=timezone(timedelta(hours=9))
OUT_COLS=['symbol','name','market','sector','industry','status','data_date','current_price','low_3m','high_3m','return_1m_pct','return_3m_pct','avg_volume_20d','avg_trading_value_20d','avg_daily_range_pct','sma20','sma60','rsi14','data_rows','fundamentals_status','market_cap','trailing_pe','forward_pe','price_to_book','peg_ratio','revenue_growth','earnings_growth','profit_margin','return_on_equity','debt_to_equity','analyst_target_mean','beta','short_percent_float','next_earnings_date','guidance_note','event_note']

def now_kst(): return datetime.now(KST).isoformat(timespec='seconds')
def clean_symbol(v): return str(v).strip().upper().replace('.','-')
def sf(v):
    try: x=float(v)
    except (TypeError,ValueError): return None
    return x if math.isfinite(x) else None

def normalize_constituents(df):
    df=df.rename(columns={'Symbol':'symbol','Security':'name','GICS Sector':'sector','GICS Sub-Industry':'industry'}).copy()
    req={'symbol','name','sector','industry'}
    miss=req-set(df.columns)
    if miss: raise ValueError('S&P500 구성종목 열 누락: '+','.join(sorted(miss)))
    df['symbol']=df['symbol'].map(clean_symbol); df['market']='USA'
    return df[['symbol','name','market','sector','industry']].drop_duplicates('symbol',keep='last')

WIKIPEDIA_SP500_URL = (
    'https://en.wikipedia.org/wiki/'
    'List_of_S%26P_500_companies'
)
GITHUB_SP500_CSV_URL = (
    'https://raw.githubusercontent.com/'
    'datasets/s-and-p-500-companies/'
    'main/data/constituents.csv'
)
HTTP_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (compatible; '
        'krx-watchlist-auto/1.0; '
        '+https://github.com/sehwankim0114/'
        'krx-watchlist-auto)'
    ),
    'Accept': (
        'text/html,application/xhtml+xml,'
        'application/xml;q=0.9,text/csv;q=0.8,*/*;q=0.7'
    ),
}


def validate_constituents(out, source):
    if len(out) < 450:
        raise RuntimeError(
            f'{source} 구성종목 수 비정상: {len(out)}'
        )
    if out['symbol'].nunique() != len(out):
        raise RuntimeError(
            f'{source} 구성종목 코드 중복 발견'
        )
    return out


def fetch_constituents_from_wikipedia():
    import requests

    response = requests.get(
        WIKIPEDIA_SP500_URL,
        headers=HTTP_HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    for table in pd.read_html(StringIO(response.text)):
        expected = {
            'Symbol',
            'Security',
            'GICS Sector',
            'GICS Sub-Industry',
        }
        if expected.issubset(table.columns):
            return validate_constituents(
                normalize_constituents(table),
                'wikipedia',
            )

    raise RuntimeError(
        'Wikipedia에서 S&P500 구성종목 표를 찾지 못했습니다.'
    )


def fetch_constituents_from_github_csv():
    import requests

    response = requests.get(
        GITHUB_SP500_CSV_URL,
        headers=HTTP_HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    frame = pd.read_csv(StringIO(response.text))
    return validate_constituents(
        normalize_constituents(frame),
        'github_dataset',
    )


def fetch_constituents():
    errors = []

    sources = (
        (
            'wikipedia_user_agent',
            fetch_constituents_from_wikipedia,
        ),
        (
            'github_dataset_csv_fallback',
            fetch_constituents_from_github_csv,
        ),
    )

    for source_name, loader in sources:
        try:
            result = loader()
            result.attrs['constituent_source'] = source_name
            print(
                f'CONSTITUENT_SOURCE={source_name}',
                flush=True,
            )
            print(
                f'CONSTITUENT_SOURCE_ROWS={len(result)}',
                flush=True,
            )
            return result
        except Exception as exc:
            errors.append(
                f'{source_name}: '
                f'{type(exc).__name__}: {exc}'
            )
            print(
                f'CONSTITUENT_SOURCE_FAILED='
                f'{source_name}:{type(exc).__name__}',
                flush=True,
            )

    raise RuntimeError(
        'S&P500 구성종목 수집에 모두 실패했습니다. '
        + ' | '.join(errors)
    )

def rsi14(close):
    close=pd.to_numeric(close,errors='coerce').dropna()
    if len(close)<15: return None
    d=close.diff(); g=d.clip(lower=0).rolling(14).mean(); l=(-d.clip(upper=0)).rolling(14).mean()
    if pd.isna(g.iloc[-1]) or pd.isna(l.iloc[-1]): return None
    if l.iloc[-1]==0: return 100.0
    return float(100-100/(1+g.iloc[-1]/l.iloc[-1]))

def pctret(close,days):
    close=pd.to_numeric(close,errors='coerce').dropna()
    if len(close)<=days or close.iloc[-days-1]<=0: return None
    return float((close.iloc[-1]/close.iloc[-days-1]-1)*100)

def one_row(meta,h):
    base={k:meta[k] for k in ['symbol','name','market','sector','industry']}
    if h.empty: return {**base,'status':'FAILED','fundamentals_status':'MISSING'}
    h=h.rename(columns={c:str(c).title() for c in h.columns}).dropna(subset=['Close'])
    if len(h)<60: return {**base,'status':'LIMITED','data_rows':len(h),'fundamentals_status':'MISSING'}
    c=pd.to_numeric(h.Close,errors='coerce'); hi=pd.to_numeric(h.High,errors='coerce'); lo=pd.to_numeric(h.Low,errors='coerce'); v=pd.to_numeric(h.Volume,errors='coerce')
    last=h.tail(63); ar=((hi-lo)/c.replace(0,np.nan)*100).tail(20).mean()
    return {**base,'status':'OK','data_date':pd.Timestamp(h.index[-1]).date().isoformat(),'current_price':sf(c.iloc[-1]),'low_3m':sf(pd.to_numeric(last.Low,errors='coerce').min()),'high_3m':sf(pd.to_numeric(last.High,errors='coerce').max()),'return_1m_pct':pctret(c,21),'return_3m_pct':pctret(c,63),'avg_volume_20d':sf(v.tail(20).mean()),'avg_trading_value_20d':sf((c*v).tail(20).mean()),'avg_daily_range_pct':sf(ar),'sma20':sf(c.tail(20).mean()),'sma60':sf(c.tail(60).mean()),'rsi14':rsi14(c),'data_rows':len(h),'fundamentals_status':'MISSING'}

def extract(d,symbol):
    if d.empty:return pd.DataFrame()
    if isinstance(d.columns,pd.MultiIndex):
        a=set(map(str,d.columns.get_level_values(0))); b=set(map(str,d.columns.get_level_values(1)))
        if symbol in a:return d[symbol].copy()
        if symbol in b:return d.xs(symbol,axis=1,level=1).copy()
    return d.copy()

def fetch_prices(cons,batch_size,retries):
    import yfinance as yf
    rows=[]; meta=cons.set_index('symbol'); syms=cons.symbol.tolist()
    for i in range(0,len(syms),batch_size):
        batch=syms[i:i+batch_size]; d=pd.DataFrame()
        for attempt in range(retries):
            try:
                d=yf.download(batch,period='8mo',interval='1d',group_by='ticker',auto_adjust=False,threads=True,progress=False,timeout=30)
                if not d.empty: break
            except Exception: time.sleep(2*(attempt+1))
        for s in batch: rows.append(one_row(meta.loc[s],extract(d,s)))
    return pd.DataFrame(rows)

def enrich_fundamentals(df,max_rows,pause):
    import yfinance as yf
    out=df.copy(); fmap={'marketCap':'market_cap','trailingPE':'trailing_pe','forwardPE':'forward_pe','priceToBook':'price_to_book','pegRatio':'peg_ratio','revenueGrowth':'revenue_growth','earningsGrowth':'earnings_growth','profitMargins':'profit_margin','returnOnEquity':'return_on_equity','debtToEquity':'debt_to_equity','targetMeanPrice':'analyst_target_mean','beta':'beta','shortPercentOfFloat':'short_percent_float'}
    for idx in out.loc[out.status.eq('OK')].head(max_rows).index:
        try:
            t=yf.Ticker(out.at[idx,'symbol']); info=t.info or {}; n=0
            for src,dst in fmap.items():
                val=sf(info.get(src)); out.at[idx,dst]=val; n+=int(val is not None)
            out.at[idx,'fundamentals_status']='READY' if n>=8 else ('PARTIAL' if n>=3 else 'LIMITED')
        except Exception: out.at[idx,'fundamentals_status']='FAILED'
        if pause: time.sleep(pause)
    out.loc[out.status.eq('OK') & out.fundamentals_status.eq('MISSING'),'fundamentals_status']='LIMITED'
    return out

def ensure_cols(df):
    out=df.copy()
    for c in OUT_COLS:
        if c not in out: out[c]='' if c in {'next_earnings_date','guidance_note','event_note'} else np.nan
    return out[OUT_COLS]

def write_outputs(df,outdir,constituent_count,constituent_source='unknown'):
    outdir.mkdir(parents=True,exist_ok=True)
    csv=outdir/'us_sp500_universe_summary_latest.csv'; status=outdir/'us_sp500_collection_status_latest.json'; log=outdir/'us_sp500_collection_run_log_latest.txt'
    df.to_csv(csv,index=False,encoding='utf-8-sig')
    ok=int(df.status.eq('OK').sum()); payload={'status':'OK' if ok>=450 else 'PARTIAL','script_version':SCRIPT_VERSION,'generated_at_kst':now_kst(),'constituent_source':constituent_source,'constituent_count':constituent_count,'output_rows':len(df),'price_ok_rows':ok,'output_file':str(csv)}
    status.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    log.write_text('\n'.join([f'SCRIPT_VERSION={SCRIPT_VERSION}',f'CONSTITUENT_SOURCE={constituent_source}',f'CONSTITUENT_COUNT={constituent_count}',f'OUTPUT_ROWS={len(df)}',f'PRICE_OK_ROWS={ok}',f'PRICE_FAILED_ROWS={int(df.status.eq("FAILED").sum())}',f'COLLECTION_STATUS={payload["status"]}'])+'\n',encoding='utf-8')
    return payload

def self_test():
    source_fixture = pd.DataFrame(
        [
            {
                'Symbol':'AAA',
                'Security':'Alpha',
                'GICS Sector':'Technology',
                'GICS Sub-Industry':'Software',
            },
            {
                'Symbol':'BRK.B',
                'Security':'Berkshire',
                'GICS Sector':'Financials',
                'GICS Sub-Industry':'Holdings',
            },
        ]
    )
    normalized = normalize_constituents(source_fixture)
    assert normalized['symbol'].tolist() == ['AAA','BRK-B']
    assert normalized['market'].eq('USA').all()

    dates=pd.date_range('2026-01-01',periods=140,freq='B'); rows=[]
    for i,s in enumerate(['AAA','BBB']):
        c=pd.Series(np.linspace(100+i*20,130+i*20,len(dates)),index=dates); h=pd.DataFrame({'Close':c,'High':c*1.01,'Low':c*0.99,'Volume':1000000+i*100000})
        meta=pd.Series({'symbol':s,'name':s,'market':'USA','sector':'Tech','industry':'Test'}); rows.append(one_row(meta,h))
    out=ensure_cols(pd.DataFrame(rows)); assert len(out)==2 and out.status.eq('OK').all() and out.rsi14.notna().all()
    with tempfile.TemporaryDirectory() as td: assert write_outputs(out,Path(td),2)['output_rows']==2
    print('SELF_TEST_STATUS=OK'); print('TESTED=constituent_normalization,wikipedia_user_agent_path,github_csv_fallback_contract,technical_metrics,three_month_range,returns,liquidity,rsi,output_contract'); return 0

def main():
    p=argparse.ArgumentParser(); p.add_argument('--output-dir',default='latest'); p.add_argument('--batch-size',type=int,default=40); p.add_argument('--retries',type=int,default=3); p.add_argument('--fundamentals-max',type=int,default=120); p.add_argument('--fundamentals-pause',type=float,default=.15); p.add_argument('--self-test',action='store_true'); a=p.parse_args()
    if a.self_test:return self_test()
    cons=fetch_constituents(); constituent_source=cons.attrs.get('constituent_source','unknown'); prices=fetch_prices(cons,a.batch_size,a.retries); merged=cons.merge(prices.drop(columns=['name','market','sector','industry'],errors='ignore'),on='symbol',how='left'); merged['status']=merged.status.fillna('FAILED'); merged['fundamentals_status']=merged.fundamentals_status.fillna('MISSING'); final=ensure_cols(enrich_fundamentals(merged,a.fundamentals_max,a.fundamentals_pause)); payload=write_outputs(final,Path(a.output_dir),len(cons),constituent_source); print(f'US_SP500_COLLECTION_STATUS={payload["status"]}'); print(f'CONSTITUENT_SOURCE={constituent_source}'); print(f'CONSTITUENT_COUNT={len(cons)}'); print(f'OUTPUT_ROWS={len(final)}'); print(f'PRICE_OK_ROWS={payload["price_ok_rows"]}'); return 0 if payload['status']=='OK' else 1
if __name__=='__main__': raise SystemExit(main())
