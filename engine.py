from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional
import numpy as np
import pandas as pd

from config import (
    SWING_LEFT, SWING_RIGHT, ATR_PERIOD,
    MIN_BREAK_ATR, MIN_DISPLACEMENT_BODY,
    DISPLACEMENT_ATR, EQUAL_LEVEL_ATR, SWEEP_MIN_ATR,
    MIN_FVG_ATR
)

def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    x = df.copy()
    if isinstance(x.columns, pd.MultiIndex):
        x.columns = [c[0] for c in x.columns]
    x.columns = [str(c).lower() for c in x.columns]
    x = x.rename(columns={"adj close": "close"})
    needed = ["open", "high", "low", "close"]
    x = x.dropna(subset=[c for c in needed if c in x.columns])
    return x

def atr(df, n=ATR_PERIOD):
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def add_features(df):
    x = normalize_ohlcv(df)
    if x.empty:
        return x
    x["atr"] = atr(x)
    x["body"] = (x["close"] - x["open"]).abs()
    x["range"] = x["high"] - x["low"]
    x["body_ratio"] = np.where(x["range"] > 0, x["body"] / x["range"], 0)
    x["bull"] = x["close"] > x["open"]
    x["bear"] = x["close"] < x["open"]

    x["swing_high"] = (
        (x["high"] > x["high"].shift(1)) &
        (x["high"] > x["high"].shift(2)) &
        (x["high"] > x["high"].shift(-1)) &
        (x["high"] > x["high"].shift(-2))
    )
    x["swing_low"] = (
        (x["low"] < x["low"].shift(1)) &
        (x["low"] < x["low"].shift(2)) &
        (x["low"] < x["low"].shift(-1)) &
        (x["low"] < x["low"].shift(-2))
    )
    return x

def recent_swings(df, lookback=100):
    x = df.tail(lookback)
    highs = x.loc[x["swing_high"], "high"].tolist()
    lows = x.loc[x["swing_low"], "low"].tolist()
    return highs, lows

def structure(df):
    x = add_features(df)
    if x.empty:
        return {"bias": "UNKNOWN", "bos": None, "choch": None, "swings": {}}

    last = x.iloc[-1]
    prev_highs = x.loc[x["swing_high"], "high"]
    prev_lows = x.loc[x["swing_low"], "low"]
    last_high = prev_highs.iloc[-1] if len(prev_highs) else np.nan
    last_low = prev_lows.iloc[-1] if len(prev_lows) else np.nan
    prev_high = prev_highs.iloc[-2] if len(prev_highs) >= 2 else np.nan
    prev_low = prev_lows.iloc[-2] if len(prev_lows) >= 2 else np.nan

    bullish_bos = bool(pd.notna(last_high) and last["close"] > last_high and
                       pd.notna(last["atr"]) and last["close"] - last_high >= MIN_BREAK_ATR * last["atr"])
    bearish_bos = bool(pd.notna(last_low) and last["close"] < last_low and
                       pd.notna(last["atr"]) and last_low - last["close"] >= MIN_BREAK_ATR * last["atr"])

    bullish_structure = pd.notna(last_high) and pd.notna(prev_high) and last_high > prev_high
    bearish_structure = pd.notna(last_low) and pd.notna(prev_low) and last_low < prev_low

    bias = "BULLISH" if bullish_structure else "BEARISH" if bearish_structure else "NEUTRAL"

    # CHoCH/MSS requires a prior directional structure and a break in the opposite direction.
    choch = None
    if bearish_structure and bullish_bos:
        choch = "BULLISH"
    elif bullish_structure and bearish_bos:
        choch = "BEARISH"

    bos = "BULLISH" if bullish_bos else "BEARISH" if bearish_bos else None

    return {
        "bias": bias,
        "bos": bos,
        "choch": choch,
        "last_high": float(last_high) if pd.notna(last_high) else None,
        "last_low": float(last_low) if pd.notna(last_low) else None,
        "swings": {
            "highs": prev_highs.tail(5).tolist(),
            "lows": prev_lows.tail(5).tolist(),
        }
    }

def detect_fvg(df):
    x = add_features(df)
    gaps = []
    for i in range(2, len(x)):
        a, c = x.iloc[i-2], x.iloc[i]
        atr_i = x.iloc[i]["atr"]
        if pd.isna(atr_i):
            continue
        if c["low"] > a["high"] and c["low"] - a["high"] >= MIN_FVG_ATR * atr_i:
            gaps.append({
                "type": "BULLISH", "top": float(c["low"]),
                "bottom": float(a["high"]), "index": x.index[i],
                "size": float(c["low"] - a["high"])
            })
        if c["high"] < a["low"] and a["low"] - c["high"] >= MIN_FVG_ATR * atr_i:
            gaps.append({
                "type": "BEARISH", "top": float(a["low"]),
                "bottom": float(c["high"]), "index": x.index[i],
                "size": float(a["low"] - c["high"])
            })
    return gaps[-20:]

