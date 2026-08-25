import pandas as pd
import streamlit as st
import yfinance as yf

SPOT='XAUUSD=X'
FUTURES='GC=F'

@st.cache_data(ttl=120, show_spinner=False)
def _download(symbol, interval, period):
    try:
        return yf.download(symbol, interval=interval, period=period, progress=False,
                           auto_adjust=False, threads=False, timeout=8)
    except Exception:
        return pd.DataFrame()

def clean(df):
    if df is None or len(df)==0:
        return pd.DataFrame()
    df=df.copy()
    if isinstance(df.columns,pd.MultiIndex):
        df.columns=[c[0] if isinstance(c,tuple) else c for c in df.columns]
    df.columns=[str(c).strip().title().replace(' ','_') for c in df.columns]
    needed=['Open','High','Low','Close']
    if not all(c in df.columns for c in needed): return pd.DataFrame()
    for c in needed: df[c]=pd.to_numeric(df[c],errors='coerce')
    if 'Volume' not in df.columns: df['Volume']=0
    df=df.dropna(subset=needed)
    df.index=pd.to_datetime(df.index)
    if getattr(df.index,'tz',None) is not None: df.index=df.index.tz_convert(None)
    return df.sort_index()

def get_tf(interval, period, allow_proxy=False):
    df=clean(_download(SPOT,interval,period))
    if len(df)>=80: return df,'XAU spot'
    if allow_proxy:
        df=clean(_download(FUTURES,interval,period))
        if len(df)>=80: return df,'GC futures proxy'
    return pd.DataFrame(),'unavailable'

@st.cache_data(ttl=120, show_spinner=False)
def load_all(allow_proxy=False):
    specs={'15m':('15m','30d'),'5m':('5m','30d'),'1m':('1m','7d')}
    out={'source':{}}
    for tf,(iv,period) in specs.items():
        df,src=get_tf(iv,period,allow_proxy); out[tf]=df; out['source'][tf]=src
    out['source_line']=' • '.join([f'{tf}: {len(out[tf])} bars · {out["source"][tf]}' for tf in ['15m','5m','1m']])
    missing=[tf for tf in ['15m','5m','1m'] if out[tf].empty]
    proxy=[tf for tf in ['15m','5m','1m'] if out['source'][tf]=='GC futures proxy']
    warnings=[]
    if missing: warnings.append('Missing required timeframe(s): '+', '.join(missing)+'. Yahoo may not currently expose that XAU interval; try Refresh.')
    if proxy: warnings.append('RESEARCH ONLY: '+', '.join(proxy)+' uses GC=F futures proxy. Do not copy these prices to a spot/CFD broker.')
    out['warning']=' '.join(warnings)
    return out
