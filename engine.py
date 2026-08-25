
import numpy as np
import pandas as pd

from config import (
    ATR_PERIOD, MIN_BREAK_ATR, MIN_DISPLACEMENT_BODY, DISPLACEMENT_ATR,
    EQUAL_LEVEL_ATR, SWEEP_MIN_ATR, MIN_FVG_ATR, SWING_LEFT, SWING_RIGHT,
    MIN_SIGNAL, MIN_WATCH, MAX_NEWS_RISK_FOR_ENTRY, MAX_SIGNAL_AGE_BARS,
    SL_ATR_BUFFER, MIN_RISK_ATR, MAX_RISK_ATR, TP1_R, TP2_R,
)


OHLC = ["open", "high", "low", "close"]


def normalize_ohlcv(df):
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=OHLC)
    x = df.copy()
    if isinstance(x.columns, pd.MultiIndex):
        cols = []
        for col in x.columns:
            parts = [str(p) for p in col]
            match = next((p for p in parts if p.lower() in OHLC + ["adj close", "volume"]), parts[0])
            cols.append(match)
        x.columns = cols
    x.columns = [str(c).strip().lower().replace(" ", "_") for c in x.columns]
    x = x.loc[:, ~x.columns.duplicated(keep="first")]
    missing = [c for c in OHLC if c not in x.columns]
    if missing:
        return pd.DataFrame(columns=OHLC)
    for c in OHLC:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=OHLC).copy()
    return x.sort_index()


def _closed(df):
    x = normalize_ohlcv(df)
    # The newest bar can still be forming. All signals are based on the last CLOSED bar.
    if len(x) > 2:
        return x.iloc[:-1].copy()
    return x