def detect_order_blocks(df):
    x = add_features(df)
    obs = []
    for i in range(1, len(x) - 1):
        cur = x.iloc[i]
        nxt = x.iloc[i+1]
        if pd.isna(cur["atr"]) or pd.isna(nxt["atr"]):
            continue

        displacement = (
            nxt["body_ratio"] >= MIN_DISPLACEMENT_BODY and
            nxt["body"] >= DISPLACEMENT_ATR * nxt["atr"]
        )

        # Last bearish candle before bullish displacement = bullish OB.
        if cur["bear"] and nxt["bull"] and displacement:
            obs.append({
                "type": "BULLISH",
                "top": float(cur["high"]),
                "bottom": float(cur["low"]),
                "index": x.index[i],
                "score": 70
            })

        # Last bullish candle before bearish displacement = bearish OB.
        if cur["bull"] and nxt["bear"] and displacement:
            obs.append({
                "type": "BEARISH",
                "top": float(cur["high"]),
                "bottom": float(cur["low"]),
                "index": x.index[i],
                "score": 70
            })
    return obs[-20:]

def liquidity_levels(df):
    x = add_features(df)
    highs = x.loc[x["swing_high"], "high"].tolist()
    lows = x.loc[x["swing_low"], "low"].tolist()
    atr_now = x["atr"].iloc[-1] if len(x) else np.nan
    eq_highs, eq_lows = [], []

    if pd.notna(atr_now):
        tol = EQUAL_LEVEL_ATR * atr_now
        for i in range(len(highs)):
            for j in range(i+1, len(highs)):
                if abs(highs[i] - highs[j]) <= tol:
                    eq_highs.append(max(highs[i], highs[j]))
        for i in range(len(lows)):
            for j in range(i+1, len(lows)):
                if abs(lows[i] - lows[j]) <= tol:
                    eq_lows.append(min(lows[i], lows[j]))

    return {
        "swing_highs": highs[-10:],
        "swing_lows": lows[-10:],
        "equal_highs": sorted(set(eq_highs))[-5:],
        "equal_lows": sorted(set(eq_lows))[-5:]
    }

def detect_recent_sweep(df):
    x = add_features(df)
    if len(x) < 10:
        return None
    last = x.iloc[-1]
    atr_now = last["atr"]
    if pd.isna(atr_now):
        return None

    lv = liquidity_levels(x)
    candidates_high = lv["equal_highs"] + lv["swing_highs"][:-1]
    candidates_low = lv["equal_lows"] + lv["swing_lows"][:-1]

    for level in reversed(candidates_low):
        if last["low"] < level and last["close"] > level and level - last["low"] >= SWEEP_MIN_ATR * atr_now:
            return {"type": "SELL_SIDE", "level": float(level), "price": float(last["low"])}
    for level in reversed(candidates_high):
        if last["high"] > level and last["close"] < level and last["high"] - level >= SWEEP_MIN_ATR * atr_now:
            return {"type": "BUY_SIDE", "level": float(level), "price": float(last["high"])}
    return None

def premium_discount(df):
    x = add_features(df)
    if x.empty:
        return None
    hi = x["high"].tail(100).max()
    lo = x["low"].tail(100).min()
    mid = (hi + lo) / 2
    price = x["close"].iloc[-1]
    return {
        "high": float(hi), "low": float(lo), "mid": float(mid),
        "zone": "DISCOUNT" if price < mid else "PREMIUM"
    }

def analyze_timeframe(df):
    return {
        "structure": structure(df),
        "fvg": detect_fvg(df),
        "ob": detect_order_blocks(df),
        "liquidity": liquidity_levels(df),
        "sweep": detect_recent_sweep(df),
        "premium_discount": premium_discount(df),
    }

