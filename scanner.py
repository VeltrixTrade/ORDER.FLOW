import logging
import asyncio
import re
import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any

from market_data import MarketData
from config import TELEGRAM_CHANNEL_ID
from trade_db import TradeDB
from news_calendar import NewsCalendar

logger = logging.getLogger(__name__)

def is_autopilot_enabled() -> bool:
    """Check if the autopilot scanner is enabled by the user"""
    try:
        db_path = os.getenv("DATABASE_PATH", "trades.db")
        db_dir = os.path.dirname(os.path.abspath(db_path))
        status_file = os.path.join(db_dir, "autopilot_status.txt")
        if not os.path.exists(status_file):
            return True
        with open(status_file, "r") as f:
            status = f.read().strip()
            return status == "ON"
    except Exception:
        return True

def set_autopilot_status(enabled: bool):
    """Set the autopilot status to ON or OFF"""
    try:
        db_path = os.getenv("DATABASE_PATH", "trades.db")
        db_dir = os.path.dirname(os.path.abspath(db_path))
        status_file = os.path.join(db_dir, "autopilot_status.txt")
        with open(status_file, "w") as f:
            f.write("ON" if enabled else "OFF")
    except Exception as e:
        logger.error(f"Failed to set autopilot status: {e}")

class MarketScanner:
    """Automated market scanner that monitors active trades and broadcasts Order Flow signals in real-time"""

    def __init__(self, bot):
        self.bot = bot
        self.market_data = MarketData()
        self.db = TradeDB()
        self.news_calendar = NewsCalendar()
        self.sent_signals = [] 
        self.is_running = False
        
        # Save active trades file in the same directory as the database to persist on Railway volumes
        db_dir = os.path.dirname(os.path.abspath(self.db.db_path))
        self.trades_file = os.path.join(db_dir, "active_trades.json")
        
        self.lock = asyncio.Lock()

    async def start(self, scan_interval_seconds: int = 300):
        """Start the background high-frequency active trade monitor loop (ticking every 60 seconds)"""
        if self.is_running:
            logger.warning("Scanner monitor loop is already running.")
            return
        
        self.is_running = True
        logger.info("Order Flow Active Trade Monitor loop started. Tick interval: 60s.")
        
        # Give the bot a moment to fully initialize
        await asyncio.sleep(10)
        
        last_scan_time = 0
        
        while self.is_running:
            try:
                # 1. High-Frequency Active Trade Monitor (Runs every 60 seconds)
                await self.monitor_active_trades()
                
                # 2. Autopilot Market Scanner (Runs every scan_interval_seconds)
                import time
                current_time = time.time()
                if current_time - last_scan_time >= scan_interval_seconds:
                    last_scan_time = current_time
                    
                    if is_autopilot_enabled():
                        await self.run_autopilot_scan()
            except Exception as e:
                logger.error(f"Error in active trade monitor loop: {e}", exc_info=True)
                
            await asyncio.sleep(60)

    async def run_autopilot_scan(self):
        """Runs the automatic market scan and broadcasts signals if confluences are met."""
        try:
            # Check if weekend (Saturday or Sunday) in Riyadh/Mecca time
            import datetime as dt
            import pytz
            mecca_tz = pytz.timezone("Asia/Riyadh")
            now_mecca = dt.datetime.now(mecca_tz)
            if now_mecca.weekday() in (5, 6): # Skip Saturday (5) and Sunday (6)
                logger.info("Autopilot Scanner: Weekend. Skipping market scan.")
                return

            # Gather live market data summary
            market_summary = self.market_data.get_market_summary()
            
            # Get live Order Flow state from the tracker
            from engine.parser import order_flow_tracker
            state = await order_flow_tracker.get_state()
            
            # Fetch recent candles to get last M5 closed candle
            candles = self.db.get_candles("XAUUSD", "M5", limit=2)
            if not candles:
                logger.warning("Autopilot Scanner: No candles found in database to evaluate.")
                return
                
            c = candles[1] if len(candles) >= 2 else candles[0]
            ohlc = {
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": int(c.get("volume") or 0),
                "delta": float(c.get("delta") or 0.0)
            }
            
            from engine.rules import evaluate_rules
            # Run rules engine check
            signal_data = evaluate_rules(state, ohlc, volume_sma_10=100, verbose_callback=self.handle_signal_rejection)
            if signal_data:
                logger.info(f"Autopilot Scanner: Rule-based signal found: {signal_data['type']}. Broadcasting...")
                # Broadcast and log trade
                # We need to map category for broadcast
                signal_data["category"] = "scalp"
                await self.broadcast_order_flow_signal(signal_data)
            else:
                logger.info("Autopilot Scanner: No setup found matching the criteria.")
        except Exception as e:
            logger.error(f"Error in run_autopilot_scan: {e}", exc_info=True)

    def stop(self):
        self.is_running = False
        logger.info("Active Trade Monitor stopped.")

    async def scan_and_signal(self, trade_type: str, force: bool = False) -> tuple[bool, Any]:
        """
        Scan market data and evaluate order flow setups.
        If force=True, calls DeepSeek AI to analyze live market conditions and returns a trade setup or message.
        """
        try:
            # 1. Gather live market data summary
            market_summary = self.market_data.get_market_summary()
            
            # 2. Get live Order Flow state from the tracker
            from engine.parser import order_flow_tracker
            state = await order_flow_tracker.get_state()
            
            val = state.get("val", 0.0)
            vah = state.get("vah", 0.0)
            poc = state.get("poc", 0.0)
            vwap = state.get("vwap", 0.0)
            cvd = state.get("cvd", 0)
            std_dev = state.get("std_dev", 0.0)
            live_footprint = state.get("live_footprint", {})
            
            from engine.footprint import FootprintAnalysis
            analyzer = FootprintAnalysis(live_footprint)
            ask_imb, bid_imb = analyzer.get_diagonal_imbalances()
            stacked_ask, stacked_bid = analyzer.get_stacked_imbalances(ask_imb, bid_imb)
            
            order_flow_state = {
                "val": val,
                "vah": vah,
                "poc": poc,
                "vwap": vwap,
                "cvd": cvd,
                "std_dev": std_dev,
                "stacked_ask_levels": stacked_ask,
                "stacked_bid_levels": stacked_bid
            }
            
            if force:
                # Force=True (Manual trigger from admin menu) -> Call DeepSeek AI
                from deepseek_client import DeepSeekClient
                ai = DeepSeekClient()
                
                logger.info(f"Calling DeepSeek AI to analyze market for {trade_type} manually...")
                ai_analysis = ai.analyze_market(market_summary, order_flow_state, trade_type)
                
                # Parse the AI response to extract trade parameters
                parsed_trade = self._parse_trade_from_text(ai_analysis)
                if parsed_trade:
                    parsed_trade["category"] = trade_type
                    return True, {"msg": ai_analysis, "trade": parsed_trade}
                else:
                    return False, f"DeepSeek returned analysis but no trade setup structure was found in the text: \n\n{ai_analysis}"
            
            else:
                # Force=False (Automatic check) -> Run rules engine first
                from engine.rules import evaluate_rules
                
                # Fetch recent candles to get last M5 closed candle
                candles = self.db.get_candles("XAUUSD", "M5", limit=2)
                if not candles:
                    return False, "No candles found in database to evaluate rules."
                    
                c = candles[1] if len(candles) >= 2 else candles[0]
                ohlc = {
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                    "volume": int(c.get("volume") or 0),
                    "delta": float(c.get("delta") or 0.0)
                }
                
                # Dry run rule evaluation
                signal_data = evaluate_rules(state, ohlc, volume_sma_10=100, verbose_callback=self.handle_signal_rejection) # lower volume threshold for custom scan
                if signal_data:
                    # Map to trade structure
                    parsed_trade = {
                        "direction": signal_data["type"],
                        "entry": signal_data["entry_price"],
                        "sl": signal_data["stop_loss"],
                        "tp1": signal_data["take_profit_1"],
                        "tp2": signal_data["take_profit_2"],
                        "tp3": signal_data.get("take_profit_3"),
                        "status": "pending"
                    }
                    
                    # Generate formatted signal text
                    dir_emoji = "🟢" if signal_data['type'] == 'BUY' else "🔴"
                    dir_name_ar = "شراء" if signal_data['type'] == 'BUY' else "بيع"
                    
                    msg_text = f"""
<b>🟢 إشارة تداول فورية | XAU/USD Market Execution</b>
<b>⚙️ النوع | Type:</b> {signal_data['type']} (تنفيذ فوري)
<b>📍 الدخول | Entry:</b> ${signal_data['entry_price']:.2f}
<b>🛑 وقف الخسارة | SL:</b> ${signal_data['stop_loss']:.2f}
<b>🎯 الهدف 1 | TP1:</b> ${signal_data['take_profit_1']:.2f}
<b>🎯 الهدف 2 | TP2:</b> ${signal_data['take_profit_2']:.2f}
<b>🎯 الهدف 3 | TP3:</b> ${signal_data.get('take_profit_3', 0.0):.2f}
<b>⚖️ مخاطرة/عائد | RR:</b> 1:3.0
<b>📊 القوة | Score:</b> {signal_data['confidence']:.0f}/100

📝 <b>الأسباب الفنية | Order Flow Confluences:</b>
• تركز سيولة عند الـ POC بسعر ${signal_data['metrics_snapshot']['poc']:.2f}
• امتصاص سعري (Absorption) عند حدود الـ VAL/VAH بسعر ${signal_data['metrics_snapshot']['val']:.2f}/${signal_data['metrics_snapshot']['vah']:.2f}
• ضغط سيولة تراكمي (CVD) بمقدار {signal_data['metrics_snapshot']['cvd']:+d} عقود
"""
                    return True, {"msg": msg_text, "trade": parsed_trade}
                else:
                    return False, "No Order Flow setup matches the rule criteria currently."
                    
        except Exception as e:
            logger.error(f"Error in scan_and_signal: {e}", exc_info=True)
            return False, str(e)

    def _parse_trade_from_text(self, text: str) -> Optional[Dict]:
        """Helper to extract direction, entry, sl, tp1, tp2 from AI text response"""
        try:
            # Clean HTML tags first to avoid parsing interference
            clean_text = re.sub(r'<[^>]*>', '', text)
            
            # 1. Search for Type/Direction (BUY or SELL)
            type_match = re.search(r'Type:\s*(BUY|SELL|BUY LIMIT|SELL LIMIT)', clean_text, re.IGNORECASE)
            if not type_match:
                # search for BUY or SELL in general text
                if "buy" in clean_text.lower():
                    direction = "BUY"
                elif "sell" in clean_text.lower():
                    direction = "SELL"
                else:
                    return None
            else:
                direction = "BUY" if "buy" in type_match.group(1).upper() else "SELL"
                
            # 2. Extract values using regex
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
            
            # Math-based direction correction to eliminate AI typos
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
                "status": "pending" if execution == "PENDING" else "active"
            }
        except Exception as e:
            logger.error(f"Failed to parse trade from text: {e}")
            return None

    def handle_signal_rejection(
        self,
        signal_type: str,
        price_near_boundary: bool,
        volume_confirmed: bool,
        stacked_imbalance: bool,
        absorption: bool,
        reason: str,
        metrics_snapshot: Optional[Dict] = None
    ):
        """Logs a rejected signal in the SQLite DB and alerts the admin chat."""
        # Enrich metrics_snapshot with delta, volume, and EMAs
        if metrics_snapshot is None:
            metrics_snapshot = {}
        else:
            metrics_snapshot = dict(metrics_snapshot)
            
        try:
            candles = self.db.get_candles("XAUUSD", "M5", limit=1)
            if candles:
                c = candles[0]
                metrics_snapshot["volume"] = int(c.get("volume") or 0)
                metrics_snapshot["delta"] = float(c.get("delta") or 0.0)
            else:
                metrics_snapshot["volume"] = 0
                metrics_snapshot["delta"] = 0.0

            from engine.rules import get_all_emas
            ema10, ema34, ema50 = get_all_emas(self.db, "M5")
            metrics_snapshot["ema10"] = ema10
            metrics_snapshot["ema34"] = ema34
            metrics_snapshot["ema50"] = ema50
        except Exception as e:
            logger.error(f"Failed to enrich metrics_snapshot in handle_signal_rejection: {e}")

        # 1. Log to DB
        import json
        metrics_json = json.dumps(metrics_snapshot)
        try:
            self.db.log_rejected_signal(
                signal_type=signal_type,
                price_near_boundary=price_near_boundary,
                volume_confirmed=volume_confirmed,
                stacked_imbalance=stacked_imbalance,
                absorption=absorption,
                reason=reason,
                metrics_snapshot=metrics_json
            )
        except Exception as db_err:
            logger.error(f"Failed to log signal rejection in DB: {db_err}")
            

    async def broadcast_to_active_subscribers(self, text: str, reply_markup=None):
        """Send message to all registered active subscribers directly."""
        subs = self.db.get_all_subscribers()
        sent_count = 0
        for s in subs:
            if s['status'] == 'active' and s.get('trading_mode', 'OFF') == 'ON':
                try:
                    await self.bot.send_message(
                        chat_id=s['user_id'],
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode='HTML'
                    )
                    sent_count += 1
                except Exception as e:
                    if "can't parse entities" in str(e).lower():
                        clean_text = re.sub(r'<[^>]*>', '', text)
                        try:
                            await self.bot.send_message(
                                chat_id=s['user_id'],
                                text=clean_text,
                                reply_markup=reply_markup
                            )
                            sent_count += 1
                        except Exception as e2:
                            logger.warning(f"Failed to send plain text fallback to user {s['user_id']}: {e2}")
                    else:
                        logger.warning(f"Failed to send broadcast to user {s['user_id']}: {e}")
        logger.info(f"Broadcasted message to {sent_count} active subscribers.")
        return sent_count

    async def broadcast_order_flow_signal(self, signal: Dict[str, Any]):
        """Formats and broadcasts a custom Order Flow signal and journals it in SQLite"""
        try:
            # 1. Check if autopilot toggle is on
            if not is_autopilot_enabled():
                logger.info("Autopilot toggle is OFF. Skipping signal broadcast.")
                return

            # 2. Prevent conflicting active trades (No opposite trades allowed)
            active_trades = self.load_active_trades()
            
            # Cooldown check: prevent another automated signal if one was triggered within the last 4 minutes
            from datetime import datetime, timedelta
            for active_t in active_trades:
                if active_t.get('source') == 'rules':
                    try:
                        trade_time = datetime.fromisoformat(active_t['timestamp'])
                        if datetime.now() - trade_time < timedelta(minutes=4):
                            logger.info("Skipping signal - Cooldown active (last signal triggered < 4 minutes ago)")
                            return
                    except Exception:
                        pass

            # Duplicate check: prevent trade if already active/pending in same direction at similar price
            for active_t in active_trades:
                if active_t['direction'] == signal['type'] and abs(active_t['entry'] - signal['entry_price']) < 0.10:
                    logger.info(f"Skipping signal - Duplicate active trade already running at price {signal['entry_price']}")
                    return

            for active_t in active_trades:
                if active_t['direction'] != signal['type']:
                    logger.info(f"Skipping signal - Active conflicting trade already running ({active_t['direction']})")
                    return

            # 2b. Enforce limit of maximum 1 active trade for the automated system (System Rules)
            # Admin trades and AI Chatbot trades are managed independently (1 max each)
            source_type = signal.get('source', 'rules')
            active_for_source = sum(1 for t in active_trades if t.get('source', 'rules') == source_type and t.get('status') in ['active', 'pending'])
            if active_for_source >= 1:
                logger.info(f"Skipping signal - Source '{source_type}' already has 1 active/pending trade ({active_for_source}). Must wait for TP/SL hit.")
                return

            # 3. Format bilingual (Arabic + English) message
            dir_emoji = "🟢" if signal['type'] == 'BUY' else "🔴"
            dir_name_ar = "شراء" if signal['type'] == 'BUY' else "بيع"
            
            reasons_list = signal.get('reasons', [])
            reasons_formatted = "\n".join([f"• {r}" for r in reasons_list]) if reasons_list else "• الشروط الفنية مستوفاة بالكامل"
            strategy_name = signal.get('strategy', 'Trend Continuation')
            
            final_msg = f"""
⚡ <b>تنبيه صفقة تداول الذهب | XAU/USD Trade Signal</b>
{'═'*35}

🤖 <b>الاستراتيجية | Strategy:</b> {strategy_name}
📊 <b>الزوج | Pair:</b> XAU/USD (الذهب)
⏰ <b>النوع | Type:</b> {signal['category'].upper()}
📍 <b>الاتجاه | Direction:</b> {dir_emoji} {signal['type']} | {dir_name_ar}

🎯 <b>نقطة الدخول | Entry:</b> ${signal['entry_price']:,.2f}
🛑 <b>وقف الخسارة | Stop Loss:</b> ${signal['stop_loss']:,.2f}
✅ <b>الهدف الأول | TP1:</b> ${signal['take_profit_1']:,.2f}
✅ <b>الهدف الثاني | TP2:</b> ${signal['take_profit_2']:,.2f}
✅ <b>الهدف الثالث | TP3:</b> ${signal.get('take_profit_3', 0.0):,.2f}

⚖️ <b>نسبة النجاح المتوقعة | Win Prob:</b> {signal['confidence']:.0f}%

🎯 <b>أسباب الدخول الفنية | Entry Triggers:</b>
{reasons_formatted}

📈 <b>مستويات المتوسطات المتحركة | Moving Average Levels:</b>
• EMA 10: $${signal['metrics_snapshot'].get('ema10', 0.0):.2f}
• EMA 34: $${signal['metrics_snapshot'].get('ema34', 0.0):.2f}
• EMA 50: $${signal['metrics_snapshot'].get('ema50', 0.0):.2f}

{'─'*35}
⚠️ <i>تنويه: تحليل تلقائي للذهب. يرجى استخدام إدارة مخاطر صارمة.</i>
"""
            # 4. Broadcast to subscribers (Skipped for Test Mode signals)
            if signal.get("is_test"):
                logger.info("🧪 Test trade signal generated from dashboard. Skipping public broadcast to subscribers.")
            else:
                logger.info(f"📢 Broadcasting {strategy_name} Signal: {signal['type']} @ {signal['entry_price']}")
                await self.broadcast_to_active_subscribers(text=final_msg)


            # 6. Log trade in SQLite DB
            db_id = None
            try:
                db_id = self.db.log_trade(
                    direction=signal['type'],
                    entry=signal['entry_price'],
                    sl=signal['stop_loss'],
                    tp1=signal['take_profit_1'],
                    tp2=signal['take_profit_2'],
                    tp3=signal.get('take_profit_3'),
                    trade_type=signal['category'],
                    asset='XAUUSD',
                    strategy=strategy_name,
                    confluences=" | ".join(reasons_list)
                )
            except Exception as db_err:
                logger.error(f"Failed to log trade in SQLite: {db_err}")

            # 7. Register trade in the Active Monitor list
            setup = {
                'direction': signal['type'],
                'entry': signal['entry_price'],
                'sl': signal['stop_loss'],
                'tp1': signal['take_profit_1'],
                'tp2': signal['take_profit_2'],
                'tp3': signal.get('take_profit_3'),
                'is_pending': False,
                'status': 'active',
                'db_id': db_id,
                'timestamp': datetime.now().isoformat(),
                'source': 'rules',
                'strategy': strategy_name,
                'confluences': " | ".join(reasons_list)
            }
            active_trades.append(setup)
            self.save_active_trades(active_trades)

        except Exception as e:
            logger.error(f"Error broadcasting order flow signal: {e}", exc_info=True)

    def load_active_trades(self) -> List[Dict]:
        """Load running trades from persistent storage"""
        try:
            if not os.path.exists(self.trades_file):
                return []
            with open(self.trades_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load active trades: {e}")
            return []

    def save_active_trades(self, trades: List[Dict]):
        """Save running trades to persistent storage"""
        try:
            with open(self.trades_file, "w") as f:
                json.dump(trades, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save active trades: {e}")

    async def monitor_active_trades(self, current_price: Optional[float] = None):
        """Check live XAU/USD price and manage active/pending trades"""
        if self.lock.locked():
            return

        async with self.lock:
            trades = self.load_active_trades()
            if not trades:
                return
                
            if current_price is None:
                try:
                    lp = self.db.get_live_price("XAUUSD")
                    if lp:
                        current_price = float(lp['bid'])
                    else:
                        candles = self.db.get_candles("XAUUSD", "M1", limit=1)
                        if candles:
                            current_price = float(candles[0]['close'])
                except Exception as db_err:
                    logger.error(f"Failed to fetch current price from DB for monitoring: {db_err}")

            if not current_price or current_price == 0:
                return
                
            updated_trades = []
            changed = False
            
            for trade in trades:
                trade_id = trade.get('timestamp')
                direction = trade['direction']
                entry = trade['entry']
                sl = trade['sl']
                tp1 = trade['tp1']
                tp2 = trade.get('tp2')
                tp3 = trade.get('tp3')
                status = trade.get('status', 'active')
                db_id = trade.get('db_id')
                
                # 1. Handle Pending orders activation
                if status == 'pending':
                    activated = False
                    if direction == 'BUY' and current_price <= entry:
                        activated = True
                    elif direction == 'SELL' and current_price >= entry:
                        activated = True
                        
                    if activated:
                        status = 'active'
                        trade['status'] = status
                        changed = True
                        logger.info(f"🟢 Pending {direction} activated at {current_price} (Entry: {entry})")
                        if db_id:
                            self.db.update_trade_status(db_id, 'active')
                        await self.broadcast_to_active_subscribers(
                            text=f"🟢 <b>تفعيل صفقة {direction} معلقة | Pending {direction} Activated!</b>\n"
                                 f"{'═'*35}\n\n"
                                 f"⚙️ <b>النوع | Type:</b> {direction}\n"
                                 f"🎯 <b>سعر الدخول | Entry:</b> ${entry:,.2f}\n"
                                 f"🛑 <b>وقف الخسارة | SL:</b> ${sl:,.2f}\n"
                                 f"✅ <b>الهدف الأول | TP1:</b> ${tp1:,.2f}"
                        )
                    else:
                        updated_trades.append(trade)
                        continue

                # 2. Check targets / Stop Loss hits
                # Stop Loss Check (Applies to all active/partial target hit statuses since SL is fixed)
                if status in ['active', 'tp1_hit', 'tp2_hit']:
                    if (direction == 'BUY' and current_price <= sl) or (direction == 'SELL' and current_price >= sl):
                        status = 'sl_hit'
                        changed = True
                        logger.info(f"🔴 Stop Loss Hit for {direction} @ {entry}. Current: {current_price}")
                        if db_id:
                            self.db.update_trade_status(db_id, 'sl_hit', result_pips=-abs(entry-sl)*10, close_price=sl)
                        
                        await self.broadcast_to_active_subscribers(
                            text=f"🔴 <b>ضرب وقف الخسارة | SL Hit!</b>\n"
                                 f"{'═'*35}\n\n"
                                 f"⚙️ <b>النوع | Type:</b> {direction}\n"
                                 f"🎯 <b>سعر الدخول | Entry:</b> ${entry:,.2f}\n"
                                 f"🛑 <b>السعر الحالي | Closed At:</b> ${current_price:,.2f}\n"
                                 f"💸 <b>النتيجة | Loss:</b> -{abs(entry-sl)*10:.1f} نقطة (Pips)"
                        )
                        continue # Closes/Removes trade

                # Target Hits Check
                if status == 'active':
                    # Check Target 1
                    if (direction == 'BUY' and current_price >= tp1) or (direction == 'SELL' and current_price <= tp1):
                        status = 'tp1_hit'
                        trade['status'] = status
                        changed = True
                        logger.info(f"🥇 Target 1 Hit for {direction} @ {entry}. Current: {current_price}")
                        if db_id:
                            self.db.update_trade_status(db_id, 'tp1_hit', result_pips=abs(entry-tp1)*10, close_price=tp1)
                        
                        await self.broadcast_to_active_subscribers(
                            text=f"🥇 <b>تحقق الهدف الأول | Target 1 Hit!</b>\n"
                                 f"{'═'*35}\n\n"
                                 f"⚙️ <b>النوع | Type:</b> {direction}\n"
                                 f"🎯 <b>سعر الدخول | Entry:</b> ${entry:,.2f}\n"
                                 f"✅ <b>الهدف الأول | TP1:</b> ${tp1:,.2f}\n"
                                 f"💰 <b>جني الأرباح الجزئية | Partial Profit:</b> جني 25% من الأرباح (+{abs(entry-tp1)*10:.1f} Pips)\n\n"
                                 f"🛡️ <i>تنويه: يظل وقف الخسارة ثابتًا عند موقعه الأصلي (${sl:,.2f}) لتأمين الصفقة، وبانتظار الهدف الثاني!</i>"
                        )

                elif status == 'tp1_hit' and tp2:
                    # Check Target 2
                    if (direction == 'BUY' and current_price >= tp2) or (direction == 'SELL' and current_price <= tp2):
                        status = 'tp2_hit'
                        trade['status'] = status
                        changed = True
                        logger.info(f"🥈 Target 2 Hit for {direction} @ {entry}. Current: {current_price}")
                        if db_id:
                            self.db.update_trade_status(db_id, 'tp2_hit', result_pips=abs(entry-tp2)*10, close_price=tp2)
                        
                        await self.broadcast_to_active_subscribers(
                            text=f"🥈 <b>تحقق الهدف الثاني | Target 2 Hit!</b>\n"
                                 f"{'═'*35}\n\n"
                                 f"⚙️ <b>النوع | Type:</b> {direction}\n"
                                 f"🎯 <b>سعر الدخول | Entry:</b> ${entry:,.2f}\n"
                                 f"✅ <b>الهدف الثاني | TP2:</b> ${tp2:,.2f}\n"
                                 f"💰 <b>جني الأرباح الجزئية | Partial Profit:</b> جني 50% من الأرباح (+{abs(entry-tp2)*10:.1f} Pips)\n\n"
                                 f"🛡️ <i>تنويه: يظل وقف الخسارة ثابتًا عند موقعه الأصلي (${sl:,.2f})، وبانتظار الهدف الثالث والنهائي!</i>"
                        )

                elif status == 'tp2_hit' and tp3:
                    # Check Target 3
                    if (direction == 'BUY' and current_price >= tp3) or (direction == 'SELL' and current_price <= tp3):
                        status = 'closed'
                        changed = True
                        logger.info(f"🏆 Target 3 Hit for {direction} @ {entry}. Current: {current_price}")
                        if db_id:
                            self.db.update_trade_status(db_id, 'closed', result_pips=abs(entry-tp3)*10, close_price=tp3)
                        
                        await self.broadcast_to_active_subscribers(
                            text=f"🎉 <b>تحقق الهدف الثالث والنهائي | Target 3 Hit!</b>\n"
                                 f"{'═'*35}\n\n"
                                 f"⚙️ <b>النوع | Type:</b> {direction}\n"
                                 f"🎯 <b>السعر الحالي | Closed At:</b> ${current_price:,.2f}\n"
                                 f"🏆 <b>الأرباح الكلية | Total Profit:</b> +{abs(entry-tp3)*10:.1f} نقطة (Pips)\n\n"
                                 f"🥇 <i>تم ضرب الهدف الثالث بنجاح وإغلاق كامل العقد لجني الأرباح! هنيئاً لكم وبدء البحث عن صفقة جديدة.</i>"
                        )
                        continue # Removes trade from monitoring list
                updated_trades.append(trade)

            if changed:
                self.save_active_trades(updated_trades)
