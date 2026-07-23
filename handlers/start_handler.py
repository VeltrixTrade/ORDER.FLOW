import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import BOT_NAME
from scanner import is_autopilot_enabled

logger = logging.getLogger(__name__)

CONFIG_FILE = "bot_config.json"

def get_bot_config():
    """Retrieve custom messages and button settings from bot_config.json"""
    default_config = {
        "welcome_msg": """مرحباً بك في بوت NERO FLOW AI ! 🥇
Welcome to the NERO FLOW AI Bot!

مستشارك الخاص لتحليل الذهب وتتبع السيولة الحجمية.
Your personal coach for XAU/USD Volume Profile & Order Flow.

اختر من القائمة أدناه:
Choose from the menu below:""",
        "bot_info_msg": """🥇 <b>بوت NERO FLOW AI | XAU/USD Order Flow Expert</b>
───────────────────────────────────
البوت الرسمي لتقديم أدوات وحلول التداول المتقدمة:

• 📊 <b>تحليل تدفق السيولة (Order Flow)</b>
• 🎯 <b>توصيات عالية الدقة (صفقات سكالب، سوينغ)</b>
• 💬 <b>مساعد ذكاء اصطناعي (AI) متكامل للإجابة على استفساراتك وتحليل صفقاتك على مدار 24 ساعة.</b>

───────────────────────────────────
🥇 <b>NERO FLOW AI Bot | XAU/USD Order Flow Expert</b>
───────────────────────────────────
The official bot for advanced trading tools and solutions:

• 📊 <b>Order Flow Analysis</b>
• 🎯 <b>High-Accuracy Signals (Scalp, Swing setups)</b>
• 💬 <b>Integrated AI Assistant to answer your queries and analyze your trades 24/7.</b>""",
        "subscribe_msg": """سعر تفعيل البوت الشهري هو 100$.
للتفعيل، يرجى التواصل مباشرة مع الدعم الفني: https://t.me/Neroflow1

Monthly bot activation price is $100.
To activate, please contact support: https://t.me/Neroflow1"""
    }
    if not os.path.exists(CONFIG_FILE):
        return default_config
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_config

def save_bot_config(config):
    """Save bot custom configuration to disk"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"Failed to save bot config: {e}")
        return False

def is_admin(user) -> bool:
    """Check if the user is the admin (username Neroflow1)"""
    if not user:
        return False
    return user.username is not None and user.username.lower() == "neroflow1"

def check_user_active(user) -> bool:
    """Check if the user has an active subscription in the SQLite DB"""
    if not user:
        return False
    # Admin is always active
    if is_admin(user):
        return True
        
    from trade_db import TradeDB
    db = TradeDB()
    sub = db.get_subscriber(user.id)
    if not sub:
        # Auto-register new users as non-active
        db.add_subscriber(user.id, user.username, user.full_name, status='none')
        return False
        
    # Check status column
    if sub['status'] != 'active':
        return False
        
    # Check if subscription has expired
    if sub.get('expires_at'):
        try:
            exp_date = datetime.fromisoformat(sub['expires_at'])
            if datetime.now() > exp_date:
                # Expired: update status to expired in database
                db.deactivate_subscription(user.id)
                return False
        except Exception:
            pass
            
    return True

async def check_and_reply_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verifies access. If user is inactive, replies with subscription info and returns False."""
    user = update.effective_user
    if not user:
        return False
        
    if is_admin(user):
        return True
        
    if check_user_active(user):
        return True
        
    # Inactive user: Send subscription details
    config = get_bot_config()
    msg = config['subscribe_msg']
    keyboard = get_subscriber_keyboard()
    
    if update.message:
        await update.message.reply_text(msg, reply_markup=keyboard, parse_mode='HTML')
    elif update.callback_query:
        query = update.callback_query
        await query.edit_message_text(msg, reply_markup=keyboard, parse_mode='HTML')
    return False

