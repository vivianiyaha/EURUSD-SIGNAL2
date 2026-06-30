"""
database.py
SQLite persistence layer for AI Scanner Trader.
Handles signals, trades, account_history and daily_summary tables.
"""

import sqlite3
import threading
from datetime import datetime, date
from contextlib import contextmanager

DB_PATH = "data/ai_scanner_trader.db"


class Database:
    """Thread-safe SQLite wrapper for the AI Scanner Trader app."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_schema()

    @contextmanager
    def _connect(self):
        """Context manager that yields a connection and always closes it."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self):
        """Create all required tables if they do not already exist."""
        with self._lock, self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    pair TEXT,
                    timeframe TEXT,
                    signal TEXT,
                    entry REAL,
                    stop_loss REAL,
                    tp1 REAL,
                    tp2 REAL,
                    tp3 REAL,
                    rr TEXT,
                    confidence REAL,
                    trend TEXT,
                    support_levels TEXT,
                    resistance_levels TEXT,
                    trade_reason TEXT,
                    risk_warning TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id INTEGER,
                    timestamp_open TEXT,
                    timestamp_close TEXT,
                    pair TEXT,
                    direction TEXT,
                    entry REAL,
                    exit_price REAL,
                    stop_loss REAL,
                    tp1 REAL,
                    tp2 REAL,
                    tp3 REAL,
                    profit REAL,
                    status TEXT,
                    confidence REAL,
                    trade_reason TEXT,
                    date TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS account_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    balance REAL,
                    equity REAL,
                    open_trades INTEGER,
                    note TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE,
                    total_signals INTEGER,
                    total_trades INTEGER,
                    wins INTEGER,
                    losses INTEGER,
                    profit REAL,
                    win_rate REAL
                )
            """)

    def insert_signal(self, sig: dict) -> int:
        """Insert a generated signal and return its row id."""
        with self._lock, self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO signals (timestamp, pair, timeframe, signal, entry, stop_loss,
                    tp1, tp2, tp3, rr, confidence, trend, support_levels, resistance_levels,
                    trade_reason, risk_warning)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                sig.get("timestamp"), sig.get("pair"), sig.get("timeframe"), sig.get("signal"),
                sig.get("entry"), sig.get("stop_loss"), sig.get("tp1"), sig.get("tp2"), sig.get("tp3"),
                sig.get("rr"), sig.get("confidence"), sig.get("trend"),
                str(sig.get("support_levels")), str(sig.get("resistance_levels")),
                sig.get("trade_reason"), sig.get("risk_warning")
            ))
            return cur.lastrowid

    def insert_trade(self, trade: dict) -> int:
        """Insert a simulated/paper trade record."""
        with self._lock, self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO trades (signal_id, timestamp_open, timestamp_close, pair, direction,
                    entry, exit_price, stop_loss, tp1, tp2, tp3, profit, status, confidence,
                    trade_reason, date)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                trade.get("signal_id"), trade.get("timestamp_open"), trade.get("timestamp_close"),
                trade.get("pair"), trade.get("direction"), trade.get("entry"), trade.get("exit_price"),
                trade.get("stop_loss"), trade.get("tp1"), trade.get("tp2"), trade.get("tp3"),
                trade.get("profit"), trade.get("status"), trade.get("confidence"),
                trade.get("trade_reason"), trade.get("date")
            ))
            return cur.lastrowid

    def update_trade_close(self, trade_id: int, exit_price: float, profit: float, status: str):
        """Mark a trade as closed with its exit price and outcome."""
        with self._lock, self._connect() as conn:
            conn.execute("""
                UPDATE trades SET exit_price=?, profit=?, status=?, timestamp_close=?
                WHERE id=?
            """, (exit_price, profit, status, datetime.now().isoformat(), trade_id))

    def log_account_snapshot(self, balance: float, equity: float, open_trades: int, note: str = ""):
        """Record an account equity snapshot."""
        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO account_history (timestamp, balance, equity, open_trades, note)
                VALUES (?,?,?,?,?)
            """, (datetime.now().isoformat(), balance, equity, open_trades, note))

    def upsert_daily_summary(self):
        """Recompute and store today's trading summary."""
        today = date.today().isoformat()
        with self._lock, self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS c FROM signals WHERE timestamp LIKE ?", (f"{today}%",))
            total_signals = cur.fetchone()["c"]
            cur.execute("SELECT * FROM trades WHERE date = ?", (today,))
            trades = cur.fetchall()
            total_trades = len(trades)
            wins = sum(1 for t in trades if (t["profit"] or 0) > 0)
            losses = sum(1 for t in trades if (t["profit"] or 0) <= 0 and t["status"] == "CLOSED")
            profit = sum((t["profit"] or 0) for t in trades)
            win_rate = (wins / total_trades * 100) if total_trades else 0.0
            cur.execute("""
                INSERT INTO daily_summary (date, total_signals, total_trades, wins, losses, profit, win_rate)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(date) DO UPDATE SET
                    total_signals=excluded.total_signals,
                    total_trades=excluded.total_trades,
                    wins=excluded.wins,
                    losses=excluded.losses,
                    profit=excluded.profit,
                    win_rate=excluded.win_rate
            """, (today, total_signals, total_trades, wins, losses, profit, win_rate))

    def fetch_recent_signals(self, limit: int = 50):
        """Return the most recent N signals as a list of dict rows."""
        with self._lock, self._connect() as conn:
            cur = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def fetch_recent_trades(self, limit: int = 50):
        """Return the most recent N trades as a list of dict rows."""
        with self._lock, self._connect() as conn:
            cur = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def fetch_daily_summary(self):
        """Return all daily summary rows, most recent first."""
        with self._lock, self._connect() as conn:
            cur = conn.execute("SELECT * FROM daily_summary ORDER BY date DESC")
            return [dict(r) for r in cur.fetchall()]

    def clear_cache_tables(self):
        """Wipe signals/trades/account_history but keep daily_summary archive."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM signals")
            conn.execute("DELETE FROM trades")
            conn.execute("DELETE FROM account_history")
