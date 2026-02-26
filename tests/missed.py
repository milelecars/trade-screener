"""
DIAGNOSTIC TEST v2 - Corrected 2-Step Signal Logic
=====================================================
Step 1 (Setup Candle):  4 indicator conditions checked on the PREVIOUS closed candle
Step 2 (Confirmation):  Next candle is bearish (SHORT) or bullish (LONG) → signal fires

Entry price = OPEN of the confirmation candle (what you see on the chart)
"""

import requests
import pandas as pd
from datetime import datetime

# ── Strategy Parameters ────────────────────────────────────────────────────────
RSI_PERIOD    = 14
EMA_SHORT     = 9
EMA_LONG      = 26
MA_PERIOD     = 44
RSI_LONG_MIN  = 45.1
RSI_LONG_MAX  = 85
RSI_SHORT_MIN = 10
RSI_SHORT_MAX = 45

# ── Indicator Functions ────────────────────────────────────────────────────────

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    prices = pd.Series(closes)
    delta  = prices.diff()
    gain   = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss   = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs     = gain / loss
    rsi    = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

def calculate_ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    prices = pd.Series(closes)
    ema    = prices.ewm(span=period, adjust=False).mean()
    return float(ema.iloc[-1])

def calculate_sma(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    return sum(closes[-period:]) / period

# ── Data Fetching ──────────────────────────────────────────────────────────────

def get_candles(symbol, target_time_utc, lookback_candles=150):
    """
    Fetches candles ending at the CONFIRMATION candle (target_time_utc).
    The candle BEFORE it is the setup candle.
    """
    target_ts = int(target_time_utc.timestamp() * 1000)
    start_ts  = target_ts - (lookback_candles * 15 * 60 * 1000)
    end_ts    = target_ts + (15 * 60 * 1000)   # include confirmation candle

    response = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={
            'symbol':    symbol,
            'interval':  '15m',
            'startTime': start_ts,
            'endTime':   end_ts,
            'limit':     200
        },
        timeout=10
    )

    if response.status_code != 200:
        return None

    candles = response.json()
    return candles if isinstance(candles, list) and len(candles) > 0 else None

# ── Core Signal Logic ──────────────────────────────────────────────────────────

def evaluate_signal(closes, opens):
    """
    2-Step Logic:
      - closes[:-1] / opens[:-1]  → SETUP candle   (last fully closed candle)
      - closes[-1]  / opens[-1]   → CONFIRMATION candle (current candle)

    Conditions 1-4 are checked on the setup candle.
    Condition 5 (candle direction) is checked on the confirmation candle.
    """

    # ── Slices ────────────────────────────────────────────────────────────────
    setup     = closes[:-1]       # setup candle is last item here
    setup_m1  = closes[:-2]       # one candle before setup (for cross detection)

    # ── Setup Candle Indicators ───────────────────────────────────────────────
    rsi       = calculate_rsi(setup, RSI_PERIOD)
    ema9      = calculate_ema(setup, EMA_SHORT)
    ema26     = calculate_ema(setup, EMA_LONG)
    ma44      = calculate_sma(setup, MA_PERIOD)

    ema9_prev  = calculate_ema(setup_m1, EMA_SHORT)
    ema26_prev = calculate_ema(setup_m1, EMA_LONG)
    ma44_prev  = calculate_sma(setup_m1, MA_PERIOD)
    ma44_5ago  = calculate_sma(closes[:-6], MA_PERIOD)

    ma_slope        = ma44 - ma44_5ago
    setup_close     = closes[-2]    # close of the setup candle
    setup_open      = opens[-2]

    # ── Confirmation Candle ───────────────────────────────────────────────────
    conf_close      = closes[-1]
    conf_open       = opens[-1]
    candle_bullish  = conf_close > conf_open
    candle_bearish  = conf_close < conf_open

    # ── LONG Conditions ───────────────────────────────────────────────────────
    rsi_long_ok     = RSI_LONG_MIN <= rsi <= RSI_LONG_MAX
    ema_cross_up    = (ema9_prev <= ema26_prev) and (ema9 > ema26)
    both_above_ma   = (ema9 > ma44) and (ema26 > ma44)
    any_cross_up_ma = (((ema9_prev  <= ma44_prev) and (ema9  > ma44)) or
                       ((ema26_prev <= ma44_prev) and (ema26 > ma44)))
    ema_ma_cross_up = both_above_ma and any_cross_up_ma
    slope_up        = ma_slope > 0

    long_setup      = rsi_long_ok and ema_cross_up and ema_ma_cross_up and slope_up
    long_signal     = long_setup and candle_bullish

    # ── SHORT Conditions ──────────────────────────────────────────────────────
    rsi_short_ok      = RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX
    ema_cross_down    = (ema9_prev >= ema26_prev) and (ema9 < ema26)
    both_below_ma     = (ema9 < ma44) and (ema26 < ma44)
    any_cross_down_ma = (((ema9_prev  >= ma44_prev) and (ema9  < ma44)) or
                         ((ema26_prev >= ma44_prev) and (ema26 < ma44)))
    ema_ma_cross_down = both_below_ma and any_cross_down_ma
    slope_down        = ma_slope < 0

    short_setup  = rsi_short_ok and ema_cross_down and ema_ma_cross_down and slope_down
    short_signal = short_setup and candle_bearish

    return {
        # Signals
        'long_signal':       long_signal,
        'short_signal':      short_signal,
        'long_setup':        long_setup,
        'short_setup':       short_setup,
        # Setup candle indicators
        'rsi':               rsi,
        'ema9':              ema9,
        'ema26':             ema26,
        'ma44':              ma44,
        'ema9_prev':         ema9_prev,
        'ema26_prev':        ema26_prev,
        'ma44_prev':         ma44_prev,
        'ma_slope':          ma_slope,
        'setup_open':        setup_open,
        'setup_close':       setup_close,
        # Confirmation candle
        'conf_open':         conf_open,
        'conf_close':        conf_close,
        'candle_bullish':    candle_bullish,
        'candle_bearish':    candle_bearish,
        # Individual conditions for diagnostics
        'rsi_long_ok':       rsi_long_ok,
        'ema_cross_up':      ema_cross_up,
        'ema_ma_cross_up':   ema_ma_cross_up,
        'slope_up':          slope_up,
        'rsi_short_ok':      rsi_short_ok,
        'ema_cross_down':    ema_cross_down,
        'ema_ma_cross_down': ema_ma_cross_down,
        'slope_down':        slope_down,
        'both_above_ma':     both_above_ma,
        'any_cross_up_ma':   any_cross_up_ma,
        'both_below_ma':     both_below_ma,
        'any_cross_down_ma': any_cross_down_ma,
    }

