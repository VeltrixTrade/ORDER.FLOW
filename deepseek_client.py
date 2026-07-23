import logging
from typing import Dict, List, Optional
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from prompts import SYSTEM_PROMPT, get_analysis_prompt, get_chat_prompt, get_comprehensive_analysis_prompt

logger = logging.getLogger(__name__)

class DeepSeekClient:
    """Client for DeepSeek AI API (OpenAI-compatible interface)"""

    def __init__(self):
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        self.model = DEEPSEEK_MODEL

    def analyze_market_comprehensive(self, market_data: Dict, order_flow_state: Dict) -> str:
        """
        Send market data and Order Flow state to DeepSeek for comprehensive multi-timeframe analysis (no setups/targets).
        """
        try:
            prompt = get_comprehensive_analysis_prompt(market_data, order_flow_state)
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=1500,
                )
                return self._clean_response(response.choices[0].message.content)
            except Exception as ds_err:
                logger.warning(f"DeepSeek analyze_market_comprehensive failed, falling back to Gemini: {ds_err}")
                from gemini_client import GeminiClient
                gemini = GeminiClient()
                return gemini.chat(prompt, system_instruction=SYSTEM_PROMPT)

        except Exception as e:
            logger.error(f"DeepSeek analyze_market_comprehensive error: {e}")
            return (
                f"❌ <b>خطأ في الاتصال بـ AI | AI Connection Error</b>\n\n"
                f"<code>{str(e)}</code>\n\n"
            )

    def analyze_market(self, market_data: Dict, order_flow_state: Dict, trade_type: str) -> str:
        """
        Send market data and Order Flow state to DeepSeek for professional trade setup generation.
        market_data: full market summary (price + multi-TF TradingView + session)
        order_flow_state: computed Order Flow state dict
        trade_type: 'scalp' | 'swing'
        """
        try:
            prompt = get_analysis_prompt(market_data, order_flow_state, trade_type)
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    temperature=0.25,  # Lower = more deterministic & precise analysis
                    max_tokens=1500,
                )
                return self._clean_response(response.choices[0].message.content)
            except Exception as ds_err:
                logger.warning(f"DeepSeek analyze_market failed, falling back to Gemini: {ds_err}")
                from gemini_client import GeminiClient
                gemini = GeminiClient()
                return gemini.chat(prompt, system_instruction=SYSTEM_PROMPT)

        except Exception as e:
            logger.error(f"DeepSeek analyze_market error: {e}")
            return (
                f"❌ <b>خطأ في الاتصال بـ AI | AI Connection Error</b>\n\n"
                f"<code>{str(e)}</code>\n\n"
                "تحقق من مفتاح API الخاص بك وحاول مرة أخرى.\n"
                "Check your API key and try again."
            )

    def analyze_chart_images(self, images_base64: List[str], trade_type: str) -> str:
        """
        Analyze chart images using DeepSeek vision (if model supports it).
        images_base64: list of base64-encoded chart images.
        """
        try:
            content = []
            for i, img_b64 in enumerate(images_base64[:3]):  # max 3 images
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                })
            content.append({
                "type": "text",
                "text": (
                    f"These are XAU/USD chart screenshots for Order Flow and Volume Profile {trade_type} analysis. "
                    "Identify VAH, VAL, POC, VWAP, CVD, imbalances, absorption, and provide a trade setup "
                    "with exact Entry, Stop Loss, TP1, TP2. Minimum RR 1:3. "
                    "Respond in Arabic and English."
                ),
            })

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": content},
                ],
                temperature=0.3,
                max_tokens=4096,
            )
            return self._clean_response(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"DeepSeek chart image analysis error: {e}")
            return (
                f"❌ <b>خطأ في تحليل الصور | Image Analysis Error</b>\n\n"
                f"<code>{str(e)}</code>"
            )

    def chat(self, message: str, history: List[Dict] = None) -> str:
        """Free-form chat with the NERO FLOW AI expert."""
        try:
            live_price = None
            try:
                from trade_db import TradeDB
                db = TradeDB()
                lp = db.get_live_price("XAUUSD")
                if lp:
                    live_price = float(lp['bid'])
            except Exception:
                pass

            active_trades = []
            try:
                from scanner import MarketScanner
                temp_scanner = MarketScanner(None)
                active_trades = temp_scanner.load_active_trades()
            except Exception:
                pass

            closed_trades = []
            try:
                from trade_db import TradeDB
                db = TradeDB()
                closed_trades = db.get_all_closed_trades()[:10]
            except Exception:
                pass

            sys_prompt = get_chat_prompt(live_price, active_trades, closed_trades)

            # Try DeepSeek first
            try:
                messages = [{"role": "system", "content": sys_prompt}]
                if history:
                    for msg in history[-12:]:  # keep last 12 turns for context
                        messages.append(msg)
                messages.append({"role": "user", "content": message})

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.65,
                    max_tokens=2048,
                )
                return self._clean_response(response.choices[0].message.content)
            except Exception as ds_err:
                logger.warning(f"DeepSeek chat failed, falling back to Gemini: {ds_err}")
                from gemini_client import GeminiClient
                gemini = GeminiClient()
                return gemini.chat(message, history, system_instruction=sys_prompt)

        except Exception as e:
            logger.error(f"DeepSeek chat error: {e}")
            return (
                f"❌ <b>خطأ | Error</b>\n\n"
                f"<code>{str(e)}</code>"
            )

    def _clean_response(self, text: str) -> str:
        """Converts markdown bold/headers/italic to clean Telegram-compatible HTML tags."""
        if not text:
            return text
        import re
        # Convert markdown bold **text** to HTML bold <b>text</b>
        cleaned = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        # Convert markdown italic *text* to HTML italic <i>text</i>
        cleaned = re.sub(r'\*(.*?)\*', r'<i>\1</i>', cleaned)
        # Convert markdown headers like ### text to HTML bold <b>text</b>
        cleaned = re.sub(r'#+\s*(.*?)\n', r'<b>\1</b>\n', cleaned)
        # Remove any residual/standalone asterisks or markdown code blocks
        cleaned = cleaned.replace("`", "")
        return cleaned.strip()
