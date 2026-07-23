"""
Backtesting Engine for XAU/USD SMC/ICT Strategy.
Simulates trading historical data and generates detailed reports.
"""

import logging
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, Any, List
from analysis_engine import AnalysisEngine
from utils.indicators import calculate_atr

logger = logging.getLogger(__name__)


class Backtester:
    """Historical backtester for the SMC/ICT trading algorithm."""

    def __init__(self, analysis_engine: AnalysisEngine) -> None:
        """Initialize with an AnalysisEngine instance."""
        self.analysis_engine = analysis_engine

    def run_backtest(self, asset: str = 'XAUUSD', period: str = '3mo', timeframe: str = '1H') -> Dict[str, Any]:
        """
        Run backtest on historical data.
        
        Args:
            asset: Asset symbol (e.g. XAUUSD).
            period: Historical period (e.g. '1mo', '3mo', '6mo').
            timeframe: Timeframe (e.g. '15M', '1H', '4H').
            
        Returns:
            Dictionary containing backtest statistics and trade history.
        """
        # Map timeframe to yfinance intervals
        yf_intervals = {
            '15M': '15m',
            '1H': '1h',
            '4H': '1h', # yfinance doesn't support 4h directly on free tier easily, download 1h and resample if needed
        }
        interval = yf_intervals.get(timeframe, '1h')
        
        logger.info(f"Starting backtest for {asset} ({period}, {timeframe})")
        
        import os
        df = None
        
        # 1. Attempt offline local CSV load first (Guaranteed success on cloud servers without limits)
        if asset == 'XAUUSD' and os.path.exists("gold_history.csv"):
            try:
                df = pd.read_csv("gold_history.csv", parse_dates=['Datetime'], index_col='Datetime')
                if df is not None and not df.empty:
                    logger.info("Successfully loaded historical backtest data from local gold_history.csv")
                    df.sort_index(inplace=True)
            except Exception as csv_err:
                logger.warning(f"Local gold_history.csv load failed: {csv_err}. Trying API fallback...")

        # 2. Attempt Twelve Data download if CSV is not present
        if df is None or df.empty:
            from config import TWELVE_DATA_API_KEY
            if asset == 'XAUUSD' and TWELVE_DATA_API_KEY:
                try:
                    from market_data import MarketData
                    md = MarketData()
                    # Fetch up to 500 candles to get a meaningful backtest
                    df = md._get_twelvedata_ohlcv(timeframe, outputsize=500)
                    if df is not None and not df.empty:
                        logger.info("Successfully loaded backtest data from Twelve Data")
                except Exception as td_err:
                    logger.warning(f"Twelve Data backtest download failed: {td_err}. Falling back to yfinance...")

        if df is None or df.empty:
            proxy_symbol = 'GC=F' if asset == 'XAUUSD' else asset
            try:
                df = yf.download(proxy_symbol, period=period, interval=interval, progress=False)
                if df.empty:
                    return {'error': 'No historical data found (Yahoo Finance returned empty data)'}
                    
                # Flatten MultiIndex columns if present
                if isinstance(df.columns, pd.MultiIndex):
                    if 'Close' in df.columns.get_level_values(0):
                        df.columns = df.columns.get_level_values(0)
                    else:
                        df.columns = df.columns.get_level_values(1)
                    
                df.sort_index(inplace=True)
            except Exception as e:
                logger.error(f"Backtest data download error: {e}")
                return {'error': f"Failed to download historical data: {str(e)}"}

        # Run simulation
        data_len = len(df)
        if data_len < 100:
            return {'error': f'Not enough candles for backtest (found {data_len}, need >= 100)'}

        trades = []
        active_trade = None
        atr_series = calculate_atr(df, 14)
        
        # Sliding window backtest (lookback of 50 candles for analysis)
        for i in range(50, data_len):
            current_time = df.index[i]
            current_close = float(df['Close'].iloc[i])
            current_high = float(df['High'].iloc[i])
            current_low = float(df['Low'].iloc[i])
            
            # 1. Manage active trade if one is running
            if active_trade:
                direction = active_trade['direction']
                sl = active_trade['sl']
                tp1 = active_trade['tp1']
                tp2 = active_trade['tp2']
                entry = active_trade['entry']
                
                # Check for exit (SL or TP2/TP1 hit)
                sl_hit = False
                tp_hit = False
                
                if direction == 'BUY':
                    if current_low <= sl:
                        sl_hit = True
                    elif current_high >= tp2:
                        tp_hit = True
                elif direction == 'SELL':
                    if current_high >= sl:
                        sl_hit = True
                    elif current_low <= tp2:
                        tp_hit = True
                        
                if sl_hit or tp_hit:
                    # Close trade
                    active_trade['closed_at'] = current_time.isoformat()
                    if sl_hit:
                        active_trade['status'] = 'sl_hit'
                        active_trade['close_price'] = sl
                        active_trade['result_pips'] = -abs(entry - sl) * 10.0
                    else:
                        active_trade['status'] = 'tp2_hit'
                        active_trade['close_price'] = tp2
                        active_trade['result_pips'] = abs(entry - tp2) * 10.0
                        
                    trades.append(active_trade)
                    active_trade = None
                continue
                
            # 2. Check for new setup trigger
            # Extract window
            window_df = df.iloc[i-50:i]
            analysis = self.analysis_engine.full_analysis(window_df)
            
            if 'error' in analysis:
                continue
                
            bias_score = analysis.get('bias_score', 0)
            atr_val = float(atr_series.iloc[i-1]) if not pd.isna(atr_series.iloc[i-1]) else 5.0
            if atr_val <= 0:
                atr_val = 5.0

            # Trigger criteria: High confidence bias score (>= 4 or <= -4)
            if bias_score >= 4:
                # BUY setup
                active_trade = {
                    'direction': 'BUY',
                    'entry': current_close,
                    'sl': round(current_close - (1.5 * atr_val), 2),
                    'tp1': round(current_close + (1.5 * atr_val), 2),
                    'tp2': round(current_close + (3.0 * atr_val), 2),
                    'timestamp': current_time.isoformat(),
                    'status': 'active',
                }
            elif bias_score <= -4:
                # SELL setup
                active_trade = {
                    'direction': 'SELL',
                    'entry': current_close,
                    'sl': round(current_close + (1.5 * atr_val), 2),
                    'tp1': round(current_close - (1.5 * atr_val), 2),
                    'tp2': round(current_close - (3.0 * atr_val), 2),
                    'timestamp': current_time.isoformat(),
                    'status': 'active',
                }

        # Calculate statistics
        total_trades = len(trades)
        if total_trades == 0:
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'total_pips': 0.0,
                'profit_factor': 0.0,
                'max_consecutive_wins': 0,
                'max_consecutive_losses': 0,
                'period': period,
                'timeframe': timeframe,
                'asset': asset,
            }

        wins = 0
        losses = 0
        total_pips = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        
        consecutive_wins = 0
        consecutive_losses = 0
        max_consecutive_wins = 0
        max_consecutive_losses = 0

        for t in trades:
            pips = t['result_pips']
            total_pips += pips
            
            if pips > 0:
                wins += 1
                gross_profit += pips
                consecutive_wins += 1
                consecutive_losses = 0
                if consecutive_wins > max_consecutive_wins:
                    max_consecutive_wins = consecutive_wins
            else:
                losses += 1
                gross_loss += abs(pips)
                consecutive_losses += 1
                consecutive_wins = 0
                if consecutive_losses > max_consecutive_losses:
                    max_consecutive_losses = consecutive_losses

        win_rate = (wins / total_trades) * 100
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

        return {
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 1),
            'total_pips': round(total_pips, 1),
            'profit_factor': round(profit_factor, 2),
            'max_consecutive_wins': max_consecutive_wins,
            'max_consecutive_losses': max_consecutive_losses,
            'period': period,
            'timeframe': timeframe,
            'asset': asset,
        }

    def format_backtest_report(self, res: Dict[str, Any]) -> str:
        """Format backtest results into a beautiful bilingual report."""
        if 'error' in res:
            import html
            safe_err = html.escape(str(res['error']))
            return f"❌ <b>خطأ في الباكتيست | Backtest Error:</b>\n<code>{safe_err}</code>"

        win_rate_emoji = "🏆" if res['win_rate'] >= 65 else "📊"
        pips_emoji = "📈" if res['total_pips'] >= 0 else "📉"

        msg = f"""
📊 <b>تقرير اختبار الاستراتيجية | Backtest Report</b>
{'═'*35}

🔍 <b>المعايير | Parameters:</b>
• <b>الأصل | Asset:</b> {res['asset']}
• <b>الفترة | Period:</b> {res['period']}
• <b>الفريم | Timeframe:</b> {res['timeframe']}

📈 <b>النتائج الكلية | General Results:</b>
• <b>إجمالي الصفقات | Total Trades:</b> {res['total_trades']}
• <b>الرابحة | Wins:</b> {res['wins']} ✅
• <b>الخاسرة | Losses:</b> {res['losses']} ❌
• <b>نسبة النجاح | Win Rate:</b> {res['win_rate']}% {win_rate_emoji}

💰 <b>صافي النقاط | Net Pips:</b> <code>{res['total_pips']:+.1f} Pips</code> {pips_emoji}
• <b>عامل الربح | Profit Factor:</b> <code>{res['profit_factor']}</code>

🔥 <b>الإحصائيات المتتالية | Streak Stats:</b>
• <b>أقصى ربح متتالي | Max Win Streak:</b> {res['max_consecutive_wins']} صفقات
• <b>أقصى خسارة متتالية | Max Loss Streak:</b> {res['max_consecutive_losses']} صفقات

{'─'*35}
⚠️ <i>تنبيه: الأداء التاريخي لا يضمن النتائج المستقبلية.\nDisclaimer: Past performance is not indicative of future results.</i>
"""
        return msg.strip()
