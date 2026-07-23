import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional

def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate RSI (Relative Strength Index)"""
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    
    # Avoid division by zero
    avg_loss = avg_loss.replace(0.0, 0.00001)
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_ema(df: pd.DataFrame, period: int, column: str = 'Close') -> pd.Series:
    """Calculate EMA (Exponential Moving Average)"""
    return df[column].ewm(span=period, adjust=False).mean()

def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
    """Calculate MACD with signal line and histogram"""
    ema_fast = df['Close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {'macd': macd_line, 'signal': signal_line, 'histogram': histogram}

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate ATR (Average True Range)"""
    high = df['High']
    low = df['Low']
    close = df['Close'].shift(1)
    tr1 = high - low
    tr2 = abs(high - close)
    tr3 = abs(low - close)
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> Dict:
    """Calculate Bollinger Bands"""
    sma = df['Close'].rolling(window=period).mean()
    std = df['Close'].rolling(window=period).std()
    return {'upper': sma + (std * std_dev), 'middle': sma, 'lower': sma - (std * std_dev)}

def calculate_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> Dict:
    """Calculate Stochastic Oscillator"""
    low_min = df['Low'].rolling(window=k_period).min()
    high_max = df['High'].rolling(window=k_period).max()
    denom = high_max - low_min
    denom = denom.replace(0.0, 0.00001)
    k = 100 * (df['Close'] - low_min) / denom
    d = k.rolling(window=d_period).mean()
    return {'k': k, 'd': d}

def find_support_resistance(df: pd.DataFrame, window: int = 10) -> Dict:
    """Find support and resistance levels using pivot points and swing highs/lows"""
    highs = []
    lows = []
    for i in range(window, len(df) - window):
        # Extract slices safely
        slice_high = df['High'].iloc[i-window:i+window+1]
        slice_low = df['Low'].iloc[i-window:i+window+1]
        if df['High'].iloc[i] == slice_high.max():
            highs.append({'price': float(df['High'].iloc[i]), 'index': i})
        if df['Low'].iloc[i] == slice_low.min():
            lows.append({'price': float(df['Low'].iloc[i]), 'index': i})
    
    resistance_levels = sorted(list(set([h['price'] for h in highs[-5:]])), reverse=True) if highs else []
    support_levels = sorted(list(set([l['price'] for l in lows[-5:]]))) if lows else []
    
    return {'resistance': resistance_levels, 'support': support_levels}

def get_all_indicators(df: pd.DataFrame) -> Dict:
    """Calculate all indicators and return as a dictionary"""
    if len(df) < 50:
        # Return fallback values for small datasets
        return {
            'rsi': 50.0,
            'macd': {'value': 0.0, 'signal': 0.0, 'histogram': 0.0},
            'atr': 1.0,
            'bollinger': {'upper': 0.0, 'middle': 0.0, 'lower': 0.0},
            'stochastic': {'k': 50.0, 'd': 50.0},
            'ema_20': 0.0,
            'ema_50': 0.0,
            'ema_200': 0.0,
            'support_resistance': {'support': [], 'resistance': []}
        }
        
    rsi = calculate_rsi(df)
    macd = calculate_macd(df)
    atr = calculate_atr(df)
    bb = calculate_bollinger_bands(df)
    stoch = calculate_stochastic(df)
    ema_20 = calculate_ema(df, 20)
    ema_50 = calculate_ema(df, 50)
    ema_200 = calculate_ema(df, 200)
    sr = find_support_resistance(df)
    
    latest = len(df) - 1
    div = detect_rsi_divergence(df)
    return {
        'rsi': round(float(rsi.iloc[latest]), 2) if not pd.isna(rsi.iloc[latest]) else None,
        'divergence': div,
        'macd': {
            'value': round(float(macd['macd'].iloc[latest]), 2) if not pd.isna(macd['macd'].iloc[latest]) else None,
            'signal': round(float(macd['signal'].iloc[latest]), 2) if not pd.isna(macd['signal'].iloc[latest]) else None,
            'histogram': round(float(macd['histogram'].iloc[latest]), 2) if not pd.isna(macd['histogram'].iloc[latest]) else None,
        },
        'atr': round(float(atr.iloc[latest]), 2) if not pd.isna(atr.iloc[latest]) else None,
        'bollinger': {
            'upper': round(float(bb['upper'].iloc[latest]), 2) if not pd.isna(bb['upper'].iloc[latest]) else None,
            'middle': round(float(bb['middle'].iloc[latest]), 2) if not pd.isna(bb['middle'].iloc[latest]) else None,
            'lower': round(float(bb['lower'].iloc[latest]), 2) if not pd.isna(bb['lower'].iloc[latest]) else None,
        },
        'stochastic': {
            'k': round(float(stoch['k'].iloc[latest]), 2) if not pd.isna(stoch['k'].iloc[latest]) else None,
            'd': round(float(stoch['d'].iloc[latest]), 2) if not pd.isna(stoch['d'].iloc[latest]) else None,
        },
        'ema_20': round(float(ema_20.iloc[latest]), 2) if not pd.isna(ema_20.iloc[latest]) else None,
        'ema_50': round(float(ema_50.iloc[latest]), 2) if not pd.isna(ema_50.iloc[latest]) else None,
        'ema_200': round(float(ema_200.iloc[latest]), 2) if not pd.isna(ema_200.iloc[latest]) else None,
        'support_resistance': sr,
    }

