import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler
)
from market_data import MarketData
from deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

class AnalysisHandler:
    """Handles manual comprehensive market analysis requests strictly using live Order Flow data."""

    def __init__(self):
        self.market_data = MarketData()
        self.ai_client = DeepSeekClient()

    async def start_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        from handlers.start_handler import check_and_reply_subscription
        if not await check_and_reply_subscription(update, context):
            return ConversationHandler.END
            
        query = update.callback_query
        user_id = update.effective_user.id if update.effective_user else 'Unknown'
        logger.info(f"🔮 START COMPREHENSIVE ANALYSIS RECEIVED: User {user_id}")
        
        B = "<b>"
        BE = "</b>"
        
        # 1. Edit or send loading message
        loading_text = (
            f"⏳ {B}Fetching market data & generating Comprehensive Order Flow Analysis...{BE}\n"
            f"⏳ {B}جاري جلب بيانات السوق وتحضير التحليل الشامل لتدفق السيولة...{BE}"
        )
        if query:
            await query.answer()
            await query.edit_message_text(loading_text, parse_mode="HTML")
        else:
            sent_msg = await update.message.reply_text(loading_text, parse_mode="HTML")
            
        try:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            
            market_summary = self.market_data.get_market_summary()
            current_price = market_summary.get("price", {}).get("price", "N/A")
            
            # 2. Fetch live technical state from tracker and DB
            from engine.parser import order_flow_tracker
            state = await order_flow_tracker.get_state()
            
            from trade_db import TradeDB
            db = TradeDB()
            # Fetch last M5 candle
            candles = db.get_candles("XAUUSD", "M5", limit=1)
            last_candle = candles[0] if candles else {}
            
            # Fetch EMAs
            from engine.rules import get_ema_values
            ema34_val, ema50_val = get_ema_values(db, "M5")
            
            # Calculate Volume SMA10
            volume_sma_10 = 0.0
            try:
                candles_10 = db.get_candles("XAUUSD", "M5", limit=10)
                if candles_10:
                    volume_sma_10 = sum(c["volume"] for c in candles_10) / len(candles_10)
            except Exception:
                pass
                
            order_flow_state = {
                "ema34": ema34_val,
                "ema50": ema50_val,
                "volume": last_candle.get("volume", 0),
                "volume_sma_10": volume_sma_10,
                "delta": last_candle.get("delta", 0.0),
                "timeframe": "M5"
            }
            
            # 3. Call AI Client to generate comprehensive multi-timeframe analysis
            ai_analysis = self.ai_client.analyze_market_comprehensive(market_summary, order_flow_state)
            # Check if weekend (Saturday or Sunday) in Riyadh/Mecca time
            import datetime as dt
            import pytz
            mecca_tz = pytz.timezone("Asia/Riyadh")
            now_mecca = dt.datetime.now(mecca_tz)
            is_weekend = now_mecca.weekday() in (5, 6) # 5 = Saturday, 6 = Sunday

            if is_weekend:
                 session_card = (
                     f"⏰ {B}حالة السوق | Market Status{BE}\n"
                     f"🔴 <b>مغلق | CLOSED</b> (عطلة نهاية الأسبوع - السبت والأحد)\n"
                     f"📌 نترقب ونرصد كل الحركات الفنية والأحداث مع بداية افتتاح السوق فجر الاثنين.\n"
                     f"We are monitoring market metrics and awaiting new technical developments upon market open on Monday."
                 )
                 kz_warning = ""
            else:
                 session_info = market_summary.get("session", {})
                 is_kz = session_info.get("is_kill_zone", False)
                 kz_warning = ""
                 if not is_kz:
                      kz_warning = (
                          "\n\n⚠️ " + B + "Warning: Outside Session Hours!" + BE + "\n"
                          "⚠️ " + B + "تنبيه: خارج أوقات النشاط المفضلة!" + BE
                      )
                      
                 kz_emoji = "🟢" if is_kz else "🔴"
                 overlap_badge = " 🔥 OVERLAP" if session_info.get("is_overlap") else ""
                 
                 session_card = (
                      f"⏰ {B}الجلسة | Session{BE}\n"
                      f"{kz_emoji} {session_info.get('session', 'N/A')}{overlap_badge}\n"
                      f"🕒 {session_info.get('utc_time', '')}\n"
                      f"📌 {session_info.get('recommendation', '')}"
                 )
            
            keyboard = [[InlineKeyboardButton("🔙 القائمة الرئيسية | Menu", callback_data="menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            analysis_header = f"📊 {B}التحليل الشامل لتدفق السيولة | NERO FLOW Comprehensive Analysis{BE}\n{'═'*35}\n\n"
            
            full_response_text = session_card + kz_warning + "\n\n" + analysis_header + ai_analysis
            
            # Send the final analysis with HTML parsing fallback
            try:
                if query:
                    await query.edit_message_text(
                         text=full_response_text,
                         reply_markup=reply_markup,
                         parse_mode="HTML"
                    )
                else:
                    await sent_msg.edit_text(
                         text=full_response_text,
                         reply_markup=reply_markup,
                         parse_mode="HTML"
                    )
            except Exception as html_err:
                import re
                logger.warning(f"Telegram analysis HTML parsing failed: {html_err}. Falling back to plain text.")
                plain_text = re.sub(r'<[^>]*>', '', full_response_text)
                if query:
                    await query.edit_message_text(
                         text=plain_text,
                         reply_markup=reply_markup
                    )
                else:
                    await sent_msg.edit_text(
                         text=plain_text,
                         reply_markup=reply_markup
                    )
             
        except Exception as e:
            logger.error(f"Error during comprehensive analysis: {e}", exc_info=True)
            keyboard = [[InlineKeyboardButton("🔙 القائمة الرئيسية | Menu", callback_data="menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            err_text = f"❌ Error: {str(e)}"
            if query:
                await query.edit_message_text(err_text, reply_markup=reply_markup)
            else:
                await sent_msg.edit_text(err_text, reply_markup=reply_markup)
             
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        if query:
            await query.answer()
            from handlers.start_handler import start_command
            await start_command(update, context)
        return ConversationHandler.END


def get_analysis_conversation_handler():
    handler = AnalysisHandler()
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handler.start_analysis, pattern="^analyze_start$"),
            CommandHandler("analysis", handler.start_analysis)
        ],
        states={},
        fallbacks=[CallbackQueryHandler(handler.cancel, pattern="^menu$")],
        per_message=False
    )
