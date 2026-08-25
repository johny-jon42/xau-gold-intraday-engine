import numpy as np
import pandas as pd
from config import ATR_PERIOD, MIN_BREAK_ATR, MIN_DISPLACEMENT_BODY, DISPLACEMENT_ATR, EQUAL_LEVEL_ATR, SWEEP_MIN_ATR, MIN_FVG_ATR, SWING_LEFT, SWING_RIGHT

OHLC = ["open", "high", "low", "close"]

def normalize_ohlcv(df):
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=OHLC)
    x = df.copy()
    if isinstance(x.columns, pd.MultiIndex):
        cols=[]
        for col in x.columns:
            parts=[str(p) for p in col]
            match=next((p for p in parts if p.lower() in OHLC+['adj close','volume']), parts[0])
            cols.append(match)
        x.columns=cols
    x.columns=[str(c).strip().lower().replace(' ','_') for c in x.columns]
    x=x.loc[:,~x.columns.duplicated(keep='first')]
    missing=[c for c in OHLC if c not in x.columns]
    if missing:
        raise ValueError(f"Market feed is missing columns: {', '.join(missing)}")
    for c in OHLC:
        x[c]=pd.to_numeric(x[c], errors='coerce')
    x=x.dropna(subset=OHLC).copy()
    if len(x)==0: return x
    return x


def add_features(df):
    x=normalize_ohlcv(df)
    if x.empty: return x
    prev_close=x["close"].shift(1)
    tr=pd.concat([(x["high"]-x["low"]).abs(), (x["high"]-prev_close).abs(), (x["low"]-prev_close).abs()], axis=1).max(axis=1)
    x["atr"]=tr.rolling(ATR_PERIOD, min_periods=ATR_PERIOD).mean()
    x["body"]=(x["close"]-x["open"]).abs()
    x["range"]=(x["high"]-x["low"]).abs()
    x["body_ratio"]=np.where(x["range"]>0, x["body"]/x["range"], 0.0)
    x["bull"]=x["close"]>x["open"]
    x["bear"]=x["close"]<x["open"]
    # Bracket indexing is intentional: avoids pandas attribute/column ambiguity.
    x["swing_high"]=(x["high"]>x["high"].shift(SWING_LEFT)) & (x["high"]>x["high"].shift(-SWING_RIGHT))
    x["swing_low"]=(x["low"]<x["low"].shift(SWING_LEFT)) & (x["low"]<x["low"].shift(-SWING_RIGHT))
    return x


def structure(df):
    x=add_features(df)
    if x.empty: return {"bias":"UNKNOWN","bos":None,"choch":None,"last_high":None,"last_low":None,"break_level":None}
    highs=x.loc[x["swing_high"],"high"]
    lows=x.loc[x["swing_low"],"low"]
    lh=float(highs.iloc[-1]) if len(highs) else np.nan
    ll=float(lows.iloc[-1]) if len(lows) else np.nan
    ph=float(highs.iloc[-2]) if len(highs)>=2 else np.nan
    pl=float(lows.iloc[-2]) if len(lows)>=2 else np.nan
    atr=x["atr"].iloc[-1]
    close=float(x["close"].iloc[-1])
    bb=pd.notna(atr) and pd.notna(lh) and close>lh and close-lh>=MIN_BREAK_ATR*atr
    bs=pd.notna(atr) and pd.notna(ll) and close<ll and ll-close>=MIN_BREAK_ATR*atr
    bull_struct=pd.notna(lh) and pd.notna(ph) and lh>ph
    bear_struct=pd.notna(ll) and pd.notna(pl) and ll<pl
    bias="BULLISH" if bull_struct else "BEARISH" if bear_struct else "NEUTRAL"
    choch="BULLISH" if bear_struct and bb else "BEARISH" if bull_struct and bs else None
    return {"bias":bias,"bos":"BULLISH" if bb else "BEARISH" if bs else None,"choch":choch,
            "last_high":lh if pd.notna(lh) else None,"last_low":ll if pd.notna(ll) else None,
            "break_level":lh if bb else ll if bs else None}


def detect_fvg(df):
    x=add_features(df); out=[]
    for i in range(2,len(x)):
        a=x.iloc[i-2]; c=x.iloc[i]
        atr=c["atr"]
        if pd.isna(atr): continue
        if c["low"]>a["high"] and c["low"]-a["high"]>=MIN_FVG_ATR*atr:
            out.append({"type":"BULLISH","top":float(c["low"]),"bottom":float(a["high"]),"index":x.index[i],"active":True})
        elif c["high"]<a["low"] and a["low"]-c["high"]>=MIN_FVG_ATR*atr:
            out.append({"type":"BEARISH","top":float(a["low"]),"bottom":float(c["high"]),"index":x.index[i],"active":True})
    # Mark gaps as mitigated if later candles fully cross the zone.
    for f in out:
        later=x.loc[x.index>f["index"]]
        if f["type"]=="BULLISH" and len(later) and (later["low"]<=f["bottom"]).any(): f["active"]=False
        if f["type"]=="BEARISH" and len(later) and (later["high"]>=f["top"]).any(): f["active"]=False
    return out[-20:]


