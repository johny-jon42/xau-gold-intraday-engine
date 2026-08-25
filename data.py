
import time, pandas as pd, yfinance as yf
import streamlit as st

SYMBOLS={"spot":"XAUUSD=X","futures":"GC=F"}
@st.cache_data(ttl=45, show_spinner=False)
def _download(symbol, interval, period):
    return yf.download(symbol, interval=interval, period=period, progress=False, auto_adjust=False, threads=False)

def clean(df):
    if df is None or len(df)==0: return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns=[c[0] if isinstance(c,tuple) else c for c in df.columns]
    df=df.copy()
    df.columns=[str(c).strip().title().replace(" ","_") for c in df.columns]
    needed=["Open","High","Low","Close"]
    if not all(c in df.columns for c in needed): return pd.DataFrame()
    for c in needed:
        df[c]=pd.to_numeric(df[c], errors="coerce")
    if "Volume" not in df: df["Volume"]=0
    df=df.dropna(subset=needed)
    return df

def get_tf(interval, periods=("5d","3d","1d")):
    for source,name in [("spot","XAU spot"),("futures","GC futures proxy")]:
        for p in periods:
            try:
                df=clean(_download(SYMBOLS[source],interval,p))
                if len(df)>=80:
                    return df, name
            except Exception:
                pass
    return pd.DataFrame(),"unavailable"

def load_all():
    out={}
    for tf,iv in [("15m","15m"),("5m","5m"),("1m","1m")]:
        df,src=get_tf(iv)
        out[tf]=df; out.setdefault("source",{})[tf]=src
    out["source_line"]=" • ".join([f"{tf}: {len(out[tf])} bars · {out['source'][tf]}" for tf in ["15m","5m","1m"]])
    if any(out[tf].empty for tf in ["15m","5m","1m"]):
        out["warning"]="One or more required timeframes are unavailable. No entry will be produced."
    else: out["warning"]=""
    return out
