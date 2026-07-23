"""
Bilingual (Arabic + English) Lot Size Calculator for XAU/USD Trading Bot.
Uses python-telegram-bot v21 conversation states.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)

# Conversation states
WAITING_BALANCE, WAITING_RISK, WAITING_SL_PIPS = range(3)


async def start_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the lot size calculator."""
    # Check if triggered by callback query or text command
    query = update.callback_query
    if query:
        await query.answer()
        chat_id = query.message.chat_id
    else:
        chat_id = update.effective_chat.id

    keyboard = [[InlineKeyboardButton("🔙 إلغاء | Cancel", callback_data="menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = (
        "🧮 <b>حاسبة حجم اللوت | Lot Size Calculator</b>\n"
        f"{'─'*35}\n\n"
        "رجاءً اكتب <b>رصيد الحساب</b> بالدولار الأمريكي (مثال: 1000):\n"
        "Please enter your <b>account balance</b> in USD (e.g. 1000):"
    )

    if query:
        await query.message.edit_text(msg, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=reply_markup, parse_mode='HTML')

    return WAITING_BALANCE


async def process_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save balance and ask for risk percentage."""
    try:
        balance = float(update.message.text.replace(',', ''))
        if balance <= 0:
            raise ValueError()
        context.user_data['calc_balance'] = balance
    except ValueError:
        await update.message.reply_text(
            "❌ قيمة غير صالحة. يرجى إدخال رقم صحيح لرصيد الحساب:\n"
            "❌ Invalid value. Please enter a valid number for balance:"
        )
        return WAITING_BALANCE

    keyboard = [[InlineKeyboardButton("🔙 إلغاء | Cancel", callback_data="menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = (
        "🧮 <b>حاسبة حجم اللوت | Lot Size Calculator</b>\n"
        f"{'─'*35}\n\n"
        "أدخل <b>نسبة المخاطرة</b> المطلوبة (مثال: 1 لنسبة 1% أو 2 لنسبة 2%):\n"
        "Enter your desired <b>risk percentage</b> (e.g. 1 for 1% or 2 for 2%):"
    )
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='HTML')
    return WAITING_RISK


async def process_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save risk percentage and ask for SL in pips."""
    try:
        risk_pct = float(update.message.text.replace('%', ''))
        if risk_pct <= 0 or risk_pct > 100:
            raise ValueError()
        context.user_data['calc_risk'] = risk_pct
    except ValueError:
        await update.message.reply_text(
            "❌ نسبة غير صالحة. يرجى إدخال رقم صحيح للمخاطرة (بين 0.1 و 100):\n"
            "❌ Invalid percentage. Please enter a valid risk number (0.1 to 100):"
        )
        return WAITING_RISK

    keyboard = [[InlineKeyboardButton("🔙 إلغاء | Cancel", callback_data="menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = (
        "🧮 <b>حاسبة حجم اللوت | Lot Size Calculator</b>\n"
        f"{'─'*35}\n\n"
        "أدخل <b>حجم وقف الخسارة بالنقاط (SL Pips)</b>\n"
        "تنبيه: في الذهب كل $1 حركة يساوي 10 نقاط (مثال: ستوب $5 = 50 نقطة):\n"
        "Enter your <b>Stop Loss in pips (SL Pips)</b>\n"
        "Note: In gold, $1 movement = 10 pips (e.g. $5 SL = 50 pips):"
    )
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='HTML')
    return WAITING_SL_PIPS


async def process_sl_pips(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Calculate and display the recommended lot size."""
    try:
        sl_pips = float(update.message.text)
        if sl_pips <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text(
            "❌ عدد نقاط غير صالح. يرجى إدخال رقم صحيح:\n"
            "❌ Invalid pips. Please enter a valid number:"
        )
        return WAITING_SL_PIPS

    balance = context.user_data.get('calc_balance', 1000.0)
    risk_pct = context.user_data.get('calc_risk', 1.0)
    
    # Risk calculation
    risk_amount = balance * (risk_pct / 100.0)
    
    # Lot size calculation for Gold (1 pip = $0.10, so 1 std lot pip value = $10)
    # Lot size = Risk Amount / (SL Pips * 10)
    lot_size = risk_amount / (sl_pips * 10.0)

    keyboard = [
        [InlineKeyboardButton("🧮 حساب جديد | Recalculate", callback_data="calculator")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية | Main Menu", callback_data="menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = f"""
⚖️ <b>نتائج إدارة المخاطر | Risk Management Results</b>
{'═'*35}

💵 <b>رصيد الحساب | Balance:</b> ${balance:,.2f}
🛡️ <b>نسبة المخاطرة | Risk:</b> {risk_pct}%
🛑 <b>وقف الخسارة | Stop Loss:</b> {sl_pips:.1f} Pips (Approx. ${sl_pips/10:.2f} Gold move)

🚨 <b>المبلغ المعرض للمخاطرة | Risk Amount:</b> <code>${risk_amount:,.2f}</code>
📊 <b>حجم اللوت الموصى به | Recommended Lot Size:</b>

🏆 <code>{lot_size:.2f} Standard Lots</code> (لوت قياسي)
ℹ️ <i>أو ما يعادل: {lot_size*10:.2f} Mini Lots / {lot_size*100:.2f} Micro Lots</i>

{'─'*35}
⚠️ <i>تأكد دائماً من مطابقة حجم اللوت في منصة التداول الخاصة بك (MT4/MT5).</i>
"""
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='HTML')
    return ConversationHandler.END


async def cancel_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Exit the calculator and return to menu."""
    query = update.callback_query
    if query:
        await query.answer()
        from handlers.start_handler import start_command
        await start_command(update, context)
    return ConversationHandler.END


def get_calculator_conversation_handler():
    """Export the conversation handler for lot size calculator."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_calculator, pattern="^calculator$"),
            CommandHandler("calculator", start_calculator)
        ],
        states={
            WAITING_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_balance)],
            WAITING_RISK: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_risk)],
            WAITING_SL_PIPS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_sl_pips)],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_calculator, pattern="^menu$"),
            CommandHandler("cancel", cancel_calculator)
        ],
    )
