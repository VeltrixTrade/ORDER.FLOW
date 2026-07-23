import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from engine.parser import order_flow_tracker, cents_to_price, price_to_cents

logger = logging.getLogger(__name__)

def get_market_text_summary(state: dict) -> str:
    """Formats the market metrics summary message."""
    from trade_db import TradeDB
    db = TradeDB()
    lp = db.get_live_price("XAUUSD")
    price_str = f"${lp['bid']:.2f}" if lp else "N/A"

    poc = state.get("poc")
    vah = state.get("vah")
    val = state.get("val")
    vwap = state.get("vwap", 0.0)
    cvd = state.get("cvd", 0)

    trend = "Neutral"
    if cvd > 500:
        trend = "Bullish (Buying Pressure)"
    elif cvd < -500:
        trend = "Bearish (Selling Pressure)"

    return (
        f"📊 <b>XAU/USD Order Flow Summary</b>\n"
        f"{'═'*30}\n"
        f"💵 <b>Current Spot Price</b>: {price_str}\n"
        f"🔹 <b>Daily VWAP</b>: ${vwap:.2f}\n"
        f"🔹 <b>Point of Control (POC)</b>: ${poc if poc else 0.0:.2f}\n"
        f"🔹 <b>Value Area High (VAH)</b>: ${vah:.2f}\n"
        f"🔹 <b>Value Area Low (VAL)</b>: ${val:.2f}\n"
        f"🔹 <b>Running CVD</b>: {cvd:+d} ({trend})\n"
        f"{'═'*30}\n"
        f"Last updated: Just now (UTC)"
    )

async def market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays live order flow metrics and interactive buttons."""
    query = update.callback_query
    
    if query:
        await query.answer()
    
    try:
        state = await order_flow_tracker.get_state()
        formatted_summary = get_market_text_summary(state)
        
        # Build keyboard with Profile and Main Menu options
        keyboard = [
            [
                InlineKeyboardButton("📊 View Volume Profile", callback_data="view_profile"),
                InlineKeyboardButton("🔄 Refresh", callback_data="market")
            ],
            [
                InlineKeyboardButton("🔙 Main Menu", callback_data="menu")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(
                formatted_summary,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                formatted_summary,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error in market callback: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]]
        err_msg = f"❌ Error loading data: {str(e)}"
        if query:
            await query.edit_message_text(err_msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(err_msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def view_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates and prints a premium text-based Volume Profile histogram."""
    query = update.callback_query
    await query.answer()
    
    try:
        state = await order_flow_tracker.get_state()
        profile = order_flow_tracker.volume_profile.profile

        if not profile:
            from trade_db import TradeDB
            from engine.profile import VolumeProfile
            db = TradeDB()
            candles = db.get_candles("XAUUSD", order_flow_tracker.timeframe, limit=300)
            if candles:
                temp_profile = VolumeProfile()
                for c in candles:
                    close_p = float(c["close"])
                    vol = float(c.get("volume") or 0.0)
                    if vol > 0:
                        temp_profile.add_trade(close_p, vol)
                profile = temp_profile.profile

        if not profile:
            await query.message.reply_text("Volume profile is currently empty.")
            return

        sorted_prices = sorted(profile.keys(), reverse=True)
        
        # Filter bins to 15 around POC to avoid Telegram size limits
        poc = state.get("poc")
        poc_cents = price_to_cents(poc) if poc else 0
        filtered_prices = [p for p in sorted_prices if abs(p - poc_cents) <= 7 * 5]
        
        if not filtered_prices:
            filtered_prices = sorted_prices[:15]

        max_vol = max(profile.values())
        histogram = "📊 <b>Volume Profile (15 ticks around POC)</b>\n<code>"

        for p_cents in filtered_prices:
            vol = profile[p_cents]
            price = cents_to_price(p_cents)
            
            bar_len = int((vol / max_vol) * 12) if max_vol > 0 else 0
            bar = "█" * bar_len
            
            tag = ""
            if p_cents == poc_cents:
                tag = " ← POC"
            elif price == state.get("vah"):
                tag = " ← VAH"
            elif price == state.get("val"):
                tag = " ← VAL"
                
            histogram += f"{price:7.2f} | {vol:4d} | {bar:<12}{tag}\n"

        histogram += "</code>"
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Market", callback_data="market")]]
        await query.message.reply_text(
            text=histogram,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in view_profile callback: {e}", exc_info=True)
        await query.message.reply_text(f"❌ Error rendering profile: {str(e)}")
