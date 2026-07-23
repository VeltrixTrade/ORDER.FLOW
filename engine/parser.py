import asyncio
from typing import Dict, List
from engine.profile import VolumeProfile, price_to_cents, cents_to_price
from engine.vwap import IncrementalVWAP

class TickBuffer:
    """
    Thread-safe circular list buffer holding raw ticks for time-window calculations.
    """
    def __init__(self, capacity: int = 15000):
        self.capacity = capacity
        self.buffer: List[dict] = []
        self.lock = asyncio.Lock()

    async def add(self, tick: dict):
        async with self.lock:
            self.buffer.append(tick)
            if len(self.buffer) > self.capacity:
                self.buffer.pop(0)

    async def get_all(self) -> List[dict]:
        async with self.lock:
            return self.buffer.copy()

    async def clear(self):
        async with self.lock:
            self.buffer.clear()

class RealTimeOrderFlowTracker:
    """
    Coordinator managing the live order book telemetry ingestion
    and routing state updates across profile and VWAP engines.
    """
    def __init__(self, timeframe: str = "M1"):
        self.timeframe = timeframe
        self.volume_profile = VolumeProfile()
        self.vwap_engine = IncrementalVWAP()
        self.tick_buffer = TickBuffer()
        
        # Candle aggregation states
        self.active_candle_start = 0
        self.active_candle_end = 0
        
        # Maps price cents -> {"bid": volume, "ask": volume}
        self.live_footprint: Dict[int, Dict[str, int]] = {}
        
        # CVD (Cumulative Volume Delta) running session register
        self.cvd_register = 0
        self.lock = asyncio.Lock()

    async def process_tick(self, price: float, volume: float, side: str, timestamp_ms: int):
        if volume <= 0:
            return

        async with self.lock:
            # 1. Update footprint matrix
            p_cents = price_to_cents(price)
            if p_cents not in self.live_footprint:
                self.live_footprint[p_cents] = {"bid": 0, "ask": 0}

            side_clean = side.upper()
            if side_clean == "ASK":
                # Lifting the Ask (Aggressive buying)
                self.live_footprint[p_cents]["ask"] += int(volume)
                self.cvd_register += int(volume)
            else:
                # Hitting the Bid (Aggressive selling)
                self.live_footprint[p_cents]["bid"] += int(volume)
                self.cvd_register -= int(volume)

            # 2. Add to raw tick buffer history
            await self.tick_buffer.add({
                "price": price,
                "volume": volume,
                "side": side_clean,
                "timestamp": timestamp_ms
            })

            # 3. Add to daily volume profile
            self.volume_profile.add_trade(price, volume)

            # 4. Accumulate VWAP
            self.vwap_engine.update(price, volume)

    async def reset_live_candle(self):
        """Resets the 5-minute candle footprint bin."""
        async with self.lock:
            self.live_footprint.clear()

    async def get_state(self) -> dict:
        """Returns a snapshot of the current session calculations."""
        async with self.lock:
            # Calculate CVD dynamically from database + live footprint
            try:
                from trade_db import TradeDB
                db = TradeDB()
                candles = db.get_candles("XAUUSD", self.timeframe, limit=300)
                # Sum of deltas of all closed candles
                historical_delta_sum = sum(float(c.get("delta") or 0.0) for c in candles)
            except Exception:
                historical_delta_sum = 0.0

            live_delta = sum(lvl["ask"] - lvl["bid"] for lvl in self.live_footprint.values())
            self.cvd_register = int(historical_delta_sum + live_delta)

            poc = self.volume_profile.get_poc()
            
            # Fallback to candle history if no live ticks have populated the profile yet
            if not poc or poc == 0.0:
                try:
                    from trade_db import TradeDB
                    db = TradeDB()
                    # Fetch last 300 candles for this timeframe
                    candles = db.get_candles("XAUUSD", self.timeframe, limit=300)
                    if candles:
                        temp_profile = VolumeProfile()
                        temp_vwap_sum = 0.0
                        temp_vol_sum = 0.0
                        for c in candles:
                            close_p = float(c["close"])
                            vol = float(c.get("volume") or 0.0)
                            if vol > 0:
                                temp_profile.add_trade(close_p, vol)
                                temp_vwap_sum += close_p * vol
                                temp_vol_sum += vol
                        
                        temp_poc = temp_profile.get_poc()
                        if temp_poc and temp_poc > 0.0:
                            poc_cents = price_to_cents(temp_poc)
                            val, vah = temp_profile.get_value_area(poc_cents)
                            hvn, lvn = temp_profile.get_hvn_lvn()
                            vwap = temp_vwap_sum / temp_vol_sum if temp_vol_sum > 0 else temp_poc
                            std_dev = 2.50  # default approximation
                            
                            return {
                                "poc": temp_poc,
                                "vah": vah,
                                "val": val,
                                "hvn": hvn,
                                "lvn": lvn,
                                "vwap": vwap,
                                "std_dev": std_dev,
                                "cvd": self.cvd_register,
                                "live_footprint": self.live_footprint.copy()
                            }
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"Fallback candle profile calculation failed: {e}")

            poc_cents = price_to_cents(poc) if poc else 0
            val, vah = self.volume_profile.get_value_area(poc_cents)
            hvn, lvn = self.volume_profile.get_hvn_lvn()

            return {
                "poc": poc,
                "vah": vah,
                "val": val,
                "hvn": hvn,
                "lvn": lvn,
                "vwap": self.vwap_engine.vwap,
                "std_dev": self.vwap_engine.get_std_dev(),
                "cvd": self.cvd_register,
                "live_footprint": self.live_footprint.copy()
            }

    async def full_reset(self):
        """Clears both active candle and daily session caches."""
        async with self.lock:
            self.live_footprint.clear()
            self.volume_profile.reset()
            self.vwap_engine.reset()
            self.cvd_register = 0
            await self.tick_buffer.clear()

order_flow_tracker_m1 = RealTimeOrderFlowTracker("M1")
order_flow_tracker_m5 = RealTimeOrderFlowTracker("M5")
order_flow_tracker = order_flow_tracker_m1
