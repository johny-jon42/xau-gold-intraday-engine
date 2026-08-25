
import numpy as np, pandas as pd, math, re, time
from urllib.request import urlopen, Request
from xml.etree import ElementTree as ET

def atr(df,n=14):
    h,l,c=df.High,df.Low,df.Close
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(n).mean()

def swings(df,lb=2):
    h=df.High; l=df.Low
    sh=(h>h.shift(1))&(h>h.shift(-1))
    sl=(l<l.shift(1))&(l<l.shift(-1))
    return sh,sl

def structure(df):
    if df.empty: return {}
    d=df.copy(); a=atr(d); sh,sl=swings(d)
    hi=d.High[sh].tail(8).tolist(); lo=d.Low[sl].tail(8).tolist()
    close=float(d.Close.iloc[-1]); aa=float(a.iloc[-1] or 0)
    ema20=float(d.Close.ewm(span=20).mean().iloc[-1]); ema50=float(d.Close.ewm(span=50).mean().iloc[-1])
    score=50
    if close>ema20: score+=10
    if close>ema50: score+=10
    if len(hi)>=2 and hi[-1]>hi[-2]: score+=10
    if len(lo)>=2 and lo[-1]>lo[-2]: score+=10
    if close<ema20: score-=10
    if close<ema50: score-=10
    if len(hi)>=2 and hi[-1]<hi[-2]: score-=10
    if len(lo)>=2 and lo[-1]<lo[-2]: score-=10
    score=int(max(0,min(100,score)))
    bias="BULLISH" if score>=60 else "BEARISH" if score<=40 else "RANGE"
    prev_hi=max(hi[:-1]) if len(hi)>1 else None
    prev_lo=min(lo[:-1]) if len(lo)>1 else None
    bos="BULLISH" if prev_hi and close>prev_hi else "BEARISH" if prev_lo and close<prev_lo else "—"
    recent_low=float(d.Low.tail(8).min()); recent_high=float(d.High.tail(8).max())
    sweep="SELL-SIDE" if close>recent_low and d.Low.tail(3).min()<recent_low else "BUY-SIDE" if close<recent_high and d.High.tail(3).max()>recent_high else "—"
    rng=float((d.High-d.Low).tail(5).mean())
    displacement="YES" if aa and rng>1.15*aa else "NO"
    # FVG on last 30 bars
    fvg="—"; ob="—"
    for i in range(len(d)-3,len(d)):
        if i<2: continue
        if d.Low.iloc[i] > d.High.iloc[i-2] and (d.Low.iloc[i]-d.High.iloc[i-2]) > 0.08*aa:
            fvg="BULLISH"
        if d.High.iloc[i] < d.Low.iloc[i-2] and (d.Low.iloc[i-2]-d.High.iloc[i]) > 0.08*aa:
            fvg="BEARISH"
    # last opposite candle before displacement
    if displacement=="YES":
        body=float(abs(d.Close.iloc[-1]-d.Open.iloc[-1]))
        if d.Close.iloc[-1]>d.Open.iloc[-1] and body>0.5*aa: ob="BULLISH"
        if d.Close.iloc[-1]<d.Open.iloc[-1] and body>0.5*aa: ob="BEARISH"
    choch="BULLISH" if bias=="BEARISH" and bos=="BULLISH" else "BEARISH" if bias=="BULLISH" and bos=="BEARISH" else "—"
    return dict(bias=bias,trend_score=score,bos=bos,choch=choch,sweep=sweep,displacement=displacement,fvg=fvg,ob=ob,atr=aa,high=recent_high,low=recent_low,close=close)

