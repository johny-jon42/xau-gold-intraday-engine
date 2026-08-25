"""
Minimal research backtest helper.

This intentionally does NOT pretend to simulate fills perfectly.
Use it to inspect how often a generated signal reaches a fixed R multiple
before the stop. A production backtester should model spread, slippage,
session rules, news latency, and intrabar ordering.
"""
import pandas as pd

def evaluate_entries(df, entries, risk_r=1.0):
    results = []
    for e in entries:
        entry = e["entry"]
        stop = e["stop"]
        direction = e["direction"]
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = entry + risk * risk_r if direction == "LONG" else entry - risk * risk_r

        future = df.loc[df.index > e["time"]]
        outcome = "OPEN"
        for _, bar in future.iterrows():
            if direction == "LONG":
                if bar["low"] <= stop:
                    outcome = "LOSS"; break
                if bar["high"] >= target:
                    outcome = "WIN"; break
            else:
                if bar["high"] >= stop:
                    outcome = "LOSS"; break
                if bar["low"] <= target:
                    outcome = "WIN"; break

        results.append({**e, "outcome": outcome})
    return pd.DataFrame(results)