def score_setup(a15, a5, a1, news_score=0, dxy_score=0, yield_score=0):
    long_score = 0
    short_score = 0
    reasons_long, reasons_short = [], []

    def add(direction, pts, reason):
        nonlocal long_score, short_score
        if direction == "LONG":
            long_score += pts; reasons_long.append(reason)
        else:
            short_score += pts; reasons_short.append(reason)

    # 15m: 25 points
    s15 = a15["structure"]
    if s15["bias"] == "BULLISH": add("LONG", 10, "15m bullish structure")
    if s15["bias"] == "BEARISH": add("SHORT", 10, "15m bearish structure")
    if s15["choch"] == "BULLISH": add("LONG", 5, "15m bullish CHoCH")
    if s15["choch"] == "BEARISH": add("SHORT", 5, "15m bearish CHoCH")
    if a15["sweep"] and a15["sweep"]["type"] == "SELL_SIDE": add("LONG", 5, "15m sell-side liquidity swept")
    if a15["sweep"] and a15["sweep"]["type"] == "BUY_SIDE": add("SHORT", 5, "15m buy-side liquidity swept")
    if any(o["type"] == "BULLISH" for o in a15["ob"][-3:]): add("LONG", 3, "15m bullish OB")
    if any(o["type"] == "BEARISH" for o in a15["ob"][-3:]): add("SHORT", 3, "15m bearish OB")
    if any(f["type"] == "BULLISH" for f in a15["fvg"][-3:]): add("LONG", 2, "15m bullish FVG")
    if any(f["type"] == "BEARISH" for f in a15["fvg"][-3:]): add("SHORT", 2, "15m bearish FVG")

    # 5m: 25 points
    s5 = a5["structure"]
    if s5["bos"] == "BULLISH": add("LONG", 7, "5m bullish BOS")
    if s5["bos"] == "BEARISH": add("SHORT", 7, "5m bearish BOS")
    if s5["choch"] == "BULLISH": add("LONG", 7, "5m bullish CHoCH")
    if s5["choch"] == "BEARISH": add("SHORT", 7, "5m bearish CHoCH")
    if a5["sweep"] and a5["sweep"]["type"] == "SELL_SIDE": add("LONG", 6, "5m sell-side sweep")
    if a5["sweep"] and a5["sweep"]["type"] == "BUY_SIDE": add("SHORT", 6, "5m buy-side sweep")
    if any(f["type"] == "BULLISH" for f in a5["fvg"][-2:]): add("LONG", 5, "5m bullish FVG")
    if any(f["type"] == "BEARISH" for f in a5["fvg"][-2:]): add("SHORT", 5, "5m bearish FVG")

    # 1m: 20 points
    s1 = a1["structure"]
    if s1["choch"] == "BULLISH": add("LONG", 7, "1m bullish CHoCH")
    if s1["choch"] == "BEARISH": add("SHORT", 7, "1m bearish CHoCH")
    if s1["bos"] == "BULLISH": add("LONG", 5, "1m bullish BOS")
    if s1["bos"] == "BEARISH": add("SHORT", 5, "1m bearish BOS")
    if a1["sweep"] and a1["sweep"]["type"] == "SELL_SIDE": add("LONG", 5, "1m sell-side sweep")
    if a1["sweep"] and a1["sweep"]["type"] == "BUY_SIDE": add("SHORT", 5, "1m buy-side sweep")
    if any(f["type"] == "BULLISH" for f in a1["fvg"][-2:]): add("LONG", 3, "1m bullish FVG")
    if any(f["type"] == "BEARISH" for f in a1["fvg"][-2:]): add("SHORT", 3, "1m bearish FVG")

    # Macro/news: directional scores are -100..100.
    if news_score > 0: add("LONG", min(10, news_score / 10), "gold news bullish")
    if news_score < 0: add("SHORT", min(10, abs(news_score) / 10), "gold news bearish")
    if dxy_score > 0: add("LONG", min(5, dxy_score / 20), "DXY supportive")
    if dxy_score < 0: add("SHORT", min(5, abs(dxy_score) / 20), "DXY supportive")
    if yield_score > 0: add("LONG", min(5, yield_score / 20), "yields supportive")
    if yield_score < 0: add("SHORT", min(5, abs(yield_score) / 20), "yields supportive")

    # The raw points can exceed 100 because the detectors are intentionally overlapping.
    long_score = min(100, round(long_score, 1))
    short_score = min(100, round(short_score, 1))

    if max(long_score, short_score) >= 85:
        signal = "LONG" if long_score > short_score else "SHORT"
        confidence = max(long_score, short_score)
    elif max(long_score, short_score) >= 75:
        signal = "LONG" if long_score > short_score else "SHORT"
        confidence = max(long_score, short_score)
    elif max(long_score, short_score) >= 65:
        signal = "WATCH"
        confidence = max(long_score, short_score)
    else:
        signal = "NO TRADE"
        confidence = max(long_score, short_score)

    return {
        "signal": signal,
        "long_score": long_score,
        "short_score": short_score,
        "confidence": confidence,
        "long_reasons": reasons_long,
        "short_reasons": reasons_short,
    }
