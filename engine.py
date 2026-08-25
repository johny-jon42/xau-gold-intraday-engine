import numpy as np, pandas as pd, math, re, time
from urllib.request import urlopen, Request
from xml.etree import ElementTree as ET


def atr(df, n=14):
    h, l, c = df.High, df.Low, df.Close
    tr = pd.concat([(h-l), (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def swings(df, lb=2):
    h, l = df.High, df.Low
    sh = (h > h.shift(1)) & (h > h.shift(-1))
    sl = (l < l.shift(1)) & (l < l.shift(-1))
    return sh, sl


def _closed(df):
    if df is None or df.empty:
        return pd.DataFrame()
    # Ignore the newest candle because it may still be forming.
    return df.iloc[:-1].copy() if len(df) > 5 else df.copy()


def _last_two(vals):
    return vals[-2], vals[-1] if len(vals) >= 2 else (None, None)


def _find_fvg(d, aa):
    bullish = bearish = None
    if len(d) < 5 or not aa or np.isnan(aa):
        return bullish, bearish
    start = max(2, len(d) - 40)
    for i in range(start, len(d)):
        if d.Low.iloc[i] > d.High.iloc[i-2] and (d.Low.iloc[i] - d.High.iloc[i-2]) >= 0.08*aa:
            bullish = {
                "type":"BULLISH FVG", "low":float(d.High.iloc[i-2]), "high":float(d.Low.iloc[i]),
                "mid":float((d.High.iloc[i-2] + d.Low.iloc[i])/2), "bar":i
            }
        if d.High.iloc[i] < d.Low.iloc[i-2] and (d.Low.iloc[i-2] - d.High.iloc[i]) >= 0.08*aa:
            bearish = {
                "type":"BEARISH FVG", "low":float(d.High.iloc[i]), "high":float(d.Low.iloc[i-2]),
                "mid":float((d.High.iloc[i] + d.Low.iloc[i-2])/2), "bar":i
            }
    return bullish, bearish


def _find_ob(d, aa):
    bull = bear = None
    if len(d) < 8 or not aa or np.isnan(aa):
        return bull, bear
    # Last opposite candle before a meaningful displacement candle.
    for i in range(max(3, len(d)-12), len(d)):
        rng = float(d.High.iloc[i] - d.Low.iloc[i])
        body = float(abs(d.Close.iloc[i]-d.Open.iloc[i]))
        if rng < 0.9*aa or body < 0.55*aa:
            continue
        if d.Close.iloc[i] > d.Open.iloc[i]:
            for j in range(i-1, max(-1, i-5), -1):
                if d.Close.iloc[j] < d.Open.iloc[j]:
                    bull = {"type":"BULLISH OB", "low":float(d.Low.iloc[j]), "high":float(d.High.iloc[j]), "mid":float((d.Low.iloc[j]+d.High.iloc[j])/2), "bar":j}
                    break
        elif d.Close.iloc[i] < d.Open.iloc[i]:
            for j in range(i-1, max(-1, i-5), -1):
                if d.Close.iloc[j] > d.Open.iloc[j]:
                    bear = {"type":"BEARISH OB", "low":float(d.Low.iloc[j]), "high":float(d.High.iloc[j]), "mid":float((d.Low.iloc[j]+d.High.iloc[j])/2), "bar":j}
                    break
    return bull, bear


def structure(df):
    d = _closed(df)
    if d.empty:
        return {}
    a = atr(d); aa = float(a.iloc[-1]) if pd.notna(a.iloc[-1]) else 0.0
    sh, sl = swings(d)
    hi = d.High[sh].tolist(); lo = d.Low[sl].tolist()
    close = float(d.Close.iloc[-1])
    ema20 = float(d.Close.ewm(span=20).mean().iloc[-1])
    ema50 = float(d.Close.ewm(span=50).mean().iloc[-1])
    score = 50
    if close > ema20: score += 8
    if close > ema50: score += 8
    if close < ema20: score -= 8
    if close < ema50: score -= 8
    if len(hi) >= 2:
        score += 12 if hi[-1] > hi[-2] else -12 if hi[-1] < hi[-2] else 0
    if len(lo) >= 2:
        score += 12 if lo[-1] > lo[-2] else -12 if lo[-1] < lo[-2] else 0
    score = int(max(0, min(100, score)))
    bias = "BULLISH" if score >= 62 else "BEARISH" if score <= 38 else "RANGE"

    prev_hi = hi[-1] if hi else None
    prev_lo = lo[-1] if lo else None
    bos = "—"
    if prev_hi is not None and close > prev_hi + 0.05*aa: bos = "BULLISH"
    elif prev_lo is not None and close < prev_lo - 0.05*aa: bos = "BEARISH"
    prior_bias = "RANGE"
    if len(hi) >= 3 and len(lo) >= 3:
        up = hi[-2] > hi[-3] and lo[-2] > lo[-3]
        down = hi[-2] < hi[-3] and lo[-2] < lo[-3]
        prior_bias = "BULLISH" if up else "BEARISH" if down else "RANGE"
    choch = "BULLISH" if prior_bias == "BEARISH" and bos == "BULLISH" else "BEARISH" if prior_bias == "BULLISH" and bos == "BEARISH" else "—"

    # Liquidity sweep against the most recent confirmed swing, then reclaim.
    sweep = "—"; sweep_level = None
    if len(hi) >= 2:
        lh = hi[-1]
        if float(d.High.iloc[-3:].max()) > lh and close < lh:
            sweep, sweep_level = "BUY-SIDE", float(lh)
    if len(lo) >= 2:
        ll = lo[-1]
        if float(d.Low.iloc[-3:].min()) < ll and close > ll:
            sweep, sweep_level = "SELL-SIDE", float(ll)

    rng = float((d.High-d.Low).tail(5).mean())
    body = float(abs(d.Close.iloc[-1]-d.Open.iloc[-1]))
    displacement = "YES" if aa and max(rng, body) >= 1.15*aa else "NO"
    bull_fvg, bear_fvg = _find_fvg(d, aa)
    bull_ob, bear_ob = _find_ob(d, aa)
    recent_high = float(d.High.tail(20).max()); recent_low = float(d.Low.tail(20).min())
    mid = (recent_high + recent_low)/2
    zone = "DISCOUNT" if close < mid else "PREMIUM"
    return dict(
        bias=bias, trend_score=score, bos=bos, choch=choch, sweep=sweep,
        sweep_level=sweep_level, displacement=displacement, fvg="BULLISH" if bull_fvg else "BEARISH" if bear_fvg else "—",
        ob="BULLISH" if bull_ob else "BEARISH" if bear_ob else "—", atr=aa, high=recent_high, low=recent_low,
        close=close, ema20=ema20, ema50=ema50, premium_discount=zone,
        bull_fvg=bull_fvg, bear_fvg=bear_fvg, bull_ob=bull_ob, bear_ob=bear_ob,
        swing_high=float(hi[-1]) if hi else recent_high, swing_low=float(lo[-1]) if lo else recent_low,
        last_candle_high=float(d.High.iloc[-1]), last_candle_low=float(d.Low.iloc[-1])
    )


def news():
    urls=[
        "https://www.forexfactory.com/calendar?day=today&format=rss",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F&region=US&lang=en-US"
    ]
    items=[]; score=0; risk=0
    for u in urls:
        try:
            req=Request(u,headers={"User-Agent":"Mozilla/5.0"})
            raw=urlopen(req,timeout=5).read(); root=ET.fromstring(raw)
            for it in root.iter():
                title=it.find("title")
                if title is None or not title.text: continue
                t=title.text.strip()
                if not t or t in [x["headline"] for x in items]: continue
                low=t.lower(); impact="normal"
                if any(k in low for k in ["fomc","powell","cpi","pce","nfp","payroll","fed","interest rate","ppi","gdp"]):
                    risk=min(100,risk+25); impact="high"
                if any(k in low for k in ["dovish","rate cut","weak jobs","lower inflation","yield fell","real yields fell"]): score+=8
                if any(k in low for k in ["hawkish","rate hike","strong jobs","higher inflation","yield rose","real yields rose"]): score-=8
                items.append({"headline":t[:180],"impact":impact})
        except Exception: pass
    bias="BULLISH" if score>=8 else "BEARISH" if score<=-8 else "NEUTRAL"
    return {"direction_score":int(max(-100,min(100,score))),"risk":min(100,risk),"bias":bias,"items":items[:15]}


def _best_zone(direction, d1, d5):
    zones=[]
    if direction=="LONG":
        for z in (d1.get("bull_fvg"), d1.get("bull_ob"), d5.get("bull_fvg"), d5.get("bull_ob")):
            if z: zones.append(z)
    else:
        for z in (d1.get("bear_fvg"), d1.get("bear_ob"), d5.get("bear_fvg"), d5.get("bear_ob")):
            if z: zones.append(z)
    if not zones: return None
    price=d1["close"]
    valid=[z for z in zones if (z["low"] <= price <= z["high"] or (direction=="LONG" and z["high"] < price and price-z["high"] <= 1.2*d1["atr"]) or (direction=="SHORT" and z["low"] > price and z["low"]-price <= 1.2*d1["atr"]))]
    return valid[-1] if valid else zones[-1]


def plan(direction, d1, d5, d15, rr2, balance, risk_pct, contract_size):
    if direction not in ("LONG","SHORT"): return None
    a=float(d1.get("atr") or 0)
    if a<=0 or balance<=0 or risk_pct<=0 or contract_size<=0: return None
    zone=_best_zone(direction,d1,d5)
    entry=float(zone["mid"] if zone else d1["close"])
    # Only use a retracement entry if it is not wildly away from current price.
    if abs(entry-d1["close"]) > 1.5*a: entry=float(d1["close"])
    if direction=="LONG":
        invalid=min(float(d1["swing_low"]), float(d5["swing_low"]), float(d1.get("sweep_level") or d1["swing_low"]))
        sl=min(invalid, float(zone["low"]) if zone else invalid)-0.05*a
        risk_dist=entry-sl
        if risk_dist<=0 or risk_dist<0.5*a or risk_dist>2.5*a: return None
        tp1=entry+risk_dist; tp2=entry+rr2*risk_dist; be=tp1
    else:
        invalid=max(float(d1["swing_high"]), float(d5["swing_high"]), float(d1.get("sweep_level") or d1["swing_high"]))
        sl=max(invalid, float(zone["high"]) if zone else invalid)+0.05*a
        risk_dist=sl-entry
        if risk_dist<=0 or risk_dist<0.5*a or risk_dist>2.5*a: return None
        tp1=entry-risk_dist; tp2=entry-rr2*risk_dist; be=tp1
    risk_usd=balance*(risk_pct/100.0)
    lots=risk_usd/(risk_dist*contract_size)
    notional=lots*contract_size*entry
    return dict(entry=entry,sl=sl,tp1=tp1,tp2=tp2,be_trigger=be,rr2=rr2,risk=risk_dist,
                risk_usd=risk_usd,lots=lots,units=lots*contract_size,notional=notional,
                zone=(zone["type"] if zone else "CURRENT PRICE"),
                instructions=f"{direction}: use the displayed entry only after the 1m trigger/confirmation closes. Risk {risk_pct:.2f}% of the entered balance. Initial SL is structural. Take partial profit at TP1 (1R), then move SL to entry/breakeven only after TP1 is actually reached. TP2 is the runner target. Confirm your broker's XAU contract size and spread before placing the order.")


def analyze(data,rr2=2.5,news_hold=70,balance=10000,risk_pct=1.0,contract_size=100):
    d15=structure(data["15m"]); d5=structure(data["5m"]); d1=structure(data["1m"])
    n=news()
    direction="NONE"
    if d15.get("bias")=="BULLISH" and d5.get("bias") in ("BULLISH","RANGE") and d1.get("bias") in ("BULLISH","RANGE"): direction="LONG"
    if d15.get("bias")=="BEARISH" and d5.get("bias") in ("BEARISH","RANGE") and d1.get("bias") in ("BEARISH","RANGE"): direction="SHORT"
    conf=int(round(d15.get("trend_score",50)*.35+d5.get("trend_score",50)*.35+d1.get("trend_score",50)*.30))
    setup="NO TRADE"; p=None
    if direction!="NONE":
        five_ok=(d5.get("bos") in (direction,"—") or d5.get("choch")==direction or d5.get("sweep")==("SELL-SIDE" if direction=="LONG" else "BUY-SIDE")) and d5.get("displacement")=="YES"
        one_ok=(d1.get("bos") in (direction,"—") or d1.get("choch")==direction or d1.get("sweep")==("SELL-SIDE" if direction=="LONG" else "BUY-SIDE")) and d1.get("displacement")=="YES"
        smc_ok=(d5.get("fvg")==("BULLISH" if direction=="LONG" else "BEARISH") or d5.get("ob")==("BULLISH" if direction=="LONG" else "BEARISH") or d1.get("fvg")==("BULLISH" if direction=="LONG" else "BEARISH") or d1.get("ob")==("BULLISH" if direction=="LONG" else "BEARISH"))
        if five_ok and one_ok and smc_ok:
            p=plan(direction,d1,d5,d15,rr2,balance,risk_pct,contract_size)
            if p and n["risk"] < news_hold:
                setup=f"{direction} READY"; conf=min(100,conf+12)
            elif p:
                setup="NEWS HOLD"
    if p is None or setup in ("NO TRADE","NEWS HOLD"): p=None
    long_trigger=float(max(d5.get("swing_high",0),d5.get("high",0)) + 0.05*d5.get("atr",0)) if d5 else 0
    short_trigger=float(min(d5.get("swing_low",0),d5.get("low",0)) - 0.05*d5.get("atr",0)) if d5 else 0
    if setup=="NEWS HOLD": msg="Technical setup is valid, but high-impact event risk is blocking entry. Wait until the risk window clears; do not chase price."
    elif direction!="NONE": msg="Directional bias exists. Wait for the displayed trigger + 5m/1m SMC confirmation before placing the trade."
    else: msg="No directional alignment yet. Use the trigger levels as watch levels, not entries."
    return dict(direction=direction,confidence=conf,setup_label=setup,trade_plan=p,trade_message=msg,
                triggers={"long":long_trigger,"short":short_trigger},news=n,
                structure={"15m":d15,"5m":d5,"1m":d1},
                levels={"15m":{"high":d15.get("high"),"low":d15.get("low")},"5m":{"high":d5.get("high"),"low":d5.get("low")},"1m":{"high":d1.get("high"),"low":d1.get("low")}},
                data_warning=data.get("warning",""),source_line=data["source_line"],
                validation={"status":"V6/V7 closed-bar research mode. For real validation, use broker-quality XAU data and test out-of-sample before risking capital."})
