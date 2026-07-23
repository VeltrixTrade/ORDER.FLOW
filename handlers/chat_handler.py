import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

CHATTING = 0

class ChatHandler:
    """Handles the free conversation with DeepSeek Gold Expert"""
    
    def __init__(self):
        self.ai_client = DeepSeekClient()
        
    async def start_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Callback to start chatting"""
        from handlers.start_handler import check_and_reply_subscription
        if not await check_and_reply_subscription(update, context):
            return ConversationHandler.END
            
        # Check if it's weekend (Saturday or Sunday) in Riyadh/Mecca time
        import datetime
        import pytz
        mecca_tz = pytz.timezone("Asia/Riyadh")
        now_mecca = datetime.datetime.now(mecca_tz)
        if now_mecca.weekday() in (5, 6): # 5 = Saturday, 6 = Sunday
            query = update.callback_query
            if query:
                await query.answer()
                await query.edit_message_text(
                    "⚠️ <b>محادثة الخبير مغلقة حالياً | Chat Offline</b>\n\n"
                    "عذراً، محادثة الخبير معطلة خلال عطلة نهاية الأسبوع (السبت والأحد) نظراً لتوقف السوق عن العمل.\n"
                    "سيكون الخبير متاحاً فور افتتاح السوق فجر يوم الاثنين.\n\n"
                    "Sorry, the AI Expert Chat is offline during weekends (Saturday and Sunday) as the market is closed. "
                    "It will resume on Monday market open.",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text(
                    "⚠️ <b>محادثة الخبير مغلقة حالياً | Chat Offline</b>\n\n"
                    "عذراً، محادثة الخبير معطلة خلال عطلة نهاية الأسبوع (السبت والأحد) نظراً لتوقف السوق عن العمل.\n"
                    "سيكون الخبير متاحاً فور افتتاح السوق فجر يوم الاثنين.",
                    parse_mode='HTML'
                )
            return ConversationHandler.END
            
        query = update.callback_query
        await query.answer()
        
        # Initialize history if not exists
        if 'chat_history' not in context.user_data:
            context.user_data['chat_history'] = []
            
        keyboard = [[InlineKeyboardButton("🚪 إنهاء المحادثة | Exit Chat", callback_data="exit_chat")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "💬 لقد بدأت الآن محادثة حرة مع <b>خبير تداول الذهب بالذكاء الاصطناعي</b>.\n"
            "💬 You started a chat session with the <b>AI Gold Trading Expert</b>.\n\n"
            "اسألني أي سؤال عن استراتيجيات تدفق السيولة (Order Flow)، إدارة المخاطر، أو سلوك الذهب السعري.\n"
            "Ask me anything about Order Flow strategies, risk management, or gold price behavior.\n\n"
            "اكتب سؤالك مباشرة لإرساله، أو اضغط على الزر أدناه للخروج:\n"
            "Write your message directly, or click the button below to exit:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return CHATTING

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Forward user message to DeepSeek or ask for timeframe if requesting trade"""
        user_message = update.message.text
        
        # Check if user is asking for a trade setup / recommendation
        trade_keywords = ["صفقة", "توصية", "شراء", "بيع", "دخول", "سكالب", "سوكالب", "trade", "setup", "signal", "entry", "recommendation"]
        is_trade_req = any(kw in user_message.lower() for kw in trade_keywords)
        
        if is_trade_req:
            # Save user prompt
            context.user_data['pending_ai_request'] = user_message
            
            keyboard = [
                [
                    InlineKeyboardButton("📊 فريم 5 دقائق | M5", callback_data="ai_tf_M5"),
                    InlineKeyboardButton("⚡ فريم دقيقة واحدة | M1", callback_data="ai_tf_M1")
                ],
                [InlineKeyboardButton("🚪 إنهاء المحادثة | Exit Chat", callback_data="exit_chat")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "يرجى اختيار الفريم الزمني المطلوب للتوصية:\n"
                "Please select the desired timeframe for the trade recommendation:",
                reply_markup=reply_markup
            )
            return CHATTING
            
        # Send typing action
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Retrieve history
        history = context.user_data.get('chat_history', [])
        
        # Get response from AI
        ai_response = self.ai_client.chat(user_message, history)
        
        # Save to history
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": ai_response})
        context.user_data['chat_history'] = history
        
        keyboard = [[InlineKeyboardButton("🚪 إنهاء المحادثة | Exit Chat", callback_data="exit_chat")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Resilient Reply with HTML Parsing Fallback
        try:
            await update.message.reply_text(
                ai_response,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        except Exception as html_err:
            logger.warning(f"Telegram HTML parsing failed: {html_err}. Falling back to plain text.")
            plain_text = re.sub(r'<[^>]*>', '', ai_response)
            await update.message.reply_text(
                plain_text,
                reply_markup=reply_markup
            )
            
        return CHATTING

    async def handle_timeframe_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """User selected M1 or M5 timeframe - trigger AI analysis with tf context"""
        query = update.callback_query
        await query.answer()
        
        tf_choice = "M5" if query.data == "ai_tf_M5" else "M1"
        user_message = context.user_data.get('pending_ai_request', 'أعطني توصية')
        
        # Update message to show selection
        await query.edit_message_text(f"⏳ جاري تحليل فريم {tf_choice}... يرجى الانتظار.")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Retrieve history
        history = context.user_data.get('chat_history', [])
        
        # Get live data for selected timeframe
        from trade_db import TradeDB
        db = TradeDB()
        lp = db.get_live_price("XAUUSD")
        
        is_stale = False
        if lp:
            try:
                import datetime
                updated_dt = datetime.datetime.fromisoformat(lp["updated_at"])
                now = datetime.datetime.now()
                if (now - updated_dt).total_seconds() > 30:
                    is_stale = True
            except Exception:
                pass
        else:
            is_stale = True
            
        candles = db.get_candles("XAUUSD", tf_choice, limit=11)
        
        if is_stale or not candles:
            await query.edit_message_text(
                "❌ <b>خطأ: المنصة غير متصلة حالياً | Platform Offline</b>\n\n"
                "عذراً، الاتصال بين منصة MT5 والسيرفر منقطع حالياً، ولا توجد بيانات أسعار كافية للتحليل.\n"
                "يرجى التأكد من تشغيل الإكسبريت واتصاله بالسيرفر على جهازك وتغذية الأسعار، وحاول مجدداً بمجرد عودة الاتصال وتحديث الشارت!",
                parse_mode='HTML'
            )
            return CHATTING
            
        current_price = lp["bid"] if lp else 0.0
        
        # Fetch the exact EMA34 and EMA50 for the chosen timeframe
        from engine.rules import get_ema_values
        ema34_val, ema50_val = get_ema_values(db, tf_choice)
        
        # Fetch complete Order Flow metrics for the chosen timeframe
        from engine.parser import order_flow_tracker_m1, order_flow_tracker_m5
        tracker = order_flow_tracker_m5 if tf_choice == "M5" else order_flow_tracker_m1
        
        state = await tracker.get_state()
        
        # get_candles() returns chronological order (oldest to newest).
        # candles[-1] is the active/open candle (volume 0).
        # closed_candles[-1] is the last fully closed candle!
        closed_candles = candles[:-1] if len(candles) >= 2 else candles
        last_candle = closed_candles[-1] if closed_candles else {}
        last_vol = last_candle.get("volume", 0)
        last_delta = last_candle.get("delta", 0.0)
        
        # Calculate Volume SMA10 strictly from closed candles
        volume_sma_10 = 0.0
        if closed_candles:
            sample = closed_candles[-10:]
            volume_sma_10 = sum(c.get("volume", 0) for c in sample) / len(sample)
        
        # Injected prompt instructing AI on timeframe, Wave Zone and metrics
        tf_inst = (
            f"\n\n[USER TIMEFRAME CHOICE: The user wants a trade setup analyzed strictly on the {tf_choice} timeframe. "
            f"Current Spot Price: ${current_price:.2f}. "
            f"The actual EMA34/EMA50 Wave Zone for the {tf_choice} timeframe is currently: EMA34 = ${ema34_val:.2f}, EMA50 = ${ema50_val:.2f}. "
            f"\n=== {tf_choice} TREND & VOLUME INDICATORS ===\n"
            f"- Last Candle Volume: {last_vol} (Volume SMA10: {volume_sma_10:.2f})\n"
            f"- Last Candle Delta: {last_delta:.2f}\n"
            f"You MUST use these exact Wave Zone, Volume, and Delta values to evaluate the trade setup. "
            f"Identify the Entry, SL, and TP levels strictly based on {tf_choice}. "
            f"Your Stop Loss must be 2.0$ above/below the EMA Wave Zone. "
            f"Explain your checklist scoring (Volume confirmed, Delta confirmed) and give a final score (Score is 50% if only one confirmed, 100% if both confirmed. Min 50% score required to recommend, and include the 50% warning if score is exactly 50%).]"
        )
        
        # Get response from AI with injected prompt
        ai_response = self.ai_client.chat(user_message + tf_inst, history)
        
        # Save to history (clean user message without system instructions)
        history.append({"role": "user", "content": f"{user_message} (Timeframe: {tf_choice})"})
        history.append({"role": "assistant", "content": ai_response})
        context.user_data['chat_history'] = history
        
        keyboard = []
        
        # Check if AI response contains a trade setup
        from scanner import MarketScanner
        temp_scanner = MarketScanner(context.bot)
        parsed_setup = temp_scanner._parse_trade_from_text(ai_response)
        
        if parsed_setup:
            context.user_data['pending_ai_trade'] = parsed_setup
            keyboard.append([
                InlineKeyboardButton("🔍 مراقبة التوصية | Monitor Recommendation", callback_data="monitor_ai_trade")
            ])
            
        keyboard.append([
            InlineKeyboardButton("🚪 إنهاء المحادثة | Exit Chat", callback_data="exit_chat")
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Resilient Reply with HTML Parsing Fallback
        try:
            await query.message.reply_text(
                ai_response,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        except Exception as html_err:
            logger.warning(f"Telegram HTML parsing failed: {html_err}. Falling back to plain text.")
            plain_text = re.sub(r'<[^>]*>', '', ai_response)
            await query.message.reply_text(
                plain_text,
                reply_markup=reply_markup
            )
            
        # Clean pending request
        context.user_data['pending_ai_request'] = None
        return CHATTING

    async def monitor_ai_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """User clicked Monitor Recommendation - save and trace this trade setup"""
        query = update.callback_query
        await query.answer()
        
        parsed = context.user_data.get('pending_ai_trade')
        if not parsed:
            await query.message.reply_text("❌ لم يتم العثور على توصية معلقة لمراقبتها أو انتهت صلاحيتها.")
            return CHATTING
            
        from scanner import MarketScanner
        from datetime import datetime
        scanner = MarketScanner(context.bot)
        
        # Log in SQLite DB
        from trade_db import TradeDB
        db = TradeDB()
        db_id = None
        try:
            db_id = db.log_trade(
                direction=parsed['direction'],
                entry=parsed['entry'],
                sl=parsed['sl'],
                tp1=parsed['tp1'],
                tp2=parsed.get('tp2'),
                tp3=parsed.get('tp3'),
                trade_type="scalp",
                asset='XAUUSD'
            )
        except Exception as db_err:
            logger.error(f"Failed to log chatbot trade in SQLite: {db_err}")
            
        parsed['db_id'] = db_id
        parsed['source'] = 'ai'  # exempt from active rules limits
        parsed['timestamp'] = parsed.get('timestamp') or int(datetime.utcnow().timestamp() * 1000)
        
        # Check current spot price to decide if trade is active or pending
        current_price = None
        try:
            lp = db.get_live_price("XAUUSD")
            if lp:
                current_price = float(lp['bid'])
        except Exception:
            pass
            
        is_pending = False
        status_val = 'active'
        if current_price and abs(parsed['entry'] - current_price) > 1.50:
            is_pending = True
            status_val = 'pending'
            
        parsed['is_pending'] = is_pending
        parsed['status'] = status_val
        
        # Append to active trades
        active_trades = scanner.load_active_trades()
        active_trades.append(parsed)
        scanner.save_active_trades(active_trades)
        
        # Update original message keyboard to remove the button
        keyboard = [[InlineKeyboardButton("🚪 إنهاء المحادثة | Exit Chat", callback_data="exit_chat")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        
        # Send confirmation based on status
        if status_val == 'pending':
            confirm_msg = (
                f"⏳ <b>تم تسجيل الصفقة كأمر معلق (Pending)!</b>\n"
                f"سعر الدخول (${parsed['entry']:.2f}) بعيد عن السعر الحالي (${current_price:.2f}).\n"
                f"سيقوم السيرفر بمراقبة السعر وتفعيل الصفقة تلقائياً بمجرد ملامسة الدخول."
            )
        else:
            confirm_msg = (
                "✅ <b>تم البدء في مراقبة الصفقة الفورية بنجاح!</b>\n"
                "سيقوم السيرفر بمتابعة الأهداف والوقف لحظة بلحظة وتنبيهك تلقائياً."
            )
        await query.message.reply_text(confirm_msg, parse_mode="HTML")
        
        context.user_data['pending_ai_trade'] = None
        return CHATTING

    async def exit_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Exit conversation and show main menu"""
        query = update.callback_query
        if query:
            await query.answer()
            from handlers.start_handler import start_command
            await start_command(update, context)
        return ConversationHandler.END

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel via command /stop or /cancel"""
        from handlers.start_handler import start_command
        await start_command(update, context)
        return ConversationHandler.END

def get_chat_conversation_handler():
    handler = ChatHandler()
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(handler.start_chat, pattern="^chat_start$")],
        states={
            CHATTING: [
                CallbackQueryHandler(handler.monitor_ai_trade, pattern="^monitor_ai_trade$"),
                CallbackQueryHandler(handler.handle_timeframe_selected, pattern="^ai_tf_M[15]$"),
                CallbackQueryHandler(handler.exit_chat, pattern="^exit_chat$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handler.handle_message)
            ]
        },
        fallbacks=[
            CommandHandler("stop", handler.cancel_command),
            CommandHandler("cancel", handler.cancel_command),
            CallbackQueryHandler(handler.exit_chat, pattern="^menu$")
        ],
        per_message=False
    )
