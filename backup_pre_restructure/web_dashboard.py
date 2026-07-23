import logging
import urllib.parse
import json
import os
import asyncio
from http.server import SimpleHTTPRequestHandler, HTTPServer
from datetime import datetime

logger = logging.getLogger(__name__)

# Dynamic timezone tracking relative to UTC
BROKER_TIMEZONE_OFFSET_HOURS = 3.0

def get_candle_start_time(timestamp_ms: int) -> int:
    """Rounds timestamp down to the nearest 1-minute interval (in milliseconds)."""
    return (timestamp_ms // 60000) * 60000

def handle_incoming_candle(data):
    """Saves a single candle to the database."""
    try:
        symbol = data['symbol']
        timeframe = data['timeframe']
        time_str = data['time']
        open_p = float(data['open'])
        high_p = float(data['high'])
        low_p = float(data['low'])
        close_p = float(data['close'])
        volume = int(data.get('volume') or 0)
        delta = float(data.get('delta') or 0.0)
        ema34 = float(data.get('ema34') or 0.0)
        ema50 = float(data.get('ema50') or 0.0)
        
        # Dynamic timezone offset detection
        try:
            from datetime import timezone
            utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
            broker_dt = datetime.strptime(time_str, '%Y.%m.%d %H:%M:%S')
            diff = (broker_dt - utc_now).total_seconds() / 3600.0
            rounded_offset = round(diff * 2) / 2.0
            global BROKER_TIMEZONE_OFFSET_HOURS
            BROKER_TIMEZONE_OFFSET_HOURS = rounded_offset
        except Exception:
            pass
        
        from trade_db import TradeDB
        db = TradeDB()
        db.save_candle(symbol, timeframe, time_str, open_p, high_p, low_p, close_p, volume, delta, ema34=ema34, ema50=ema50)
        return True, "Candle saved"
    except Exception as e:
        logger.error(f"Error handling candle: {e}")
        return False, str(e)

async def close_candle_for_timeframe(timeframe: str, tracker, bot, scanner):
    try:
        from engine.footprint import FootprintAnalysis
        from engine.rules import evaluate_rules
        from trade_db import TradeDB
        import json
        
        state = await tracker.get_state()
        footprint_matrix = state["live_footprint"]
        
        footprint_analyzer = FootprintAnalysis(footprint_matrix)
        ask_imb, bid_imb = footprint_analyzer.get_diagonal_imbalances()
        
        # Fetch all ticks in closed window
        ticks_list = await tracker.tick_buffer.get_all()
        candle_ticks = [
            t for t in ticks_list
            if tracker.active_candle_start <= t["timestamp"] < tracker.active_candle_end
        ]
        
        if candle_ticks:
            o_val = candle_ticks[0]["price"]
            c_val = candle_ticks[-1]["price"]
            h_val = max(t["price"] for t in candle_ticks)
            l_val = min(t["price"] for t in candle_ticks)
            
            # Wait 1.5 seconds for EA upload
            await asyncio.sleep(1.5)
            
            db = TradeDB()
            
            # Convert active_candle_start (broker time) directly to string
            from datetime import datetime, timezone
            broker_dt = datetime.fromtimestamp(tracker.active_candle_start / 1000.0, tz=timezone.utc)
            candle_time_str = broker_dt.strftime('%Y.%m.%d %H:%M:%S')
            
            db_c_row = db.conn.execute(
                "SELECT * FROM candles WHERE symbol = ? AND timeframe = ? AND time = ?",
                ("XAUUSD", timeframe, candle_time_str)
            ).fetchone()
            
            candle_delta_val = sum(lvl["ask"] - lvl["bid"] for lvl in footprint_matrix.values())
            fp_volume = sum(lvl["ask"] + lvl["bid"] for lvl in footprint_matrix.values())
            
            if db_c_row:
                db_c = dict(db_c_row)
                futures_close = c_val
                mt5_close = db_c["close"]
                price_offset = mt5_close - futures_close
                
                shifted_footprint = {}
                for k_cents, val in footprint_matrix.items():
                    price_val = float(k_cents) / 100.0
                    shifted_price = price_val + price_offset
                    shifted_cents = int(round(shifted_price * 100.0))
                    shifted_footprint[shifted_cents] = val
                    
                footprint_json = json.dumps(shifted_footprint)
                final_volume = int(db_c["volume"] or 0)
                final_delta = float(db_c["delta"] or 0.0) if db_c["delta"] is not None else candle_delta_val
                
                ohlc_data = {
                    "open": db_c["open"],
                    "high": db_c["high"],
                    "low": db_c["low"],
                    "close": db_c["close"],
                    "volume": final_volume,
                    "delta": final_delta
                }
                
                db.save_candle(
                    symbol="XAUUSD", timeframe=timeframe, time_str=candle_time_str,
                    open_p=db_c["open"], high_p=db_c["high"], low_p=db_c["low"], close_p=db_c["close"],
                    volume=final_volume, delta=final_delta, footprint_data=footprint_json
                )
                logger.info(f"Closed {timeframe} candle updated in DB with shifted footprint. Offset: {price_offset:.2f}, Vol: {final_volume}")
            else:
                footprint_json = json.dumps(footprint_matrix)
                ohlc_data = {
                    "open": o_val,
                    "high": h_val,
                    "low": l_val,
                    "close": c_val,
                    "volume": int(fp_volume),
                    "delta": candle_delta_val
                }
                db.save_candle(
                    symbol="XAUUSD", timeframe=timeframe, time_str=candle_time_str,
                    open_p=o_val, high_p=h_val, low_p=l_val, close_p=c_val,
                    volume=int(fp_volume), delta=candle_delta_val, footprint_data=footprint_json
                )
                logger.info(f"Closed {timeframe} candle saved as fallback in DB. Vol: {fp_volume}")
                
            logger.info(f"--- {timeframe} Candle Closed [{tracker.active_candle_start}] ---")
            
            # Evaluate rules for this timeframe
            state_with_tf = state.copy()
            state_with_tf["timeframe"] = timeframe
            
            signal_data = evaluate_rules(
                state_with_tf, ohlc_data, volume_sma_10=1000,
                verbose_callback=scanner.handle_signal_rejection if scanner else None
            )
            if signal_data and scanner:
                await scanner.broadcast_order_flow_signal(signal_data)
                
        # Clear footprint matrix for next candle
        await tracker.reset_live_candle()
    except Exception as e:
        logger.error(f"Error in close_candle_for_timeframe for {timeframe}: {e}", exc_info=True)

async def handle_ticks_batch_async(data, bot, scanner):
    """Processes a batch of raw transaction ticks inside the asyncio event loop for both M1 and M5."""
    try:
        ticks = data.get("ticks", [])
        
        from engine.parser import order_flow_tracker_m1, order_flow_tracker_m5
        
        for tick in ticks:
            tick_time = int(tick["t"])
            price = float(tick["p"])
            volume = float(tick["v"])
            side = tick["s"]
            
            # --- 1. Process M1 Timeframe ---
            tick_candle_start_m1 = (tick_time // 60000) * 60000
            if order_flow_tracker_m1.active_candle_start == 0:
                order_flow_tracker_m1.active_candle_start = tick_candle_start_m1
                order_flow_tracker_m1.active_candle_end = tick_candle_start_m1 + 60000
                logger.info(f"Initialized active M1 candle: {order_flow_tracker_m1.active_candle_start}")
                
            if tick_time >= order_flow_tracker_m1.active_candle_end:
                await close_candle_for_timeframe("M1", order_flow_tracker_m1, bot, scanner)
                order_flow_tracker_m1.active_candle_start = tick_candle_start_m1
                order_flow_tracker_m1.active_candle_end = tick_candle_start_m1 + 60000
                
            await order_flow_tracker_m1.process_tick(price, volume, side, tick_time)
            
            # --- 2. Process M5 Timeframe ---
            tick_candle_start_m5 = (tick_time // 300000) * 300000
            if order_flow_tracker_m5.active_candle_start == 0:
                order_flow_tracker_m5.active_candle_start = tick_candle_start_m5
                order_flow_tracker_m5.active_candle_end = tick_candle_start_m5 + 300000
                logger.info(f"Initialized active M5 candle: {order_flow_tracker_m5.active_candle_start}")
                
            if tick_time >= order_flow_tracker_m5.active_candle_end:
                await close_candle_for_timeframe("M5", order_flow_tracker_m5, bot, scanner)
                order_flow_tracker_m5.active_candle_start = tick_candle_start_m5
                order_flow_tracker_m5.active_candle_end = tick_candle_start_m5 + 300000
                
            await order_flow_tracker_m5.process_tick(price, volume, side, tick_time)
            
        return True, f"Ticks batch of {len(ticks)} processed for M1 and M5"
    except Exception as e:
        logger.error(f"Error in handle_ticks_batch_async: {e}", exc_info=True)
        return False, str(e)

async def handle_live_price_async(data, bot, scanner):
    """Updates the live price cache and triggers active trade monitoring."""
    try:
        symbol = data['symbol']
        bid = float(data['bid'])
        ask = float(data['ask'])
        spread = float(data['spread'])
        server_time = data['server_time']
        ema34 = float(data.get('ema34', 0.0))
        ema50 = float(data.get('ema50', 0.0))
        
        # Dynamic timezone offset detection
        try:
            from datetime import timezone
            utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
            broker_dt = datetime.strptime(server_time, '%Y.%m.%d %H:%M:%S')
            diff = (broker_dt - utc_now).total_seconds() / 3600.0
            rounded_offset = round(diff * 2) / 2.0
            global BROKER_TIMEZONE_OFFSET_HOURS
            BROKER_TIMEZONE_OFFSET_HOURS = rounded_offset
        except Exception:
            pass
        
        # Save to SQLite DB
        from trade_db import TradeDB
        db = TradeDB()
        db.save_live_price(symbol, bid, ask, spread, server_time, ema34, ema50)
        
        # Run trade monitoring immediately
        if scanner:
            await scanner.monitor_active_trades(current_price=bid)
            
        return True, "Price updated & trades monitored"
    except Exception as e:
        logger.error(f"Error in handle_live_price_async: {e}")
        return False, str(e)

async def handle_live_footprint_async(data):
    """Processes the full raw accumulated footprint streamed from the MT5 EA."""
    try:
        tf = data.get("timeframe", "M1")
        raw_data = data.get("raw_data", "")
        raw_data = raw_data.replace('\\n', '\n')
        
        from engine.parser import order_flow_tracker_m1, order_flow_tracker_m5
        tracker = order_flow_tracker_m5 if tf == "M5" else order_flow_tracker_m1
        
        lines = raw_data.strip().split('\n')
        if lines:
            # Extract active candle time from the first line
            first_line = lines[0]
            idx_semi = first_line.find(';')
            bartime = None
            if idx_semi >= 19:
                bartime = first_line[idx_semi-19:idx_semi]
                
            async with tracker.lock:
                # Clear footprint only if a new candle time is detected
                last_time = getattr(tracker, "active_candle_time_str", None)
                if bartime and last_time != bartime:
                    tracker.live_footprint.clear()
                    tracker.active_candle_time_str = bartime
                    logger.info(f"New active candle detected: {bartime}. Cleared footprint accumulator.")
                
                for line in lines:
                    idx_semi = line.find(';')
                    if idx_semi >= 19:
                        footprint_part = line[idx_semi+1:]
                        levels = footprint_part.split('|')
                        for lvl in levels[1:]:
                            lvl_parts = lvl.split(';')
                            if len(lvl_parts) >= 3:
                                try:
                                    price = float(lvl_parts[0])
                                    ask = int(lvl_parts[1])
                                    bid = int(lvl_parts[2])
                                    cents = int(round(price * 100.0))
                                    
                                    # Accumulate ask and bid volumes for this price level
                                    if cents in tracker.live_footprint:
                                        tracker.live_footprint[cents]["ask"] += ask
                                        tracker.live_footprint[cents]["bid"] += bid
                                    else:
                                        tracker.live_footprint[cents] = {"ask": ask, "bid": bid}
                                except ValueError:
                                    pass
                                
        # Update active candle start time from footprint data
        if lines:
            line = lines[0]
            idx_semi = line.find(';')
            if idx_semi >= 19:
                bartime = line[idx_semi-19:idx_semi]
                tracker.active_candle_time_str = bartime
                try:
                    from datetime import datetime, timezone
                    dt = datetime.strptime(bartime, '%Y.%m.%d %H:%M:%S')
                    dt = dt.replace(tzinfo=timezone.utc)
                    tracker.active_candle_start = int(dt.timestamp() * 1000.0)
                    tracker.active_candle_end = tracker.active_candle_start + (300000 if tf == "M5" else 60000)
                except Exception as parse_err:
                    logger.warning(f"Failed to parse active candle time '{bartime}': {parse_err}")
                            
        return True, "Footprint updated"
    except Exception as e:
        logger.error(f"Error in handle_live_footprint_async: {e}")
        return False, str(e)

class WebDashboardHandler(SimpleHTTPRequestHandler):
    """API Gateway for MetaTrader 5 integration, handling order flow tick feeds and serving Admin Testing Console."""

    def do_GET(self):
        url_path = urllib.parse.urlparse(self.path).path
        
        # 1. API Test Endpoints
        if url_path.startswith("/api/test/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            test_type = url_path.replace("/api/test/", "")
            response_data = {}
            
            if test_type == "deepseek":
                try:
                    from deepseek_client import DeepSeekClient
                    client = DeepSeekClient()
                    res = client.chat("Respond in 1 line: 'DeepSeek API connection successful!'")
                    response_data = {"status": "success", "message": res}
                except Exception as e:
                    response_data = {"status": "error", "message": str(e)}
                    
            elif test_type == "gemini":
                try:
                    from gemini_client import GeminiClient
                    client = GeminiClient()
                    if not client.api_key:
                        response_data = {"status": "error", "message": "GEMINI_API_KEY is missing from environment variables."}
                    else:
                        summary = {"price": {"price": 2400.0, "change": 0.5, "adr": 25.0, "dxy": {"price": 105.0, "trend": "Neutral"}}, "session": {"session": "Asian"}}
                        # Single pixel red base64 image
                        mock_image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
                        res = client.analyze_chart_images([mock_image], "scalp", summary)
                        response_data = {"status": "success", "message": res}
                except Exception as e:
                    response_data = {"status": "error", "message": str(e)}
                    
            elif test_type == "database":
                try:
                    from trade_db import TradeDB
                    db = TradeDB()
                    subs_count = len(db.get_all_subscribers())
                    cursor = db.conn.execute("SELECT COUNT(*) FROM trades")
                    trades_count = cursor.fetchone()[0]
                    cursor = db.conn.execute("SELECT COUNT(*) FROM candles")
                    candles_count = cursor.fetchone()[0]
                    cursor = db.conn.execute("SELECT COUNT(*) FROM live_prices")
                    prices_count = cursor.fetchone()[0]
                    response_data = {
                        "status": "success",
                        "subscribers": subs_count,
                        "logged_trades": trades_count,
                        "cached_candles": candles_count,
                        "cached_live_prices": prices_count
                    }
                except Exception as e:
                    response_data = {"status": "error", "message": str(e)}
                    
            elif test_type == "orderflow":
                try:
                    from engine.parser import order_flow_tracker
                    from trade_db import TradeDB
                    db = TradeDB()
                    lp = db.get_live_price("XAUUSD")
                    ema34_val = lp.get("ema34", 0.0) if lp else 0.0
                    ema50_val = lp.get("ema50", 0.0) if lp else 0.0
                    
                    if hasattr(self.server, 'loop') and self.server.loop:
                        future = asyncio.run_coroutine_threadsafe(order_flow_tracker.get_state(), self.server.loop)
                        state = future.result(timeout=2.0)
                        response_data = {
                            "status": "success",
                            "vwap": state.get("vwap"),
                            "poc": state.get("poc"),
                            "vah": state.get("vah"),
                            "val": state.get("val"),
                            "cvd": state.get("cvd"),
                            "std_dev": state.get("std_dev"),
                            "ema34": ema34_val,
                            "ema50": ema50_val,
                            "tick_buffer_size": len(state.get("live_footprint", {}))
                        }
                    else:
                        response_data = {"status": "error", "message": "Server event loop not attached"}
                except Exception as e:
                    response_data = {"status": "error", "message": str(e)}
                    
            elif test_type == "run":
                try:
                    diagnostics = {}
                    diagnostics["env_bot_token"] = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
                    diagnostics["env_deepseek_key"] = bool(os.getenv("DEEPSEEK_API_KEY"))
                    diagnostics["env_gemini_key"] = bool(os.getenv("GEMINI_API_KEY"))
                    
                    from trade_db import TradeDB
                    db = TradeDB()
                    diagnostics["database_file_exists"] = os.path.exists("trades.db")
                    
                    # check DLL
                    dll_found = False
                    appdata_path = os.getenv("APPDATA")
                    if appdata_path:
                        mql5_lib = os.path.join(appdata_path, "MetaQuotes", "Terminal", "E7DB6AF1FE93F292652A5D3B98342601", "MQL5", "Libraries")
                        dll_path = os.path.join(mql5_lib, "footprint_v1x0_x64.dll")
                        dll_found = os.path.exists(dll_path)
                    diagnostics["dll_in_mql5_libraries"] = dll_found
                    
                    from engine.rules import evaluate_rules
                    state = {"val": 2350.0, "vah": 2360.0, "vwap": 2355.0, "std_dev": 2.0, "cvd": 100, "live_footprint": {}}
                    ohlc = {"open": 2352.0, "high": 2358.0, "low": 2351.0, "close": 2355.0, "volume": 1200}
                    rule_eval = evaluate_rules(state, ohlc, volume_sma_10=1000)
                    diagnostics["rules_engine_dry_run"] = "OK"
                    
                    response_data = {
                        "status": "success",
                        "diagnostics": diagnostics
                    }
                except Exception as e:
                    response_data = {"status": "error", "message": str(e)}
            else:
                response_data = {"status": "error", "message": "Unknown test endpoint"}
                
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
            return

        # 1.5 Live Price Status
        if url_path == "/api/live-price-status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                from trade_db import TradeDB
                db = TradeDB()
                lp = db.get_live_price("XAUUSD")
                if lp:
                    response_data = {
                        "status": "success",
                        "bid": lp["bid"],
                        "ask": lp["ask"],
                        "spread": lp["spread"],
                        "ema34": lp.get("ema34", 0.0),
                        "ema50": lp.get("ema50", 0.0),
                        "server_time": lp["server_time"]
                    }
                else:
                    candles = db.get_candles("XAUUSD", "M1", limit=1)
                    if candles:
                        c = candles[0]
                        response_data = {
                            "status": "success",
                            "bid": c["close"],
                            "ask": c["close"],
                            "spread": 0.0,
                            "server_time": c["time"]
                        }
                    else:
                        response_data = {
                            "status": "error",
                            "message": "No price data in database yet."
                        }
            except Exception as e:
                response_data = {"status": "error", "message": str(e)}
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
            return

        # 1.6 Rejected Signals Audit
        if url_path == "/api/rejected-signals":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                from trade_db import TradeDB
                db = TradeDB()
                signals = db.get_rejected_signals(limit=50)
                self.wfile.write(json.dumps(signals).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 1.7 Live Query Footprint & Candles
        if url_path.startswith("/api/query-footprint"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                from urllib.parse import parse_qs, urlparse
                query_components = parse_qs(urlparse(self.path).query)
                symbol = query_components.get("symbol", ["XAUUSD"])[0]
                timeframe = query_components.get("timeframe", ["M1"])[0]
                
                from trade_db import TradeDB
                db = TradeDB()
                limit_count = 60 if timeframe == "M1" else 12
                candles = db.get_candles(symbol, timeframe, limit=limit_count)
                signals = db.get_rejected_signals(limit=5)
                
                response_data = {
                    "status": "success",
                    "candles": candles,
                    "signals": [
                        {
                            "id": s["id"],
                            "timestamp": s["timestamp"],
                            "signal_type": s["signal_type"],
                            "reason": s["reason"],
                            "metrics_snapshot": json.loads(s["metrics_snapshot"]) if s["metrics_snapshot"] else {}
                        } for s in signals
                    ]
                }
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 1.8 Query Specific Candle Footprint
        if url_path == "/api/query-candle-footprint":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                from urllib.parse import parse_qs, urlparse
                query_components = parse_qs(urlparse(self.path).query)
                symbol = query_components.get("symbol", ["XAUUSD"])[0]
                timeframe = query_components.get("timeframe", ["M1"])[0]
                time_str = query_components.get("time", [""])[0]
                
                from trade_db import TradeDB
                db = TradeDB()
                
                from engine.parser import order_flow_tracker_m1, order_flow_tracker_m5
                tracker = order_flow_tracker_m5 if timeframe == "M5" else order_flow_tracker_m1
                
                # Determine if querying the active candle
                is_active = False
                if time_str:
                    if hasattr(tracker, "active_candle_time_str") and tracker.active_candle_time_str == time_str:
                        is_active = True
                else:
                    is_active = True
                    if hasattr(tracker, "active_candle_time_str"):
                        time_str = tracker.active_candle_time_str
                
                query = "SELECT * FROM candles WHERE symbol = ? AND timeframe = ?"
                params = [symbol, timeframe]
                if time_str:
                    query += " AND time = ?"
                    params.append(time_str)
                else:
                    query += " ORDER BY time DESC LIMIT 1"
                
                row = db.conn.execute(query, params).fetchone()
                if row:
                    candle = dict(row)
                    
                    if is_active:
                        # Get live footprint from tracker memory
                        state = asyncio.run_coroutine_threadsafe(tracker.get_state(), self.server.loop).result(timeout=2.0)
                        footprint_matrix = state["live_footprint"]
                        
                        if footprint_matrix:
                            # Calculate futures high from footprint keys (in cents)
                            futures_high = max(float(k) / 100.0 for k in footprint_matrix.keys())
                            mt5_high = float(candle["high"])
                            price_offset = mt5_high - futures_high
                            
                            # Shift footprint prices
                            shifted_footprint = {}
                            for k_cents, val in footprint_matrix.items():
                                price_val = float(k_cents) / 100.0
                                shifted_price = price_val + price_offset
                                shifted_cents = int(round(shifted_price * 100.0))
                                shifted_footprint[shifted_cents] = val
                                
                            candle["footprint_data"] = shifted_footprint
                            candle["delta"] = sum(lvl["ask"] - lvl["bid"] for lvl in footprint_matrix.values())
                            fp_volume = sum(lvl["ask"] + lvl["bid"] for lvl in footprint_matrix.values())
                            candle["volume"] = max(int(candle["volume"] or 0), int(fp_volume))
                        else:
                            candle["footprint_data"] = {}
                    else:
                        # Fetch from DB
                        if candle.get("footprint_data"):
                            try:
                                candle["footprint_data"] = json.loads(candle["footprint_data"])
                            except Exception:
                                candle["footprint_data"] = {}
                        else:
                            candle["footprint_data"] = {}
                            
                    response_data = {"status": "success", "candle": candle}
                else:
                    response_data = {"status": "error", "message": "Candle not found"}
                
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # 2. Serve Admin HTML Panel
        if url_path in ["/", "/admin"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            
            html_content = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NERO FLOW - لوحة اختبارات المسؤول</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Outfit', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        body {
            background-color: #0b0c10;
            color: #c5c6c7;
            padding: 40px 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        .container {
            max-width: 1000px;
            width: 100%;
            background: rgba(20, 24, 33, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            padding: 30px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
        }
        header {
            text-align: center;
            margin-bottom: 30px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 20px;
        }
        header h1 {
            color: #66fcf1;
            font-size: 2.2rem;
            font-weight: 700;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }
        header p {
            color: #8b9bb4;
            font-size: 1rem;
            margin-bottom: 15px;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 35px;
        }
        .card {
            background: rgba(31, 40, 51, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            transition: all 0.3s ease;
        }
        .card:hover {
            transform: translateY(-5px);
            border-color: #66fcf1;
            box-shadow: 0 4px 20px rgba(102, 252, 241, 0.15);
        }
        .card h3 {
            color: #ffffff;
            font-size: 1.2rem;
            margin-bottom: 15px;
        }
        .btn {
            background-color: #45f3ff;
            color: #0b0c10;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            transition: all 0.3s ease;
        }
        .btn:hover {
            background-color: #66fcf1;
            box-shadow: 0 0 10px rgba(102, 252, 241, 0.4);
        }
        .btn-system {
            background-color: #10b981;
            color: white;
            font-size: 1.1rem;
            padding: 15px;
            margin-bottom: 30px;
        }
        .btn-system:hover {
            background-color: #059669;
            box-shadow: 0 0 15px rgba(16, 185, 129, 0.4);
        }
        .console-container {
            background-color: #050608;
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            padding: 20px;
            font-family: 'Courier New', Courier, monospace;
            position: relative;
        }
        .console-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 10px;
            margin-bottom: 15px;
        }
        .console-title {
            color: #8b9bb4;
            font-size: 0.9rem;
            font-weight: 600;
        }
        .status-badge {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .status-idle { background: #374151; color: #d1d5db; }
        .status-loading { background: #fbbf24; color: #0b0c10; }
        .status-success { background: #10b981; color: white; }
        .status-error { background: #ef4444; color: white; }
        .console-output {
            color: #00ff66;
            font-size: 0.95rem;
            white-space: pre-wrap;
            max-height: 350px;
            overflow-y: auto;
            text-align: left;
            direction: ltr;
        }
        @keyframes blink {
            0% { opacity: 0.4; }
            100% { opacity: 1.0; }
        }
        
        .footprint-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.95rem;
        }
        .footprint-row {
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }
        .footprint-cell-bid {
            width: 40%;
            text-align: left;
            padding: 8px 15px;
            color: #ef4444;
            font-weight: bold;
        }
        .footprint-cell-price {
            width: 20%;
            text-align: center;
            padding: 8px;
            background: #1f2833;
            color: #ffffff;
            font-weight: bold;
            border-left: 2px solid rgba(255,255,255,0.1);
            border-right: 2px solid rgba(255,255,255,0.1);
        }
        .footprint-cell-price.poc {
            background: #fbbf24;
            color: #0b0c10;
        }
        .footprint-cell-ask {
            width: 40%;
            text-align: right;
            padding: 8px 15px;
            color: #10b981;
            font-weight: bold;
        }
        .imbalance-buy {
            background-color: rgba(16, 185, 129, 0.25);
            border: 1px solid #10b981;
        }
        .imbalance-sell {
            background-color: rgba(239, 68, 68, 0.25);
            border: 1px solid #ef4444;
        }
    </style>
</head>
<body class="notranslate">
    <div class="container">
        <header>
            <h1>🥇 NERO FLOW CONTROL PANEL</h1>
            <p>لوحة التحكم واختبارات المكونات المدمجة للسيرفر والذكاء الاصطناعي</p>
            
            <div style="margin-top: 15px; display: inline-flex; align-items: center; background: rgba(102, 252, 241, 0.08); border: 1px solid rgba(102, 252, 241, 0.25); padding: 8px 22px; border-radius: 50px; box-shadow: 0 0 15px rgba(102, 252, 241, 0.08); gap: 15px;">
                <span style="font-size: 0.95rem; color: #8b9bb4; font-weight: 600;">🟡 سعر الذهب المباشر (MT5 Gold Price):</span>
                <span id="live-gold-price" style="font-size: 1.25rem; color: #66fcf1; font-weight: 700; font-family: 'Courier New', monospace; letter-spacing: 1px; text-shadow: 0 0 10px rgba(102, 252, 241, 0.4);">جاري الجلب...</span>
                <span style="width: 10px; height: 10px; background-color: #fbbf24; border-radius: 50%; display: inline-block; animation: blink 1s infinite alternate;" id="price-status-dot"></span>
                <span style="font-size: 0.95rem; color: #8b9bb4; font-weight: 600; border-left: 1px solid rgba(255,255,255,0.15); padding-left: 15px;">🌊 موجة المتوسطات (EMA Wave Zone):</span>
                <span id="live-ema-wave" style="font-size: 1.15rem; color: #fbbf24; font-weight: 700; font-family: 'Courier New', monospace;">EMA34: -- | EMA50: --</span>
            </div>
        </header>

        <!-- Footprint Viewer Section (NOW AT THE TOP!) -->
        <div style="margin-bottom: 35px; background: rgba(31, 40, 51, 0.4); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 12px; padding: 20px;">
            <div style="border-bottom: 1px solid rgba(255, 255, 255, 0.05); padding-bottom: 12px; margin-bottom: 15px;">
                <h3 style="color: #66fcf1; font-size: 1.25rem; font-weight: 600;">👣 مستعرض بصمة الشموع التاريخية (Candle Footprint Profile)</h3>
                <p style="font-size: 0.85rem; color: #8b9bb4; margin-top: 5px;">استعرض التوزيع الفعلي لأسعار الشراء والبيع والامتصاص لأي شمعة مخزنة في قاعدة البيانات بالتوقيت المحلي</p>
            </div>
            
            <div style="display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap;">
                <div style="flex: 1; min-width: 150px;">
                    <label style="font-size: 0.8rem; color: #8b9bb4; display: block; margin-bottom: 5px;">الفريم الزمنى:</label>
                    <select id="fp-timeframe" style="width: 100%; background: #0b0c10; color: #c5c6c7; border: 1px solid rgba(255,255,255,0.1); padding: 8px; border-radius: 6px;" onchange="loadRecentCandlesList()">
                        <option value="M5" selected>M5 (5 دقائق)</option>
                        <option value="M1">M1 (1 دقيقة)</option>
                    </select>
                </div>
                <div style="flex: 2; min-width: 250px;">
                    <label style="font-size: 0.8rem; color: #8b9bb4; display: block; margin-bottom: 5px;">اختر من الشموع الأخيرة:</label>
                    <select id="fp-candle-select" style="width: 100%; background: #0b0c10; color: #c5c6c7; border: 1px solid rgba(255,255,255,0.1); padding: 8px; border-radius: 6px;" onchange="syncSearchTimeInput()">
                        <option value="">-- اختر شمعة --</option>
                    </select>
                </div>
                <div style="flex: 2; min-width: 200px;">
                    <label style="font-size: 0.8rem; color: #8b9bb4; display: block; margin-bottom: 5px;">أو ابحث عن وقت محدد (توقيتك المحلي):</label>
                    <input type="text" id="fp-candle-time" placeholder="مثال: 2026.07.15 09:30:00" style="width: 100%; background: #0b0c10; color: #c5c6c7; border: 1px solid rgba(255,255,255,0.1); padding: 8px; border-radius: 6px;">
                </div>
                <div style="display: flex; align-items: flex-end;">
                    <button class="btn" style="width: auto; padding: 8px 25px; height: 38px;" onclick="fetchAndRenderFootprint()">عرض البصمة 🔍</button>
                </div>
            </div>
            
            <div id="footprint-result-container" style="display: none; grid-template-columns: 1fr 2fr; gap: 20px; margin-top: 20px;">
                <!-- Left: Candle Metadata Summary -->
                <div style="background: rgba(11, 12, 16, 0.6); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 10px; padding: 20px; display: flex; flex-direction: column; gap: 12px;" id="fp-candle-summary">
                </div>
                <!-- Right: Footprint Chart -->
                <div style="background: rgba(11, 12, 16, 0.6); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 10px; padding: 20px; overflow-y: auto; max-height: 500px;" id="fp-chart-container">
                </div>
            </div>
            <div id="footprint-no-data" style="padding: 30px; text-align: center; color: #8b9bb4; border: 1px dashed rgba(255,255,255,0.08); border-radius: 10px; margin-top: 20px;">
                اختر شمعة أو أدخل التوقيت واضغط على "عرض البصمة" لاستعراض تفاصيل توزيع العقود.
            </div>
        </div>

        <button class="btn btn-system" id="btn-run" onclick="runTest('run')">🔥 تشغيل فحص تشخيصي كامل للمشروع (Full Diagnostics)</button>

        <div class="grid">
            <div class="card">
                <h3>🧠 اختبار ديب سيك</h3>
                <p style="font-size:0.85rem; color:#8b9bb4; margin-bottom:15px;">فحص اتصال وتوليد نصوص الذكاء الاصطناعي</p>
                <button class="btn" onclick="runTest('deepseek')">فحص الاتصال</button>
            </div>
            <div class="card">
                <h3>🖼️ اختبار جيمناي</h3>
                <p style="font-size:0.85rem; color:#8b9bb4; margin-bottom:15px;">فحص تحليل الرؤية البصرية لشارت الذهب</p>
                <button class="btn" onclick="runTest('gemini')">فحص الاتصال</button>
            </div>
            <div class="card">
                <h3>💾 اختبار قاعدة البيانات</h3>
                <p style="font-size:0.85rem; color:#8b9bb4; margin-bottom:15px;">جرد الأعضاء، الصفقات والشموع المخزنة</p>
                <button class="btn" onclick="runTest('database')">فحص البيانات</button>
            </div>
            <div class="card">
                <h3>📈 اختبار مؤشرات السيولة</h3>
                <p style="font-size:0.85rem; color:#8b9bb4; margin-bottom:15px;">فحص قيم VWAP, CVD, VAL, VAH النشطة</p>
                <button class="btn" onclick="runTest('orderflow')">فحص المؤشرات</button>
            </div>
        </div>

        <div class="console-container">
            <div class="console-header">
                <span class="console-title">🖥️ مخرجات الفحص (Test Outputs)</span>
                <span id="badge" class="status-badge status-idle">خامل (IDLE)</span>
            </div>
            <div id="output" class="console-output">اضغط على أي اختبار في الأعلى لبدء التشغيل الفوري واستعراض مخرجات السيرفر...</div>
        </div>

        <!-- Rejected Signals Log Audit Trail -->
        <div style="margin-top: 35px; background: rgba(31, 40, 51, 0.4); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 12px; padding: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255, 255, 255, 0.05); padding-bottom: 12px; margin-bottom: 15px;">
                <h3 style="color: #66fcf1; font-size: 1.25rem; font-weight: 600;">🛡️ سجل تصفية الصفقات المرفوضة (Rejected Signals Audit Trail)</h3>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <select id="signal-filter" style="background: #0b0c10; color: #c5c6c7; border: 1px solid rgba(255,255,255,0.1); padding: 6px 12px; border-radius: 6px; font-size: 0.85rem;" onchange="loadRejectedSignals()">
                        <option value="today" selected>صفقات اليوم (Today)</option>
                        <option value="week">آخر 7 أيام (Last 7 Days)</option>
                        <option value="all">كل السجلات (All)</option>
                    </select>
                    <button class="btn" style="width: auto; padding: 6px 15px; font-size: 0.85rem;" onclick="loadRejectedSignals()">🔄 تحديث السجل</button>
                </div>
            </div>
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; text-align: right; font-size: 0.9rem;" id="rejected-signals-table">
                    <thead>
                        <tr style="border-bottom: 2px solid rgba(255, 255, 255, 0.08); color: #8b9bb4;">
                            <th style="padding: 10px;">التوقيت</th>
                            <th style="padding: 10px;">الاتجاه</th>
                            <th style="padding: 10px; text-align: center;">الاتجاه (EMA Wave)</th>
                            <th style="padding: 10px; text-align: center;">الحجم > SMA10</th>
                            <th style="padding: 10px; text-align: center;">سيولة البصمة</th>
                            <th style="padding: 10px; text-align: center;">الامتصاص</th>
                            <th style="padding: 10px;">سبب الرفض</th>
                        </tr>
                    </thead>
                    <tbody id="rejected-signals-body">
                        <tr>
                            <td colspan="7" style="padding: 20px; text-align: center; color: #8b9bb4;">جاري تحميل سجل الصفقات المرفوضة...</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        async function runTest(type) {
            const outputDiv = document.getElementById("output");
            const badge = document.getElementById("badge");
            
            outputDiv.innerHTML = "جاري الاتصال بالسيرفر وتشغيل الاختبار... يرجى الانتظار ⏳";
            badge.className = "status-badge status-loading";
            badge.innerText = "جاري الفحص (TESTING)";
            
            try {
                const response = await fetch('/api/test/' + type);
                const data = await response.json();
                
                outputDiv.innerHTML = JSON.stringify(data, null, 4);
                
                if (data.status === 'success') {
                    badge.className = "status-badge status-success";
                    badge.innerText = "ناجح (SUCCESS)";
                } else {
                    badge.className = "status-badge status-error";
                    badge.innerText = "خطأ (ERROR)";
                }
            } catch (err) {
                outputDiv.innerHTML = "خطأ في الاتصال بالويب سيرفر: " + err.message;
                badge.className = "status-badge status-error";
                badge.innerText = "خطأ اتصال (CONN_ERR)";
            }
        }

        async function updateLivePrice() {
            try {
                const response = await fetch('/api/live-price-status');
                const data = await response.json();
                const priceSpan = document.getElementById("live-gold-price");
                const waveSpan = document.getElementById("live-ema-wave");
                const dot = document.getElementById("price-status-dot");
                
                if (data.status === 'success') {
                    priceSpan.innerText = "$" + data.bid.toFixed(2) + " (Spread: " + data.spread.toFixed(1) + ")";
                    if (data.ema34 && data.ema50) {
                        waveSpan.innerText = "EMA34: $" + data.ema34.toFixed(2) + " | EMA50: $" + data.ema50.toFixed(2);
                    } else {
                        waveSpan.innerText = "EMA34: -- | EMA50: --";
                    }
                    dot.style.backgroundColor = "#10b981";
                } else {
                    priceSpan.innerText = "غير متصل (Disconnected)";
                    waveSpan.innerText = "EMA34: -- | EMA50: --";
                    dot.style.backgroundColor = "#ef4444";
                }
            } catch (err) {
                document.getElementById("live-gold-price").innerText = "خطأ اتصال (Error)";
                document.getElementById("live-ema-wave").innerText = "EMA34: -- | EMA50: --";
                document.getElementById("price-status-dot").style.backgroundColor = "#ef4444";
            }
        }

        async function loadRejectedSignals() {
            const tbody = document.getElementById("rejected-signals-body");
            try {
                const response = await fetch('/api/rejected-signals');
                const data = await response.json();
                
                if (data.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="7" style="padding: 20px; text-align: center; color: #8b9bb4;">لا يوجد صفقات مرفوضة في قاعدة البيانات حالياً.</td></tr>`;
                    return;
                }
                
                let html = "";
                data.forEach(s => {
                    let timestampStr = s.timestamp;
                    if (timestampStr && !timestampStr.endsWith('Z')) {
                        timestampStr += 'Z';
                    }
                    const date = new Date(timestampStr).toLocaleString("ar-EG");
                    const emoji = val => val === 1 ? "<span style='color: #10b981; font-weight: bold;'>✅</span>" : "<span style='color: #ef4444; font-weight: bold;'>❌</span>";
                    const signalColor = s.signal_type === 'BUY' ? '#10b981' : s.signal_type === 'SELL' ? '#ef4444' : '#8b9bb4';
                    
                    html += `<tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05); transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.02)'" onmouseout="this.style.background='none'">
                        <td style="padding: 12px; font-family: monospace; text-align: right;">${date}</td>
                        <td style="padding: 12px; color: ${signalColor}; font-weight: bold; text-align: right;">${s.signal_type}</td>
                        <td style="padding: 12px; text-align: center;">${emoji(s.price_near_boundary)}</td>
                        <td style="padding: 12px; text-align: center;">${emoji(s.volume_confirmed)}</td>
                        <td style="padding: 12px; text-align: center;">${emoji(s.stacked_imbalance)}</td>
                        <td style="padding: 12px; text-align: center;">${emoji(s.absorption)}</td>
                        <td style="padding: 12px; color: #fbbf24; font-size: 0.85rem; text-align: right; white-space: pre-line; line-height: 1.6;">${s.reason}</td>
                    </tr>`;
                });
                tbody.innerHTML = html;
            } catch (err) {
                tbody.innerHTML = `<tr><td colspan="7" style="padding: 20px; text-align: center; color: #ef4444;">فشل جلب سجلات الرفض: ${err.message}</td></tr>`;
            }
        }
        
        // Polling live price status every 2 seconds
        updateLivePrice();
        setInterval(updateLivePrice, 2000);

        // Polling rejected signals status every 10 seconds
        loadRejectedSignals();
        setInterval(loadRejectedSignals, 10000);

        // Timezone conversion helpers (broker time is already user's local chart time)
        function convertLocalToBrokerTime(localStr) {
            return localStr;
        }

        function convertBrokerToLocalTime(brokerStr) {
            return brokerStr;
        }

        async function loadRecentCandlesList() {
            const timeframe = document.getElementById("fp-timeframe").value;
            const select = document.getElementById("fp-candle-select");
            try {
                const response = await fetch(`/api/query-footprint?timeframe=${timeframe}`);
                const data = await response.json();
                
                if (data.status === 'success' && data.candles) {
                    let html = `<option value="">-- اختر شمعة --</option>`;
                    data.candles.slice().reverse().forEach(c => {
                        const localTime = convertBrokerToLocalTime(c.time);
                        html += `<option value="${c.time}">${localTime} (Vol: ${c.volume})</option>`;
                    });
                    select.innerHTML = html;
                } else {
                    select.innerHTML = `<option value="">-- لا يوجد شموع في القاعدة --</option>`;
                }
            } catch (err) {
                select.innerHTML = `<option value="">-- خطأ في تحميل الشموع --</option>`;
            }
        }
        
        function syncSearchTimeInput() {
            const select = document.getElementById("fp-candle-select");
            const input = document.getElementById("fp-candle-time");
            if (select.value) {
                input.value = convertBrokerToLocalTime(select.value);
            } else {
                input.value = "";
            }
        }
        
        async function fetchAndRenderFootprint() {
            const timeframe = document.getElementById("fp-timeframe").value;
            const time = document.getElementById("fp-candle-time").value;
            const resContainer = document.getElementById("footprint-result-container");
            const noDataDiv = document.getElementById("footprint-no-data");
            
            if (!time) {
                alert("يرجى إدخال وقت الشمعة أو اختيارها من القائمة أولاً.");
                return;
            }
            
            noDataDiv.innerHTML = "جاري التحميل وعرض البصمة... ⏳";
            noDataDiv.style.display = "block";
            resContainer.style.display = "none";
            
            try {
                const brokerTime = convertLocalToBrokerTime(time);
                const response = await fetch(`/api/query-candle-footprint?timeframe=${timeframe}&time=${encodeURIComponent(brokerTime)}`);
                const data = await response.json();
                
                if (data.status === 'error' || !data.candle) {
                    noDataDiv.innerHTML = `❌ لم يتم العثور على الشمعة المطلوبة في هذا التوقيت (${time}). يرجى التأكد من التوقيت أو اختيار شمعة من القائمة.`;
                    return;
                }
                
                const candle = data.candle;
                noDataDiv.style.display = "none";
                resContainer.style.display = "grid";
                
                // 1. Render Summary Card
                const isBullish = candle.close >= candle.open;
                const candleTypeStr = isBullish ? "شمعة صاعدة (BULLISH) 🟢" : "شمعة هابطة (BEARISH) 🔴";
                const typeColor = isBullish ? "#10b981" : "#ef4444";
                
                let summaryHtml = `
                    <h4 style="color: ${typeColor}; font-size: 1.15rem; font-weight: 700; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 8px;">${candleTypeStr}</h4>
                    <div style="display: flex; justify-content: space-between;"><span style="color:#8b9bb4;">التوقيت (المحلي):</span><span style="font-family:monospace; font-weight:bold;">${convertBrokerToLocalTime(candle.time)}</span></div>
                    <div style="display: flex; justify-content: space-between;"><span style="color:#8b9bb4;">الافتتاح:</span><span style="font-family:monospace;">$${candle.open.toFixed(2)}</span></div>
                    <div style="display: flex; justify-content: space-between;"><span style="color:#8b9bb4;">الأعلى:</span><span style="font-family:monospace;">$${candle.high.toFixed(2)}</span></div>
                    <div style="display: flex; justify-content: space-between;"><span style="color:#8b9bb4;">الأدنى:</span><span style="font-family:monospace;">$${candle.low.toFixed(2)}</span></div>
                    <div style="display: flex; justify-content: space-between;"><span style="color:#8b9bb4;">الإغلاق:</span><span style="font-family:monospace;">$${candle.close.toFixed(2)}</span></div>
                    <div style="display: flex; justify-content: space-between; border-top: 1px dashed rgba(255,255,255,0.08); padding-top: 8px;"><span style="color:#8b9bb4;">الحجم:</span><span style="font-family:monospace; font-weight:bold; color:#66fcf1;">${candle.volume}</span></div>
                    <div style="display: flex; justify-content: space-between;"><span style="color:#8b9bb4;">الدلتا:</span><span style="font-family:monospace; font-weight:bold; color:${candle.delta >= 0 ? '#10b981' : '#ef4444'}">${candle.delta >= 0 ? '+' : ''}${candle.delta}</span></div>
                `;
                document.getElementById("fp-candle-summary").innerHTML = summaryHtml;
                
                // 2. Render Footprint Table
                const fpData = candle.footprint_data || {};
                const prices = Object.keys(fpData).map(Number).sort((a,b) => b - a);
                
                if (prices.length === 0) {
                    document.getElementById("fp-chart-container").innerHTML = `
                        <div style="padding: 40px; text-align: center; color: #8b9bb4;">
                            ⚠️ تم العثور على الشمعة، ولكن لا يوجد بيانات تيكات تفصيلية (Footprint) مخزنة لها في قاعدة البيانات. 
                            <br><small style="color: #66fcf1; display:block; margin-top:10px;">(يتم تخزين البصمة فقط للشموع المغلقة أثناء عمل البوت الحي)</small>
                        </div>
                    `;
                    return;
                }
                
                // Find POC
                let maxVol = -1;
                let pocCents = null;
                prices.forEach(c => {
                    const total = (fpData[c].bid || 0) + (fpData[c].ask || 0);
                    if (total > maxVol) {
                        maxVol = total;
                        pocCents = c;
                    }
                });
                
                let chartHtml = `
                    <div style="text-align: center; margin-bottom: 10px; color:#8b9bb4; font-size: 0.85rem; display: flex; justify-content: space-between;">
                        <span style="color:#ef4444; font-weight:bold;">🔴 حجم البيع (BID)</span>
                        <span style="color:#ffffff; font-weight:bold;">سعر التيك</span>
                        <span style="color:#10b981; font-weight:bold;">🟢 حجم الشراء (ASK)</span>
                    </div>
                    <table class="footprint-table">
                `;
                
                prices.forEach(c => {
                    const bid = fpData[c].bid || 0;
                    const ask = fpData[c].ask || 0;
                    const price = c / 100.0;
                    const isPoc = c === pocCents;
                    const pocClass = isPoc ? "poc" : "";
                    
                    let bidClass = "";
                    let askClass = "";
                    if (ask >= bid * 3 && ask > 0 && bid > 0) {
                        askClass = "imbalance-buy";
                    }
                    if (bid >= ask * 3 && bid > 0 && ask > 0) {
                        bidClass = "imbalance-sell";
                    }
                    
                    chartHtml += `
                        <tr class="footprint-row">
                            <td class="footprint-cell-bid ${bidClass}">${bid}</td>
                            <td class="footprint-cell-price ${pocClass}">$${price.toFixed(2)}</td>
                            <td class="footprint-cell-ask ${askClass}">${ask}</td>
                        </tr>
                    `;
                });
                chartHtml += `</table>`;
                document.getElementById("fp-chart-container").innerHTML = chartHtml;
                
            } catch (err) {
                noDataDiv.innerHTML = `❌ حدث خطأ أثناء الاتصال بالويب سيرفر: ${err.message}`;
            }
        }
        
        loadRecentCandlesList();
    </script>
</body>
</html>"""
            self.wfile.write(html_content.encode('utf-8'))
            return

    def do_POST(self):
        url_path = urllib.parse.urlparse(self.path).path
        
        if url_path in ["/api/market-data", "/api/live-prices", "/api/ticks", "/api/live-footprint"]:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            try:
                raw_body = post_data.decode('utf-8').strip('\x00 \t\r\n')
                data = json.loads(raw_body)
            except Exception as json_err:
                logger.error(f"JSON Decode Error: {json_err}")
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"Invalid JSON: {str(json_err)}".encode('utf-8'))
                return
                
            # Validate secret key via headers or JSON body
            expected_secret = os.getenv("MT5_SECRET_KEY", "NEROFLOW_SECRET")
            
            # Check Headers
            secret = self.headers.get("X-Gateway-Auth")
            if not secret:
                auth_header = self.headers.get("Authorization")
                if auth_header:
                    if auth_header.lower().startswith("bearer "):
                        secret = auth_header[7:]
                    else:
                        secret = auth_header
            
            # Check JSON Body if not in headers
            if not secret:
                if isinstance(data, list) and len(data) > 0:
                    secret = data[0].get("secret")
                elif isinstance(data, dict):
                    secret = data.get("secret")
                    
            if not secret or secret != expected_secret:
                logger.warning(f"Unauthorized API POST attempt to {url_path} with secret: {secret}")
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Unauthorized")
                return
                
            if not hasattr(self.server, 'loop') or not self.server.loop:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Error: Server event loop not attached")
                return
 
            if url_path == "/api/live-footprint":
                future = asyncio.run_coroutine_threadsafe(
                    handle_live_footprint_async(data),
                    self.server.loop
                )
                try:
                    success, msg = future.result(timeout=4.0)
                    if success:
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b"OK")
                    else:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(f"Error: {msg}".encode('utf-8'))
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(f"Timeout/Error: {str(e)}".encode('utf-8'))
 
            elif url_path == "/api/market-data":
                if isinstance(data, list):
                    # Save all historical candles
                    saved_count = 0
                    for candle in data:
                        success, _ = handle_incoming_candle(candle)
                        if success:
                            saved_count += 1
                            
                    # Process the closed candle (which is data[1]) for footprint and rules
                    if len(data) > 1:
                        closed_c = data[1]
                        tf = closed_c.get("timeframe", "M1")
                        symbol = closed_c.get("symbol", "XAUUSD")
                        time_str = closed_c.get("time")
                        
                        from engine.parser import order_flow_tracker_m1, order_flow_tracker_m5
                        tracker = order_flow_tracker_m5 if tf == "M5" else order_flow_tracker_m1
                        
                        state = asyncio.run_coroutine_threadsafe(tracker.get_state(), self.server.loop).result(timeout=2.0)
                        footprint_matrix = state["live_footprint"]
                        
                        if footprint_matrix:
                            # Calculate futures high from footprint keys (in cents)
                            futures_high = max(float(k) / 100.0 for k in footprint_matrix.keys())
                            mt5_high = float(closed_c["high"])
                            price_offset = mt5_high - futures_high
                            
                            # Shift footprint prices
                            shifted_footprint = {}
                            for k_cents, val in footprint_matrix.items():
                                price_val = float(k_cents) / 100.0
                                shifted_price = price_val + price_offset
                                shifted_cents = int(round(shifted_price * 100.0))
                                shifted_footprint[shifted_cents] = val
                                
                            footprint_json = json.dumps(shifted_footprint)
                            
                            # Calculate delta and volume from footprint
                            candle_delta_val = sum(lvl["ask"] - lvl["bid"] for lvl in footprint_matrix.values())
                            fp_volume = sum(lvl["ask"] + lvl["bid"] for lvl in footprint_matrix.values())
                            final_volume = max(int(closed_c["volume"] or 0), int(fp_volume))
                            
                            # Update DB candle with footprint and delta
                            from trade_db import TradeDB
                            db = TradeDB()
                            db.save_candle(
                                symbol=symbol, timeframe=tf, time_str=time_str,
                                open_p=float(closed_c["open"]), high_p=float(closed_c["high"]),
                                low_p=float(closed_c["low"]), close_p=float(closed_c["close"]),
                                volume=final_volume, delta=candle_delta_val, footprint_data=footprint_json,
                                ema34=float(closed_c.get("ema34") or 0.0), ema50=float(closed_c.get("ema50") or 0.0)
                            )
                            logger.info(f"Closed {tf} candle [{time_str}] updated with footprint. Offset: {price_offset:.2f}, Vol: {final_volume}, Delta: {candle_delta_val}")
                            
                            # Evaluate rules
                            ohlc_data = {
                                "open": float(closed_c["open"]),
                                "high": float(closed_c["high"]),
                                "low": float(closed_c["low"]),
                                "close": float(closed_c["close"]),
                                "volume": final_volume,
                                "delta": candle_delta_val,
                                "ema34": float(closed_c.get("ema34") or 0.0),
                                "ema50": float(closed_c.get("ema50") or 0.0)
                            }
                            state_with_tf = state.copy()
                            state_with_tf["timeframe"] = tf
                            
                            from engine.rules import evaluate_rules
                            signal_data = evaluate_rules(
                                state_with_tf, ohlc_data, volume_sma_10=1000,
                                verbose_callback=self.server.scanner.handle_signal_rejection if self.server.scanner else None
                            )
                            if signal_data and self.server.scanner:
                                asyncio.run_coroutine_threadsafe(self.server.scanner.broadcast_order_flow_signal(signal_data), self.server.loop)
                                
                            # Reset tracker footprint for next candle
                            asyncio.run_coroutine_threadsafe(tracker.reset_live_candle(), self.server.loop).result(timeout=2.0)
                            
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(f"OK: Saved {saved_count}/{len(data)} candles".encode('utf-8'))
                else:
                    success, msg = handle_incoming_candle(data)
                    if success:
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b"OK")
                    else:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(f"Error: {msg}".encode('utf-8'))
                        
            elif url_path == "/api/live-prices":
                future = asyncio.run_coroutine_threadsafe(
                    handle_live_price_async(data, self.server.bot, self.server.scanner),
                    self.server.loop
                )
                try:
                    success, msg = future.result(timeout=3.0)
                    if success:
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b"OK")
                    else:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(f"Error: {msg}".encode('utf-8'))
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(f"Timeout/Error: {str(e)}".encode('utf-8'))
            self.wfile.write(b"Not Found")

    def log_message(self, format, *args):
        # Mute logging to keep console clean
        pass

def start_dashboard_server(port: int, bot, loop, scanner):
    """Start the HTTPServer API gateway, attaching bot references."""
    server_address = ('', port)
    try:
        httpd = HTTPServer(server_address, WebDashboardHandler)
        httpd.bot = bot
        httpd.loop = loop
        httpd.scanner = scanner
        logger.info(f"Starting MT5 API Gateway Server on port {port}...")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start API gateway server: {e}")
