import numpy as np
import pandas as pd
from config import ATR_PERIOD, MIN_BREAK_ATR, MIN_DISPLACEMENT_BODY, DISPLACEMENT_ATR, EQUAL_LEVEL_ATR, SWEEP_MIN_ATR, MIN_FVG_ATR

def normalize_ohlcv(df):
    if df is None or df.empty: return pd.DataFrame()
    x=df.copy()
    if isinstance(x.columns,pd.MultiIndex): x.columns=[c[0] for c in x.columns]
    x.columns=[str(c).lower() for c in x.columns]
    return x.dropna(subset=["open","high","low","close"])

def add_features(df):
    x=normalize_ohlcv(df)
    if x.empty:return x
    tr=pd.concat([x['high']-x['low'],(x['high']-x['close'].shift()).abs(),(x['low']-x['close'].shift()).abs()],axis=1).max(axis=1)
    x["atr"]=tr.rolling(ATR_PERIOD).mean()
    x["body"]=(x['close']-x['open']).abs()
    x["range"]=x['high']-x['low']
    x["body_ratio"]=np.where(x["range"]>0,x['body']/x["range"],0)
    x["bull"]=x['close']>x['open']; x["bear"]=x['close']<x['open']
    x["swing_high"]=(x['high']>x['high'].shift(1))&(x['high']>x['high'].shift(2))&(x['high']>x['high'].shift(-1))&(x['high']>x['high'].shift(-2))
    x["swing_low"]=(x['low']<x['low'].shift(1))&(x['low']<x['low'].shift(2))&(x['low']<x['low'].shift(-1))&(x['low']<x['low'].shift(-2))
    return x

def structure(df):
    x=add_features(df)
    if x.empty:return {"bias":"UNKNOWN","bos":None,"choch":None,"last_high":None,"last_low":None}
    last=x.iloc[-1]; highs=x.loc[x['swing_high'],"high"]; lows=x.loc[x['swing_low'],"low"]
    lh=highs.iloc[-1] if len(highs) else np.nan; ll=lows.iloc[-1] if len(lows) else np.nan
    ph=highs.iloc[-2] if len(highs)>=2 else np.nan; pl=lows.iloc[-2] if len(lows)>=2 else np.nan
    bb=bool(pd.notna(lh) and pd.notna(last.atr) and last.close>lh and last.close-lh>=MIN_BREAK_ATR*last.atr)
    bs=bool(pd.notna(ll) and pd.notna(last.atr) and last.close<ll and ll-last.close>=MIN_BREAK_ATR*last.atr)
    bull_struct=pd.notna(lh) and pd.notna(ph) and lh>ph
    bear_struct=pd.notna(ll) and pd.notna(pl) and ll<pl
    bias="BULLISH" if bull_struct else "BEARISH" if bear_struct else "NEUTRAL"
    choch="BULLISH" if bear_struct and bb else "BEARISH" if bull_struct and bs else None
    return {"bias":bias,"bos":"BULLISH" if bb else "BEARISH" if bs else None,"choch":choch,
            "last_high":float(lh) if pd.notna(lh) else None,"last_low":float(ll) if pd.notna(ll) else None}

def detect_fvg(df):
    x=add_features(df); out=[]
    for i in range(2,len(x)):
        a,c=x.iloc[i-2],x.iloc[i]
        if pd.isna(c.atr):continue
        if c.low>a.high and c.low-a.high>=MIN_FVG_ATR*c.atr:
            out.append({"type":"BULLISH","top":float(c.low),"bottom":float(a.high),"index":x.index[i]})
        if c.high<a.low and a.low-c.high>=MIN_FVG_ATR*c.atr:
            out.append({"type":"BEARISH","top":float(a.low),"bottom":float(c.high),"index":x.index[i]})
    return out[-20:]

def detect_order_blocks(df):
    x=add_features(df); out=[]
    for i in range(1,len(x)-1):
        cur,nxt=x.iloc[i],x.iloc[i+1]
        if pd.isna(nxt.atr):continue
        disp=nxt.body_ratio>=MIN_DISPLACEMENT_BODY and nxt.body>=DISPLACEMENT_ATR*nxt.atr
        if cur.bear and nxt.bull and disp:
            out.append({"type":"BULLISH","top":float(cur.high),"bottom":float(cur.low),"index":x.index[i],"score":70})
        if cur.bull and nxt.bear and disp:
            out.append({"type":"BEARISH","top":float(cur.high),"bottom":float(cur.low),"index":x.index[i],"score":70})
    return out[-20:]

def liquidity_levels(df):
    x=add_features(df); highs=x.loc[x['swing_high'],"high"].tolist(); lows=x.loc[x['swing_low'],"low"].tolist()
    atr_now=x['atr'].iloc[-1] if len(x) else np.nan
    eh,el=[],[]
    if pd.notna(atr_now):
        tol=EQUAL_LEVEL_ATR*atr_now
        for i in range(len(highs)):
            for j in range(i+1,len(highs)):
                if abs(highs[i]-highs[j])<=tol: eh.append(max(highs[i],highs[j]))
        for i in range(len(lows)):
            for j in range(i+1,len(lows)):
                if abs(lows[i]-lows[j])<=tol: el.append(min(lows[i],lows[j]))
    return {"swing_highs":highs[-10:],"swing_lows":lows[-10:],"equal_highs":sorted(set(eh))[-5:],"equal_lows":sorted(set(el))[-5:]}

