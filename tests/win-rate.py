"""
30-DAY BACKTEST SCANNER — Final Signal Logic
=============================================
4-LAYER SIGNAL DETECTION:

LAYER 1 — Sideways filter (last 20 candles):
  max(MA44) - min(MA44) > 0.2% of current price
  Rejects signals when market is consolidating/flat

LAYER 2 — Cross confirmation (last 4 candles):
  LONG : EMA9 crossed above MA44 within last 4 candles
         AND EMA26 crossed above MA44 within last 4 candles
  SHORT: EMA9 crossed below MA44 within last 4 candles
         AND EMA26 crossed below MA44 within last 4 candles
  (each cross checked independently, looser interpretation)

LAYER 3 — Setup candle (candle[-2], previous closed candle):
  LONG:
    1. RSI 45.1–85
    2. EMA9 > EMA26
    3. EMA9 > MA44  AND  EMA26 > MA44
    4. Bullish candle (close > open)
    5. Close > EMA9, EMA26, MA44

  SHORT:
    1. RSI 10–45
    2. EMA9 < EMA26
    3. EMA9 < MA44  AND  EMA26 < MA44
    4. Bearish candle (close < open)
    5. Close < EMA9, EMA26, MA44

LAYER 4 — Trigger candle (candle[-1], fires at open):
  LONG : MA44(setup) > MA44(candle before setup)  AND  open > setup open
  SHORT: MA44(setup) < MA44(candle before setup)  AND  open < setup open
  Entry = open of trigger candle

SL/TP:
  LONG  : SL = entry * 0.995,  TP = entry * 1.015
  SHORT : SL = entry * 1.005,  TP = entry * 0.985
"""

import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import sys
import time

# ============================================================================
# STRATEGY PARAMETERS
# ============================================================================

RSI_PERIOD    = 14
EMA_SHORT     = 9
EMA_LONG      = 26
MA_PERIOD     = 44
RSI_LONG_MIN  = 45.1
RSI_LONG_MAX  = 85
RSI_SHORT_MIN = 10
RSI_SHORT_MAX = 45
SL_PERCENT    = 0.5
TP_PERCENT    = 1.5

SIDEWAYS_LOOKBACK  = 20     # candles to check for flat MA44
SIDEWAYS_THRESHOLD = 0.002  # 0.2% of price — MA44 must move more than this
CROSS_LOOKBACK     = 4      # candles to look back for EMA/MA44 cross

SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
    'DOGEUSDT', 'ADAUSDT', 'AVAXUSDT', 'LINKUSDT', 'DOTUSDT',
]

# ============================================================================
# INDICATORS
# ============================================================================

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

# ============================================================================
# LAYER 1 — SIDEWAYS FILTER
# ============================================================================

def is_trending(closes):
    """
    Returns True if MA44 has moved more than 0.2% of current price
    over the last SIDEWAYS_LOOKBACK candles.
    Rejects sideways/flat markets.
    """
    if len(closes) < MA_PERIOD + SIDEWAYS_LOOKBACK:
        return False

    # Compute MA44 at each of the last SIDEWAYS_LOOKBACK candle positions
    ma44_values = []
    for k in range(SIDEWAYS_LOOKBACK, 0, -1):
        # closes[:-k] gives closes up to SIDEWAYS_LOOKBACK candles ago
        ma44_values.append(calculate_sma(closes[:-k], MA_PERIOD))

    # Also include current MA44
    ma44_values.append(calculate_sma(closes, MA_PERIOD))

    ma44_max   = max(ma44_values)
    ma44_min   = min(ma44_values)
    ma44_range = ma44_max - ma44_min

    current_price = closes[-1]
    threshold     = current_price * SIDEWAYS_THRESHOLD

    return ma44_range > threshold


# ============================================================================
# LAYER 2 — CROSS CONFIRMATION (last 4 candles)
# ============================================================================

def had_cross_above_ma44(closes):
    """
    Returns True if BOTH EMA9 AND EMA26 each individually crossed
    above MA44 within the last CROSS_LOOKBACK candles.

    For each EMA independently:
      Find any candle k in last 4 where EMA(k-1) <= MA44(k-1)
      and EMA(k) > MA44(k)  → that's a cross above.
    """
    if len(closes) < MA_PERIOD + CROSS_LOOKBACK + 2:
        return False

    ema9_crossed  = False
    ema26_crossed = False

    for k in range(1, CROSS_LOOKBACK + 1):
        # k=1 → most recent candle, k=4 → 4 candles ago
        closes_now  = closes[:-k + 1] if k > 1 else closes
        closes_prev = closes[:-k]

        if len(closes_now) < MA_PERIOD or len(closes_prev) < MA_PERIOD:
            continue

        ema9_now   = calculate_ema(closes_now,  EMA_SHORT)
        ema9_prev  = calculate_ema(closes_prev, EMA_SHORT)
        ema26_now  = calculate_ema(closes_now,  EMA_LONG)
        ema26_prev = calculate_ema(closes_prev, EMA_LONG)
        ma44_now   = calculate_sma(closes_now,  MA_PERIOD)
        ma44_prev  = calculate_sma(closes_prev, MA_PERIOD)

        if not ema9_crossed and (ema9_prev <= ma44_prev) and (ema9_now > ma44_now):
            ema9_crossed = True

        if not ema26_crossed and (ema26_prev <= ma44_prev) and (ema26_now > ma44_now):
            ema26_crossed = True

        if ema9_crossed and ema26_crossed:
            return True

    return ema9_crossed and ema26_crossed


