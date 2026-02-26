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
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT',
    'DOGEUSDT', 'SOLUSDT', 'DOTUSDT', 'MATICUSDT', 'AVAXUSDT',
    'LINKUSDT', 'UNIUSDT', 'ATOMUSDT', 'LTCUSDT', 'XLMUSDT',
    'ALGOUSDT', 'VETUSDT', 'FILUSDT', 'TRXUSDT', 'NEARUSDT',
    'SHIBUSDT', 'APEUSDT', 'SANDUSDT', 'MANAUSDT', 'CRVUSDT',
    'AAVEUSDT', 'GRTUSDT', 'ENJUSDT', 'CHZUSDT', 'THETAUSDT',
    'FTMUSDT', 'AXSUSDT', 'HBARUSDT', 'EOSUSDT', 'FLOWUSDT',
    'ICPUSDT', 'XTZUSDT', 'EGLDUSDT', 'QNTUSDT', 'INJUSDT',
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
      closes[-3] = candle before setup  (MA44 slope reference)
      closes[-2] = setup candle
      closes[-1] = trigger candle

    Returns entry price if triggered, else None.
    """
    if len(closes) < MA_PERIOD + 5:
        return None

    ma44_setup  = calculate_sma(closes[:-1], MA_PERIOD)   # setup candle
    ma44_before = calculate_sma(closes[:-2], MA_PERIOD)   # candle before setup

    trigger_open = opens[-1]
    setup_open   = opens[-2]

    if pending_direction == 'LONG':
        if (ma44_setup > ma44_before) and (trigger_open > setup_open):
            return trigger_open

    elif pending_direction == 'SHORT':
        if (ma44_setup < ma44_before) and (trigger_open < setup_open):
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
    COOLDOWN_MS       = 5 * 60 * 1000

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
                        'time_str': datetime.fromtimestamp(candle_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
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

    end_dt   = datetime.utcnow()
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
        p(f"Generated : {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
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
                setup_time = datetime.utcfromtimestamp(sig['setup_ts'] / 1000)\
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


if __name__ == "__main__":
    main()