import pandas as pd
import numpy as np
import requests
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import pytz

from config import GOLD_FUTURES_SYMBOL, FOREX_SYMBOL, FOREX_EXCHANGE, FOREX_SCREENER, TIMEFRAMES, TWELVE_DATA_API_KEY, GOLDAPI_KEY

logger = logging.getLogger(__name__)

try:
    from tradingview_ta import TA_Handler, Interval
    TV_AVAILABLE = True
except ImportError:
    TV_AVAILABLE = False
    logger.warning("tradingview_ta not available")

TV_INTERVAL_MAP = {}
if TV_AVAILABLE:
    TV_INTERVAL_MAP = {
        '4h': Interval.INTERVAL_4_HOURS,
        '1h': Interval.INTERVAL_1_HOUR,
        '15m': Interval.INTERVAL_15_MINUTES,
        '1d': Interval.INTERVAL_1_DAY,
        '1W': Interval.INTERVAL_1_WEEK,
    }

# Twelve Data interval mapping
TWELVE_DATA_INTERVALS = {
    '15M':    '15min',
    '1H':     '1h',
    '4H':     '4h',
    'Daily':  '1day',
    'Weekly': '1week',
}

class MarketData:
    """Handles all market data fetching for XAU/USD via Twelve Data + TradingView"""

    def __init__(self):
        import yfinance as yf
        self._ticker = yf.Ticker(GOLD_FUTURES_SYMBOL)
        self._base_url = "https://api.twelvedata.com"

    # ────────────────────────────────────────────────────────────
    # US Dollar Index (DXY) Tracking
    # ────────────────────────────────────────────────────────────
    def get_dxy_status(self) -> Dict:
        """Fetch US Dollar Index (DXY) status to check correlation"""
        # Try Twelve Data first
        if TWELVE_DATA_API_KEY:
            try:
                url = f"{self._base_url}/price?symbol=DXY&apikey={TWELVE_DATA_API_KEY}"
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if 'price' in data:
                        price = float(data['price'])
                        # Fetch daily change
                        series_url = f"{self._base_url}/time_series?symbol=DXY&interval=1day&outputsize=2&apikey={TWELVE_DATA_API_KEY}"
                        sr = requests.get(series_url, timeout=10)
                        change = 0.0
                        if sr.status_code == 200:
                            sdata = sr.json()
                            if 'values' in sdata and len(sdata['values']) >= 2:
                                prev_close = float(sdata['values'][1]['close'])
                                change = ((price - prev_close) / prev_close) * 100
                        return {
                            'price': round(price, 2),
                            'change': round(change, 2),
                            'trend': 'Bullish 📈' if change > 0.05 else 'Bearish 📉' if change < -0.05 else 'Neutral ↔️',
                            'source': 'Twelve Data (DXY)',
                        }
            except Exception as e:
                logger.error(f"DXY Twelve Data error: {e}")

        # Fallback to yfinance DX-Y.NYB
        try:
            import yfinance as yf
            dxy_ticker = yf.Ticker("DX-Y.NYB")
            hist = dxy_ticker.history(period="2d")
            if not hist.empty and len(hist) >= 2:
                current = float(hist.iloc[-1]['Close'])
                prev = float(hist.iloc[-2]['Close'])
                change = ((current - prev) / prev) * 100
                return {
                    'price': round(current, 2),
                    'change': round(change, 2),
                    'trend': 'Bullish 📈' if change > 0.05 else 'Bearish 📉' if change < -0.05 else 'Neutral ↔️',
                    'source': 'yfinance (DX-Y.NYB)',
                }
        except Exception as e:
            logger.error(f"DXY yfinance fallback error: {e}")

        return {'price': 100.0, 'change': 0.0, 'trend': 'Unknown ↔️', 'source': 'None'}

    def get_current_price(self) -> Dict:
        """Get live XAU/USD spot price from the local SQLite database (populated by MT5)"""
        dxy = {'price': 100.0, 'change': 0.0, 'trend': 'Neutral ↔️', 'source': 'None'}
        
        from trade_db import TradeDB
        db = TradeDB()
        
        lp = db.get_live_price("XAUUSD")
        
        if lp:
            price = lp['bid']
            open_p = price
            high_p = price
            low_p = price
            change = 0.0
            
            # Fetch today's Daily candle to get open/high/low
            d1_candles = db.get_candles("XAUUSD", "D1", limit=1)
            if d1_candles:
                c = d1_candles[0]
                open_p = c['open']
                high_p = max(c['high'], price)
                low_p = min(c['low'], price)
                change = ((price - open_p) / open_p) * 100 if open_p > 0 else 0.0
                
            return {
                'price': round(price, 2),
                'open':  round(open_p, 2),
                'high':  round(high_p, 2),
                'low':   round(low_p, 2),
                'volume': 0,
                'change': round(change, 2),
                'adr': 25.0, # Gold average daily range approximation
                'dxy': dxy,
                'timestamp': lp.get('server_time') or datetime.now().isoformat(),
                'source': 'MetaTrader 5 Live Price',
            }
            
        # Fallback to last M1 candle close
        m1_candles = db.get_candles("XAUUSD", "M1", limit=1)
        if m1_candles:
            c = m1_candles[0]
            price = c['close']
            return {
                'price': round(price, 2),
                'open':  round(c['open'], 2),
                'high':  round(c['high'], 2),
                'low':   round(c['low'], 2),
                'volume': c['volume'] or 0,
                'change': 0.0,
                'adr': 25.0,
                'dxy': dxy,
                'timestamp': c['time'],
                'source': 'MetaTrader 5 Database Candles',
            }
            
        # Default fallback if database is completely empty
        return {
            'price': 2000.0,
            'open':  2000.0,
            'high':  2000.0,
            'low':   2000.0,
            'volume': 0,
            'change': 0.0,
            'adr': 25.0,
            'dxy': dxy,
            'timestamp': datetime.now().isoformat(),
            'source': 'MetaTrader 5 (No Data in DB)',
        }

    # ────────────────────────────────────────────────────────────
    # OHLCV data from Twelve Data
    # ────────────────────────────────────────────────────────────
    def _get_twelvedata_ohlcv(self, timeframe: str, outputsize: int = 200) -> Optional[pd.DataFrame]:
        """Deprecated Twelve Data getter - kept for compatibility but returns empty"""
        return None

    def get_ohlcv(self, timeframe: str = '1H') -> Optional[pd.DataFrame]:
        """Get OHLCV bars directly from our local SQLite database (populated by MT5)"""
        from trade_db import TradeDB
        db = TradeDB()
        
        # Map timeframe name to DB timeframe name
        tf_map = {
            '15M': 'M15',
            '1H': 'H1',
            '4H': 'H4',
            'Daily': 'D1',
            'Weekly': 'W1',
            'M1': 'M1',
            'M5': 'M5',
            'M30': 'M30'
        }
        db_tf = tf_map.get(timeframe, timeframe)
        
        candles = db.get_candles("XAUUSD", db_tf, limit=1500)
        if not candles:
            logger.warning(f"No candles found in database for timeframe {timeframe} ({db_tf})")
            return None
            
        rows = []
        for c in candles:
            time_str = c['time']
            try:
                dt = pd.to_datetime(time_str.replace('Z', '').replace('T', ' '))
            except Exception:
                dt = pd.to_datetime(time_str)
                
            rows.append({
                'Datetime': dt,
                'Open': float(c['open']),
                'High': float(c['high']),
                'Low': float(c['low']),
                'Close': float(c['close']),
                'Volume': float(c['volume'] or 0)
            })
            
        df = pd.DataFrame(rows)
        if not df.empty:
            df.set_index('Datetime', inplace=True)
            return df
            
        return None

    # ────────────────────────────────────────────────────────────
    # TradingView Technical Analysis
    # ────────────────────────────────────────────────────────────
    def get_technical_analysis(self, timeframe: str = '1H') -> Dict:
        """Get TradingView TA signals for the given timeframe"""
        if not TV_AVAILABLE:
            return {'error': 'tradingview_ta not installed'}
        try:
            tf_config   = TIMEFRAMES.get(timeframe, TIMEFRAMES['1H'])
            tv_interval = TV_INTERVAL_MAP.get(tf_config.get('tv_interval'))
            if not tv_interval:
                tv_interval = Interval.INTERVAL_1_HOUR
            handler  = TA_Handler(symbol=FOREX_SYMBOL, screener=FOREX_SCREENER,
                                  exchange=FOREX_EXCHANGE, interval=tv_interval)
            analysis = handler.get_analysis()
            return {
                'recommendation': analysis.summary.get('RECOMMENDATION', 'N/A'),
                'buy': analysis.summary.get('BUY', 0),
                'sell': analysis.summary.get('SELL', 0),
                'neutral': analysis.summary.get('NEUTRAL', 0),
                'indicators': {
                    'rsi':          analysis.indicators.get('RSI'),
                    'macd_macd':    analysis.indicators.get('MACD.macd'),
                    'macd_signal':  analysis.indicators.get('MACD.signal'),
                    'ema_20':       analysis.indicators.get('EMA20'),
                    'ema_50':       analysis.indicators.get('EMA50'),
                    'ema_200':      analysis.indicators.get('EMA200'),
                    'stoch_k':      analysis.indicators.get('Stoch.K'),
                    'stoch_d':      analysis.indicators.get('Stoch.D'),
                    'adx':          analysis.indicators.get('ADX'),
                    'atr':          analysis.indicators.get('ATR'),
                    'bb_upper':     analysis.indicators.get('BB.upper'),
                    'bb_lower':     analysis.indicators.get('BB.lower'),
                    'pivot':        analysis.indicators.get('Pivot.M.Classic.Middle'),
                    'pivot_r1':     analysis.indicators.get('Pivot.M.Classic.R1'),
                    'pivot_r2':     analysis.indicators.get('Pivot.M.Classic.R2'),
                    'pivot_s1':     analysis.indicators.get('Pivot.M.Classic.S1'),
                    'pivot_s2':     analysis.indicators.get('Pivot.M.Classic.S2'),
                },
                'oscillators':      analysis.oscillators,
                'moving_averages':  analysis.moving_averages,
            }
        except Exception as e:
            logger.error(f"TV analysis error ({timeframe}): {e}")
            return {'error': str(e)}

    # ────────────────────────────────────────────────────────────
    # Kill Zone / Session Detection
    # ────────────────────────────────────────────────────────────
    def get_current_session(self) -> Dict:
        """Detect the current trading session with full 24h coverage"""
        utc_now = datetime.now(pytz.utc)
        
        # Convert to Mecca Time (Asia/Riyadh = UTC+3)
        mecca_tz = pytz.timezone('Asia/Riyadh')
        mecca_now = utc_now.astimezone(mecca_tz)
        
        hour    = utc_now.hour
        minute  = utc_now.minute
        t       = hour * 60 + minute  # minutes since midnight UTC

        # ═══════════════════════════════════════════════════════════
        # Full 24-Hour Session Map
        # ═══════════════════════════════════════════════════════════
        sessions = {
            # Asian Session (Sydney + Tokyo) — 00:00-09:00 UTC (03:00-12:00 Mecca)
            'Asian Kill Zone': {
                'start': 0*60, 'end': 3*60,
                'ar': '🌏 جلسة آسيا (Kill Zone)',
                'volatility': 'Low-Medium',
                'liquidity': 'Medium',
                'best_strategy': 'Range Trading / Mean Reversion',
                'description': 'تتشكل نطاقات السعر - ابحث عن القمم والقيعان',
                'quality': 3,  # 1-5 rating for trade quality
            },
            'Asian Extended': {
                'start': 3*60, 'end': 6*60,
                'ar': '🌏 جلسة آسيا (الامتداد)',
                'volatility': 'Low',
                'liquidity': 'Low-Medium',
                'best_strategy': 'Range Trading / Consolidation Watch',
                'description': 'فترة هدوء - تحديد نطاق آسيا (Asian Range)',
                'quality': 2,
            },
            'Pre-London': {
                'start': 6*60, 'end': 7*60,
                'ar': '🌅 ما قبل لندن',
                'volatility': 'Medium',
                'liquidity': 'Medium',
                'best_strategy': 'Breakout Preparation / Range Sweep Watch',
                'description': 'ترقب اكتساح نطاق آسيا',
                'quality': 3,
            },
            # London Session — 07:00-16:00 UTC (10:00-19:00 Mecca)
            'London Open KZ': {
                'start': 7*60, 'end': 10*60,
                'ar': '🇬🇧 لندن فتح (Kill Zone)',
                'volatility': 'High',
                'liquidity': 'Very High',
                'best_strategy': 'Order Flow - VAH/VAL Boundary Rejection',
                'description': 'أقوى فترة! اكتساح نطاق آسيا ثم الانعكاس',
                'quality': 5,
            },
            'London Session': {
                'start': 10*60, 'end': 13*60,
                'ar': '🇬🇧 جلسة لندن',
                'volatility': 'Medium-High',
                'liquidity': 'High',
                'best_strategy': 'Trend Following / POC Retest',
                'description': 'استمرار اتجاه لندن أو تصحيح',
                'quality': 4,
            },
            # NY Session — 13:00-22:00 UTC (16:00-01:00 Mecca)
            'London-NY Overlap KZ': {
                'start': 13*60, 'end': 16*60,
                'ar': '🇬🇧🗽 تداخل لندن-نيويورك (أعلى سيولة)',
                'volatility': 'Very High',
                'liquidity': 'Maximum',
                'best_strategy': 'Order Flow - CVD Divergence & Absorption',
                'description': 'أعلى سيولة في اليوم! أفضل فرص التداول',
                'quality': 5,
            },
            'NY Session': {
                'start': 16*60, 'end': 19*60,
                'ar': '🗽 جلسة نيويورك',
                'volatility': 'Medium-High',
                'liquidity': 'High',
                'best_strategy': 'Momentum / Trend Continuation',
                'description': 'استمرار الزخم أو جني أرباح',
                'quality': 4,
            },
            'NY Close KZ': {
                'start': 19*60, 'end': 22*60,
                'ar': '🗽 إغلاق نيويورك (Kill Zone)',
                'volatility': 'Medium',
                'liquidity': 'Medium',
                'best_strategy': 'Reversal / Position Close',
                'description': 'إغلاق المراكز ومراقبة الانعكاسات',
                'quality': 3,
            },
            # Late Night — 22:00-00:00 UTC (01:00-03:00 Mecca)
            'Late Night': {
                'start': 22*60, 'end': 24*60,
                'ar': '🌙 الفترة الليلية',
                'volatility': 'Very Low',
                'liquidity': 'Low',
                'best_strategy': 'No Trading / Analysis Only',
                'description': 'فترة هدوء - وقت التحليل والإعداد',
                'quality': 1,
            },
        }

        active_session = 'No Active Kill Zone | لا توجد جلسة نشطة'
        active_ar      = '⏸️ بين الجلسات'
        is_kill_zone   = False
        session_data   = {}

        for session_name, data in sessions.items():
            if data['start'] <= t < data['end']:
                active_session = session_name
                active_ar      = data['ar']
                session_data   = data
                # Kill Zones are the high-quality trading windows
                is_kill_zone = 'KZ' in session_name or 'Overlap' in session_name
                break

        # Determine if we're in London-NY overlap (Best liquidity)
        is_overlap = (13*60 <= t < 16*60)
        
        # Calculate next Kill Zone
        next_kz = self._get_next_kill_zone(t, sessions)

        return {
            'session': active_session,
            'session_ar': active_ar,
            'is_kill_zone': is_kill_zone,
            'is_overlap': is_overlap,
            'volatility': session_data.get('volatility', 'Unknown'),
            'liquidity': session_data.get('liquidity', 'Unknown'),
            'best_strategy': session_data.get('best_strategy', 'N/A'),
            'description': session_data.get('description', ''),
            'quality': session_data.get('quality', 0),
            'utc_time': mecca_now.strftime('%I:%M %p بتوقيت مكة المكرمة'),
            'next_kill_zone': next_kz,
            'recommendation': self._get_session_recommendation(is_kill_zone, session_data),
        }

    def _get_next_kill_zone(self, current_minutes: int, sessions: Dict) -> str:
        """Find the next upcoming Kill Zone"""
        kz_sessions = [(name, data) for name, data in sessions.items() 
                       if 'KZ' in name or 'Overlap' in name]
        for name, data in kz_sessions:
            if data['start'] > current_minutes:
                hours_left = (data['start'] - current_minutes) // 60
                mins_left = (data['start'] - current_minutes) % 60
                return f"{data['ar']} (بعد {hours_left}ساعة و{mins_left}دقيقة)"
        # Wrap to next day
        if kz_sessions:
            first = kz_sessions[0]
            total_mins = (24*60 - current_minutes) + first[1]['start']
            return f"{first[1]['ar']} (بعد {total_mins//60}ساعة و{total_mins%60}دقيقة)"
        return 'N/A'

    def _get_session_recommendation(self, is_kill_zone: bool, session_data: Dict) -> str:
        """Get session-specific trading recommendation"""
        quality = session_data.get('quality', 0)
        if quality >= 5:
            return '🔥 وقت مثالي للتداول! أعلى سيولة وأفضل فرص'
        elif quality >= 4:
            return '✅ وقت جيد للتداول — سيولة عالية'
        elif quality >= 3:
            return '⚡ فرص متاحة — تداول بحذر مع إدارة مخاطر'
        elif quality >= 2:
            return '⚠️ سيولة منخفضة — تداول بحذر شديد أو انتظر'
        else:
            return '🚫 لا يُنصح بالتداول — انتظر الجلسة القادمة'


    # ────────────────────────────────────────────────────────────
    # Comprehensive Market Summary
    # ────────────────────────────────────────────────────────────
    def get_market_summary(self) -> Dict:
        """Comprehensive market data: price + multi-TF TA + session info + correlation"""
        return {
            'price':       self.get_current_price(),
            'ta_daily':    self.get_technical_analysis('Daily'),
            'ta_4h':       self.get_technical_analysis('4H'),
            'ta_1h':       self.get_technical_analysis('1H'),
            'ta_15m':      self.get_technical_analysis('15M'),
            'session':     self.get_current_session(),
            'correlation': self.get_correlation_data(),
        }

    def get_multi_timeframe_data(self, timeframes: List[str] = None) -> Dict:
        """OHLCV + TA for multiple timeframes"""
        if timeframes is None:
            timeframes = ['4H', '1H', '15M']
        return {
            tf: {'ohlcv': self.get_ohlcv(tf), 'ta': self.get_technical_analysis(tf)}
            for tf in timeframes
        }

    # ────────────────────────────────────────────────────────────
    # Correlated Assets Monitor (US10Y, S&P500)
    # ────────────────────────────────────────────────────────────
    def get_correlation_data(self) -> Dict:
        """Fetch correlated assets to assess macro environment for gold"""
        result = {
            'us10y': {'price': None, 'change': None, 'impact': 'Unknown'},
            'sp500': {'price': None, 'change': None, 'impact': 'Unknown'},
            'gold_outlook': 'Neutral ↔️',
        }
        bullish_count = 0
        bearish_count = 0

        try:
            import yfinance as yf

            # US 10-Year Treasury Yield (inverse to gold)
            try:
                tnx = yf.Ticker("^TNX")
                hist = tnx.history(period="2d")
                if not hist.empty and len(hist) >= 2:
                    current = float(hist.iloc[-1]['Close'])
                    prev = float(hist.iloc[-2]['Close'])
                    change = round(((current - prev) / prev) * 100, 2)
                    result['us10y'] = {
                        'price': round(current, 3),
                        'change': change,
                        'impact': '📈 سلبي للذهب' if change > 0.5 else '📉 إيجابي للذهب' if change < -0.5 else 'محايد ↔️',
                    }
                    if change > 0.5: bearish_count += 1
                    elif change < -0.5: bullish_count += 1
            except Exception as e:
                logger.warning(f"US10Y fetch error: {e}")

            # S&P 500 (risk-on vs risk-off)
            try:
                spx = yf.Ticker("^GSPC")
                hist = spx.history(period="2d")
                if not hist.empty and len(hist) >= 2:
                    current = float(hist.iloc[-1]['Close'])
                    prev = float(hist.iloc[-2]['Close'])
                    change = round(((current - prev) / prev) * 100, 2)
                    result['sp500'] = {
                        'price': round(current, 2),
                        'change': change,
                        'impact': '📈 Risk-On (سلبي للذهب)' if change > 0.5 else '📉 Risk-Off (إيجابي للذهب)' if change < -0.5 else 'محايد ↔️',
                    }
                    if change > 0.5: bearish_count += 1
                    elif change < -0.5: bullish_count += 1
            except Exception as e:
                logger.warning(f"S&P500 fetch error: {e}")

            # Gold macro outlook based on correlation votes
            if bullish_count >= 2:
                result['gold_outlook'] = 'إيجابي للذهب 🟢 (Bullish Macro)'
            elif bearish_count >= 2:
                result['gold_outlook'] = 'سلبي للذهب 🔴 (Bearish Macro)'
            else:
                result['gold_outlook'] = 'محايد ↔️ (Neutral Macro)'

        except Exception as e:
            logger.error(f"Correlation data fetch error: {e}")

        return result

    # ────────────────────────────────────────────────────────────
    # Key Level Alerts
    # ────────────────────────────────────────────────────────────
    def check_key_levels(self, current_price: float) -> Optional[str]:
        """Check if price is near critical psychological or ATH levels"""
        if not current_price or current_price == 0:
            return None

        key_levels = [
            (2900, "$2,900"), (2950, "$2,950"), (3000, "$3,000"),
            (3050, "$3,050"), (3100, "$3,100"), (3150, "$3,150"),
            (3200, "$3,200"), (3250, "$3,250"), (3300, "$3,300"),
            (3350, "$3,350"), (3400, "$3,400"), (3450, "$3,450"),
            (3500, "$3,500"),
        ]

        for level, label in key_levels:
            distance = abs(current_price - level)
            if distance <= 5:  # Within $5 of a key level
                direction = "فوق ⬆️" if current_price > level else "تحت ⬇️"
                return (
                    f"⚡ <b>تنبيه مستوى حرج | Key Level Alert</b>\n"
                    f"{'─'*35}\n"
                    f"📍 السعر الحالي: <b>${current_price:,.2f}</b>\n"
                    f"🎯 المستوى النفسي: <b>{label}</b> ({direction})\n"
                    f"📏 المسافة: <b>${distance:.2f}</b> فقط\n\n"
                    f"⚠️ <i>توقع تذبذبات حادة وصيد سيولة عند هذا المستوى!</i>"
                )
        return None

    # ────────────────────────────────────────────────────────────
    # Multi-Asset Price Fetcher
    # ────────────────────────────────────────────────────────────
    ASSET_MAP = {
        'XAUUSD': {'yf': 'GC=F', 'td': 'XAU/USD', 'name': 'الذهب | Gold'},
        'EURUSD': {'yf': 'EURUSD=X', 'td': 'EUR/USD', 'name': 'اليورو/دولار'},
        'GBPUSD': {'yf': 'GBPUSD=X', 'td': 'GBP/USD', 'name': 'الجنيه/دولار'},
        'US30':   {'yf': 'YM=F', 'td': None, 'name': 'داو جونز | US30'},
        'NAS100': {'yf': 'NQ=F', 'td': None, 'name': 'ناسداك | NAS100'},
        'BTCUSD': {'yf': 'BTC-USD', 'td': 'BTC/USD', 'name': 'بيتكوين | BTC'},
    }

    def get_asset_price(self, asset: str = 'XAUUSD') -> Dict:
        """Fetch live price for any supported asset"""
        asset_info = self.ASSET_MAP.get(asset, self.ASSET_MAP['XAUUSD'])
        try:
            import yfinance as yf
            ticker = yf.Ticker(asset_info['yf'])
            hist = ticker.history(period="2d")
            if not hist.empty and len(hist) >= 1:
                current = float(hist.iloc[-1]['Close'])
                prev = float(hist.iloc[-2]['Close']) if len(hist) >= 2 else current
                change = round(((current - prev) / prev) * 100, 2) if prev != 0 else 0.0
                return {
                    'asset': asset,
                    'name': asset_info['name'],
                    'price': round(current, 2),
                    'change': change,
                    'trend': '📈 صعود' if change > 0.1 else '📉 هبوط' if change < -0.1 else '↔️ مستقر',
                }
        except Exception as e:
            logger.error(f"Asset price fetch error ({asset}): {e}")
        return {'asset': asset, 'name': asset_info.get('name', asset), 'price': 0, 'change': 0, 'trend': 'Unknown'}

