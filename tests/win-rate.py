"""
Check for trading signals over the PAST 30 DAYS
With AUTOMATED WIN RATE CALCULATION
ALL OUTPUT WRITTEN TO FILE: signal_analysis_report.txt
"""
import requests
import pandas as pd
from datetime import datetime, timedelta
import sys

# Redirect all output to file
output_file = open('signal_analysis_report.txt', 'w', encoding='utf-8')
sys.stdout = output_file

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

def check_trade_outcome(signal_time_ms, entry, sl, tp, signal_type, symbol):
    """
    Check if trade hit TP (win) or SL (loss) after signal
    Returns: 'WIN', 'LOSS', or 'ONGOING' (if neither hit yet)
    """
    try:
        # Get candles AFTER the signal for next 48 hours
        url = "https://api.binance.com/api/v3/klines"
        
        start_ts = signal_time_ms + 1
        end_ts = signal_time_ms + (48 * 60 * 60 * 1000)
        
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
            return 'UNKNOWN'
        
        candles = response.json()
        
        if not isinstance(candles, list) or len(candles) == 0:
            return 'ONGOING'
        
        # Check each candle to see if TP or SL was hit
        for candle in candles:
            high = float(candle[2])
            low = float(candle[3])
            
            if signal_type == 'LONG':
                if low <= sl:
                    return 'LOSS'
                if high >= tp:
                    return 'WIN'
            else:  # SHORT
                if high >= sl:
                    return 'LOSS'
                if low <= tp:
                    return 'WIN'
        
        return 'ONGOING'
        
    except Exception as e:
        return 'UNKNOWN'

def check_symbol_past_30_days(symbol):
    """Check if symbol had any signals in past 30 days"""
    
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        start_ts = int(start_date.timestamp() * 1000)
        end_ts = int(end_date.timestamp() * 1000)
        
        url = "https://api.binance.com/api/v3/klines"
        
        all_candles = []
        current_start = start_ts - (100 * 15 * 60 * 1000)
        
        while current_start < end_ts:
            response = requests.get(
                url,
                params={
                    'symbol': symbol,
                    'interval': '15m',
                    'startTime': current_start,
                    'endTime': end_ts,
                    'limit': 1000
                },
                timeout=10
            )
            
            if response.status_code != 200:
                return False
            
            candles = response.json()
            
            if not isinstance(candles, list) or len(candles) == 0:
                break
            
            all_candles.extend(candles)
            current_start = candles[-1][0] + 1
            
            if len(candles) < 1000:
                break
        
        if len(all_candles) < 50:
            return False
        
        signals_found = []
        
        for i in range(len(all_candles)):
            candle_time = all_candles[i][0]
            
            if candle_time < start_ts or candle_time > end_ts:
                continue
            
            closes = [float(c[4]) for c in all_candles[:i+1]]
            opens = [float(c[1]) for c in all_candles[:i+1]]
            
            if len(closes) < MA_PERIOD + 10:
                continue
            
            rsi = calculate_rsi(closes, RSI_PERIOD)
            ema9 = calculate_ema(closes, EMA_SHORT)
            ema26 = calculate_ema(closes, EMA_LONG)
            ma44 = calculate_sma(closes, MA_PERIOD)
            
            ema9_prev = calculate_ema(closes[:-1], EMA_SHORT)
            ema26_prev = calculate_ema(closes[:-1], EMA_LONG)
            ma44_prev = calculate_sma(closes[:-1], MA_PERIOD)
            
            current_close = closes[-1]
            current_open = opens[-1]
            
            ma_slope = ma44 - calculate_sma(closes[:-5], MA_PERIOD)
            
            # LONG SIGNAL
            rsi_long_ok = RSI_LONG_MIN <= rsi <= RSI_LONG_MAX
            ema_cross_up = (ema9_prev <= ema26_prev) and (ema9 > ema26)
            both_above = (ema9 > ma44) and (ema26 > ma44)
            ema9_crossed_up = (ema9_prev <= ma44_prev) and (ema9 > ma44)
            ema26_crossed_up = (ema26_prev <= ma44_prev) and (ema26 > ma44)
            both_crossed_up = both_above and (ema9_crossed_up or ema26_crossed_up)
            slope_up = ma_slope > 0
            bullish = current_close > current_open
            above_mas = current_close > max(ema9, ema26, ma44)
            candle_ok_long = bullish and above_mas
            
            long_signal = (rsi_long_ok and ema_cross_up and both_crossed_up and 
                          slope_up and candle_ok_long)
            
            # SHORT SIGNAL
            rsi_short_ok = RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX
            ema_cross_down = (ema9_prev >= ema26_prev) and (ema9 < ema26)
            both_below = (ema9 < ma44) and (ema26 < ma44)
            ema9_crossed_down = (ema9_prev >= ma44_prev) and (ema9 < ma44)
            ema26_crossed_down = (ema26_prev >= ma44_prev) and (ema26 < ma44)
            both_crossed_down = both_below and (ema9_crossed_down or ema26_crossed_down)
            slope_down = ma_slope < 0
            bearish = current_close < current_open
            below_mas = current_close < min(ema9, ema26, ma44)
            candle_ok_short = bearish and below_mas
            
            short_signal = (rsi_short_ok and ema_cross_down and both_crossed_down and 
                           slope_down and candle_ok_short)
            
            if long_signal or short_signal:
                time_str = datetime.fromtimestamp(candle_time/1000).strftime('%Y-%m-%d %H:%M UTC')
                signal_type = 'LONG' if long_signal else 'SHORT'
                
                entry = current_close
                if long_signal:
                    sl = entry * (1 - 0.5/100)
                    tp = entry * (1 + 1.5/100)
                else:
                    sl = entry * (1 + 0.5/100)
                    tp = entry * (1 - 1.5/100)
                
                # Check trade outcome
                outcome = check_trade_outcome(candle_time, entry, sl, tp, signal_type, symbol)
                
                signals_found.append({
                    'symbol': symbol,
                    'time': time_str,
                    'time_ms': candle_time,
                    'type': signal_type,
                    'entry': entry,
                    'sl': sl,
                    'tp': tp,
                    'rsi': rsi,
                    'ema9': ema9,
                    'ema26': ema26,
                    'ma44': ma44,
                    'outcome': outcome
                })
        
        return signals_found
        
    except Exception as e:
        return False

