import unittest
import os
import json
from unittest.mock import MagicMock, patch

from engine.rules import evaluate_rules, load_monitoring_state, save_monitoring_state
from engine.profile import price_to_cents

class TestOrderFlowRulesEngine(unittest.TestCase):

    def setUp(self):
        # Reset monitoring state before each test
        state = {
            "is_monitoring": False,
            "monitored_candles_count": 0,
            "trend_bias": None,
            "consecutive_closes_outside": 0
        }
        save_monitoring_state(state)

    def tearDown(self):
        # Clean up state file
        if os.path.exists("database/monitoring_state.json"):
            try:
                os.remove("database/monitoring_state.json")
            except Exception:
                pass

    def test_wave_zone_monitoring_trigger(self):
        """Verifies that monitoring mode starts when price touches the wave zone."""
        # Setup mock db and prices
        state = {
            "timeframe": "M5",
            "val": 2350.00,
            "vah": 2360.00,
            "poc": 2355.00
        }
        
        # Candle intersects the wave zone [2350.0, 2355.0]
        # Previous trend was BUY (price completely above wave zone previously)
        # Low price is 2351.0 (touches wave zone), High is 2361.0
        ohlc = {
            "open": 2360.0,
            "high": 2361.0,
            "low": 2351.0,
            "close": 2358.0,
            "volume": 500
        }
        
        # Patch db calls to return EMA34 = 2355.0 and EMA50 = 2350.0
        with patch("engine.rules.get_ema_values") as mock_ema:
            mock_ema.return_value = (2355.0, 2350.0)
            
            # Initial evaluation (low <= 2355.0 and high >= 2350.0 -> touches wave zone)
            signal = evaluate_rules(state, ohlc, volume_sma_10=1000)
            
            # Check state
            m_state = load_monitoring_state()
            self.assertTrue(m_state["is_monitoring"])
            self.assertEqual(m_state["monitored_candles_count"], 1)

    def test_scoring_system_buy_trigger(self):
        """Verifies that a BUY signal triggers when score >= 75%."""
        state = {
            "timeframe": "M5",
            "val": 2350.00,
            "vah": 2360.00,
            "poc": 2355.00,
            "live_footprint": {
                price_to_cents(2352.00): {"bid": 10, "ask": 150},
                price_to_cents(2351.75): {"bid": 15, "ask": 180},
                price_to_cents(2350.00): {"bid": 300, "ask": 5} # Trapped sellers / absorption
            }
        }
        
        # Candle: Volume confirmed, stacked ask imbalance present, absorption present, delta is positive
        # This should give 100% score (all 4 conditions met)
        ohlc = {
            "open": 2352.00,
            "high": 2356.00,
            "low": 2350.00,
            "close": 2354.00,
            "volume": 1200
        }
        
        # Setup monitoring state to simulate active monitoring
        m_state = {
            "is_monitoring": True,
            "monitored_candles_count": 1,
            "trend_bias": "BUY",
            "consecutive_closes_outside": 0
        }
        save_monitoring_state(m_state)
        
        with patch("engine.rules.get_ema_values") as mock_ema:
            mock_ema.return_value = (2353.0, 2348.0) # Wave zone: [2348.0, 2353.0]
            
            signal = evaluate_rules(state, ohlc, volume_sma_10=1000)
            
            self.assertIsNotNone(signal)
            self.assertEqual(signal["type"], "BUY")
            self.assertEqual(signal["confidence"], 100.0)
            self.assertEqual(signal["stop_loss"], 2348.0 - 2.0) # Wave bottom (2348.0) - 2.0 = 2346.0
            self.assertEqual(signal["take_profit_1"], 2354.0 + (2354.0 - 2346.0)) # Entry + Risk = 2354.0 + 8.0 = 2362.0

if __name__ == "__main__":
    unittest.main()
