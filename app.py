
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone

from config import SYMBOL_SPOT, SYMBOL_FUTURES
from data import get_ohlcv_with_meta, news_snapshot
from engine import analyze_timeframe, score_setup, build_trade_plan, walk_forward_backtest

st.set_page_config(
    page_title="XAU/USD Intraday Engine",
    page_icon="🥇",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.block-container{padding-top:0.8rem;padding-bottom:2rem;max-width:1450px}
[data-testid="stMetric"]{padding:0.35rem 0}
.small{font-size:.86rem;opacity:.78}
.good{border-left:4px solid #22c55e;padding:.65rem .8rem;background:rgba(34,197,94,.08)}
.warn{border-left:4px solid #f59e0b;padding:.65rem .8rem;background:rgba(245,158,11,.08)}
.bad{border-left:4px solid #ef4444;padding:.65rem .8rem;background:rgba(239,68,68,.08)}
</style>
""", unsafe_allow_html=True)

st.title("🥇 XAU/USD Intraday Engine")
st.caption("15m context → 5m confirmation → 1m execution • strict confirmation • analysis only")

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60_000, key="gold_auto_refresh")
except Exception:
    pass


@st.cache_data(ttl=50, show_spinner=False)
def scan():
    market, meta = get_ohlcv_with_meta()
    analyses = {tf: analyze_timeframe(df) for tf, df in market.items()}
    news = news_snapshot()
    result = score_setup(
        analyses["15m"], analyses["5m"], analyses["1m"], news=news
    )
    plan = build_trade_plan(
        analyses["15m"], analyses["5m"], analyses["1m"], result
    )
    return market, meta, analyses, result, news, plan


try:
    market, meta, a, result, news, plan = scan()
except Exception as e:
    st.error(f"Scanner failed: {type(e).__name__}: {e}")
    st.info("Open Manage app → Logs if this persists. The engine is designed to fail safely rather than invent market data.")
    st.stop()

# ---------- Header / health ----------
available = [tf for tf in ["15m", "5m", "1m"] if meta[tf]["available"]]
proxy_tfs = [tf for tf in available if meta[tf]["is_proxy"]]

c = st.columns(6)
c[0].metric("Signal", result["signal"])
c[1].metric("Confidence", f"{result['confidence']:.0f}/100")
c[2].metric("LONG", f"{result['long_score']:.0f}")
c[3].metric("SHORT", f"{result['short_score']:.0f}")
c[4].metric("News dir.", f"{news['direction_score']:+.0f}")
c[5].metric("News risk", f"{news['risk_score']:.0f}/100")

health_text = []
for tf in ["15m", "5m", "1m"]:
    m = meta[tf]
    if m["available"]:
        src = "XAU spot" if m["source"] == SYMBOL_SPOT else "GC futures proxy"
        health_text.append(f"**{tf}:** {m['bars']} bars · {src}")
    else:
        health_text.append(f"**{tf}:** unavailable")

st.markdown(" · ".join(health_text))
if proxy_tfs:
    st.warning("Some intraday analysis is using GC=F (COMEX gold futures) as a transparent fallback because free XAU/USD spot candles are not always available. No candles are fabricated.")
if len(available) < 3:
    st.warning("The engine is in SAFE MODE: it will not issue an execution-ready trade unless 15m, 5m and 1m data are all available.")

st.caption("Last scan: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

# ---------- Signal state ----------
if result["signal"] in ("LONG", "SHORT") and plan:
    st.success(
        f"{plan['direction']} setup is execution-ready. "
        f"Entry {plan['entry']:.2f} · SL {plan['sl']:.2f} · "
        f"TP1 {plan['tp1']:.2f} · TP2 {plan['tp2']:.2f} · "
        f"risk {plan['risk_atr']:.2f} ATR"
    )
    st.caption(plan["invalidation_rule"])
elif result["signal"] == "NEWS HOLD":
    st.error(
        f"NO ENTRY: high-impact news risk is {news['risk_score']:.0f}/100. "
        "The directional setup and event risk are deliberately separated."
    )
elif result["signal"] in ("WATCH", "NO TRADE", "LONG", "SHORT"):
    reason = result.get("reasons_global", ["Waiting for the full 15m → 5m → 1m confirmation chain."])
    st.info(reason[0])

# ---------- Mobile section selector ----------
section = st.selectbox(
    "Dashboard section",
    ["📈 Annotated Chart", "🧠 Structure", "📰 News & Events", "🧪 Backtest", "📋 Rules"],
)

if section == "📈 Annotated Chart":
    tf = st.selectbox("Chart timeframe", ["15m", "5m", "1m"], index=2)
    df = a[tf]["data"].tail(350).copy()

    if df.empty:
        st.warning(
            f"No closed {tf} candles are available from the free feeds right now. "
            f"Source attempts: {', '.join(meta[tf].get('attempts', []))}. The engine will not create synthetic candles."
        )
    else:
        fig = go.Figure(go.Candlestick(
            x=df.index, open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name=SYMBOL_SPOT
        ))

        for level in a[tf]["liquidity"]["equal_highs"]:
            fig.add_hline(y=level, line_dash="dot", annotation_text="EQH")
        for level in a[tf]["liquidity"]["equal_lows"]:
            fig.add_hline(y=level, line_dash="dot", annotation_text="EQL")
        for level in a[tf]["liquidity"]["swing_highs"][-4:]:
            fig.add_hline(y=level, line_dash="dash", opacity=.35)
        for level in a[tf]["liquidity"]["swing_lows"][-4:]:
            fig.add_hline(y=level, line_dash="dash", opacity=.35)

        for o in a[tf]["ob"][-8:]:
            if o["index"] <= df.index[-1] and o["top"] >= df["low"].min() and o["bottom"] <= df["high"].max():
                x0 = max(o["index"], df.index[0])
                fill = "rgba(34,197,94,0.12)" if o["type"] == "BULLISH" else "rgba(239,68,68,0.12)"
                fig.add_shape(
                    type="rect", x0=x0, x1=df.index[-1],
                    y0=o["bottom"], y1=o["top"],
                    line_width=1, fillcolor=fill
                )

        for f in a[tf]["fvg"][-8:]:
            if f["index"] <= df.index[-1] and f["active"]:
                x0 = max(f["index"], df.index[0])
                fig.add_shape(
                    type="rect", x0=x0, x1=df.index[-1],
                    y0=f["bottom"], y1=f["top"],
                    line_width=0, fillcolor="rgba(59,130,246,0.12)"
                )

        sw = a[tf]["sweep"]
        if sw:
            fig.add_hline(y=sw["level"], line_width=3, annotation_text=f"{sw['type']} SWEEP")

        if plan and tf == "1m":
            fig.add_hline(y=plan["entry"], line_dash="dash", annotation_text="ENTRY")
            fig.add_hline(y=plan["sl"], line_dash="dot", annotation_text="INVALIDATION / SL")
            fig.add_hline(y=plan["tp1"], line_dash="dot", annotation_text="TP1")
            fig.add_hline(y=plan["tp2"], line_dash="dot", annotation_text="TP2")

        fig.update_layout(
            height=650, margin=dict(l=5, r=5, t=20, b=5),
            xaxis_rangeslider_visible=False, template="plotly_dark"
        )
        st.plotly_chart(fig, use_container_width=True)

        s = a[tf]["structure"]
        z = a[tf].get("near_fvg") or a[tf].get("near_ob")
        st.write(
            f"**{tf} closed-bar state:** Bias={s['bias']} · BOS={s['bos'] or '—'} · "
            f"CHoCH={s['choch'] or '—'} · Sweep={(a[tf]['sweep'] or {}).get('type','—')} · "
            f"Location={a[tf].get('premium_discount',{}).get('zone','—') if a[tf].get('premium_discount') else '—'}"
        )
        if z:
            st.write(
                f"Nearest active zone: **{z['type']}** "
                f"{z['bottom']:.2f}–{z['top']:.2f}"
            )

elif section == "🧠 Structure":
    cols = st.columns(3)
    for col, tf in zip(cols, ["15m", "5m", "1m"]):
        s = a[tf]["structure"]
        col.subheader(tf)
        col.metric("Bias", s["bias"])
        col.write(f"BOS: {s['bos'] or '—'}")
        col.write(f"CHoCH: {s['choch'] or '—'}")
        col.write(f"Displacement: {'YES' if s['displacement'] else 'NO'}")
        col.write(f"Sweep: {(a[tf]['sweep'] or {}).get('type', '—')}")
        col.write(f"Trigger: {'READY' if a[tf].get('trigger') else 'NO'}")

    st.subheader("Decision chain")
    for text in result.get("reasons_global", []):
        st.write("• " + text)

    left, right = st.columns(2)
    left.markdown("### LONG")
    for x in result["long_reasons"]:
        left.write("• " + x)
    right.markdown("### SHORT")
    for x in result["short_reasons"]:
        right.write("• " + x)

elif section == "📰 News & Events":
    st.metric("Directional news", f"{news['direction_score']:+.0f}/100")
    st.metric("Event risk", f"{news['risk_score']:.0f}/100")
    st.write(
        f"Direct gold influence: **{news['direct_score']:+.0f}** · "
        f"Indirect USD/macro influence: **{news['indirect_score']:+.0f}** · "
        f"High-impact events detected: **{news['high_impact_count']}**"
    )
    st.caption(
        "Direction answers 'which way does the information lean?'. "
        "Risk answers 'should we avoid entering around the event?'. "
        "They are intentionally separate."
    )

    st.subheader("Calendar / event risk")
    for item in news["events"][:15]:
        st.write(
            f"**{item['impact']}** · {item['title']} · "
            f"direction {item['delta']:+.1f} · {item['published']}"
        )

    st.subheader("Relevant headlines")
    for item in news["headlines"][:20]:
        title = item["title"]
        link = item.get("link", "")
        if link:
            st.markdown(f"**{item['delta']:+.1f} · {item['relevance']}** — [{title}]({link})")
        else:
            st.write(f"**{item['delta']:+.1f} · {item['relevance']}** — {title}")

elif section == "🧪 Backtest":
    st.subheader("Walk-forward validation — 5m structure engine")
    st.caption(
        "The replay uses only information available at each historical candle close. "
        "The final 30% is scored as out-of-sample (OOS) with the same fixed rules. "
        "No thresholds are tuned to the OOS segment. News is not retroactively guessed "
        "from today's RSS; therefore this structural test does not claim to validate the news filter."
    )
    df5 = market.get("5m", pd.DataFrame())
    if not df5.empty:
        bt = walk_forward_backtest(df5)
        if bt.get("error"):
            st.warning(bt["error"])
        else:
            all_s = bt.get("all", {})
            oos = bt.get("oos", {})
            ins = bt.get("in_sample", {})
            b = st.columns(5)
            b[0].metric("All trades", all_s.get("trades", 0))
            b[1].metric("OOS trades", oos.get("trades", 0))
            b[2].metric("OOS win rate", f"{oos.get('win_rate',0):.1f}%")
            b[3].metric("OOS net R", f"{oos.get('net_r',0):.2f}")
            b[4].metric("OOS PF", f"{oos.get('profit_factor',0):.2f}")

            st.markdown("### In-sample vs OOS")
            rows = []
            for name, stat in [("IN-SAMPLE", ins), ("OOS", oos)]:
                rows.append({
                    "Sample": name, "Trades": stat.get("trades",0),
                    "Win rate %": stat.get("win_rate",0), "Net R": stat.get("net_r",0),
                    "Avg R": stat.get("avg_r",0), "Profit factor": stat.get("profit_factor",0),
                    "Max DD R": stat.get("max_drawdown_r",0),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.markdown("### Session breakdown")
            sess_rows=[]
            for name, stat in bt.get("sessions", {}).items():
                sess_rows.append({"Session":name,"Trades":stat.get("trades",0),"Win rate %":stat.get("win_rate",0),"Net R":stat.get("net_r",0),"PF":stat.get("profit_factor",0)})
            st.dataframe(pd.DataFrame(sess_rows), use_container_width=True, hide_index=True)

            st.markdown("### Interpretation gates")
            if oos.get("trades", 0) < 20:
                st.warning("OOS sample is small. Do not treat the result as statistically meaningful yet.")
            elif oos.get("net_r", 0) <= 0 or oos.get("profit_factor", 0) <= 1:
                st.error("OOS result is not profitable under the current fixed rules. Do not trade this logic live.")
            else:
                st.success("OOS result is positive under the fixed replay assumptions. It still requires more data and independent validation before live use.")
    else:
        st.warning("5m data unavailable for validation.")

elif section == "📋 Rules":
    st.subheader("Permanent trading logic")
    st.markdown("""
**15m context**
- Only bullish structure allows long candidates; only bearish structure allows short candidates.
- BOS/CHoCH uses a **closed candle** beyond a confirmed swing by at least 0.15 ATR.

**5m confirmation**
- Must agree with 15m.
- Requires a fresh BOS/CHoCH.
- A-grade setup requires a liquidity sweep.
- Location preference: discount for longs, premium for shorts.

**1m execution**
- 1m cannot reverse the 15m bias.
- Requires aligned BOS/CHoCH + displacement + liquidity sweep.
- FVG/OB proximity adds confluence.
- If 1m data is missing, the engine goes into **SAFE MODE** and will not produce an execution-ready trade.

**Order blocks**
- Only the last opposite candle before a real displacement move is promoted.
- The block is invalidated by a closed candle through its far side.

**FVG**
- Minimum gap = 0.08 ATR.
- It becomes inactive after a close through the far side.

**Entry invalidation**
- Stop is anchored beyond the sweep/OB invalidation level with a 0.15 ATR buffer.
- A directional score alone can never authorize an entry; a valid trade plan must exist.
- If the 1m feed is unavailable, the system is SAFE MODE: no execution-ready signal.
- Risk must be between 0.60 and 2.50 ATR.
- The signal expires after 3 one-minute bars if it has not triggered.
- A high-impact event-risk score ≥55/100 blocks entry.

**News
- Directional score and event-risk score are separate.
- Directional news may add confluence but cannot override structure.
- High-impact event risk can veto an otherwise bullish/bearish setup.
- The backtest does not pretend that current news RSS can reconstruct historical event risk.
- Direct gold headlines, USD/DXY/yields and macro releases are weighted separately.
- High-impact USD events increase risk; they do not automatically choose LONG or SHORT.
""")

if st.button("🔄 Refresh now", use_container_width=True):
    st.cache_data.clear()
    st.rerun()
