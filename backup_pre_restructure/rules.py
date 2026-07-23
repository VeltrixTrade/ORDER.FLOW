from datetime import datetime
from typing import Dict, Any, Optional, Tuple
import os
import json
import logging
import sqlite3
from trade_db import TradeDB

logger = logging.getLogger(__name__)

STATE_FILE = "database/monitoring_state.json"

def load_monitoring_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "is_monitoring": False,
        "monitored_candles_count": 0,
        "trend_bias": None,
        "consecutive_closes_outside": 0
    }

def save_monitoring_state(state_dict: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state_dict, f, indent=4)
    except Exception:
        pass

def is_news_freeze_active() -> bool:
    return False

def is_in_cooldown(signal_type: str) -> bool:
    return False

def calculate_ema(prices: list, period: int) -> float:
    if not prices:
        return 0.0
    multiplier = 2 / (period + 1)
    if len(prices) < period:
        return sum(prices) / len(prices)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def get_ema_values(db: TradeDB, tf: str) -> Tuple[float, float]:
    """Retrieve EMA34 and EMA50 by calculating them dynamically from database candles for the specific timeframe."""
    candles = db.get_candles("XAUUSD", tf, limit=100)
    if len(candles) >= 10:
        closes = [c["close"] for c in reversed(candles)]
        ema34 = calculate_ema(closes, 34)
        ema50 = calculate_ema(closes, 50)
        return ema34, ema50
        
    # Fallback to live price if not enough database candles are available
    lp = db.get_live_price("XAUUSD")
    if lp and lp.get("ema34") and lp.get("ema50"):
        return float(lp["ema34"]), float(lp["ema50"])
    return 0.0, 0.0

