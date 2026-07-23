from datetime import datetime
from typing import Dict, Any, Optional, Tuple
import os
import json
import logging
from trade_db import TradeDB

logger = logging.getLogger(__name__)

# State Files
CONTINUATION_STATE_FILE = "database/continuation_state.json"
REVERSAL_STATE_FILE = "database/reversal_state.json"

# State Helpers
def load_state(filepath: str, default: dict) -> dict:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return default.copy()

def save_state(filepath: str, state_dict: dict):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        with open(filepath, "w") as f:
            json.dump(state_dict, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save state to {filepath}: {e}")

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

def get_all_emas(db: TradeDB, tf: str) -> Tuple[float, float, float]:
    """Retrieve EMA10, EMA34, and EMA50 directly from the database candles without manual calculations."""
    candles_latest = db.get_candles("XAUUSD", tf, limit=1)
    if candles_latest:
        c = candles_latest[0]
        ema10_val = float(c.get("ema10") or c["close"])
        ema34_val = float(c.get("ema34") or c["close"])
        ema50_val = float(c.get("ema50") or c["close"])
        return ema10_val, ema34_val, ema50_val
    return 0.0, 0.0, 0.0

def get_ema_values(db: TradeDB, tf: str) -> Tuple[float, float]:
    """Fallback method for compatibility, returns EMA34 and EMA50."""
    _, ema34, ema50 = get_all_emas(db, tf)
    if ema34 <= 0 or ema50 <= 0:
        candles = db.get_candles("XAUUSD", tf, limit=1)
        if not candles:
            candles = db.get_candles("XAUUSD", "M5", limit=1)
        if candles:
            ref_price = float(candles[0]["close"])
            ema34 = ref_price
            ema50 = ref_price
        else:
            lp = db.get_live_price("XAUUSD")
            ref_price = float(lp["bid"]) if lp else 2400.0
            ema34 = ref_price
            ema50 = ref_price
    return ema34, ema50


class TrendContinuationStrategy:
    """
    Strategy 1: Trend Continuation
    - EMA34 & EMA50 act as a dynamic wave zone.
    - EMA10 must align with the trend (EMA10 > max_ema and price close > max_ema for BUY).
    - Trigger: Candle touches or enters wave zone (Pullback), but does NOT close behind it.
    - Cancel if body closes behind the wave zone (close < min_ema for BUY, close > max_ema for SELL).
    - Monitoring window: 5 candles.
    - Stop Loss: Remains as original (2.0$ outside the wave zone).
    """

    @staticmethod
    def get_default_state() -> dict:
        return {
            "is_monitoring": False,
            "monitored_candles_count": 0,
            "trend_bias": None,
            "consecutive_closes_outside": 0
        }

    @classmethod
    def evaluate(
        cls,
        state: Dict[str, Any],
        ohlc: Dict[str, Any],
        volume_sma_10: float,
        verbose_callback: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        db = TradeDB()
        tf = state.get("timeframe", "M5")
        if tf != "M5":
            return None

        # Get EMA values
        ema10, ema34, ema50 = get_all_emas(db, tf)
        if ema10 <= 0 or ema34 <= 0 or ema50 <= 0:
            ema34, ema50 = ohlc.get("ema34", ohlc["close"]), ohlc.get("ema50", ohlc["close"])
            ema10 = ohlc["close"]

        min_ema = min(ema34, ema50)
        max_ema = max(ema34, ema50)

        # Candle metrics
        open_p, close_p = ohlc["open"], ohlc["close"]
        high_p, low_p = ohlc["high"], ohlc["low"]
        total_volume = ohlc.get("volume", 0)
        delta_val = ohlc.get("delta", 0.0)

        # Load state
        m_state = load_state(CONTINUATION_STATE_FILE, cls.get_default_state())

        # Check Breakout & EMA10 status:
        # Case A: Candle broke wave above, but EMA10 hasn't crossed above wave yet
        if close_p > max_ema and ema10 <= max_ema:
            if not m_state.get("is_monitoring") or m_state.get("pending_breakout") != "BUY":
                m_state["is_monitoring"] = True
                m_state["monitored_candles_count"] = 1
                m_state["pending_breakout"] = "BUY"
                logger.info("[Rules] Candle broke ABOVE wave. Started 5-candle monitoring window waiting for EMA 10 crossover.")
            else:
                m_state["monitored_candles_count"] = m_state.get("monitored_candles_count", 0) + 1

        # Case B: Candle broke wave below, but EMA10 hasn't crossed below wave yet
        elif close_p < min_ema and ema10 >= min_ema:
            if not m_state.get("is_monitoring") or m_state.get("pending_breakout") != "SELL":
                m_state["is_monitoring"] = True
                m_state["monitored_candles_count"] = 1
                m_state["pending_breakout"] = "SELL"
                logger.info("[Rules] Candle broke BELOW wave. Started 5-candle monitoring window waiting for EMA 10 crossover.")
            else:
                m_state["monitored_candles_count"] = m_state.get("monitored_candles_count", 0) + 1

        # Cancellation Trigger 1: 5 candles passed without EMA 10 crossover
        if m_state.get("is_monitoring") and m_state.get("monitored_candles_count", 0) > 5:
            m_state["is_monitoring"] = False
            m_state["monitored_candles_count"] = 0
            m_state["pending_breakout"] = None
            m_state["trend_bias"] = None
            save_state(CONTINUATION_STATE_FILE, m_state)
            logger.info("[Rules] CANCELLED: 5 candles limit exceeded without EMA 10 crossing wave zone.")
            if verbose_callback:
                verbose_callback(
                    signal_type="NONE", price_near_boundary=1, volume_confirmed=(total_volume >= volume_sma_10),
                    stacked_imbalance=False, absorption=False,
                    reason="CANCELLED: 5 candles limit exceeded without EMA 10 crossover", metrics_snapshot=state
                )
            return None

        # Cancellation Trigger 2: Candle body closes back on opposite side of wave during monitoring
        if m_state.get("pending_breakout") == "BUY" and close_p < min_ema:
            m_state["is_monitoring"] = False
            m_state["monitored_candles_count"] = 0
            m_state["pending_breakout"] = None
            m_state["trend_bias"] = None
            save_state(CONTINUATION_STATE_FILE, m_state)
            logger.info("[Rules] CANCELLED: Candle body closed back below wave zone during monitoring.")
            if verbose_callback:
                verbose_callback(
                    signal_type="NONE", price_near_boundary=1, volume_confirmed=(total_volume >= volume_sma_10),
                    stacked_imbalance=False, absorption=False,
                    reason="CANCELLED: Candle body closed back below wave zone", metrics_snapshot=state
                )
            return None

        if m_state.get("pending_breakout") == "SELL" and close_p > max_ema:
            m_state["is_monitoring"] = False
            m_state["monitored_candles_count"] = 0
            m_state["pending_breakout"] = None
            m_state["trend_bias"] = None
            save_state(CONTINUATION_STATE_FILE, m_state)
            logger.info("[Rules] CANCELLED: Candle body closed back above wave zone during monitoring.")
            if verbose_callback:
                verbose_callback(
                    signal_type="NONE", price_near_boundary=1, volume_confirmed=(total_volume >= volume_sma_10),
                    stacked_imbalance=False, absorption=False,
                    reason="CANCELLED: Candle body closed back above wave zone", metrics_snapshot=state
                )
            return None

        # Confirmation Trigger: EMA 10 is completely outside wave zone in trend direction
        current_trend = None
        if ema10 > max_ema and close_p >= min_ema:
            current_trend = "BUY"
        elif ema10 < min_ema and close_p <= max_ema:
            current_trend = "SELL"

        if current_trend is None:
            save_state(CONTINUATION_STATE_FILE, m_state)
            return None

        # Reset pending breakout upon successful EMA 10 crossover confirmation
        m_state["pending_breakout"] = None
        m_state["trend_bias"] = current_trend

        # Pullback detection on current candle
        touches_wave = False
        if current_trend == "BUY" and low_p <= max_ema and close_p >= min_ema:
            touches_wave = True
        elif current_trend == "SELL" and high_p >= min_ema and close_p <= max_ema:
            touches_wave = True

        if not touches_wave:
            save_state(CONTINUATION_STATE_FILE, m_state)
            return None

        # Save State
        save_state(CONTINUATION_STATE_FILE, m_state)

        if not m_state["is_monitoring"]:
            return None

        signal_type = m_state["trend_bias"]

        # Evaluate volume and delta confluences
        vol_ok = total_volume >= volume_sma_10
        delta_ok = (signal_type == "BUY" and delta_val > 0) or (signal_type == "SELL" and delta_val < 0)

        score = 50
        reasons = []
        if vol_ok:
            score += 20
            reasons.append("Volume Confirmed ✅")
        else:
            reasons.append("Volume Unconfirmed ❌")

        if delta_ok:
            score += 20
            reasons.append("Delta Confirmed ✅")
        else:
            reasons.append("Delta Unconfirmed ❌")

        logger.info(f"[Continuation] Evaluating: Trend={signal_type} | Score={score}% | Reasons: {', '.join(reasons)}")

        if score >= 70:
            # Trigger setup!
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

            # Reset state
            m_state["is_monitoring"] = False
            m_state["monitored_candles_count"] = 0
            save_state(CONTINUATION_STATE_FILE, m_state)

            reason_str = " | ".join(reasons)
            return {
                "type": signal_type,
                "strategy": "Trend Continuation",
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
                    "signal_classification": "Continuation Setup",
                    "partial_close_instruction": "TP1 hit: take 25% partial profits & move SL to entry"
                }
            }
        else:
            # Format rejections audit
            rejections_list = []
            vol_symbol = "✅" if vol_ok else "❌"
            rejections_list.append(f"- الحجم: {total_volume:.1f} (المطلوب >= {volume_sma_10:.1f}) {vol_symbol}")
            delta_symbol = "✅" if delta_ok else "❌"
            delta_desc = "عكس الاتجاه" if not delta_ok else "مع الاتجاه"
            rejections_list.append(f"- الدلتا: {delta_val:.1f} ({delta_desc}) {delta_symbol}")

            reason = (
                f"[Continuation] التقييم: {score}% (مرفوض ❌ - المطلوب 70% أو أكثر)\n"
                + "\n".join(rejections_list)
            )

            if verbose_callback:
                verbose_callback(
                    signal_type=signal_type,
                    price_near_boundary=1,
                    volume_confirmed=vol_ok,
                    stacked_imbalance=False,
                    absorption=False,
                    reason=reason,
                    metrics_snapshot=state
                )
            return None


class TrendReversalStrategy:
    """
    Strategy 2: Trend Reversal
    - Phase 1: Wait for a candle to cross the EMA34/50 wave zone and close completely on the other side.
    - Phase 2: Wait for EMA10 to also cross and close on the same side as the candles.
    - If candles cross back before EMA10 crosses, cancel the setup immediately.
    - Starts a 5-candle monitoring window upon EMA10 crossing.
    - Checks Volume and Delta confluences.
    - Stop Loss: 1.5$ outside the wave zone (min_ema - 1.5$ for BUY, max_ema + 1.5$ for SELL).
    """

    @staticmethod
    def get_default_state() -> dict:
        return {
            "phase": 0,                     # 0 = waiting for candle cross, 1 = waiting for EMA10 cross, 2 = monitoring window
            "trend_bias": None,             # "BUY" or "SELL" (target direction of the reversal)
            "monitored_candles_count": 0
        }

    @classmethod
    def evaluate(
        cls,
        state: Dict[str, Any],
        ohlc: Dict[str, Any],
        volume_sma_10: float,
        verbose_callback: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        db = TradeDB()
        tf = state.get("timeframe", "M5")
        if tf != "M5":
            return None

        # Fetch recent candles (limit=2) to identify crossings
        candles = db.get_candles("XAUUSD", tf, limit=2)
        if len(candles) < 2:
            return None

        c_curr = candles[0]
        c_prev = candles[1]

        # Calculate current EMAs
        ema10, ema34_curr, ema50_curr = get_all_emas(db, tf)
        if ema10 <= 0 or ema34_curr <= 0 or ema50_curr <= 0:
            return None

        min_ema_curr = min(ema34_curr, ema50_curr)
        max_ema_curr = max(ema34_curr, ema50_curr)

        # Get previous candle's EMAs dynamically by removing c_curr's close
        closes_prev = [c["close"] for c in reversed(candles[1:100])]
        ema34_prev = calculate_ema(closes_prev, 34)
        ema50_prev = calculate_ema(closes_prev, 50)
        min_ema_prev = min(ema34_prev, ema50_prev)
        max_ema_prev = max(ema34_prev, ema50_prev)

        close_p = ohlc["close"]
        total_volume = ohlc.get("volume", 0)
        delta_val = ohlc.get("delta", 0.0)

        # Load state
        m_state = load_state(REVERSAL_STATE_FILE, cls.get_default_state())

        # State Machine Transitions
        if m_state["phase"] == 0:
            # Phase 0: Look for candle breakout/crossing
            # BUY Reversal: Previous candle closed below previous wave, current candle closes completely above current wave
            if c_prev["close"] < min_ema_prev and close_p > max_ema_curr:
                m_state["phase"] = 1
                m_state["trend_bias"] = "BUY"
                m_state["monitored_candles_count"] = 0
                logger.info(f"[Reversal] Phase 1 Triggered: Candle crossed ABOVE wave. Trend Bias set to BUY.")
            # SELL Reversal: Previous candle closed above previous wave, current candle closes completely below current wave
            elif c_prev["close"] > max_ema_prev and close_p < min_ema_curr:
                m_state["phase"] = 1
                m_state["trend_bias"] = "SELL"
                m_state["monitored_candles_count"] = 0
                logger.info(f"[Reversal] Phase 1 Triggered: Candle crossed BELOW wave. Trend Bias set to SELL.")

        elif m_state["phase"] == 1:
            # Phase 1: Wait for EMA10 crossover
            # Check cancel: candles cross back to the opposite side of wave before EMA10 crosses
            if m_state["trend_bias"] == "BUY" and close_p < min_ema_curr:
                m_state["phase"] = 0
                m_state["trend_bias"] = None
                logger.info(f"[Reversal] Phase 1 CANCELLED: Candle crossed back below wave.")
            elif m_state["trend_bias"] == "SELL" and close_p > max_ema_curr:
                m_state["phase"] = 0
                m_state["trend_bias"] = None
                logger.info(f"[Reversal] Phase 1 CANCELLED: Candle crossed back above wave.")
            else:
                # Check crossover
                if m_state["trend_bias"] == "BUY" and ema10 > max_ema_curr:
                    m_state["phase"] = 2
                    m_state["monitored_candles_count"] = 1
                    logger.info(f"[Reversal] Phase 2 Triggered: EMA10 crossed ABOVE wave. Monitoring started.")
                elif m_state["trend_bias"] == "SELL" and ema10 < min_ema_curr:
                    m_state["phase"] = 2
                    m_state["monitored_candles_count"] = 1
                    logger.info(f"[Reversal] Phase 2 Triggered: EMA10 crossed BELOW wave. Monitoring started.")

        elif m_state["phase"] == 2:
            # Phase 2: Monitoring 5-candle window
            # Check cancel: candles cross back to opposite side of wave
            if m_state["trend_bias"] == "BUY" and close_p < min_ema_curr:
                m_state["phase"] = 0
                m_state["trend_bias"] = None
                m_state["monitored_candles_count"] = 0
                logger.info(f"[Reversal] Phase 2 Monitoring CANCELLED: Candle crossed back below wave.")
            elif m_state["trend_bias"] == "SELL" and close_p > max_ema_curr:
                m_state["phase"] = 0
                m_state["trend_bias"] = None
                m_state["monitored_candles_count"] = 0
                logger.info(f"[Reversal] Phase 2 Monitoring CANCELLED: Candle crossed back above wave.")

        # Save State after transition checks
        save_state(REVERSAL_STATE_FILE, m_state)

        # Evaluate if in Phase 2
        if m_state["phase"] != 2:
            return None

        signal_type = m_state["trend_bias"]

        # Check confluences
        vol_ok = total_volume >= volume_sma_10
        delta_ok = (signal_type == "BUY" and delta_val > 0) or (signal_type == "SELL" and delta_val < 0)

        score = 50
        reasons = []
        if vol_ok:
            score += 20
            reasons.append("Volume Confirmed ✅")
        else:
            reasons.append("Volume Unconfirmed ❌")

        if delta_ok:
            score += 20
            reasons.append("Delta Confirmed ✅")
        else:
            reasons.append("Delta Unconfirmed ❌")

        logger.info(f"[Reversal] Evaluating Candle {m_state['monitored_candles_count']}/5: Trend={signal_type} | Score={score}% | Reasons: {', '.join(reasons)}")

        if score >= 70:
            # Trigger reversal!
            entry = close_p
            if signal_type == "BUY":
                sl = min_ema_curr - 2.0
                risk = abs(entry - sl)
                tp1 = entry + risk
                tp2 = entry + 2.0 * risk
                tp3 = entry + 3.0 * risk
            else:
                sl = max_ema_curr + 2.0
                risk = abs(entry - sl)
                tp1 = entry - risk
                tp2 = entry - 2.0 * risk
                tp3 = entry - 3.0 * risk

            # Reset Reversal State
            m_state["phase"] = 0
            m_state["trend_bias"] = None
            m_state["monitored_candles_count"] = 0
            save_state(REVERSAL_STATE_FILE, m_state)

            reason_str = " | ".join(reasons)
            return {
                "type": signal_type,
                "strategy": "Trend Reversal",
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
                    "ema34": ema34_curr,
                    "ema50": ema50_curr,
                    "score_reasons": reason_str,
                    "signal_classification": "Reversal Setup",
                    "partial_close_instruction": "TP1 hit: take 25% partial profits & move SL to entry"
                }
            }
        else:
            # Check expiration or increment monitored count
            m_state["monitored_candles_count"] += 1
            if m_state["monitored_candles_count"] > 5:
                # Exceeded 5 candles, reset monitoring
                logger.info(f"[Reversal] Monitoring window expired (5 candles). Resetting setup.")
                m_state["phase"] = 0
                m_state["trend_bias"] = None
                m_state["monitored_candles_count"] = 0
                save_state(REVERSAL_STATE_FILE, m_state)

                if verbose_callback:
                    verbose_callback(
                        signal_type=signal_type,
                        price_near_boundary=1,
                        volume_confirmed=vol_ok,
                        stacked_imbalance=False,
                        absorption=False,
                        reason="[Reversal] Exceeded 5 candles monitoring window",
                        metrics_snapshot=state
                    )
            else:
                save_state(REVERSAL_STATE_FILE, m_state)

            return None


def evaluate_rules(
    state: Dict[str, Any],
    ohlc: Dict[str, Any],
    volume_sma_10: float,
    verbose_callback: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    """Wrapper method calling Trend Continuation and Trend Reversal strategies sequentially."""
    tf = state.get("timeframe", "M5")
    if tf not in ["M5", "M1"]:
        tf = "M5"

    # Calculate dynamic volume_sma_10 from DB candles (filtering out MT5 tick volume outliers > 300)
    try:
        db = TradeDB()
        candles = db.get_candles("XAUUSD", tf, limit=15)
        if candles:
            real_vols = [float(c["volume"]) for c in candles if 0 < float(c["volume"]) <= 300]
            if real_vols:
                volume_sma_10 = sum(real_vols) / len(real_vols)
            else:
                volume_sma_10 = 35.0
        else:
            volume_sma_10 = 35.0
    except Exception:
        volume_sma_10 = 35.0

    # 1. Run Trend Continuation Strategy
    sig_cont = TrendContinuationStrategy.evaluate(state, ohlc, volume_sma_10, verbose_callback)
    if sig_cont:
        return sig_cont

    # 2. Run Trend Reversal Strategy
    sig_rev = TrendReversalStrategy.evaluate(state, ohlc, volume_sma_10, verbose_callback)
    if sig_rev:
        return sig_rev

    return None
