import math

class IncrementalVWAP:
    """
    Computes VWAP and Standard Deviation Bands in O(1) time complexity.
    Uses Welford's algorithm for running variance.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.sum_pv = 0.0      # Sum of (Price * Volume)
        self.sum_v = 0.0       # Sum of Volume
        self.vwap = 0.0
        
        # Variance (Welford's tracking parameters)
        self.count = 0
        self.mean_p = 0.0
        self.M2 = 0.0
        self.variance = 0.0

    def update(self, price: float, volume: float):
        if volume <= 0:
            return

        # 1. Update VWAP
        self.sum_pv += price * volume
        self.sum_v += volume
        self.vwap = self.sum_pv / self.sum_v

        # 2. Update variance using Welford's algorithm
        self.count += 1
        delta = price - self.mean_p
        self.mean_p += delta / self.count
        delta2 = price - self.mean_p
        self.M2 += delta * delta2

        if self.count > 1:
            self.variance = self.M2 / (self.count - 1)
        else:
            self.variance = 0.0

    def get_std_dev(self) -> float:
        """Returns standard deviation of price."""
        return math.sqrt(self.variance)
