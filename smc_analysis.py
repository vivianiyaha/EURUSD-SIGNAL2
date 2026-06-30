"""
smc_analysis.py
Smart Money Concepts (SMC) and ICT analysis engine:
- Market structure (HH/HL/LH/LL, BOS, CHOCH)
- Liquidity sweeps
- Order blocks / breaker blocks / mitigation blocks
- Fair Value Gaps (FVG)
- Premium / Discount zones
- Support & resistance (swing highs/lows)
- Price action patterns (pin bar, engulfing, rejection, breakout/retest)
"""

import pandas as pd
import numpy as np


def find_swings(df: pd.DataFrame, lookback: int = 3):
    """
    Identify swing highs and swing lows using a simple fractal method:
    a swing high/low is a local max/min over `lookback` candles on each side.
    Returns two boolean Series aligned to df.index.
    """
    highs = df["High"]
    lows = df["Low"]
    swing_high = pd.Series(False, index=df.index)
    swing_low = pd.Series(False, index=df.index)

    for i in range(lookback, len(df) - lookback):
        window_h = highs.iloc[i - lookback:i + lookback + 1]
        window_l = lows.iloc[i - lookback:i + lookback + 1]
        if highs.iloc[i] == window_h.max():
            swing_high.iloc[i] = True
        if lows.iloc[i] == window_l.min():
            swing_low.iloc[i] = True

    return swing_high, swing_low


def market_structure(df: pd.DataFrame, lookback: int = 3) -> dict:
    """
    Determine market structure: sequence of HH/HL/LH/LL, latest BOS and CHOCH.
    Returns a dict with trend label, last structure events and key swing levels.
    """
    swing_high, swing_low = find_swings(df, lookback)
    highs = df.loc[swing_high, "High"]
    lows = df.loc[swing_low, "Low"]

    structure_events = []
    if len(highs) >= 2:
        structure_events.append(("HH" if highs.iloc[-1] > highs.iloc[-2] else "LH", highs.index[-1]))
    if len(lows) >= 2:
        structure_events.append(("HL" if lows.iloc[-1] > lows.iloc[-2] else "LL", lows.index[-1]))

    # Determine trend from the most recent structure events
    labels = [e[0] for e in structure_events]
    if "HH" in labels and "HL" in labels:
        trend = "Bullish"
    elif "LH" in labels and "LL" in labels:
        trend = "Bearish"
    else:
        trend = "Ranging"

    # BOS: close breaks beyond the last opposite swing level in the trend direction
    bos = False
    choch = False
    last_close = df["Close"].iloc[-1]
    if len(highs) >= 1 and len(lows) >= 1:
        if trend == "Bullish" and last_close > highs.iloc[-1]:
            bos = True
        elif trend == "Bearish" and last_close < lows.iloc[-1]:
            bos = True

        # CHOCH: price breaks structure opposite to the prevailing trend (early reversal signal)
        if len(highs) >= 2 and len(lows) >= 2:
            prior_trend_bullish = highs.iloc[-2] < highs.iloc[-1] and lows.iloc[-2] < lows.iloc[-1]
            prior_trend_bearish = highs.iloc[-2] > highs.iloc[-1] and lows.iloc[-2] > lows.iloc[-1]
            if prior_trend_bullish and last_close < lows.iloc[-1]:
                choch = True
            if prior_trend_bearish and last_close > highs.iloc[-1]:
                choch = True

    return {
        "trend": trend,
        "bos": bos,
        "choch": choch,
        "swing_highs": highs.tail(5).to_dict(),
        "swing_lows": lows.tail(5).to_dict(),
    }


def detect_liquidity_sweep(df: pd.DataFrame, lookback: int = 10) -> dict:
    """
    Detect a liquidity sweep: price wicks beyond a recent swing high/low then closes back inside,
    signalling a stop-hunt / liquidity grab typical of institutional order flow.
    """
    recent = df.tail(lookback)
    prior_high = recent["High"].iloc[:-1].max()
    prior_low = recent["Low"].iloc[:-1].min()
    last = recent.iloc[-1]

    swept_high = last["High"] > prior_high and last["Close"] < prior_high
    swept_low = last["Low"] < prior_low and last["Close"] > prior_low

    return {
        "swept_high": bool(swept_high),
        "swept_low": bool(swept_low),
        "level_high": float(prior_high),
        "level_low": float(prior_low),
    }


def detect_order_blocks(df: pd.DataFrame, lookback: int = 20) -> dict:
    """
    Identify the most recent bullish and bearish order blocks:
    the last opposite-colour candle before a strong impulsive move.
    """
    recent = df.tail(lookback).copy()
    recent["body"] = (recent["Close"] - recent["Open"]).abs()
    avg_body = recent["body"].mean()

    bullish_ob = None
    bearish_ob = None

    for i in range(1, len(recent)):
        cur = recent.iloc[i]
        prev = recent.iloc[i - 1]
        impulsive_up = cur["Close"] > cur["Open"] and cur["body"] > avg_body * 1.5
        impulsive_down = cur["Close"] < cur["Open"] and cur["body"] > avg_body * 1.5

        if impulsive_up and prev["Close"] < prev["Open"]:
            bullish_ob = {"low": float(prev["Low"]), "high": float(prev["High"]), "time": str(prev.name)}
        if impulsive_down and prev["Close"] > prev["Open"]:
            bearish_ob = {"low": float(prev["Low"]), "high": float(prev["High"]), "time": str(prev.name)}

    return {"bullish_ob": bullish_ob, "bearish_ob": bearish_ob}


