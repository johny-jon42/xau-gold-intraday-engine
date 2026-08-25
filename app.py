import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
from engine import analyze
from data import load_all

st.set_page_config(page_title='XAU/USD Intraday Engine V9', page_icon='🥇', layout='wide')
st.title('🥇 XAU/USD SMC Intraday Engine V9')
st.caption('15m bias → 5m SMC setup → 1m execution • manual execution only')

with st.sidebar:
    st.header('Risk & broker settings')
    balance=st.number_input('Account balance (USD)',min_value=10.0,value=10000.0,step=100.0)
    risk_pct=st.number_input('Risk per trade (%)',min_value=0.1,max_value=5.0,value=1.0,step=0.1)
    contract_size=st.number_input('XAU contract size (oz / 1 lot)',min_value=1.0,value=100.0,step=1.0)
    lot_step=st.number_input('Lot step',min_value=0.001,value=0.01,step=0.01,format='%.3f')
    min_lot=st.number_input('Minimum lot',min_value=0.001,value=0.01,step=0.01,format='%.3f')
    spread=st.number_input('Estimated spread ($/oz)',min_value=0.0,value=0.10,step=0.01)
    slippage=st.number_input('Estimated slippage ($/oz)',min_value=0.0,value=0.05,step=0.01)
    rr2=st.slider('TP2 target (R)',1.5,5.0,2.5,0.25)
    news_hold=st.slider('News hold threshold',50,100,70,5)
    refresh=st.slider('Refresh target (seconds)',30,300,60,30)
    st.info('The app never places orders. It calculates a manual trade plan. Verify broker contract/tick specifications before using the size.')
    if st.button('🔄 Refresh now'): st.rerun()

data=load_all()
result=analyze(data,rr2,news_hold,balance,risk_pct,contract_size,lot_step,min_lot,spread,slippage)
if result['data_warning']: st.warning(result['data_warning'])

m1,m2,m3,m4=st.columns(4)
m1.metric('Setup',result['setup_label'])
m2.metric('Confidence',f"{result['confidence']}/100")
m3.metric('Direction',result['direction'])
m4.metric('News risk',f"{result['news']['risk']}/100")
st.caption(result['source_line'])

if result['trade_plan'] and result['trade_plan'].get('valid'):
    p=result['trade_plan']; st.subheader('🎯 MANUAL EXECUTION PLAN')
    if result['setup_label']=='NEWS HOLD': st.warning('Technical setup is valid, but NEWS HOLD blocks entry right now.')
    elif result['setup_label']=='RESEARCH ONLY': st.warning('Research-only setup: do not copy these levels to a spot/CFD broker while a futures proxy is being used.')
    else: st.success(f"{result['direction']} confirmed. Execute manually only after the 1m confirmation candle closes and the price is in the execution zone.")
    c=st.columns(7)
    for col,label,val in zip(c,['ENTRY','SL','TP1 (1R)','TP2','BE AFTER TP1','R:R','ZONE'],[f"{p['entry']:.2f}",f"{p['sl']:.2f}",f"{p['tp1']:.2f}",f"{p['tp2']:.2f}",f"{p['be_trigger_price']:.2f}",f"{p['rr2']:.2f}R",p['zone']]): col.metric(label,val)
    q=st.columns(5)
    q[0].metric('Max risk',f"${p['max_risk']:,.2f}"); q[1].metric('Estimated risk',f"${p['risk_usd']:,.2f}"); q[2].metric('Position',f"{p['lots']:.3f} lots"); q[3].metric('Units',f"{p['units']:.1f} oz"); q[4].metric('Stop distance',f"{p['risk']:.2f}")
    st.info(p['instructions'])
else:
    st.warning(result['trade_message'])
    a,b=st.columns(2)
    for col,label,key in [(a,'LONG WATCH ZONE','long'),(b,'SHORT WATCH ZONE','short')]:
        lo,hi,typ=result['triggers'][key]
        col.metric(label,f'{lo:.2f} – {hi:.2f}')
        col.caption(f'{typ}. This is NOT an entry. Wait for the complete SMC sequence.')

