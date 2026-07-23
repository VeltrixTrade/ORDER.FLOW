"""
Performance Statistics Engine for XAU/USD Trading Bot.
Calculates daily, weekly, monthly, and lifetime stats, win streaks, and drawdown.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from trade_db import TradeDB

logger = logging.getLogger(__name__)


class StatsEngine:
    """Calculates trading performance statistics using SQLite database data."""

    def __init__(self, db: TradeDB) -> None:
        """Initialize with a TradeDB instance."""
        self.db = db

    def _calculate_stats(self, trades: list) -> Dict[str, Any]:
        """Helper to calculate statistics on a list of trade dicts."""
        total_trades = len(trades)
        if total_trades == 0:
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'total_pips': 0.0,
                'best_trade_pips': 0.0,
                'worst_trade_pips': 0.0,
            }

        wins = 0
        losses = 0
        total_pips = 0.0
        best_pips = -999999.0
        worst_pips = 999999.0

        for t in trades:
            pips = t.get('result_pips') or 0.0
            total_pips += pips
            
            # Count win vs loss (wins are > 0 pips, losses are <= 0 pips)
            # Or based on status if result_pips is null
            status = t.get('status')
            if pips > 0 or status in ('tp1_hit', 'tp2_hit', 'tp3_hit'):
                wins += 1
            elif pips < 0 or status == 'sl_hit':
                losses += 1

            if pips > best_pips:
                best_pips = pips
            if pips < worst_pips:
                worst_pips = pips

        # If no trades have pips recorded, normalize best/worst
        if best_pips == -999999.0:
            best_pips = 0.0
        if worst_pips == 999999.0:
            worst_pips = 0.0

        win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0.0

        return {
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 1),
            'total_pips': round(total_pips, 1),
            'best_trade_pips': round(best_pips, 1),
            'worst_trade_pips': round(worst_pips, 1),
        }

    def get_daily_stats(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """Get trading stats for a given day (defaults to today in UTC)."""
        if not date_str:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
        trades = self.db.get_trades_by_date(date_str)
        return self._calculate_stats(trades)

    def get_weekly_stats(self) -> Dict[str, Any]:
        """Get trading stats for the current calendar week (Monday to Sunday)."""
        today = datetime.utcnow().date()
        start_of_week = today - timedelta(days=today.weekday())  # Monday
        end_of_week = start_of_week + timedelta(days=6)          # Sunday
        
        trades = self.db.get_trades_in_range(start_of_week.isoformat(), end_of_week.isoformat())
        return self._calculate_stats(trades)

    def get_monthly_stats(self) -> Dict[str, Any]:
        """Get trading stats for the current calendar month."""
        today = datetime.utcnow().date()
        start_of_month = today.replace(day=1)
        # Next month minus 1 day
        if today.month == 12:
            end_of_month = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end_of_month = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
            
        trades = self.db.get_trades_in_range(start_of_month.isoformat(), end_of_month.isoformat())
        return self._calculate_stats(trades)

    def get_all_time_stats(self) -> Dict[str, Any]:
        """Get lifetime trading stats (all closed/completed trades)."""
        trades = self.db.get_all_closed_trades()
        return self._calculate_stats(trades)

    def get_streak(self) -> Dict[str, Any]:
        """Calculate the current win or loss streak."""
        trades = self.db.get_all_closed_trades()
        if not trades:
            return {'type': 'none', 'count': 0}

        # Sort trades by closed_at or timestamp (oldest first to find current ending streak)
        # SQLite queries return DESC, so first item is the most recent closed trade.
        current_streak_type = None
        count = 0

        for t in trades:
            pips = t.get('result_pips') or 0.0
            status = t.get('status')
            
            is_win = pips > 0 or status in ('tp1_hit', 'tp2_hit', 'tp3_hit')
            is_loss = pips < 0 or status == 'sl_hit'
            
            if not is_win and not is_loss:
                continue  # skip trades with no clear outcome

            trade_type = 'win' if is_win else 'loss'
            
            if current_streak_type is None:
                current_streak_type = trade_type
                count = 1
            elif current_streak_type == trade_type:
                count += 1
            else:
                break  # streak broken

        return {
            'type': current_streak_type or 'none',
            'count': count,
        }

    def get_max_drawdown(self) -> float:
        """Calculate maximum drawdown in pips based on equity curve high-to-low path."""
        trades = self.db.get_all_closed_trades()
        if not trades:
            return 0.0

        # Sort chronologically (oldest first)
        trades = sorted(trades, key=lambda x: x.get('timestamp') or '')
        
        cumulative_pips = 0.0
        peak = 0.0
        max_drawdown = 0.0

        for t in trades:
            pips = t.get('result_pips') or 0.0
            cumulative_pips += pips
            
            if cumulative_pips > peak:
                peak = cumulative_pips
                
            drawdown = peak - cumulative_pips
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        return round(max_drawdown, 1)