def detect_recent_sweep(df):
    x=add_features(df)
    if len(x)<10:return None
    last=x.iloc[-1]
    if pd.isna(last.atr):return None
    lv=liquidity_levels(x)
    for level in reversed(lv["equal_lows"]+lv["swing_lows"][:-1]):
        if last.low<level and last.close>level and level-last.low>=SWEEP_MIN_ATR*last.atr:
            return {"type":"SELL_SIDE","level":float(level),"price":float(last.low)}
    for level in reversed(lv["equal_highs"]+lv["swing_highs"][:-1]):
        if last.high>level and last.close<level and last.high-level>=SWEEP_MIN_ATR*last.atr:
            return {"type":"BUY_SIDE","level":float(level),"price":float(last.high)}
    return None

def premium_discount(df):
    x=add_features(df)
    if x.empty:return None
    hi=x['high'].tail(100).max(); lo=x['low'].tail(100).min(); mid=(hi+lo)/2; price=x['close'].iloc[-1]
    return {"high":float(hi),"low":float(lo),"mid":float(mid),"zone":"DISCOUNT" if price<mid else "PREMIUM"}

def analyze_timeframe(df):
    return {"structure":structure(df),"fvg":detect_fvg(df),"ob":detect_order_blocks(df),
            "liquidity":liquidity_levels(df),"sweep":detect_recent_sweep(df),
            "premium_discount":premium_discount(df)}

def score_setup(a15,a5,a1,news_score=0,dxy_score=0,yield_score=0):
    L=S=0; lr=[]; sr=[]
    def add(d,p,r):
        nonlocal L,S
        if d=="LONG":L+=p;lr.append(r)
        else:S+=p;sr.append(r)
    s=a15["structure"]
    if s["bias"]=="BULLISH":add("LONG",10,"15m bullish structure")
    if s["bias"]=="BEARISH":add("SHORT",10,"15m bearish structure")
    if s["choch"]=="BULLISH":add("LONG",5,"15m bullish CHoCH")
    if s["choch"]=="BEARISH":add("SHORT",5,"15m bearish CHoCH")
    if a15["sweep"] and a15["sweep"]["type"]=="SELL_SIDE":add("LONG",5,"15m sell-side sweep")
    if a15["sweep"] and a15["sweep"]["type"]=="BUY_SIDE":add("SHORT",5,"15m buy-side sweep")
    if any(o["type"]=="BULLISH" for o in a15["ob"][-3:]):add("LONG",3,"15m bullish OB")
    if any(o["type"]=="BEARISH" for o in a15["ob"][-3:]):add("SHORT",3,"15m bearish OB")
    if any(f["type"]=="BULLISH" for f in a15["fvg"][-3:]):add("LONG",2,"15m bullish FVG")
    if any(f["type"]=="BEARISH" for f in a15["fvg"][-3:]):add("SHORT",2,"15m bearish FVG")
    s=a5["structure"]
    if s["bos"]=="BULLISH":add("LONG",7,"5m bullish BOS")
    if s["bos"]=="BEARISH":add("SHORT",7,"5m bearish BOS")
    if s["choch"]=="BULLISH":add("LONG",7,"5m bullish CHoCH")
    if s["choch"]=="BEARISH":add("SHORT",7,"5m bearish CHoCH")
    if a5["sweep"] and a5["sweep"]["type"]=="SELL_SIDE":add("LONG",6,"5m sell-side sweep")
    if a5["sweep"] and a5["sweep"]["type"]=="BUY_SIDE":add("SHORT",6,"5m buy-side sweep")
    if any(f["type"]=="BULLISH" for f in a5["fvg"][-2:]):add("LONG",5,"5m bullish FVG")
    if any(f["type"]=="BEARISH" for f in a5["fvg"][-2:]):add("SHORT",5,"5m bearish FVG")
    s=a1["structure"]
    if s["choch"]=="BULLISH":add("LONG",7,"1m bullish CHoCH")
    if s["choch"]=="BEARISH":add("SHORT",7,"1m bearish CHoCH")
    if s["bos"]=="BULLISH":add("LONG",5,"1m bullish BOS")
    if s["bos"]=="BEARISH":add("SHORT",5,"1m bearish BOS")
    if a1["sweep"] and a1["sweep"]["type"]=="SELL_SIDE":add("LONG",5,"1m sell-side sweep")
    if a1["sweep"] and a1["sweep"]["type"]=="BUY_SIDE":add("SHORT",5,"1m buy-side sweep")
    if any(f["type"]=="BULLISH" for f in a1["fvg"][-2:]):add("LONG",3,"1m bullish FVG")
    if any(f["type"]=="BEARISH" for f in a1["fvg"][-2:]):add("SHORT",3,"1m bearish FVG")
    if news_score>0:add("LONG",min(10,news_score/10),"gold news bullish")
    if news_score<0:add("SHORT",min(10,abs(news_score)/10),"gold news bearish")
    L=min(100,round(L,1));S=min(100,round(S,1))
    best=max(L,S)
    signal=("LONG" if L>S else "SHORT") if best>=75 else "WATCH" if best>=65 else "NO TRADE"
    return {"signal":signal,"long_score":L,"short_score":S,"confidence":best,"long_reasons":lr,"short_reasons":sr}
