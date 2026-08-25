import numpy as np, pandas as pd, math, re
from urllib.request import urlopen, Request
from xml.etree import ElementTree as ET


def atr(df, n=14):
    h,l,c=df.High,df.Low,df.Close
    tr=pd.concat([(h-l),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(n,min_periods=n).mean()


def swings(df):
    h,l=df.High,df.Low
    return (h>h.shift(1))&(h>h.shift(-1)), (l<l.shift(1))&(l<l.shift(-1))


def _closed(df):
    if df is None or df.empty: return pd.DataFrame()
    return df.iloc[:-1].copy() if len(df)>5 else df.copy()


def _zones(d, aa):
    bull_fvg=bear_fvg=bull_ob=bear_ob=None
    if len(d)<8 or not aa or np.isnan(aa): return bull_fvg,bear_fvg,bull_ob,bear_ob
    for i in range(max(2,len(d)-50),len(d)):
        if d.Low.iloc[i]>d.High.iloc[i-2] and d.Low.iloc[i]-d.High.iloc[i-2]>=0.08*aa:
            bull_fvg={'type':'BULLISH FVG','low':float(d.High.iloc[i-2]),'high':float(d.Low.iloc[i]),'mid':float((d.High.iloc[i-2]+d.Low.iloc[i])/2)}
        if d.High.iloc[i]<d.Low.iloc[i-2] and d.Low.iloc[i-2]-d.High.iloc[i]>=0.08*aa:
            bear_fvg={'type':'BEARISH FVG','low':float(d.High.iloc[i]),'high':float(d.Low.iloc[i-2]),'mid':float((d.High.iloc[i]+d.Low.iloc[i-2])/2)}
    for i in range(max(3,len(d)-20),len(d)):
        rng=float(d.High.iloc[i]-d.Low.iloc[i]); body=float(abs(d.Close.iloc[i]-d.Open.iloc[i]))
        if rng<0.9*aa or body<0.55*aa: continue
        if d.Close.iloc[i]>d.Open.iloc[i]:
            for j in range(i-1,max(-1,i-5),-1):
                if d.Close.iloc[j]<d.Open.iloc[j]:
                    bull_ob={'type':'BULLISH OB','low':float(d.Low.iloc[j]),'high':float(d.High.iloc[j]),'mid':float((d.Low.iloc[j]+d.High.iloc[j])/2)}; break
        elif d.Close.iloc[i]<d.Open.iloc[i]:
            for j in range(i-1,max(-1,i-5),-1):
                if d.Close.iloc[j]>d.Open.iloc[j]:
                    bear_ob={'type':'BEARISH OB','low':float(d.Low.iloc[j]),'high':float(d.High.iloc[j]),'mid':float((d.Low.iloc[j]+d.High.iloc[j])/2)}; break
    return bull_fvg,bear_fvg,bull_ob,bear_ob


def structure(df):
    d=_closed(df)
    if d.empty: return {}
    a=atr(d); aa=float(a.iloc[-1]) if pd.notna(a.iloc[-1]) else 0.0
    sh,sl=swings(d); hi=d.High[sh].tolist(); lo=d.Low[sl].tolist(); close=float(d.Close.iloc[-1])
    ema20=float(d.Close.ewm(span=20,adjust=False).mean().iloc[-1]); ema50=float(d.Close.ewm(span=50,adjust=False).mean().iloc[-1])
    score=50
    if close>ema20: score+=8
    elif close<ema20: score-=8
    if close>ema50: score+=8
    elif close<ema50: score-=8
    if len(hi)>=2: score += 12 if hi[-1]>hi[-2] else -12 if hi[-1]<hi[-2] else 0
    if len(lo)>=2: score += 12 if lo[-1]>lo[-2] else -12 if lo[-1]<lo[-2] else 0
    # Recent closes add a small directional component without letting them override structure.
    if len(d)>=6:
        delta=float(d.Close.iloc[-1]-d.Close.iloc[-6]); score += 5 if delta>0 else -5 if delta<0 else 0
    score=int(max(0,min(100,score)))
    bias='BULLISH' if score>=58 else 'BEARISH' if score<=42 else 'RANGE'
    ph=hi[-1] if hi else float(d.High.tail(20).max()); pl=lo[-1] if lo else float(d.Low.tail(20).min())
    bos='—'
    if ph is not None and close>ph+0.05*aa: bos='BULLISH'
    elif pl is not None and close<pl-0.05*aa: bos='BEARISH'
    prior='RANGE'
    if len(hi)>=3 and len(lo)>=3:
        prior='BULLISH' if hi[-2]>hi[-3] and lo[-2]>lo[-3] else 'BEARISH' if hi[-2]<hi[-3] and lo[-2]<lo[-3] else 'RANGE'
    choch='BULLISH' if prior=='BEARISH' and bos=='BULLISH' else 'BEARISH' if prior=='BULLISH' and bos=='BEARISH' else '—'
    sweep='—'; sweep_level=None
    if len(hi)>=2 and float(d.High.tail(3).max())>hi[-1] and close<hi[-1]: sweep='BUY-SIDE'; sweep_level=float(hi[-1])
    if len(lo)>=2 and float(d.Low.tail(3).min())<lo[-1] and close>lo[-1]: sweep='SELL-SIDE'; sweep_level=float(lo[-1])
    body=float(abs(d.Close.iloc[-1]-d.Open.iloc[-1])); displacement='YES' if aa and body>=1.15*aa else 'NO'
    bf,rf,bo,ro=_zones(d,aa)
    rh=float(d.High.tail(20).max()); rl=float(d.Low.tail(20).min()); mid=(rh+rl)/2
    return {'bias':bias,'trend_score':score,'bos':bos,'choch':choch,'sweep':sweep,'sweep_level':sweep_level,'displacement':displacement,
            'fvg':'BULLISH' if bf else 'BEARISH' if rf else '—','ob':'BULLISH' if bo else 'BEARISH' if ro else '—','atr':aa,
            'high':rh,'low':rl,'close':close,'ema20':ema20,'ema50':ema50,'premium_discount':'DISCOUNT' if close<mid else 'PREMIUM',
            'bull_fvg':bf,'bear_fvg':rf,'bull_ob':bo,'bear_ob':ro,'swing_high':float(hi[-1]) if hi else rh,'swing_low':float(lo[-1]) if lo else rl,
            'last_candle_high':float(d.High.iloc[-1]),'last_candle_low':float(d.Low.iloc[-1])}


def news():
    urls=['https://www.forexfactory.com/calendar?day=today&format=rss','https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F&region=US&lang=en-US']
    items=[]; score=0; risk=0
    for u in urls:
        try:
            req=Request(u,headers={'User-Agent':'Mozilla/5.0'}); root=ET.fromstring(urlopen(req,timeout=5).read())
            for it in root.iter():
                title=it.find('title')
                if title is None or not title.text: continue
                t=title.text.strip(); low=t.lower()
                if not t or any(x['headline']==t for x in items): continue
                impact='normal'
                if any(k in low for k in ['fomc','powell','cpi','pce','nfp','payroll','fed','interest rate','ppi','gdp','jobs report']): risk=min(100,risk+25); impact='high'
                if any(k in low for k in ['dovish','rate cut','weak jobs','lower inflation','yield fell','real yields fell']): score+=8
                if any(k in low for k in ['hawkish','rate hike','strong jobs','higher inflation','yield rose','real yields rose']): score-=8
                items.append({'headline':t[:180],'impact':impact})
        except Exception: pass
    return {'direction_score':int(max(-100,min(100,score))),'risk':min(100,risk),'bias':'BULLISH' if score>=8 else 'BEARISH' if score<=-8 else 'NEUTRAL','items':items[:15]}


def _best_zone(direction,d1,d5):
    zs=[]
    keys=('bull_fvg','bull_ob') if direction=='LONG' else ('bear_fvg','bear_ob')
    for z in [d1.get(k) for k in keys]+[d5.get(k) for k in keys]:
        if z: zs.append(z)
    if not zs: return None
    price=d1['close']; valid=[z for z in zs if z['low']<=price<=z['high']]
    if valid: return valid[-1]
    return min(zs,key=lambda z:abs(z['mid']-price))


def plan(direction,d1,d5,rr2,balance,risk_pct,contract_size):
    a=float(d1.get('atr') or 0)
    if direction not in ('LONG','SHORT') or a<=0: return None
    zone=_best_zone(direction,d1,d5); entry=float(zone['mid'] if zone else d1['close'])
    if abs(entry-d1['close'])>1.5*a: entry=float(d1['close'])
    if direction=='LONG':
        invalid=min(float(d1['swing_low']),float(d5['swing_low']),float(d1.get('sweep_level') or d1['swing_low']))
        sl=min(invalid,float(zone['low']) if zone else invalid)-0.05*a; dist=entry-sl
        if dist<=0 or not 0.4*a<=dist<=2.75*a: return None
        tp1=entry+dist; tp2=entry+rr2*dist
    else:
        invalid=max(float(d1['swing_high']),float(d5['swing_high']),float(d1.get('sweep_level') or d1['swing_high']))
        sl=max(invalid,float(zone['high']) if zone else invalid)+0.05*a; dist=sl-entry
        if dist<=0 or not 0.4*a<=dist<=2.75*a: return None
        tp1=entry-dist; tp2=entry-rr2*dist
    risk_usd=float(balance)*float(risk_pct)/100; lots=risk_usd/(dist*float(contract_size)) if contract_size else 0
    return {'entry':entry,'sl':sl,'tp1':tp1,'tp2':tp2,'be_trigger':tp1,'rr2':rr2,'risk':dist,'risk_usd':risk_usd,'lots':lots,'units':lots*contract_size,
            'zone':zone['type'] if zone else 'CURRENT PRICE','instructions':f'{direction}: wait for the 1m confirmation candle to close. Initial SL is structural. Take partial profit at TP1 (1R), then move SL to entry only after TP1 is reached. Verify broker XAU contract size, spread and minimum lot.'}


def _signal_for_bar(df5, i, rr2=2.0):
    hist5=df5.iloc[:i].copy()
    if len(hist5)<120: return None
    # Build 15m context only from data available before the decision bar.
    h15=hist5.resample('15min').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    if len(h15)<80: return None
    d15=structure(h15); d5=structure(hist5)
    direction='LONG' if d15.get('bias')=='BULLISH' and d5.get('bias')=='BULLISH' else 'SHORT' if d15.get('bias')=='BEARISH' and d5.get('bias')=='BEARISH' else None
    if not direction: return None
    sweep_ok=d5.get('sweep')==('SELL-SIDE' if direction=='LONG' else 'BUY-SIDE')
    displacement=d5.get('displacement')=='YES'
    bos_ok=d5.get('bos')==direction or d5.get('choch')==direction
    zone_ok=d5.get('fvg')==('BULLISH' if direction=='LONG' else 'BEARISH') or d5.get('ob')==('BULLISH' if direction=='LONG' else 'BEARISH')
    if not ((bos_ok or sweep_ok) and displacement and zone_ok): return None
    # Next bar open is the earliest executable price, avoiding look-ahead.
    nxt=df5.iloc[i]
    entry=float(nxt.Open)
    a=float(d5.get('atr') or 0)
    if direction=='LONG': sl=min(float(d5['swing_low']),float(d5.get('sweep_level') or d5['swing_low']))-0.05*a; dist=entry-sl; tp=entry+rr2*dist
    else: sl=max(float(d5['swing_high']),float(d5.get('sweep_level') or d5['swing_high']))+0.05*a; dist=sl-entry; tp=entry-rr2*dist
    if dist<=0 or dist>2.75*a: return None
    return direction,entry,sl,tp


def validation(df5):
    if df5 is None or df5.empty or len(df5)<300: return {'status':'Insufficient 5m history','trades':0}
    df=df5.copy(); df.index=pd.to_datetime(df.index)
    # Warm-up + OOS split; no future bars are used for signals.
    split=int(len(df)*0.70); rows=[]
    for i in range(max(120,split),len(df)-1):
        sig=_signal_for_bar(df,i)
        if not sig: continue
        direction,entry,sl,tp=sig; result=None; r=None
        for j in range(i,min(i+80,len(df))):
            hi=float(df.High.iloc[j]); lo=float(df.Low.iloc[j])
            if direction=='LONG':
                hit_sl=lo<=sl; hit_tp=hi>=tp
            else: hit_sl=hi>=sl; hit_tp=lo<=tp
            if hit_sl and hit_tp: result=-1.0; break # conservative same-bar ambiguity
            if hit_sl: result=-1.0; break
            if hit_tp: result=2.0; break
        if result is not None: rows.append({'time':df.index[i],'r':result,'direction':direction,'oos':i>=split})
    if not rows: return {'status':'No qualifying closed-bar setups in OOS sample','trades':0,'oos_trades':0}
    x=pd.DataFrame(rows); o=x[x.oos]; ins=x[~x.oos]
    def stats(z):
        if z.empty: return {'trades':0,'win_rate':None,'net_r':0.0,'avg_r':None,'profit_factor':None,'max_dd_r':0.0}
        eq=z.r.cumsum(); peak=eq.cummax(); dd=eq-peak
        wins=z[z.r>0].r.sum(); losses=abs(z[z.r<0].r.sum()); pf=(wins/losses) if losses else None
        return {'trades':int(len(z)),'win_rate':round(float((z.r>0).mean()*100),1),'net_r':round(float(z.r.sum()),2),'avg_r':round(float(z.r.mean()),3),'profit_factor':round(float(pf),2) if pf else None,'max_dd_r':round(float(dd.min()),2)}
    return {'status':'Closed-bar walk-forward research completed','in_sample':stats(ins),'out_of_sample':stats(o),'total':stats(x),'note':'Signals use only candles available before entry. If SL and TP occur in the same candle, the backtest counts the trade as an SL for conservative treatment. This is research, not proof of profitability.'}


def analyze(data,rr2=2.5,news_hold=70,balance=10000,risk_pct=1.0,contract_size=100):
    d15=structure(data['15m']); d5=structure(data['5m']); d1=structure(data['1m']); n=news()
    # Directional lean: RANGE is allowed only as a watch state, never as confirmed direction.
    direction='LONG' if d15.get('bias')=='BULLISH' and d5.get('bias') in ('BULLISH','RANGE') else 'SHORT' if d15.get('bias')=='BEARISH' and d5.get('bias') in ('BEARISH','RANGE') else 'NONE'
    conf=int(round(d15.get('trend_score',50)*.4+d5.get('trend_score',50)*.35+d1.get('trend_score',50)*.25))
    setup='NO TRADE'; p=None
    if direction!='NONE':
        want='SELL-SIDE' if direction=='LONG' else 'BUY-SIDE'; side='BULLISH' if direction=='LONG' else 'BEARISH'
        five_ok=(d5.get('bos')==direction or d5.get('choch')==direction or d5.get('sweep')==want) and d5.get('displacement')=='YES'
        one_ok=(d1.get('bos')==direction or d1.get('choch')==direction or d1.get('sweep')==want) and d1.get('displacement')=='YES'
        smc_ok=any(d.get('fvg')==side or d.get('ob')==side for d in (d5,d1))
        p=plan(direction,d1,d5,rr2,balance,risk_pct,contract_size)
        if five_ok and one_ok and smc_ok and p:
            setup='NEWS HOLD' if n['risk']>=news_hold else f'{direction} READY'; conf=min(100,conf+12)
        else:
            p=None
    # Actionable watch zones even before full confirmation.
    long_zone=_best_zone('LONG',d1,d5); short_zone=_best_zone('SHORT',d1,d5)
    long_trigger=float((long_zone['mid'] if long_zone else d1.get('close',0)))
    short_trigger=float((short_zone['mid'] if short_zone else d1.get('close',0)))
    if setup=='NEWS HOLD': msg='Technical setup is valid, but event risk is blocking entry. Wait for the risk window to clear.'
    elif direction!='NONE': msg='Directional bias exists. Wait for the 5m structure/sweep and then the 1m confirmation before executing.'
    else: msg='15m is RANGE. No directional trade yet. Watch the SMC zones and wait for a 15m/5m directional break.'
    val=validation(data['5m'])
    return {'direction':direction,'confidence':conf,'setup_label':setup,'trade_plan':p,'trade_message':msg,
            'triggers':{'long':long_trigger,'short':short_trigger},'news':n,'structure':{'15m':d15,'5m':d5,'1m':d1},
            'levels':{'15m':{'high':d15.get('high'),'low':d15.get('low')},'5m':{'high':d5.get('high'),'low':d5.get('low')},'1m':{'high':d1.get('high'),'low':d1.get('low')}},
            'data_warning':data.get('warning',''),'source_line':data['source_line'],'validation':val}
