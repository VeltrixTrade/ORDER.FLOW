import logging
import requests
import base64
from typing import List, Dict, Optional
from config import GEMINI_API_KEY
from prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

class GeminiClient:
    """Client for Google Gemini Multimodal API"""
    
    def __init__(self):
        self.api_key = GEMINI_API_KEY
        # Use gemini-1.5-flash which is fast and supports high-quality vision/image input
        self.url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={self.api_key}" if self.api_key else ""
        
    def analyze_chart_images(self, images_base64: List[str], trade_type: str, market_summary: Dict) -> str:
        """Send base64 images and current market data to Gemini for analysis"""
        if not self.api_key:
            return "❌ <b>خطأ في الإعداد | Config Error</b>\n\nلم يتم العثور على مفتاح <code>GEMINI_API_KEY</code>. يرجى إضافته إلى ملف <code>.env</code>."
            
        try:
            # Combine image analysis prompt with market summary
            price_info = market_summary.get('price', {})
            current_price = price_info.get('price', 'N/A')
            dxy_status = price_info.get('dxy', {})
            dxy_trend = dxy_status.get('trend', 'Neutral ↔️')
            
            prompt_text = f"""
{SYSTEM_PROMPT}

=== CURRENT LIVE DATA CONTEXT ===
- Live Spot Price: ${current_price}
- Average Daily Range (ADR): ${price_info.get('adr', 'N/A')}
- DXY Trend: {dxy_trend} (Price change: {dxy_status.get('change', '0.0')}%)
- Active Session: {market_summary.get('session', {}).get('session', 'N/A')}

=== YOUR TASK ===
The user has uploaded one or more screenshots of the XAU/USD gold chart.
1. Analyze the chart visually. Identify the volume profile distribution, key POC, and Value Area (VAH/VAL) boundaries.
2. Locate key volume imbalances, absorption tails, or rejection zones visible in the image.
3. Align this with the current live spot price (${current_price}).
4. Determine the trade setup (BUY/SELL) for a {trade_type} trade with a minimum 1:3 RR ratio.
5. Output the result in both Arabic and English using the exact format from the system prompt instructions.
"""
            # Construct the parts payload
            parts = [{"text": prompt_text}]
            
            for img_b64 in images_base64[:3]: # Max 3 images
                parts.append({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": img_b64
                    }
                })
                
            payload = {
                "contents": [
                    {
                        "parts": parts
                    }
                ],
                "generationConfig": {
                    "temperature": 0.25,
                    "maxOutputTokens": 4096
                }
            }
            
            headers = {
                "Content-Type": "application/json"
            }
            
            logger.info("Sending request to Gemini API for chart image analysis...")
            response = requests.post(self.url, json=payload, headers=headers, timeout=45)
            
            if response.status_code == 200:
                data = response.json()
                try:
                    text_out = data['candidates'][0]['content']['parts'][0]['text']
                    return text_out
                except (KeyError, IndexError) as parse_err:
                    logger.error(f"Error parsing Gemini response: {parse_err}. Response data: {data}")
                    return "❌ حدث خطأ في معالجة إجابة جيمناي."
            else:
                logger.error(f"Gemini API returned status code {response.status_code}: {response.text}")
                return f"❌ خطأ من سيرفر جيمناي (كود {response.status_code}): {response.text}"
                
        except Exception as e:
            logger.error(f"Gemini Client error: {e}", exc_info=True)
            return f"❌ حدث خطأ غير متوقع أثناء تحليل الصور: {str(e)}"

    def chat(self, message: str, history: List[Dict] = None, system_instruction: str = "") -> str:
        """Text-based chat with Gemini, compatible with DeepSeekClient format"""
        if not self.api_key:
            return "❌ <b>خطأ في الإعداد | Config Error</b>\n\nلم يتم العثور على مفتاح <code>GEMINI_API_KEY</code>."
            
        try:
            contents = []
            if history:
                for msg in history[-12:]:
                    role = "user" if msg.get("role") == "user" else "model"
                    contents.append({
                        "role": role,
                        "parts": [{"text": msg.get("content", "")}]
                    })
            contents.append({
                "role": "user",
                "parts": [{"text": message}]
            })
            
            payload = {
                "contents": contents,
                "generationConfig": {
                    "temperature": 0.45,
                    "maxOutputTokens": 2048
                }
            }
            if system_instruction:
                payload["systemInstruction"] = {
                    "parts": {"text": system_instruction}
                }
                
            headers = {
                "Content-Type": "application/json"
            }
            
            response = requests.post(self.url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                try:
                    text_out = data['candidates'][0]['content']['parts'][0]['text']
                    return self._clean_response(text_out)
                except (KeyError, IndexError) as parse_err:
                    logger.error(f"Error parsing Gemini chat response: {parse_err}. Data: {data}")
                    raise Exception("Invalid Gemini chat response structure")
            else:
                logger.error(f"Gemini Chat API returned status code {response.status_code}: {response.text}")
                raise Exception(f"Gemini Chat API error status {response.status_code}")
                
        except Exception as e:
            logger.error(f"Gemini chat method error: {e}")
            raise e

    def _clean_response(self, text: str) -> str:
        """Converts markdown bold/headers/italic to clean Telegram-compatible HTML tags."""
        if not text:
            return text
        import re
        cleaned = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        cleaned = re.sub(r'\*(.*?)\*', r'<i>\1</i>', cleaned)
        cleaned = re.sub(r'#+\s*(.*?)\n', r'<b>\1</b>\n', cleaned)
        cleaned = cleaned.replace("`", "")
        return cleaned.strip()