# Main execution
print("="*80)
print("SCANNING PAST 30 DAYS - WITH WIN RATE CALCULATION")
print("="*80)
end_date = datetime.now()
start_date = end_date - timedelta(days=30)
print(f"Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
print(f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*80)
print()
print("Scanning all symbols and calculating outcomes...")
print()

SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT',
    'DOGEUSDT', 'SOLUSDT', 'DOTUSDT', 'MATICUSDT', 'AVAXUSDT',
    'LINKUSDT', 'UNIUSDT', 'ATOMUSDT', 'LTCUSDT', 'XLMUSDT',
    'ALGOUSDT', 'VETUSDT', 'FILUSDT', 'TRXUSDT', 'NEARUSDT',
    'SHIBUSDT', 'APEUSDT', 'SANDUSDT', 'MANAUSDT', 'CRVUSDT',
    'AAVEUSDT', 'GRTUSDT', 'ENJUSDT', 'CHZUSDT', 'THETAUSDT',
    'FTMUSDT', 'AXSUSDT', 'HBARUSDT', 'EOSUSDT', 'FLOWUSDT',
    'ICPUSDT', 'XTZUSDT', 'EGLDUSDT', 'QNTUSDT', 'INJUSDT',
]

all_signals = []
symbols_checked = 0
symbols_with_errors = 0

for idx, symbol in enumerate(SYMBOLS, 1):
    print(f"[{idx}/{len(SYMBOLS)}] Checking {symbol}...", end=" ")
    signals = check_symbol_past_30_days(symbol)
    
    if signals == False:
        symbols_with_errors += 1
        print("ERROR")
        continue
    
    symbols_checked += 1
    
    if signals:
        all_signals.extend(signals)
        print(f"Found {len(signals)} signal(s)")
    else:
        print("No signals")

# Calculate statistics
total_signals = len(all_signals)
wins = sum(1 for s in all_signals if s['outcome'] == 'WIN')
losses = sum(1 for s in all_signals if s['outcome'] == 'LOSS')
ongoing = sum(1 for s in all_signals if s['outcome'] == 'ONGOING')
unknown = sum(1 for s in all_signals if s['outcome'] == 'UNKNOWN')

# Print all signals with outcomes
print()
print("="*80)
print("ALL SIGNALS FOUND (WITH WIN/LOSS ANALYSIS)")
print("="*80)
print()