st.divider()
tabs=st.tabs(['📈 Chart + levels','🧠 SMC Structure','📰 News','🧪 Validation','📋 Trade Rules'])
with tabs[0]:
    tf=st.selectbox('Chart timeframe',['15m','5m','1m'],index=1)
    df=data.get(tf)
    if df is None or df.empty: st.error(f'No usable {tf} data.')
    else:
        d=df.tail(220).copy(); fig=go.Figure([go.Candlestick(x=d.index,open=d.Open,high=d.High,low=d.Low,close=d.Close,name=tf)])
        p=result.get('trade_plan')
        if p and p.get('valid'):
            for name,val,dash in [('ENTRY',p['entry'],'solid'),('SL',p['sl'],'dash'),('TP1',p['tp1'],'dot'),('TP2',p['tp2'],'dashdot'),('BE',p['be_trigger_price'],'longdash')]: fig.add_hline(y=val,line_dash=dash,annotation_text=name,annotation_position='top left')
            fig.add_hrect(y0=p['entry'] if result['direction']=='LONG' else p['entry'], y1=p['tp1'] if result['direction']=='LONG' else p['tp1'], opacity=0.05, line_width=0)
        s=result['structure'][tf]
        for key,label in [('swing_high','Swing High'),('swing_low','Swing Low')]:
            if s.get(key): fig.add_hline(y=s[key],line_dash='dash',annotation_text=label,annotation_position='bottom right')
        for zkey in [('bull_fvg','Bull FVG'),('bear_fvg','Bear FVG'),('bull_ob','Bull OB'),('bear_ob','Bear OB')]:
            z=s.get(zkey[0])
            if z: fig.add_hrect(y0=z['low'],y1=z['high'],opacity=0.10,line_width=1,annotation_text=zkey[1])
        fig.update_layout(height=560,margin=dict(l=10,r=10,t=30,b=10),xaxis_rangeslider_visible=False)
        st.plotly_chart(fig,use_container_width=True)
        st.caption(f'{tf}: {len(df)} bars • {data["source"].get(tf,"unknown")} • current levels are not broker execution guarantees')
with tabs[1]:
    for tf in ['15m','5m','1m']:
        s=result['structure'][tf]; st.subheader(tf)
        st.write({'Bias':s['bias'],'Trend score':s['trend_score'],'BOS':s['bos'],'CHoCH':s['choch'],'Liquidity sweep':s['sweep'],'Displacement':s['displacement'],'FVG':s['fvg'],'OB':s['ob'],'Premium/Discount':s['premium_discount'],'Swing high':s['swing_high'],'Swing low':s['swing_low']})
        st.caption(' • '.join(s.get('reason',[])))
    st.subheader('Execution checklist')
    for name,ok in result['execution']['checks']:
        st.write(('✅ ' if ok else '⬜ ')+name)
    st.metric('Execution score',f"{result['execution']['score']}/100")
with tabs[2]:
    n=result['news']; c=st.columns(3); c[0].metric('Directional score',f"{n['direction_score']:+d}"); c[1].metric('Event risk',f"{n['risk']}/100"); c[2].metric('Gold bias',n['bias'])
    if n['items']: st.dataframe(pd.DataFrame(n['items']),use_container_width=True)
    else: st.info('No news items retrieved. Treat event risk conservatively.')
with tabs[3]:
    st.subheader('Exact 15m → 5m → 1m closed-bar validation')
    st.caption('Research only. No future candle is used to create the signal. Same-candle SL+TP is treated as an SL.')
    v=result['validation']; st.info(v.get('status','Unknown'))
    if v.get('in_sample'):
        c=st.columns(3)
        for col,title,key in zip(c,['In-sample','Out-of-sample','Combined'],['in_sample','out_of_sample','total']):
            col.markdown(f'### {title}'); col.json(v[key])
    st.caption(v.get('note',''))
with tabs[4]:
    st.markdown('''### Professional SMC execution rules\n\n**15m bias:** confirmed swing progression + structure; EMA alignment is secondary context, not the trigger. RANGE means wait.\n\n**5m setup:** same-direction liquidity sweep → displacement → BOS/CHoCH → valid FVG/OB POI.\n\n**1m execution:** same-direction sweep → displacement → BOS/CHoCH → FVG/OB; then retracement into the POI.\n\n**Entry:** POI midpoint when the confirmed execution sequence is complete; otherwise no entry.\n\n**SL:** beyond the structural invalidation/sweep/POI with an ATR buffer. A closed 1m candle through invalidation cancels the setup.\n\n**TP1:** 1R. **Break-even:** only after TP1/1R is actually reached. **TP2:** user-selected R multiple.\n\n**Position sizing:** max risk = balance × risk %. Size uses entry→SL plus spread/slippage and broker lot step/minimum. If the minimum lot would exceed the selected risk, the trade is rejected.\n\n**News:** directional pressure and event risk are separate. High-impact risk can block a technically valid setup.\n\n**Data:** XAU spot is required for execution-grade levels. GC futures is allowed only as a clearly labelled research proxy.\n\n**Manual only:** no broker login, order placement, or automated execution is performed by this app.''')

st.caption(f"Last scan: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} • Refresh target: {refresh}s")
