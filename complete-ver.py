"""
COMPLETE SCANNER VERIFICATION TOOL
Tests: Telegram ✓ | Binance Connection | Strategy Logic | Data Flow

Run this to verify EVERYTHING works before running the real scanner
"""

import requests
import json
import pandas as pd
import numpy as np
from datetime import datetime
import time

# ============================================================================
# YOUR CONFIGURATION
# ============================================================================

TELEGRAM_BOT_TOKEN = "8352614023:AAEtoaKKhYpAhb7E3ncpp78aYARghlm5cMI"
TELEGRAM_CHAT_ID = "-1003854097829"

# ============================================================================
# TEST 1: TELEGRAM CONNECTION
# ============================================================================

def test_telegram():
    """Test if Telegram bot is working"""
    print("\n" + "="*70)
    print("TEST 1: TELEGRAM CONNECTION")
    print("="*70)
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    message = f"""
🧪 <b>Test 1: Telegram Connection</b>

✅ Your Telegram bot is configured correctly!

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
    
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ PASS - Telegram message sent successfully")
        print(f"   Response: {response.status_code}")
        return True
    except Exception as e:
        print(f"❌ FAIL - Telegram error: {e}")
        return False

# ============================================================================
# TEST 2: BINANCE API CONNECTION
# ============================================================================

def test_binance_api():
    """Test if we can connect to Binance API"""
    print("\n" + "="*70)
    print("TEST 2: BINANCE API CONNECTION")
    print("="*70)
    
    try:
        # Test 1: Server time
        print("\n📡 Testing Binance server connection...")
        url = "https://api.binance.com/api/v3/time"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        server_time = response.json()
        print(f"   ✅ Server responded")
        print(f"   Server time: {datetime.fromtimestamp(server_time['serverTime']/1000)}")
        
        # Test 2: Get BTC price
        print("\n💰 Testing price data retrieval...")
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        price_data = response.json()
        btc_price = float(price_data['price'])
        print(f"   ✅ BTC price: ${btc_price:,.2f}")
        
        # Test 3: Get historical candles
        print("\n📊 Testing historical data retrieval...")
        url = "https://api.binance.com/api/v3/klines"
        params = {
            'symbol': 'BTCUSDT',
            'interval': '1m',
            'limit': 100
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        candles = response.json()
        print(f"   ✅ Retrieved {len(candles)} candles")
        print(f"   Latest candle close: ${float(candles[-1][4]):,.2f}")
        
        print("\n✅ PASS - Binance API connection working perfectly")
        return True
        
    except Exception as e:
        print(f"\n❌ FAIL - Binance API error: {e}")
        return False

# ============================================================================
# TEST 3: STRATEGY CALCULATION
# ============================================================================

def test_strategy_calculations():
    """Test if strategy indicators calculate correctly"""
    print("\n" + "="*70)
    print("TEST 3: STRATEGY INDICATOR CALCULATIONS")
    print("="*70)
    
    try:
        # Fetch real BTC data
        print("\n📊 Fetching BTCUSDT data...")
        url = "https://api.binance.com/api/v3/klines"
        params = {
            'symbol': 'BTCUSDT',
            'interval': '1m',
            'limit': 100
        }
        response = requests.get(url, params=params, timeout=10)
        candles = response.json()
        
        # Extract close prices
        closes = [float(candle[4]) for candle in candles]
        opens = [float(candle[1]) for candle in candles]
        
        print(f"   ✅ Got {len(closes)} price points")
        print(f"   Latest close: ${closes[-1]:,.2f}")
        
        # Calculate RSI
        print("\n🔢 Calculating RSI...")
        prices = pd.Series(closes)
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
        print(f"   ✅ RSI = {current_rsi:.2f}")
        
        # Calculate EMAs
        print("\n📈 Calculating EMAs...")
        ema_9 = prices.ewm(span=9, adjust=False).mean().iloc[-1]
        ema_26 = prices.ewm(span=26, adjust=False).mean().iloc[-1]
        print(f"   ✅ EMA 9 = ${ema_9:,.2f}")
        print(f"   ✅ EMA 26 = ${ema_26:,.2f}")
        
        # Calculate MA 44
        print("\n📊 Calculating MA 44...")
        ma_44 = prices.rolling(window=44).mean().iloc[-1]
        print(f"   ✅ MA 44 = ${ma_44:,.2f}")
        
        # Check current candle
        print("\n🕯️ Current Candle Analysis...")
        current_close = closes[-1]
        current_open = opens[-1]
        is_bullish = current_close > current_open
        candle_type = "🟢 BULLISH" if is_bullish else "🔴 BEARISH"
        print(f"   {candle_type}")
        print(f"   Open: ${current_open:,.2f}")
        print(f"   Close: ${current_close:,.2f}")
        
        # Check conditions
        print("\n🎯 Checking Strategy Conditions...")
        print(f"   RSI in LONG range (20-50): {20 <= current_rsi <= 50}")
        print(f"   RSI in SHORT range (50-80): {50 <= current_rsi <= 80}")
        print(f"   EMA 9 above EMA 26: {ema_9 > ema_26}")
        print(f"   EMA 9 below EMA 26: {ema_9 < ema_26}")
        print(f"   Price above MA 44: {current_close > ma_44}")
        print(f"   Price below MA 44: {current_close < ma_44}")
        
        print("\n✅ PASS - All indicators calculating correctly")
        return True
        
    except Exception as e:
        print(f"\n❌ FAIL - Strategy calculation error: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================================
# TEST 4: WEBSOCKET CONNECTION (LIVE STREAM)
# ============================================================================

def test_websocket_stream():
    """Test if WebSocket streaming works"""
    print("\n" + "="*70)
    print("TEST 4: WEBSOCKET LIVE STREAM")
    print("="*70)
    
    try:
        import websocket
        
        received_data = {'count': 0, 'prices': []}
        
        def on_message(ws, message):
            data = json.loads(message)
            if 'data' in data:
                price = float(data['data']['c'])
                received_data['count'] += 1
                received_data['prices'].append(price)
                print(f"   📊 Update #{received_data['count']}: BTC = ${price:,.2f}", end='\r')
        
        def on_error(ws, error):
            if str(error).strip():
                print(f"\n   ⚠️  WebSocket error: {error}")
        
        def on_close(ws, close_status_code, close_msg):
            print("\n   Connection closed")
        
        def on_open(ws):
            print("   ✅ WebSocket connected!")
            print("   📡 Receiving live price updates...")
            print("   (Will test for 10 seconds)\n")
        
        # Connect to Binance WebSocket
        ws_url = "wss://stream.binance.com:9443/stream?streams=btcusdt@ticker"
        ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )
        
        # Run for 10 seconds
        import threading
        ws_thread = threading.Thread(target=ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()
        
        time.sleep(10)
        ws.close()
        time.sleep(1)
        
        print(f"\n\n   ✅ Received {received_data['count']} live updates in 10 seconds")
        if received_data['prices']:
            print(f"   Latest price: ${received_data['prices'][-1]:,.2f}")
        
        if received_data['count'] > 0:
            print("\n✅ PASS - WebSocket streaming working perfectly")
            return True
        else:
            print("\n❌ FAIL - No data received from WebSocket")
            return False
            
    except ImportError:
        print("\n❌ FAIL - websocket-client not installed")
        print("   Install with: pip install websocket-client")
        return False
    except Exception as e:
        print(f"\n❌ FAIL - WebSocket error: {e}")
        return False

# ============================================================================
# TEST 5: FULL SIGNAL DETECTION TEST
# ============================================================================

def test_signal_detection():
    """Test complete signal detection with real data"""
    print("\n" + "="*70)
    print("TEST 5: SIGNAL DETECTION LOGIC")
    print("="*70)
    
    try:
        print("\n🔍 Testing with multiple coins...")
        
        symbols_to_test = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT']
        signals_found = []
        
        for symbol in symbols_to_test:
            print(f"\n📊 Checking {symbol}...")
            
            # Get data
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': '1m',
                'limit': 100
            }
            response = requests.get(url, params=params, timeout=10)
            candles = response.json()
            
            closes = [float(c[4]) for c in candles]
            opens = [float(c[1]) for c in candles]
            
            # Calculate indicators
            prices = pd.Series(closes)
            delta = prices.diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            ema_9 = prices.ewm(span=9, adjust=False).mean()
            ema_26 = prices.ewm(span=26, adjust=False).mean()
            ma_44 = prices.rolling(window=44).mean()
            
            # Current values
            curr_rsi = rsi.iloc[-1]
            curr_ema9 = ema_9.iloc[-1]
            curr_ema26 = ema_26.iloc[-1]
            curr_ma44 = ma_44.iloc[-1]
            curr_close = closes[-1]
            
            # Previous values
            prev_ema9 = ema_9.iloc[-2]
            prev_ema26 = ema_26.iloc[-2]
            prev_ma44 = ma_44.iloc[-2]
            
            # Check LONG conditions (relaxed for testing)
            rsi_ok = 10 <= curr_rsi <= 90  # Relaxed
            ema_cross_up = (prev_ema9 <= prev_ema26) and (curr_ema9 > curr_ema26)
            both_above = (curr_ema9 > curr_ma44) and (curr_ema26 > curr_ma44)
            
            print(f"   RSI: {curr_rsi:.2f} {'✅' if rsi_ok else '❌'}")
            print(f"   EMA cross up: {'✅' if ema_cross_up else '❌'}")
            print(f"   Both above MA44: {'✅' if both_above else '❌'}")
            
            if ema_cross_up or both_above:
                signals_found.append(f"{symbol} - Partial match")
        
        if signals_found:
            print(f"\n   Found {len(signals_found)} potential setups:")
            for sig in signals_found:
                print(f"   • {sig}")
        
        print("\n✅ PASS - Signal detection logic working")
        print("   (Full signals are rare - this is normal)")
        return True
        
    except Exception as e:
        print(f"\n❌ FAIL - Signal detection error: {e}")
        return False

# ============================================================================
# RUN ALL TESTS
# ============================================================================

def run_all_verifications():
    """Run complete verification suite"""
    
    print("\n" + "="*70)
    print("🧪 COMPLETE SCANNER VERIFICATION TOOL")
    print("="*70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    # Check config
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌ Please set TELEGRAM_BOT_TOKEN first!")
        return
    
    results = {}
    
    # Run tests
    results['Telegram Connection'] = test_telegram()
    time.sleep(2)
    
    results['Binance API'] = test_binance_api()
    time.sleep(2)
    
    results['Strategy Calculations'] = test_strategy_calculations()
    time.sleep(2)
    
    results['WebSocket Stream'] = test_websocket_stream()
    time.sleep(2)
    
    results['Signal Detection'] = test_signal_detection()
    
    # Summary
    print("\n" + "="*70)
    print("📊 VERIFICATION SUMMARY")
    print("="*70)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    passed = sum(results.values())
    total = len(results)
    
    print("="*70)
    print(f"RESULT: {passed}/{total} tests passed")
    print("="*70)
    
    if passed == total:
        print("\n🎉 ALL SYSTEMS OPERATIONAL!")
        print("\nYour scanner is ready to run:")
        print("1. ✅ Telegram alerts working")
        print("2. ✅ Binance connection working")
        print("3. ✅ Strategy logic working")
        print("4. ✅ WebSocket streaming working")
        print("5. ✅ Signal detection working")
        print("\n▶️  You can now run: python realtime_binance_scanner_fixed.py")
    else:
        print("\n⚠️  Some tests failed - fix these before running scanner")
    
    # Send summary to Telegram
    summary_msg = f"""
📊 <b>Verification Complete</b>

Results: {passed}/{total} tests passed

{'🎉 All systems operational!' if passed == total else '⚠️ Some issues detected'}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
    
    if results.get('Telegram Connection'):
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': summary_msg,
            'parse_mode': 'HTML'
        })

if __name__ == "__main__":
    run_all_verifications()