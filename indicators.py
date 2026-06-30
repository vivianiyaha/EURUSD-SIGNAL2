"""
indicators.py
Standard technical indicators: EMA, RSI, ATR, volume analysis.
"""

import pandas as pd
import numpy as np


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range using High/Low/Close."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def volume_analysis(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Volume relative to its rolling average — values >1 indicate above-average activity."""
    avg_vol = df["Volume"].rolling(period).mean().replace(0, np.nan)
    return (df["Volume"] / avg_vol).fillna(1.0)


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Attach EMA50, EMA200, RSI14, ATR14 and volume ratio columns to a copy of df."""
    out = df.copy()
    out["EMA50"] = ema(out["Close"], 50)
    out["EMA200"] = ema(out["Close"], 200)
    out["RSI14"] = rsi(out["Close"], 14)
    out["ATR14"] = atr(out, 14)
    out["VolRatio"] = volume_analysis(out, 20)
    return out
