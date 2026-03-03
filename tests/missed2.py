"""
MISSED TRADE DIAGNOSTIC
========================
Fetches real Binance data and checks every condition of the 4-layer
signal logic for two specific missed trades on BTCUSDT.

Output: missed_trade_diagnostic.txt

PARAMETERS (updated):
  - CROSS_LOOKBACK : 8  (was 4)
  - RSI_SHORT_MAX  : 55 (was 45)
  - MA44 slope     : 8 candles back (was 4)
"""

import requests
import pandas as pd
from datetime import datetime, timezone
import sys

# ============================================================================
# STRATEGY PARAMETERS (must match backtest exactly)
# ============================================================================

RSI_PERIOD         = 14
EMA_SHORT          = 9
EMA_LONG           = 26
MA_PERIOD          = 44
RSI_LONG_MIN       = 45.1
RSI_LONG_MAX       = 85
RSI_SHORT_MIN      = 10
RSI_SHORT_MAX      = 55    # expanded from 45
SL_PERCENT         = 0.5
TP_PERCENT         = 1.5
SIDEWAYS_LOOKBACK  = 20
SIDEWAYS_THRESHOLD = 0.002
CROSS_LOOKBACK     = 8     # expanded from 4

SYMBOL = 'BTCUSDT'

# ============================================================================
# MISSED TRADES TO DIAGNOSE
# ============================================================================

MISSED_TRADES = [
    {
        'id':          1,
        'direction':   'SHORT',
        'setup_dt':    datetime(2026, 1, 31, 6, 15, tzinfo=timezone.utc),
        'trigger_dt':  datetime(2026, 1, 31, 6, 30, tzinfo=timezone.utc),
        'known_ema9':  83954,
        'known_ema26': 84004,
        'known_ma44':  84077,
        'trigger_px':  83670,
        'note':        'EMA9 < EMA26 < MA44 -- suggests SHORT setup',
    },
    {
        'id':          2,
        'direction':   'SHORT',
        'setup_dt':    datetime(2026, 2, 1, 10, 45, tzinfo=timezone.utc),
        'trigger_dt':  datetime(2026, 2, 1, 11,  0, tzinfo=timezone.utc),
        'known_ema9':  78671,
        'known_ema26': 78679,
        'known_ma44':  78722,
        'trigger_px':  78279,
        'note':        'EMA9 < EMA26 < MA44 -- suggests SHORT setup',
    },
]

# ============================================================================
# INDICATORS
# ============================================================================

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    prices = pd.Series(closes)
    delta  = prices.diff()
    gain   = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss   = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs     = gain / loss
    rsi    = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

def calculate_ema(closes, period):
    if len(closes) < period:
        return None
    prices = pd.Series(closes)
    return float(prices.ewm(span=period, adjust=False).mean().iloc[-1])

def calculate_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

# ============================================================================
# DATA FETCH
# ============================================================================