if total_signals == 0:
    print("No signals found in the past 30 days.")
    print()
    print("This is NORMAL for your strict strategy.")
    print("Your strategy requires ALL 5 conditions to align perfectly.")
else:
    for sig in all_signals:
        outcome_emoji = {
            'WIN': '✅',
            'LOSS': '❌',
            'ONGOING': '⏳',
            'UNKNOWN': '❓'
        }.get(sig['outcome'], '❓')
        
        print("="*80)
        print(f"📅 DATE: {sig['time']}")
        print(f"📊 SYMBOL: {sig['symbol']}")
        print(f"🎯 SIGNAL: {sig['type']}")
        print(f"{outcome_emoji} OUTCOME: {sig['outcome']}")
        print("="*80)
        print(f"💰 Entry:      ${sig['entry']:.4f}")
        print(f"🛑 Stop Loss:  ${sig['sl']:.4f} ({'-0.5%' if sig['type']=='LONG' else '+0.5%'})")
        print(f"🎯 Target:     ${sig['tp']:.4f} ({'+1.5%' if sig['type']=='LONG' else '-1.5%'})")
        print()
        print(f"📈 Indicators:")
        print(f"   RSI:    {sig['rsi']:.2f}")
        print(f"   EMA 9:  ${sig['ema9']:.2f}")
        print(f"   EMA 26: ${sig['ema26']:.2f}")
        print(f"   MA 44:  ${sig['ma44']:.2f}")
        print()

# Print summary statistics
print()
print("="*80)
print("📊 30-DAY PERFORMANCE SUMMARY")
print("="*80)
print(f"✅ Symbols scanned: {symbols_checked}/{len(SYMBOLS)}")
print(f"⚠️  Symbols with errors: {symbols_with_errors}")
print(f"🎯 Total signals found: {total_signals}")
print()

if total_signals > 0:
    print("📈 TRADE OUTCOMES:")
    print(f"   ✅ Wins:    {wins} ({wins/total_signals*100:.1f}%)")
    print(f"   ❌ Losses:  {losses} ({losses/total_signals*100:.1f}%)")
    print(f"   ⏳ Ongoing: {ongoing} ({ongoing/total_signals*100:.1f}%)")
    if unknown > 0:
        print(f"   ❓ Unknown: {unknown} ({unknown/total_signals*100:.1f}%)")
    print()
    
    if wins + losses > 0:
        win_rate = wins / (wins + losses) * 100
        print("="*80)
        print(f"🏆 WIN RATE: {win_rate:.1f}%")
        print(f"   ({wins} wins out of {wins + losses} closed trades)")
        print("="*80)
        print()
        
        # Calculate expected profit per trade
        avg_profit_per_trade = (win_rate/100 * 1.5) - ((100-win_rate)/100 * 0.5)
        
        print(f"💰 EXPECTED PROFIT PER TRADE: {avg_profit_per_trade:+.2f}%")
        print(f"   With Risk/Reward Ratio: 1:3 (Risk 0.5%, Target 1.5%)")
        print()
        
        # Strategy assessment
        if win_rate >= 60:
            assessment = "✅ EXCELLENT STRATEGY!"
            detail = "Win rate above 60% - highly profitable with 1:3 R/R"
        elif win_rate >= 50:
            assessment = "✅ GOOD STRATEGY"
            detail = "Win rate above 50% - profitable with 1:3 R/R"
        elif win_rate >= 40:
            assessment = "⚠️  MARGINAL STRATEGY"
            detail = "Win rate 40-50% - still profitable with 1:3 R/R"
        else:
            assessment = "❌ NEEDS IMPROVEMENT"
            detail = "Win rate below 40% - losing strategy even with 1:3 R/R"
        
        print(f"📊 STRATEGY ASSESSMENT: {assessment}")
        print(f"   {detail}")
        print()
        
        # Profit calculation over 30 days
        total_profit = (wins * 1.5) - (losses * 0.5)
        print(f"📈 TOTAL 30-DAY PERFORMANCE:")
        print(f"   Closed trades: {wins + losses}")
        print(f"   Total profit: {total_profit:+.2f}%")
        print(f"   Average per trade: {total_profit/(wins+losses):+.2f}%")
        
    else:
        print("⏳ All trades still ongoing - cannot calculate win rate yet")
        print("   Check again later when more trades have closed")

