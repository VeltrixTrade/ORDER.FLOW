import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.rules import evaluate_rules
from trade_db import TradeDB

def test():
    print("Testing Strategy Rules Evaluator...")
    # Mock order flow state
    state = {
        "val": 4000.0,
        "vah": 4010.0,
        "poc": 4005.0,
        "vwap": 4004.0,
        "cvd": 500, # confirmed buyer pressure
        "std_dev": 2.5,
        "m1": {
            "ema10": 4008.0,
            "ema34": 4004.0,
            "ema50": 4002.0
        },
        "m5": {
            "ema10": 4015.0,
            "ema34": 4009.0,
            "ema50": 4006.0
        }
    }
    
    # Mock M5 candle with separate EMAs to trigger Trend Continuation BUY
    ohlc = {
        "open": 4009.0,
        "high": 4016.0,
        "low": 4008.0,
        "close": 4015.0,
        "volume": 250, # confirmed volume > volume_sma_10 (100)
        "delta": 80.0,
        "ema34": 4009.0,
        "ema50": 4006.0
    }
    
    print("Running evaluate_rules for Trend Continuation BUY setup...")
    res = evaluate_rules(state, ohlc, volume_sma_10=100)
    print("Result:", json.dumps(res, indent=4) if res else "No signal generated.")
    
    # Test DB
    print("\nTesting Database Connection and rejected signals logging...")
    db = TradeDB()
    # Log a rejected signal
    db.log_rejected_signal(
        signal_type="Trend Continuation BUY",
        price_near_boundary=1,
        volume_confirmed=0,
        stacked_imbalance=1,
        absorption=0,
        reason="Low Volume",
        metrics_snapshot=state
    )
    print("Rejected signal logged successfully!")
    
    # Query database to confirm
    cursor = db.conn.execute("SELECT * FROM rejected_signals ORDER BY id DESC LIMIT 1;")
    row = cursor.fetchone()
    if row:
        print("Retrieved from DB:", dict(row))
    else:
        print("Failed to retrieve from DB.")
        
if __name__ == "__main__":
    test()