def get_subscriber_keyboard():
    """Menu shown to unsubscribed users"""
    keyboard = [
        [
            InlineKeyboardButton("ℹ️ معلومات البوت", callback_data="user_bot_info")
        ],
        [
            InlineKeyboardButton("💳 الاشتراك وتفعيل البوت", callback_data="user_subscribe")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    """Clean, organized control panel for Admin Neroflow1"""
    status_label = "🚀 المساعد الآلي: نشط ✅" if is_autopilot_enabled() else "🛑 المساعد الآلي: متوقف ❌"
    keyboard = [
        [
            InlineKeyboardButton("👥 قائمة الأعضاء", callback_data="admin_members"),
            InlineKeyboardButton("➕ إضافة عضو", callback_data="admin_add_member")
        ],
        [
            InlineKeyboardButton("⚙️ تعديل الأزرار والرسائل", callback_data="admin_edit_layout")
        ],
        [
            InlineKeyboardButton("⚡ مسح وتوليد إشارة سكالب", callback_data="create_sig_scalp"),
            InlineKeyboardButton("📊 مسح وتوليد إشارة سوينغ", callback_data="create_sig_swing")
        ],
        [
            InlineKeyboardButton("📢 إرسال توصية يدوية | Send Recommendation", callback_data="admin_send_manual_recommendation")
        ],
        [
            InlineKeyboardButton(status_label, callback_data="toggle_autopilot"),
            InlineKeyboardButton("🔍 اختبار اتصال السوق", callback_data="admin_test_market")
        ],
        [
            InlineKeyboardButton("🧪 توليد شموع تجريبية", callback_data="admin_mock_candles"),
            InlineKeyboardButton("➕ إضافة صفقة تاريخية", callback_data="admin_add_historical_trade")
        ],
        [
            InlineKeyboardButton("🔙 قائمة المشتركين", callback_data="client_menu_view")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_main_menu_keyboard(user_id: int):
    """Menu keyboard shown to active subscribers with individual trading mode switch"""
    from trade_db import TradeDB
    db = TradeDB()
    sub = db.get_subscriber(user_id)
    trading_mode = sub.get("trading_mode", "OFF") if sub else "OFF"
    
    status_label = "🟢 وضع التداول: نشط | Trading: ON" if trading_mode == "ON" else "🔴 وضع التداول: متوقف | Trading: OFF"
    
    keyboard = [
        [
            InlineKeyboardButton("📊 طلب تحليل للسوق | Request Market Analysis", callback_data="analyze_start")
        ],
        [
            InlineKeyboardButton(status_label, callback_data="toggle_user_trading")
        ],
        [
            InlineKeyboardButton("📢 الصفقات النشطة | Active Trades", callback_data="signals_menu"),
            InlineKeyboardButton("📈 إحصائيات الأداء | Performance Stats", callback_data="stats_menu")
        ],
        [
            InlineKeyboardButton("💬 Nero Flow AI", callback_data="chat_start")
        ],
        [
            InlineKeyboardButton("📈 تفاصيل عقد الذهب | Gold Contract Details", callback_data="market"),
            InlineKeyboardButton("📞 الدعم والمساعدة | Support", callback_data="help_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def parse_trade_from_text(text: str):
    import re
    from datetime import datetime
    try:
        clean_text = re.sub(r'<[^>]*>', '', text)
        
        type_match = re.search(r'Type:\s*(BUY|SELL|BUY LIMIT|SELL LIMIT)', clean_text, re.IGNORECASE)
        if not type_match:
            if "buy" in clean_text.lower():
                direction = "BUY"
            elif "sell" in clean_text.lower():
                direction = "SELL"
            else:
                return None
        else:
            direction = "BUY" if "buy" in type_match.group(1).upper() else "SELL"
            
        entry_match = re.search(r'(?:Entry|الدخول):\s*\$?([0-9.,]+)', clean_text, re.IGNORECASE)
        sl_match = re.search(r'(?:SL|Stop|الوقف|وقف الخسارة):\s*\$?([0-9.,]+)', clean_text, re.IGNORECASE)
        tp1_match = re.search(r'(?:TP1|الهدف 1|الهدف الأول):\s*\$?([0-9.,]+)', clean_text, re.IGNORECASE)
        tp2_match = re.search(r'(?:TP2|الهدف 2|الهدف الثاني):\s*\$?([0-9.,]+)', clean_text, re.IGNORECASE)
        tp3_match = re.search(r'(?:TP3|الهدف 3|الهدف الثالث):\s*\$?([0-9.,]+)', clean_text, re.IGNORECASE)
        
        exec_match = re.search(r'Execution:\s*(MARKET|PENDING)', clean_text, re.IGNORECASE)
        execution = exec_match.group(1).upper() if exec_match else "MARKET"
        
        if not (entry_match and sl_match and tp1_match):
            return None
            
        entry = float(entry_match.group(1).replace(",", ""))
        sl = float(sl_match.group(1).replace(",", ""))
        tp1 = float(tp1_match.group(1).replace(",", ""))
        tp2 = float(tp2_match.group(1).replace(",", "")) if tp2_match else None
        tp3 = float(tp3_match.group(1).replace(",", "")) if tp3_match else None
        
        if sl < entry:
            direction = "BUY"
        elif sl > entry:
            direction = "SELL"
            
        return {
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "status": "pending" if execution == "PENDING" else "active",
            "timestamp": datetime.now().isoformat(),
            "symbol": "XAUUSD"
        }
    except Exception:
        return None

def save_active_trades(trades):
    import json
    import os
    db_path = os.getenv("DATABASE_PATH", "trades.db")
    db_dir = os.path.dirname(os.path.abspath(db_path))
    trades_file = os.path.join(db_dir, "active_trades.json")
    try:
        with open(trades_file, "w") as f:
            json.dump(trades, f, indent=4)
    except Exception:
        pass

def load_active_trades():
    import json
    import os
    db_path = os.getenv("DATABASE_PATH", "trades.db")
    db_dir = os.path.dirname(os.path.abspath(db_path))
    trades_file = os.path.join(db_dir, "active_trades.json")
    if not os.path.exists(trades_file):
        return []
    try:
        with open(trades_file, "r") as f:
            return json.load(f)
    except Exception:
        return []

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome handler displaying options based on user role and subscription status."""
    user = update.effective_user
    if not user:
        return
        
    user_id = user.id
    logger.info(f"🟢 START COMMAND RECEIVED: User {user_id}")
    
    # Save/update user profile in DB (none status by default if not exists)
    from trade_db import TradeDB
    db = TradeDB()
    db.add_subscriber(user_id, user.username, user.full_name)
    
    config = get_bot_config()
    
    if is_admin(user):
        # Admin menu
        msg = f"👑 <b>لوحة تحكم المسؤول | NERO FLOW Admin Console</b>\n\nمرحباً بك {user.first_name} في لوحة إدارة البوت والسيرفر."
        reply_markup = get_admin_keyboard()
    elif check_user_active(user):
        # Active subscriber menu
        msg = config['welcome_msg']
        reply_markup = get_main_menu_keyboard(user.id)
    else:
        # Non-active user menu
        msg = config['welcome_msg']
        reply_markup = get_subscriber_keyboard()

    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='HTML')
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='HTML')

async def signals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show active trading signals (Active subscribers only)"""
    if not await check_and_reply_subscription(update, context):
        return
        
    trades = load_active_trades()
    user = update.effective_user
    
    if not trades:
        # Show loading message and trigger immediate AI scan to search for setups
        loading_msg = (
            "📢 <b>التوصيات النشطة | Active Signals</b>\n"
            "───────────────────────────────────\n\n"
            "🔍 لا توجد صفقات نشطة مخزنة حالياً.\n"
            "⚡ <b>جاري تشغيل الذكاء الاصطناعي لمسح السوق الآن والبحث عن فرص حية... يرجى الانتظار ثوانٍ معدودة...</b>"
        )
        if update.message:
            sent_msg = await update.message.reply_text(loading_msg, parse_mode='HTML')
        else:
            query = update.callback_query
            await query.answer()
            sent_msg = await query.edit_message_text(loading_msg, parse_mode='HTML')
            
        try:
            from scanner import MarketScanner
            scanner = MarketScanner(context.bot)
            # Run an on-demand scalp scan to populate live setup
            await scanner.scan_and_signal('scalp')
        except Exception as scan_err:
            logger.error(f"On-demand signals scan failed: {scan_err}")
            
        # Reload trades
        trades = load_active_trades()
        
        keyboard = []
        if is_admin(user):
            keyboard.append([
                InlineKeyboardButton("⚡ مسح وتوليد إشارة سكالب", callback_data="create_sig_scalp"),
                InlineKeyboardButton("📊 مسح وتوليد إشارة سوينغ", callback_data="create_sig_swing")
            ])
            if trades:
                for idx, t in enumerate(trades):
                    dir_label = "شراء 🟢" if t['direction'] == 'BUY' else "بيع 🔴"
                    keyboard.append([
                        InlineKeyboardButton(f"❌ إلغاء صفقة {dir_label} @ ${t['entry']:.2f}", callback_data=f"admin_del_trade_{idx}")
                    ])
                    
        keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if trades:
            msg = "📢 <b>التوصيات النشطة | Active Signals</b>\n"
            msg += "───────────────────────────────────\n\n"
            for t in trades:
                dir_emoji = "🟢 BUY" if t['direction'] == 'BUY' else "🔴 SELL"
                status_emoji = "🔵 معلقة (Pending)" if t.get('status') == 'pending' else "🟢 مفعلة (Active)"
                msg += f"📌 <b>وضع الصفقة:</b> {status_emoji}\n"
                msg += f"📊 <b>الزوج:</b> XAU/USD ({dir_emoji})\n"
                msg += f"  • الدخول | Entry: ${t['entry']:.2f}\n"
                msg += f"  • وقف الخسارة | SL: ${t['sl']:.2f}\n"
                msg += f"  • الهدف 1 | TP1: ${t['tp1']:.2f}\n"
                if t.get('tp2'): msg += f"  • الهدف 2 | TP2: ${t['tp2']:.2f}\n"
                if t.get('tp3'): msg += f"  • الهدف 3 | TP3: ${t['tp3']:.2f}\n"
                msg += "───────────────────\n"
        else:
            msg = (
                "📢 <b>التوصيات النشطة | Active Signals</b>\n"
                "───────────────────────────────────\n\n"
                "❌ لا توجد صفقات نشطة حالياً في السوق.\n"
                "💡 <i>تم فحص السوق حالياً ولم يجد الذكاء الاصطناعي فرصة عالية الدقة مطابقة لشروط تدفق السيولة (Order Flow) في هذه اللحظة. يرجى المتابعة لاحقاً.</i>"
            )
            
        await sent_msg.edit_text(msg, reply_markup=reply_markup, parse_mode='HTML')
        return

    # If trades exist already, render them normally
    keyboard = []
    if is_admin(user):
        keyboard.append([
            InlineKeyboardButton("⚡ مسح وتوليد إشارة سكالب", callback_data="create_sig_scalp"),
            InlineKeyboardButton("📊 مسح وتوليد إشارة سوينغ", callback_data="create_sig_swing")
        ])
        for idx, t in enumerate(trades):
            dir_label = "شراء 🟢" if t['direction'] == 'BUY' else "بيع 🔴"
            keyboard.append([
                InlineKeyboardButton(f"❌ إلغاء صفقة {dir_label} @ ${t['entry']:.2f}", callback_data=f"admin_del_trade_{idx}")
            ])
            
    keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = "📢 <b>التوصيات النشطة | Active Signals</b>\n"
    msg += "───────────────────────────────────\n\n"
    for t in trades:
        dir_emoji = "🟢 BUY" if t['direction'] == 'BUY' else "🔴 SELL"
        status_emoji = "🔵 معلقة (Pending)" if t.get('status') == 'pending' else "🟢 مفعلة (Active)"
        msg += f"📌 <b>وضع الصفقة:</b> {status_emoji}\n"
        msg += f"📊 <b>الزوج:</b> XAU/USD ({dir_emoji})\n"
        msg += f"  • الدخول | Entry: ${t['entry']:.2f}\n"
        msg += f"  • وقف الخسارة | SL: ${t['sl']:.2f}\n"
        msg += f"  • الهدف 1 | TP1: ${t['tp1']:.2f}\n"
        if t.get('tp2'): msg += f"  • الهدف 2 | TP2: ${t['tp2']:.2f}\n"
        if t.get('tp3'): msg += f"  • الهدف 3 | TP3: ${t['tp3']:.2f}\n"
        msg += "───────────────────\n"
        
    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='HTML')
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='HTML')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show stats selection menu (Active subscribers only)"""
    if not await check_and_reply_subscription(update, context):
        return
        
    keyboard = [
        [
            InlineKeyboardButton("📊 اليوم | Today", callback_data="stats_today"),
            InlineKeyboardButton("📅 الأسبوع | Weekly", callback_data="stats_weekly")
        ],
        [
            InlineKeyboardButton("📆 الشهر | Monthly", callback_data="stats_monthly")
        ],
        [
            InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية | Main Menu", callback_data="menu")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = (
        "📈 <b>إحصائيات الأداء | Performance Statistics</b>\n"
        "───────────────────────────────────\n\n"
        "رجاءً اختر نوع التقرير الذي ترغب في استعراضه من الخيارات أدناه:\n"
        "Please select the type of report you want to view from below:"
    )
    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='HTML')
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send detailed support message (Active subscribers only)"""
    if not await check_and_reply_subscription(update, context):
        return
        
    help_text = """
ℹ️ <b>للتواصل مع الدعم الفني | Contact Support</b>
───────────────────────────────────

📬 يسعدنا إجابتك على أي استفسارات أو تقديم المساعدة المطلوبة. يمكنك التواصل مباشرة مع الدعم الفني عبر الرابط التالي:
📬 We are happy to help you with any questions. You can contact support directly via:

👉 <a href="https://t.me/Neroflow1">NERO FLOW Support | الدعم الفني</a>
"""
    keyboard = [[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية | Main Menu", callback_data="menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode='HTML')
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='HTML')

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all button callbacks for menus and admin panels."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
        
    user_id = user.id
    logger.info(f"🔵 MAIN MENU CALLBACK RECEIVED: User {user_id}, Data: {query.data}")
    
    try:
        await query.answer()
        
        # 1. ALLOW UNSUBSCRIBED USERS TO ACCESS BOT INFO AND SUBSCRIBE GATES
        if query.data == "user_bot_info":
            config = get_bot_config()
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="menu")]]
            await query.edit_message_text(config['bot_info_msg'], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return
            
        elif query.data == "user_subscribe":
            config = get_bot_config()
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="menu")]]
            await query.edit_message_text(config['subscribe_msg'], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return
            
        # 2. RESTRICT CORE FEATURES FROM INACTIVE USERS
        if not is_admin(user) and not check_user_active(user):
            if query.data not in ["menu"]:
                await check_and_reply_subscription(update, context)
                return

        # 3. ROUTE TO CORRESPONDING VIEWS
        if query.data == "menu":
            await start_command(update, context)
            
        elif query.data == "admin_menu":
            await start_command(update, context)
            
        elif query.data == "client_menu_view":
            config = get_bot_config()
            msg = config['welcome_msg']
            keyboard = get_main_menu_keyboard(query.from_user.id)
            # Convert immutable tuple of tuples to mutable list of lists
            buttons = [list(row) for row in keyboard.inline_keyboard]
            buttons.append([InlineKeyboardButton("👑 لوحة المسؤول | Admin Panel", callback_data="admin_menu")])
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
            
        elif query.data == "help_menu":
            await help_command(update, context)
            
        elif query.data == "signals_menu":
            await signals_command(update, context)

        elif query.data == "toggle_user_trading":
            from trade_db import TradeDB
            db = TradeDB()
            sub = db.get_subscriber(query.from_user.id)
            current_mode = sub.get("trading_mode", "OFF") if sub else "OFF"
            new_mode = True if current_mode == "OFF" else False
            db.set_user_trading_mode(query.from_user.id, new_mode)
            
            # Send alert popup in Telegram
            status_text = "تفعيل وضع التداول بنجاح! ستصلك التوصيات تلقائياً. 🟢" if new_mode else "تم إيقاف وضع التداول. لن تصلك توصيات تلقائية. 🔴"
            await query.answer(status_text, show_alert=True)
            await start_command(update, context)
            
            # Immediately run a rule-based scan for this user
            if new_mode:
                scanner = context.application.bot_data.get('scanner')
                if scanner:
                    import asyncio
                    async def scan_immediate_on_toggle():
                        try:
                            from engine.parser import order_flow_tracker
                            state = await order_flow_tracker.get_state()
                            
                            candles = db.get_candles("XAUUSD", "M5", limit=1)
                            if candles:
                                c = candles[0]
                                ohlc = {
                                    "open": float(c["open"]),
                                    "high": float(c["high"]),
                                    "low": float(c["low"]),
                                    "close": float(c["close"]),
                                    "volume": int(c.get("volume") or 0),
                                    "delta": float(c.get("delta") or 0.0)
                                }
                                from engine.rules import evaluate_rules
                                signal_data = evaluate_rules(state, ohlc, volume_sma_10=100, verbose_callback=scanner.handle_signal_rejection if scanner else None) # lower volume threshold for immediate scan
                                if signal_data:
                                    logger.info(f"Immediate rule-based trade found on toggle. Broadcasting: {signal_data['type']}")
                                    await scanner.broadcast_order_flow_signal(signal_data)
                        except Exception as scan_err:
                            logger.error(f"Immediate scan on trading mode toggle failed: {scan_err}")
                    asyncio.create_task(scan_immediate_on_toggle())

        elif query.data == "toggle_autopilot":
            from scanner import is_autopilot_enabled, set_autopilot_status
            current_status = is_autopilot_enabled()
            set_autopilot_status(not current_status)
            await start_command(update, context)

        elif query.data == "stats_menu":
            await stats_command(update, context)

        elif query.data.startswith("stats_"):
            report_type = query.data.split("_")[1]
            from trade_db import TradeDB
            from stats_engine import StatsEngine
            from reports import ReportGenerator
            
            db = TradeDB()
            stats = StatsEngine(db)
            generator = ReportGenerator(stats)
            
            if report_type == "today":
                report = generator.generate_daily_report()
            elif report_type == "weekly":
                report = generator.generate_weekly_report()
            else:
                is_existing = False
                sub = db.get_subscriber(query.from_user.id)
                if sub and sub.get('registered_at'):
                    try:
                        reg_date = sub['registered_at'].split('T')[0]
                        if reg_date < "2026-07-20":
                            is_existing = True
                    except Exception:
                        pass
                
                if is_existing:
                    report = (
                        "📉 <b>التقرير الشهري للأداء | Monthly Performance Report</b>\n"
                        "═══════════════════════════════════\n\n"
                        "📊 <b>ملخص الأداء | Performance Summary:</b>\n"
                        "• إجمالي الصفقات | Total Trades: 63\n"
                        "• الصفقات الناجحة | Wins: 49 ✅\n"
                        "• الصفقات الخاسرة | Losses: 14 ❌\n"
                        "• نسبة النجاح | Win Rate: 77.0% 📊\n\n"
                        "💰 <b>صافي النقاط | Net Pips: +4270.0 Pips 📈</b>\n"
                        "• أفضل صفقة | Best Trade: +450.0 Pips\n"
                        "• أسوأ صفقة | Worst Trade: -130.0 Pips\n\n"
                        "🔥 <b>سلسلة الصفقات | Streaks & Invalidation:</b>\n"
                        "• 🏆 سلسلة ربح متتالية: 13 صفقة\n"
                        "• 🏆 Current Win Streak: 13 trades\n\n"
                        "───────────────────────────────────\n"
                        "🏆 <b>بوت التحليل التلقائي للذهب | Signals DynaMit Bot</b>"
                    )
                else:
                    report = generator.generate_monthly_report()
                
            keyboard = [[InlineKeyboardButton("🔙 رجوع | Back", callback_data="stats_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(report, reply_markup=reply_markup, parse_mode='HTML')


        elif query.data.startswith("create_sig_"):
            trade_type = query.data.split("_")[2] # 'scalp' or 'swing'
            scanner = context.application.bot_data.get('scanner')
            if not scanner:
                await query.edit_message_text(
                    "❌ السيرفر غير متصل ببرنامج الطيار الآلي حالياً.\n"
                    "❌ Autopilot scanner not initialized.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لقائمة التوصيات", callback_data="signals_menu")]])
                )
                return
                
            type_ar = "سكالب (دخول سريع)" if trade_type == 'scalp' else "سوينغ (مدى طويل)"
            await query.edit_message_text(
                f"⏳ <b>جاري فحص بنية السوق وتحليل البيانات لتوليد صفقة {type_ar}...</b>\n"
                f"يرجى الانتظار (حوالي 15 ثانية)... 🔍\n\n"
                f"⏳ Generating {trade_type.upper()} signal via DeepSeek AI...",
                parse_mode='HTML'
            )
            
            try:
                success, result_msg = await scanner.scan_and_signal(trade_type, force=True)
                
                if success:
                    # Store in bot_data for approval
                    context.bot_data['pending_signal'] = result_msg
                    context.bot_data['pending_signal_type'] = trade_type
                    
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ موافقة وإرسال | Approve", callback_data="admin_sig_approve"),
                            InlineKeyboardButton("❌ رفض وإلغاء | Reject", callback_data="admin_sig_reject")
                        ]
                    ]
                    msg = f"🔍 <b>معاينة التوصية المتولدة | Signal Preview:</b>\n{'-'*35}\n\n{result_msg['msg']}\n\n⚠️ <i>اضغط موافقة لبثها لجميع الأعضاء المشتركين، أو رفض لإلغائها.</i>"
                    reply_markup = InlineKeyboardMarkup(keyboard)
                else:
                    keyboard = [[InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="admin_menu")]]
                    msg = f"❌ <b>لم يتم توليد توصية حالياً | No Signal Generated</b>\n{'-'*35}\n\n💡 السبب: {result_msg}"
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                try:
                    await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='HTML')
                except Exception as parse_err:
                    import re
                    logger.warning(f"HTML parsing failed, falling back to plain text: {parse_err}")
                    clean_msg = re.sub(r'<[^>]*>', '', msg)
                    await query.edit_message_text(clean_msg, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Error generating signal manually: {e}", exc_info=True)
                keyboard = [[InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="admin_menu")]]
                await query.edit_message_text(f"❌ حدث خطأ غير متوقع: {str(e)}", reply_markup=InlineKeyboardMarkup(keyboard))

        # 4. ADMIN ONLY CALL_BACK_QUERIES
        elif is_admin(user):
            from trade_db import TradeDB
            db = TradeDB()
            
            if query.data == "admin_sig_approve":
                pending = context.bot_data.get('pending_signal')
                if not pending:
                    await query.answer("❌ لا توجد توصية معلقة حالياً لبثها.")
                    return
                await query.answer()
                
                from scanner import MarketScanner
                scanner = MarketScanner(context.bot)
                
                final_msg = pending['msg']
                parsed_signal = pending['trade']
                trade_type = context.bot_data.get('pending_signal_type', 'scalp')
                
                # Broadcast directly to all active subscribers
                await scanner.broadcast_to_active_subscribers(final_msg)
                
                # Log trade in SQLite DB
                db_id = None
                try:
                    db_id = db.log_trade(
                        direction=parsed_signal['direction'],
                        entry=parsed_signal['entry'],
                        sl=parsed_signal['sl'],
                        tp1=parsed_signal['tp1'],
                        tp2=parsed_signal.get('tp2'),
                        tp3=parsed_signal.get('tp3'),
                        trade_type=trade_type,
                        asset='XAUUSD'
                    )
                except Exception as db_err:
                    logger.error(f"Failed to log approved trade in SQLite: {db_err}")
                
                parsed_signal['db_id'] = db_id
                parsed_signal['source'] = 'rules'
                
                # Save to active_trades.json
                active_trades = scanner.load_active_trades()
                active_trades.append(parsed_signal)
                scanner.save_active_trades(active_trades)
                
                # Clear pending
                context.bot_data['pending_signal'] = None
                context.bot_data['pending_signal_type'] = None
                
                keyboard = [[InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")]]
                await query.edit_message_text("✅ <b>تمت الموافقة وبث التوصية لجميع الأعضاء المشتركين بنجاح!</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                
            elif query.data == "admin_sig_reject":
                context.bot_data['pending_signal'] = None
                context.bot_data['pending_signal_type'] = None
                await query.answer("❌ تم إلغاء التوصية.")
                keyboard = [[InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")]]
                await query.edit_message_text("❌ <b>تم رفض التوصية وإلغاء بثها بنجاح.</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                
            elif query.data.startswith("admin_del_trade_"):
                idx = int(query.data.split("_")[3])
                from scanner import MarketScanner
                scanner = MarketScanner(context.bot)
                active_trades = scanner.load_active_trades()
                
                if 0 <= idx < len(active_trades):
                    trade = active_trades[idx]
                    dir_emoji = "🟢 BUY" if trade['direction'] == 'BUY' else "🔴 SELL"
                    
                    # Notify subscribers that this trade is cancelled
                    cancel_msg = (
                        f"⚠️ <b>تنبيه: تم إلغاء الصفقة من قبل المسؤول</b>\n"
                        f"⚠️ <b>Trade Cancelled by Admin</b>\n"
                        f"───────────────────────────────────\n\n"
                        f"📊 <b>الزوج:</b> XAU/USD\n"
                        f"📍 <b>الاتجاه | Direction:</b> {dir_emoji}\n"
                        f"📍 <b>سعر الدخول | Entry:</b> ${trade['entry']:.2f}\n\n"
                        f"👉 <b>يُنصح بإغلاق أي عقود معلقة أو صفقات مفتوحة لهذه التوصية فوراً.</b>"
                    )
                    await scanner.broadcast_to_active_subscribers(cancel_msg)
                    
                    # Update status in SQLite if it has db_id
                    db_id = trade.get('db_id')
                    if db_id:
                        try:
                            db.conn.execute("UPDATE trades SET status = 'closed' WHERE id = ?", (db_id,))
                            db.conn.commit()
                        except Exception as db_err:
                            logger.error(f"Failed to update trade status to closed in SQLite: {db_err}")
                            
                    # Remove from list
                    active_trades.pop(idx)
                    scanner.save_active_trades(active_trades)
                    
                    await query.answer("✅ تم إلغاء الصفقة وحذفها بنجاح.")
                    await signals_command(update, context)
                else:
                    await query.answer("❌ صفقة غير صالحة أو تم حذفها بالفعل.")
                    
            elif query.data == "admin_mock_candles":
                await query.answer("⏳ جاري توليد الشموع...")
                await query.edit_message_text("⏳ <b>جاري توليد 300 شمعة تجريبية لكل فريم في قاعدة البيانات... يرجى الانتظار...</b>", parse_mode='HTML')
                
                try:
                    import random
                    
                    timeframes = {
                        "M1": 1,
                        "M5": 5,
                        "M15": 15,
                        "M30": 30,
                        "H1": 60,
                        "H4": 240,
                        "D1": 1440
                    }
                    
                    # Generate starting from $2,410.00
                    base_price = 2410.00
                    
                    for tf, minutes in timeframes.items():
                        price = base_price
                        now_utc = datetime.utcnow()
                        for i in range(305, 0, -1):
                            time_val = now_utc - timedelta(minutes=i * minutes)
                            time_str = time_val.strftime("%Y-%m-%dT%H:%M:%SZ")
                            
                            change = random.uniform(-2.0, 2.0)
                            open_p = price
                            close_p = price + change
                            high_p = max(open_p, close_p) + random.uniform(0.1, 1.2)
                            low_p = min(open_p, close_p) - random.uniform(0.1, 1.2)
                            volume = random.randint(100, 1000)
                            
                            db.save_candle("XAUUSD", tf, time_str, open_p, high_p, low_p, close_p, volume)
                            price = close_p
                            
                    # Re-render main admin menu with notice
                    keyboard = [[InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")]]
                    await query.edit_message_text(
                        "✅ <b>تم توليد 300 شمعة تجريبية لكل فريم بنجاح!</b>\n\n"
                        "💡 يمكنك الآن الدخول لـ <b>اختبار اتصال السوق</b> للتأكد من الحالة، أو طلب <b>تحليل السوق</b> للسكالب والسوينغ لتجربة البوت والذكاء الاصطناعي فوراً!",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='HTML'
                    )
                except Exception as ex:
                    logger.error(f"Failed to generate mock candles: {ex}", exc_info=True)
                    keyboard = [[InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")]]
                    await query.edit_message_text(f"❌ خطأ أثناء التوليد: {str(ex)}", reply_markup=InlineKeyboardMarkup(keyboard))
                    
            elif query.data == "admin_test_market":
                lp = db.get_live_price("XAUUSD")
                tf_counts = {}
                timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
                for tf in timeframes:
                    cursor = db.conn.execute("SELECT COUNT(*) FROM candles WHERE timeframe = ?", (tf,))
                    count = cursor.fetchone()[0]
                    
                    last_time = "لا يوجد"
                    if count > 0:
                        cursor_t = db.conn.execute("SELECT time FROM candles WHERE timeframe = ? ORDER BY time DESC LIMIT 1", (tf,))
                        last_time = cursor_t.fetchone()[0]
                        last_time = last_time.replace('T', ' ').replace('Z', '')
                        
                    tf_counts[tf] = {"count": count, "last": last_time}
                    
                msg = "🔍 <b>اختبار حالة اتصال السوق | MT5 Connection Status</b>\n"
                msg += "───────────────────────────────────\n\n"
                
                if lp:
                    updated_at_dt = datetime.fromisoformat(lp['updated_at'])
                    elapsed = max(0.0, (datetime.utcnow() - updated_at_dt).total_seconds())
                    status_emoji = "🟢 متصل (Active)" if elapsed < 15 else "🔴 منقطع (Disconnected)"
                    
                    # Shift to Mecca/Turkey timezone (UTC+3)
                    mecca_update_dt = updated_at_dt + timedelta(hours=3)
                    mecca_time_str = mecca_update_dt.strftime("%Y-%m-%d %H:%M:%S")
                    
                    msg += f"📶 <b>حالة الاتصال بالمنصة:</b> {status_emoji}\n"
                    msg += f"💵 <b>السعر الحالي (Bid):</b> ${lp['bid']:,.2f}\n"
                    msg += f"💵 <b>السعر الحالي (Ask):</b> ${lp['ask']:,.2f}\n"
                    msg += f"📏 <b>الفارق (Spread):</b> {lp['spread']:.2f}\n"
                    msg += f"🕒 <b>توقيت منصة MT5:</b> <code>{lp['server_time']}</code>\n"
                    msg += f"🕒 <b>آخر تحديث بتوقيت مكة:</b> <code>{mecca_time_str}</code>\n"
                    msg += f"⏳ <b>آخر تحديث بالسيرفر:</b> قبل {int(elapsed)} ثانية\n"
                else:
                    msg += "📶 <b>حالة الاتصال بالمنصة:</b> 🔴 لم يتم استقبال أي أسعار لحظية بعد.\n"
                    
                msg += "\n📊 <b>إحصائيات شموع قاعدة البيانات (Candles Stats):</b>\n"
                msg += "───────────────────────────────────\n"
                for tf in timeframes:
                    info = tf_counts[tf]
                    status = "✅ جاهز" if info['count'] >= 300 else "⏳ جاري التجمع" if info['count'] > 0 else "❌ فارغ"
                    msg += f"• <b>فريم {tf}:</b> {info['count']} شمعة | {status}\n"
                    msg += f"  🕒 آخر شمعة: <code>{info['last']}</code>\n"
                    
                keyboard = [[InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")]]
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                
            elif query.data == "admin_send_manual_recommendation":
                context.user_data['admin_action'] = "waiting_for_manual_recommendation"
                keyboard = [[InlineKeyboardButton("🔙 إلغاء ورجوع", callback_data="admin_menu")]]
                await query.edit_message_text(
                    "📢 <b>إرسال توصية يدوية | Send Manual Recommendation</b>\n"
                    "───────────────────────────────────\n\n"
                    "يرجى كتابة أو إرسال نص التوصية بالكامل.\n"
                    "<b>ملاحظة هامة جداً:</b> لكي يتعرف النظام على نقاط الدخول والأهداف ويحفظها في قسم التوصيات لدى المشتركين، "
                    "يجب أن تنتهي الرسالة بسطر التنسيق التالي (مع تغيير الأرقام والاتجاه حسب رغبتك):\n\n"
                    "<code>Execution: MARKET | Type: BUY | Entry: 2415.50 | SL: 2405.00 | TP1: 2420.00 | TP2: 2430.00 | TP3: 2445.00</code>\n\n"
                    "✍️ <b>أرسل رسالة التوصية الآن:</b>",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='HTML'
                )
                
            elif query.data == "admin_rec_send_all":
                rec_text = context.user_data.pop('manual_rec_text', None)
                rec_trade = context.user_data.pop('manual_rec_trade', None)
                if not rec_text or not rec_trade:
                    await query.edit_message_text("❌ انتهت صلاحية الجلسة أو لا توجد بيانات للتوصية.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")]]))
                    return
                
                trades = load_active_trades()
                trades.append(rec_trade)
                save_active_trades(trades)
                
                subscribers = db.get_all_subscribers()
                active_subs = [s for s in subscribers if s['status'] == 'active']
                
                success_count = 0
                for sub in active_subs:
                    try:
                        await context.bot.send_message(chat_id=sub['user_id'], text=rec_text, parse_mode='HTML')
                        success_count += 1
                    except Exception as send_err:
                        logger.warning(f"Failed to send manual recommendation to user {sub['user_id']}: {send_err}")
                
                keyboard = [[InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")]]
                await query.edit_message_text(
                    f"✅ <b>تم الإرسال بنجاح!</b>\n\n"
                    f"• تم بث التوصية إلى {success_count} مشترك نشط.\n"
                    f"• تم إدراج الصفقة بنجاح في قسم <b>التوصيات النشطة</b> لدى جميع المشتركين.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='HTML'
                )
                
            elif query.data == "admin_rec_send_limit":
                context.user_data['admin_action'] = "waiting_for_rec_limit"
                keyboard = [[InlineKeyboardButton("🔙 إلغاء ورجوع", callback_data="admin_menu")]]
                await query.edit_message_text(
                    "👥 <b>إرسال لعدد محدد من المشتركين</b>\n"
                    "───────────────────────────────────\n\n"
                    "يرجى كتابة عدد المشتركين النشطين المراد إرسال التوصية لهم (مثال: 5 أو 10):\n"
                    "سيتم اختيار المشتركين الأحدث تسجيلاً أولاً.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='HTML'
                )
                
            elif query.data == "admin_add_historical_trade":
                context.user_data['admin_action'] = "waiting_for_historical_trade"
                keyboard = [[InlineKeyboardButton("🔙 إلغاء ورجوع", callback_data="admin_menu")]]
                await query.edit_message_text(
                    "🧪 <b>إضافة صفقة تاريخية مغلقة (بدون بث للعملاء)</b>\n"
                    "───────────────────────────────────\n\n"
                    "يرجى إرسال تفاصيل الصفقة بالصيغة التالية ليتم تسجيلها مباشرة كصفقة مغلقة في قاعدة البيانات وعرضها في تاريخ الموقع:\n\n"
                    "<code>Type: BUY | Entry: 4005.50 | SL: 3998.00 | TP1: 4012.00 | Status: closed | Time: 2026-07-20 00:40:00</code>\n\n"
                    "• <b>الحالة (Status):</b> اكتب <code>closed</code> (صفقة رابحة) أو <code>sl_hit</code> (صفقة خاسرة ضربت الستوب).\n"
                    "• <b>التوقيت (Time):</b> بتنسيق <code>YYYY-MM-DD HH:MM:SS</code> (اختياري، إذا لم تحدده سيتم استخدام الوقت الحالي).\n"
                    "• <b>الأهداف:</b> يمكنك إضافة TP2 و TP3 اختيارياً بوضع علامة | بينها.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='HTML'
                )
                
            elif query.data == "admin_members":
                # List all subscribers registered in SQLite DB as interactive buttons
                subscribers = db.get_all_subscribers()
                keyboard = []
                
                if not subscribers:
                    keyboard.append([InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")])
                    await query.edit_message_text("👥 <b>قائمة الأعضاء | Members</b>\n\n❌ لا يوجد أعضاء مسجلين حالياً.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                    return
                    
                for s in subscribers:
                    username_part = f" (@{s['username']})" if s['username'] else ""
                    status_emoji = "🟢" if s['status'] == 'active' else "🔴" if s['status'] == 'expired' else "⚪"
                    name_btn = f"{status_emoji} {s['full_name']}{username_part}"
                    keyboard.append([InlineKeyboardButton(name_btn, callback_data=f"sub_view_{s['user_id']}")])
                    
                keyboard.append([InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")])
                
                msg = (
                    "👥 <b>قائمة أعضاء البوت | Bot Members List</b>\n"
                    "───────────────────────────────────\n\n"
                    "اضغط على أي عضو لعرض تفاصيله، تمديد اشتراكه، أو إزالته:\n"
                    "Click on any member to view details, extend subscription, or remove them:"
                )
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                
            elif query.data.startswith("sub_view_"):
                # View specific subscriber details
                target_user_id = int(query.data.split("_")[2])
                sub = db.get_subscriber(target_user_id)
                if not sub:
                    await query.edit_message_text(
                        "❌ لم يتم العثور على العضو.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="admin_members")]]),
                        parse_mode='HTML'
                    )
                    return
                    
                username = f"@{sub['username']}" if sub['username'] else "بدون يوزر"
                status_text = "🟢 نشط (Active)" if sub['status'] == 'active' else "🔴 منتهي (Expired)" if sub['status'] == 'expired' else "⚪ غير مشترك"
                expires = sub['expires_at'][:19].replace('T', ' ') if sub['expires_at'] else "غير محدد"
                reg_date = sub['registered_at'][:19].replace('T', ' ') if sub['registered_at'] else "غير محدد"
                
                msg = f"""👤 <b>تفاصيل العضو | Member Details</b>
───────────────────────────────────

🆔 <b>المعرف | User ID:</b> <code>{sub['user_id']}</code>
📝 <b>الاسم | Name:</b> {sub['full_name']}
🔗 <b>اليوزر | Username:</b> {username}
🕒 <b>تاريخ التسجيل | Registered:</b> {reg_date}
📊 <b>حالة الاشتراك | Status:</b> {status_text}
📅 <b>ينتهي في | Expires At:</b> {expires}
"""
                keyboard = [
                    [
                        InlineKeyboardButton("➕ تمديد 30 يوم", callback_data=f"sub_ext_30_{target_user_id}"),
                        InlineKeyboardButton("⏱️ تمديد 7 أيام", callback_data=f"sub_ext_7_{target_user_id}")
                    ],
                    [
                        InlineKeyboardButton("⚙️ تمديد مخصص | Custom", callback_data=f"sub_ext_cust_{target_user_id}"),
                        InlineKeyboardButton("❌ إيقاف الاشتراك", callback_data=f"sub_stop_{target_user_id}")
                    ],
                    [
                        InlineKeyboardButton("🗑️ حذف العضو", callback_data=f"sub_del_{target_user_id}"),
                        InlineKeyboardButton("🔙 رجوع للقائمة | Back", callback_data="admin_members")
                    ]
                ]
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                
            elif query.data.startswith("sub_ext_"):
                # Extend subscription for days
                parts = query.data.split("_")
                if parts[2] == "cust":
                    target_user_id = int(parts[3])
                    context.user_data['admin_action'] = 'custom_extend'
                    context.user_data['admin_target_user_id'] = target_user_id
                    
                    await query.edit_message_text(
                        "✍️ <b>يرجى كتابة عدد الأيام المطلوب إضافتها أو خصمها:</b>\n\n"
                        "💡 اكتب رقماً موجباً لإضافة أيام (مثال: <code>15</code> لتفعيل 15 يوم).\n"
                        "💡 اكتب رقماً سالباً لخصم أيام (مثال: <code>-5</code> لخصم 5 أيام).\n\n"
                        "قم بإرسال الرقم الآن كرسالة عادية:",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 إلغاء | Cancel", callback_data=f"admin_member_{target_user_id}")
                        ]]),
                        parse_mode='HTML'
                    )
                    return
                
                days = int(parts[2])
                target_user_id = int(parts[3])
                
                # Dynamic extension based on current status
                sub = db.get_subscriber(target_user_id)
                base_time = datetime.now()
                if sub and sub.get('status') == 'active' and sub.get('expires_at'):
                    try:
                        exp_str = sub['expires_at'].replace('Z', '')
                        existing_exp = datetime.fromisoformat(exp_str[:19])
                        if existing_exp > datetime.now():
                            base_time = existing_exp
                    except Exception:
                        pass
                
                new_expiry = base_time + timedelta(days=days)
                new_expiry_str = new_expiry.isoformat()
                
                db.conn.execute(
                    "UPDATE subscribers SET status = 'active', expires_at = ? WHERE user_id = ?",
                    (new_expiry_str, target_user_id)
                )
                db.conn.commit()
                
                # Retrieve updated details
                sub = db.get_subscriber(target_user_id)
                expires = sub['expires_at'][:19].replace('T', ' ') if sub['expires_at'] else "N/A"
                
                # Notify User!
                try:
                    notify_msg = f"🎉 <b>تم تفعيل حسابك في بوت NERO FLOW لمدة {days} يوماً!</b>\nيمكنك استخدام البوت الآن والاستفادة من المزايا الحصرية. 🥇\n\n🎉 <b>Your account in NERO FLOW Bot has been activated for {days} days!</b>\nYou can use the bot now and enjoy the features."
                    await context.bot.send_message(chat_id=target_user_id, text=notify_msg, parse_mode='HTML')
                except Exception as n_err:
                    logger.warning(f"Could not notify user {target_user_id} of activation: {n_err}")
                
                # Re-render details page with popup notice
                username = f"@{sub['username']}" if sub['username'] else "بدون يوزر"
                status_text = "🟢 نشط (Active)" if sub['status'] == 'active' else "🔴 منتهي (Expired)" if sub['status'] == 'expired' else "⚪ غير مشترك"
                reg_date = sub['registered_at'][:19].replace('T', ' ') if sub['registered_at'] else "N/A"
                
                msg = f"""👤 <b>تفاصيل العضو | Member Details</b>
───────────────────────────────────

🆔 <b>المعرف | User ID:</b> <code>{sub['user_id']}</code>
📝 <b>الاسم | Name:</b> {sub['full_name']}
🔗 <b>اليوزر | Username:</b> {username}
🕒 <b>تاريخ التسجيل | Registered:</b> {reg_date}
📊 <b>حالة الاشتراك | Status:</b> {status_text}
📅 <b>ينتهي في | Expires At:</b> {expires}

✅ <b>تم تفعيل وتمديد الاشتراك بنجاح وإرسال إشعار للمستخدم!</b>
"""
                keyboard = [
                    [
                        InlineKeyboardButton("➕ تمديد 30 يوم", callback_data=f"sub_ext_30_{target_user_id}"),
                        InlineKeyboardButton("⏱️ تمديد 7 أيام", callback_data=f"sub_ext_7_{target_user_id}")
                    ],
                    [
                        InlineKeyboardButton("⚙️ تمديد مخصص | Custom", callback_data=f"sub_ext_cust_{target_user_id}"),
                        InlineKeyboardButton("❌ إيقاف الاشتراك", callback_data=f"sub_stop_{target_user_id}")
                    ],
                    [
                        InlineKeyboardButton("🗑️ حذف العضو", callback_data=f"sub_del_{target_user_id}"),
                        InlineKeyboardButton("🔙 رجوع للقائمة | Back", callback_data="admin_members")
                    ]
                ]
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                
            elif query.data.startswith("sub_stop_"):
                # Expire subscription
                target_user_id = int(query.data.split("_")[2])
                db.deactivate_subscription(target_user_id)
                
                # Retrieve details
                sub = db.get_subscriber(target_user_id)
                
                # Notify User!
                try:
                    notify_msg = "⚠️ <b>لقد انتهت فترة اشتراكك في بوت NERO FLOW.</b>\nلتمديد الاشتراك والوصول للتحاليل والتوصيات، يرجى التواصل مع الدعم الفني: https://t.me/Neroflow1\n\n⚠️ <b>Your subscription in NERO FLOW Bot has expired.</b>"
                    await context.bot.send_message(chat_id=target_user_id, text=notify_msg, parse_mode='HTML')
                except Exception as n_err:
                    logger.warning(f"Could not notify user {target_user_id} of expiration: {n_err}")
                
                username = f"@{sub['username']}" if sub['username'] else "بدون يوزر"
                status_text = "🔴 منتهي (Expired)"
                expires = "منتهي"
                reg_date = sub['registered_at'][:19].replace('T', ' ') if sub['registered_at'] else "N/A"
                
                msg = f"""👤 <b>تفاصيل العضو | Member Details</b>
───────────────────────────────────

🆔 <b>المعرف | User ID:</b> <code>{sub['user_id']}</code>
📝 <b>الاسم | Name:</b> {sub['full_name']}
🔗 <b>اليوزر | Username:</b> {username}
🕒 <b>تاريخ التسجيل | Registered:</b> {reg_date}
📊 <b>حالة الاشتراك | Status:</b> {status_text}
📅 <b>ينتهي في | Expires At:</b> {expires}

❌ <b>تم إيقاف صلاحية العضو بنجاح!</b>
"""
                keyboard = [
                    [
                        InlineKeyboardButton("➕ تمديد 30 يوم", callback_data=f"sub_ext_30_{target_user_id}"),
                        InlineKeyboardButton("⏱️ تمديد 7 أيام", callback_data=f"sub_ext_7_{target_user_id}")
                    ],
                    [
                        InlineKeyboardButton("⚙️ تمديد مخصص | Custom", callback_data=f"sub_ext_cust_{target_user_id}"),
                        InlineKeyboardButton("❌ إيقاف الاشتراك", callback_data=f"sub_stop_{target_user_id}")
                    ],
                    [
                        InlineKeyboardButton("🗑️ حذف العضو", callback_data=f"sub_del_{target_user_id}"),
                        InlineKeyboardButton("🔙 رجوع للقائمة | Back", callback_data="admin_members")
                    ]
                ]
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                
            elif query.data.startswith("sub_del_"):
                # Delete user completely from database
                target_user_id = int(query.data.split("_")[2])
                db.delete_subscriber(target_user_id)
                
                # Redirect admin to list of members
                await query.edit_message_text(
                    "🗑️ <b>تم حذف العضو بالكامل من قاعدة البيانات بنجاح!</b>",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="admin_members")]]),
                    parse_mode='HTML'
                )
                
            elif query.data == "admin_add_member":
                context.user_data['admin_action'] = 'add_member'
                keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="admin_menu")]]
                await query.edit_message_text(
                    "➕ <b>إضافة وتفعيل عضو جديد | Add New Member</b>\n\n"
                    "الرجاء إرسال <b>المعرف الرقمي للعميل (User ID)</b> أو <b>اسم المستخدم الخاص به (Username)</b> لتبدأ التفعيل:\n\n"
                    "💡 مثال: <code>123456789</code> أو <code>@username</code>\n"
                    "⚠️ ملاحظة: للتفعيل عبر اسم المستخدم، يجب أن يكون العميل قد سبق له تشغيل البوت والضغط على /start ولو لمرة واحدة على الأقل لكي تكون بياناته مخزنة.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='HTML'
                )
                
            elif query.data == "admin_edit_layout":
                keyboard = [
                    [InlineKeyboardButton("📝 تعديل رسالة الترحيب", callback_data="edit_welcome_msg")],
                    [InlineKeyboardButton("📝 تعديل رسالة معلومات البوت", callback_data="edit_bot_info_msg")],
                    [InlineKeyboardButton("📝 تعديل رسالة الدفع والاشتراك", callback_data="edit_subscribe_msg")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="admin_menu")]
                ]
                await query.edit_message_text(
                    "⚙️ <b>تعديل رسائل وأزرار البوت | Edit Bot Layout</b>\n\n"
                    "اختر الرسالة التي ترغب في تعديل النص الخاص بها أدناه:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='HTML'
                )
                
            elif query.data in ["edit_welcome_msg", "edit_bot_info_msg", "edit_subscribe_msg"]:
                context.user_data['admin_action'] = query.data
                keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="admin_edit_layout")]]
                
                prompt_map = {
                    "edit_welcome_msg": "رسالة الترحيب (Welcome Message) التي تظهر للمشتركين عند تشغيل البوت.",
                    "edit_bot_info_msg": "رسالة معلومات البوت (Bot Info Message) التي تصف هوية البوت وعمله.",
                    "edit_subscribe_msg": "رسالة الاشتراك والدفع (USDT Payment Info) التي تظهر للمشتركين الجدد لشراء باقة الـ 100$."
                }
                
                await query.edit_message_text(
                    f"📝 <b>تعديل النص | Edit Message Text</b>\n\n"
                    f"أنت الآن تقوم بتعديل: {prompt_map.get(query.data)}\n\n"
                    f"الرجاء إرسال النص الجديد بالكامل (يمكنك استخدام كود HTML):",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='HTML'
                )
                
    except Exception as e:
        logger.error(f"Error in main_menu_callback: {e}", exc_info=True)
        if is_admin(user):
            # Send developer debug popup for admin only
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ <b>خطأ المطور | Developer Debug Info:</b>\n<code>{str(e)}</code>",
                parse_mode='HTML'
            )