print()
print("="*80)
print("💡 METHODOLOGY:")
print("="*80)
print("✅ WIN  = Take Profit (TP) was hit first")
print("❌ LOSS = Stop Loss (SL) was hit first")
print("⏳ ONGOING = Neither TP nor SL hit within 48-hour window")
print("❓ UNKNOWN = Could not determine outcome (data unavailable)")
print()
print("Win rate calculated as: Wins / (Wins + Losses) × 100%")
print("Only closed trades (WIN or LOSS) are included in win rate calculation.")
print()
print("="*80)
print("Report saved to: signal_analysis_report.txt")
print("="*80)

# Close file and restore stdout
output_file.close()
sys.stdout = sys.__stdout__

# Print completion message to terminal
print("✅ Analysis complete! Report saved to: signal_analysis_report.txt")
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

def check_trade_outcome(signal_time_ms, entry, sl, tp, signal_type, symbol):
    """
    Check if trade hit TP (win) or SL (loss) after signal
    Returns: 'WIN', 'LOSS', or 'ONGOING' (if neither hit yet)
    """
    try:
        # Get candles AFTER the signal for next 48 hours (to see outcome)
        url = "https://api.binance.com/api/v3/klines"
        
        # Check next 48 hours (192 fifteen-minute candles)
        start_ts = signal_time_ms + 1  # Start from next candle
        end_ts = signal_time_ms + (48 * 60 * 60 * 1000)  # 48 hours later
        
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
            return 'UNKNOWN'
        
        candles = response.json()
        
        if not isinstance(candles, list) or len(candles) == 0:
            return 'ONGOING'
        
        # Check each candle to see if TP or SL was hit
        for candle in candles:
            high = float(candle[2])
            low = float(candle[3])
            
            if signal_type == 'LONG':
                # For LONG: Check if price hit SL (below) or TP (above)
                if low <= sl:
                    return 'LOSS'  # SL hit first
                if high >= tp:
                    return 'WIN'   # TP hit first
            else:  # SHORT
                # For SHORT: Check if price hit SL (above) or TP (below)
                if high >= sl:
                    return 'LOSS'  # SL hit first
                if low <= tp:
                    return 'WIN'   # TP hit first
        
        # Neither hit within 48 hours
        return 'ONGOING'
        
    except Exception as e:
        return 'UNKNOWN'

