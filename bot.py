import logging
import sys
import os
import threading
import warnings
import asyncio
from http.server import SimpleHTTPRequestHandler, HTTPServer
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

warnings.filterwarnings("ignore", category=UserWarning)
try:
    from telegram.warnings import PTBUserWarning
    warnings.filterwarnings("ignore", category=PTBUserWarning)
except ImportError:
    pass

from config import TELEGRAM_BOT_TOKEN, BOT_NAME
from handlers.start_handler import start_command, help_command, main_menu_callback, channel_id_helper, signals_command, stats_command, handle_admin_text_input
from handlers.analysis_handler import get_analysis_conversation_handler
from handlers.chat_handler import get_chat_conversation_handler
from handlers.image_handler import get_image_conversation_handler
from handlers.market_handler import market_callback, view_profile_callback


# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)

def main():
    """Main entry point for the bot"""
    logger.info(f"Starting {BOT_NAME}...")


    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing! Please configure it in .env file.")
        sys.exit(1)

    async def run_reports_scheduler(bot):
        """Automatically broadcasts daily & weekly performance reports to the channel at 22:00 Mecca time"""
        import asyncio
        import pytz
        from datetime import datetime
        from trade_db import TradeDB
        from stats_engine import StatsEngine
        from reports import ReportGenerator
        from config import TELEGRAM_CHANNEL_ID
        
        logger.info("Daily/Weekly Performance Report Scheduler started.")
        mecca_tz = pytz.timezone("Asia/Riyadh")
        last_daily_sent_date = None
        last_weekly_sent_date = None
        
        while True:
            try:
                now_mecca = datetime.now(mecca_tz)
                current_date = now_mecca.strftime("%Y-%m-%d")
                
                # Check if it's 22:00 Mecca time (between 22:00 and 22:02)
                if now_mecca.hour == 22 and now_mecca.minute == 0:
                    db = TradeDB()
                    stats = StatsEngine(db)
                    generator = ReportGenerator(stats)
                    
                    # 1. Send Daily Report (only on weekdays: Monday to Friday)
                    if now_mecca.weekday() not in (5, 6): # Skip Saturday (5) and Sunday (6)
                        if last_daily_sent_date != current_date:
                            last_daily_sent_date = current_date
                            report_text = generator.generate_daily_report()
                        logger.info("Automatically broadcasting Daily Performance Report to all active subscribers.")
                        subs = db.get_all_subscribers()
                        for s in subs:
                            if s['status'] == 'active':
                                try:
                                    await bot.send_message(
                                        chat_id=s['user_id'],
                                        text=report_text,
                                        parse_mode='HTML'
                                    )
                                except Exception as e:
                                    logger.warning(f"Failed to send daily report to user {s['user_id']}: {e}")
                            
                    # 2. Send Weekly Report (only on Fridays)
                    if now_mecca.weekday() == 4: # Friday
                        if last_weekly_sent_date != current_date:
                            last_weekly_sent_date = current_date
                            report_text = generator.generate_weekly_report()
                            logger.info("Automatically broadcasting Weekly Performance Report to all active subscribers.")
                            subs = db.get_all_subscribers()
                            for s in subs:
                                if s['status'] == 'active':
                                    try:
                                        await bot.send_message(
                                            chat_id=s['user_id'],
                                            text=report_text,
                                            parse_mode='HTML'
                                        )
                                    except Exception as e:
                                        logger.warning(f"Failed to send weekly report to user {s['user_id']}: {e}")
                                
            except Exception as e:
                logger.error(f"Error in reports scheduler: {e}")
                
            await asyncio.sleep(60) # check every minute
        
    async def post_init(application):
        import asyncio
        from scanner import MarketScanner
        scanner = MarketScanner(application.bot)
        # Store scanner instance in bot_data for manual triggers
        application.bot_data['scanner'] = scanner
        # Scan every 5 minutes (300 seconds)
        asyncio.create_task(scanner.start(scan_interval_seconds=300))
        # Start report scheduler
        asyncio.create_task(run_reports_scheduler(application.bot))
        
        # Start Web API Gateway server linked with main loop and scanner
        loop = asyncio.get_running_loop()
        def run_dashboard():
            from web_dashboard import start_dashboard_server
            port = int(os.getenv("PORT", 8080))
            start_dashboard_server(port, application.bot, loop, scanner)
        threading.Thread(target=run_dashboard, daemon=True).start()
        
        logger.info("Autopilot Market Scanner, report scheduler, and Web API server successfully registered in post_init hook.")


    # Build application
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    
    # Add conversation handlers FIRST (they take priority)
    app.add_handler(get_analysis_conversation_handler())
    app.add_handler(get_chat_conversation_handler())
    app.add_handler(get_image_conversation_handler())

    
    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("signals", signals_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("support", help_command))
    app.add_handler(CommandHandler("market", market_callback))
    
    # Forwarded channel messages helper
    app.add_handler(MessageHandler(filters.FORWARDED, channel_id_helper))
    
    # General text inputs for Admin Panel actions
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text_input))
    
    # Callback handlers for main menu and market
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^(menu|help_menu|toggle_|stats_|backtest_start|signals_menu|create_sig_|admin_|edit_|user_|client_|sub_)"))
    
    app.add_handler(CallbackQueryHandler(market_callback, pattern="^market$"))
    app.add_handler(CallbackQueryHandler(view_profile_callback, pattern="^view_profile$"))
    
    # Error handler
    async def error_handler(update, context):
        logger.error(f"Error handling update {update}: {context.error}", exc_info=context.error)
        if update and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ حدث خطأ داخلي. حاول مرة أخرى.\n❌ An internal error occurred. Please try again."
            )
    
    app.add_error_handler(error_handler)
    
    # Start polling
    logger.info("Bot is running! Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
