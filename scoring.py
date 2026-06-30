"""
scoring.py
AI Decision Engine: weighted confluence scoring across market structure, SMC,
RSI, EMA trend, liquidity sweeps and price action. Produces the final trade signal.

Weights:
    Market Structure  = 25%
    SMC Confirmation  = 25%
    RSI Confirmation  = 15%
    EMA Trend         = 15%
    Liquidity Sweep   = 10%
    Price Action      = 10%
"""

from datetime import datetime

WEIGHTS = {
    "structure": 0.25,
    "smc": 0.25,
    "rsi": 0.15,
    "ema": 0.15,
    "liquidity": 0.10,
    "price_action": 0.10,
}

MIN_CONFIDENCE = 75.0


def _score_structure(htf_struct: dict, ltf_struct: dict) -> tuple:
    """Score market structure alignment between higher and execution timeframe. Returns (score 0-100, bias)."""
    htf_trend = htf_struct["trend"]
    ltf_trend = ltf_struct["trend"]
    bias = None
    score = 0
    if htf_trend == ltf_trend and htf_trend in ("Bullish", "Bearish"):
        score = 100
        bias = "BUY" if htf_trend == "Bullish" else "SELL"
    elif htf_trend in ("Bullish", "Bearish") and ltf_struct["choch"]:
        # Execution TF showing early reversal against HTF — lower confidence, opposite bias
        score = 40
        bias = "SELL" if htf_trend == "Bullish" else "BUY"
    elif ltf_trend in ("Bullish", "Bearish"):
        score = 55
        bias = "BUY" if ltf_trend == "Bullish" else "SELL"
    else:
        score = 20
    if ltf_struct["bos"]:
        score = min(100, score + 15)
    return score, bias


def _score_smc(smc: dict, bias: str) -> float:
    """Score SMC/ICT confluence: order blocks, FVG, premium/discount alignment, mitigation."""
    score = 0
    pd_zone = smc["premium_discount"]["zone"]
    if bias == "BUY" and pd_zone == "Discount":
        score += 35
    elif bias == "SELL" and pd_zone == "Premium":
        score += 35

    obs = smc["order_blocks"]
    if bias == "BUY" and obs.get("bullish_ob"):
        score += 25
    elif bias == "SELL" and obs.get("bearish_ob"):
        score += 25

    fvg_list = smc["fvg"]
    relevant_fvg = [g for g in fvg_list if (g["type"] == "bullish" and bias == "BUY")
                    or (g["type"] == "bearish" and bias == "SELL")]
    if relevant_fvg:
        score += 20

    mitigation = smc["breaker_mitigation"]["mitigation"]
    if mitigation:
        score += 20

    return min(100, score)


def _score_rsi(rsi_value: float, bias: str) -> float:
    """Score RSI confirmation: favour buys when RSI recovering from oversold, sells from overbought."""
    if bias == "BUY":
        if rsi_value < 40:
            return 100
        if rsi_value < 55:
            return 60
        return 20
    elif bias == "SELL":
        if rsi_value > 60:
            return 100
        if rsi_value > 45:
            return 60
        return 20
    return 0


def _score_ema(close: float, ema50: float, ema200: float, bias: str) -> float:
    """Score EMA trend alignment (price vs EMA50/200 and EMA50 vs EMA200)."""
    if bias == "BUY":
        score = 0
        if close > ema50:
            score += 40
        if ema50 > ema200:
            score += 40
        if close > ema200:
            score += 20
        return score
    elif bias == "SELL":
        score = 0
        if close < ema50:
            score += 40
        if ema50 < ema200:
            score += 40
        if close < ema200:
            score += 20
        return score
    return 0


def _score_liquidity(sweep: dict, bias: str) -> float:
    """Score liquidity sweep confirmation (stop hunt in the direction that supports a reversal entry)."""
    if bias == "BUY" and sweep["swept_low"]:
        return 100
    if bias == "SELL" and sweep["swept_high"]:
        return 100
    return 0


def _score_price_action(pa: dict, bias: str) -> float:
    """Score candlestick price action confirmation aligned with bias."""
    if bias == "BUY" and (pa.get("pin_bar_bull") or pa.get("bullish_engulfing")):
        return 100
    if bias == "SELL" and (pa.get("pin_bar_bear") or pa.get("bearish_engulfing")):
        return 100
    if pa.get("rejection"):
        return 40
    return 0