def detect_order_blocks(df):
    x=add_features(df); out=[]
    for i in range(1,len(x)-1):
        cur=x.iloc[i]; nxt=x.iloc[i+1]
        atr=nxt["atr"]
        if pd.isna(atr): continue
        displacement=(nxt["body_ratio"]>=MIN_DISPLACEMENT_BODY and nxt["body"]>=DISPLACEMENT_ATR*atr)
        if cur["bear"] and nxt["bull"] and displacement:
            out.append({"type":"BULLISH","top":float(cur["high"]),"bottom":float(cur["low"]),"index":x.index[i],"score":70,"active":True})
        elif cur["bull"] and nxt["bear"] and displacement:
            out.append({"type":"BEARISH","top":float(cur["high"]),"bottom":float(cur["low"]),"index":x.index[i],"score":70,"active":True})
    for o in out:
        later=x.loc[x.index>o["index"]]
        if o["type"]=="BULLISH" and len(later) and (later["close"]<o["bottom"]).any(): o["active"]=False
        if o["type"]=="BEARISH" and len(later) and (later["close"]>o["top"]).any(): o["active"]=False
    return out[-20:]


def liquidity_levels(df):
    x=add_features(df)
    if x.empty: return {"swing_highs":[],"swing_lows":[],"equal_highs":[],"equal_lows":[]}
    highs=x.loc[x["swing_high"],"high"].tolist(); lows=x.loc[x["swing_low"],"low"].tolist()
    atr=x["atr"].iloc[-1]; tol=float(EQUAL_LEVEL_ATR*atr) if pd.notna(atr) else 0
    eh=[]; el=[]
    if tol>0:
        for i in range(len(highs)):
            for j in range(i+1,len(highs)):
                if abs(highs[i]-highs[j])<=tol: eh.append(max(highs[i],highs[j]))
        for i in range(len(lows)):
            for j in range(i+1,len(lows)):
                if abs(lows[i]-lows[j])<=tol: el.append(min(lows[i],lows[j]))
    return {"swing_highs":[float(v) for v in highs[-10:]],"swing_lows":[float(v) for v in lows[-10:]],
            "equal_highs":[float(v) for v in sorted(set(eh))[-5:]],"equal_lows":[float(v) for v in sorted(set(el))[-5:]]}


def detect_recent_sweep(df):
    x=add_features(df)
    if len(x)<10 or pd.isna(x["atr"].iloc[-1]): return None
    last=x.iloc[-1]; lv=liquidity_levels(x); atr=float(last["atr"])
    for level in reversed(lv["equal_lows"]+lv["swing_lows"][:-1]):
        if last["low"]<level and last["close"]>level and level-last["low"]>=SWEEP_MIN_ATR*atr:
            return {"type":"SELL_SIDE","level":float(level),"price":float(last["low"]),"index":x.index[-1]}
    for level in reversed(lv["equal_highs"]+lv["swing_highs"][:-1]):
        if last["high"]>level and last["close"]<level and last["high"]-level>=SWEEP_MIN_ATR*atr:
            return {"type":"BUY_SIDE","level":float(level),"price":float(last["high"]),"index":x.index[-1]}
    return None


def premium_discount(df):
    x=add_features(df)
    if x.empty:return None
    hi=float(x["high"].tail(100).max()); lo=float(x["low"].tail(100).min()); mid=(hi+lo)/2; price=float(x["close"].iloc[-1])
    return {"high":hi,"low":lo,"mid":mid,"zone":"DISCOUNT" if price<mid else "PREMIUM"}


def analyze_timeframe(df):
    return {"data":add_features(df),"structure":structure(df),"fvg":detect_fvg(df),"ob":detect_order_blocks(df),
            "liquidity":liquidity_levels(df),"sweep":detect_recent_sweep(df),"premium_discount":premium_discount(df)}