def calculate_fibonacci_levels(high: float, low: float, trend: str = 'up') -> Dict:
    """Calculate Fibonacci retracement and extension levels"""
    diff = high - low
    if trend == 'up':
        return {
            '0.0': high,
            '0.236': high - diff * 0.236,
            '0.382': high - diff * 0.382,
            '0.5': high - diff * 0.5,
            '0.618': high - diff * 0.618,
            '0.786': high - diff * 0.786,
            '1.0': low,
            '-0.272': high + diff * 0.272,  # Extension
            '-0.618': high + diff * 0.618,  # Extension
        }
    else:
        return {
            '0.0': low,
            '0.236': low + diff * 0.236,
            '0.382': low + diff * 0.382,
            '0.5': low + diff * 0.5,
            '0.618': low + diff * 0.618,
            '0.786': low + diff * 0.786,
            '1.0': high,
            '-0.272': low - diff * 0.272,  # Extension
            '-0.618': low - diff * 0.618,  # Extension
        }

def detect_rsi_divergence(df: pd.DataFrame, period: int = 14, lookback: int = 30) -> Optional[str]:
    """Detect if there is a Bullish or Bearish RSI divergence in the last lookback candles"""
    if len(df) < lookback + period:
        return None
        
    prices = df['Close'].tail(lookback).values
    rsi_vals = calculate_rsi(df, period).tail(lookback).values
    
    # Find local swing points
    highs_idx = []
    lows_idx = []
    for i in range(2, lookback - 2):
        # Swing High
        if prices[i] > prices[i-1] and prices[i] > prices[i-2] and prices[i] > prices[i+1] and prices[i] > prices[i+2]:
            highs_idx.append(i)
        # Swing Low
        if prices[i] < prices[i-1] and prices[i] < prices[i-2] and prices[i] < prices[i+1] and prices[i] < prices[i+2]:
            lows_idx.append(i)
            
    # Check Bearish Divergence (Price Higher High, RSI Lower High)
    if len(highs_idx) >= 2:
        i1, i2 = highs_idx[-2], highs_idx[-1]
        if prices[i2] > prices[i1] and rsi_vals[i2] < rsi_vals[i1] and rsi_vals[i2] > 50:
            return "Bearish Divergence 🐻 (انحراف سلبي للمؤسسات)"
            
    # Check Bullish Divergence (Price Lower Low, RSI Higher Low)
    if len(lows_idx) >= 2:
        i1, i2 = lows_idx[-2], lows_idx[-1]
        if prices[i2] < prices[i1] and rsi_vals[i2] > rsi_vals[i1] and rsi_vals[i2] < 50:
            return "Bullish Divergence 🐂 (انحراف إيجابي للمؤسسات)"
            
    return None