def check_symbol_past_30_days(symbol):
    """Check if symbol had any signals in past 30 days"""
    
    try:
        # Calculate date range - past 30 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        start_ts = int(start_date.timestamp() * 1000)
        end_ts = int(end_date.timestamp() * 1000)
        
        url = "https://api.binance.com/api/v3/klines"
        
        all_candles = []
        current_start = start_ts - (100 * 15 * 60 * 1000)
        
        while current_start < end_ts:
            response = requests.get(
                url,
                params={
                    'symbol': symbol,
                    'interval': '15m',
                    'startTime': current_start,
                    'endTime': end_ts,
                    'limit': 1000
                },
                timeout=10
            )
            
            if response.status_code != 200:
                return False
            
            candles = response.json()
            
            if not isinstance(candles, list) or len(candles) == 0:
                break
            
            all_candles.extend(candles)
            current_start = candles[-1][0] + 1
            
            if len(candles) < 1000:
                break
        
        if len(all_candles) < 50:
            return False
        
        signals_found = []
        
        # Check each candle in the past 30 days
        for i in range(len(all_candles)):
            candle_time = all_candles[i][0]
            
            if candle_time < start_ts or candle_time > end_ts:
                continue
            
            closes = [float(c[4]) for c in all_candles[:i+1]]
            opens = [float(c[1]) for c in all_candles[:i+1]]
            
            if len(closes) < MA_PERIOD + 10:
                continue
            
            # Calculate indicators
            rsi = calculate_rsi(closes, RSI_PERIOD)
            ema9 = calculate_ema(closes, EMA_SHORT)
            ema26 = calculate_ema(closes, EMA_LONG)
            ma44 = calculate_sma(closes, MA_PERIOD)
            
            ema9_prev = calculate_ema(closes[:-1], EMA_SHORT)
            ema26_prev = calculate_ema(closes[:-1], EMA_LONG)
            ma44_prev = calculate_sma(closes[:-1], MA_PERIOD)
            
            current_close = closes[-1]
            current_open = opens[-1]
            
            ma_slope = ma44 - calculate_sma(closes[:-5], MA_PERIOD)
            
            # LONG SIGNAL
            rsi_long_ok = RSI_LONG_MIN <= rsi <= RSI_LONG_MAX
            ema_cross_up = (ema9_prev <= ema26_prev) and (ema9 > ema26)
            both_above = (ema9 > ma44) and (ema26 > ma44)
            ema9_crossed_up = (ema9_prev <= ma44_prev) and (ema9 > ma44)
            ema26_crossed_up = (ema26_prev <= ma44_prev) and (ema26 > ma44)
            both_crossed_up = both_above and (ema9_crossed_up or ema26_crossed_up)
            slope_up = ma_slope > 0
            bullish = current_close > current_open
            above_mas = current_close > max(ema9, ema26, ma44)
            candle_ok_long = bullish and above_mas
            
            long_signal = (rsi_long_ok and ema_cross_up and both_crossed_up and 
                          slope_up and candle_ok_long)
            
            # SHORT SIGNAL
            rsi_short_ok = RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX
            ema_cross_down = (ema9_prev >= ema26_prev) and (ema9 < ema26)
            both_below = (ema9 < ma44) and (ema26 < ma44)
            ema9_crossed_down = (ema9_prev >= ma44_prev) and (ema9 < ma44)
            ema26_crossed_down = (ema26_prev >= ma44_prev) and (ema26 < ma44)
            both_crossed_down = both_below and (ema9_crossed_down or ema26_crossed_down)
            slope_down = ma_slope < 0
            bearish = current_close < current_open
            below_mas = current_close < min(ema9, ema26, ma44)
            candle_ok_short = bearish and below_mas
            
            short_signal = (rsi_short_ok and ema_cross_down and both_crossed_down and 
                           slope_down and candle_ok_short)
            
            if long_signal or short_signal:
                time_str = datetime.fromtimestamp(candle_time/1000).strftime('%Y-%m-%d %H:%M UTC')
                signal_type = 'LONG' if long_signal else 'SHORT'
                
                # Calculate entry, SL, and TP
                entry = current_close
                if long_signal:
                    sl = entry * (1 - 0.5/100)
                    tp = entry * (1 + 1.5/100)
                else:
                    sl = entry * (1 + 0.5/100)
                    tp = entry * (1 - 1.5/100)
                
                # Check trade outcome
                outcome = check_trade_outcome(candle_time, entry, sl, tp, signal_type, symbol)
                
                signals_found.append({
                    'symbol': symbol,
                    'time': time_str,
                    'time_ms': candle_time,
                    'type': signal_type,
                    'entry': entry,
                    'sl': sl,
                    'tp': tp,
                    'rsi': rsi,
                    'ema9': ema9,
                    'ema26': ema26,
                    'ma44': ma44,
                    'outcome': outcome
                })
        
        return signals_found
        
    except Exception as e:
        return False

# Main execution
print("="*80)
print("SCANNING PAST 30 DAYS - WITH WIN RATE CALCULATION")
print("="*80)
end_date = datetime.now()
start_date = end_date - timedelta(days=30)
print(f"Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*80)
print()
print("Scanning symbols and calculating outcomes...")
print("(This may take a few minutes)")
print()

SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT',
    'DOGEUSDT', 'SOLUSDT', 'DOTUSDT', 'MATICUSDT', 'AVAXUSDT',
    'LINKUSDT', 'UNIUSDT', 'ATOMUSDT', 'LTCUSDT', 'XLMUSDT',
    'ALGOUSDT', 'VETUSDT', 'FILUSDT', 'TRXUSDT', 'NEARUSDT',
    'SHIBUSDT', 'APEUSDT', 'SANDUSDT', 'MANAUSDT', 'CRVUSDT',
    'AAVEUSDT', 'GRTUSDT', 'ENJUSDT', 'CHZUSDT', 'THETAUSDT',
    'FTMUSDT', 'AXSUSDT', 'HBARUSDT', 'EOSUSDT', 'FLOWUSDT',
    'ICPUSDT', 'XTZUSDT', 'EGLDUSDT', 'QNTUSDT', 'INJUSDT',
]

all_signals = []
symbols_checked = 0
symbols_with_errors = 0

for idx, symbol in enumerate(SYMBOLS, 1):
    print(f"[{idx}/{len(SYMBOLS)}] Checking {symbol}...", end=" ")
    signals = check_symbol_past_30_days(symbol)
    
    if signals == False:
        symbols_with_errors += 1
        print("ERROR")
        continue
    
    symbols_checked += 1
    
    if signals:
        all_signals.extend(signals)
        print(f"Found {len(signals)} signal(s)")
    else:
        print("No signals")

