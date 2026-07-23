import math
from typing import Dict, List, Tuple, Optional

TICK_SIZE_CENTS = 5  # 0.05 for XAUUSD

def price_to_cents(price: float) -> int:
    """Converts price float to mapped integer cents (discrete tick buckets)."""
    return int(round(price * 100 / TICK_SIZE_CENTS) * TICK_SIZE_CENTS)

def cents_to_price(cents: int) -> float:
    """Converts discrete tick bucket back to price float."""
    return float(cents) / 100.0

class VolumeProfile:
    """
    Manages session-level volume profiles mapped to discrete tick cents.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        # Maps price cent (int) -> volume (int)
        self.profile: Dict[int, int] = {}
        self.total_volume = 0

    def add_trade(self, price: float, volume: float):
        if volume <= 0:
            return
        p_cents = price_to_cents(price)
        self.profile[p_cents] = self.profile.get(p_cents, 0) + int(volume)
        self.total_volume += int(volume)

    def get_poc(self) -> Optional[float]:
        """Returns Point of Control (price level with max volume)."""
        if not self.profile:
            return None
        max_cents = max(self.profile, key=self.profile.get)
        return cents_to_price(max_cents)

    def get_value_area(self, poc_cents: int, percentage: float = 0.70) -> Tuple[float, float]:
        """
        Expands outward from POC to identify the Value Area (VAH and VAL)
        housing 70% of total session volume.
        """
        if not self.profile or self.total_volume == 0:
            return 0.0, 0.0

        target_volume = int(self.total_volume * percentage)
        accumulated_volume = self.profile.get(poc_cents, 0)

        lower_cents = poc_cents - TICK_SIZE_CENTS
        upper_cents = poc_cents + TICK_SIZE_CENTS

        min_cents = min(self.profile.keys())
        max_cents = max(self.profile.keys())

        while accumulated_volume < target_volume:
            if lower_cents < min_cents and upper_cents > max_cents:
                break # out of bounds of the entire profile

            vol_low = self.profile.get(lower_cents, 0)
            vol_high = self.profile.get(upper_cents, 0)

            # Compare adjacent upper and lower nodes
            if vol_low >= vol_high and vol_low > 0:
                accumulated_volume += vol_low
                lower_cents -= TICK_SIZE_CENTS
            elif vol_high > vol_low and vol_high > 0:
                accumulated_volume += vol_high
                upper_cents += TICK_SIZE_CENTS
            else:
                # If both are 0, expand both boundaries to skip empty gaps
                lower_cents -= TICK_SIZE_CENTS
                upper_cents += TICK_SIZE_CENTS

        val = cents_to_price(lower_cents + TICK_SIZE_CENTS)
        vah = cents_to_price(upper_cents - TICK_SIZE_CENTS)
        return val, vah

    def get_hvn_lvn(self) -> Tuple[List[float], List[float]]:
        """
        Identifies prominent High Volume Nodes (HVNs) and Low Volume Nodes (LVNs)
        using local extrema peak detection.
        """
        if len(self.profile) < 5:
            return [], []

        sorted_cents = sorted(self.profile.keys())
        hvns = []
        lvns = []

        # 3-node sliding window to detect local peaks/valleys
        for i in range(1, len(sorted_cents) - 1):
            prev_v = self.profile[sorted_cents[i - 1]]
            curr_v = self.profile[sorted_cents[i]]
            next_v = self.profile[sorted_cents[i + 1]]

            # HVN: local peak
            if curr_v > prev_v and curr_v > next_v:
                hvns.append(cents_to_price(sorted_cents[i]))
            # LVN: local valley
            elif curr_v < prev_v and curr_v < next_v:
                lvns.append(cents_to_price(sorted_cents[i]))

        return hvns[:5], lvns[:5]  # Limit to top 5 nodes
