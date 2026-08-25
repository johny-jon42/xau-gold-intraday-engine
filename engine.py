import math
import re
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import streamlit as st


def atr(df, n=14):
    if df is None or len(df) < n + 1:
        return pd.Series(index=df.index if df is not None else [], dtype=float)
    h, l, c = df.High, df.Low, df.Close
    tr = pd.concat([(h-l), (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def _closed(df):
    if df is None or df.empty:
        return pd.DataFrame()
    return df.iloc[:-1].copy() if len(df) > 5 else df.copy()


def _confirmed_swings(df, left=2, right=2):
    d = df.copy()
    h = d.High.astype(float); l = d.Low.astype(float)
    sh = (h.shift(left) < h)
    sl = (l.shift(left) > l)
    for k in range(1, left + 1):
        sh &= h > h.shift(k)
        sl &= l < l.shift(k)
    for k in range(1, right + 1):
        sh &= h > h.shift(-k)
        sl &= l < l.shift(-k)
    sh = sh.fillna(False); sl = sl.fillna(False)
    return sh, sl


def _latest_pivots(d, limit=80):
    sh, sl = _confirmed_swings(d)
    highs = [(d.index[i], float(d.High.iloc[i])) for i in np.where(sh.values)[0]][-limit:]
    lows = [(d.index[i], float(d.Low.iloc[i])) for i in np.where(sl.values)[0]][-limit:]
    return highs, lows


def _fvg_candidates(d, aa, lookback=80):
    out = []
    if len(d) < 5 or not aa or np.isnan(aa):
        return out
    start = max(2, len(d) - lookback)
    for i in range(start, len(d)):
        # Three-candle imbalance, based on completed candles only.
        if float(d.Low.iloc[i]) > float(d.High.iloc[i-2]):
            gap = float(d.Low.iloc[i] - d.High.iloc[i-2])
            if gap >= 0.08 * aa:
                out.append({'type':'BULLISH FVG','low':float(d.High.iloc[i-2]),'high':float(d.Low.iloc[i]),'mid':float((d.High.iloc[i-2]+d.Low.iloc[i])/2),'created':d.index[i]})
        if float(d.High.iloc[i]) < float(d.Low.iloc[i-2]):
            gap = float(d.Low.iloc[i-2] - d.High.iloc[i])
            if gap >= 0.08 * aa:
                out.append({'type':'BEARISH FVG','low':float(d.High.iloc[i]),'high':float(d.Low.iloc[i-2]),'mid':float((d.High.iloc[i]+d.Low.iloc[i-2])/2),'created':d.index[i]})
    return out


def _ob_candidates(d, aa, lookback=60):
    out=[]
    if len(d)<8 or not aa or np.isnan(aa): return out
    start=max(3,len(d)-lookback)
    for i in range(start, len(d)):
        rng=float(d.High.iloc[i]-d.Low.iloc[i]); body=float(abs(d.Close.iloc[i]-d.Open.iloc[i]))
        if rng < 1.0*aa or body < 0.55*rng:
            continue
        # Strong displacement candle creates an OB from the last opposite candle.
        if d.Close.iloc[i] > d.Open.iloc[i]:
            for j in range(i-1, max(-1,i-6), -1):
                if d.Close.iloc[j] < d.Open.iloc[j]:
                    out.append({'type':'BULLISH OB','low':float(d.Low.iloc[j]),'high':float(d.High.iloc[j]),'mid':float((d.Low.iloc[j]+d.High.iloc[j])/2),'created':d.index[i],'origin':d.index[j]})
                    break
        else:
            for j in range(i-1, max(-1,i-6), -1):
                if d.Close.iloc[j] > d.Open.iloc[j]:
                    out.append({'type':'BEARISH OB','low':float(d.Low.iloc[j]),'high':float(d.High.iloc[j]),'mid':float((d.Low.iloc[j]+d.High.iloc[j])/2),'created':d.index[i],'origin':d.index[j]})
                    break
    return out


def _active_zones(d, aa):
    price=float(d.Close.iloc[-1])
    fvgs=_fvg_candidates(d,aa); obs=_ob_candidates(d,aa)
    zones=[]
    for z in fvgs + obs:
        # Invalidate a zone only after a later close crosses its far edge.
        created=z['created']; later=d.loc[d.index > created]
        invalid=False
        if z['type'].startswith('BULLISH') and not later.empty:
            invalid=bool((later.Close < z['low']).any())
        elif z['type'].startswith('BEARISH') and not later.empty:
            invalid=bool((later.Close > z['high']).any())
        if not invalid:
            z=dict(z); z['distance']=abs(price-z['mid']); zones.append(z)
    zones.sort(key=lambda x: (0 if x['low']<=price<=x['high'] else 1, x['distance']))
    return zones


def _structure_state(d):
    d=_closed(d)
    if len(d)<60: return {'bias':'RANGE','trend_score':50,'reason':['insufficient history']}
    aa=float(atr(d).iloc[-1]) if pd.notna(atr(d).iloc[-1]) else 0.0
    close=float(d.Close.iloc[-1]); ema20=float(d.Close.ewm(span=20,adjust=False).mean().iloc[-1]); ema50=float(d.Close.ewm(span=50,adjust=False).mean().iloc[-1])
    highs,lows=_latest_pivots(d)
    hs=[x[1] for x in highs]; ls=[x[1] for x in lows]
    score=50; reasons=[]
    if close>ema20: score+=7; reasons.append('price above EMA20')
    elif close<ema20: score-=7; reasons.append('price below EMA20')
    if close>ema50: score+=7; reasons.append('price above EMA50')
    elif close<ema50: score-=7; reasons.append('price below EMA50')
    if len(hs)>=2:
        if hs[-1]>hs[-2]: score+=13; reasons.append('higher swing high')
        elif hs[-1]<hs[-2]: score-=13; reasons.append('lower swing high')
    if len(ls)>=2:
        if ls[-1]>ls[-2]: score+=13; reasons.append('higher swing low')
        elif ls[-1]<ls[-2]: score-=13; reasons.append('lower swing low')
    if len(d)>=8:
        delta=float(d.Close.iloc[-1]-d.Close.iloc[-8])
        if aa and delta>0.35*aa: score+=5; reasons.append('recent upward displacement')
        elif aa and delta<-0.35*aa: score-=5; reasons.append('recent downward displacement')
    score=int(max(0,min(100,score)))
    bias='BULLISH' if score>=62 else 'BEARISH' if score<=38 else 'RANGE'
    # Last confirmed structure breaks.
    bos='—'; choch='—'; sweep='—'; sweep_level=None
    if highs and close>highs[-1][1] + 0.05*aa: bos='BULLISH'
    elif lows and close<lows[-1][1] - 0.05*aa: bos='BEARISH'
    if len(hs)>=3 and len(ls)>=3:
        prev='BULLISH' if hs[-2]>hs[-3] and ls[-2]>ls[-3] else 'BEARISH' if hs[-2]<hs[-3] and ls[-2]<ls[-3] else 'RANGE'
        if prev=='BEARISH' and bos=='BULLISH': choch='BULLISH'
        if prev=='BULLISH' and bos=='BEARISH': choch='BEARISH'
    # Liquidity sweep must be wick-through + close back inside prior pivot.
    if highs:
        level=highs[-1][1]
        if float(d.High.iloc[-1])>level and close<level: sweep='BUY-SIDE'; sweep_level=level
    if lows:
        level=lows[-1][1]
        if float(d.Low.iloc[-1])<level and close>level: sweep='SELL-SIDE'; sweep_level=level
    body=abs(float(d.Close.iloc[-1]-d.Open.iloc[-1])); displacement=bool(aa and body>=1.15*aa)
    zones=_active_zones(d,aa)
    bull_fvg=next((z for z in zones if z['type']=='BULLISH FVG'),None); bear_fvg=next((z for z in zones if z['type']=='BEARISH FVG'),None)
    bull_ob=next((z for z in zones if z['type']=='BULLISH OB'),None); bear_ob=next((z for z in zones if z['type']=='BEARISH OB'),None)
    rh=float(d.High.tail(40).max()); rl=float(d.Low.tail(40).min()); mid=(rh+rl)/2
    return {'bias':bias,'trend_score':score,'reason':reasons,'bos':bos,'choch':choch,'sweep':sweep,'sweep_level':sweep_level,'displacement':'YES' if displacement else 'NO','atr':aa,'high':rh,'low':rl,'close':close,'ema20':ema20,'ema50':ema50,'premium_discount':'DISCOUNT' if close<mid else 'PREMIUM','swing_high':hs[-1] if hs else rh,'swing_low':ls[-1] if ls else rl,'bull_fvg':bull_fvg,'bear_fvg':bear_fvg,'bull_ob':bull_ob,'bear_ob':bear_ob,'fvg':'BULLISH' if bull_fvg else 'BEARISH' if bear_fvg else '—','ob':'BULLISH' if bull_ob else 'BEARISH' if bear_ob else '—'}


def structure(df):
    return _structure_state(df)


@st.cache_data(ttl=120, show_spinner=False)
def news():
    urls=['https://www.forexfactory.com/calendar?day=today&format=rss','https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F&region=US&lang=en-US']
    items=[]; score=0; risk=0
    seen=set()
    high_terms=['fomc','powell','cpi','pce','nfp','payroll','fed','interest rate','ppi','gdp','jobs report','unemployment','retail sales','ism']
    bull_terms=['dovish','rate cut','weak jobs','lower inflation','yield fell','real yields fell','weaker dollar','dollar fell']
    bear_terms=['hawkish','rate hike','strong jobs','higher inflation','yield rose','real yields rose','strong dollar','dollar rose']
    for u in urls:
        try:
            req=Request(u,headers={'User-Agent':'Mozilla/5.0'}); root=ET.fromstring(urlopen(req,timeout=3).read())
            for it in root.iter():
                title=it.find('title')
                if title is None or not title.text: continue
                t=title.text.strip(); low=t.lower()
                if not t or t in seen: continue
                seen.add(t)
                impact='normal'
                if any(k in low for k in high_terms): risk=min(100,risk+20); impact='high'
                if any(k in low for k in bull_terms): score+=7
                if any(k in low for k in bear_terms): score-=7
                items.append({'headline':t[:180],'impact':impact})
        except Exception: pass
    score=int(max(-100,min(100,score)))
    return {'direction_score':score,'risk':min(100,risk),'bias':'BULLISH' if score>=8 else 'BEARISH' if score<=-8 else 'NEUTRAL','items':items[:20]}


def _zones_for_direction(direction,d5,d1):
    keys=('bull_fvg','bull_ob') if direction=='LONG' else ('bear_fvg','bear_ob')
    zs=[]
    for d in (d5,d1):
        for k in keys:
            if d.get(k): zs.append(d[k])
    return zs


def _risk_position(entry,sl,balance,risk_pct,contract_size,lot_step,min_lot,spread,slippage):
    max_risk=float(balance)*float(risk_pct)/100.0
    stop_dist=abs(entry-sl)
    effective_dist=stop_dist+max(0,float(spread))+max(0,float(slippage))
    raw=max_risk/(effective_dist*float(contract_size)) if effective_dist>0 and contract_size>0 else 0
    lots=math.floor(raw/lot_step+1e-9)*lot_step if lot_step>0 else raw
    lots=round(lots,8)
    if lots < min_lot:
        return {'ok':False,'reason':f'Broker minimum lot {min_lot:g} would exceed the selected risk limit. Calculated size is {raw:.4f} lots.','lots':0.0,'risk_usd':0.0,'max_risk':max_risk}
    actual_risk=effective_dist*contract_size*lots
    return {'ok':actual_risk<=max_risk*1.02,'reason':'OK' if actual_risk<=max_risk*1.02 else 'Normalized lot size exceeds risk limit.','lots':lots,'risk_usd':actual_risk,'max_risk':max_risk}


def _make_plan(direction,d5,d1,rr2,balance,risk_pct,contract_size,lot_step,min_lot,spread,slippage):
    if direction not in ('LONG','SHORT'): return None
    zones=_zones_for_direction(direction,d5,d1)
    price=float(d1['close']); a=float(d1.get('atr') or 0)
    if a<=0: return None
    # Prefer 5m POI; 1m zone is used for execution refinement.
    preferred=[z for z in zones if z['low']<=price<=z['high']]
    zone=preferred[0] if preferred else (min(zones,key=lambda z:abs(z['mid']-price)) if zones else None)
    if zone and abs(zone['mid']-price)<=1.25*a:
        entry=float(zone['mid'])
    else:
        entry=price
    if direction=='LONG':
        invalid=min(float(d5['swing_low']),float(d1['swing_low']))
        if d5.get('sweep')=='SELL-SIDE' and d5.get('sweep_level') is not None: invalid=min(invalid,float(d5['sweep_level']))
        if d1.get('sweep')=='SELL-SIDE' and d1.get('sweep_level') is not None: invalid=min(invalid,float(d1['sweep_level']))
        if zone: invalid=min(invalid,float(zone['low']))
        sl=invalid-0.08*a
        dist=entry-sl
        tp1=entry+dist
        tp2=entry+rr2*dist
    else:
        invalid=max(float(d5['swing_high']),float(d1['swing_high']))
        if d5.get('sweep')=='BUY-SIDE' and d5.get('sweep_level') is not None: invalid=max(invalid,float(d5['sweep_level']))
        if d1.get('sweep')=='BUY-SIDE' and d1.get('sweep_level') is not None: invalid=max(invalid,float(d1['sweep_level']))
        if zone: invalid=max(invalid,float(zone['high']))
        sl=invalid+0.08*a
        dist=sl-entry
        tp1=entry-dist
        tp2=entry-rr2*dist
    if dist<=0 or not 0.35*a<=dist<=2.5*a: return None
    risk=_risk_position(entry,sl,balance,risk_pct,contract_size,lot_step,min_lot,spread,slippage)
    if not risk['ok']: return {'valid':False,'reason':risk['reason'],'entry':entry,'sl':sl,'tp1':tp1,'tp2':tp2,'be_trigger':tp1,'zone':zone['type'] if zone else 'none','risk':dist,'risk_usd':risk['max_risk'],'lots':0.0,'units':0.0,'rr2':rr2}
    return {'valid':True,'entry':entry,'sl':sl,'tp1':tp1,'tp2':tp2,'be_trigger':entry,'be_trigger_price':tp1,'rr2':rr2,'risk':dist,'risk_usd':risk['risk_usd'],'max_risk':risk['max_risk'],'lots':risk['lots'],'units':risk['lots']*contract_size,'zone':zone['type'] if zone else 'CURRENT PRICE','instructions':f'{direction}: manual execution only. Wait for the 1m confirmation candle to close and price to retrace into the execution zone. Initial SL is structural. At +1R/TP1, take your chosen partial and move the remainder SL to entry only after TP1 is actually reached. Verify broker contract size, tick value, spread, slippage, minimum lot and lot step.'}


def _execution_state(direction,d5,d1):
    if direction not in ('LONG','SHORT'): return {'ready':False,'score':0,'checks':[]}
    side='BULLISH' if direction=='LONG' else 'BEARISH'
    sweep='SELL-SIDE' if direction=='LONG' else 'BUY-SIDE'
    checks=[]
    checks.append(('5m liquidity sweep', d5.get('sweep')==sweep))
    checks.append(('5m displacement', d5.get('displacement')=='YES'))
    checks.append(('5m BOS/CHoCH', d5.get('bos')==side or d5.get('choch')==side))
    checks.append(('5m POI', d5.get('fvg')==side or d5.get('ob')==side))
    checks.append(('1m liquidity sweep', d1.get('sweep')==sweep))
    checks.append(('1m displacement', d1.get('displacement')=='YES'))
    checks.append(('1m BOS/CHoCH', d1.get('bos')==side or d1.get('choch')==side))
    checks.append(('1m POI', d1.get('fvg')==side or d1.get('ob')==side))
    score=int(round(sum(ok for _,ok in checks)/len(checks)*100))
    return {'ready':score>=75,'score':score,'checks':checks}


def _watch_levels(direction,d5,d1):
    zones=_zones_for_direction(direction,d5,d1)
    if zones:
        z=min(zones,key=lambda x:abs(x['mid']-d1['close']))
        return float(z['low']),float(z['high']),z['type']
    if direction=='LONG': return float(d5['swing_high']),float(d5['swing_high']), '5m swing trigger'
    return float(d5['swing_low']),float(d5['swing_low']), '5m swing trigger'


def _resample_15m(df5):
    if df5 is None or df5.empty: return pd.DataFrame()
    x=df5.copy(); x.index=pd.to_datetime(x.index)
    return x.resample('15min').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()


def _replay_signal(d15,d5,d1,i5,rr2=2.5):
    # Closed-bar replay: decision is made at end of 5m bar i5 using only prior completed 1m bars.
    if i5<120: return None
    hist5=d5.iloc[:i5].copy(); h15=_resample_15m(hist5)
    if len(h15)<60 or len(hist5)<120: return None
    s15=structure(h15); s5=structure(hist5)
    direction='LONG' if s15['bias']=='BULLISH' else 'SHORT' if s15['bias']=='BEARISH' else None
    if not direction or s5['bias'] not in (('BULLISH' if direction=='LONG' else 'BEARISH'), 'RANGE'): return None
    # Require 5m setup ingredients before searching 1m execution.
    side='BULLISH' if direction=='LONG' else 'BEARISH'; sweep='SELL-SIDE' if direction=='LONG' else 'BUY-SIDE'
    five_ok=(s5['sweep']==sweep and s5['displacement']=='YES' and (s5['bos']==side or s5['choch']==side) and (s5['fvg']==side or s5['ob']==side))
    if not five_ok: return None
    ts=d5.index[i5-1]
    prior1=d1[d1.index<=ts]
    if len(prior1)<120: return None
    s1=structure(prior1)
    one_ok=(s1['sweep']==sweep and s1['displacement']=='YES' and (s1['bos']==side or s1['choch']==side) and (s1['fvg']==side or s1['ob']==side))
    if not one_ok: return None
    zones=_zones_for_direction(direction,s5,s1); zone=min(zones,key=lambda z:abs(z['mid']-s1['close'])) if zones else None
    entry=float(d1[d1.index>ts].iloc[0].Open) if not d1[d1.index>ts].empty else float(s1['close'])
    a=float(s1['atr']);
    if direction=='LONG':
        invalid=min(s5['swing_low'],s1['swing_low']); sl=invalid-0.08*a; tp=entry+rr2*(entry-sl)
    else:
        invalid=max(s5['swing_high'],s1['swing_high']); sl=invalid+0.08*a; tp=entry-rr2*(sl-entry)
    if (entry-sl if direction=='LONG' else sl-entry)<=0: return None
    return {'direction':direction,'entry':entry,'sl':sl,'tp':tp,'signal_time':d1.index[d1.index>ts][0] if not d1[d1.index>ts].empty else ts}


def validation(data,rr2=2.5):
    d5=data.get('5m'); d1=data.get('1m')
    if d5 is None or d1 is None or d5.empty or d1.empty:
        return {'status':'Missing 5m or 1m history; validation cannot run.','trades':0}
    d5=d5.copy(); d1=d1.copy(); d5.index=pd.to_datetime(d5.index); d1.index=pd.to_datetime(d1.index)
    # Bound research work so the mobile app does not spend minutes rebuilding thousands of structures.
    d5=d5.tail(420); d1=d1.tail(2200)
    if len(d5)<180 or len(d1)<300:
        return {'status':'Insufficient recent 5m/1m history for validation.','trades':0}
    split=int(len(d5)*0.70); rows=[]
    for i in range(max(130,split),len(d5)-1):
        sig=_replay_signal(None,d5,d1,i,rr2)
        if not sig: continue
        start=sig['signal_time']; future=d1[d1.index>=start].head(240)
        if future.empty: continue
        direction=sig['direction']; entry=sig['entry']; sl=sig['sl']; tp=sig['tp']; result=None
        for _,r in future.iterrows():
            hi=float(r.High); lo=float(r.Low)
            if direction=='LONG': hs=lo<=sl; ht=hi>=tp
            else: hs=hi>=sl; ht=lo<=tp
            if hs and ht: result=-1.0; break
            if hs: result=-1.0; break
            if ht: result=rr2; break
        if result is not None: rows.append({'time':sig['signal_time'],'r':result,'direction':direction,'oos':i>=split})
    if not rows: return {'status':'No qualifying full 15m→5m→1m setups in the recent validation sample.','trades':0}
    x=pd.DataFrame(rows); ins=x[~x.oos]; o=x[x.oos]
    def stats(z):
        if z.empty: return {'trades':0,'win_rate':None,'net_r':0.0,'avg_r':None,'profit_factor':None,'max_dd_r':0.0,'long_trades':0,'short_trades':0}
        eq=z.r.cumsum(); dd=eq-eq.cummax(); wins=float(z.loc[z.r>0,'r'].sum()); losses=abs(float(z.loc[z.r<0,'r'].sum()))
        return {'trades':int(len(z)),'win_rate':round(float((z.r>0).mean()*100),1),'net_r':round(float(z.r.sum()),2),'avg_r':round(float(z.r.mean()),3),'profit_factor':round(wins/losses,2) if losses else None,'max_dd_r':round(float(dd.min()),2),'long_trades':int((z.direction=='LONG').sum()),'short_trades':int((z.direction=='SHORT').sum())}
    return {'status':'Closed-bar 15m→5m→1m walk-forward research completed','in_sample':stats(ins),'out_of_sample':stats(o),'total':stats(x),'note':'Recent bounded sample for mobile responsiveness. Signals use completed candles only; same-candle SL+TP is counted as SL. This is research, not proof of profitability.'}


def analyze(data,rr2=2.5,news_hold=70,balance=10000,risk_pct=1.0,contract_size=100,lot_step=0.01,min_lot=0.01,spread=0.10,slippage=0.05,run_validation=False):
    d15=structure(data.get('15m')); d5=structure(data.get('5m')); d1=structure(data.get('1m')); n=news()
    source_ok=all('XAU spot' in data.get('source',{}).get(tf,'') for tf in ('15m','5m','1m'))
    required_ok=all(bool(data.get(tf) is not None and not data.get(tf).empty) for tf in ('15m','5m','1m'))
    direction='LONG' if d15.get('bias')=='BULLISH' else 'SHORT' if d15.get('bias')=='BEARISH' else 'NONE'
    conf=int(round(0.45*d15.get('trend_score',50)+0.35*d5.get('trend_score',50)+0.20*d1.get('trend_score',50)))
    exec_state=_execution_state(direction,d5,d1)
    p=None; setup='NO TRADE'
    if direction!='NONE' and required_ok:
        if exec_state['ready']:
            p=_make_plan(direction,d5,d1,rr2,balance,risk_pct,contract_size,lot_step,min_lot,spread,slippage)
            if p and p.get('valid'):
                if n['risk']>=news_hold: setup='NEWS HOLD'
                elif not source_ok: setup='RESEARCH ONLY'
                else: setup=f'{direction} READY'; conf=min(100,conf+10)
            elif p: setup='RISK BLOCK'
        else: setup=f'{direction} WATCH'
    if not required_ok: setup='DATA HOLD'
    if d15.get('bias')=='RANGE': setup='RANGE / WAIT'
    if setup=='NEWS HOLD': msg='Technical SMC setup is confirmed, but high-impact event risk is blocking the entry. Wait until the event-risk window clears.'
    elif setup=='RESEARCH ONLY': msg='Setup is technically confirmed, but at least one timeframe is using GC futures instead of XAU spot. Do not copy these prices to a spot/CFD account.'
    elif setup=='RISK BLOCK': msg=p.get('reason','Position sizing rejected the setup.') if p else 'Risk engine rejected the setup.'
    elif setup.endswith('WATCH'): msg='Direction is established, but the complete 5m→1m SMC execution sequence is not confirmed. Wait; do not enter at the watch price.'
    elif setup=='RANGE / WAIT': msg='15m structure is neutral. Wait for a confirmed 15m BOS/CHoCH and then the 5m/1m sequence.'
    elif setup=='DATA HOLD': msg='Required 15m, 5m and 1m data are not all available. No trade plan is produced.'
    else: msg='Confirmed SMC execution sequence. Verify your broker price/spread and manually place the order.'
    lz=_watch_levels('LONG',d5,d1); sz=_watch_levels('SHORT',d5,d1)
    val=validation(data,rr2) if run_validation else {'status':'Validation is OFF for fast live scanning. Enable it in the sidebar to run the bounded research test.'}
    return {'direction':direction,'confidence':conf,'setup_label':setup,'trade_plan':p,'trade_message':msg,'execution':exec_state,'triggers':{'long':lz,'short':sz},'news':n,'structure':{'15m':d15,'5m':d5,'1m':d1},'data_warning':data.get('warning',''),'source_line':data.get('source_line',''),'execution_grade':source_ok and required_ok,'validation':val}
