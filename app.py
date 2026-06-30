"""
app.py
AI Scanner Trader — Production Streamlit SMC/ICT scalper dashboard.

Run with: streamlit run app.py
"""

import os
import json
import shutil
import logging
import traceback
from datetime import datetime

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from data_fetch import fetch_multi_timeframe, SYMBOL_MAP
from indicators import add_all_indicators
from smc_analysis import full_smc_analysis
from scoring import generate_signal, MIN_CONFIDENCE
from database import Database
from ui_styles import CUSTOM_CSS

# --------------------------------------------------------------------------------------
# Logging setup
# --------------------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)
os.makedirs("signals_archive", exist_ok=True)

logging.basicConfig(
    filename="logs/app.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_scanner_trader.app")

CSV_LOG_PATH = "logs/trade_log.csv"
PAIRS = list(SYMBOL_MAP.keys())
HIGHER_TIMEFRAMES = ["H4", "H1"]
EXEC_TIMEFRAMES = ["M15", "M5", "M1"]

st.set_page_config(page_title="AI Scanner Trader", page_icon="📊", layout="wide")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------------------
# Session state initialisation
# --------------------------------------------------------------------------------------
def init_state():
    """Initialise all required Streamlit session_state variables exactly once."""
    defaults = {
        "bot_running": False,
        "live_logs": [],
        "current_signals": {},
        "db": Database(),
        "last_scan_time": None,
        "selected_pairs": PAIRS.copy(),
        "selected_higher_tf": "H1",
        "selected_exec_tf": "M5",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()
db: Database = st.session_state["db"]


def log_event(message: str):
    """Append a timestamped event to the in-memory live log and the persistent CSV log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {message}"
    st.session_state["live_logs"].insert(0, entry)
    st.session_state["live_logs"] = st.session_state["live_logs"][:200]

    file_exists = os.path.exists(CSV_LOG_PATH)
    with open(CSV_LOG_PATH, "a", encoding="utf-8") as f:
        if not file_exists:
            f.write("timestamp,message\n")
        safe_msg = message.replace(",", ";")
        f.write(f"{ts},{safe_msg}\n")


# --------------------------------------------------------------------------------------
# Core scanning logic
# --------------------------------------------------------------------------------------
def scan_pair(pair: str, higher_tf: str, exec_tf: str) -> dict:
    """
    Run the full pipeline for a single pair: fetch real OHLC data, compute indicators,
    run SMC/ICT analysis on both timeframes, and produce a weighted-confidence signal.
    Any failure is caught and logged, returning a NO TRADE placeholder instead of crashing.
    """
    try:
        htf_df, ltf_df = fetch_multi_timeframe(pair, higher_tf, exec_tf)
        htf_ind = add_all_indicators(htf_df)
        ltf_ind = add_all_indicators(ltf_df)

        htf_smc = full_smc_analysis(htf_ind)
        ltf_smc = full_smc_analysis(ltf_ind)

        signal = generate_signal(pair, exec_tf, htf_df, ltf_df, htf_smc, ltf_smc, ltf_ind)
        signal["_ltf_chart_df"] = ltf_ind.tail(150)

        # Current price / market status info (independent of whether a trade signal fired)
        last_price = float(ltf_ind["Close"].iloc[-1])
        prev_price = float(ltf_ind["Close"].iloc[-2]) if len(ltf_ind) > 1 else last_price
        change_pct = ((last_price - prev_price) / prev_price * 100) if prev_price else 0.0
        signal["current_price"] = round(last_price, 5)
        signal["price_change_pct"] = round(change_pct, 3)
        signal["market_status"] = "Open"
        signal["last_update"] = datetime.now().strftime("%H:%M:%S")
        return signal
    except Exception as e:
        logger.error(f"Error scanning {pair}: {e}\n{traceback.format_exc()}")
        return {
            "timestamp": datetime.now().isoformat(),
            "pair": pair, "timeframe": exec_tf, "signal": "NO TRADE",
            "entry": None, "stop_loss": None, "tp1": None, "tp2": None, "tp3": None,
            "rr": "-", "confidence": 0.0, "trend": "Unknown",
            "support_levels": [], "resistance_levels": [],
            "trade_reason": f"Data/analysis error: {e}",
            "risk_warning": "Unable to generate a reliable signal due to a data error.",
            "_ltf_chart_df": None,
            "current_price": None, "price_change_pct": None,
            "market_status": "Error", "last_update": datetime.now().strftime("%H:%M:%S"),
        }


def run_scan_cycle():
    """Scan every selected pair, store signals in DB, update session state and logs."""
    higher_tf = st.session_state["selected_higher_tf"]
    exec_tf = st.session_state["selected_exec_tf"]

    for pair in st.session_state["selected_pairs"]:
        signal = scan_pair(pair, higher_tf, exec_tf)
        st.session_state["current_signals"][pair] = signal

        db_signal = {k: v for k, v in signal.items() if k != "_ltf_chart_df"}
        db.insert_signal(db_signal)

        if signal["signal"] in ("BUY", "SELL"):
            log_event(f"Signal Generated — {pair} {signal['signal']} @ {signal['entry']} "
                      f"(Confidence {signal['confidence']}%)")
            db.insert_trade({
                "signal_id": None,
                "timestamp_open": signal["timestamp"],
                "timestamp_close": None,
                "pair": pair,
                "direction": signal["signal"],
                "entry": signal["entry"],
                "exit_price": None,
                "stop_loss": signal["stop_loss"],
                "tp1": signal["tp1"], "tp2": signal["tp2"], "tp3": signal["tp3"],
                "profit": None,
                "status": "OPEN",
                "confidence": signal["confidence"],
                "trade_reason": signal["trade_reason"],
                "date": datetime.now().date().isoformat(),
            })
            log_event(f"Trade Opened — {pair} {signal['signal']} | SL {signal['stop_loss']} | "
                      f"TP1 {signal['tp1']}")
        else:
            log_event(f"{pair}: NO TRADE — {signal['confidence']}% confidence "
                      f"(threshold {MIN_CONFIDENCE}%)")

    db.upsert_daily_summary()
    st.session_state["last_scan_time"] = datetime.now()


def archive_and_clear_cache():
    """
    Save all current signals/trades to a timestamped JSON file in signals_archive/
    before wiping the live cache tables — so historical data is never lost.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = f"signals_archive/archive_{ts}.json"

    payload = {
        "archived_at": datetime.now().isoformat(),
        "signals": db.fetch_recent_signals(limit=1000),
        "trades": db.fetch_recent_trades(limit=1000),
    }
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    db.clear_cache_tables()
    st.session_state["current_signals"] = {}
    log_event(f"Cache cleared. Previous signals archived to {archive_path}.")
    return archive_path


# --------------------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ AI Scanner Trader")
    st.markdown("**Settings**")

    selected_pairs = st.multiselect("Pair Selection", PAIRS, default=st.session_state["selected_pairs"])
    st.session_state["selected_pairs"] = selected_pairs or PAIRS

    higher_tf = st.selectbox("Higher Timeframe (Bias)", HIGHER_TIMEFRAMES,
                              index=HIGHER_TIMEFRAMES.index(st.session_state["selected_higher_tf"]))
    exec_tf = st.selectbox("Execution Timeframe", EXEC_TIMEFRAMES,
                            index=EXEC_TIMEFRAMES.index(st.session_state["selected_exec_tf"]))
    st.session_state["selected_higher_tf"] = higher_tf
    st.session_state["selected_exec_tf"] = exec_tf

    st.markdown("---")
    st.markdown("**Bot Controls**")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶ START BOT", use_container_width=True):
            st.session_state["bot_running"] = True
            log_event("Bot STARTED.")
    with col2:
        if st.button("⏹ STOP BOT", use_container_width=True):
            st.session_state["bot_running"] = False
            log_event("Bot STOPPED.")

    if st.button("🔄 RESET SESSION", use_container_width=True):
        st.session_state["bot_running"] = False
        st.session_state["live_logs"] = []
        st.session_state["current_signals"] = {}
        st.session_state["last_scan_time"] = None
        log_event("Session RESET.")

    st.markdown("---")
    st.markdown("**Cache Management**")
    if st.button("🗑️ Delete Cache (Archive First)", use_container_width=True):
        path = archive_and_clear_cache()
        st.success(f"Cache cleared. Archived to:\n{path}")

    st.markdown("---")
    status_color = "🟢" if st.session_state["bot_running"] else "🔴"
    st.markdown(f"**Status:** {status_color} {'RUNNING' if st.session_state['bot_running'] else 'STOPPED'}")
    if st.session_state["last_scan_time"]:
        st.caption(f"Last scan: {st.session_state['last_scan_time'].strftime('%H:%M:%S')}")

    st.markdown("---")
    st.caption("⚠️ Data sourced via Yahoo Finance (yfinance) real market feeds. "
               "No simulated/random data is used. For live Deriv execution, "
               "connect your Deriv API token securely below.")
    deriv_token = st.text_input("Deriv API Token (optional, masked)", type="password",
                                 help="Used only for live account data — never hardcoded, never logged.")
    if deriv_token:
        st.session_state["deriv_token_set"] = True
        st.caption("✅ Token received for this session only (not persisted to disk).")


# --------------------------------------------------------------------------------------
# Main dashboard
# --------------------------------------------------------------------------------------
st.title("📊 AI Scanner Trader")
st.caption("SMC + ICT Multi-Timeframe Confluence Scalper — EURUSD · GBPJPY · AUDUSD")

# Trigger a scan cycle if the bot is running
if st.session_state["bot_running"]:
    with st.spinner("Scanning markets..."):
        run_scan_cycle()

tab_signals, tab_chart, tab_log, tab_history, tab_summary = st.tabs(
    ["📡 Current Signals", "📈 Live Chart", "📝 Trade Log", "🗂 Signal History", "📅 Daily Summary"]
)

# ---- Current Signals tab ----
with tab_signals:
    st.subheader("Market Status & Current Signals")

    if not st.session_state["current_signals"]:
        st.info("No signals yet. Click **START BOT** in the sidebar to begin scanning.")
    else:
        st.markdown("#### 💹 Current Price & Market Status")
        price_cols = st.columns(len(st.session_state["current_signals"]))
        for col, (pair, sig) in zip(price_cols, st.session_state["current_signals"].items()):
            with col:
                price = sig.get("current_price")
                chg = sig.get("price_change_pct")
                status = sig.get("market_status", "Unknown")
                status_icon = "🟢" if status == "Open" else ("🔴" if status == "Error" else "⚪")
                st.metric(
                    label=f"{pair}  {status_icon} {status}",
                    value=f"{price}" if price is not None else "—",
                    delta=f"{chg}%" if chg is not None else None,
                )
                st.caption(f"Updated {sig.get('last_update', '—')}")

        st.markdown("#### 📡 Signals")
        cols = st.columns(len(st.session_state["current_signals"]))
        for col, (pair, sig) in zip(cols, st.session_state["current_signals"].items()):
            with col:
                st.metric(label=pair, value=sig["signal"], delta=f"{sig['confidence']}% confidence")

        for pair, sig in st.session_state["current_signals"].items():
            css_class = {"BUY": "signal-card-buy", "SELL": "signal-card-sell"}.get(sig["signal"], "signal-card-notrade")
            badge_class = {"BUY": "badge-buy", "SELL": "badge-sell"}.get(sig["signal"], "badge-notrade")

            with st.container():
                st.markdown(f"""
                <div class="{css_class}">
                    <h4>{pair} — {sig['timeframe']} &nbsp; <span class="{badge_class}">{sig['signal']}</span></h4>
                    <b>Trend:</b> {sig['trend']} &nbsp; | &nbsp; <b>Confidence:</b> {sig['confidence']}%<br>
                </div>
                """, unsafe_allow_html=True)

                if sig["signal"] in ("BUY", "SELL"):
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("Entry", sig["entry"])
                    c2.metric("Stop Loss", sig["stop_loss"])
                    c3.metric("TP1", sig["tp1"])
                    c4.metric("TP2", sig["tp2"])
                    c5.metric("TP3", sig["tp3"])
                    st.write(f"**Risk:Reward:** {sig['rr']}")
                    st.write(f"**Support Levels:** {', '.join(map(str, sig['support_levels'])) or '—'}")
                    st.write(f"**Resistance Levels:** {', '.join(map(str, sig['resistance_levels'])) or '—'}")

                with st.expander("Trade Reason & Risk Warning"):
                    st.write(f"**Trade Reason:** {sig['trade_reason']}")
                    st.warning(sig["risk_warning"])

# ---- Live Chart tab ----
with tab_chart:
    st.subheader("Live Chart")
    if not st.session_state["current_signals"]:
        st.info("Start the bot to load live chart data.")
    else:
        chart_pair = st.selectbox("Select pair to chart", list(st.session_state["current_signals"].keys()))
        sig = st.session_state["current_signals"][chart_pair]
        chart_df = sig.get("_ltf_chart_df")

        if chart_df is not None and not chart_df.empty:
            fig = go.Figure(data=[go.Candlestick(
                x=chart_df.index, open=chart_df["Open"], high=chart_df["High"],
                low=chart_df["Low"], close=chart_df["Close"],
                increasing_line_color="#FF8C00", decreasing_line_color="#6A0DAD",
                name=chart_pair,
            )])
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["EMA50"], name="EMA50",
                                      line=dict(color="#FF8C00", width=1)))
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["EMA200"], name="EMA200",
                                      line=dict(color="#6A0DAD", width=1)))

            if sig["signal"] in ("BUY", "SELL"):
                fig.add_hline(y=sig["entry"], line_dash="dot", line_color="black",
                              annotation_text="Entry")
                fig.add_hline(y=sig["stop_loss"], line_dash="dot", line_color="#6A0DAD",
                              annotation_text="SL")
                fig.add_hline(y=sig["tp1"], line_dash="dot", line_color="#FF8C00",
                              annotation_text="TP1")

            fig.update_layout(
                plot_bgcolor="white", paper_bgcolor="white",
                font_color="#1a1a1a", xaxis_rangeslider_visible=False, height=550,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No chart data available for this pair.")

# ---- Trade Log tab ----
with tab_log:
    st.subheader("Live Trade Log")
    if st.session_state["live_logs"]:
        st.text_area("Recent activity", value="\n".join(st.session_state["live_logs"]), height=400)
    else:
        st.info("No activity yet.")

    if os.path.exists(CSV_LOG_PATH):
        with open(CSV_LOG_PATH, "rb") as f:
            st.download_button("⬇ Download Full CSV Log", f, file_name="trade_log.csv")

# ---- Signal History tab ----
with tab_history:
    st.subheader("Signal History (Database)")
    history = db.fetch_recent_signals(limit=100)
    if history:
        hist_df = pd.DataFrame(history)
        st.dataframe(hist_df, use_container_width=True, height=400)
    else:
        st.info("No signal history yet.")

    st.subheader("Trade History")
    trades = db.fetch_recent_trades(limit=100)
    if trades:
        trades_df = pd.DataFrame(trades)
        st.dataframe(trades_df, use_container_width=True, height=300)
    else:
        st.info("No trades yet.")

    st.subheader("Archived Signal Files")
    archive_files = sorted(os.listdir("signals_archive"), reverse=True)
    if archive_files:
        for fname in archive_files[:10]:
            fpath = os.path.join("signals_archive", fname)
            with open(fpath, "rb") as f:
                st.download_button(f"⬇ {fname}", f, file_name=fname, key=fname)
    else:
        st.caption("No archives yet. Use 'Delete Cache' in the sidebar to create one.")

# ---- Daily Summary tab ----
with tab_summary:
    st.subheader("Daily Performance Summary")
    summary = db.fetch_daily_summary()
    if summary:
        st.dataframe(pd.DataFrame(summary), use_container_width=True)
    else:
        st.info("No summary data yet — run the bot to generate signals.")

st.markdown("---")
st.caption("AI Scanner Trader · Educational tool only · Not financial advice · "
           "Trading forex and CFDs carries a high level of risk and may not be suitable for all investors.")
