"""
Automated bilingual (Arabic + English) report generator for the XAU/USD Trading Bot.
Provides HTML formats for daily, weekly, and monthly trading performance.
"""

import logging
from typing import Dict, Any
from stats_engine import StatsEngine

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates styled bilingual reports for Telegram channels and admin chat."""

    def __init__(self, stats_engine: StatsEngine) -> None:
        """Initialize with a StatsEngine instance."""
        self.stats = stats_engine

    def _format_report(self, title_ar: str, title_en: str, stats: Dict[str, Any]) -> str:
        """Helper to build a unified report format."""
        total = stats['total_trades']
        wins = stats['wins']
        losses = stats['losses']
        win_rate = stats['win_rate']
        total_pips = stats['total_pips']
        best = stats['best_trade_pips']
        worst = stats['worst_trade_pips']

        pips_emoji = "📈" if total_pips >= 0 else "📉"
        win_rate_emoji = "🏆" if win_rate >= 60 else "📊"

        # Current streak
        streak_info = self.stats.get_streak()
        streak_type = streak_info['type']
        streak_count = streak_info['count']
        
        if streak_type == 'win':
            streak_str_ar = f"🔥 سلسلة انتصارات متتالية: {streak_count} صفقات"
            streak_str_en = f"🔥 Current Win Streak: {streak_count} trades"
        elif streak_type == 'loss':
            streak_str_ar = f"⚠️ سلسلة خسائر متتالية: {streak_count} صفقات"
            streak_str_en = f"⚠️ Current Loss Streak: {streak_count} trades"
        else:
            streak_str_ar = "⏸️ لا توجد سلسلة نشطة"
            streak_str_en = "⏸️ No active streak"

        msg = f"""
{pips_emoji} <b>{title_ar} | {title_en}</b>
{'═'*35}

📊 <b>ملخص الأداء | Performance Summary:</b>
• <b>إجمالي الصفقات | Total Trades:</b> {total}
• <b>الصفقات الناجحة | Wins:</b> {wins} ✅
• <b>الصفقات الخاسرة | Losses:</b> {losses} ❌
• <b>نسبة النجاح | Win Rate:</b> {win_rate}% {win_rate_emoji}

💰 <b>صافي النقاط | Net Pips:</b> <code>{total_pips:+.1f} Pips</code> {pips_emoji}
• <b>أفضل صفقة | Best Trade:</b> <code>{best:+.1f} Pips</code>
• <b>أسوأ صفقة | Worst Trade:</b> <code>{worst:+.1f} Pips</code>

🔥 <b>سلسلة الصفقات | Streaks & Invalidation:</b>
• {streak_str_ar}
• {streak_str_en}

{'─'*35}
🏆 <i>بوت التحليل التلقائي للذهب | Signals DynaMit Bot</i>
"""
        return msg.strip()

    def generate_daily_report(self) -> str:
        """Generate today's trading report."""
        return self._format_report(
            "التقرير اليومي للأداء",
            "Daily Performance Report",
            self.stats.get_daily_stats()
        )

    def generate_weekly_report(self) -> str:
        """Generate this week's performance report."""
        return self._format_report(
            "التقرير الأسبوعي للأداء",
            "Weekly Performance Report",
            self.stats.get_weekly_stats()
        )

    def generate_monthly_report(self) -> str:
        """Generate this month's performance report."""
        return self._format_report(
            "التقرير الشهري للأداء",
            "Monthly Performance Report",
            self.stats.get_monthly_stats()
        )
