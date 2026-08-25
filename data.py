import pandas as pd
import streamlit as st
import yfinance as yf

SYMBOLS={"spot":"XAUUSD=X","futures":"GC=F"}

@st.cache_data(ttl=45, show_spinner=False)
def _download(symbol, interval, period):
    return yf.download(symbol, interval=interval, period=period, progress=False, auto_adjust=False, threads=False)

def clean(df):
    if df is None or len(df)==0: return pd.DataFrame()
    if isinstance(df.columns,pd.MultiIndex): df.columns=[c[0] if isinstance(c,tuple) else c for c in df.columns]
    df=df.copy(); df.columns=[str(c).strip().title().replace(' ','_') for c in df.columns]
    needed=['Open','High','Low','Close']
    if not all(c in df.columns for c in needed): return pd.DataFrame()
    for c in needed: df[c]=pd.to_numeric(df[c],errors='coerce')
    if 'Volume' not in df.columns: df['Volume']=0
    df=df.dropna(subset=needed); df.index=pd.to_datetime(df.index)
    return df

def get_tf(interval, period):
    for source,name in [('spot','XAU spot'),('futures','GC futures proxy')]:
        try:
            df=clean(_download(SYMBOLS[source],interval,period))
            if len(df)>=80: return df,name
        except Exception: pass
    return pd.DataFrame(),'unavailable'

def load_all():
    specs={'15m':('15m','60d'),'5m':('5m','60d'),'1m':('1m','7d')}
    out={'source':{}}
    for tf,(iv,period) in specs.items():
        df,src=get_tf(iv,period); out[tf]=df; out['source'][tf]=src
    out['source_line']=' • '.join([f'{tf}: {len(out[tf])} bars · {out["source"][tf]}' for tf in ['15m','5m','1m']])
    missing=[tf for tf in ['15m','5m','1m'] if out[tf].empty]
    fallback=[tf for tf in ['15m','5m','1m'] if out['source'][tf]=='GC futures proxy']
    warnings=[]
    if missing: warnings.append('Missing required timeframe(s): '+', '.join(missing)+'.')
    if fallback: warnings.append('Execution-grade warning: '+', '.join(fallback)+' uses GC=F futures proxy. Trade levels are research-only until all 15m/5m/1m feeds are XAU spot or broker-quality data.')
    out['warning']=' '.join(warnings)
    return out