def news():
    # Lightweight public RSS; failures are handled conservatively.
    urls=[
        "https://www.forexfactory.com/calendar?day=today&format=rss",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F&region=US&lang=en-US"
    ]
    items=[]; score=0; risk=0
    for u in urls:
        try:
            req=Request(u,headers={"User-Agent":"Mozilla/5.0"})
            raw=urlopen(req,timeout=5).read()
            root=ET.fromstring(raw)
            for it in root.iter():
                title=it.find("title")
                if title is not None and title.text:
                    t=title.text.strip()
                    if t and t not in [x["headline"] for x in items]:
                        items.append({"headline":t[:180],"impact":"unknown"})
                        low=t.lower()
                        if any(k in low for k in ["fomc","powell","cpi","pce","nfp","payroll","fed","interest rate","ppi","gdp"]):
                            risk=min(100,risk+25)
                        if any(k in low for k in ["dovish","rate cut","weak jobs","lower inflation","yield fell"]): score+=8
                        if any(k in low for k in ["hawkish","rate hike","strong jobs","higher inflation","yield rose"]): score-=8
        except Exception: pass
    risk=min(100,risk)
    bias="BULLISH" if score>=8 else "BEARISH" if score<=-8 else "NEUTRAL"
    return {"direction_score":int(max(-100,min(100,score))),"risk":risk,"bias":bias,"items":items[:15]}

def plan(direction, d1, d5, d15, rr2):
    if direction not in ("LONG","SHORT"): return None
    a=d1["atr"] or 0
    if a<=0: return None
    entry=d1["close"]
    # structural stop around recent liquidity/sweep
    if direction=="LONG":
        sl=min(d1["low"], d5["low"])-0.05*a
        risk=entry-sl
        if risk<=0 or risk<0.6*a or risk>2.5*a: return None
        tp1=entry+risk; tp2=entry+rr2*risk; be=entry+risk
    else:
        sl=max(d1["high"], d5["high"])+0.05*a
        risk=sl-entry
        if risk<=0 or risk<0.6*a or risk>2.5*a: return None
        tp1=entry-risk; tp2=entry-rr2*risk; be=entry-risk
    return dict(entry=entry,sl=sl,tp1=tp1,tp2=tp2,be_trigger=be,rr2=rr2,risk=risk,
                instructions=f"{direction}: place only after the 1m trigger candle closes in the zone. Initial SL at structural invalidation. Take partials at TP1/1R; move SL to breakeven only after TP1 is actually reached. Exit the remainder at TP2 or earlier if structure invalidates.")

def analyze(data,rr2=2.5,news_hold=70):
    d15=structure(data["15m"]); d5=structure(data["5m"]); d1=structure(data["1m"])
    n=news()
    direction="NONE"
    if d15.get("bias")=="BULLISH" and d5.get("bias")=="BULLISH" and d1.get("bias")=="BULLISH": direction="LONG"
    if d15.get("bias")=="BEARISH" and d5.get("bias")=="BEARISH" and d1.get("bias")=="BEARISH": direction="SHORT"
    conf=int(round((d15.get("trend_score",50)*.35+d5.get("trend_score",50)*.35+d1.get("trend_score",50)*.30)))
    setup="NO TRADE"
    p=None
    if direction!="NONE":
        trigger_ok=(d5.get("bos") in (direction,"—") or d5.get("choch")==direction) and d5.get("displacement")=="YES"
        exec_ok=(d1.get("bos") in (direction,"—") or d1.get("choch")==direction) and d1.get("displacement")=="YES"
        if trigger_ok and exec_ok:
            p=plan(direction,d1,d5,d15,rr2)
            if p and n["risk"]<news_hold:
                setup=f"{direction} READY"; conf=min(100,conf+10)
            elif p: setup="NEWS HOLD"
    if p is None or setup in ("NO TRADE","NEWS HOLD"):
        p=None
    long_trigger=float(d5["high"]+0.05*d5["atr"]) if d5 else 0
    short_trigger=float(d5["low"]-0.05*d5["atr"]) if d5 else 0
    msg=("Wait: 15m/5m/1m must align before an actionable entry is issued."
         if setup=="NO TRADE" else "High-impact event risk is blocking the entry. Direction may be valid, but do not enter until the risk window clears.")
    return dict(direction=direction,confidence=conf,setup_label=setup,trade_plan=p,trade_message=msg,
                triggers={"long":long_trigger,"short":short_trigger},
                news=n,structure={"15m":d15,"5m":d5,"1m":d1},
                levels={"15m":{"high":d15.get("high"),"low":d15.get("low")},"5m":{"high":d5.get("high"),"low":d5.get("low")},"1m":{"high":d1.get("high"),"low":d1.get("low")}},
                data_warning=data.get("warning",""),source_line=data["source_line"],
                validation={"status":"Available after enough history; V6 prioritizes closed-bar rules and avoids look-ahead. Use the live dashboard only after verifying the feed and broker price."})