def fetch_candles(symbol, end_dt, n_candles=200):
    end_ts   = int(end_dt.timestamp() * 1000)
    start_ts = end_ts - (n_candles * 15 * 60 * 1000)
    resp = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={'symbol': symbol, 'interval': '15m',
                'startTime': start_ts, 'endTime': end_ts, 'limit': n_candles},
        timeout=15
    )
    if resp.status_code != 200:
        raise Exception(f"Binance API error: {resp.status_code} -- {resp.text}")
    candles = []
    for c in resp.json():
        candles.append({
            'ts':    int(c[0]),
            'open':  float(c[1]),
            'high':  float(c[2]),
            'low':   float(c[3]),
            'close': float(c[4]),
            'time':  datetime.fromtimestamp(int(c[0])/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        })
    return candles

# ============================================================================
# DIAGNOSTIC
# ============================================================================

def diagnose_trade(trade, out):
    """Run all 4 layers and write results to out (file object)."""

    W = 72

    def p(line=''):
        print(line, file=out)

    def div(char='-'):
        p(char * W)

    p()
    div('=')
    p(f"  MISSED TRADE #{trade['id']}")
    p(f"  Setup candle  : {trade['setup_dt'].strftime('%Y-%m-%d %H:%M UTC')}")
    p(f"  Trigger candle: {trade['trigger_dt'].strftime('%Y-%m-%d %H:%M UTC')}")
    p(f"  Expected dir  : {trade['direction']}")
    p(f"  Known EMA9    : {trade['known_ema9']:,.0f}")
    p(f"  Known EMA26   : {trade['known_ema26']:,.0f}")
    p(f"  Known MA44    : {trade['known_ma44']:,.0f}")
    p(f"  Trigger price : {trade['trigger_px']:,.0f}")
    p(f"  Note          : {trade['note']}")
    div('=')

    n_needed = MA_PERIOD + SIDEWAYS_LOOKBACK + CROSS_LOOKBACK + 20
    p(f"\nFetching {n_needed} candles of BTCUSDT 15m ending at setup candle...")

    try:
        setup_close_dt = datetime.fromtimestamp(
            trade['setup_dt'].timestamp() + 15 * 60, tz=timezone.utc
        )
        candles = fetch_candles(SYMBOL, setup_close_dt, n_candles=n_needed)
    except Exception as e:
        p(f"  ERROR: {e}")
        return

    if len(candles) < 10:
        p(f"  ERROR: Only got {len(candles)} candles -- not enough data.")
        return

    p(f"  Got {len(candles)} candles.")
    p(f"  Last candle   : {candles[-1]['time']}  close={candles[-1]['close']:,.2f}")
    p()

    closes      = [c['close'] for c in candles]
    opens       = [c['open']  for c in candles]
    setup_close = closes[-1]
    setup_open  = opens[-1]

    rsi   = calculate_rsi(closes, RSI_PERIOD)
    ema9  = calculate_ema(closes, EMA_SHORT)
    ema26 = calculate_ema(closes, EMA_LONG)
    ma44  = calculate_sma(closes, MA_PERIOD)

    p("  COMPUTED INDICATORS (setup candle):")
    p(f"  {'RSI':<8}: {rsi:.2f}"      if rsi  else "  RSI     : n/a")
    p(f"  {'EMA9':<8}: {ema9:,.2f}"   if ema9  else "  EMA9    : n/a")
    p(f"  {'EMA26':<8}: {ema26:,.2f}" if ema26 else "  EMA26   : n/a")
    p(f"  {'MA44':<8}: {ma44:,.2f}"   if ma44  else "  MA44    : n/a")
    p(f"  {'Candle':<8}: open={setup_open:,.2f}  close={setup_close:,.2f}  "
      f"({'bullish' if setup_close > setup_open else 'bearish'})")

    direction = trade['direction']
    all_pass  = []

    def check(label, result, detail=''):
        mark = '  [PASS]' if result else '  [FAIL] <---'
        line = f'{mark}  {label}'
        if detail:
            line += f'  ({detail})'
        p(line)
        return result

    # ── Layer 1 ──────────────────────────────────────────────────────────────
    p()
    div()
    p(f"  LAYER 1 -- SIDEWAYS FILTER  (MA44 range > {SIDEWAYS_THRESHOLD*100:.1f}% over last {SIDEWAYS_LOOKBACK} candles)")
    div()

    if len(closes) >= MA_PERIOD + SIDEWAYS_LOOKBACK:
        ma44_vals = [calculate_sma(closes[:-k], MA_PERIOD) for k in range(SIDEWAYS_LOOKBACK, 0, -1)]
        ma44_vals.append(ma44)
        ma44_range = max(ma44_vals) - min(ma44_vals)
        threshold  = closes[-1] * SIDEWAYS_THRESHOLD
        r = check(
            f'MA44 range {ma44_range:.2f} > threshold {threshold:.2f}',
            ma44_range > threshold,
            f'max={max(ma44_vals):,.2f}  min={min(ma44_vals):,.2f}'
        )
        all_pass.append(r)
    else:
        p(f"  [SKIP]  Not enough candles ({len(closes)} available)")
        all_pass.append(False)

    # ── Layer 2 ──────────────────────────────────────────────────────────────
    p()
    div()
    p(f"  LAYER 2 -- CROSS CONFIRMATION  (within last {CROSS_LOOKBACK} candles)")
    div()

    cross_fn  = had_cross_below_ma44 if direction == 'SHORT' else had_cross_above_ma44
    cross_dir = 'below' if direction == 'SHORT' else 'above'

    p(f"  Logic: at least 1 freshly crossed {cross_dir} MA44 within last {CROSS_LOOKBACK} candles,")
    p(f"         AND the other is currently {cross_dir} MA44 (may have crossed earlier).")
    p()

    # Current positions
    ema9_now  = calculate_ema(closes, EMA_SHORT)
    ema26_now = calculate_ema(closes, EMA_LONG)
    ma44_now  = calculate_sma(closes, MA_PERIOD)

    if direction == 'SHORT':
        ema9_side  = ema9_now  < ma44_now
        ema26_side = ema26_now < ma44_now
    else:
        ema9_side  = ema9_now  > ma44_now
        ema26_side = ema26_now > ma44_now

    p(f"  Current positions vs MA44 ({ma44_now:,.1f}):")
    p(f"    EMA9  {ema9_now:,.1f}  -> {'BELOW' if ema9_now < ma44_now else 'ABOVE'} MA44  {'[OK]' if ema9_side else '[not on correct side]'}")
    p(f"    EMA26 {ema26_now:,.1f}  -> {'BELOW' if ema26_now < ma44_now else 'ABOVE'} MA44  {'[OK]' if ema26_side else '[not on correct side]'}")
    p()

    ema9_crossed = ema26_crossed = False
    for k in range(1, CROSS_LOOKBACK + 1):
        cn  = closes[:-k + 1] if k > 1 else closes
        cp  = closes[:-k]
        if len(cn) < MA_PERIOD or len(cp) < MA_PERIOD:
            continue
        e9n  = calculate_ema(cn, EMA_SHORT);  e9p  = calculate_ema(cp, EMA_SHORT)
        e26n = calculate_ema(cn, EMA_LONG);   e26p = calculate_ema(cp, EMA_LONG)
        m44n = calculate_sma(cn, MA_PERIOD);  m44p = calculate_sma(cp, MA_PERIOD)
        cl   = candles[-k]['time'] if k <= len(candles) else f'k={k}'
        e9_x  = ''
        e26_x = ''
        if direction == 'SHORT':
            if not ema9_crossed  and e9p  >= m44p and e9n  < m44n: ema9_crossed  = True; e9_x  = ' << EMA9 CROSSED'
            if not ema26_crossed and e26p >= m44p and e26n < m44n: ema26_crossed = True; e26_x = ' << EMA26 CROSSED'
        else:
            if not ema9_crossed  and e9p  <= m44p and e9n  > m44n: ema9_crossed  = True; e9_x  = ' << EMA9 CROSSED'
            if not ema26_crossed and e26p <= m44p and e26n > m44n: ema26_crossed = True; e26_x = ' << EMA26 CROSSED'
        p(f"  k={k} ({cl}): EMA9 {e9p:,.1f}->{e9n:,.1f}  MA44 {m44p:,.1f}->{m44n:,.1f}  EMA26 {e26p:,.1f}->{e26n:,.1f}{e9_x}{e26_x}")

    p()
    # Relaxed verdict: (EMA9 freshly crossed AND EMA26 on correct side)
    #              OR (EMA26 freshly crossed AND EMA9 on correct side)
    scenario_a = ema9_crossed  and ema26_side
    scenario_b = ema26_crossed and ema9_side
    cross_ok   = scenario_a or scenario_b

    check(f'EMA9  freshly crossed {cross_dir} MA44 in last {CROSS_LOOKBACK} candles', ema9_crossed)
    check(f'EMA26 currently {cross_dir} MA44 (positioned correctly)',                  ema26_side)
    p(f"  Scenario A (EMA9 crossed + EMA26 positioned): {'PASS' if scenario_a else 'FAIL'}")
    check(f'EMA26 freshly crossed {cross_dir} MA44 in last {CROSS_LOOKBACK} candles', ema26_crossed)
    check(f'EMA9  currently {cross_dir} MA44 (positioned correctly)',                  ema9_side)
    p(f"  Scenario B (EMA26 crossed + EMA9 positioned): {'PASS' if scenario_b else 'FAIL'}")
    p()
    check(f'Layer 2 overall (Scenario A OR Scenario B)', cross_ok)
    all_pass.append(cross_ok)

    # ── Layer 3 ──────────────────────────────────────────────────────────────
    p()
    div()
    p("  LAYER 3 -- SETUP CANDLE CONDITIONS")
    div()

    if direction == 'SHORT':
        r1 = check(f'RSI {rsi:.2f} in range [{RSI_SHORT_MIN}, {RSI_SHORT_MAX}]',
                   RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX if rsi else False)
        r2 = check(f'EMA9 {ema9:,.2f} < EMA26 {ema26:,.2f}',
                   ema9 < ema26 if (ema9 and ema26) else False)
        r3 = check(f'EMA9 {ema9:,.2f} < MA44 {ma44:,.2f}  AND  EMA26 {ema26:,.2f} < MA44 {ma44:,.2f}',
                   (ema9 < ma44 and ema26 < ma44) if (ema9 and ema26 and ma44) else False)
        r4 = check(f'Bearish candle: close {setup_close:,.2f} < open {setup_open:,.2f}',
                   setup_close < setup_open)
        r5 = check(f'Close {setup_close:,.2f} < EMA9 {ema9:,.2f}, EMA26 {ema26:,.2f}, MA44 {ma44:,.2f}',
                   (setup_close < ema9 and setup_close < ema26 and setup_close < ma44)
                   if (ema9 and ema26 and ma44) else False)
    else:
        r1 = check(f'RSI {rsi:.2f} in range [{RSI_LONG_MIN}, {RSI_LONG_MAX}]',
                   RSI_LONG_MIN <= rsi <= RSI_LONG_MAX if rsi else False)
        r2 = check(f'EMA9 {ema9:,.2f} > EMA26 {ema26:,.2f}',
                   ema9 > ema26 if (ema9 and ema26) else False)
        r3 = check(f'EMA9 {ema9:,.2f} > MA44 {ma44:,.2f}  AND  EMA26 {ema26:,.2f} > MA44 {ma44:,.2f}',
                   (ema9 > ma44 and ema26 > ma44) if (ema9 and ema26 and ma44) else False)
        r4 = check(f'Bullish candle: close {setup_close:,.2f} > open {setup_open:,.2f}',
                   setup_close > setup_open)
        r5 = check(f'Close {setup_close:,.2f} > EMA9 {ema9:,.2f}, EMA26 {ema26:,.2f}, MA44 {ma44:,.2f}',
                   (setup_close > ema9 and setup_close > ema26 and setup_close > ma44)
                   if (ema9 and ema26 and ma44) else False)

    all_pass.append(r1 and r2 and r3 and r4 and r5)

    # ── Layer 4 ──────────────────────────────────────────────────────────────
    p()
    div()
    p("  LAYER 4 -- TRIGGER CANDLE CONDITIONS")
    div()

    try:
        trigger_close_dt = datetime.fromtimestamp(
            trade['trigger_dt'].timestamp() + 15 * 60, tz=timezone.utc
        )
        trig_candles   = fetch_candles(SYMBOL, trigger_close_dt, n_candles=3)
        trigger_candle = None
        target_ts      = int(trade['trigger_dt'].timestamp() * 1000)
        for c in trig_candles:
            if c['ts'] == target_ts:
                trigger_candle = c
                break
        if trigger_candle is None:
            trigger_candle = trig_candles[-2] if len(trig_candles) >= 2 else trig_candles[-1]
    except Exception as e:
        p(f"  ERROR fetching trigger candle: {e}")
        trigger_candle = None

    if trigger_candle:
        trigger_open = trigger_candle['open']
        setup_open_c = opens[-1]
        ma44_setup   = calculate_sma(closes,      MA_PERIOD)   # setup candle
        ma44_3ago    = calculate_sma(closes[:-3],  MA_PERIOD)  # 3 candles before setup (current slope)

        p(f"  Trigger candle open : {trigger_open:,.2f}")
        p(f"  Setup candle open   : {setup_open_c:,.2f}")
        p(f"  MA44 at setup candle: {ma44_setup:,.2f}")
        p(f"  MA44 3 candles ago  : {ma44_3ago:,.2f}  (current slope reference)")
        p()

        if direction == 'SHORT':
            rs = check(f'MA44 sloping DOWN now: MA44(setup) {ma44_setup:,.2f} < MA44(3ago) {ma44_3ago:,.2f}',
                       ma44_setup < ma44_3ago if (ma44_setup and ma44_3ago) else False)
            ro = check(f'Trigger open {trigger_open:,.2f} < Setup open {setup_open_c:,.2f}',
                       trigger_open < setup_open_c)
        else:
            rs = check(f'MA44 sloping UP now: MA44(setup) {ma44_setup:,.2f} > MA44(3ago) {ma44_3ago:,.2f}',
                       ma44_setup > ma44_3ago if (ma44_setup and ma44_3ago) else False)
            ro = check(f'Trigger open {trigger_open:,.2f} > Setup open {setup_open_c:,.2f}',
                       trigger_open > setup_open_c)
        all_pass.append(rs and ro)
    else:
        p("  Could not fetch trigger candle data.")
        all_pass.append(False)

    # ── Verdict ───────────────────────────────────────────────────────────────
    p()
    div('=')
    failed      = [i+1 for i, r in enumerate(all_pass) if not r]
    layer_names = ['Layer 1 (Sideways)', 'Layer 2 (Cross)', 'Layer 3 (Setup candle)', 'Layer 4 (Trigger)']

    if all(all_pass):
        p("  VERDICT: ALL CONDITIONS PASS -- signal should have fired.")
        p("  >> Check cooldown or pending_setup_i logic in scanner.")
    else:
        p(f"  VERDICT: SIGNAL BLOCKED -- failed layers: {[layer_names[i-1] for i in failed]}")
        p()
        p("  ROOT CAUSE SUMMARY:")
        for i in failed:
            if i == 1:
                p("  >> MA44 was too flat over last 20 candles -- market treated as sideways.")
            elif i == 2:
                p(f"  >> EMA9/EMA26 did not freshly cross MA44 within the last {CROSS_LOOKBACK} candles.")
                p("     The cross happened earlier. Consider increasing CROSS_LOOKBACK further.")
            elif i == 3:
                p("  >> One or more setup candle conditions failed.")
                p("     Check RSI range, EMA positions, candle direction, close vs MAs.")
            elif i == 4:
                p("  >> Trigger candle conditions failed.")
                p("     MA44 not currently sloping in expected direction (3-candle check), or open gap wrong direction.")
    div('=')


def had_cross_below_ma44(closes):
    """Relaxed: 1 freshly crossed below MA44 + other currently below MA44."""
    if len(closes) < MA_PERIOD + CROSS_LOOKBACK + 2:
        return False
    ema9_now   = calculate_ema(closes, EMA_SHORT)
    ema26_now  = calculate_ema(closes, EMA_LONG)
    ma44_now   = calculate_sma(closes, MA_PERIOD)
    ema9_below  = ema9_now  < ma44_now
    ema26_below = ema26_now < ma44_now
    if not ema9_below and not ema26_below:
        return False
    ema9_crossed = ema26_crossed = False
    for k in range(1, CROSS_LOOKBACK + 1):
        cn  = closes[:-k + 1] if k > 1 else closes
        cp  = closes[:-k]
        if len(cn) < MA_PERIOD or len(cp) < MA_PERIOD:
            continue
        e9n  = calculate_ema(cn, EMA_SHORT);  e9p  = calculate_ema(cp, EMA_SHORT)
        e26n = calculate_ema(cn, EMA_LONG);   e26p = calculate_ema(cp, EMA_LONG)
        m44n = calculate_sma(cn, MA_PERIOD);  m44p = calculate_sma(cp, MA_PERIOD)
        if not ema9_crossed  and e9p  >= m44p and e9n  < m44n: ema9_crossed  = True
        if not ema26_crossed and e26p >= m44p and e26n < m44n: ema26_crossed = True
    return (ema9_crossed and ema26_below) or (ema26_crossed and ema9_below)


def had_cross_above_ma44(closes):
    """Relaxed: 1 freshly crossed above MA44 + other currently above MA44."""
    if len(closes) < MA_PERIOD + CROSS_LOOKBACK + 2:
        return False
    ema9_now   = calculate_ema(closes, EMA_SHORT)
    ema26_now  = calculate_ema(closes, EMA_LONG)
    ma44_now   = calculate_sma(closes, MA_PERIOD)
    ema9_above  = ema9_now  > ma44_now
    ema26_above = ema26_now > ma44_now
    if not ema9_above and not ema26_above:
        return False
    ema9_crossed = ema26_crossed = False
    for k in range(1, CROSS_LOOKBACK + 1):
        cn  = closes[:-k + 1] if k > 1 else closes
        cp  = closes[:-k]
        if len(cn) < MA_PERIOD or len(cp) < MA_PERIOD:
            continue
        e9n  = calculate_ema(cn, EMA_SHORT);  e9p  = calculate_ema(cp, EMA_SHORT)
        e26n = calculate_ema(cn, EMA_LONG);   e26p = calculate_ema(cp, EMA_LONG)
        m44n = calculate_sma(cn, MA_PERIOD);  m44p = calculate_sma(cp, MA_PERIOD)
        if not ema9_crossed  and e9p  <= m44p and e9n  > m44n: ema9_crossed  = True
        if not ema26_crossed and e26p <= m44p and e26n > m44n: ema26_crossed = True
    return (ema9_crossed and ema26_above) or (ema26_crossed and ema9_above)

# ============================================================================
# MAIN
# ============================================================================

def main():
    filename = 'missed_trade_diagnostic.txt'

    with open(filename, 'w', encoding='utf-8') as out:

        def p(line=''):
            print(line, file=out)

        p('=' * 72)
        p('  BTCUSDT -- MISSED TRADE DIAGNOSTIC')
        p('  Checking all 4 signal logic layers for each missed trade')
        p()
        p(f'  Parameters used:')
        p(f'    RSI_SHORT_MAX  : {RSI_SHORT_MAX}  (expanded from 45)')
        p(f'    CROSS_LOOKBACK : {CROSS_LOOKBACK} candles  (expanded from 4)')
        p(f'    MA44 slope ref : 3 candles back  (current slope, not historical)')
        p(f'    Cross logic    : 1 freshly crossed + other already below/above MA44')
        p('=' * 72)

        for trade in MISSED_TRADES:
            diagnose_trade(trade, out)
            p()

        p()
        p('Done. Review [FAIL] lines above to identify blocking conditions.')

    # also print to terminal so user knows it finished
    sys.__stdout__.write(f"\nDone -> {filename}\n\n")


if __name__ == "__main__":
    main()