def had_cross_below_ma44(closes):
    """
    Returns True if BOTH EMA9 AND EMA26 each individually crossed
    below MA44 within the last CROSS_LOOKBACK candles.
    """
    if len(closes) < MA_PERIOD + CROSS_LOOKBACK + 2:
        return False

    ema9_crossed  = False
    ema26_crossed = False

    for k in range(1, CROSS_LOOKBACK + 1):
        closes_now  = closes[:-k + 1] if k > 1 else closes
        closes_prev = closes[:-k]

        if len(closes_now) < MA_PERIOD or len(closes_prev) < MA_PERIOD:
            continue

        ema9_now   = calculate_ema(closes_now,  EMA_SHORT)
        ema9_prev  = calculate_ema(closes_prev, EMA_SHORT)
        ema26_now  = calculate_ema(closes_now,  EMA_LONG)
        ema26_prev = calculate_ema(closes_prev, EMA_LONG)
        ma44_now   = calculate_sma(closes_now,  MA_PERIOD)
        ma44_prev  = calculate_sma(closes_prev, MA_PERIOD)

        if not ema9_crossed and (ema9_prev >= ma44_prev) and (ema9_now < ma44_now):
            ema9_crossed = True

        if not ema26_crossed and (ema26_prev >= ma44_prev) and (ema26_now < ma44_now):
            ema26_crossed = True

        if ema9_crossed and ema26_crossed:
            return True

    return ema9_crossed and ema26_crossed


# ============================================================================
# LAYER 3 — SETUP CANDLE
# ============================================================================

def check_setup_candle(closes, opens):
    """
    Evaluate all 5 setup conditions on the LAST candle in closes/opens.
    Also runs Layer 1 (sideways filter) and Layer 2 (cross confirmation).

    Returns 'LONG', 'SHORT', or None.
    """
    if len(closes) < MA_PERIOD + SIDEWAYS_LOOKBACK + CROSS_LOOKBACK + 5:
        return None

    # ── Layer 1: Sideways filter ──────────────────────────────────────────────
    if not is_trending(closes):
        return None

    setup_close = closes[-1]
    setup_open  = opens[-1]

    rsi   = calculate_rsi(closes, RSI_PERIOD)
    ema9  = calculate_ema(closes, EMA_SHORT)
    ema26 = calculate_ema(closes, EMA_LONG)
    ma44  = calculate_sma(closes, MA_PERIOD)

    # ── LONG setup ────────────────────────────────────────────────────────────

    # Layer 2: cross confirmation
    long_cross = had_cross_above_ma44(closes)

    # Layer 3: setup candle conditions
    long_1_rsi    = RSI_LONG_MIN <= rsi <= RSI_LONG_MAX
    long_2_ema    = ema9 > ema26
    long_3_mas    = (ema9 > ma44) and (ema26 > ma44)
    long_4_candle = setup_close > setup_open
    long_5_close  = (setup_close > ema9 and
                     setup_close > ema26 and
                     setup_close > ma44)

    long_setup = (long_cross and
                  long_1_rsi and long_2_ema and long_3_mas and
                  long_4_candle and long_5_close)

    # ── SHORT setup ───────────────────────────────────────────────────────────

    # Layer 2: cross confirmation
    short_cross = had_cross_below_ma44(closes)

    # Layer 3: setup candle conditions
    short_1_rsi    = RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX
    short_2_ema    = ema9 < ema26
    short_3_mas    = (ema9 < ma44) and (ema26 < ma44)
    short_4_candle = setup_close < setup_open
    short_5_close  = (setup_close < ema9 and
                      setup_close < ema26 and
                      setup_close < ma44)

    short_setup = (short_cross and
                   short_1_rsi and short_2_ema and short_3_mas and
                   short_4_candle and short_5_close)

    if long_setup:
        return 'LONG'
    if short_setup:
        return 'SHORT'
    return None


# ============================================================================
# LAYER 4 — TRIGGER CANDLE
# ============================================================================