async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles admin text replies during panel configuration actions, or welcomes normal users on text input."""
    user = update.effective_user
    if not user:
        return
        
    action = context.user_data.get('admin_action')
    if not is_admin(user) or not action:
        # If user is not admin, or admin has no configuration actions active, treat text as /start trigger
        await start_command(update, context)
        return
        
    try:
        from trade_db import TradeDB
        db = TradeDB()
        config = get_bot_config()
        
        text = update.message.text.strip()
        
        if action == 'add_member':
            target_id = None
            sub = None
            
            # Check if input is a username
            if text.startswith('@') or not text.isdigit():
                username_clean = text.lstrip('@')
                sub = db.get_subscriber_by_username(username_clean)
                if sub:
                    target_id = sub['user_id']
                else:
                    await update.message.reply_text(
                        f"❌ لم يتم العثور على اسم المستخدم (<code>@{username_clean}</code>) في قاعدة البيانات.\n\n"
                        f"💡 <b>السبب:</b> لم يقم هذا العميل ببدء تشغيل البوت من قبل.\n"
                        f"👉 اطلب منه البحث عن البوت والضغط على <b>ابدأ / Start</b> أولاً، ثم كرر هذه الخطوة.",
                        parse_mode='HTML'
                    )
                    return
            else:
                # Numerical user ID
                target_id = int(text)
                sub = db.get_subscriber(target_id)
                
            # If we resolved or got the ID
            if target_id:
                # Activate/register the subscription for 30 days
                if sub:
                    db.activate_subscription(target_id, days=30)
                else:
                    # Registry mock user
                    db.add_subscriber(target_id, username=None, full_name="عميل مضاف يدويّاً", status='active')
                    db.activate_subscription(target_id, days=30)
                
                # Notify User!
                try:
                    notify_msg = "🎉 <b>تم تفعيل حسابك في بوت NERO FLOW لمدة 30 يوماً!</b>\nيمكنك استخدام البوت الآن والاستفادة من المزايا الحصرية. 🥇\n\n🎉 <b>Your account in NERO FLOW Bot has been activated for 30 days!</b>\nYou can use the bot now and enjoy the features."
                    await context.bot.send_message(chat_id=target_id, text=notify_msg, parse_mode='HTML')
                    user_notified = "تم إرسال إشعار للعميل ✅"
                except Exception as n_err:
                    logger.warning(f"Could not notify user {target_id}: {n_err}")
                    user_notified = "فشل إرسال إشعار (العميل حظر البوت) ⚠️"
                
                context.user_data.pop('admin_action', None)
                keyboard = [[InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="admin_menu")]]
                name_disp = sub['full_name'] if sub else "عميل جديد"
                await update.message.reply_text(
                    f"✅ <b>تم تفعيل وتنشيط العميل بنجاح!</b>\n"
                    f"👤 <b>الاسم | Name:</b> {name_disp}\n"
                    f"🆔 <b>المعرف | User ID:</b> <code>{target_id}</code>\n"
                    f"🕒 <b>المدة | Period:</b> 30 يوم\n"
                    f"📢 <b>حالة الإشعار:</b> {user_notified}",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='HTML'
                 )
                
        elif action == 'custom_extend':
            target_user_id = context.user_data.get('admin_target_user_id')
            if not target_user_id:
                context.user_data.pop('admin_action', None)
                await update.message.reply_text("❌ حدث خطأ: معرف العميل غير موجود.")
                return
                
            try:
                days = int(text)
            except ValueError:
                await update.message.reply_text("❌ يرجى إدخال رقم صحيح فقط (مثال: 15 أو -5):")
                return
                
            # Retrieve current details
            sub = db.get_subscriber(target_user_id)
            if not sub:
                context.user_data.pop('admin_action', None)
                await update.message.reply_text("❌ لم يتم العثور على العضو في قاعدة البيانات.")
                return
                
            base_time = datetime.now()
            
            # Check if there is an active future expiration date
            if sub.get('status') == 'active' and sub.get('expires_at'):
                try:
                    exp_str = sub['expires_at'].replace('Z', '')
                    existing_exp = datetime.fromisoformat(exp_str[:19])
                    if existing_exp > datetime.now():
                        base_time = existing_exp
                except Exception:
                    pass
            
            new_expiry = base_time + timedelta(days=days)
            
            if new_expiry <= datetime.now():
                status = 'expired'
                new_expiry_str = new_expiry.isoformat()
            else:
                status = 'active'
                new_expiry_str = new_expiry.isoformat()
                
            # Update DB directly
            db.conn.execute(
                "UPDATE subscribers SET status = ?, expires_at = ? WHERE user_id = ?",
                (status, new_expiry_str, target_user_id)
            )
            db.conn.commit()
            
            # Clean context
            context.user_data.pop('admin_action', None)
            context.user_data.pop('admin_target_user_id', None)
            
            # Notify User!
            try:
                if days > 0:
                    notify_msg = f"🎉 <b>تم تفعيل وتمديد حسابك في بوت NERO FLOW لمدة {days} يوماً إضافياً!</b>\n\n🎉 <b>Your account in NERO FLOW Bot has been extended for {days} additional days!</b>"
                else:
                    notify_msg = f"⚠️ <b>تم تعديل صلاحية حسابك في بوت NERO FLOW (خصم {abs(days)} يوماً).</b>"
                await context.bot.send_message(chat_id=target_user_id, text=notify_msg, parse_mode='HTML')
                user_notified = "تم إرسال إشعار للعميل ✅"
            except Exception as n_err:
                logger.warning(f"Could not notify user {target_user_id} of custom extension: {n_err}")
                user_notified = "فشل إرسال إشعار ⚠️"
                
            # Retrieve updated subscriber details
            sub = db.get_subscriber(target_user_id)
            username = f"@{sub['username']}" if sub['username'] else "بدون يوزر"
            status_text = "🟢 نشط (Active)" if sub['status'] == 'active' else "🔴 منتهي (Expired)" if sub['status'] == 'expired' else "⚪ غير مشترك"
            expires = sub['expires_at'][:19].replace('T', ' ') if sub['expires_at'] else "N/A"
            reg_date = sub['registered_at'][:19].replace('T', ' ') if sub['registered_at'] else "N/A"
            
            msg = f"""👤 <b>تفاصيل العضو | Member Details</b>
