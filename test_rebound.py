"""
Local test script to verify all new trading strategies and rebound zone prediction engine
using historical gold_history.csv data.
"""

import pandas as pd
import logging
from analysis_engine import AnalysisEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    logger.info("Initializing AnalysisEngine and loading gold_history.csv...")
    
    # Load historical data (GC=F actual prices)
    df = pd.read_csv("gold_history.csv", parse_dates=['Datetime'], index_col='Datetime')
    df.sort_index(inplace=True)
    print("PROCESSED FIRST CLOSE:", df['Close'].iloc[0])
    
    engine = AnalysisEngine()
    
    # Test strategy analyses on the latest 200 candles
    test_window = df.tail(200)
    
    logger.info("Testing Mean Reversion Analysis...")
    mr = engine.analyze_mean_reversion(test_window)
    print("Mean Reversion Result:", mr)
    
    logger.info("Testing Momentum Breakout Analysis...")
    mom = engine.analyze_momentum_breakout(test_window)
    print("Momentum Breakout Result:", mom)
    
    logger.info("Testing Volume Profile Analysis...")
    vp = engine.analyze_volume_profile(test_window)
    print("Volume Profile Result (POC/VAH/VAL):", vp)
    
    logger.info("Testing Pivot & Fib Rebound Analysis...")
    piv = engine.analyze_pivot_rebound(test_window)
    print("Pivots:", piv.get('pivots'))
    print("Fibs (Partial):", {k: v for k, v in list(piv.get('fibs', {}).items())[:4]})
    
    logger.info("Testing Rebound Zone Predictor (Confidence 80%-95%)...")
    prediction = engine.predict_rebound_zones(test_window)
    if prediction:
        print("💡 PREDICTION FOUND!")
        print("Direction:", prediction['direction'])
        print(f"Zone: ${prediction['zone_low']:.2f} - ${prediction['zone_high']:.2f}")
        print("Confidence:", prediction['confidence'], "%")
        print("Confluence Factors:", prediction['reasons'])
    else:
        print("❌ No high-probability rebound zone found in this window.")
        
    # Search history for a window that DOES contain a high confidence prediction to verify formatting
    logger.info("Searching historical slices for a high confidence prediction...")
    found = False
    for i in range(100, len(df), 20):
        slice_df = df.iloc[i-100:i]
        pred = engine.predict_rebound_zones(slice_df)
        if pred and pred['confidence'] >= 80:
            print(f"\n🌟 High Confidence Rebound Zone found at slice index {i}:")
            print("Direction:", pred['direction'])
            print(f"Zone: ${pred['zone_low']:.2f} - ${pred['zone_high']:.2f}")
            print("Confidence:", pred['confidence'], "%")
            print("Confluence Factors:", pred['reasons'])
            found = True
            break
            
    if not found:
        print("\nℹ️ No historical confluences >= 80% found, checking >= 75% confluences:")
        for i in range(100, len(df), 20):
            slice_df = df.iloc[i-100:i]
            pred = engine.predict_rebound_zones(slice_df)
            if pred and pred['confidence'] >= 75:
                print(f"Moderate Confidence Rebound Zone found at slice index {i}:")
                print("Direction:", pred['direction'])
                print(f"Zone: ${pred['zone_low']:.2f} - ${pred['zone_high']:.2f}")
                print("Confidence:", pred['confidence'], "%")
                print("Confluence Factors:", pred['reasons'])
                break


if __name__ == "__main__":
    main()