def generate_signal(pair: str, timeframe: str, htf_df, ltf_df, htf_smc: dict, ltf_smc: dict,
                     ltf_indicators) -> dict:
    """
    Combine all confluence factors into a final weighted confidence score and
    produce a full structured trade signal dict. Returns SIGNAL = NO TRADE if
    confidence is below MIN_CONFIDENCE or required confirmations are missing.
    """
    struct_score, bias = _score_structure(htf_smc["structure"], ltf_smc["structure"])

    if bias is None:
        return _no_trade_signal(pair, timeframe, "No clear directional bias from market structure.")

    smc_score = _score_smc(ltf_smc, bias)
    last = ltf_indicators.iloc[-1]
    rsi_score = _score_rsi(last["RSI14"], bias)
    ema_score = _score_ema(last["Close"], last["EMA50"], last["EMA200"], bias)
    liquidity_score = _score_liquidity(ltf_smc["liquidity_sweep"], bias)
    pa_score = _score_price_action(ltf_smc["price_action"], bias)

    confidence = (
        struct_score * WEIGHTS["structure"] +
        smc_score * WEIGHTS["smc"] +
        rsi_score * WEIGHTS["rsi"] +
        ema_score * WEIGHTS["ema"] +
        liquidity_score * WEIGHTS["liquidity"] +
        pa_score * WEIGHTS["price_action"]
    )

    # Entry rules: confidence threshold, trend alignment, BOS, liquidity sweep, RSI confirmation
    bos_confirmed = ltf_smc["structure"]["bos"]
    liquidity_confirmed = liquidity_score > 0
    rsi_confirmed = rsi_score >= 60

    if confidence < MIN_CONFIDENCE or not (bos_confirmed or liquidity_confirmed) or not rsi_confirmed:
        reason = (f"Confidence {confidence:.1f}% below threshold or missing confirmations "
                  f"(BOS={bos_confirmed}, Liquidity={liquidity_confirmed}, RSI={rsi_confirmed}).")
        return _no_trade_signal(pair, timeframe, reason, confidence)

    entry = float(last["Close"])
    atr_val = float(last["ATR14"]) or entry * 0.001
    sr = ltf_smc["support_resistance"]

    if bias == "BUY":
        stop_loss = entry - atr_val * 1.5
        tp1 = entry + atr_val * 1.5
        tp2 = entry + atr_val * 2.5
        tp3 = entry + atr_val * 4.0
    else:
        stop_loss = entry + atr_val * 1.5
        tp1 = entry - atr_val * 1.5
        tp2 = entry - atr_val * 2.5
        tp3 = entry - atr_val * 4.0

    risk = abs(entry - stop_loss) or 1e-9
    reward = abs(tp1 - entry)
    rr = f"1:{round(reward / risk, 2)}"

    reason = _build_trade_reason(bias, htf_smc, ltf_smc, last, confidence)
    warning = ("Trading forex carries substantial risk of loss and is not suitable for all investors. "
               "Past performance is not indicative of future results. Never risk more than you can afford to lose.")

    return {
        "timestamp": datetime.now().isoformat(),
        "pair": pair,
        "timeframe": timeframe,
        "signal": bias,
        "entry": round(entry, 5),
        "stop_loss": round(stop_loss, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "rr": rr,
        "confidence": round(confidence, 1),
        "trend": ltf_smc["structure"]["trend"],
        "support_levels": sr["support"],
        "resistance_levels": sr["resistance"],
        "trade_reason": reason,
        "risk_warning": warning,
    }


def _no_trade_signal(pair: str, timeframe: str, reason: str, confidence: float = 0.0) -> dict:
    """Build a standard NO TRADE signal dict."""
    return {
        "timestamp": datetime.now().isoformat(),
        "pair": pair,
        "timeframe": timeframe,
        "signal": "NO TRADE",
        "entry": None, "stop_loss": None, "tp1": None, "tp2": None, "tp3": None,
        "rr": "-",
        "confidence": round(confidence, 1),
        "trend": "Ranging",
        "support_levels": [],
        "resistance_levels": [],
        "trade_reason": reason,
        "risk_warning": "No trade is being recommended at this time. Wait for high-probability setups.",
    }


def _build_trade_reason(bias: str, htf_smc: dict, ltf_smc: dict, last_row, confidence: float) -> str:
    """Compose a human-readable explanation of why the signal was generated."""
    direction = "bullish" if bias == "BUY" else "bearish"
    pd_zone = ltf_smc["premium_discount"]["zone"]
    parts = [
        f"Higher-timeframe structure is {htf_smc['structure']['trend'].lower()}, "
        f"aligning with a {direction} bias on the execution timeframe.",
        f"Price is trading in a {pd_zone.lower()} zone of the current dealing range, "
        f"favouring {bias.lower()} entries.",
    ]
    if ltf_smc["liquidity_sweep"]["swept_low"] or ltf_smc["liquidity_sweep"]["swept_high"]:
        parts.append("A liquidity sweep was detected, indicating a stop-hunt before the expected move.")
    if ltf_smc["order_blocks"].get("bullish_ob") or ltf_smc["order_blocks"].get("bearish_ob"):
        parts.append("Price is reacting from a relevant order block.")
    if ltf_smc["fvg"]:
        parts.append("An unfilled Fair Value Gap supports continuation in this direction.")
    parts.append(f"RSI14 is at {last_row['RSI14']:.1f}, EMA50/EMA200 trend filter confirms the move. "
                f"Composite AI confidence score: {confidence:.1f}%.")
    return " ".join(parts)
