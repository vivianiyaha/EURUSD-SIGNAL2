# AI Scanner Trader

A production-ready Streamlit SMC/ICT scalper dashboard for EURUSD, GBPJPY and AUDUSD.

## Setup
```bash
pip install -r requirements.txt
streamlit run app.py
```

## What it does
- Pulls **real** OHLC forex data via yfinance (no random/simulated candles).
- Runs full SMC/ICT analysis: market structure (HH/HL/LH/LL, BOS, CHOCH), liquidity
  sweeps, order blocks, breaker/mitigation blocks, Fair Value Gaps, premium/discount zones.
- Adds EMA50/EMA200, RSI14, ATR14, volume ratio, support/resistance, and price-action
  pattern detection (pin bars, engulfing, rejection).
- Combines everything into a weighted AI confidence score (Structure 25%, SMC 25%,
  RSI 15%, EMA 15%, Liquidity 10%, Price Action 10%). Signals only fire at >= 75%
  confidence with BOS/liquidity + RSI confirmation — otherwise it returns NO TRADE.
- Multi-timeframe: H4/H1 for bias, M5/M1 for execution.
- Logs every event to an in-app live log, a CSV file (logs/trade_log.csv), and a
  SQLite database (data/ai_scanner_trader.db) with signals/trades/account_history/
  daily_summary tables.
- "Delete Cache" button archives all current signals & trades to a timestamped JSON
  file in signals_archive/ BEFORE wiping the live database tables, so nothing is lost.
- START BOT / STOP BOT / RESET SESSION controls in the sidebar.
- Orange / white / purple / black themed UI per spec.

## Notes on live Deriv execution
This build focuses on **signal generation** using verified real market data (yfinance).
A masked Deriv API token field is included in the sidebar for future live-account
integration (balance, equity, order placement via Deriv's WebSocket API) — wire this
into a new `deriv_client.py` module using `websockets`/`asyncio` when you're ready to
go from paper signals to live order execution. Keeping signal generation and broker
execution as separate modules keeps the system safer to test and easier to maintain.
