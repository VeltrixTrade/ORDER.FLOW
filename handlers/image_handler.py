import logging
import base64
import os
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from market_data import MarketData
from gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# Conversation States
WAITING_TRADE_TYPE = 0

class ImageAnalysisHandler:
    """Handles chart image upload and analysis using Google Gemini"""
    
    def __init__(self):
        self.market_data = MarketData()
        self.gemini_client = GeminiClient()

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Called when a user sends a photo to the bot"""
        from handlers.start_handler import check_and_reply_subscription
        if not await check_and_reply_subscription(update, context):
            return ConversationHandler.END
        # Save the largest size photo file ID
        photo_file_id = update.message.photo[-1].file_id
        context.user_data['chart_photo_id'] = photo_file_id
        
        # Build trade type selection keyboard
        keyboard = [
            [
                InlineKeyboardButton("⚡ تحليل سكالب | Scalp", callback_data="img_type_scalp"),
                InlineKeyboardButton("📊 طويلة المدى | Swing", callback_data="img_type_swing")
            ],
            [
                InlineKeyboardButton("🔙 إلغاء | Cancel", callback_data="img_cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🖼️ <b>تم استلام صورة الشارت بنجاح!</b>\n"
            "يرجى تحديد نوع الصفقة التي تريد تحليلها من الشارت:\n\n"
            "🖼️ <b>Chart image received successfully!</b>\n"
            "Please select the trade type for analysis:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return WAITING_TRADE_TYPE

    async def process_image_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Download photo, convert to base64, call Gemini API, and display results"""
        query = update.callback_query
        await query.answer()
        
        choice = query.data
        if choice == "img_cancel":
            context.user_data.pop('chart_photo_id', None)
            await query.edit_message_text("❌ تم إلغاء تحليل الصورة.\n❌ Image analysis cancelled.")
            return ConversationHandler.END
            
        trade_type = 'scalp' if choice == "img_type_scalp" else 'swing'
        trade_type_ar = "سكالب ⚡" if trade_type == 'scalp' else "سوينغ 📊"
        
        photo_id = context.user_data.get('chart_photo_id')
        if not photo_id:
            await query.edit_message_text("❌ لم يتم العثور على الصورة. يرجى إرسال الصورة مرة أخرى.")
            return ConversationHandler.END
            
        await query.edit_message_text(
            f"⏳ <b>جاري تحميل صورة الشارت وتحضيرها...</b>\n"
            f"⏳ <b>Downloading and preparing chart image...</b>",
            parse_mode='HTML'
        )
        
        try:
            # Download file from Telegram
            photo_file = await context.bot.get_file(photo_id)
            photo_bytes = io.BytesIO()
            await photo_file.download_to_memory(photo_bytes)
            
            # Convert bytes to base64
            photo_bytes.seek(0)
            img_b64 = base64.b64encode(photo_bytes.read()).decode('utf-8')
            
            # Send status update
            await query.edit_message_text(
                f" Live Spot Price: Fetching live prices...\n"
                f"🔬 <b>جاري تحليل الشارت باستخدام Gemini 2.5 Flash...</b>",
                parse_mode='HTML'
            )
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            
            # Fetch live market summary for context
            market_summary = self.market_data.get_market_summary()
            
            # Run image analysis via Gemini
            ai_analysis = self.gemini_client.analyze_chart_images([img_b64], trade_type, market_summary)
            
            # Display results
            keyboard = [[InlineKeyboardButton("🔙 القائمة الرئيسية | Main Menu", callback_data="menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            header = (
                f"🔮 <b>تحليل الشارت بالذكاء الاصطناعي | Gemini Chart Analysis</b>\n"
                f"📌 <b>نوع الصفقة:</b> {trade_type_ar}\n"
                f"{'═'*35}\n\n"
            )
            full_msg = header + ai_analysis
            
            # Send the analysis
            if len(full_msg) > 4000:
                parts = [full_msg[i:i+4000] for i in range(0, len(full_msg), 4000)]
                for part in parts[:-1]:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=part, parse_mode='HTML')
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text=parts[-1],
                    reply_markup=reply_markup, parse_mode='HTML'
                )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text=full_msg,
                    reply_markup=reply_markup, parse_mode='HTML'
                )
                
            # Register Gemini visual trade setup in the Autopilot Monitor
            try:
                from scanner import MarketScanner
                temp_scanner = MarketScanner(context.bot)
                parsed_trade = temp_scanner.parse_full_setup(ai_analysis, trade_type)
                if parsed_trade:
                    # Log trade in SQLite DB
                    try:
                        db_id = temp_scanner.db.log_trade(
                            direction=parsed_trade['direction'],
                            entry=parsed_trade['entry'],
                            sl=parsed_trade['sl'],
                            tp1=parsed_trade['tp1'],
                            tp2=parsed_trade.get('tp2'),
                            tp3=parsed_trade.get('tp3'),
                            trade_type=trade_type,
                            asset='XAUUSD'
                        )
                        parsed_trade['db_id'] = db_id
                    except Exception as db_err:
                        logger.error(f"Failed to log Gemini visual trade in SQLite: {db_err}")

                    active_trades = temp_scanner.load_active_trades()
                    active_trades.append(parsed_trade)
                    temp_scanner.save_active_trades(active_trades)
                    logger.info(f"Registered Gemini visual trade in active monitor: {parsed_trade['direction']} @ {parsed_trade['entry']}")
            except Exception as reg_err:
                logger.error(f"Failed to register Gemini visual trade in active monitor: {reg_err}")


            # Broadcast to channel if configured

            from config import TELEGRAM_CHANNEL_ID
            if TELEGRAM_CHANNEL_ID:
                try:
                    channel_msg = (
                        f"🔮 <b>بث تحليل شارت | Chart Image Broadcast</b>\n"
                        f"📌 <b>النوع | Type:</b> {trade_type_ar}\n"
                        f"{'═'*35}\n\n"
                        f"{ai_analysis}\n\n"
                        f"🤖 <i>تحليل بصري بواسطة Gemini API.</i>"
                    )
                    # Send photo + analysis text to channel
                    photo_bytes.seek(0)
                    if len(channel_msg) > 1024:
                        # Send photo first then text
                        await context.bot.send_photo(
                            chat_id=TELEGRAM_CHANNEL_ID,
                            photo=photo_bytes,
                            caption="📊 شارت الذهب المرفق للتحليل الفني | Attached XAU/USD Chart"
                        )
                        # Send analysis text split if needed
                        if len(channel_msg) > 4000:
                            c_parts = [channel_msg[i:i+4000] for i in range(0, len(channel_msg), 4000)]
                            for cp in c_parts:
                                await context.bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=cp, parse_mode='HTML')
                        else:
                            await context.bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=channel_msg, parse_mode='HTML')
                    else:
                        await context.bot.send_photo(
                            chat_id=TELEGRAM_CHANNEL_ID,
                            photo=photo_bytes,
                            caption=channel_msg,
                            parse_mode='HTML'
                        )
                except Exception as channel_err:
                    logger.error(f"Failed to post image analysis to channel: {channel_err}")
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"⚠️ <b>تنبيه البث:</b> تعذر إرسال الشارت والتحليل لقناتك.\nError: {channel_err}"
                    )
                    
        except Exception as e:
            logger.error(f"Error during image analysis flow: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ حدث خطأ غير متوقع أثناء معالجة الصورة:\n{str(e)}"
            )
            
        finally:
            context.user_data.pop('chart_photo_id', None)
            
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel image analysis conversation"""
        query = update.callback_query
        if query:
            await query.answer()
        context.user_data.pop('chart_photo_id', None)
        return ConversationHandler.END

def get_image_conversation_handler():
    handler = ImageAnalysisHandler()
    return ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, handler.handle_photo)],
        states={
            WAITING_TRADE_TYPE: [
                CallbackQueryHandler(handler.process_image_analysis, pattern="^img_type_"),
                CallbackQueryHandler(handler.process_image_analysis, pattern="^img_cancel$")
            ]
        },
        fallbacks=[CommandHandler("cancel", handler.cancel)]
    )