def check_trigger_candle(closes, opens, pending_direction):
    """
    Evaluate 2 trigger conditions on the current (last) candle.

    Layout:
      closes[-1] = trigger candle  (current)
      closes[-2] = setup candle
      closes[-6] = 4 candles before setup  (MA44 slope reference)

    MA44 slope: compare MA44(setup candle) vs MA44(4 candles before setup).
    4 candles = 1 hour on 15-min chart — gives a visible slope confirmation.

    Returns entry price if triggered, else None.
    """
    if len(closes) < MA_PERIOD + 7:
        return None

    ma44_setup = calculate_sma(closes[:-1], MA_PERIOD)   # setup candle  [-2]
    ma44_4ago  = calculate_sma(closes[:-5], MA_PERIOD)   # 4 candles before setup [-6]

    trigger_open = opens[-1]
    setup_open   = opens[-2]

    if pending_direction == 'LONG':
        if (ma44_setup > ma44_4ago) and (trigger_open > setup_open):
            return trigger_open

    elif pending_direction == 'SHORT':
        if (ma44_setup < ma44_4ago) and (trigger_open < setup_open):
            return trigger_open

    return None


# ============================================================================
# OUTCOME CHECKER
# ============================================================================

def check_trade_outcome(signal_time_ms, entry, sl, tp, signal_type, symbol):
    """
    Check if TP or SL was hit within 48 hours after entry.
    Entry is at the open of the trigger candle.
    """
    try:
        start_ts = signal_time_ms
        end_ts   = signal_time_ms + (48 * 60 * 60 * 1000)

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
            return 'UNKNOWN'

        candles = response.json()
        if not isinstance(candles, list) or len(candles) == 0:
            return 'ONGOING'

        for idx, candle in enumerate(candles):
            high = float(candle[2])
            low  = float(candle[3])

            # First candle: entry is at open, so only count movement from open onward
            if idx == 0:
                if signal_type == 'LONG':
                    low  = min(float(candle[1]), float(candle[4]))
                    high = float(candle[2])
                else:
                    high = max(float(candle[1]), float(candle[4]))
                    low  = float(candle[3])

            if signal_type == 'LONG':
                if low  <= sl: return 'LOSS'
                if high >= tp: return 'WIN'
            else:
                if high >= sl: return 'LOSS'
                if low  <= tp: return 'WIN'

        return 'ONGOING'

    except Exception:
        return 'UNKNOWN'


# ============================================================================
# SYMBOL SCANNER
# ============================================================================

def scan_symbol(symbol, start_ts, end_ts):
    """
    Fetch candles and run 4-layer signal detection.
    Returns list of signal dicts, or None on error.
    """
    # Extra warmup: MA_PERIOD + SIDEWAYS_LOOKBACK + CROSS_LOOKBACK + buffer
    warmup_candles = MA_PERIOD + SIDEWAYS_LOOKBACK + CROSS_LOOKBACK + 20
    warmup_ms      = warmup_candles * 15 * 60 * 1000
    fetch_start    = start_ts - warmup_ms
    all_candles    = []
    current_start  = fetch_start

    while current_start < end_ts:
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    'symbol':    symbol,
                    'interval':  '15m',
                    'startTime': current_start,
                    'endTime':   end_ts,
                    'limit':     1000,
                },
                timeout=15
            )
        except Exception:
            return None

        if resp.status_code != 200:
            return None

        batch = resp.json()
        if not isinstance(batch, list) or len(batch) == 0:
            break

        all_candles.extend(batch)
        current_start = batch[-1][0] + 1
        if len(batch) < 1000:
            break

    min_candles = MA_PERIOD + SIDEWAYS_LOOKBACK + CROSS_LOOKBACK + 10
    if len(all_candles) < min_candles:
        return None

    closes_all = [float(c[4]) for c in all_candles]
    opens_all  = [float(c[1]) for c in all_candles]
    times_all  = [int(c[0])   for c in all_candles]

    signals           = []
    pending_direction = None
    pending_setup_i   = None
    last_signal_ts    = 0
    COOLDOWN_MS       = 60 * 60 * 1000     # 1 hour between signals per symbol

    start_i = MA_PERIOD + SIDEWAYS_LOOKBACK + CROSS_LOOKBACK + 5

    for i in range(start_i, len(all_candles)):
        candle_ts = times_all[i]
        in_window = (start_ts <= candle_ts <= end_ts)

        # ── CHECK A: Trigger candle ───────────────────────────────────────────
        if pending_direction is not None:
            entry = check_trigger_candle(
                closes_all[:i + 1],
                opens_all[:i + 1],
                pending_direction
            )

            if entry is not None and in_window:
                if candle_ts - last_signal_ts >= COOLDOWN_MS:
                    if pending_direction == 'LONG':
                        sl = entry * (1 - SL_PERCENT / 100)
                        tp = entry * (1 + TP_PERCENT / 100)
                    else:
                        sl = entry * (1 + SL_PERCENT / 100)
                        tp = entry * (1 - TP_PERCENT / 100)

                    outcome = check_trade_outcome(
                        candle_ts, entry, sl, tp, pending_direction, symbol
                    )

                    si = pending_setup_i
                    signals.append({
                        'symbol':     symbol,
                        'type':       pending_direction,
                        'setup_ts':   times_all[si],
                        'trigger_ts': candle_ts,
                        'time_str':   datetime.fromtimestamp(candle_ts / 1000, tz=timezone.utc)
                                          .strftime('%Y-%m-%d %H:%M UTC'),
                        'entry':      entry,
                        'sl':         sl,
                        'tp':         tp,
                        'rsi':        calculate_rsi(closes_all[:si + 1], RSI_PERIOD),
                        'ema9':       calculate_ema(closes_all[:si + 1], EMA_SHORT),
                        'ema26':      calculate_ema(closes_all[:si + 1], EMA_LONG),
                        'ma44':       calculate_sma(closes_all[:si + 1], MA_PERIOD),
                        'outcome':    outcome,
                    })
                    last_signal_ts = candle_ts

            # Option A: always discard setup after one trigger attempt
            pending_direction = None
            pending_setup_i   = None

        # ── CHECK B: Setup candle ─────────────────────────────────────────────
        direction = check_setup_candle(
            closes_all[:i + 1],
            opens_all[:i + 1]
        )

        if direction is not None:
            pending_direction = direction
            pending_setup_i   = i

    return signals


