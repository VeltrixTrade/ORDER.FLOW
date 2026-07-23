# -*- coding: utf-8 -*-
from typing import Dict, Optional

def format_price(price) -> str:
    """Format price with $ sign and 2 decimal places"""
    if price is None or isinstance(price, str):
        return str(price)
    try:
        return f"${float(price):,.2f}"
    except Exception:
        return str(price)

def calculate_smart_lots(entry: float, stop_loss: float, account_size: float, risk_pct: float = 1.0) -> float:
    """
    Calculate the recommended Lot Size for XAU/USD (Gold).
    Contract size for gold is 100 ounces (1 Lot = $100 change per $1 move).
    """
    try:
        sl_distance = abs(entry - stop_loss)
        if sl_distance <= 0:
            return 0.01
        
        # Risk amount in dollars
        risk_amount = account_size * (risk_pct / 100.0)
        
        # Gold lot calculator formula: Risk / (SL distance * 100)
        lots = risk_amount / (sl_distance * 100.0)
        
        # Enforce MetaTrader min/max lot constraints and round down
        lots = max(0.01, round(lots, 2))
        return lots
    except Exception:
        return 0.01

def format_trade_setup(setup: Dict) -> str:
    """Format a trade setup into a Telegram HTML message with smart lot sizing"""
    direction_emoji = "🟢" if setup.get('direction') == 'BUY' else "🔴"
    direction_ar    = "شراء" if setup.get('direction') == 'BUY' else "بيع"
    
    entry = float(setup.get('entry', 0))
    sl = float(setup.get('stop_loss', 0))
    
    # Calculate recommended lots for popular account sizes (using 1% risk per trade)
    lots_1k = calculate_smart_lots(entry, sl, 1000.0, 1.0)
    lots_5k = calculate_smart_lots(entry, sl, 5000.0, 1.0)
    lots_10k = calculate_smart_lots(entry, sl, 10000.0, 1.0)

    msg = f"""
{'='*35}
{direction_emoji} <b>إشارة تداول | Trade Signal</b> {direction_emoji}
{'='*35}

📊 <b>الزوج | Pair:</b> XAU/USD (الذهب | Gold)
📍 <b>الاتجاه | Direction:</b> {setup.get('direction', 'N/A')} | {direction_ar}
⏰ <b>نوع الصفقة | Trade Type:</b> {setup.get('trade_type', 'N/A')}
📈 <b>الفريم | Timeframe:</b> {setup.get('timeframe', 'N/A')}

{'─'*35}
💰 <b>تفاصيل الصفقة | Trade Details</b>
{'─'*35}

🎯 <b>نقطة الدخول | Entry:</b> {format_price(entry)}
🛑 <b>وقف الخسارة | Stop Loss:</b> {format_price(sl)}
✅ <b>الهدف الأول | TP1:</b> {format_price(setup.get('tp1', 0))}
✅ <b>الهدف الثاني | TP2:</b> {format_price(setup.get('tp2', 0))}
✅ <b>الهدف الثالث | TP3:</b> {format_price(setup.get('tp3', 0))}

{'─'*35}
📊 <b>إدارة المخاطر وحجم اللوت (المخاطرة 1%)</b>
{'─'*35}

⚖️ <b>نسبة المخاطرة:المكافأة | RR:</b> 1:{setup.get('rr_ratio', 'N/A')}
📊 <b>مستوى الثقة | Confidence:</b> {setup.get('confidence', 'N/A')}%

⚖️ <b>حجم اللوت الموصى به | Recommended Lot Size:</b>
  • حساب <b>$1,000</b> ← <code>{lots_1k:.2f} Lot</code> (المخاطرة $10)
  • حساب <b>$5,000</b> ← <code>{lots_5k:.2f} Lot</code> (المخاطرة $50)
  • حساب <b>$10,000</b> ← <code>{lots_10k:.2f} Lot</code> (المخاطرة $100)

{'─'*35}
📝 <b>السبب | Reasoning:</b>
{setup.get('reasoning', 'N/A')}

⚠️ <i>تنويه: هذا التحليل للأغراض التعليمية فقط وليس نصيحة مالية.
Disclaimer: This analysis is for educational purposes only, not financial advice.</i>
"""
    return msg.strip()


def format_market_summary(data: Dict) -> str:
    """Format market summary into a Telegram HTML message"""
    price_info = data.get('price', {})

    msg = f"""🥇 <b>ملخص سوق الذهب | Gold Market Summary</b>
{'═'*35}

💰 <b>السعر الحالي | Current Price:</b> {format_price(price_info.get('price', 0))}
📈 <b>أعلى سعر اليوم | Daily High:</b> {format_price(price_info.get('high', 0))}
📉 <b>أقل سعر اليوم | Daily Low:</b> {format_price(price_info.get('low', 0))}
📊 <b>الافتتاح | Open:</b> {format_price(price_info.get('open', 0))}
🔄 <b>التغيير اليومي | Change:</b> {price_info.get('change', 'N/A')}%
🔗 <b>المصدر | Source:</b> {price_info.get('source', 'N/A')}"""
    return msg.strip()


def format_analysis_result(analysis: str, trade_type: str) -> str:
    """Wrap AI analysis result with a header"""
    type_emoji   = "⚡" if trade_type == 'scalp' else "📊"
    type_name_ar = "سكالب ⚡" if trade_type == 'scalp' else "سوينغ 📊"
    type_name_en = "Scalp" if trade_type == 'scalp' else "Swing"

    msg = f"""{type_emoji} <b>تحليل {type_name_ar} | {type_name_en} Analysis</b>
{'='*35}

{analysis}

{'='*35}
⚠️ <i>تنويه: هذا التحليل للأغراض التعليمية فقط وليس نصيحة استثمارية.
Disclaimer: For educational purposes only.</i>"""
    return msg.strip()


