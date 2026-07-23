from typing import Dict, List, Tuple, Optional, Any
from engine.profile import price_to_cents, cents_to_price, TICK_SIZE_CENTS

class FootprintAnalysis:
    """
    Analyzes live candle footprints for aggressive imbalances,
    absorption levels, and exhaustions.
    """
    def __init__(self, footprint_matrix: Dict[int, Dict[str, int]]):
        # Ensure all keys are parsed as integers to prevent string-key crashes
        self.matrix = {}
        if footprint_matrix:
            for k, v in footprint_matrix.items():
                try:
                    self.matrix[int(k)] = v
                except (ValueError, TypeError):
                    pass

    def get_diagonal_imbalances(self, imbalance_ratio: float = 2.5) -> Tuple[Dict[int, bool], Dict[int, bool]]:
        """
        Detects buying and selling diagonal imbalances.
        Compare Bid at price P with Ask at price P + 1 tick (diagonal buying),
        and Ask at price P with Bid at price P - 1 tick (diagonal selling).
        """
        ask_imbalances: Dict[int, bool] = {}
        bid_imbalances: Dict[int, bool] = {}

        for p_cents in self.matrix:
            # 1. Check buying imbalance: Ask at (P + 1 tick) compared to Bid at P
            next_cents = p_cents + TICK_SIZE_CENTS
            if next_cents in self.matrix:
                bid_vol = self.matrix[p_cents].get("bid", 0)
                ask_vol = self.matrix[next_cents].get("ask", 0)
                if bid_vol > 0 and ask_vol >= bid_vol * imbalance_ratio:
                    ask_imbalances[next_cents] = True

            # 2. Check selling imbalance: Bid at (P - 1 tick) compared to Ask at P
            prev_cents = p_cents - TICK_SIZE_CENTS
            if prev_cents in self.matrix:
                ask_vol = self.matrix[p_cents].get("ask", 0)
                bid_vol = self.matrix[prev_cents].get("bid", 0)
                if ask_vol > 0 and bid_vol >= ask_vol * imbalance_ratio:
                    bid_imbalances[prev_cents] = True

        return ask_imbalances, bid_imbalances

    def get_stacked_imbalances(self, ask_imb: Dict[int, bool], bid_imb: Dict[int, bool]) -> Tuple[List[float], List[float]]:
        """
        Finds stacked imbalances (2 or more price levels anywhere with active imbalances).
        """
        stacked_ask_levels = []
        stacked_bid_levels = []

        # If there are at least 2 ask imbalances anywhere, they are stacked ask imbalances
        if len(ask_imb) >= 2:
            stacked_ask_levels = [cents_to_price(c) for c in ask_imb.keys()]

        # If there are at least 2 bid imbalances anywhere, they are stacked bid imbalances
        if len(bid_imb) >= 2:
            stacked_bid_levels = [cents_to_price(c) for c in bid_imb.keys()]

        return stacked_ask_levels, stacked_bid_levels

    def detect_absorption(self, open_p: float, close_p: float, high_p: float, low_p: float, 
                          support_level: float = 0.0, resistance_level: float = 0.0) -> Tuple[bool, bool, Dict[str, Any]]:
        """
        Detects wick absorption: high volume executed on wicks where price reversed.
        Support/Bullish: high volume on Bid at the bottom 20% wick, physical bottom wick >= 20% of range, positive candle delta.
        Resistance/Bearish: high volume on Ask at the top 20% wick, physical top wick >= 20% of range, negative candle delta.
        """
        bullish_absorption = False
        bearish_absorption = False
        
        range_val = high_p - low_p
        metadata = {
            "bottom_wick_ratio": 0.0,
            "top_wick_ratio": 0.0,
            "bottom_wick_vol": 0,
            "top_wick_vol": 0,
            "total_candle_vol": 0,
            "val_distance": 999.0,
            "vah_distance": 999.0,
            "wick_range_ratio_threshold": 0.20,
            "wick_volume_ratio_threshold": 0.20,
            "proximity_threshold": 1.5,
            "candle_delta": 0,
            "bottom_wick_range_ratio": 0.0,
            "top_wick_range_ratio": 0.0
        }
        if range_val <= 0:
            return False, False, metadata

        body_low = min(open_p, close_p)
        body_high = max(open_p, close_p)

        bottom_wick_threshold = low_p + range_val * 0.20
        top_wick_threshold = high_p - range_val * 0.20

        # Physical wick ranges
        metadata["bottom_wick_range_ratio"] = (body_low - low_p) / range_val
        metadata["top_wick_range_ratio"] = (high_p - body_high) / range_val

        total_bottom_wick_vol = 0
        total_top_wick_vol = 0
        total_candle_vol = 0
        candle_delta = 0

        for p_cents, vols in self.matrix.items():
            price = cents_to_price(p_cents)
            bid = vols.get("bid", 0)
            ask = vols.get("ask", 0)
            vol = bid + ask
            total_candle_vol += vol
            candle_delta += (ask - bid)
            
            if price <= bottom_wick_threshold:
                total_bottom_wick_vol += vol
            if price >= top_wick_threshold:
                total_top_wick_vol += vol

        metadata["total_candle_vol"] = total_candle_vol
        metadata["bottom_wick_vol"] = total_bottom_wick_vol
        metadata["top_wick_vol"] = total_top_wick_vol
        metadata["candle_delta"] = candle_delta
        
        if total_candle_vol > 0:
            metadata["bottom_wick_ratio"] = total_bottom_wick_vol / total_candle_vol
            metadata["top_wick_ratio"] = total_top_wick_vol / total_candle_vol

        if support_level > 0:
            metadata["val_distance"] = abs(low_p - support_level)
        if resistance_level > 0:
            metadata["vah_distance"] = abs(high_p - resistance_level)

        if total_candle_vol > 0:
            # Bullish absorption: wick range >= 20%, wick vol >= 20% (delta supports is handled in rules check)
            if (metadata["bottom_wick_range_ratio"] >= 0.20 and 
                metadata["bottom_wick_ratio"] >= 0.20):
                bullish_absorption = True
                
            # Bearish absorption: wick range >= 20%, wick vol >= 20%
            if (metadata["top_wick_range_ratio"] >= 0.20 and 
                metadata["top_wick_ratio"] >= 0.20):
                bearish_absorption = True

        return bullish_absorption, bearish_absorption, metadata

    def detect_exhaustion(self, high_p: float, low_p: float) -> Tuple[bool, bool]:
        """
        Detects buyers/sellers exhaustion at extreme prices (extreme low volumes at peaks/valleys).
        """
        bullish_exhaustion = False
        bearish_exhaustion = False

        low_cents = price_to_cents(low_p)
        high_cents = price_to_cents(high_p)

        # Bullish exhaustion: extremely low Ask volume at low price
        if low_cents in self.matrix:
            ask_vol = self.matrix[low_cents].get("ask", 0)
            if ask_vol <= 2:
                bullish_exhaustion = True

        # Bearish exhaustion: extremely low Bid volume at high price
        if high_cents in self.matrix:
            bid_vol = self.matrix[high_cents].get("bid", 0)
            if bid_vol <= 2:
                bearish_exhaustion = True

        return bullish_exhaustion, bearish_exhaustion