def add_features(df):
    x = _closed(df)
    if x.empty:
        return x
    prev_close = x["close"].shift(1)
    tr = pd.concat([
        (x["high"] - x["low"]).abs(),
        (x["high"] - prev_close).abs(),
        (x["low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    x["atr"] = tr.rolling(ATR_PERIOD, min_periods=ATR_PERIOD).mean()
    x["body"] = (x["close"] - x["open"]).abs()
    x["range"] = (x["high"] - x["low"]).abs()
    x["body_ratio"] = np.where(x["range"] > 0, x["body"] / x["range"], 0.0)
    x["bull"] = x["close"] > x["open"]
    x["bear"] = x["close"] < x["open"]
    x["swing_high"] = (
        (x["high"] > x["high"].shift(SWING_LEFT)) &
        (x["high"] > x["high"].shift(-SWING_RIGHT))
    )
    x["swing_low"] = (
        (x["low"] < x["low"].shift(SWING_LEFT)) &
        (x["low"] < x["low"].shift(-SWING_RIGHT))
    )
    return x


def _last_confirmed_swings(x):
    highs = x.loc[x["swing_high"], ["high"]].copy()
    lows = x.loc[x["swing_low"], ["low"]].copy()
    return highs, lows


def structure(df):
    x = add_features(df)
    base = {
        "bias": "UNKNOWN", "bos": None, "choch": None,
        "last_high": None, "last_low": None, "break_level": None,
        "event_index": None, "event_age": None, "displacement": False
    }
    if len(x) < max(ATR_PERIOD + 5, 20):
        return base

    highs, lows = _last_confirmed_swings(x)
    if len(highs) < 2 or len(lows) < 2:
        return base

    lh, ph = float(highs.iloc[-1]["high"]), float(highs.iloc[-2]["high"])
    ll, pl = float(lows.iloc[-1]["low"]), float(lows.iloc[-2]["low"])

    bull_struct = lh > ph and ll > pl
    bear_struct = lh < ph and ll < pl
    bias = "BULLISH" if bull_struct else "BEARISH" if bear_struct else "RANGE"

    last = x.iloc[-1]
    atr = last["atr"]
    if pd.isna(atr) or atr <= 0:
        return {**base, "bias": bias, "last_high": lh, "last_low": ll}

    # A structure break must be a CLOSED candle beyond the confirmed swing by a minimum ATR fraction.
    bull_break = last["close"] > lh and last["close"] - lh >= MIN_BREAK_ATR * atr
    bear_break = last["close"] < ll and ll - last["close"] >= MIN_BREAK_ATR * atr

    displacement = bool(
        last["body_ratio"] >= MIN_DISPLACEMENT_BODY and
        last["body"] >= DISPLACEMENT_ATR * atr
    )

    bos = None
    choch = None
    if bull_break:
        bos = "BULLISH" if bias in ("BULLISH", "RANGE") else None
        choch = "BULLISH" if bias == "BEARISH" else None
    elif bear_break:
        bos = "BEARISH" if bias in ("BEARISH", "RANGE") else None
        choch = "BEARISH" if bias == "BULLISH" else None

    return {
        "bias": bias,
        "bos": bos,
        "choch": choch,
        "last_high": lh,
        "last_low": ll,
        "break_level": lh if bull_break else ll if bear_break else None,
        "event_index": x.index[-1] if (bull_break or bear_break) else None,
        "event_age": 0 if (bull_break or bear_break) else None,
        "displacement": displacement,
    }


def detect_fvg(df):
    x = add_features(df)
    out = []
    if len(x) < 10:
        return out

    for i in range(2, len(x)):
        a = x.iloc[i - 2]
        b = x.iloc[i - 1]
        c = x.iloc[i]
        atr = c["atr"]
        if pd.isna(atr) or atr <= 0:
            continue

        # Three-candle imbalance: the middle candle is the displacement candle.
        if c["low"] > a["high"] and c["low"] - a["high"] >= MIN_FVG_ATR * atr:
            out.append({
                "type": "BULLISH", "top": float(c["low"]), "bottom": float(a["high"]),
                "index": x.index[i], "active": True, "displacement": bool(
                    b["body_ratio"] >= MIN_DISPLACEMENT_BODY and b["body"] >= DISPLACEMENT_ATR * atr
                )
            })
        elif c["high"] < a["low"] and a["low"] - c["high"] >= MIN_FVG_ATR * atr:
            out.append({
                "type": "BEARISH", "top": float(a["low"]), "bottom": float(c["high"]),
                "index": x.index[i], "active": True, "displacement": bool(
                    b["body_ratio"] >= MIN_DISPLACEMENT_BODY and b["body"] >= DISPLACEMENT_ATR * atr
                )
            })

    # A gap is inactive after price closes through the far side.
    for f in out:
        later = x.loc[x.index > f["index"]]
        if f["type"] == "BULLISH" and len(later):
            if (later["close"] < f["bottom"]).any():
                f["active"] = False
        elif f["type"] == "BEARISH" and len(later):
            if (later["close"] > f["top"]).any():
                f["active"] = False
    return out[-25:]


def detect_order_blocks(df):
    x = add_features(df)
    s = structure(df)
    out = []
    if len(x) < 15:
        return out

    # Only promote an OB when it is followed by a real displacement candle
    # that also creates a structure break. This prevents "every opposite candle = OB".
    for i in range(2, len(x)):
        nxt = x.iloc[i]
        atr = nxt["atr"]
        if pd.isna(atr) or atr <= 0:
            continue
        displacement = (
            nxt["body_ratio"] >= MIN_DISPLACEMENT_BODY and
            nxt["body"] >= DISPLACEMENT_ATR * atr
        )
        if not displacement:
            continue

        prior = x.iloc[max(0, i - 6):i]
        if prior.empty:
            continue

        # Bullish displacement: last bearish candle before the move.
        if nxt["bull"]:
            candidates = prior[prior["bear"]]
            if len(candidates):
                ob = candidates.iloc[-1]
                out.append({
                    "type": "BULLISH",
                    "top": float(ob["high"]),
                    "bottom": float(ob["low"]),
                    "index": ob.name,
                    "score": 75,
                    "active": True,
                    "displacement_index": nxt.name
                })
        # Bearish displacement: last bullish candle before the move.
        elif nxt["bear"]:
            candidates = prior[prior["bull"]]
            if len(candidates):
                ob = candidates.iloc[-1]
                out.append({
                    "type": "BEARISH",
                    "top": float(ob["high"]),
                    "bottom": float(ob["low"]),
                    "index": ob.name,
                    "score": 75,
                    "active": True,
                    "displacement_index": nxt.name
                })

    # Invalidation = CLOSE through the far side of the block.
    for o in out:
        later = x.loc[x.index > o["index"]]
        if o["type"] == "BULLISH" and len(later) and (later["close"] < o["bottom"]).any():
            o["active"] = False
        if o["type"] == "BEARISH" and len(later) and (later["close"] > o["top"]).any():
            o["active"] = False
    return out[-25:]


def liquidity_levels(df):
    x = add_features(df)
    if x.empty:
        return {"swing_highs": [], "swing_lows": [], "equal_highs": [], "equal_lows": []}
    highs = x.loc[x["swing_high"], "high"].tolist()
    lows = x.loc[x["swing_low"], "low"].tolist()
    atr = x["atr"].iloc[-1]
    tol = float(EQUAL_LEVEL_ATR * atr) if pd.notna(atr) else 0
    eh, el = [], []
    if tol > 0:
        for i in range(len(highs)):
            for j in range(i + 1, len(highs)):
                if abs(highs[i] - highs[j]) <= tol:
                    eh.append((highs[i] + highs[j]) / 2)
        for i in range(len(lows)):
            for j in range(i + 1, len(lows)):
                if abs(lows[i] - lows[j]) <= tol:
                    el.append((lows[i] + lows[j]) / 2)
    return {
        "swing_highs": [float(v) for v in highs[-12:]],
        "swing_lows": [float(v) for v in lows[-12:]],
        "equal_highs": [float(v) for v in sorted(set(eh))[-6:]],
        "equal_lows": [float(v) for v in sorted(set(el))[-6:]],
    }


def detect_recent_sweep(df):
    x = add_features(df)
    if len(x) < 12 or pd.isna(x["atr"].iloc[-1]):
        return None

    # Do not use the current swing itself as liquidity; only prior levels.
    prior = x.iloc[:-1]
    lv = liquidity_levels(prior)
    last = x.iloc[-1]
    atr = float(last["atr"])

    sell_levels = lv["equal_lows"] + lv["swing_lows"][-5:]
    buy_levels = lv["equal_highs"] + lv["swing_highs"][-5:]

    # Prefer the nearest relevant level.
    for level in sorted(set(sell_levels), reverse=True):
        if last["low"] < level and last["close"] > level and level - last["low"] >= SWEEP_MIN_ATR * atr:
            return {
                "type": "SELL_SIDE", "level": float(level), "price": float(last["low"]),
                "index": x.index[-1], "age": 0
            }

    for level in sorted(set(buy_levels)):
        if last["high"] > level and last["close"] < level and last["high"] - level >= SWEEP_MIN_ATR * atr:
            return {
                "type": "BUY_SIDE", "level": float(level), "price": float(last["high"]),
                "index": x.index[-1], "age": 0
            }
    return None


def premium_discount(df):
    x = add_features(df)
    if x.empty:
        return None
    # Use the most recent structural range rather than arbitrary last-100 extremes.
    hi = float(x["high"].tail(100).max())
    lo = float(x["low"].tail(100).min())
    mid = (hi + lo) / 2
    price = float(x["close"].iloc[-1])
    return {
        "high": hi, "low": lo, "mid": mid, "price": price,
        "zone": "DISCOUNT" if price < mid else "PREMIUM"
    }


def _near_zone(price, zones, atr, tolerance_atr=0.25):
    if price is None or not zones or pd.isna(atr) or atr <= 0:
        return None
    tol = tolerance_atr * atr
    best = None
    best_dist = 1e99
    for z in zones:
        if not z.get("active", True):
            continue
        dist = 0 if z["bottom"] <= price <= z["top"] else min(abs(price-z["bottom"]), abs(price-z["top"]))
        if dist <= tol and dist < best_dist:
            best, best_dist = z, dist
    return best


def analyze_timeframe(df):
    data = add_features(df)
    if data.empty:
        return {
            "data": data, "structure": structure(df), "fvg": [], "ob": [],
            "liquidity": liquidity_levels(df), "sweep": None,
            "premium_discount": None, "trigger": False
        }
    s = structure(df)
    fvg = detect_fvg(df)
    ob = detect_order_blocks(df)
    atr = data["atr"].iloc[-1]
    price = float(data["close"].iloc[-1])
    sweep = detect_recent_sweep(df)
    near_fvg = _near_zone(price, fvg[-8:], atr)
    near_ob = _near_zone(price, ob[-8:], atr)

    # 1m trigger quality: structure break/CHoCH must be accompanied by a sweep,
    # displacement, or zone retest. Higher timeframes can use broader confirmation.
    trigger = bool(
        sweep is not None and
        (s["bos"] or s["choch"]) and
        s["displacement"]
    )
    return {
        "data": data, "structure": s, "fvg": fvg, "ob": ob,
        "liquidity": liquidity_levels(df), "sweep": sweep,
        "premium_discount": premium_discount(df),
        "near_fvg": near_fvg, "near_ob": near_ob, "trigger": trigger
    }


def _add(scores, reasons, side, pts, reason):
    scores[side] += pts
    reasons[side].append(f"+{pts}: {reason}")


def score_setup(a15, a5, a1, news=None):
    scores = {"LONG": 0.0, "SHORT": 0.0}
    reasons = {"LONG": [], "SHORT": []}

    # Hard directional context: 15m decides the side. We do not allow 5m/1m
    # to overpower a clearly opposite 15m structure.
    b15 = a15["structure"]["bias"]
    if b15 == "BULLISH":
        _add(scores, reasons, "LONG", 25, "15m bullish structure")
    elif b15 == "BEARISH":
        _add(scores, reasons, "SHORT", 25, "15m bearish structure")
    else:
        return _result(scores, reasons, "15m is not directional")

    # 5m must agree with 15m and produce a fresh break/CHoCH.
    b5 = a5["structure"]["bias"]
    if (b15 == "BULLISH" and b5 == "BULLISH"):
        _add(scores, reasons, "LONG", 15, "5m aligns with 15m")
    elif (b15 == "BEARISH" and b5 == "BEARISH"):
        _add(scores, reasons, "SHORT", 15, "5m aligns with 15m")
    else:
        return _result(scores, reasons, "5m does not confirm 15m direction")

    s5 = a5["structure"]
    if b15 == "BULLISH" and s5["bos"] == "BULLISH":
        _add(scores, reasons, "LONG", 15, "fresh 5m bullish BOS")
    elif b15 == "BEARISH" and s5["bos"] == "BEARISH":
        _add(scores, reasons, "SHORT", 15, "fresh 5m bearish BOS")
    elif b15 == "BULLISH" and s5["choch"] == "BULLISH":
        _add(scores, reasons, "LONG", 10, "5m bullish CHoCH")
    elif b15 == "BEARISH" and s5["choch"] == "BEARISH":
        _add(scores, reasons, "SHORT", 10, "5m bearish CHoCH")

    # Liquidity event is mandatory for an A-grade scalp.
    if b15 == "BULLISH" and a5["sweep"] and a5["sweep"]["type"] == "SELL_SIDE":
        _add(scores, reasons, "LONG", 12, "5m sell-side liquidity sweep")
    elif b15 == "BEARISH" and a5["sweep"] and a5["sweep"]["type"] == "BUY_SIDE":
        _add(scores, reasons, "SHORT", 12, "5m buy-side liquidity sweep")

    # Location: trade from discount for longs / premium for shorts.
    pd5 = a5["premium_discount"]
    if pd5:
        if b15 == "BULLISH" and pd5["zone"] == "DISCOUNT":
            _add(scores, reasons, "LONG", 8, "5m discount")
        if b15 == "BEARISH" and pd5["zone"] == "PREMIUM":
            _add(scores, reasons, "SHORT", 8, "5m premium")

    # 1m is execution only. It cannot flip the 15m direction.
    b1 = a1["structure"]["bias"]
    s1 = a1["structure"]
    side = "LONG" if b15 == "BULLISH" else "SHORT"

    aligned_trigger = (
        (side == "LONG" and s1["bos"] == "BULLISH") or
        (side == "SHORT" and s1["bos"] == "BEARISH") or
        (side == "LONG" and s1["choch"] == "BULLISH") or
        (side == "SHORT" and s1["choch"] == "BEARISH")
    )
    if aligned_trigger:
        _add(scores, reasons, side, 12, "1m aligned structure trigger")
    if a1["sweep"] and (
        (side == "LONG" and a1["sweep"]["type"] == "SELL_SIDE") or
        (side == "SHORT" and a1["sweep"]["type"] == "BUY_SIDE")
    ):
        _add(scores, reasons, side, 10, "1m liquidity sweep")
    if a1.get("near_fvg"):
        z = a1["near_fvg"]
        if (side == "LONG" and z["type"] == "BULLISH") or (side == "SHORT" and z["type"] == "BEARISH"):
            _add(scores, reasons, side, 5, "1m FVG location")
    if a1.get("near_ob"):
        z = a1["near_ob"]
        if (side == "LONG" and z["type"] == "BULLISH") or (side == "SHORT" and z["type"] == "BEARISH"):
            _add(scores, reasons, side, 5, "1m order-block location")
    if s1["displacement"] and aligned_trigger:
        _add(scores, reasons, side, 5, "1m displacement")

    # News is a separate axis: direction adds a little, risk can veto the trade.
    news = news or {}
    nd = float(news.get("direction_score", 0))
    nr = float(news.get("risk_score", 0))
    if abs(nd) >= 15:
        if side == "LONG" and nd > 0:
            _add(scores, reasons, "LONG", 5, f"news direction supports gold ({nd:+.0f})")
        elif side == "SHORT" and nd < 0:
            _add(scores, reasons, "SHORT", 5, f"news direction supports gold downside ({nd:+.0f})")
        elif side == "LONG" and nd < 0:
            scores["LONG"] -= 5; reasons["LONG"].append(f"-5: news direction conflicts ({nd:+.0f})")
        elif side == "SHORT" and nd > 0:
            scores["SHORT"] -= 5; reasons["SHORT"].append(f"-5: news direction conflicts ({nd:+.0f})")

    result = _result(scores, reasons, "")
    result["news_direction"] = nd
    result["news_risk"] = nr
    result["hard_news_block"] = nr >= MAX_NEWS_RISK_FOR_ENTRY
    result["execution_ready"] = bool(
        result["signal"] in ("LONG", "SHORT") and
        a1.get("trigger", False) and
        not result["hard_news_block"]
    )
    if result["hard_news_block"]:
        result["reasons_global"] = [f"NO ENTRY: high-impact news risk {nr:.0f}/100"]
        result["signal"] = "NEWS HOLD"
    return result


def _result(scores, reasons, global_reason):
    L = round(max(0, min(100, scores["LONG"])), 1)
    S = round(max(0, min(100, scores["SHORT"])), 1)
    best = max(L, S)
    if L > S and L >= MIN_SIGNAL:
        signal = "LONG"
    elif S > L and S >= MIN_SIGNAL:
        signal = "SHORT"
    elif best >= MIN_WATCH:
        signal = "WATCH"
    else:
        signal = "NO TRADE"
    return {
        "signal": signal,
        "long_score": L,
        "short_score": S,
        "confidence": best,
        "long_reasons": reasons["LONG"],
        "short_reasons": reasons["SHORT"],
        "reasons_global": [global_reason] if global_reason else [],
    }


def _invalidation_for(side, a1, a5, price, atr):
    zones = []
    if side == "LONG":
        if a1.get("near_ob") and a1["near_ob"]["type"] == "BULLISH":
            zones.append(a1["near_ob"]["bottom"])
        if a5.get("near_ob") and a5["near_ob"]["type"] == "BULLISH":
            zones.append(a5["near_ob"]["bottom"])
        if a1.get("sweep") and a1["sweep"]["type"] == "SELL_SIDE":
            zones.append(a1["sweep"]["price"])
        if a5.get("sweep") and a5["sweep"]["type"] == "SELL_SIDE":
            zones.append(a5["sweep"]["price"])
        base = min(zones) if zones else price - atr
        return base - SL_ATR_BUFFER * atr
    else:
        if a1.get("near_ob") and a1["near_ob"]["type"] == "BEARISH":
            zones.append(a1["near_ob"]["top"])
        if a5.get("near_ob") and a5["near_ob"]["type"] == "BEARISH":
            zones.append(a5["near_ob"]["top"])
        if a1.get("sweep") and a1["sweep"]["type"] == "BUY_SIDE":
            zones.append(a1["sweep"]["price"])
        if a5.get("sweep") and a5["sweep"]["type"] == "BUY_SIDE":
            zones.append(a5["sweep"]["price"])
        base = max(zones) if zones else price + atr
        return base + SL_ATR_BUFFER * atr


def build_trade_plan(a15, a5, a1, result):
    if not result.get("execution_ready"):
        return None

    data = a1.get("data")
    if data is None or data.empty:
        return None

    price = float(data["close"].iloc[-1])
    atr = float(data["atr"].iloc[-1]) if pd.notna(data["atr"].iloc[-1]) else price * 0.001
    if atr <= 0:
        return None

    direction = result["signal"]
    invalidation = _invalidation_for(direction, a1, a5, price, atr)

    if direction == "LONG":
        risk = price - invalidation
        if risk <= 0:
            return None
        risk_atr = risk / atr
        if risk_atr < MIN_RISK_ATR or risk_atr > MAX_RISK_ATR:
            return None
        sl = invalidation
        tp1 = price + TP1_R * risk
        tp2 = price + TP2_R * risk
    else:
        risk = invalidation - price
        if risk <= 0:
            return None
        risk_atr = risk / atr
        if risk_atr < MIN_RISK_ATR or risk_atr > MAX_RISK_ATR:
            return None
        sl = invalidation
        tp1 = price - TP1_R * risk
        tp2 = price - TP2_R * risk

    return {
        "direction": direction,
        "entry": price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk": abs(risk),
        "risk_atr": round(risk_atr, 2),
        "rr_tp2": TP2_R,
        "invalidation_rule": (
            "Invalidate if a CLOSED 1m candle closes beyond SL / the swept extreme, "
            "or if the 1m trigger structure is broken before entry."
        ),
        "expiry_bars": MAX_SIGNAL_AGE_BARS,
    }


def simple_backtest(df, horizon=12, min_score=75):
    x = normalize_ohlcv(df)
    if len(x) < 300:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "avg_r": 0, "net_r": 0}

    trades = []
    step = max(1, horizon // 2)

    for i in range(220, len(x) - horizon - 2, step):
        w = x.iloc[:i + 1]
        a = analyze_timeframe(w)
        s = a["structure"]
        direction = "LONG" if s["bos"] == "BULLISH" or s["choch"] == "BULLISH" else \
                    "SHORT" if s["bos"] == "BEARISH" or s["choch"] == "BEARISH" else None
        if not direction:
            continue
        if not a["sweep"] or not s["displacement"]:
            continue

        entry = float(x["close"].iloc[i])
        atr = float(a["data"]["atr"].iloc[-1]) if pd.notna(a["data"]["atr"].iloc[-1]) else 0
        if atr <= 0:
            continue

        if direction == "LONG":
            sl = float(a["sweep"]["price"]) - SL_ATR_BUFFER * atr
            if sl >= entry:
                continue
            risk = entry - sl
            tp = entry + 2.0 * risk
        else:
            sl = float(a["sweep"]["price"]) + SL_ATR_BUFFER * atr
            if sl <= entry:
                continue
            risk = sl - entry
            tp = entry - 2.0 * risk

        if risk / atr < MIN_RISK_ATR or risk / atr > MAX_RISK_ATR:
            continue

        future = x.iloc[i + 1:i + 1 + horizon]
        result = None
        for _, r in future.iterrows():
            if direction == "LONG":
                # Conservative: if both touched in same candle, count the stop first.
                if r["low"] <= sl:
                    result = -1.0
                    break
                if r["high"] >= tp:
                    result = 2.0
                    break
            else:
                if r["high"] >= sl:
                    result = -1.0
                    break
                if r["low"] <= tp:
                    result = 2.0
                    break
        if result is not None:
            trades.append(result)

    wins = sum(v > 0 for v in trades)
    losses = sum(v < 0 for v in trades)
    return {
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": round(100 * wins / len(trades), 1) if trades else 0,
        "avg_r": round(float(np.mean(trades)), 2) if trades else 0,
        "net_r": round(float(np.sum(trades)), 2) if trades else 0,
    }

# ---------------------------------------------------------------------------
# V5 validation engine: closed-bar replay + walk-forward diagnostics
# ---------------------------------------------------------------------------
from config import (
    BACKTEST_MIN_BARS, BACKTEST_HORIZON_BARS, BACKTEST_STEP_BARS,
    BACKTEST_OOS_FRACTION, BACKTEST_MIN_TRADES,
    LONDON_START_UTC, LONDON_END_UTC, NEW_YORK_START_UTC, NEW_YORK_END_UTC,
)


def _closed_replay_features(df):
    """Feature set for historical replay where the final row is KNOWN closed.
    This deliberately duplicates add_features() without dropping the last row,
    preventing look-ahead while allowing a decision exactly at a historical close.
    """
    x = normalize_ohlcv(df)
    if x.empty:
        return x
    prev_close = x["close"].shift(1)
    tr = pd.concat([
        (x["high"] - x["low"]).abs(),
        (x["high"] - prev_close).abs(),
        (x["low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    x["atr"] = tr.rolling(ATR_PERIOD, min_periods=ATR_PERIOD).mean()
    x["body"] = (x["close"] - x["open"]).abs()
    x["range"] = (x["high"] - x["low"]).abs()
    x["body_ratio"] = np.where(x["range"] > 0, x["body"] / x["range"], 0.0)
    x["bull"] = x["close"] > x["open"]
    x["bear"] = x["close"] < x["open"]
    x["swing_high"] = (
        (x["high"] > x["high"].shift(SWING_LEFT)) &
        (x["high"] > x["high"].shift(-SWING_RIGHT))
    )
    x["swing_low"] = (
        (x["low"] < x["low"].shift(SWING_LEFT)) &
        (x["low"] < x["low"].shift(-SWING_RIGHT))
    )
    return x


def _replay_structure(df):
    x = _closed_replay_features(df)
    base = {"bias":"UNKNOWN","bos":None,"choch":None,"last_high":None,"last_low":None,
            "break_level":None,"event_index":None,"event_age":None,"displacement":False}
    if len(x) < max(ATR_PERIOD + 8, 30):
        return base
    # Only swings that are confirmed by the right-side lookback are eligible.
    confirmed = x.iloc[:-SWING_RIGHT] if len(x) > SWING_RIGHT else x.iloc[0:0]
    highs = confirmed.loc[confirmed["swing_high"], "high"]
    lows = confirmed.loc[confirmed["swing_low"], "low"]
    if len(highs) < 2 or len(lows) < 2:
        return base
    lh, ph = float(highs.iloc[-1]), float(highs.iloc[-2])
    ll, pl = float(lows.iloc[-1]), float(lows.iloc[-2])
    bull_struct = lh > ph and ll > pl
    bear_struct = lh < ph and ll < pl
    bias = "BULLISH" if bull_struct else "BEARISH" if bear_struct else "RANGE"
    last = x.iloc[-1]
    atr = last["atr"]
    if pd.isna(atr) or atr <= 0:
        return {**base,"bias":bias,"last_high":lh,"last_low":ll}
    bull_break = last["close"] > lh and last["close"] - lh >= MIN_BREAK_ATR * atr
    bear_break = last["close"] < ll and ll - last["close"] >= MIN_BREAK_ATR * atr
    displacement = bool(last["body_ratio"] >= MIN_DISPLACEMENT_BODY and last["body"] >= DISPLACEMENT_ATR * atr)
    bos = choch = None
    if bull_break:
        bos = "BULLISH" if bias in ("BULLISH","RANGE") else None
        choch = "BULLISH" if bias == "BEARISH" else None
    elif bear_break:
        bos = "BEARISH" if bias in ("BEARISH","RANGE") else None
        choch = "BEARISH" if bias == "BULLISH" else None
    return {"bias":bias,"bos":bos,"choch":choch,"last_high":lh,"last_low":ll,
            "break_level":lh if bull_break else ll if bear_break else None,
            "event_index":x.index[-1] if (bull_break or bear_break) else None,
            "event_age":0 if (bull_break or bear_break) else None,"displacement":displacement}


def _replay_sweep(df):
    x = _closed_replay_features(df)
    if len(x) < 30 or pd.isna(x["atr"].iloc[-1]):
        return None
    confirmed = x.iloc[:-SWING_RIGHT] if len(x) > SWING_RIGHT else x.iloc[0:0]
    highs = confirmed.loc[confirmed["swing_high"], "high"].tolist()
    lows = confirmed.loc[confirmed["swing_low"], "low"].tolist()
    if not highs and not lows:
        return None
    atr = float(x["atr"].iloc[-1])
    last = x.iloc[-1]
    tol = EQUAL_LEVEL_ATR * atr
    sell = list(lows[-8:]); buy = list(highs[-8:])
    for vals, typ in [ (sell, "SELL_SIDE"), (buy, "BUY_SIDE") ]:
        for level in sorted(set(vals), reverse=(typ=="SELL_SIDE")):
            if typ == "SELL_SIDE" and last["low"] < level <= last["close"] and level-last["low"] >= SWEEP_MIN_ATR*atr:
                return {"type":typ,"level":float(level),"price":float(last["low"]),"index":x.index[-1],"age":0}
            if typ == "BUY_SIDE" and last["high"] > level >= last["close"] and last["high"]-level >= SWEEP_MIN_ATR*atr:
                return {"type":typ,"level":float(level),"price":float(last["high"]),"index":x.index[-1],"age":0}
    # Equal-level clusters get priority when close enough.
    return None


def _replay_trigger(df):
    s = _replay_structure(df)
    sw = _replay_sweep(df)
    return s, sw, bool(sw is not None and (s["bos"] or s["choch"]) and s["displacement"])


def _session(ts):
    try:
        h = pd.Timestamp(ts).tz_convert("UTC").hour if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).hour
    except Exception:
        return "UNKNOWN"
    if LONDON_START_UTC <= h < LONDON_END_UTC:
        return "LONDON"
    if NEW_YORK_START_UTC <= h < NEW_YORK_END_UTC:
        return "NEW_YORK"
    return "OTHER"


def _trade_outcome(df, entry_i, side, sl, tp1, tp2, horizon):
    future = df.iloc[entry_i+1:entry_i+1+horizon]
    for j, r in future.iterrows():
        if side == "LONG":
            sl_hit = r["low"] <= sl
            tp2_hit = r["high"] >= tp2
            tp1_hit = r["high"] >= tp1
        else:
            sl_hit = r["high"] >= sl
            tp2_hit = r["low"] <= tp2
            tp1_hit = r["low"] <= tp1
        if sl_hit:
            return -1.0, "SL", j
        if tp2_hit:
            return 2.0, "TP2", j
        if tp1_hit:
            return 1.0, "TP1", j
    return 0.0, "TIMEOUT", future.index[-1] if len(future) else None


def walk_forward_backtest(df, horizon=None, oos_fraction=None):
    """Closed-bar, no-lookahead validation on 5m data with 15m context resampled.
    The last OOS fraction is never used to set thresholds; it is only scored.
    """
    x = normalize_ohlcv(df)
    if len(x) < BACKTEST_MIN_BARS:
        return {"error":f"Need at least {BACKTEST_MIN_BARS} 5m bars; got {len(x)}.","trades":0}
    horizon = horizon or BACKTEST_HORIZON_BARS
    oos_fraction = oos_fraction or BACKTEST_OOS_FRACTION
    split = int(len(x) * (1-oos_fraction))
    records = []
    # Build 15m bars from 5m data to keep the replay source consistent.
    m15 = x.resample("15min", label="right", closed="right").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    for i in range(max(250, SWING_RIGHT+30), split):
        if i + horizon >= len(x): break
        hist5 = x.iloc[:i+1]
        ts = x.index[i]
        hist15 = m15.loc[m15.index <= ts]
        if len(hist15) < 40:
            continue
        s15 = _replay_structure(hist15)
        s5, sw5, trig5 = _replay_trigger(hist5)
        if s15["bias"] not in ("BULLISH","BEARISH") or s5["bias"] != s15["bias"]:
            continue
        side = "LONG" if s15["bias"] == "BULLISH" else "SHORT"
        aligned_break = (side=="LONG" and (s5["bos"]=="BULLISH" or s5["choch"]=="BULLISH")) or (side=="SHORT" and (s5["bos"]=="BEARISH" or s5["choch"]=="BEARISH"))
        if not aligned_break or sw5 is None or not s5["displacement"]:
            continue
        entry = float(x["close"].iloc[i])
        atr = float(_closed_replay_features(hist5)["atr"].iloc[-1])
        if not np.isfinite(atr) or atr <= 0: continue
        if side == "LONG":
            sl = float(sw5["price"])-SL_ATR_BUFFER*atr
            risk = entry-sl
            if risk <= 0: continue
            tp1, tp2 = entry+TP1_R*risk, entry+TP2_R*risk
        else:
            sl = float(sw5["price"])+SL_ATR_BUFFER*atr
            risk = sl-entry
            if risk <= 0: continue
            tp1, tp2 = entry-TP1_R*risk, entry-TP2_R*risk
        risk_atr = risk/atr
        if risk_atr < MIN_RISK_ATR or risk_atr > MAX_RISK_ATR: continue
        r, outcome, exit_ts = _trade_outcome(x, i, side, sl, tp1, tp2, horizon)
        records.append({"timestamp":ts,"side":side,"r":r,"outcome":outcome,"session":_session(ts),"risk_atr":risk_atr,"exit":exit_ts})
    # OOS replay uses same fixed rules, no tuning.
    for i in range(split, len(x)-horizon-1):
        hist5 = x.iloc[:i+1]
        ts=x.index[i]
        hist15=m15.loc[m15.index<=ts]
        if len(hist15)<40: continue
        s15=_replay_structure(hist15); s5,sw5,trig5=_replay_trigger(hist5)
        if s15["bias"] not in ("BULLISH","BEARISH") or s5["bias"] != s15["bias"]: continue
        side="LONG" if s15["bias"]=="BULLISH" else "SHORT"
        aligned=(side=="LONG" and (s5["bos"]=="BULLISH" or s5["choch"]=="BULLISH")) or (side=="SHORT" and (s5["bos"]=="BEARISH" or s5["choch"]=="BEARISH"))
        if not aligned or sw5 is None or not s5["displacement"]: continue
        entry=float(x["close"].iloc[i]); atr=float(_closed_replay_features(hist5)["atr"].iloc[-1])
        if not np.isfinite(atr) or atr<=0: continue
        sl=(float(sw5["price"])-SL_ATR_BUFFER*atr) if side=="LONG" else (float(sw5["price"])+SL_ATR_BUFFER*atr)
        risk=(entry-sl) if side=="LONG" else (sl-entry)
        if risk<=0: continue
        risk_atr=risk/atr
        if risk_atr<MIN_RISK_ATR or risk_atr>MAX_RISK_ATR: continue
        tp1=(entry+TP1_R*risk) if side=="LONG" else (entry-TP1_R*risk)
        tp2=(entry+TP2_R*risk) if side=="LONG" else (entry-TP2_R*risk)
        r,outcome,exit_ts=_trade_outcome(x,i,side,sl,tp1,tp2,horizon)
        records.append({"timestamp":ts,"side":side,"r":r,"outcome":outcome,"session":_session(ts),"risk_atr":risk_atr,"exit":exit_ts,"sample":"OOS"})
    d=pd.DataFrame(records)
    if d.empty:
        return {"error":"No qualifying trades under the strict rules in this sample.","trades":0,"in_sample":{},"oos":{}}
    if "sample" not in d: d["sample"]="IN_SAMPLE"
    d.loc[d["timestamp"]>=x.index[split],"sample"]="OOS"
    def stats(q):
        if q.empty: return {"trades":0,"wins":0,"losses":0,"win_rate":0.0,"net_r":0.0,"avg_r":0.0,"profit_factor":0.0,"max_drawdown_r":0.0}
        vals=q["r"].astype(float).tolist(); wins=sum(v>0 for v in vals); losses=sum(v<0 for v in vals)
        eq=np.cumsum(vals); peak=np.maximum.accumulate(eq); dd=eq-peak
        gross_win=sum(v for v in vals if v>0); gross_loss=abs(sum(v for v in vals if v<0))
        return {"trades":len(vals),"wins":wins,"losses":losses,"win_rate":round(100*wins/len(vals),1),"net_r":round(float(sum(vals)),2),"avg_r":round(float(np.mean(vals)),2),"profit_factor":round(gross_win/gross_loss,2) if gross_loss else float("inf"),"max_drawdown_r":round(float(dd.min()),2)}
    all_s=stats(d); ins=stats(d[d["sample"]=="IN_SAMPLE"]); oos=stats(d[d["sample"]=="OOS"])
    sess={s:stats(d[d["session"]==s]) for s in ["LONDON","NEW_YORK","OTHER"]}
    return {"trades":len(d),"in_sample":ins,"oos":oos,"all":all_s,"sessions":sess,"split_index":split,"records":d}