def score_setup(a15,a5,a1,news_score=0):
    L=S=0.0; lr=[]; sr=[]
    def add(direction,points,reason):
        nonlocal L,S
        if direction=="LONG": L+=points; lr.append(reason)
        else: S+=points; sr.append(reason)
    for a, weights in [(a15,(10,5,5,3,2)),(a5,(7,7,6,5,5)),(a1,(5,7,5,3,3))]:
        s=a["structure"]
        if s["bias"]=="BULLISH": add("LONG",weights[0],f"{weights[0]} pts: {('15m' if a is a15 else '5m' if a is a5 else '1m')} bullish structure")
        if s["bias"]=="BEARISH": add("SHORT",weights[0],f"{weights[0]} pts: bearish structure")
        if s["bos"]=="BULLISH": add("LONG",weights[1],"Bullish BOS")
        if s["bos"]=="BEARISH": add("SHORT",weights[1],"Bearish BOS")
        if s["choch"]=="BULLISH": add("LONG",weights[1],"Bullish CHoCH")
        if s["choch"]=="BEARISH": add("SHORT",weights[1],"Bearish CHoCH")
        if a["sweep"] and a["sweep"]["type"]=="SELL_SIDE": add("LONG",weights[2],"Sell-side liquidity sweep")
        if a["sweep"] and a["sweep"]["type"]=="BUY_SIDE": add("SHORT",weights[2],"Buy-side liquidity sweep")
        if any(f["type"]=="BULLISH" and f["active"] for f in a["fvg"][-3:]): add("LONG",weights[3],"Active bullish FVG")
        if any(f["type"]=="BEARISH" and f["active"] for f in a["fvg"][-3:]): add("SHORT",weights[3],"Active bearish FVG")
        if any(o["type"]=="BULLISH" and o["active"] for o in a["ob"][-3:]): add("LONG",weights[4],"Active bullish order block")
        if any(o["type"]=="BEARISH" and o["active"] for o in a["ob"][-3:]): add("SHORT",weights[4],"Active bearish order block")
    if news_score>0: add("LONG",min(10,news_score/10),f"Gold news +{news_score}")
    elif news_score<0: add("SHORT",min(10,abs(news_score)/10),f"Gold news {news_score}")
    L=round(min(100,L),1); S=round(min(100,S),1); best=max(L,S)
    signal="LONG" if L>S and best>=75 else "SHORT" if S>L and best>=75 else "WATCH" if best>=65 else "NO TRADE"
    return {"signal":signal,"long_score":L,"short_score":S,"confidence":best,"long_reasons":lr,"short_reasons":sr}


def build_trade_plan(a15,a5,a1,result):
    price=float(a1["data"]["close"].iloc[-1]) if not a1["data"].empty else None
    if price is None or result["signal"] not in ("LONG","SHORT"): return None
    direction=result["signal"]
    atr=float(a1["data"]["atr"].iloc[-1]) if pd.notna(a1["data"]["atr"].iloc[-1]) else price*0.001
    sweep=a1["sweep"] or a5["sweep"]
    if direction=="LONG":
        sl=(sweep["price"]-0.15*atr) if sweep and sweep["type"]=="SELL_SIDE" else price-1.2*atr
        risk=price-sl; tp1=price+risk; tp2=price+2*risk
    else:
        sl=(sweep["price"]+0.15*atr) if sweep and sweep["type"]=="BUY_SIDE" else price+1.2*atr
        risk=sl-price; tp1=price-risk; tp2=price-2*risk
    return {"direction":direction,"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,"risk":abs(risk),"rr_tp2":2.0}


def simple_backtest(df, horizon=12, min_score=75):
    x=normalize_ohlcv(df)
    if len(x)<250:return {"trades":0,"wins":0,"losses":0,"win_rate":0,"avg_r":0,"net_r":0}
    # Lightweight 5m replay: score structure on a rolling window, then evaluate next horizon bars.
    trades=[]; step=max(1, horizon//2)
    for i in range(180,len(x)-horizon,step):
        w=x.iloc[:i+1]
        a=analyze_timeframe(w)
        s=a["structure"]; direction="LONG" if s["bos"]=="BULLISH" or s["choch"]=="BULLISH" else "SHORT" if s["bos"]=="BEARISH" or s["choch"]=="BEARISH" else None
        if not direction: continue
        score=75 + (5 if a["sweep"] else 0) + (3 if any(f["active"] for f in a["fvg"][-2:]) else 0)
        if score<min_score: continue
        entry=float(x["close"].iloc[i]); atr=float(a["data"]["atr"].iloc[-1]) if pd.notna(a["data"]["atr"].iloc[-1]) else 0
        if atr<=0: continue
        sl=entry-1.0*atr if direction=="LONG" else entry+1.0*atr
        tp=entry+1.5*atr if direction=="LONG" else entry-1.5*atr
        future=x.iloc[i+1:i+1+horizon]
        result=0
        for _,r in future.iterrows():
            if direction=="LONG":
                if r["low"]<=sl: result=-1; break
                if r["high"]>=tp: result=1.5; break
            else:
                if r["high"]>=sl: result=-1; break
                if r["low"]<=tp: result=1.5; break
        if result: trades.append(result)
    wins=sum(v>0 for v in trades); losses=sum(v<0 for v in trades)
    return {"trades":len(trades),"wins":wins,"losses":losses,"win_rate":round(100*wins/len(trades),1) if trades else 0,
            "avg_r":round(float(np.mean(trades)),2) if trades else 0,"net_r":round(float(np.sum(trades)),2) if trades else 0}