# ── Test Runner ────────────────────────────────────────────────────────────────

def test_signal(test_name, symbol, utc_time, expected_signal, expected_values):
    """
    utc_time = time of the CONFIRMATION candle (what you see on the chart)
    The setup candle is the one 15 minutes BEFORE utc_time.
    """

    print("=" * 80)
    print(f"TEST: {test_name}")
    print("=" * 80)
    print(f"Symbol:              {symbol}")
    print(f"Confirmation candle: {utc_time.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"Setup candle:        15 min before (indicators evaluated here)")
    print(f"Expected Signal:     {expected_signal}")
    print()

    # Fetch candles
    candles = get_candles(symbol, utc_time)
    if not candles:
        print("❌ ERROR: Could not fetch candle data")
        return False

    print(f"✅ Fetched {len(candles)} candles")
    print()

    # Find confirmation candle index
    target_ts = int(utc_time.timestamp() * 1000)
    conf_idx  = None
    for i, candle in enumerate(candles):
        if candle[0] <= target_ts < candle[0] + (15 * 60 * 1000):
            conf_idx = i
            break

    if conf_idx is None:
        print("❌ ERROR: Could not find confirmation candle at target time")
        return False

    if conf_idx < MA_PERIOD + 10:
        print(f"❌ ERROR: Not enough history before target candle (index {conf_idx}, need >{MA_PERIOD + 10})")
        return False

    print(f"✅ Confirmation candle at index {conf_idx}")
    print(f"   Setup candle at index {conf_idx - 1}")
    print()

    # Build price arrays up to and including confirmation candle
    closes = [float(c[4]) for c in candles[:conf_idx + 1]]
    opens  = [float(c[1]) for c in candles[:conf_idx + 1]]

    # Run signal logic
    r = evaluate_signal(closes, opens)

    # ── Print Setup Candle Indicators ─────────────────────────────────────────
    print("📊 SETUP CANDLE INDICATORS (previous closed candle):")
    print(f"   Open:    ${r['setup_open']:.2f}")
    print(f"   Close:   ${r['setup_close']:.2f}")
    print(f"   RSI:     {r['rsi']:.2f}")
    print(f"   EMA 9:   ${r['ema9']:.2f}")
    print(f"   EMA 26:  ${r['ema26']:.2f}")
    print(f"   MA 44:   ${r['ma44']:.2f}")
    print(f"   MA Slope:{r['ma_slope']:.4f}")
    print()

    print("🕯️  CONFIRMATION CANDLE (entry candle):")
    print(f"   Open:    ${r['conf_open']:.2f}  ← entry price")
    print(f"   Close:   ${r['conf_close']:.2f}")
    direction = "🟢 BULLISH" if r['candle_bullish'] else ("🔴 BEARISH" if r['candle_bearish'] else "➡️  DOJI")
    print(f"   Direction: {direction}")
    print()

    print("📋 YOUR REPORTED VALUES (for reference):")
    print(f"   Price:   ${expected_values['price']:.2f}")
    print(f"   RSI:     {expected_values['rsi']:.2f}")
    print(f"   EMA 9:   ${expected_values['ema9']:.2f}")
    print(f"   EMA 26:  ${expected_values['ema26']:.2f}")
    print(f"   MA 44:   ${expected_values['ma44']:.2f}")
    print()

    # ── Condition Breakdown ────────────────────────────────────────────────────
    print("=" * 80)
    print(f"CHECKING CONDITIONS — {'🟢 LONG' if expected_signal == 'LONG' else '🔴 SHORT'}")
    print("=" * 80)
    print()

    if expected_signal == 'LONG':

        print(f"1️⃣  RSI in range ({RSI_LONG_MIN} to {RSI_LONG_MAX})")
        print(f"   RSI: {r['rsi']:.2f}  →  {'✅ PASS' if r['rsi_long_ok'] else '❌ FAIL'}")
        if not r['rsi_long_ok']:
            print(f"   ⚠️  {'Too low' if r['rsi'] < RSI_LONG_MIN else 'Too high'}")
        print()

        print(f"2️⃣  EMA9 crosses ABOVE EMA26  (on setup candle)")
        print(f"   Prev:  EMA9={r['ema9_prev']:.2f}  EMA26={r['ema26_prev']:.2f}  → EMA9 {'<=' if r['ema9_prev'] <= r['ema26_prev'] else '>'} EMA26")
        print(f"   Now:   EMA9={r['ema9']:.2f}  EMA26={r['ema26']:.2f}  → EMA9 {'>' if r['ema9'] > r['ema26'] else '<='} EMA26")
        print(f"   Status: {'✅ PASS' if r['ema_cross_up'] else '❌ FAIL'}")
        if not r['ema_cross_up']:
            if r['ema9_prev'] > r['ema26_prev']:
                print(f"   ⚠️  EMA9 was already above EMA26 — not a fresh cross")
            if r['ema9'] <= r['ema26']:
                print(f"   ⚠️  EMA9 still not above EMA26")
        print()

        print(f"3️⃣  Both EMAs above MA44  +  at least one crossed above MA44")
        print(f"   EMA9  > MA44: {r['ema9']:.2f} > {r['ma44']:.2f}  = {'✅' if r['ema9'] > r['ma44'] else '❌'}")
        print(f"   EMA26 > MA44: {r['ema26']:.2f} > {r['ma44']:.2f}  = {'✅' if r['ema26'] > r['ma44'] else '❌'}")
        print(f"   EMA9  crossed MA44: {'✅' if (r['ema9_prev'] <= r['ma44_prev'] and r['ema9'] > r['ma44']) else '❌'}  (prev EMA9={r['ema9_prev']:.2f}, prev MA44={r['ma44_prev']:.2f})")
        print(f"   EMA26 crossed MA44: {'✅' if (r['ema26_prev'] <= r['ma44_prev'] and r['ema26'] > r['ma44']) else '❌'}  (prev EMA26={r['ema26_prev']:.2f}, prev MA44={r['ma44_prev']:.2f})")
        print(f"   Status: {'✅ PASS' if r['ema_ma_cross_up'] else '❌ FAIL'}")
        if not r['ema_ma_cross_up']:
            if not r['both_above_ma']:
                print(f"   ⚠️  Not both EMAs above MA44")
            elif not r['any_cross_up_ma']:
                print(f"   ⚠️  Neither EMA just crossed MA44 (already above before)")
        print()

        print(f"4️⃣  MA44 upward slope")
        print(f"   Slope: {r['ma_slope']:.4f}  →  {'✅ PASS' if r['slope_up'] else '❌ FAIL'}")
        if not r['slope_up']:
            print(f"   ⚠️  MA44 is flat or declining")
        print()

        print(f"5️⃣  Confirmation candle is BULLISH  (close > open)")
        print(f"   Open: ${r['conf_open']:.2f}  Close: ${r['conf_close']:.2f}  →  {'✅ PASS' if r['candle_bullish'] else '❌ FAIL'}")
        if not r['candle_bullish']:
            print(f"   ⚠️  Candle is not bullish — no confirmation")
        print()

        print("=" * 80)
        print(f"🎯 SETUP (4 conditions):  {'✅ READY' if r['long_setup'] else '❌ NOT READY'}")
        print(f"🎯 FINAL SIGNAL:          {'✅ LONG SIGNAL SENT' if r['long_signal'] else '❌ NO SIGNAL'}")
        print("=" * 80)

        if r['long_setup'] and not r['long_signal']:
            print()
            print("⚠️  Setup was READY but confirmation candle was not bullish.")
            print("   Signal would fire on the next bullish candle if setup conditions still hold.")

        if not r['long_setup']:
            print()
            print("❌ FAILED SETUP CONDITIONS:")
            if not r['rsi_long_ok']:       print("   • RSI out of range")
            if not r['ema_cross_up']:      print("   • EMA9 did not cross above EMA26")
            if not r['ema_ma_cross_up']:   print("   • EMAs did not cross above MA44")
            if not r['slope_up']:          print("   • MA44 slope not positive")

        return r['long_signal']

    else:  # SHORT

        print(f"1️⃣  RSI in range ({RSI_SHORT_MIN} to {RSI_SHORT_MAX})")
        print(f"   RSI: {r['rsi']:.2f}  →  {'✅ PASS' if r['rsi_short_ok'] else '❌ FAIL'}")
        if not r['rsi_short_ok']:
            print(f"   ⚠️  {'Too low' if r['rsi'] < RSI_SHORT_MIN else 'Too high'}")
        print()

        print(f"2️⃣  EMA9 crosses BELOW EMA26  (on setup candle)")
        print(f"   Prev:  EMA9={r['ema9_prev']:.2f}  EMA26={r['ema26_prev']:.2f}  → EMA9 {'>=' if r['ema9_prev'] >= r['ema26_prev'] else '<'} EMA26")
        print(f"   Now:   EMA9={r['ema9']:.2f}  EMA26={r['ema26']:.2f}  → EMA9 {'<' if r['ema9'] < r['ema26'] else '>='} EMA26")
        print(f"   Status: {'✅ PASS' if r['ema_cross_down'] else '❌ FAIL'}")
        if not r['ema_cross_down']:
            if r['ema9_prev'] < r['ema26_prev']:
                print(f"   ⚠️  EMA9 was already below EMA26 — not a fresh cross")
            if r['ema9'] >= r['ema26']:
                print(f"   ⚠️  EMA9 still not below EMA26")
        print()

        print(f"3️⃣  Both EMAs below MA44  +  at least one crossed below MA44")
        print(f"   EMA9  < MA44: {r['ema9']:.2f} < {r['ma44']:.2f}  = {'✅' if r['ema9'] < r['ma44'] else '❌'}")
        print(f"   EMA26 < MA44: {r['ema26']:.2f} < {r['ma44']:.2f}  = {'✅' if r['ema26'] < r['ma44'] else '❌'}")
        print(f"   EMA9  crossed MA44: {'✅' if (r['ema9_prev'] >= r['ma44_prev'] and r['ema9'] < r['ma44']) else '❌'}  (prev EMA9={r['ema9_prev']:.2f}, prev MA44={r['ma44_prev']:.2f})")
        print(f"   EMA26 crossed MA44: {'✅' if (r['ema26_prev'] >= r['ma44_prev'] and r['ema26'] < r['ma44']) else '❌'}  (prev EMA26={r['ema26_prev']:.2f}, prev MA44={r['ma44_prev']:.2f})")
        print(f"   Status: {'✅ PASS' if r['ema_ma_cross_down'] else '❌ FAIL'}")
        if not r['ema_ma_cross_down']:
            if not r['both_below_ma']:
                print(f"   ⚠️  Not both EMAs below MA44")
            elif not r['any_cross_down_ma']:
                print(f"   ⚠️  Neither EMA just crossed MA44 (already below before)")
        print()

        print(f"4️⃣  MA44 downward slope")
        print(f"   Slope: {r['ma_slope']:.4f}  →  {'✅ PASS' if r['slope_down'] else '❌ FAIL'}")
        if not r['slope_down']:
            print(f"   ⚠️  MA44 is flat or rising")
        print()

        print(f"5️⃣  Confirmation candle is BEARISH  (close < open)")
        print(f"   Open: ${r['conf_open']:.2f}  Close: ${r['conf_close']:.2f}  →  {'✅ PASS' if r['candle_bearish'] else '❌ FAIL'}")
        if not r['candle_bearish']:
            print(f"   ⚠️  Candle is not bearish — no confirmation")
        print()

        print("=" * 80)
        print(f"🎯 SETUP (4 conditions):  {'✅ READY' if r['short_setup'] else '❌ NOT READY'}")
        print(f"🎯 FINAL SIGNAL:          {'✅ SHORT SIGNAL SENT' if r['short_signal'] else '❌ NO SIGNAL'}")
        print("=" * 80)

        if r['short_setup'] and not r['short_signal']:
            print()
            print("⚠️  Setup was READY but confirmation candle was not bearish.")
            print("   Signal would fire on the next bearish candle if setup conditions still hold.")

        if not r['short_setup']:
            print()
            print("❌ FAILED SETUP CONDITIONS:")
            if not r['rsi_short_ok']:       print("   • RSI out of range")
            if not r['ema_cross_down']:     print("   • EMA9 did not cross below EMA26")
            if not r['ema_ma_cross_down']:  print("   • EMAs did not cross below MA44")
            if not r['slope_down']:         print("   • MA44 slope not negative")

        return r['short_signal']

# ── Run Tests ──────────────────────────────────────────────────────────────────

print("=" * 80)
print("DIAGNOSTIC TEST SUITE  v2  —  2-Step Signal Logic")
print("=" * 80)
print()
print("HOW IT WORKS:")
print("  • Conditions 1-4 are evaluated on the SETUP candle (15 min before your timestamp)")
print("  • Condition 5 (candle direction) is evaluated on the CONFIRMATION candle (your timestamp)")
print("  • Entry price = OPEN of the confirmation candle")
print()

# ── Test 1: ETH LONG — Feb 24, 19:15 UTC+4 = 15:15 UTC ───────────────────────
# utc_time = the CONFIRMATION candle time
test1_result = test_signal(
    test_name      = "Trade #1 — ETH LONG",
    symbol         = "ETHUSDT",
    utc_time       = datetime(2026, 2, 24, 19, 15, 0),   # 19:15 UTC+4 = 15:15 UTC
    expected_signal= "LONG",
    expected_values= {
        'price': 1839,
        'rsi':   70,
        'ema9':  1831,
        'ema26': 1827,
        'ma44':  1825
    }
)

print("\n\n")

# ── Test 2: ETH SHORT — Feb 23, 20:00 UTC+4 = 16:00 UTC ──────────────────────
test2_result = test_signal(
    test_name      = "Trade #2 — ETH SHORT",
    symbol         = "ETHUSDT",
    utc_time       = datetime(2026, 2, 23, 20, 0, 0),    # 20:00 UTC+4 = 16:00 UTC
    expected_signal= "SHORT",
    expected_values= {
        'price': 1894,
        'rsi':   34,
        'ema9':  1902,
        'ema26': 1906,
        'ma44':  1900
    }
)

print("\n\n")

# ── Test 3: ETH SHORT — Feb 22, 16:45 UTC+4 = 12:45 UTC ──────────────────────
test3_result = test_signal(
    test_name      = "Trade #3 — ETH SHORT",
    symbol         = "ETHUSDT",
    utc_time       = datetime(2026, 2, 22, 16, 45, 0),   # 16:45 UTC+4 = 12:45 UTC
    expected_signal= "SHORT",
    expected_values= {
        'price': 1966,
        'rsi':   36,
        'ema9':  1972,
        'ema26': 1974,
        'ma44':  1974.4
    }
)

print("\n\n")

# ── Summary ────────────────────────────────────────────────────────────────────
print("=" * 80)
print("TEST SUMMARY")
print("=" * 80)
print(f"Test 1  (ETH LONG  24 Feb 19:15 UTC):  {'✅ PASSED' if test1_result else '❌ FAILED'}")
print(f"Test 2  (ETH SHORT 23 Feb 20:00 UTC):  {'✅ PASSED' if test2_result else '❌ FAILED'}")
print(f"Test 3  (ETH SHORT 22 Feb 16:45 UTC):  {'✅ PASSED' if test3_result else '❌ FAILED'}")
print("=" * 80)
print()
print("Scroll up to see the full condition breakdown for each test.")
print()
print("REMINDER — The timestamps above are the CONFIRMATION candle times (UTC).")
print("The SETUP candle (where indicators are evaluated) is always 15 min earlier.")