# ============================================================================
# MAIN
# ============================================================================

def main():
    terminal = sys.__stdout__

    end_dt   = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=30)
    end_ts   = int(end_dt.timestamp()   * 1000)
    start_ts = int(start_dt.timestamp() * 1000)

    terminal.write("\n" + "=" * 70 + "\n")
    terminal.write("30-DAY BACKTEST — Final Signal Logic (4 Layers)\n")
    terminal.write("=" * 70 + "\n")
    terminal.write(f"Period     : {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')} UTC\n")
    terminal.write(f"Symbols    : {len(SYMBOLS)}\n")
    terminal.write(f"Sideways   : MA44 range > {SIDEWAYS_THRESHOLD*100:.1f}% over {SIDEWAYS_LOOKBACK} candles\n")
    terminal.write(f"Cross check: Both EMA9 & EMA26 crossed MA44 within last {CROSS_LOOKBACK} candles\n")
    terminal.write("=" * 70 + "\n\n")

    all_signals = []
    symbols_ok  = 0
    symbols_err = 0

    for idx, symbol in enumerate(SYMBOLS, 1):
        terminal.write(f"[{idx:>2}/{len(SYMBOLS)}] {symbol:<14} scanning... ")
        terminal.flush()

        result = scan_symbol(symbol, start_ts, end_ts)

        if result is None:
            symbols_err += 1
            terminal.write("ERROR\n")
            continue

        symbols_ok += 1

        if result:
            wins   = sum(1 for s in result if s['outcome'] == 'WIN')
            losses = sum(1 for s in result if s['outcome'] == 'LOSS')
            terminal.write(f"{len(result)} signal(s)  [W:{wins} L:{losses}]\n")
            all_signals.extend(result)
        else:
            terminal.write("no signals\n")

        time.sleep(0.1)

    # ── Write report ──────────────────────────────────────────────────────────
    terminal.write("\nWriting report...\n")

    with open('signal_analysis_report_new.txt', 'w', encoding='utf-8') as f:

        def p(*args, **kwargs):
            print(*args, **kwargs, file=f)

        p("=" * 80)
        p("30-DAY BACKTEST REPORT — Final Signal Logic")
        p("=" * 80)
        p(f"Period    : {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')} UTC")
        p(f"Generated : {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        p(f"Symbols   : {symbols_ok} scanned  |  {symbols_err} errors")
        p()
        p("SIGNAL LOGIC (4 LAYERS):")
        p(f"  Layer 1 — Sideways filter  : MA44 range > {SIDEWAYS_THRESHOLD*100:.1f}% over {SIDEWAYS_LOOKBACK} candles")
        p(f"  Layer 2 — Cross confirm    : EMA9 & EMA26 each crossed MA44 within last {CROSS_LOOKBACK} candles")
        p("  Layer 3 — Setup candle     : RSI + EMA positions + bullish/bearish + close above/below all 3 MAs")
        p("  Layer 4 — Trigger candle   : MA44 slope + current open vs setup open")
        p("  Entry = open of trigger candle")
        p("  SL/TP: LONG SL=-0.5% TP=+1.5%  |  SHORT SL=+0.5% TP=-1.5%")
        p("=" * 80)
        p()

        total   = len(all_signals)
        wins    = sum(1 for s in all_signals if s['outcome'] == 'WIN')
        losses  = sum(1 for s in all_signals if s['outcome'] == 'LOSS')
        longs   = sum(1 for s in all_signals if s['type'] == 'LONG')
        shorts  = sum(1 for s in all_signals if s['type'] == 'SHORT')
        ongoing = sum(1 for s in all_signals if s['outcome'] == 'ONGOING')
        unknown = sum(1 for s in all_signals if s['outcome'] == 'UNKNOWN')

        if total == 0:
            p("NO SIGNALS found in the past 30 days.")
            p()
            p("Possible reasons:")
            p(f"  - MA44 was flat on most symbols (threshold: {SIDEWAYS_THRESHOLD*100:.1f}% over {SIDEWAYS_LOOKBACK} candles)")
            p(f"  - EMA9/EMA26 cross of MA44 did not occur within {CROSS_LOOKBACK} candles of setup")
            p("  - Setup candle conditions (RSI, close above MAs) did not align")
            p("  - Trigger candle open gap condition was not met")
        else:
            p(f"TOTAL SIGNALS : {total}  (LONG: {longs}  SHORT: {shorts})")
            p()

            for sig in sorted(all_signals, key=lambda x: x['trigger_ts']):
                status = {'WIN': 'WIN ', 'LOSS': 'LOSS',
                          'ONGOING': 'OPEN', 'UNKNOWN': '????'}.get(sig['outcome'], '????')
                setup_time = datetime.fromtimestamp(sig['setup_ts'] / 1000, tz=timezone.utc)\
                                 .strftime('%Y-%m-%d %H:%M UTC')
                p("-" * 80)
                p(f"  [{status}]  {sig['type']:<6}  {sig['symbol']:<14}  {sig['time_str']}")
                p(f"  Setup    : {setup_time}")
                p(f"  Entry    : ${sig['entry']:.4f}  "
                  f"SL: ${sig['sl']:.4f}  TP: ${sig['tp']:.4f}")
                p(f"  RSI={sig['rsi']:.1f}  EMA9={sig['ema9']:.4f}  "
                  f"EMA26={sig['ema26']:.4f}  MA44={sig['ma44']:.4f}")
            p()

            p("=" * 80)
            p("PERFORMANCE SUMMARY")
            p("=" * 80)
            p(f"  Total signals : {total}  (Long: {longs}  Short: {shorts})")
            p(f"  Wins          : {wins}")
            p(f"  Losses        : {losses}")
            p(f"  Ongoing       : {ongoing}")
            p(f"  Unknown       : {unknown}")
            p()

            closed = wins + losses
            if closed > 0:
                win_rate   = wins / closed * 100
                expectancy = (win_rate/100 * TP_PERCENT) - ((100 - win_rate)/100 * SL_PERCENT)
                total_pnl  = (wins * TP_PERCENT) - (losses * SL_PERCENT)

                p(f"  Win rate      : {win_rate:.1f}%  ({wins}/{closed} closed trades)")
                p(f"  Expectancy    : {expectancy:+.3f}% per trade")
                p(f"  Total PnL     : {total_pnl:+.2f}%  (equal-size positions)")
                p(f"  R/R ratio     : 1:{TP_PERCENT/SL_PERCENT:.0f}")
                p()

                if win_rate >= 60:
                    verdict = "EXCELLENT  — highly profitable with 1:3 R/R"
                elif win_rate >= 50:
                    verdict = "GOOD       — profitable with 1:3 R/R"
                elif win_rate >= 40:
                    verdict = "MARGINAL   — still profitable with 1:3 R/R"
                elif win_rate >= 25:
                    verdict = "WEAK       — losing with 1:3 R/R"
                else:
                    verdict = "POOR       — significantly losing"

                p(f"  Verdict       : {verdict}")
                p()

                p("=" * 80)
                p("PER-SYMBOL BREAKDOWN")
                p("=" * 80)
                p(f"  {'Symbol':<14} {'Sigs':>5} {'Long':>5} {'Short':>6} "
                  f"{'Win':>5} {'Loss':>5} {'Open':>5} {'WinRate':>8}")
                p("  " + "-" * 60)
                for sym in sorted(set(s['symbol'] for s in all_signals)):
                    ss  = [s for s in all_signals if s['symbol'] == sym]
                    sw  = sum(1 for s in ss if s['outcome'] == 'WIN')
                    sl_ = sum(1 for s in ss if s['outcome'] == 'LOSS')
                    so  = sum(1 for s in ss if s['outcome'] == 'ONGOING')
                    lo  = sum(1 for s in ss if s['type'] == 'LONG')
                    sh  = sum(1 for s in ss if s['type'] == 'SHORT')
                    wr  = f"{sw/(sw+sl_)*100:.0f}%" if sw + sl_ > 0 else "n/a"
                    p(f"  {sym:<14} {len(ss):>5} {lo:>5} {sh:>6} "
                      f"{sw:>5} {sl_:>5} {so:>5} {wr:>8}")
            else:
                p("  No closed trades yet — win rate not calculable.")

        p()
        p("=" * 80)
        p("METHODOLOGY")
        p("=" * 80)
        p("  WIN     : TP hit before SL within 48-hour window")
        p("  LOSS    : SL hit before TP within 48-hour window")
        p("  ONGOING : Neither hit within 48 hours")
        p("  UNKNOWN : Data unavailable")
        p("  Entry   : Open of trigger candle")
        p("  Outcome : Checked from trigger candle open onward")
        p("=" * 80)

    wins_f   = sum(1 for s in all_signals if s['outcome'] == 'WIN')
    losses_f = sum(1 for s in all_signals if s['outcome'] == 'LOSS')
    closed_f = wins_f + losses_f

    terminal.write(f"\nDone. Report → signal_analysis_report_new.txt\n")
    terminal.write(
        f"Signals: {len(all_signals)}  |  Wins: {wins_f}  Losses: {losses_f}  " +
        (f"Win rate: {wins_f/closed_f*100:.1f}%" if closed_f > 0 else "No closed trades") + "\n"
    )

    # HTML visual report
    generate_html_report(all_signals, start_dt, end_dt, 'signal_report.html')
    terminal.write("Open signal_report.html in your browser to explore signals visually.\n")


# ============================================================================
# HTML REPORT GENERATOR
# ============================================================================

def generate_html_report(all_signals, start_dt, end_dt, filename='signal_report.html'):
    wins     = sum(1 for s in all_signals if s['outcome'] == 'WIN')
    losses   = sum(1 for s in all_signals if s['outcome'] == 'LOSS')
    ongoing  = sum(1 for s in all_signals if s['outcome'] == 'ONGOING')
    longs    = sum(1 for s in all_signals if s['type'] == 'LONG')
    shorts   = sum(1 for s in all_signals if s['type'] == 'SHORT')
    total    = len(all_signals)
    closed   = wins + losses
    win_rate   = wins / closed * 100 if closed > 0 else 0
    expectancy = (win_rate/100 * 1.5) - ((100 - win_rate)/100 * 0.5) if closed > 0 else 0
    total_pnl  = (wins * 1.5) - (losses * 0.5)

    symbols_seen = sorted(set(s['symbol'] for s in all_signals))
    sym_rows = []
    for sym in symbols_seen:
        ss  = [s for s in all_signals if s['symbol'] == sym]
        sw  = sum(1 for s in ss if s['outcome'] == 'WIN')
        sl_ = sum(1 for s in ss if s['outcome'] == 'LOSS')
        so  = sum(1 for s in ss if s['outcome'] == 'ONGOING')
        lo  = sum(1 for s in ss if s['type'] == 'LONG')
        sh  = sum(1 for s in ss if s['type'] == 'SHORT')
        wr  = f"{sw/(sw+sl_)*100:.0f}%" if sw + sl_ > 0 else "—"
        pnl = (sw * 1.5) - (sl_ * 0.5)
        sym_rows.append((sym, len(ss), lo, sh, sw, sl_, so, wr, pnl))

    def signal_row(sig):
        outcome   = sig['outcome']
        stype     = sig['type']
        ts_setup  = datetime.fromtimestamp(sig['setup_ts']/1000, tz=timezone.utc).strftime('%m/%d %H:%M')
        ts_trig   = datetime.fromtimestamp(sig['trigger_ts']/1000, tz=timezone.utc).strftime('%m/%d %H:%M')
        oc        = {'WIN':'win','LOSS':'loss','ONGOING':'ongoing','UNKNOWN':'unknown'}.get(outcome,'unknown')
        ol        = {'WIN':'✓ WIN','LOSS':'✗ LOSS','ONGOING':'● OPEN','UNKNOWN':'? N/A'}.get(outcome,'?')
        tc        = 'long' if stype == 'LONG' else 'short'
        return f"""<tr class="sig-row" data-outcome="{outcome}" data-type="{stype}" data-symbol="{sig['symbol']}">
            <td><span class="badge {oc}">{ol}</span></td>
            <td><span class="badge {tc}">{stype}</span></td>
            <td class="symbol">{sig['symbol']}</td>
            <td class="mono">{ts_setup}</td><td class="mono">{ts_trig}</td>
            <td class="mono">${sig['entry']:.4f}</td>
            <td class="mono loss-color">${sig['sl']:.4f}</td>
            <td class="mono win-color">${sig['tp']:.4f}</td>
            <td class="mono">{sig['rsi']:.1f}</td>
            <td class="mono">{sig['ema9']:.2f}</td>
            <td class="mono">{sig['ema26']:.2f}</td>
            <td class="mono">{sig['ma44']:.2f}</td></tr>"""

    def sym_row(row):
        sym, total_s, lo, sh, sw, sl_, so, wr, pnl = row
        pc = 'win-color' if pnl > 0 else 'loss-color' if pnl < 0 else ''
        return f"""<tr><td class="symbol">{sym}</td><td>{total_s}</td>
            <td><span class="badge long">{lo}L</span> <span class="badge short">{sh}S</span></td>
            <td class="win-color">{sw}</td><td class="loss-color">{sl_}</td><td>{so}</td>
            <td><strong>{wr}</strong></td><td class="mono {pc}">{pnl:+.1f}%</td></tr>"""

    sig_html = '\n'.join(signal_row(s) for s in sorted(all_signals, key=lambda x: x['trigger_ts']))
    sym_html = '\n'.join(sym_row(r) for r in sorted(sym_rows, key=lambda x: -x[1]))
    vc = 'win-color' if win_rate >= 50 else 'loss-color'
    vt = ('EXCELLENT' if win_rate>=60 else 'GOOD' if win_rate>=50 else
          'MARGINAL'  if win_rate>=40 else 'WEAK' if win_rate>=25 else 'POOR') if closed>0 else 'NO DATA'
    gen = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Signal Report</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');
:root{{--bg:#0d0f14;--surface:#141720;--border:#1e2330;--text:#c8cdd8;--muted:#555f72;
--win:#00c896;--loss:#ff4d6a;--long:#3b9eff;--short:#ff9d3b;--ongoing:#8b7cf8;--accent:#f0f2f5;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:var(--bg);color:var(--text);font-family:'IBM Plex Sans',sans-serif;font-size:14px;line-height:1.6;}}
.mono{{font-family:'IBM Plex Mono',monospace;}}
header{{padding:48px 48px 32px;border-bottom:1px solid var(--border);}}
header h1{{font-size:11px;font-weight:600;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);margin-bottom:8px;}}
header h2{{font-size:28px;font-weight:700;color:var(--accent);margin-bottom:4px;}}
header .meta{{font-size:12px;color:var(--muted);font-family:'IBM Plex Mono',monospace;}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;background:var(--border);border-top:1px solid var(--border);border-bottom:1px solid var(--border);}}
.stat{{background:var(--surface);padding:24px 28px;}}
.stat .label{{font-size:10px;font-weight:600;letter-spacing:.15em;text-transform:uppercase;color:var(--muted);margin-bottom:8px;}}
.stat .value{{font-size:26px;font-weight:700;font-family:'IBM Plex Mono',monospace;color:var(--accent);}}
.stat .value.win-color{{color:var(--win);}} .stat .value.loss-color{{color:var(--loss);}} .stat .value.long-color{{color:var(--long);}}
.filters{{padding:20px 48px;display:flex;gap:10px;flex-wrap:wrap;border-bottom:1px solid var(--border);background:var(--surface);}}
.filter-btn{{padding:6px 16px;border:1px solid var(--border);background:transparent;color:var(--muted);border-radius:4px;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.08em;cursor:pointer;transition:all .15s;text-transform:uppercase;}}
.filter-btn:hover,.filter-btn.active{{background:var(--accent);color:var(--bg);border-color:var(--accent);}}
.filter-btn.win-btn.active{{background:var(--win);border-color:var(--win);color:#000;}}
.filter-btn.loss-btn.active{{background:var(--loss);border-color:var(--loss);color:#fff;}}
.filter-btn.long-btn.active{{background:var(--long);border-color:var(--long);color:#fff;}}
.filter-btn.short-btn.active{{background:var(--short);border-color:var(--short);color:#000;}}
.filter-search{{margin-left:auto;padding:6px 14px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'IBM Plex Mono',monospace;font-size:12px;outline:none;width:180px;}}
.filter-search:focus{{border-color:var(--muted);}}
.section{{padding:32px 48px;}}
.section-title{{font-size:10px;font-weight:600;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);margin-bottom:16px;}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
th{{text-align:left;padding:10px 12px;font-size:10px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);white-space:nowrap;}}
td{{padding:11px 12px;border-bottom:1px solid var(--border);white-space:nowrap;}}
tr:hover td{{background:rgba(255,255,255,.02);}}
tr.hidden{{display:none;}}
.badge{{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:600;font-family:'IBM Plex Mono',monospace;letter-spacing:.05em;}}
.badge.win{{background:rgba(0,200,150,.15);color:var(--win);}} .badge.loss{{background:rgba(255,77,106,.15);color:var(--loss);}}
.badge.ongoing{{background:rgba(139,124,248,.15);color:var(--ongoing);}} .badge.unknown{{background:rgba(100,100,100,.15);color:var(--muted);}}
.badge.long{{background:rgba(59,158,255,.15);color:var(--long);}} .badge.short{{background:rgba(255,157,59,.15);color:var(--short);}}
.win-color{{color:var(--win)!important;}} .loss-color{{color:var(--loss)!important;}}
.symbol{{font-weight:600;color:var(--accent);}}
.wr-bar-wrap{{display:flex;align-items:center;gap:16px;margin:24px 0;}}
.wr-bar{{flex:1;height:8px;background:var(--border);border-radius:4px;overflow:hidden;}}
.wr-fill{{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--win),#00e5b0);transition:width 1s cubic-bezier(.4,0,.2,1);}}
.wr-label{{font-family:'IBM Plex Mono',monospace;font-size:22px;font-weight:600;min-width:80px;}}
.verdict{{display:inline-block;padding:4px 14px;border-radius:4px;font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin-top:4px;}}
.verdict.win-color{{background:rgba(0,200,150,.1);color:var(--win);}} .verdict.loss-color{{background:rgba(255,77,106,.1);color:var(--loss);}}
.no-results{{text-align:center;padding:40px;color:var(--muted);font-family:'IBM Plex Mono',monospace;font-size:12px;display:none;}}
.divider{{height:1px;background:var(--border);margin:0 48px;}}
</style></head><body>
<header>
  <h1>Backtest Report</h1>
  <h2>Signal Analysis — Past 30 Days</h2>
  <div class="meta">{start_dt.strftime('%Y-%m-%d')} → {end_dt.strftime('%Y-%m-%d')} UTC &nbsp;·&nbsp; Generated {gen} &nbsp;·&nbsp; 15m candles · Binance</div>
</header>
<div class="stats">
  <div class="stat"><div class="label">Total Signals</div><div class="value">{total}</div></div>
  <div class="stat"><div class="label">Wins</div><div class="value win-color">{wins}</div></div>
  <div class="stat"><div class="label">Losses</div><div class="value loss-color">{losses}</div></div>
  <div class="stat"><div class="label">Open</div><div class="value">{ongoing}</div></div>
  <div class="stat"><div class="label">Long / Short</div><div class="value long-color">{longs}<span style="color:var(--muted);font-size:16px"> / </span>{shorts}</div></div>
  <div class="stat"><div class="label">Win Rate</div><div class="value {vc}">{win_rate:.1f}%</div></div>
  <div class="stat"><div class="label">Expectancy</div><div class="value {'win-color' if expectancy>=0 else 'loss-color'}">{expectancy:+.2f}%</div></div>
  <div class="stat"><div class="label">Total PnL</div><div class="value {'win-color' if total_pnl>=0 else 'loss-color'}">{total_pnl:+.1f}%</div></div>
</div>
<div class="filters">
  <button class="filter-btn active" onclick="setFilter('all',this)">All ({total})</button>
  <button class="filter-btn win-btn" onclick="setFilter('WIN',this)">Wins ({wins})</button>
  <button class="filter-btn loss-btn" onclick="setFilter('LOSS',this)">Losses ({losses})</button>
  <button class="filter-btn" onclick="setFilter('ONGOING',this)">Open ({ongoing})</button>
  <button class="filter-btn long-btn" onclick="setFilter('LONG',this)">Long ({longs})</button>
  <button class="filter-btn short-btn" onclick="setFilter('SHORT',this)">Short ({shorts})</button>
  <input class="filter-search" type="text" placeholder="Search symbol..." oninput="filterSymbol(this.value)">
</div>
<div class="section">
  <div class="section-title">All Signals</div>
  <table id="sig-table"><thead><tr>
    <th>Outcome</th><th>Type</th><th>Symbol</th><th>Setup (UTC)</th><th>Trigger (UTC)</th>
    <th>Entry</th><th>Stop Loss</th><th>Take Profit</th><th>RSI</th><th>EMA9</th><th>EMA26</th><th>MA44</th>
  </tr></thead><tbody>{sig_html}</tbody></table>
  <div class="no-results" id="no-results">No signals match the current filter.</div>
</div>
<div class="divider"></div>
<div class="section">
  <div class="section-title">Win Rate</div>
  <div class="wr-bar-wrap">
    <div class="wr-label {vc}">{win_rate:.1f}%</div>
    <div class="wr-bar"><div class="wr-fill" id="wr-fill" style="width:0%"></div></div>
    <div style="font-size:12px;color:var(--muted);min-width:160px;">
      {wins}W / {losses}L of {closed} closed<br><span class="verdict {vc}">{vt}</span>
    </div>
  </div>
</div>
<div class="divider"></div>
<div class="section">
  <div class="section-title">Per-Symbol Breakdown</div>
  <table><thead><tr>
    <th>Symbol</th><th>Signals</th><th>Direction</th><th>Wins</th><th>Losses</th><th>Open</th><th>Win Rate</th><th>PnL</th>
  </tr></thead><tbody>{sym_html}</tbody></table>
</div>
<script>
window.addEventListener('load',()=>{{setTimeout(()=>{{document.getElementById('wr-fill').style.width='{win_rate:.1f}%';}},300);}});
let activeOutcome='all',activeSymbol='';
function applyFilters(){{
  const rows=document.querySelectorAll('.sig-row');let visible=0;
  rows.forEach(row=>{{
    const om=(activeOutcome==='all'||row.dataset.outcome===activeOutcome||row.dataset.type===activeOutcome);
    const sm=row.dataset.symbol.toLowerCase().includes(activeSymbol.toLowerCase());
    if(om&&sm){{row.classList.remove('hidden');visible++;}}else{{row.classList.add('hidden');}}
  }});
  document.getElementById('no-results').style.display=visible===0?'block':'none';
}}
function setFilter(val,btn){{document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');activeOutcome=val;applyFilters();}}
function filterSymbol(val){{activeSymbol=val;applyFilters();}}
</script>
</body></html>"""

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"HTML report → {filename}")


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    main()