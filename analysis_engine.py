import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional, Any
from utils.indicators import (get_all_indicators, calculate_atr,
                               calculate_fibonacci_levels, calculate_ema)

logger = logging.getLogger(__name__)


class AnalysisEngine:
    """Advanced Smart Money Concepts (SMC) + ICT Analysis Engine"""

    # ──────────────────────────────────────────────────────────────────────
    # Order Blocks
    # ──────────────────────────────────────────────────────────────────────
    def find_order_blocks(self, df: pd.DataFrame, lookback: int = 50) -> List[Dict]:
        """
        Detect Bullish/Bearish Order Blocks.
        Bullish OB : last bearish candle before a bullish BOS.
        Bearish OB : last bullish candle before a bearish BOS.
        """
        order_blocks = []
        data = df.tail(max(lookback, 10)).reset_index(drop=True)

        for i in range(2, len(data) - 1):
            # Bullish OB
            if (data['Close'].iloc[i] > data['Open'].iloc[i]          # bull candle
                    and data['Close'].iloc[i-1] < data['Open'].iloc[i-1]   # prev bear
                    and data['Close'].iloc[i] > data['High'].iloc[i-2]):   # BOS up
                rng = data['High'].iloc[i] - data['Low'].iloc[i] + 1e-9
                strength = abs(data['Close'].iloc[i] - data['Open'].iloc[i]) / rng * 100
                order_blocks.append({
                    'type': 'bullish',
                    'high': round(float(data['Open'].iloc[i-1]), 2),
                    'low':  round(float(data['Low'].iloc[i-1]),  2),
                    'index': i-1,
                    'strength': round(float(strength), 1),
                })

            # Bearish OB
            if (data['Close'].iloc[i] < data['Open'].iloc[i]
                    and data['Close'].iloc[i-1] > data['Open'].iloc[i-1]
                    and data['Close'].iloc[i] < data['Low'].iloc[i-2]):
                rng = data['High'].iloc[i] - data['Low'].iloc[i] + 1e-9
                strength = abs(data['Open'].iloc[i] - data['Close'].iloc[i]) / rng * 100
                order_blocks.append({
                    'type': 'bearish',
                    'high': round(float(data['High'].iloc[i-1]),  2),
                    'low':  round(float(data['Open'].iloc[i-1]),  2),
                    'index': i-1,
                    'strength': round(float(strength), 1),
                })

        return order_blocks[-5:]

    # ──────────────────────────────────────────────────────────────────────
    # Fair Value Gaps (ICT)
    # ──────────────────────────────────────────────────────────────────────
    def find_fair_value_gaps(self, df: pd.DataFrame, lookback: int = 50) -> List[Dict]:
        """3-candle FVG pattern (bullish + bearish)."""
        fvgs = []
        data = df.tail(max(lookback, 5)).reset_index(drop=True)

        for i in range(2, len(data)):
            # Bullish FVG: candle[i-2].high < candle[i].low
            if data['High'].iloc[i-2] < data['Low'].iloc[i]:
                fvgs.append({
                    'type':   'bullish',
                    'high':   round(float(data['Low'].iloc[i]),    2),
                    'low':    round(float(data['High'].iloc[i-2]), 2),
                    'mid':    round((float(data['Low'].iloc[i]) + float(data['High'].iloc[i-2])) / 2, 2),
                    'index':  i-1,
                    'filled': float(data['Low'].iloc[i:].min()) <= float(data['High'].iloc[i-2]),
                })
            # Bearish FVG: candle[i-2].low > candle[i].high
            if data['Low'].iloc[i-2] > data['High'].iloc[i]:
                fvgs.append({
                    'type':   'bearish',
                    'high':   round(float(data['Low'].iloc[i-2]), 2),
                    'low':    round(float(data['High'].iloc[i]),  2),
                    'mid':    round((float(data['Low'].iloc[i-2]) + float(data['High'].iloc[i])) / 2, 2),
                    'index':  i-1,
                    'filled': float(data['High'].iloc[i:].max()) >= float(data['Low'].iloc[i-2]),
                })

        unfilled = [f for f in fvgs if not f.get('filled')]
        return unfilled[-5:] if unfilled else fvgs[-3:]

    # ──────────────────────────────────────────────────────────────────────
    # Liquidity Pools
    # ──────────────────────────────────────────────────────────────────────
    def find_liquidity_levels(self, df: pd.DataFrame, lookback: int = 100) -> List[Dict]:
        """BSL / SSL / Equal Highs & Lows."""
        liquidity = []
        data = df.tail(min(lookback, len(df))).reset_index(drop=True)
        if len(data) < 14:
            return []

        atr_s   = calculate_atr(data)
        tol     = float(atr_s.iloc[-1]) * 0.15 if not pd.isna(atr_s.iloc[-1]) else 2.0

        for i in range(2, len(data) - 2):
            if (data['High'].iloc[i] > data['High'].iloc[i-1]
                    and data['High'].iloc[i] > data['High'].iloc[i-2]
                    and data['High'].iloc[i] > data['High'].iloc[i+1]
                    and data['High'].iloc[i] > data['High'].iloc[i+2]):
                liquidity.append({'type': 'BSL (Buy-Side Liquidity)', 'price': round(float(data['High'].iloc[i]), 2)})
            if (data['Low'].iloc[i] < data['Low'].iloc[i-1]
                    and data['Low'].iloc[i] < data['Low'].iloc[i-2]
                    and data['Low'].iloc[i] < data['Low'].iloc[i+1]
                    and data['Low'].iloc[i] < data['Low'].iloc[i+2]):
                liquidity.append({'type': 'SSL (Sell-Side Liquidity)', 'price': round(float(data['Low'].iloc[i]), 2)})

        # Equal Highs / Lows in last 30 candles
        recent = data.tail(30).reset_index(drop=True)
        for i in range(len(recent)):
            for j in range(i+1, min(i+15, len(recent))):
                if abs(float(recent['High'].iloc[i]) - float(recent['High'].iloc[j])) < tol:
                    liquidity.append({'type': '⚡ EQH (Equal Highs)', 'price': round(float(recent['High'].iloc[i]), 2)})
                if abs(float(recent['Low'].iloc[i]) - float(recent['Low'].iloc[j])) < tol:
                    liquidity.append({'type': '⚡ EQL (Equal Lows)',  'price': round(float(recent['Low'].iloc[i]),  2)})

        return liquidity[-8:]

    # ──────────────────────────────────────────────────────────────────────
    # Market Structure  (BOS / CHoCH / Trend)
    # ──────────────────────────────────────────────────────────────────────
    def detect_market_structure(self, df: pd.DataFrame, lookback: int = 60) -> Dict:
        data = df.tail(min(lookback, len(df))).reset_index(drop=True)
        swing_highs, swing_lows = [], []

        for i in range(2, len(data) - 2):
            if (data['High'].iloc[i] >= data['High'].iloc[i-1]
                    and data['High'].iloc[i] >= data['High'].iloc[i-2]
                    and data['High'].iloc[i] >= data['High'].iloc[i+1]
                    and data['High'].iloc[i] >= data['High'].iloc[i+2]):
                swing_highs.append({'price': float(data['High'].iloc[i]), 'idx': i})
            if (data['Low'].iloc[i] <= data['Low'].iloc[i-1]
                    and data['Low'].iloc[i] <= data['Low'].iloc[i-2]
                    and data['Low'].iloc[i] <= data['Low'].iloc[i+1]
                    and data['Low'].iloc[i] <= data['Low'].iloc[i+2]):
                swing_lows.append({'price': float(data['Low'].iloc[i]),  'idx': i})

        trend = 'Neutral'
        bos, choch = None, None

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            hh = swing_highs[-1]['price'] > swing_highs[-2]['price']
            hl = swing_lows[-1]['price']  > swing_lows[-2]['price']
            lh = swing_highs[-1]['price'] < swing_highs[-2]['price']
            ll = swing_lows[-1]['price']  < swing_lows[-2]['price']
            trend = ('Bullish' if hh and hl else 'Bearish' if lh and ll else 'Neutral')

            close = float(data['Close'].iloc[-1])
            if trend == 'Bullish' and close > swing_highs[-1]['price']:
                bos = {'type': 'BOS ✅ Bullish Break', 'price': round(swing_highs[-1]['price'], 2)}
            elif trend == 'Bearish' and close < swing_lows[-1]['price']:
                bos = {'type': 'BOS ✅ Bearish Break', 'price': round(swing_lows[-1]['price'], 2)}
            if trend == 'Bullish' and close < swing_lows[-1]['price']:
                choch = {'type': 'CHoCH ⚠️ Bearish Reversal', 'price': round(swing_lows[-1]['price'], 2)}
                trend = 'Bearish (CHoCH)'
            elif trend == 'Bearish' and close > swing_highs[-1]['price']:
                choch = {'type': 'CHoCH ⚠️ Bullish Reversal', 'price': round(swing_highs[-1]['price'], 2)}
                trend = 'Bullish (CHoCH)'

        range_h = max(sh['price'] for sh in swing_highs[-3:]) if swing_highs else float(data['High'].max())
        range_l = min(sl['price'] for sl in swing_lows[-3:])  if swing_lows  else float(data['Low'].min())
        eq      = (range_h + range_l) / 2
        zone    = 'Premium ⬆️' if float(data['Close'].iloc[-1]) > eq else 'Discount ⬇️'

        return {
            'trend':            trend,
            'bos':              bos,
            'choch':            choch,
            'swing_highs':      [{'price': round(sh['price'], 2)} for sh in swing_highs[-3:]],
            'swing_lows':       [{'price': round(sl['price'], 2)} for sl in swing_lows[-3:]],
            'premium_discount': zone,
            'equilibrium':      round(eq, 2),
            'range_high':       round(range_h, 2),
            'range_low':        round(range_l, 2),
        }

    # ──────────────────────────────────────────────────────────────────────
    # OTE  — Optimal Trade Entry (ICT 61.8-78.6% Fibonacci)
    # ──────────────────────────────────────────────────────────────────────
    def find_ote_zone(self, df: pd.DataFrame) -> Dict:
        """Find the ICT Optimal Trade Entry zone (61.8%–78.6% retracement)."""
        data = df.tail(100).reset_index(drop=True)
        high = float(data['High'].max())
        low  = float(data['Low'].min())
        diff = high - low
        if diff == 0:
            return {}

        # Current price position
        current = float(data['Close'].iloc[-1])
        fib_618 = high - diff * 0.618
        fib_786 = high - diff * 0.786
        in_ote  = fib_786 <= current <= fib_618

        return {
            'range_high': round(high,    2),
            'range_low':  round(low,     2),
            'fib_50':     round(high - diff * 0.5,   2),
            'fib_618':    round(fib_618, 2),
            'fib_705':    round(high - diff * 0.705, 2),
            'fib_786':    round(fib_786, 2),
            'in_ote':     in_ote,
            'current':    round(current, 2),
        }

    # ──────────────────────────────────────────────────────────────────────
    # Volume Imbalances / VWAP deviation
    # ──────────────────────────────────────────────────────────────────────
    def detect_volume_imbalances(self, df: pd.DataFrame) -> List[Dict]:
        """Candles with unusually high volume — potential institutional activity."""
        imbalances = []
        if 'Volume' not in df.columns:
            return imbalances
        data = df.tail(50).reset_index(drop=True)
        avg_vol = data['Volume'].mean()
        if avg_vol == 0:
            return imbalances
        for i in range(len(data)):
            vol = float(data['Volume'].iloc[i])
            if vol > avg_vol * 2.0:
                direction = 'Bullish' if data['Close'].iloc[i] >= data['Open'].iloc[i] else 'Bearish'
                imbalances.append({
                    'price': round(float(data['Close'].iloc[i]), 2),
                    'volume_ratio': round(vol / avg_vol, 1),
                    'direction': direction,
                    'index': i,
                })
        return imbalances[-3:]

    def detect_judas_swing(self, df: pd.DataFrame, structure: Dict) -> Optional[Dict]:
        """Detect stop hunts / liquidity sweeps (Judas Swing)"""
        if df is None or df.empty or not structure or not structure.get('swing_highs'):
            return None
        
        last_candles = df.tail(3)
        swing_highs = [sh['price'] for sh in structure['swing_highs']]
        swing_lows = [sl['price'] for sl in structure['swing_lows']]
        
        if not swing_highs or not swing_lows:
            return None
            
        recent_max = float(last_candles['High'].max())
        recent_min = float(last_candles['Low'].min())
        recent_close = float(df['Close'].iloc[-1])
        
        # Bullish Liquidity Sweep (SSL Sweep): Price went below a swing low, then closed above it
        for sl in swing_lows:
            if recent_min < sl and recent_close > sl:
                return {
                    'type': 'Bullish Judas Swing (SSL Sweep) 🟢',
                    'swept_level': round(sl, 2),
                    'low_reached': round(recent_min, 2),
                    'confluence': 'High institutional buy pressure (stop-hunt complete)'
                }
                
        # Bearish Liquidity Sweep (BSL Sweep): Price went above a swing high, then closed below it
        for sh in swing_highs:
            if recent_max > sh and recent_close < sh:
                return {
                    'type': 'Bearish Judas Swing (BSL Sweep) 🔴',
                    'swept_level': round(sh, 2),
                    'high_reached': round(recent_max, 2),
                    'confluence': 'High institutional sell pressure (stop-hunt complete)'
                }
                
        return None

    def find_inducement(self, df: pd.DataFrame) -> Optional[Dict]:
        """Detect the closest minor structural pullback (Inducement level)"""
        if df is None or len(df) < 15:
            return None
        data = df.tail(20).reset_index(drop=True)
        for i in range(len(data) - 3, 2, -1):
            if data['Low'].iloc[i] < data['Low'].iloc[i-1] and data['Low'].iloc[i] < data['Low'].iloc[i+1]:
                return {'type': 'Minor Low (IDM)', 'price': round(float(data['Low'].iloc[i]), 2)}
            if data['High'].iloc[i] > data['High'].iloc[i-1] and data['High'].iloc[i] > data['High'].iloc[i+1]:
                return {'type': 'Minor High (IDM)', 'price': round(float(data['High'].iloc[i]), 2)}
        return None

    # ──────────────────────────────────────────────────────────────────────
    # Full Analysis
    # ──────────────────────────────────────────────────────────────────────
    def full_analysis(self, df: pd.DataFrame, dxy_trend: str = 'Neutral ↔️') -> Dict:
        """Run complete SMC/ICT analysis and return a structured dict."""
        if df is None or df.empty:
            return {'error': 'DataFrame is empty or None'}
        dxy_trend = dxy_trend or 'Neutral ↔️'
        try:
            order_blocks = self.find_order_blocks(df)
            fvg          = self.find_fair_value_gaps(df)
            liquidity    = self.find_liquidity_levels(df)
            structure    = self.detect_market_structure(df)
            ote          = self.find_ote_zone(df)
            vol_imb      = self.detect_volume_imbalances(df)
            indicators   = get_all_indicators(df)
            
            # Judas Swing and Inducement
            judas_swing = self.detect_judas_swing(df, structure)
            inducement  = self.find_inducement(df)

            # Bias scoring
            score = 0
            if structure['trend'] in ('Bullish', 'Bullish (CHoCH)'):
                score += 2
            elif structure['trend'] in ('Bearish', 'Bearish (CHoCH)'):
                score -= 2
            
            # DXY Correlation Modifier (Inverse relationship)
            if 'Bullish' in dxy_trend:
                score -= 1  # DXY up = Gold down pressure
            elif 'Bearish' in dxy_trend:
                score += 1  # DXY down = Gold up pressure
                
            if indicators.get('rsi'):
                if indicators['rsi'] > 70: score -= 1
                elif indicators['rsi'] < 30: score += 1
            if structure.get('premium_discount') == 'Discount ⬇️': score += 1
            elif structure.get('premium_discount') == 'Premium ⬆️': score -= 1
            
            # RSI Divergence Modifier (+2 / -2 for high probability reversals)
            divergence = indicators.get('divergence')
            if divergence:
                if "Bullish" in divergence:
                    score += 2
                elif "Bearish" in divergence:
                    score -= 2

            # ADR Exhaustion Modifier
            atr = indicators.get('atr') or 0.0
            range_high = structure.get('range_high') or 0.0
            range_low = structure.get('range_low') or 0.0
            day_range = range_high - range_low
            is_exhausted = False
            if atr > 0.0 and day_range > (atr * 0.90):
                is_exhausted = True
                # Penalize trend following when daily range is exhausted
                if score > 0: score = max(0, score - 1)
                elif score < 0: score = min(0, score + 1)

            # EMAs
            ema20 = indicators.get('ema_20') or 0
            ema50 = indicators.get('ema_50') or 0
            if ema20 and ema50:
                if ema20 > ema50: score += 1
                else:             score -= 1

            bias = 'Bullish' if score >= 2 else 'Bearish' if score <= -2 else 'Neutral'

            return {
                'order_blocks':     order_blocks,
                'fvg':              fvg,
                'liquidity':        liquidity,
                'ote':              ote,
                'volume_imbalances': vol_imb,
                'judas_swing':      judas_swing,
                'inducement':       inducement,
                'structure':        structure.get('trend', 'N/A'),
                'bos':              structure.get('bos'),
                'choch':            structure.get('choch'),
                'swing_highs':      structure.get('swing_highs', []),
                'swing_lows':       structure.get('swing_lows', []),
                'premium_discount': structure.get('premium_discount', 'N/A'),
                'equilibrium':      structure.get('equilibrium'),
                'range_high':       structure.get('range_high'),
                'range_low':        structure.get('range_low'),
                'indicators':       indicators,
                'divergence':       divergence,
                'adr_exhausted':    is_exhausted,
                'bias':             bias,
                'bias_score':       score,
            }
        except Exception as e:
            logger.error(f"full_analysis error: {e}", exc_info=True)
            return {'error': str(e)}

    # ──────────────────────────────────────────────────────────────────────
    # 1. Mean Reversion Analysis
    # ──────────────────────────────────────────────────────────────────────
    def analyze_mean_reversion(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analyze market for Mean Reversion (Overbought/Oversold bounds)"""
        try:
            indicators = get_all_indicators(df)
            rsi = indicators.get('rsi') or 50.0
            stoch = indicators.get('stochastic') or {'k': 50.0, 'd': 50.0}
            stoch_k = stoch.get('k') or 50.0
            
            bb = indicators.get('bollinger') or {'upper': 0.0, 'middle': 0.0, 'lower': 0.0}
            close = float(df['Close'].iloc[-1])
            upper_band = bb['upper']
            lower_band = bb['lower']
            
            direction = 'Neutral'
            score = 0
            
            if close >= upper_band * 0.998 and rsi >= 68 and stoch_k >= 80:
                direction = 'Bearish Reversion 📉'
                score = 3
            elif close <= lower_band * 1.002 and rsi <= 32 and stoch_k <= 20:
                direction = 'Bullish Reversion 📈'
                score = 3
                
            return {
                'strategy': 'Mean Reversion',
                'direction': direction,
                'score': score,
                'rsi': round(rsi, 2),
                'stoch_k': round(stoch_k, 2),
            }
        except Exception as e:
            logger.error(f"Mean reversion analysis error: {e}")
            return {'direction': 'Neutral', 'score': 0}

    # ──────────────────────────────────────────────────────────────────────
    # 2. Momentum & Range Breakout Analysis
    # ──────────────────────────────────────────────────────────────────────
    def analyze_momentum_breakout(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analyze if price is breaking out from a tight volatility squeeze"""
        try:
            if len(df) < 30:
                return {'direction': 'Neutral', 'squeeze': False}
                
            close = float(df['Close'].iloc[-1])
            high = float(df['High'].iloc[-1])
            low = float(df['Low'].iloc[-1])
            
            # Bollinger Bands Width to detect Squeeze
            bb_period = 20
            sma = df['Close'].rolling(window=bb_period).mean()
            std = df['Close'].rolling(window=bb_period).std()
            upper = sma + (std * 2.0)
            lower = sma - (std * 2.0)
            
            bb_width = (upper - lower) / sma
            latest_width = float(bb_width.iloc[-1])
            
            # ADX proxy (strength of trend)
            # A simple rate of change of EMAs to measure trend acceleration
            ema12 = calculate_ema(df, 12)
            ema26 = calculate_ema(df, 26)
            trend_strength = abs(ema12.iloc[-1] - ema26.iloc[-1]) / ema26.iloc[-1] * 100
            
            is_squeeze = latest_width < 0.008  # BB width is less than 0.8% of price
            direction = 'Neutral'
            
            # Check for breakout of the bands
            if is_squeeze or latest_width < 0.012:
                if close > upper.iloc[-1] and trend_strength > 0.5:
                    direction = 'Bullish Breakout 🚀'
                elif close < lower.iloc[-1] and trend_strength > 0.5:
                    direction = 'Bearish Breakout 🪂'
                    
            return {
                'strategy': 'Momentum Breakout',
                'direction': direction,
                'squeeze': is_squeeze,
                'width': round(latest_width, 4),
                'trend_strength': round(trend_strength, 2),
            }
        except Exception as e:
            logger.error(f"Momentum breakout analysis error: {e}")
            return {'direction': 'Neutral', 'squeeze': False}

    # ──────────────────────────────────────────────────────────────────────
    # 3. Volume Profile & Order Flow
    # ──────────────────────────────────────────────────────────────────────
    def analyze_volume_profile(self, df: pd.DataFrame, bins_count: int = 50) -> Dict[str, Any]:
        """Calculate POC, Value Area High/Low and check for volume spikes"""
        try:
            if len(df) < 50:
                return {'poc': 0.0, 'vah': 0.0, 'val': 0.0, 'spike': False}
                
            prices = df['Close'].values
            volumes = df['Volume'].values
            
            # Clean volumes (in case yfinance returns 0s for some candles)
            avg_vol = float(np.mean(volumes[-20:]))
            if avg_vol == 0:
                avg_vol = 1.0
                
            latest_vol = float(volumes[-1])
            is_spike = latest_vol > (avg_vol * 2.0)
            
            # Calculate Volume Profile (POC, VAH, VAL)
            price_min, price_max = float(np.min(prices)), float(np.max(prices))
            if price_max == price_min:
                price_max += 0.01
                
            bin_width = (price_max - price_min) / bins_count
            bins = np.linspace(price_min, price_max, bins_count + 1)
            
            # Assign volumes to price bins
            volume_profile = np.zeros(bins_count)
            for p, v in zip(prices, volumes):
                bin_idx = min(int((p - price_min) / bin_width), bins_count - 1)
                volume_profile[bin_idx] += v
                
            # Point of Control (POC)
            poc_bin_idx = int(np.argmax(volume_profile))
            poc = float(price_min + (poc_bin_idx * bin_width) + (bin_width / 2.0))
            
            # Value Area (70% of total volume centered around POC)
            total_vol = float(np.sum(volume_profile))
            target_vol = total_vol * 0.70
            
            # Simple approximation of VAH/VAL: expansion from POC
            current_vol = volume_profile[poc_bin_idx]
            left = poc_bin_idx - 1
            right = poc_bin_idx + 1
            
            while current_vol < target_vol and (left >= 0 or right < bins_count):
                vol_left = volume_profile[left] if left >= 0 else 0
                vol_right = volume_profile[right] if right < bins_count else 0
                
                if vol_left >= vol_right:
                    current_vol += vol_left
                    left -= 1
                else:
                    current_vol += vol_right
                    right += 1
                    
            val = float(price_min + (max(0, left + 1) * bin_width))
            vah = float(price_min + (min(bins_count - 1, right - 1) * bin_width))
            
            return {
                'poc': round(poc, 2),
                'vah': round(vah, 2),
                'val': round(val, 2),
                'spike': is_spike,
                'avg_volume': round(avg_vol, 1),
                'latest_volume': round(latest_vol, 1),
            }
        except Exception as e:
            logger.error(f"Volume profile analysis error: {e}")
            return {'poc': 0.0, 'vah': 0.0, 'val': 0.0, 'spike': False}

    # ──────────────────────────────────────────────────────────────────────
    # 4. Pivot Points & Fibonacci Clusters
    # ──────────────────────────────────────────────────────────────────────
    def analyze_pivot_rebound(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Generate Daily Standard Pivot Points and Fibonacci retracements"""
        try:
            # 1. Pivot Points of the last 24 candles (approximates 1 trading day)
            day_data = df.tail(24)
            h = float(day_data['High'].max())
            l = float(day_data['Low'].min())
            c = float(day_data['Close'].iloc[-1])
            
            p = (h + l + c) / 3.0
            r1 = (2.0 * p) - l
            s1 = (2.0 * p) - h
            r2 = p + (h - l)
            s2 = p - (h - l)
            r3 = h + 2.0 * (p - l)
            s3 = l - 2.0 * (h - p)
            
            # 2. Fibonacci levels of the last 100 candles
            htf_data = df.tail(100)
            hh = float(htf_data['High'].max())
            ll = float(htf_data['Low'].min())
            fibs = calculate_fibonacci_levels(hh, ll, trend='up') # get levels
            
            return {
                'pivots': {
                    'P': round(p, 2),
                    'R1': round(r1, 2), 'S1': round(s1, 2),
                    'R2': round(r2, 2), 'S2': round(s2, 2),
                    'R3': round(r3, 2), 'S3': round(s3, 2),
                },
                'fibs': {k: round(float(v), 2) for k, v in fibs.items()},
            }
        except Exception as e:
            logger.error(f"Pivot rebound analysis error: {e}")
            return {'pivots': {}, 'fibs': {}}

    # ──────────────────────────────────────────────────────────────────────
    # 5. Market Rebound Zone Predictor
    # ──────────────────────────────────────────────────────────────────────
    def predict_rebound_zones(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """Predict highest probability price zones for market rebounds"""
        try:
            if len(df) < 50:
                return None
                
            close = float(df['Close'].iloc[-1])
            atr_val = calculate_atr(df).iloc[-1] or 3.0
            buffer = max(1.5, atr_val * 0.3)  # Search buffer zone around prices
            
            # Gather all levels from all strategies
            obs = self.find_order_blocks(df)
            fvgs = self.find_fair_value_gaps(df)
            vp = self.analyze_volume_profile(df)
            piv = self.analyze_pivot_rebound(df)
            
            poc = vp.get('poc', 0.0)
            vah = vp.get('vah', 0.0)
            val = vp.get('val', 0.0)
            
            fib_levels = piv.get('fibs', {})
            pivot_levels = piv.get('pivots', {})
            
            # Define potential rebound target ranges:
            # We check support levels (below current price) and resistance levels (above current price)
            support_levels = []
            resistance_levels = []
            
            # Add Pivot supports/resistances
            if pivot_levels:
                support_levels.append(('Pivot S1', pivot_levels['S1']))
                support_levels.append(('Pivot S2', pivot_levels['S2']))
                support_levels.append(('Pivot S3', pivot_levels['S3']))
                
                resistance_levels.append(('Pivot R1', pivot_levels['R1']))
                resistance_levels.append(('Pivot R2', pivot_levels['R2']))
                resistance_levels.append(('Pivot R3', pivot_levels['R3']))
                
            # Add Fibonacci levels
            for name, val_price in fib_levels.items():
                if name in ['0.382', '0.5', '0.618', '0.786']:
                    if val_price < close:
                        support_levels.append((f"Fib {name}", val_price))
                    else:
                        resistance_levels.append((f"Fib {name}", val_price))
                        
            # Add Order Blocks
            for ob in obs:
                ob_price = (ob['high'] + ob['low']) / 2.0
                if ob['type'] == 'bullish' and ob_price < close:
                    support_levels.append(('Order Block (Bullish)', ob_price))
                elif ob['type'] == 'bearish' and ob_price > close:
                    resistance_levels.append(('Order Block (Bearish)', ob_price))
                    
            # Add Volume Profile limits
            if val > 0 and val < close:
                support_levels.append(('Volume Profile VAL', val))
            if Vah_price := vah:
                if Vah_price > close:
                    resistance_levels.append(('Volume Profile VAH', Vah_price))
            if poc > 0:
                if poc < close:
                    support_levels.append(('Volume Profile POC', poc))
                else:
                    resistance_levels.append(('Volume Profile POC', poc))

            # Find Clusters (areas where multiple levels are close to each other)
            best_zone = None
            max_confluences = 0
            zone_type = 'Neutral'
            reasons = []
            
            # 1. Check Support Clusters (Bullish Rebound)
            for ref_name, ref_price in support_levels:
                cluster = [ref_price]
                names = [ref_name]
                for other_name, other_price in support_levels:
                    if other_name != ref_name and abs(other_price - ref_price) <= buffer:
                        cluster.append(other_price)
                        names.append(other_name)
                        
                unique_names = list(set(names))
                if len(unique_names) > max_confluences:
                    max_confluences = len(unique_names)
                    zone_mean = float(np.mean(cluster))
                    best_zone = (zone_mean - buffer, zone_mean + buffer)
                    zone_type = 'BULLISH'
                    reasons = unique_names
                    
            # 2. Check Resistance Clusters (Bearish Rebound)
            for ref_name, ref_price in resistance_levels:
                cluster = [ref_price]
                names = [ref_name]
                for other_name, other_price in resistance_levels:
                    if other_name != ref_name and abs(other_price - ref_price) <= buffer:
                        cluster.append(other_price)
                        names.append(other_name)
                        
                unique_names = list(set(names))
                if len(unique_names) > max_confluences:
                    max_confluences = len(unique_names)
                    zone_mean = float(np.mean(cluster))
                    best_zone = (zone_mean - buffer, zone_mean + buffer)
                    zone_type = 'BEARISH'
                    reasons = unique_names

            if best_zone and max_confluences >= 2:
                # Calculate confidence score
                # 2 confluences = 75%, 3 confluences = 85%, 4+ confluences = 90-95%
                confidence = 60
                if max_confluences == 2:   confidence = 75
                elif max_confluences == 3: confidence = 85
                elif max_confluences >= 4: confidence = 90 + min(5, max_confluences - 4)
                
                return {
                    'direction': zone_type,
                    'zone_low': round(best_zone[0], 2),
                    'zone_high': round(best_zone[1], 2),
                    'confidence': confidence,
                    'reasons': reasons,
                }
            return None
        except Exception as e:
            logger.error(f"Rebound zone prediction error: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════
    #  NEW ADVANCED STRATEGIES  (added 2026-07-09)
    # ══════════════════════════════════════════════════════════════════════

    # ──────────────────────────────────────────────────────────────────────
    # 6. ICT Supply & Demand Zone Detection
    # ──────────────────────────────────────────────────────────────────────
    def analyze_supply_demand_zones(
        self, df: pd.DataFrame, lookback: int = 80, consolidation_window: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Detect institutional Supply & Demand zones.

        Supply zone  — tight consolidation followed by a sharp drop (imbalance sell).
        Demand zone  — tight consolidation followed by a sharp rally (imbalance buy).

        Each zone records whether price has revisited (tested) it since creation.

        Args:
            df: OHLCV DataFrame.
            lookback: how far back to scan.
            consolidation_window: candles used to measure tightness.

        Returns:
            List of zone dicts with keys:
                type, high, low, strength (0-100), tested (bool), index.
        """
        try:
            zones: List[Dict[str, Any]] = []
            data = df.tail(max(lookback, 20)).reset_index(drop=True)
            if len(data) < consolidation_window + 5:
                return zones

            atr_s = calculate_atr(data)
            atr_val = float(atr_s.iloc[-1]) if not pd.isna(atr_s.iloc[-1]) else 3.0

            for i in range(consolidation_window, len(data) - 2):
                # --- measure consolidation range for the window ending at i ---
                window_slice = data.iloc[i - consolidation_window : i]
                window_range = float(window_slice['High'].max() - window_slice['Low'].min())

                # Tight range = consolidation (less than 0.6 × ATR)
                if window_range > atr_val * 0.6:
                    continue

                # Candle right after consolidation
                move_candle_range = abs(
                    float(data['Close'].iloc[i]) - float(data['Open'].iloc[i])
                )
                move_pct = move_candle_range / (atr_val + 1e-9)

                if move_pct < 0.5:
                    continue  # Not impulsive enough

                # --- Volume confirmation ---
                avg_vol = float(data['Volume'].iloc[max(0, i - 20) : i].mean()) if 'Volume' in data.columns else 1.0
                cur_vol = float(data['Volume'].iloc[i]) if 'Volume' in data.columns else 1.0
                vol_ratio = cur_vol / (avg_vol + 1e-9)

                # Strength formula: candle impulse × volume spike (capped at 100)
                strength = min(100.0, (move_pct * 40.0) + (vol_ratio * 20.0))

                zone_high = float(window_slice['High'].max())
                zone_low  = float(window_slice['Low'].min())

                # Determine zone type by impulse direction
                if float(data['Close'].iloc[i]) > float(data['Open'].iloc[i]):
                    zone_type = 'demand'   # Rally out of base
                else:
                    zone_type = 'supply'   # Drop out of base

                # Check if zone has been tested (price returned into the zone later)
                tested = False
                future = data.iloc[i + 1 :]
                if not future.empty:
                    if zone_type == 'demand':
                        tested = bool(float(future['Low'].min()) <= zone_high)
                    else:
                        tested = bool(float(future['High'].max()) >= zone_low)

                zones.append({
                    'type':     zone_type,
                    'high':     round(zone_high, 2),
                    'low':      round(zone_low, 2),
                    'strength': round(float(strength), 1),
                    'tested':   tested,
                    'index':    i,
                })

            # Return the 6 strongest zones
            zones.sort(key=lambda z: z['strength'], reverse=True)
            return zones[:6]

        except Exception as e:
            logger.error(f"analyze_supply_demand_zones error: {e}", exc_info=True)
            return []

    # ──────────────────────────────────────────────────────────────────────
    # 7. Wyckoff Accumulation / Distribution Phase Detector
    # ──────────────────────────────────────────────────────────────────────
    def analyze_wyckoff_phase(self, df: pd.DataFrame, lookback: int = 120) -> Dict[str, Any]:
        """
        Identify which Wyckoff phase the market is in.

        Phases detected:
            • Accumulation  — range-bound, Spring (false breakdown then recovery) = BUY
            • Markup         — trending up after accumulation
            • Distribution   — range-bound, UTAD (false breakout then rejection) = SELL
            • Markdown       — trending down after distribution

        Args:
            df: OHLCV DataFrame (ideally ≥ 120 candles).

        Returns:
            Dict with keys: phase, direction (buy/sell/neutral),
                            signal (Spring/UTAD/None), confluence (list of reasons).
        """
        default: Dict[str, Any] = {
            'phase': 'Unknown', 'direction': 'neutral',
            'signal': None, 'confluence': [],
        }
        try:
            data = df.tail(min(lookback, len(df))).reset_index(drop=True)
            if len(data) < 40:
                return default

            close = data['Close'].astype(float)
            high  = data['High'].astype(float)
            low   = data['Low'].astype(float)

            # ---- Range detection (first 60 % of window = "trading range") ----
            range_end   = int(len(data) * 0.6)
            range_data  = data.iloc[:range_end]
            range_high  = float(range_data['High'].max())
            range_low   = float(range_data['Low'].min())
            range_size  = range_high - range_low

            # Recent price action (last 40 %)
            recent      = data.iloc[range_end:]
            recent_close = float(close.iloc[-1])

            # ---- Trend of recent portion via EMA slope ----
            ema20 = calculate_ema(data, 20)
            ema_slope = (float(ema20.iloc[-1]) - float(ema20.iloc[-6])) if len(ema20) >= 6 else 0.0

            # ---- Volume trend (rising / falling) ----
            vol_recent = float(data['Volume'].iloc[-10:].mean()) if 'Volume' in data.columns else 1.0
            vol_early  = float(data['Volume'].iloc[:20].mean()) if 'Volume' in data.columns else 1.0
            vol_expanding = vol_recent > vol_early * 1.2

            confluence: List[str] = []

            # ---- Spring detection (Accumulation) ----
            # Price dipped below range low then recovered back inside
            spring_detected = False
            for idx in range(range_end, len(data)):
                if float(low.iloc[idx]) < range_low and float(close.iloc[idx]) > range_low:
                    spring_detected = True
                    break

            # ---- UTAD detection (Distribution) ----
            # Price spiked above range high then closed back inside
            utad_detected = False
            for idx in range(range_end, len(data)):
                if float(high.iloc[idx]) > range_high and float(close.iloc[idx]) < range_high:
                    utad_detected = True
                    break

            # ---- Phase classification ----
            phase = 'Unknown'
            direction = 'neutral'
            signal = None

            if spring_detected and ema_slope > 0:
                phase = 'Accumulation (Spring)'
                direction = 'buy'
                signal = 'Spring'
                confluence.append('Spring below support recovered')
                if vol_expanding:
                    confluence.append('Volume expanding on recovery')
            elif utad_detected and ema_slope < 0:
                phase = 'Distribution (UTAD)'
                direction = 'sell'
                signal = 'UTAD'
                confluence.append('UTAD above resistance rejected')
                if vol_expanding:
                    confluence.append('Volume expanding on rejection')
            elif recent_close > range_high and ema_slope > 0:
                phase = 'Markup'
                direction = 'buy'
                confluence.append('Price broke above trading range')
                if vol_expanding:
                    confluence.append('Strong volume confirms markup')
            elif recent_close < range_low and ema_slope < 0:
                phase = 'Markdown'
                direction = 'sell'
                confluence.append('Price broke below trading range')
                if vol_expanding:
                    confluence.append('Strong volume confirms markdown')
            else:
                # Still inside range
                mid = (range_high + range_low) / 2.0
                if recent_close > mid:
                    phase = 'Ranging (upper half)'
                    confluence.append('Price in upper half of trading range')
                else:
                    phase = 'Ranging (lower half)'
                    confluence.append('Price in lower half of trading range')

            # Additional confluence checks
            if ema_slope > 0:
                confluence.append('EMA-20 slope positive')
            elif ema_slope < 0:
                confluence.append('EMA-20 slope negative')

            return {
                'phase':      phase,
                'direction':  direction,
                'signal':     signal,
                'confluence': confluence,
                'range_high': round(range_high, 2),
                'range_low':  round(range_low, 2),
            }

        except Exception as e:
            logger.error(f"analyze_wyckoff_phase error: {e}", exc_info=True)
            return default

    # ──────────────────────────────────────────────────────────────────────
    # 8. Session-Specific Bias Analysis (Asian / London / NY)
    # ──────────────────────────────────────────────────────────────────────
    def analyze_session_bias(
        self, df: pd.DataFrame, session_name: str = 'london'
    ) -> Dict[str, Any]:
        """
        Compute directional bias based on the current trading session.

        Logic:
            Asian  → define the range (Asian high / low); look for liquidity resting
                     above / below.
            London → detect whether Asian high or low was swept (liquidity grab).
            NY     → check if London's directional move continues or reverses.

        Args:
            df: OHLCV DataFrame (should contain enough candles to cover sessions).
            session_name: one of 'asian', 'london', 'ny'.

        Returns:
            Dict with keys:
                session_bias (buy/sell/neutral), asian_high, asian_low,
                sweep_detected (bool), reasoning (str).
        """
        default: Dict[str, Any] = {
            'session_bias': 'neutral', 'asian_high': 0.0, 'asian_low': 0.0,
            'sweep_detected': False, 'reasoning': 'Insufficient data',
        }
        try:
            if len(df) < 30:
                return default

            data = df.tail(60).reset_index(drop=True)
            session_name = session_name.strip().lower()

            # Approximate session splits on the last 60 candles:
            #   Asian  → first 1/3,  London → middle 1/3,  NY → last 1/3
            third = len(data) // 3
            asian_data  = data.iloc[:third]
            london_data = data.iloc[third : 2 * third]
            ny_data     = data.iloc[2 * third :]

            asian_high  = float(asian_data['High'].max())
            asian_low   = float(asian_data['Low'].min())

            result: Dict[str, Any] = {
                'session_bias':   'neutral',
                'asian_high':     round(asian_high, 2),
                'asian_low':      round(asian_low, 2),
                'sweep_detected': False,
                'reasoning':      '',
            }

            if session_name == 'asian':
                # Asian session: just define range, check for liquidity pockets
                asian_range = asian_high - asian_low
                atr_s = calculate_atr(data)
                atr_val = float(atr_s.iloc[-1]) if not pd.isna(atr_s.iloc[-1]) else 3.0

                if asian_range < atr_val * 0.4:
                    result['reasoning'] = (
                        'Tight Asian range — liquidity resting above & below. '
                        'Expect London sweep.'
                    )
                else:
                    result['reasoning'] = 'Wide Asian range — less predictable sweep.'
                # Bias stays neutral during Asian session
                return result

            elif session_name == 'london':
                # London: did price sweep Asian high or low?
                london_high = float(london_data['High'].max())
                london_low  = float(london_data['Low'].min())
                london_close = float(london_data['Close'].iloc[-1])

                swept_high = london_high > asian_high
                swept_low  = london_low < asian_low

                if swept_high and london_close < asian_high:
                    # Swept Asian high then reversed — bearish bias
                    result['session_bias']   = 'sell'
                    result['sweep_detected'] = True
                    result['reasoning'] = (
                        'London swept Asian high (BSL grab) then reversed below — '
                        'bearish session bias.'
                    )
                elif swept_low and london_close > asian_low:
                    # Swept Asian low then reversed — bullish bias
                    result['session_bias']   = 'buy'
                    result['sweep_detected'] = True
                    result['reasoning'] = (
                        'London swept Asian low (SSL grab) then reversed above — '
                        'bullish session bias.'
                    )
                elif swept_high and london_close > asian_high:
                    result['session_bias'] = 'buy'
                    result['reasoning'] = (
                        'London broke above Asian high with conviction — '
                        'bullish continuation bias.'
                    )
                elif swept_low and london_close < asian_low:
                    result['session_bias'] = 'sell'
                    result['reasoning'] = (
                        'London broke below Asian low with conviction — '
                        'bearish continuation bias.'
                    )
                else:
                    result['reasoning'] = (
                        'London has not swept Asian range — wait for clearer move.'
                    )
                return result

            elif session_name == 'ny':
                # NY: does London direction continue or reverse?
                london_open  = float(london_data['Open'].iloc[0])
                london_close = float(london_data['Close'].iloc[-1])
                london_dir   = 'buy' if london_close > london_open else 'sell'

                ny_open  = float(ny_data['Open'].iloc[0])
                ny_close = float(ny_data['Close'].iloc[-1])
                ny_dir   = 'buy' if ny_close > ny_open else 'sell'

                if ny_dir == london_dir:
                    result['session_bias'] = ny_dir
                    result['reasoning'] = (
                        f'NY continues London {london_dir} direction — '
                        f'confluence confirms {ny_dir} bias.'
                    )
                else:
                    result['session_bias'] = ny_dir
                    result['reasoning'] = (
                        f'NY reversed London direction ({london_dir} → {ny_dir}) — '
                        f'possible reversal / profit-taking.'
                    )
                return result

            else:
                result['reasoning'] = f"Unknown session '{session_name}'. Use asian/london/ny."
                return result

        except Exception as e:
            logger.error(f"analyze_session_bias error: {e}", exc_info=True)
            return default

    # ──────────────────────────────────────────────────────────────────────
    # 9. Multi-Timeframe Smart Confluence (MTF)
    # ──────────────────────────────────────────────────────────────────────
    def analyze_multi_timeframe_confluence(
        self,
        df_15m: pd.DataFrame,
        df_1h: pd.DataFrame,
        df_4h: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Score directional confluence across three timeframes.

        Weights: 4H = 3×, 1H = 2×, 15M = 1×.
        Factors per timeframe: market structure, order blocks, FVGs.

        Args:
            df_15m, df_1h, df_4h: OHLCV DataFrames for each timeframe.

        Returns:
            Dict with keys:
                direction (buy/sell/neutral), confidence (0-100),
                details (per-TF breakdown dict).
        """
        default: Dict[str, Any] = {
            'direction': 'neutral', 'confidence': 0,
            'details': {},
        }
        try:
            frames = {
                '15m': {'df': df_15m, 'weight': 1},
                '1h':  {'df': df_1h,  'weight': 2},
                '4h':  {'df': df_4h,  'weight': 3},
            }

            total_weighted_score = 0.0
            max_possible = 0.0
            details: Dict[str, Any] = {}

            for tf_name, meta in frames.items():
                tf_df = meta['df']
                w     = meta['weight']

                if tf_df is None or tf_df.empty or len(tf_df) < 20:
                    details[tf_name] = {'score': 0, 'direction': 'neutral', 'reasons': ['Insufficient data']}
                    max_possible += w * 5  # max per TF = 5
                    continue

                tf_score = 0
                reasons: List[str] = []

                # --- Market structure ---
                structure = self.detect_market_structure(tf_df)
                trend = structure.get('trend', 'Neutral')
                if 'Bullish' in trend:
                    tf_score += 2
                    reasons.append(f'{tf_name} structure: {trend}')
                elif 'Bearish' in trend:
                    tf_score -= 2
                    reasons.append(f'{tf_name} structure: {trend}')

                # BOS / CHoCH bonus
                if structure.get('bos'):
                    tf_score += 1 if 'Bullish' in structure['bos'].get('type', '') else -1
                    reasons.append(f"{tf_name} {structure['bos']['type']}")
                if structure.get('choch'):
                    tf_score += 1 if 'Bullish' in structure['choch'].get('type', '') else -1
                    reasons.append(f"{tf_name} {structure['choch']['type']}")

                # --- Order Blocks proximity ---
                obs = self.find_order_blocks(tf_df)
                current_price = float(tf_df['Close'].iloc[-1])
                for ob in obs[-3:]:
                    ob_mid = (ob['high'] + ob['low']) / 2.0
                    atr_s = calculate_atr(tf_df)
                    atr_v = float(atr_s.iloc[-1]) if not pd.isna(atr_s.iloc[-1]) else 3.0
                    if abs(current_price - ob_mid) < atr_v * 1.5:
                        if ob['type'] == 'bullish':
                            tf_score += 1
                            reasons.append(f'{tf_name} near bullish OB @ {ob_mid:.2f}')
                        else:
                            tf_score -= 1
                            reasons.append(f'{tf_name} near bearish OB @ {ob_mid:.2f}')
                        break  # only count nearest

                # --- FVG presence ---
                fvgs = self.find_fair_value_gaps(tf_df)
                unfilled_bull = [f for f in fvgs if f['type'] == 'bullish' and not f.get('filled')]
                unfilled_bear = [f for f in fvgs if f['type'] == 'bearish' and not f.get('filled')]
                if unfilled_bull:
                    tf_score += 1
                    reasons.append(f'{tf_name} unfilled bullish FVG')
                if unfilled_bear:
                    tf_score -= 1
                    reasons.append(f'{tf_name} unfilled bearish FVG')

                # Clamp TF score to [-5, 5]
                tf_score = max(-5, min(5, tf_score))

                details[tf_name] = {
                    'score':     tf_score,
                    'direction': 'buy' if tf_score > 0 else ('sell' if tf_score < 0 else 'neutral'),
                    'reasons':   reasons,
                }
                total_weighted_score += tf_score * w
                max_possible += w * 5

            # ---- Overall direction & confidence ----
            if max_possible == 0:
                return default

            # Normalise to 0-100 (score can be negative)
            raw_ratio = total_weighted_score / max_possible   # -1 … +1
            confidence = int(min(100, max(0, abs(raw_ratio) * 100)))
            direction = 'buy' if total_weighted_score > 0 else ('sell' if total_weighted_score < 0 else 'neutral')

            return {
                'direction':  direction,
                'confidence': confidence,
                'details':    details,
            }

        except Exception as e:
            logger.error(f"analyze_multi_timeframe_confluence error: {e}", exc_info=True)
            return default

    # ──────────────────────────────────────────────────────────────────────
    # 10. Smart Entry / SL / TP Calculator
    # ──────────────────────────────────────────────────────────────────────
    def calculate_smart_entry_levels(
        self, df: pd.DataFrame, direction: str, atr_val: float
    ) -> Dict[str, Any]:
        """
        Calculate optimal entry, stop-loss, and three take-profit levels.

        BUY logic:
            Entry  → nearest unfilled bullish FVG mid or bullish OB mid.
            SL     → swing low − 0.5 × ATR.
            TPs    → 1:3, 1:5, 1:8 risk-reward.

        SELL logic (mirror):
            Entry  → nearest unfilled bearish FVG mid or bearish OB mid.
            SL     → swing high + 0.5 × ATR.
            TPs    → 1:3, 1:5, 1:8 risk-reward.

        Entry is validated — must not be more than 2 × ATR away from current price.

        Args:
            df:        OHLCV DataFrame.
            direction: 'buy' or 'sell'.
            atr_val:   current ATR value (pre-calculated).

        Returns:
            Dict with keys: entry, sl, tp1, tp2, tp3, rr_ratio, valid (bool), reason.
        """
        default: Dict[str, Any] = {
            'entry': 0.0, 'sl': 0.0, 'tp1': 0.0, 'tp2': 0.0, 'tp3': 0.0,
            'rr_ratio': 0.0, 'valid': False, 'reason': 'Could not compute levels',
        }
        try:
            if df is None or df.empty or len(df) < 20:
                return default

            current_price = float(df['Close'].iloc[-1])
            direction = direction.strip().lower()
            atr_val = max(float(atr_val), 0.5)  # safety floor

            fvgs = self.find_fair_value_gaps(df)
            obs  = self.find_order_blocks(df)
            structure = self.detect_market_structure(df)

            swing_highs = [sh['price'] for sh in structure.get('swing_highs', [])]
            swing_lows  = [sl['price'] for sl in structure.get('swing_lows', [])]

            entry = current_price  # fallback to market price

            if direction == 'buy':
                # --- Entry: nearest unfilled bullish FVG or bullish OB below price ---
                candidates: List[float] = []
                for fvg in fvgs:
                    if fvg['type'] == 'bullish' and not fvg.get('filled'):
                        candidates.append(fvg['mid'])
                for ob in obs:
                    if ob['type'] == 'bullish':
                        candidates.append((ob['high'] + ob['low']) / 2.0)

                # Pick the nearest candidate that is ≤ current price
                below = [c for c in candidates if c <= current_price]
                if below:
                    entry = max(below)  # closest below

                # SL below swing low − 0.5 × ATR
                sl = (min(swing_lows) - 0.5 * atr_val) if swing_lows else (entry - 1.5 * atr_val)

                risk = entry - sl
                if risk <= 0:
                    risk = atr_val  # fallback

                tp1 = entry + risk * 3.0
                tp2 = entry + risk * 5.0
                tp3 = entry + risk * 8.0

            elif direction == 'sell':
                # --- Entry: nearest unfilled bearish FVG or bearish OB above price ---
                candidates = []
                for fvg in fvgs:
                    if fvg['type'] == 'bearish' and not fvg.get('filled'):
                        candidates.append(fvg['mid'])
                for ob in obs:
                    if ob['type'] == 'bearish':
                        candidates.append((ob['high'] + ob['low']) / 2.0)

                above = [c for c in candidates if c >= current_price]
                if above:
                    entry = min(above)  # closest above

                # SL above swing high + 0.5 × ATR
                sl = (max(swing_highs) + 0.5 * atr_val) if swing_highs else (entry + 1.5 * atr_val)

                risk = sl - entry
                if risk <= 0:
                    risk = atr_val

                tp1 = entry - risk * 3.0
                tp2 = entry - risk * 5.0
                tp3 = entry - risk * 8.0

            else:
                default['reason'] = f"Invalid direction '{direction}'. Use 'buy' or 'sell'."
                return default

            # --- Validate entry distance ---
            dist = abs(entry - current_price)
            valid = dist <= atr_val * 2.0
            reason = 'OK' if valid else f'Entry too far from price ({dist:.2f} > {atr_val * 2:.2f})'

            rr_ratio = round((abs(tp1 - entry) / (abs(entry - sl) + 1e-9)), 1)

            return {
                'entry':    round(entry, 2),
                'sl':       round(sl, 2),
                'tp1':      round(tp1, 2),
                'tp2':      round(tp2, 2),
                'tp3':      round(tp3, 2),
                'rr_ratio': rr_ratio,
                'valid':    valid,
                'reason':   reason,
            }

        except Exception as e:
            logger.error(f"calculate_smart_entry_levels error: {e}", exc_info=True)
            return default

    # ──────────────────────────────────────────────────────────────────────
    # 11. Master Trade Confidence Aggregator
    # ──────────────────────────────────────────────────────────────────────
    def get_trade_confidence(
        self,
        smc_data: Dict[str, Any],
        session_name: str = 'london',
        mtf_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Combine all signal sources into a single 0-100 confidence score.

        Weight distribution:
            • SMC bias score        — 30 %
            • MTF confluence        — 25 %
            • Session strength      — 15 %
            • Volume confirmation   — 15 %
            • Indicator alignment   — 15 %

        Args:
            smc_data:     output from full_analysis().
            session_name: 'asian', 'london', or 'ny'.
            mtf_data:     output from analyze_multi_timeframe_confluence() (optional).

        Returns:
            Dict with keys: confidence (int 0-100), grade (A/B/C/D), summary (str).
        """
        default: Dict[str, Any] = {
            'confidence': 0, 'grade': 'D',
            'summary': 'Unable to calculate confidence.',
        }
        try:
            if not smc_data or smc_data.get('error'):
                return default

            parts: List[str] = []

            # ──── 1. SMC Bias Score (30 %) ────
            bias_score_raw = smc_data.get('bias_score', 0)
            # Normalise: assume range is roughly -6 … +6
            smc_pct = min(100.0, abs(bias_score_raw) / 6.0 * 100.0)
            smc_contrib = smc_pct * 0.30
            bias_dir = smc_data.get('bias', 'Neutral')
            parts.append(f"SMC bias {bias_dir} ({smc_pct:.0f}%)")

            # ──── 2. MTF Confluence (25 %) ────
            mtf_pct = 0.0
            if mtf_data and mtf_data.get('confidence'):
                mtf_pct = float(mtf_data['confidence'])
                mtf_dir = mtf_data.get('direction', 'neutral')
                # Penalise if MTF direction disagrees with SMC bias
                if bias_dir.lower() != 'neutral' and mtf_dir != 'neutral':
                    if ('bullish' in bias_dir.lower() and mtf_dir == 'sell') or \
                       ('bearish' in bias_dir.lower() and mtf_dir == 'buy'):
                        mtf_pct *= 0.3   # heavy penalty for disagreement
                parts.append(f"MTF confluence {mtf_pct:.0f}%")
            mtf_contrib = mtf_pct * 0.25

            # ──── 3. Session Strength (15 %) ────
            session_pct = 50.0  # neutral default
            session_name_lower = session_name.strip().lower()
            if session_name_lower == 'london':
                session_pct = 80.0   # London is highest-volume session
            elif session_name_lower == 'ny':
                session_pct = 70.0
            elif session_name_lower == 'asian':
                session_pct = 40.0   # Asian session = range, lower conviction
            parts.append(f"Session ({session_name}) {session_pct:.0f}%")
            session_contrib = session_pct * 0.15

            # ──── 4. Volume Confirmation (15 %) ────
            vol_pct = 0.0
            vol_imbs = smc_data.get('volume_imbalances', [])
            if vol_imbs:
                # At least one volume spike aligned with bias = high confirmation
                for vi in vol_imbs:
                    vi_dir = vi.get('direction', '')
                    if ('Bullish' in vi_dir and 'Bullish' in bias_dir) or \
                       ('Bearish' in vi_dir and 'Bearish' in bias_dir):
                        vol_pct = min(100.0, vi.get('volume_ratio', 1.0) * 30.0)
                        break
                if vol_pct == 0.0:
                    vol_pct = 30.0  # volume spike exists but opposes bias
            parts.append(f"Volume {vol_pct:.0f}%")
            vol_contrib = vol_pct * 0.15

            # ──── 5. Indicator Alignment (15 %) ────
            ind_pct = 50.0
            indicators = smc_data.get('indicators', {})
            ind_score = 0

            rsi = indicators.get('rsi')
            if rsi is not None:
                if ('Bullish' in bias_dir and rsi < 60) or ('Bearish' in bias_dir and rsi > 40):
                    ind_score += 1  # RSI has room to move
                elif ('Bullish' in bias_dir and rsi > 75) or ('Bearish' in bias_dir and rsi < 25):
                    ind_score -= 1  # Overextended

            macd_info = indicators.get('macd', {})
            hist = macd_info.get('histogram')
            if hist is not None:
                if ('Bullish' in bias_dir and hist > 0) or ('Bearish' in bias_dir and hist < 0):
                    ind_score += 1
                else:
                    ind_score -= 1

            ema20_val = indicators.get('ema_20', 0)
            ema50_val = indicators.get('ema_50', 0)
            if ema20_val and ema50_val:
                if ('Bullish' in bias_dir and ema20_val > ema50_val) or \
                   ('Bearish' in bias_dir and ema20_val < ema50_val):
                    ind_score += 1

            # Divergence bonus
            div = smc_data.get('divergence')
            if div:
                if ('Bullish' in bias_dir and 'Bullish' in div) or \
                   ('Bearish' in bias_dir and 'Bearish' in div):
                    ind_score += 2  # Strong confirmation

            ind_pct = min(100.0, max(0.0, 50.0 + ind_score * 15.0))
            parts.append(f"Indicators {ind_pct:.0f}%")
            ind_contrib = ind_pct * 0.15

            # ──── Final aggregation ────
            confidence = int(min(100, max(0, smc_contrib + mtf_contrib + session_contrib + vol_contrib + ind_contrib)))

            # Grade assignment
            if confidence >= 80:
                grade = 'A'
            elif confidence >= 60:
                grade = 'B'
            elif confidence >= 40:
                grade = 'C'
            else:
                grade = 'D'

            summary = f"Grade {grade} ({confidence}%) — " + " | ".join(parts)

            return {
                'confidence': confidence,
                'grade':      grade,
                'summary':    summary,
            }

        except Exception as e:
            logger.error(f"get_trade_confidence error: {e}", exc_info=True)
            return default