# Calculate statistics
total_signals = len(all_signals)
wins = sum(1 for s in all_signals if s['outcome'] == 'WIN')
losses = sum(1 for s in all_signals if s['outcome'] == 'LOSS')
ongoing = sum(1 for s in all_signals if s['outcome'] == 'ONGOING')
unknown = sum(1 for s in all_signals if s['outcome'] == 'UNKNOWN')

# Print all signals with outcomes
print()
print("="*80)
print("SIGNALS FOUND (WITH OUTCOMES)")
print("="*80)
print()

for sig in all_signals:
    outcome_emoji = {
        'WIN': '✅',
        'LOSS': '❌',
        'ONGOING': '⏳',
        'UNKNOWN': '❓'
    }.get(sig['outcome'], '❓')
    
    print("="*80)
    print(f"📅 DATE: {sig['time']}")
    print(f"📊 SYMBOL: {sig['symbol']}")
    print(f"🎯 SIGNAL: {sig['type']}")
    print(f"{outcome_emoji} OUTCOME: {sig['outcome']}")
    print("="*80)
    print(f"💰 Entry:      ${sig['entry']:.4f}")
    print(f"🛑 Stop Loss:  ${sig['sl']:.4f} ({'-0.5%' if sig['type']=='LONG' else '+0.5%'})")
    print(f"🎯 Target:     ${sig['tp']:.4f} ({'+1.5%' if sig['type']=='LONG' else '-1.5%'})")
    print()
    print(f"📈 Indicators:")
    print(f"   RSI:    {sig['rsi']:.2f}")
    print(f"   EMA 9:  ${sig['ema9']:.2f}")
    print(f"   EMA 26: ${sig['ema26']:.2f}")
    print(f"   MA 44:  ${sig['ma44']:.2f}")
    print()

# Print summary statistics
print()
print("="*80)
print("📊 PERFORMANCE SUMMARY")
print("="*80)
print(f"✅ Symbols scanned: {symbols_checked}/{len(SYMBOLS)}")
print(f"⚠️  Symbols with errors: {symbols_with_errors}")
print(f"🎯 Total signals found: {total_signals}")
print()

if total_signals > 0:
    print("📈 TRADE OUTCOMES:")
    print(f"   ✅ Wins:    {wins} ({wins/total_signals*100:.1f}%)")
    print(f"   ❌ Losses:  {losses} ({losses/total_signals*100:.1f}%)")
    print(f"   ⏳ Ongoing: {ongoing} ({ongoing/total_signals*100:.1f}%)")
    if unknown > 0:
        print(f"   ❓ Unknown: {unknown} ({unknown/total_signals*100:.1f}%)")
    print()
    
    if wins + losses > 0:
        win_rate = wins / (wins + losses) * 100
        print("="*80)
        print(f"🏆 WIN RATE: {win_rate:.1f}% ({wins} wins / {wins + losses} closed trades)")
        print("="*80)
        print()
        
        # Calculate expected profit per trade (with 1:3 R:R)
        avg_profit_per_trade = (win_rate/100 * 1.5) - ((100-win_rate)/100 * 0.5)
        
        print(f"💰 EXPECTED PROFIT PER TRADE: {avg_profit_per_trade:.2f}%")
        print(f"   (With Risk/Reward = 1:3)")
        print()
        
        if win_rate >= 60:
            print("✅ EXCELLENT strategy! Win rate above 60%")
        elif win_rate >= 50:
            print("✅ GOOD strategy! Win rate above 50%")
        elif win_rate >= 40:
            print("⚠️  MARGINAL strategy. With 1:3 R/R, still profitable.")
        else:
            print("❌ NEEDS IMPROVEMENT. Win rate below 40%")
    else:
        print("⏳ All trades still ongoing - cannot calculate win rate yet")
else:
    print("📊 RESULT: No signals found in past 30 days")
    print()
    print("This is NORMAL for your strict strategy.")

print()
print("="*80)
print("💡 INTERPRETATION:")
print("="*80)
print("✅ WIN  = Target Price (TP) was hit first")
print("❌ LOSS = Stop Loss (SL) was hit first")
print("⏳ ONGOING = Neither TP nor SL hit yet (within 48hr window)")
print("❓ UNKNOWN = Could not determine (data unavailable)")