def evaluate_rules(
    state: Dict[str, Any],
    ohlc: Dict[str, Any],
    volume_sma_10: float,
    verbose_callback: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    """
    Evaluates order flow setups against dynamic EMA Wave Zone and Scoring rules.
    """
    db = TradeDB()
    tf = state.get("timeframe", "M1")
    if tf != "M5":
        return None

    # 1. Calculate dynamic volume_sma_10 from last 10 candles in DB
    try:
        candles = db.get_candles("XAUUSD", tf, limit=10)
        if candles:
            volume_sma_10 = sum(c["volume"] for c in candles) / len(candles)
    except Exception as e:
        logger.warning(f"Could not compute dynamic volume SMA10: {e}, falling back to passed {volume_sma_10}")

    # 2. Get EMA34 and EMA50 (Prefer values passed directly from MT5 if available)
    ema34 = ohlc.get("ema34", 0.0)
    ema50 = ohlc.get("ema50", 0.0)
    if ema34 <= 0 or ema50 <= 0:
        ema34, ema50 = get_ema_values(db, tf)
        if ema34 <= 0 or ema50 <= 0:
            # Fallback to simple close value if EMAs cannot be resolved
            ema34, ema50 = ohlc["close"], ohlc["close"]

    min_ema = min(ema34, ema50)
    max_ema = max(ema34, ema50)
    
    # Candle metrics
    open_p, close_p = ohlc["open"], ohlc["close"]
    high_p, low_p = ohlc["high"], ohlc["low"]
    total_volume = ohlc.get("volume", 0)
    delta_val = ohlc.get("delta", 0.0)

    # Load persistent monitoring state
    m_state = load_monitoring_state()
    
    # 3. Determine base trend bias
    current_trend = m_state["trend_bias"]
    if low_p > max_ema:
        current_trend = "BUY"
    elif high_p < min_ema:
        current_trend = "SELL"
        
    m_state["trend_bias"] = current_trend

    # 4. Check if we should trigger Monitoring Mode
    price_touches_wave = (low_p <= max_ema and high_p >= min_ema)
    touches_execution_zone = price_touches_wave

    if not m_state["is_monitoring"]:
        if touches_execution_zone and current_trend is not None:
            m_state["is_monitoring"] = True
            m_state["monitored_candles_count"] = 1
            m_state["consecutive_closes_outside"] = 0
            logger.info(f"Monitoring Mode STARTED on touch of wave zone. Trend Bias: {current_trend}")
    else:
        # Increment candle count
        m_state["monitored_candles_count"] += 1
        
        # Check cancellation: 2 consecutive closes completely outside in the opposite direction
        closed_outside = False
        if m_state["trend_bias"] == "BUY" and close_p < min_ema:
            closed_outside = True
        elif m_state["trend_bias"] == "SELL" and close_p > max_ema:
            closed_outside = True
            
        if closed_outside:
            m_state["consecutive_closes_outside"] += 1
        else:
            m_state["consecutive_closes_outside"] = 0
            
        should_cancel = False
        cancel_reason = ""
        if m_state["consecutive_closes_outside"] >= 2:
            should_cancel = True
            cancel_reason = "2 consecutive closes outside wave zone in opposite direction"
            # Reverse trend bias
            m_state["trend_bias"] = "SELL" if m_state["trend_bias"] == "BUY" else "BUY"
        elif m_state["monitored_candles_count"] > 3:
            should_cancel = True
            cancel_reason = "3 monitored candles limit exceeded"
            
        if should_cancel:
            m_state["is_monitoring"] = False
            m_state["monitored_candles_count"] = 0
            m_state["consecutive_closes_outside"] = 0
            save_monitoring_state(m_state)
            logger.info(f"Monitoring Mode CANCELLED: {cancel_reason}")
            if verbose_callback:
                verbose_callback(
                    signal_type="NONE",
                    price_near_boundary=1 if current_trend is not None else 0,
                    volume_confirmed=(total_volume >= volume_sma_10),
                    stacked_imbalance=False,
                    absorption=False,
                    reason=f"Monitoring cancelled: {cancel_reason}",
                    metrics_snapshot=state
                )
            return None

    # Save state
    save_monitoring_state(m_state)
    
    # 5. Evaluate setup if monitoring is active
    if not m_state["is_monitoring"]:
        return None
        
    signal_type = m_state["trend_bias"]
    
    # Compute Score Points (Max 100)
    score = 0
    reasons = []
    
    # Condition 1: Volume (50 pts)
    vol_ok = total_volume >= volume_sma_10
    if vol_ok:
        score += 50
        reasons.append("Volume Confirmed ✅")
    else:
        reasons.append("Volume Unconfirmed ❌")
        
    # Condition 2: Delta (50 pts)
    delta_ok = False
    if signal_type == "BUY" and delta_val > 0:
        delta_ok = True
    elif signal_type == "SELL" and delta_val < 0:
        delta_ok = True
        
    if delta_ok:
        score += 50
        reasons.append("Delta Confirmed ✅")
    else:
        reasons.append("Delta Unconfirmed ❌")

    logger.info(f"Evaluating Rules: Trend={signal_type} | Score={score}% | Details: {', '.join(reasons)}")

    # 6. Check Signal Acceptance Threshold (Minimum 100% - both conditions must be met)
    if score >= 100:
        # Determine dynamic stop loss and risk
        entry = close_p
        if signal_type == "BUY":
            sl = min(min_ema, entry) - 2.0
            risk = abs(entry - sl)
            tp1 = entry + risk
            tp2 = entry + 2.0 * risk
            tp3 = entry + 3.0 * risk
        else:
            sl = max(max_ema, entry) + 2.0
            risk = abs(entry - sl)
            tp1 = entry - risk
            tp2 = entry - 2.0 * risk
            tp3 = entry - 3.0 * risk
            
        # Reset monitoring state since trade is triggered
        m_state["is_monitoring"] = False
        m_state["monitored_candles_count"] = 0
        m_state["consecutive_closes_outside"] = 0
        save_monitoring_state(m_state)
        
        reason_str = " | ".join(reasons)
        sig_class = "Strong Signal"
        
        return {
            "type": signal_type,
            "category": "scalp" if risk < 5.0 else "swing",
            "entry_price": entry,
            "stop_loss": sl,
            "take_profit_1": tp1,
            "take_profit_2": tp2,
            "take_profit_3": tp3,
            "confidence": float(score),
            "reasons": reasons,
            "metrics_snapshot": {
                "vwap": state.get("vwap", 0.0),
                "cvd": state.get("cvd", 0),
                "val": 0.0,
                "vah": 0.0,
                "ema34": ema34,
                "ema50": ema50,
                "score_reasons": reason_str,
                "signal_classification": sig_class,
                "partial_close_instruction": "TP1 hit: take 25% partial profits & move SL to entry"
            }
        }
    else:
        # Construct vertical audit report in Arabic
        rejections_list = []
        
        # 1. Volume
        vol_symbol = "✅" if vol_ok else "❌"
        rejections_list.append(f"- الحجم: {total_volume:.1f} (المطلوب >= {volume_sma_10:.1f}) {vol_symbol}")
        
        # 2. Delta
        delta_symbol = "✅" if delta_ok else "❌"
        delta_desc = "عكس الاتجاه" if not delta_ok else "مع الاتجاه"
        rejections_list.append(f"- الدلتا: {delta_val:.1f} ({delta_desc}) {delta_symbol}")
        
        reason = (
            f"التقييم: {score}% (مرفوض ❌ - المطلوب 100%)\n"
            + "\n".join(rejections_list)
        )
        
        if verbose_callback:
            verbose_callback(
                signal_type=signal_type,
                price_near_boundary=1 if current_trend is not None else 0,
                volume_confirmed=vol_ok,
                stacked_imbalance=False,
                absorption=False,
                reason=reason,
                metrics_snapshot=state
            )
        return None