def detect_fvg(df: pd.DataFrame, lookback: int = 20) -> list:
    """
    Detect Fair Value Gaps (3-candle imbalance): a gap between candle 1's high/low
    and candle 3's low/high with candle 2 as the impulsive move.
    """
    recent = df.tail(lookback)
    gaps = []
    for i in range(2, len(recent)):
        c1 = recent.iloc[i - 2]
        c3 = recent.iloc[i]
        if c3["Low"] > c1["High"]:
            gaps.append({"type": "bullish", "bottom": float(c1["High"]), "top": float(c3["Low"]),
                         "time": str(recent.index[i])})
        elif c3["High"] < c1["Low"]:
            gaps.append({"type": "bearish", "bottom": float(c3["High"]), "top": float(c1["Low"]),
                         "time": str(recent.index[i])})
    return gaps[-5:]  # most recent 5 gaps


def premium_discount_zone(df: pd.DataFrame, lookback: int = 50) -> dict:
    """
    Calculate the premium/discount zone of the current dealing range.
    Below 50% = discount (favour buys), above 50% = premium (favour sells).
    """
    recent = df.tail(lookback)
    high = recent["High"].max()
    low = recent["Low"].min()
    mid = (high + low) / 2
    last_close = df["Close"].iloc[-1]
    zone = "Discount" if last_close < mid else "Premium"
    return {"range_high": float(high), "range_low": float(low), "midpoint": float(mid), "zone": zone}


def detect_breaker_mitigation_blocks(df: pd.DataFrame, ob: dict) -> dict:
    """
    Determine if a previously broken order block has been mitigated (retested) —
    classifying it as a breaker block (failed OB that flips polarity) once price returns to it.
    """
    last_close = df["Close"].iloc[-1]
    result = {"breaker": None, "mitigation": None}

    bullish_ob = ob.get("bullish_ob")
    bearish_ob = ob.get("bearish_ob")

    if bullish_ob and bullish_ob["low"] <= last_close <= bullish_ob["high"]:
        result["mitigation"] = "bullish_ob_retested"
    if bearish_ob and bearish_ob["low"] <= last_close <= bearish_ob["high"]:
        result["mitigation"] = "bearish_ob_retested"

    return result


def support_resistance(df: pd.DataFrame, lookback: int = 50, n_levels: int = 3) -> dict:
    """Return the strongest recent swing-based support and resistance levels."""
    swing_high, swing_low = find_swings(df.tail(lookback), lookback=2)
    recent = df.tail(lookback)
    res_levels = sorted(recent.loc[swing_high.reindex(recent.index, fill_value=False), "High"].unique(),
                         reverse=True)[:n_levels]
    sup_levels = sorted(recent.loc[swing_low.reindex(recent.index, fill_value=False), "Low"].unique())[:n_levels]
    return {"support": [float(x) for x in sup_levels], "resistance": [float(x) for x in res_levels]}


def price_action_patterns(df: pd.DataFrame) -> dict:
    """Detect pin bar, engulfing, and rejection candle patterns on the latest candle."""
    if len(df) < 2:
        return {}
    cur = df.iloc[-1]
    prev = df.iloc[-2]

    body = abs(cur["Close"] - cur["Open"])
    full_range = cur["High"] - cur["Low"] or 1e-9
    upper_wick = cur["High"] - max(cur["Close"], cur["Open"])
    lower_wick = min(cur["Close"], cur["Open"]) - cur["Low"]

    pin_bar_bull = lower_wick > body * 2 and lower_wick / full_range > 0.5
    pin_bar_bear = upper_wick > body * 2 and upper_wick / full_range > 0.5

    bullish_engulf = (cur["Close"] > cur["Open"] and prev["Close"] < prev["Open"]
                       and cur["Close"] > prev["Open"] and cur["Open"] < prev["Close"])
    bearish_engulf = (cur["Close"] < cur["Open"] and prev["Close"] > prev["Open"]
                       and cur["Close"] < prev["Open"] and cur["Open"] > prev["Close"])

    rejection = pin_bar_bull or pin_bar_bear

    return {
        "pin_bar_bull": bool(pin_bar_bull),
        "pin_bar_bear": bool(pin_bar_bear),
        "bullish_engulfing": bool(bullish_engulf),
        "bearish_engulfing": bool(bearish_engulf),
        "rejection": bool(rejection),
    }


def full_smc_analysis(df: pd.DataFrame) -> dict:
    """Run the complete SMC/ICT analysis pipeline on a single timeframe and return a combined dict."""
    structure = market_structure(df)
    sweep = detect_liquidity_sweep(df)
    obs = detect_order_blocks(df)
    fvg = detect_fvg(df)
    pd_zone = premium_discount_zone(df)
    breaker = detect_breaker_mitigation_blocks(df, obs)
    sr = support_resistance(df)
    pa = price_action_patterns(df)

    return {
        "structure": structure,
        "liquidity_sweep": sweep,
        "order_blocks": obs,
        "fvg": fvg,
        "premium_discount": pd_zone,
        "breaker_mitigation": breaker,
        "support_resistance": sr,
        "price_action": pa,
    }
