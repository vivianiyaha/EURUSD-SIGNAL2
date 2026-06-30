"""
data_fetch.py
Real market data acquisition for forex pairs using yfinance.
Includes retry mechanism and error handling — no synthetic/random data is ever used.
"""

import time
import logging
import pandas as pd
import yfinance as yf

logger = logging.getLogger("ai_scanner_trader.data_fetch")

# Map our app's pair labels to Yahoo Finance forex tickers
SYMBOL_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPJPY": "GBPJPY=X",
    "AUDUSD": "AUDUSD=X",
}

# Map app timeframe labels to yfinance interval + lookback period
TIMEFRAME_MAP = {
    "M1": {"interval": "1m", "period": "5d"},
    "M5": {"interval": "5m", "period": "5d"},
    "M15": {"interval": "15m", "period": "1mo"},
    "H1": {"interval": "60m", "period": "3mo"},
    "H4": {"interval": "60m", "period": "6mo"},  # resampled to 4H below
    "D1": {"interval": "1d", "period": "2y"},
}


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten yfinance MultiIndex columns (introduced in newer yfinance versions)."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def _resample_h4(df: pd.DataFrame) -> pd.DataFrame:
    """Resample 1H candles into 4H candles for higher-timeframe analysis."""
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    out = df.resample("4h").agg(agg).dropna()
    return out


def fetch_ohlc(pair: str, timeframe: str, retries: int = 3, backoff: float = 1.5) -> pd.DataFrame:
    """
    Fetch real OHLC candle data for a given pair/timeframe.
    Retries on transient failures with exponential backoff.
    Returns a clean DataFrame indexed by datetime with Open/High/Low/Close/Volume columns.
    """
    if pair not in SYMBOL_MAP:
        raise ValueError(f"Unsupported pair: {pair}")
    if timeframe not in TIMEFRAME_MAP:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    ticker = SYMBOL_MAP[pair]
    cfg = TIMEFRAME_MAP[timeframe]

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            df = yf.download(
                ticker,
                interval=cfg["interval"],
                period=cfg["period"],
                progress=False,
                auto_adjust=False,
            )
            df = _flatten_columns(df)
            if df is None or df.empty:
                raise RuntimeError(f"Empty data returned for {pair} ({ticker})")

            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

            if timeframe == "H4":
                df = _resample_h4(df)

            return df
        except Exception as e:
            last_err = e
            logger.warning(f"Attempt {attempt}/{retries} failed for {pair} {timeframe}: {e}")
            time.sleep(backoff ** attempt)

    raise ConnectionError(f"Failed to fetch data for {pair} {timeframe} after {retries} attempts: {last_err}")


def fetch_multi_timeframe(pair: str, higher_tf: str, exec_tf: str):
    """Fetch both higher-timeframe and execution-timeframe data for MTF analysis."""
    htf_df = fetch_ohlc(pair, higher_tf)
    ltf_df = fetch_ohlc(pair, exec_tf)
    return htf_df, ltf_df
