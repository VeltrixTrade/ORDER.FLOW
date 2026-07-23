import os
from dotenv import load_dotenv

load_dotenv(override=True)

# === DeepSeek AI Configuration ===
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# === Telegram Bot Configuration ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")  # Optional: e.g. @mychannel or -100xxxxxxxxx
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")



# === Twelve Data API Configuration ===
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

# === GoldAPI.io Configuration (Free XAU/USD spot price) ===
GOLDAPI_KEY = os.getenv("GOLDAPI_KEY")


# === Market Settings ===
GOLD_FUTURES_SYMBOL = "GC=F"  # Gold Futures on Yahoo Finance
FOREX_SYMBOL = "XAUUSD"  # Gold/USD forex pair
FOREX_EXCHANGE = "OANDA"  # Exchange for TradingView TA
FOREX_SCREENER = "cfd"  # Screener type for TradingView TA (CFD instead of forex)


# === Supported Timeframes ===
TIMEFRAMES = {
    "4H": {"yf_interval": "1h", "yf_period": "60d", "tv_interval": "4h"},
    "1H": {"yf_interval": "1h", "yf_period": "30d", "tv_interval": "1h"},
    "15M": {"yf_interval": "15m", "yf_period": "5d", "tv_interval": "15m"},
    "Daily": {"yf_interval": "1d", "yf_period": "365d", "tv_interval": "1d"},
    "Weekly": {"yf_interval": "1wk", "yf_period": "730d", "tv_interval": "1W"},
}

# === Trade Settings ===
MIN_RR_RATIO = 3.0  # Minimum Risk:Reward ratio (1:3)
DEFAULT_RISK_PERCENT = 1.0  # Default risk per trade

# === Bot Messages ===
BOT_NAME = "🥇 NERO FLOW Bot | بوت نيرو فلو"
WELCOME_MSG = """مرحباً بك في بوت NERO FLOW ! 🥇
Welcome to the NERO FLOW Bot!

أنا خبير في تحليل XAU/USD باستخدام:
بااستخدام اقوى ادوات السوق 

اختر من القائمة أدناه:
Choose from the menu below:"""