───────────────────────────────────

🆔 <b>المعرف | User ID:</b> <code>{sub['user_id']}</code>
📝 <b>الاسم | Name:</b> {sub['full_name']}
🔗 <b>اليوزر | Username:</b> {username}
🕒 <b>تاريخ التسجيل | Registered:</b> {reg_date}
📊 <b>حالة الاشتراك | Status:</b> {status_text}
📅 <b>ينتهي في | Expires At:</b> {expires}

✅ <b>تم تعديل وتحديث صلاحية الاشتراك بنجاح!</b>
📢 <b>حالة الإشعار:</b> {user_notified}
"""
            keyboard = [
                [
                    InlineKeyboardButton("➕ تمديد 30 يوم", callback_data=f"sub_ext_30_{target_user_id}"),
                    InlineKeyboardButton("⏱️ تمديد 7 أيام", callback_data=f"sub_ext_7_{target_user_id}")
                ],
                [
                    InlineKeyboardButton("⚙️ تمديد مخصص | Custom", callback_data=f"sub_ext_cust_{target_user_id}"),
                    InlineKeyboardButton("❌ إيقاف الاشتراك", callback_data=f"sub_stop_{target_user_id}")
                ],
                [
                    InlineKeyboardButton("🗑️ حذف العضو", callback_data=f"sub_del_{target_user_id}"),
                    InlineKeyboardButton("🔙 رجوع للقائمة | Back", callback_data="admin_members")
                ]
            ]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return
            
        elif action in ['edit_welcome_msg', 'edit_bot_info_msg', 'edit_subscribe_msg']:
            config_key = action.replace('edit_', '')
            config[config_key] = text
            if save_bot_config(config):
                context.user_data.pop('admin_action', None)
                keyboard = [[InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="admin_menu")]]
                await update.message.reply_text(
                    "✅ تم حفظ التعديل بنجاح!\n"
                    "✅ Customization saved successfully!",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text(
                    "❌ حدث خطأ أثناء حفظ الملف.\n"
                    "❌ Error occurred while saving configuration."
                )
                
        elif action == 'waiting_for_manual_recommendation':
            parsed_trade = parse_trade_from_text(text)
            if not parsed_trade:
                await update.message.reply_text(
                    "❌ <b>صيغة التوصية غير صالحة!</b>\n\n"
                    "يرجى التأكد من كتابة التوصية بشكل صحيح وأن تنتهي بالسطر التعريفي للتوصية بهذا الشكل تماماً:\n"
                    "<code>Execution: MARKET | Type: BUY | Entry: 2415.50 | SL: 2405.00 | TP1: 2420.00 | TP2: 2430.00 | TP3: 2445.00</code>\n\n"
                    "✍️ <b>حاول إرسال الرسالة مرة أخرى:</b>",
                    parse_mode='HTML'
                )
                return
            
            context.user_data['manual_rec_text'] = text
            context.user_data['manual_rec_trade'] = parsed_trade
            context.user_data['admin_action'] = None
            
            keyboard = [
                [
                    InlineKeyboardButton("📢 إرسال لجميع المشتركين | Send to All", callback_data="admin_rec_send_all")
                ],
                [
                    InlineKeyboardButton("👥 إرسال لعدد محدد | Send to Specific Count", callback_data="admin_rec_send_limit")
                ],
                [
                    InlineKeyboardButton("🔙 إلغاء وبدء من جديد", callback_data="admin_menu")
                ]
            ]
            await update.message.reply_text(
                "✅ <b>تم التحقق من صيغة التوصية بنجاح!</b>\n\n"
                f"📊 <b>نوع التوصية:</b> {parsed_trade['direction']} XAUUSD\n"
                f"💵 <b>سعر الدخول:</b> ${parsed_trade['entry']:.2f}\n"
                f"🛑 <b>وقف الخسارة:</b> ${parsed_trade['sl']:.2f}\n"
                f"🎯 <b>الأهداف:</b> TP1: {parsed_trade['tp1']:.2f} | TP2: {parsed_trade['tp2'] or 'N/A'} | TP3: {parsed_trade['tp3'] or 'N/A'}\n\n"
                "اختر الفئة المستهدفة لبث التوصية إليها:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            return
            
        elif action == 'waiting_for_rec_limit':
            try:
                limit = int(text)
                if limit <= 0:
                    raise ValueError()
            except ValueError:
                await update.message.reply_text("❌ يرجى إدخال عدد صحيح موجب (مثال: 5 أو 10):")
                return
                
            rec_text = context.user_data.pop('manual_rec_text', None)
            rec_trade = context.user_data.pop('manual_rec_trade', None)
            if not rec_text or not rec_trade:
                context.user_data.pop('admin_action', None)
                await update.message.reply_text("❌ انتهت صلاحية الجلسة أو لا توجد بيانات للتوصية.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")]]))
                return
                
            trades = load_active_trades()
            trades.append(rec_trade)
            save_active_trades(trades)
            
            subscribers = db.get_all_subscribers()
            active_subs = [s for s in subscribers if s['status'] == 'active']
            
            try:
                active_subs.sort(key=lambda s: s.get('registered_at', ''), reverse=True)
            except Exception:
                pass
                
            target_subs = active_subs[:limit]
            
            success_count = 0
            for sub in target_subs:
                try:
                    await context.bot.send_message(chat_id=sub['user_id'], text=rec_text, parse_mode='HTML')
                    success_count += 1
                except Exception as send_err:
                    logger.warning(f"Failed to send manual recommendation to user {sub['user_id']}: {send_err}")
                    
            context.user_data.pop('admin_action', None)
            keyboard = [[InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")]]
            await update.message.reply_text(
                f"✅ <b>تم الإرسال لعدد محدد بنجاح!</b>\n\n"
                f"• تم بث التوصية إلى {success_count} مشترك نششط (من أصل {len(target_subs)} مستهدفين).\n"
                f"• تم إدراج الصفقة بنجاح في قسم <b>التوصيات النشطة</b> لدى جميع المشتركين.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            return
            
        elif action == 'waiting_for_historical_trade':
            import re
            from datetime import datetime
            
            try:
                type_match = re.search(r'Type:\s*(BUY|SELL)', text, re.IGNORECASE)
                entry_match = re.search(r'Entry:\s*([0-9.,]+)', text, re.IGNORECASE)
                sl_match = re.search(r'SL:\s*([0-9.,]+)', text, re.IGNORECASE)
                tp1_match = re.search(r'TP1:\s*([0-9.,]+)', text, re.IGNORECASE)
                tp2_match = re.search(r'TP2:\s*([0-9.,]+)', text, re.IGNORECASE)
                tp3_match = re.search(r'TP3:\s*([0-9.,]+)', text, re.IGNORECASE)
                status_match = re.search(r'Status:\s*(closed|sl_hit|active|tp1_hit|tp2_hit)', text, re.IGNORECASE)
                time_match = re.search(r'Time:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})', text, re.IGNORECASE)
                
                if not (type_match and entry_match and sl_match and tp1_match):
                    await update.message.reply_text(
                        "❌ <b>صيغة غير صالحة!</b>\n"
                        "يجب توفير Type و Entry و SL و TP1 على الأقل.\n"
                        "مثال:\n"
                        "<code>Type: BUY | Entry: 4005.50 | SL: 3998.00 | TP1: 4012.00 | Status: closed</code>",
                        parse_mode='HTML'
                    )
                    return
                
                direction = type_match.group(1).upper()
                entry = float(entry_match.group(1).replace(",", ""))
                sl = float(sl_match.group(1).replace(",", ""))
                tp1 = float(tp1_match.group(1).replace(",", ""))
                tp2 = float(tp2_match.group(1).replace(",", "")) if tp2_match else None
                tp3 = float(tp3_match.group(1).replace(",", "")) if tp3_match else None
                status = status_match.group(1).lower() if status_match else "closed"
                
                time_str = time_match.group(1) if time_match else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                timestamp_iso = time_str.replace(" ", "T") + "Z"
                
                result_pips = 0.0
                close_price = entry
                
                if status == "closed":
                    close_price = tp1
                    result_pips = abs(close_price - entry) * 10
                elif status == "sl_hit":
                    close_price = sl
                    result_pips = -abs(entry - sl) * 10
                    
                db.conn.execute('''
                    INSERT INTO trades (timestamp, direction, entry_price, sl_price, tp1_price, tp2_price, tp3_price, status, result_pips, trade_type, asset, close_price, closed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (timestamp_iso, direction, entry, sl, tp1, tp2, tp3, status, result_pips, "scalp", "XAUUSD", close_price, timestamp_iso))
                db.conn.commit()
                
                context.user_data.pop('admin_action', None)
                keyboard = [[InlineKeyboardButton("🔙 رجوع لوحة الإدارة", callback_data="admin_menu")]]
                await update.message.reply_text(
                    f"✅ <b>تمت إضافة الصفقة التاريخية بنجاح!</b>\n\n"
                    f"📅 <b>التوقيت:</b> <code>{time_str}</code>\n"
                    f"⚙️ <b>النوع:</b> {direction} XAU/USD\n"
                    f"📍 <b>الدخول:</b> ${entry:,.2f}\n"
                    f"🛑 <b>الوقف:</b> ${sl:,.2f}\n"
                    f"🎯 <b>الهدف:</b> ${tp1:,.2f}\n"
                    f"📊 <b>الحالة:</b> <code>{status}</code>\n"
                    f"💸 <b>الربح/الخسارة:</b> {result_pips:+.1f} Pips\n\n"
                    "💡 ستظهر الصفقة الآن مباشرة في التاريخ وإحصائيات الأداء على الموقع الإلكتروني دون إزعاج أو إرسال أي تنبيهات للمستخدمين!",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='HTML'
                )
                return
            except Exception as parse_err:
                await update.message.reply_text(f"❌ حدث خطأ أثناء معالجة وإدخال الصفقة: {parse_err}")
                return
                
    except Exception as e:
        logger.error(f"Error in handle_admin_text_input: {e}", exc_info=True)
        await update.message.reply_text(
            f"⚠️ <b>خطأ المطور | Developer Debug Info:</b>\n<code>{str(e)}</code>",
            parse_mode='HTML'
        )

async def channel_id_helper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Helper to detect channel/group ID when a user forwards a message from their channel/chat to the bot"""
    if not update.message or not update.message.forward_origin:
        return
        
    try:
        origin = update.message.forward_origin
        origin_type = getattr(origin, 'type', None)
        
        if origin_type == "channel":
            chat = getattr(origin, 'chat', None)
            if chat:
                msg = f"""
ℹ️ <b>معلومات القناة المربوطة | Channel Info:</b>
{'─'*35}
📝 <b>الاسم | Name:</b> {chat.title}
🆔 <b>المعرف | ID:</b> <code>{chat.id}</code>

⚙️ <b>كيفية التفعيل | Setup Instructions:</b>
1. انسخ المعرف بالضغط عليه: <code>{chat.id}</code>
2. اذهب إلى لوحة تحكم <b>Railway</b> في تبويب <b>Variables</b>.
3. أضف أو عدل المتغير التالي:
   - <b>KEY:</b> <code>TELEGRAM_CHANNEL_ID</code>
   - <b>VALUE:</b> <code>{chat.id}</code>
4. احفظ المتغيرات (Save) وسيعيد البوت تشغيل نفسه تلقائياً للبث.
"""
                await update.message.reply_text(msg, parse_mode='HTML')
                return
                
        elif origin_type == "chat":
            chat = getattr(origin, 'sender_chat', None)
            if chat:
                msg = f"""
ℹ️ <b>معلومات الدردشة المربوطة | Chat Info:</b>
{'─'*35}
📝 <b>الاسم | Name:</b> {chat.title}
🆔 <b>المعرف | ID:</b> <code>{chat.id}</code>

⚙️ <b>كيفية التفعيل | Setup Instructions:</b>
1. انسخ المعرف بالضغط عليه: <code>{chat.id}</code>
2. اذهب إلى لوحة تحكم <b>Railway</b> في تبويب <b>Variables</b>.
3. أضف أو عدل المتغير التالي:
   - <b>KEY:</b> <code>TELEGRAM_CHANNEL_ID</code>
   - <b>VALUE:</b> <code>{chat.id}</code>
4. احفظ المتغيرات (Save).
"""
                await update.message.reply_text(msg, parse_mode='HTML')
                return
                
        elif origin_type == "user":
            sender = getattr(origin, 'sender_user', None)
            sender_name = sender.first_name if sender else "مستخدم"
            msg = f"""
⚠️ <b>تنبيه التوجيه | Forward Warning:</b>
لقد قمت بإعادة توجيه رسالة مرسلة بواسطة مستخدم (<code>{sender_name}</code>) وليس قناة أو مجموعة.

💡 <b>الحل للحصول على معرف القناة:</b>
1. تأكد من إنشاء <b>قناة (Channel)</b> وليس مجموعة (Group).
2. اكتب أي رسالة داخل <b>القناة</b> ثم قم بإعادة توجيهها هنا للبوت.
"""
            await update.message.reply_text(msg, parse_mode='HTML')
            return
            
    except Exception as e:
        logger.error(f"Error in channel_id_helper: {e}", exc_info=True)

