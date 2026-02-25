"""
DIAGNOSTIC TEST - Check Why Specific Signals Were Missed
Tests the exact logic against your reported signals to find where it's failing
"""
import requests
import pandas as pd
from datetime import datetime, timedelta

# Strategy parameters (from your code)
RSI_PERIOD = 14
EMA_SHORT = 9
EMA_LONG = 26
MA_PERIOD = 44
RSI_LONG_MIN = 45.1
RSI_LONG_MAX = 85
RSI_SHORT_MIN = 10
RSI_SHORT_MAX = 45

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    prices = pd.Series(closes)
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

def calculate_ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    prices = pd.Series(closes)
    ema = prices.ewm(span=period, adjust=False).mean()
    return float(ema.iloc[-1])

def calculate_sma(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    return sum(closes[-period:]) / period

def get_candle_at_time(symbol, target_time_utc, lookback_candles=150):
    """Get candle data at specific time with enough history for indicators"""
    
    # Convert to timestamp
    target_ts = int(target_time_utc.timestamp() * 1000)
    
    # Get candles before this time for indicator calculation
    start_ts = target_ts - (lookback_candles * 15 * 60 * 1000)
    end_ts = target_ts + (15 * 60 * 1000)  # Include the target candle
    
    url = "https://api.binance.com/api/v3/klines"
    
    response = requests.get(
        url,
        params={
            'symbol': symbol,
            'interval': '15m',
            'startTime': start_ts,
            'endTime': end_ts,
            'limit': 200
        },
        timeout=10
    )
    
    if response.status_code != 200:
        return None
    
    candles = response.json()
    
    if not isinstance(candles, list) or len(candles) == 0:
        return None
    
    return candles

def test_signal(test_name, symbol, utc_time, expected_signal, expected_values):
    """Test a specific signal scenario"""
    
    print("="*80)
    print(f"TEST: {test_name}")
    print("="*80)
    print(f"Symbol: {symbol}")
    print(f"Time (UTC): {utc_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"Expected Signal: {expected_signal}")
    print()
    
    # Get candle data
    candles = get_candle_at_time(symbol, utc_time)
    
    if not candles:
        print("❌ ERROR: Could not fetch candle data")
        return False
    
    print(f"✅ Fetched {len(candles)} candles for analysis")
    print()
    
    # Find the exact candle at target time
    target_ts = int(utc_time.timestamp() * 1000)
    target_candle_idx = None
    
    for i, candle in enumerate(candles):
        candle_time = candle[0]
        # Check if this is the 15-min candle that contains our target time
        if candle_time <= target_ts < candle_time + (15 * 60 * 1000):
            target_candle_idx = i
            break
    
    if target_candle_idx is None:
        print("❌ ERROR: Could not find candle at target time")
        return False
    
    print(f"✅ Found target candle at index {target_candle_idx}")
    print()
    
    # Get price data up to target candle
    closes = [float(c[4]) for c in candles[:target_candle_idx+1]]
    opens = [float(c[1]) for c in candles[:target_candle_idx+1]]
    
    if len(closes) < MA_PERIOD + 10:
        print(f"❌ ERROR: Not enough data for indicators (have {len(closes)}, need {MA_PERIOD + 10})")
        return False
    
    # Calculate indicators
    rsi = calculate_rsi(closes, RSI_PERIOD)
    ema9 = calculate_ema(closes, EMA_SHORT)
    ema26 = calculate_ema(closes, EMA_LONG)
    ma44 = calculate_sma(closes, MA_PERIOD)
    
    # Previous values
    ema9_prev = calculate_ema(closes[:-1], EMA_SHORT)
    ema26_prev = calculate_ema(closes[:-1], EMA_LONG)
    ma44_prev = calculate_sma(closes[:-1], MA_PERIOD)
    
    current_close = closes[-1]
    current_open = opens[-1]
    
    # MA Slope
    ma_slope = ma44 - calculate_sma(closes[:-5], MA_PERIOD)
    
    # Print calculated values
    print("📊 CALCULATED INDICATORS:")
    print(f"   Price:   ${current_close:.2f}")
    print(f"   RSI:     {rsi:.2f}")
    print(f"   EMA 9:   ${ema9:.2f}")
    print(f"   EMA 26:  ${ema26:.2f}")
    print(f"   MA 44:   ${ma44:.2f}")
    print()
    
    # Compare with expected values
    print("📋 YOUR REPORTED VALUES:")
    print(f"   Price:   ${expected_values['price']:.2f}")
    print(f"   RSI:     {expected_values['rsi']:.2f}")
    print(f"   EMA 9:   ${expected_values['ema9']:.2f}")
    print(f"   EMA 26:  ${expected_values['ema26']:.2f}")
    print(f"   MA 44:   ${expected_values['ma44']:.2f}")
    print()
    
    # Check differences
    print("🔍 COMPARISON (Calculated vs Expected):")
    print(f"   Price difference:   ${abs(current_close - expected_values['price']):.2f}")
    print(f"   RSI difference:     {abs(rsi - expected_values['rsi']):.2f}")
    print(f"   EMA 9 difference:   ${abs(ema9 - expected_values['ema9']):.2f}")
    print(f"   EMA 26 difference:  ${abs(ema26 - expected_values['ema26']):.2f}")
    print(f"   MA 44 difference:   ${abs(ma44 - expected_values['ma44']):.2f}")
    print()
    
    # Now check ALL 5 conditions
    print("="*80)
    print("CHECKING ALL 5 STRATEGY CONDITIONS:")
    print("="*80)
    print()
    
    if expected_signal == 'LONG':
        # LONG CONDITIONS
        print("🟢 LONG SIGNAL CONDITIONS:")
        print()
        
        # Condition 1: RSI Range
        rsi_long_ok = RSI_LONG_MIN <= rsi <= RSI_LONG_MAX
        print(f"1️⃣  RSI in range ({RSI_LONG_MIN} to {RSI_LONG_MAX})")
        print(f"   Current RSI: {rsi:.2f}")
        print(f"   Status: {'✅ PASS' if rsi_long_ok else '❌ FAIL'}")
        if not rsi_long_ok:
            if rsi < RSI_LONG_MIN:
                print(f"   ⚠️  RSI too low (need ≥{RSI_LONG_MIN})")
            else:
                print(f"   ⚠️  RSI too high (need ≤{RSI_LONG_MAX})")
        print()
        
        # Condition 2: EMA Cross
        ema_cross_up = (ema9_prev <= ema26_prev) and (ema9 > ema26)
        print(f"2️⃣  EMA 9 crosses above EMA 26")
        print(f"   Previous: EMA9={ema9_prev:.2f}, EMA26={ema26_prev:.2f} (EMA9 {'<=' if ema9_prev <= ema26_prev else '>'} EMA26)")
        print(f"   Current:  EMA9={ema9:.2f}, EMA26={ema26:.2f} (EMA9 {'>' if ema9 > ema26 else '<='} EMA26)")
        print(f"   Status: {'✅ PASS' if ema_cross_up else '❌ FAIL'}")
        if not ema_cross_up:
            if ema9_prev > ema26_prev:
                print(f"   ⚠️  EMA9 was already above EMA26 (not a fresh cross)")
            if ema9 <= ema26:
                print(f"   ⚠️  EMA9 not above EMA26 now")
        print()
        
        # Condition 3: Both EMAs crossed above MA44
        both_above = (ema9 > ma44) and (ema26 > ma44)
        ema9_crossed_up = (ema9_prev <= ma44_prev) and (ema9 > ma44)
        ema26_crossed_up = (ema26_prev <= ma44_prev) and (ema26 > ma44)
        both_crossed_up = both_above and (ema9_crossed_up or ema26_crossed_up)
        
        print(f"3️⃣  Both EMAs crossed above MA 44")
        print(f"   EMA9 > MA44: {ema9:.2f} > {ma44:.2f} = {'✅' if ema9 > ma44 else '❌'}")
        print(f"   EMA26 > MA44: {ema26:.2f} > {ma44:.2f} = {'✅' if ema26 > ma44 else '❌'}")
        print(f"   EMA9 crossed up: {'✅' if ema9_crossed_up else '❌'} (was {ema9_prev:.2f}, MA44 was {ma44_prev:.2f})")
        print(f"   EMA26 crossed up: {'✅' if ema26_crossed_up else '❌'} (was {ema26_prev:.2f}, MA44 was {ma44_prev:.2f})")
        print(f"   Status: {'✅ PASS' if both_crossed_up else '❌ FAIL'}")
        if not both_crossed_up:
            if not both_above:
                print(f"   ⚠️  Not both EMAs above MA44")
            elif not (ema9_crossed_up or ema26_crossed_up):
                print(f"   ⚠️  Neither EMA crossed MA44 recently (already above)")
        print()
        
        # Condition 4: MA44 Slope
        slope_up = ma_slope > 0
        print(f"4️⃣  MA 44 has upward slope")
        print(f"   MA44 slope: {ma_slope:.4f}")
        print(f"   Status: {'✅ PASS' if slope_up else '❌ FAIL'}")
        if not slope_up:
            print(f"   ⚠️  MA44 is flat or declining")
        print()
        
        # Condition 5: Candle Pattern
        bullish = current_close > current_open
        above_mas = current_close > max(ema9, ema26, ma44)
        candle_ok_long = bullish and above_mas
        
        print(f"5️⃣  Bullish candle above all MAs")
        print(f"   Candle: Open=${current_open:.2f}, Close=${current_close:.2f}")
        print(f"   Bullish: {'✅' if bullish else '❌'} (close > open)")
        print(f"   Above EMA9: {'✅' if current_close > ema9 else '❌'} ({current_close:.2f} vs {ema9:.2f})")
        print(f"   Above EMA26: {'✅' if current_close > ema26 else '❌'} ({current_close:.2f} vs {ema26:.2f})")
        print(f"   Above MA44: {'✅' if current_close > ma44 else '❌'} ({current_close:.2f} vs {ma44:.2f})")
        print(f"   Status: {'✅ PASS' if candle_ok_long else '❌ FAIL'}")
        if not candle_ok_long:
            if not bullish:
                print(f"   ⚠️  Candle is bearish (close < open)")
            if not above_mas:
                print(f"   ⚠️  Close not above all moving averages")
        print()
        
        # Final verdict
        long_signal = (rsi_long_ok and ema_cross_up and both_crossed_up and 
                      slope_up and candle_ok_long)
        
        print("="*80)
        print(f"🎯 FINAL RESULT: {'✅ SIGNAL GENERATED' if long_signal else '❌ NO SIGNAL'}")
        print("="*80)
        
        if not long_signal:
            print()
            print("❌ FAILED CONDITIONS:")
            if not rsi_long_ok:
                print(f"   • RSI not in valid range")
            if not ema_cross_up:
                print(f"   • EMA9 did not cross above EMA26")
            if not both_crossed_up:
                print(f"   • EMAs did not cross above MA44")
            if not slope_up:
                print(f"   • MA44 slope not positive")
            if not candle_ok_long:
                print(f"   • Candle pattern invalid")
        
        return long_signal
        
    else:  # SHORT
        # SHORT CONDITIONS
        print("🔴 SHORT SIGNAL CONDITIONS:")
        print()
        
        # Condition 1: RSI Range
        rsi_short_ok = RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX
        print(f"1️⃣  RSI in range ({RSI_SHORT_MIN} to {RSI_SHORT_MAX})")
        print(f"   Current RSI: {rsi:.2f}")
        print(f"   Status: {'✅ PASS' if rsi_short_ok else '❌ FAIL'}")
        if not rsi_short_ok:
            if rsi < RSI_SHORT_MIN:
                print(f"   ⚠️  RSI too low (need ≥{RSI_SHORT_MIN})")
            else:
                print(f"   ⚠️  RSI too high (need ≤{RSI_SHORT_MAX})")
        print()
        
        # Condition 2: EMA Cross
        ema_cross_down = (ema9_prev >= ema26_prev) and (ema9 < ema26)
        print(f"2️⃣  EMA 9 crosses below EMA 26")
        print(f"   Previous: EMA9={ema9_prev:.2f}, EMA26={ema26_prev:.2f} (EMA9 {'>=' if ema9_prev >= ema26_prev else '<'} EMA26)")
        print(f"   Current:  EMA9={ema9:.2f}, EMA26={ema26:.2f} (EMA9 {'<' if ema9 < ema26 else '>='} EMA26)")
        print(f"   Status: {'✅ PASS' if ema_cross_down else '❌ FAIL'}")
        if not ema_cross_down:
            if ema9_prev < ema26_prev:
                print(f"   ⚠️  EMA9 was already below EMA26 (not a fresh cross)")
            if ema9 >= ema26:
                print(f"   ⚠️  EMA9 not below EMA26 now")
        print()
        
        # Condition 3: Both EMAs crossed below MA44
        both_below = (ema9 < ma44) and (ema26 < ma44)
        ema9_crossed_down = (ema9_prev >= ma44_prev) and (ema9 < ma44)
        ema26_crossed_down = (ema26_prev >= ma44_prev) and (ema26 < ma44)
        both_crossed_down = both_below and (ema9_crossed_down or ema26_crossed_down)
        
        print(f"3️⃣  Both EMAs crossed below MA 44")
        print(f"   EMA9 < MA44: {ema9:.2f} < {ma44:.2f} = {'✅' if ema9 < ma44 else '❌'}")
        print(f"   EMA26 < MA44: {ema26:.2f} < {ma44:.2f} = {'✅' if ema26 < ma44 else '❌'}")
        print(f"   EMA9 crossed down: {'✅' if ema9_crossed_down else '❌'} (was {ema9_prev:.2f}, MA44 was {ma44_prev:.2f})")
        print(f"   EMA26 crossed down: {'✅' if ema26_crossed_down else '❌'} (was {ema26_prev:.2f}, MA44 was {ma44_prev:.2f})")
        print(f"   Status: {'✅ PASS' if both_crossed_down else '❌ FAIL'}")
        if not both_crossed_down:
            if not both_below:
                print(f"   ⚠️  Not both EMAs below MA44")
            elif not (ema9_crossed_down or ema26_crossed_down):
                print(f"   ⚠️  Neither EMA crossed MA44 recently (already below)")
        print()
        
        # Condition 4: MA44 Slope
        slope_down = ma_slope < 0
        print(f"4️⃣  MA 44 has downward slope")
        print(f"   MA44 slope: {ma_slope:.4f}")
        print(f"   Status: {'✅ PASS' if slope_down else '❌ FAIL'}")
        if not slope_down:
            print(f"   ⚠️  MA44 is flat or rising")
        print()
        
        # Condition 5: Candle Pattern
        bearish = current_close < current_open
        below_mas = current_close < min(ema9, ema26, ma44)
        candle_ok_short = bearish and below_mas
        
        print(f"5️⃣  Bearish candle below all MAs")
        print(f"   Candle: Open=${current_open:.2f}, Close=${current_close:.2f}")
        print(f"   Bearish: {'✅' if bearish else '❌'} (close < open)")
        print(f"   Below EMA9: {'✅' if current_close < ema9 else '❌'} ({current_close:.2f} vs {ema9:.2f})")
        print(f"   Below EMA26: {'✅' if current_close < ema26 else '❌'} ({current_close:.2f} vs {ema26:.2f})")
        print(f"   Below MA44: {'✅' if current_close < ma44 else '❌'} ({current_close:.2f} vs {ma44:.2f})")
        print(f"   Status: {'✅ PASS' if candle_ok_short else '❌ FAIL'}")
        if not candle_ok_short:
            if not bearish:
                print(f"   ⚠️  Candle is bullish (close > open)")
            if not below_mas:
                print(f"   ⚠️  Close not below all moving averages")
        print()
        
        # Final verdict
        short_signal = (rsi_short_ok and ema_cross_down and both_crossed_down and 
                       slope_down and candle_ok_short)
        
        print("="*80)
        print(f"🎯 FINAL RESULT: {'✅ SIGNAL GENERATED' if short_signal else '❌ NO SIGNAL'}")
        print("="*80)
        
        if not short_signal:
            print()
            print("❌ FAILED CONDITIONS:")
            if not rsi_short_ok:
                print(f"   • RSI not in valid range")
            if not ema_cross_down:
                print(f"   • EMA9 did not cross below EMA26")
            if not both_crossed_down:
                print(f"   • EMAs did not cross below MA44")
            if not slope_down:
                print(f"   • MA44 slope not negative")
            if not candle_ok_short:
                print(f"   • Candle pattern invalid")
        
        return short_signal

# ============================================================================
# RUN TESTS
# ============================================================================

print("="*80)
print("DIAGNOSTIC TEST SUITE")
print("Testing why specific signals were missed by the scanner")
print("="*80)
print()

# Test 1: ETH Long on Feb 24, 19:15 UTC+4 = 15:15 UTC
test1_result = test_signal(
    test_name="Trade #1 - ETH LONG",
    symbol="ETHUSDT",
    utc_time=datetime(2026, 2, 24, 15, 15, 0),  # 19:15 UTC+4 = 15:15 UTC
    expected_signal="LONG",
    expected_values={
        'price': 1839,
        'rsi': 70,
        'ema9': 1831,
        'ema26': 1827,
        'ma44': 1825
    }
)

print("\n\n")

# Test 2: ETH Short on Feb 23, 20:00 UTC+4 = 16:00 UTC
test2_result = test_signal(
    test_name="Trade #2 - ETH SHORT",
    symbol="ETHUSDT",
    utc_time=datetime(2026, 2, 23, 16, 0, 0),  # 20:00 UTC+4 = 16:00 UTC
    expected_signal="SHORT",
    expected_values={
        'price': 1894,
        'rsi': 34,
        'ema9': 1902,
        'ema26': 1906,
        'ma44': 1900
    }
)

print("\n\n")

# Test 3: ETH Short on Feb 22, 16:45 UTC+4 = 12:45 UTC
test3_result = test_signal(
    test_name="Trade #3 - ETH SHORT",
    symbol="ETHUSDT",
    utc_time=datetime(2026, 2, 22, 12, 45, 0),  # 16:45 UTC+4 = 12:45 UTC
    expected_signal="SHORT",
    expected_values={
        'price': 1966,
        'rsi': 36,
        'ema9': 1972,
        'ema26': 1974,
        'ma44': 1974.4
    }
)

print("\n\n")

# Summary
print("="*80)
print("TEST SUMMARY")
print("="*80)
print(f"Test 1 (ETH LONG 24 Feb):  {'✅ PASSED' if test1_result else '❌ FAILED'}")
print(f"Test 2 (ETH SHORT 23 Feb): {'✅ PASSED' if test2_result else '❌ FAILED'}")
print(f"Test 3 (ETH SHORT 22 Feb): {'✅ PASSED' if test3_result else '❌ FAILED'}")
print("="*80)
print()
print("Check the detailed output above to see which conditions failed.")
print("This will help identify where the strategy logic needs adjustment.")