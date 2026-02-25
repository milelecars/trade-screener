"""
30-DAY BACKTEST SCANNER — Updated Signal Logic
===============================================
SIGNAL LOGIC (confirmed):

SETUP CANDLE (candle[-2] = previous closed candle):
  LONG:
    1. RSI between 45.1 - 85
    2. EMA9 > EMA26
    3. EMA9 > MA44  AND  EMA26 > MA44
    4. Candle is bullish (close > open)
    5. Close > EMA9, EMA26, and MA44

  SHORT:
    1. RSI between 10 - 45
    2. EMA9 < EMA26
    3. EMA9 < MA44  AND  EMA26 < MA44
    4. Candle is bearish (close < open)
    5. Close < EMA9, EMA26, and MA44

TRIGGER CANDLE (candle[-1] = current candle, fires at open):
  LONG:
    1. MA44(setup candle) > MA44(candle before setup)  → slope up
    2. Open of current candle > Open of setup candle
    Entry = Open of current candle

  SHORT:
    1. MA44(setup candle) < MA44(candle before setup)  → slope down
    2. Open of current candle < Open of setup candle
    Entry = Open of current candle

SL/TP:
  LONG  : SL = entry * 0.995,  TP = entry * 1.015
  SHORT : SL = entry * 1.005,  TP = entry * 0.985
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
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
# SETUP CANDLE CONDITIONS
# ============================================================================

def check_setup_candle(closes, opens):
    """
    Evaluate all 5 setup conditions on the LAST candle in closes/opens.
    Uses closes[-2] as the candle before setup for MA44 slope pre-calculation.

    Returns:
        'LONG'  if all 5 long conditions pass
        'SHORT' if all 5 short conditions pass
        None    if neither
    """
    if len(closes) < MA_PERIOD + 5:
        return None

    # Setup candle values
    setup_close = closes[-1]
    setup_open  = opens[-1]

    rsi  = calculate_rsi(closes, RSI_PERIOD)
    ema9 = calculate_ema(closes, EMA_SHORT)
    ema26= calculate_ema(closes, EMA_LONG)
    ma44 = calculate_sma(closes, MA_PERIOD)

    # ── LONG setup conditions ─────────────────────────────────────────────────
    long_1_rsi     = RSI_LONG_MIN <= rsi <= RSI_LONG_MAX   # RSI 45.1–85
    long_2_ema     = ema9 > ema26                           # EMA9 above EMA26
    long_3_mas     = (ema9 > ma44) and (ema26 > ma44)      # both above MA44
    long_4_candle  = setup_close > setup_open               # bullish candle
    long_5_close   = (setup_close > ema9 and               # close above all 3
                      setup_close > ema26 and
                      setup_close > ma44)

    long_setup = long_1_rsi and long_2_ema and long_3_mas and long_4_candle and long_5_close

    # ── SHORT setup conditions ────────────────────────────────────────────────
    short_1_rsi    = RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX  # RSI 10–45
    short_2_ema    = ema9 < ema26                           # EMA9 below EMA26
    short_3_mas    = (ema9 < ma44) and (ema26 < ma44)      # both below MA44
    short_4_candle = setup_close < setup_open               # bearish candle
    short_5_close  = (setup_close < ema9 and               # close below all 3
                      setup_close < ema26 and
                      setup_close < ma44)

    short_setup = short_1_rsi and short_2_ema and short_3_mas and short_4_candle and short_5_close

    if long_setup:
        return 'LONG'
    if short_setup:
        return 'SHORT'
    return None

# ============================================================================
# TRIGGER CANDLE CONDITIONS
# ============================================================================

def check_trigger_candle(closes_up_to_trigger, opens_up_to_trigger, pending_direction):
    """
    Evaluate the 2 trigger conditions on the CURRENT candle.

    closes_up_to_trigger : all closes including the trigger candle
    opens_up_to_trigger  : all opens including the trigger candle

    candle layout:
        [-3] = candle before setup  (used for MA44 slope)
        [-2] = setup candle
        [-1] = trigger candle  (current)

    Returns entry price if triggered, else None.
    """
    if len(closes_up_to_trigger) < MA_PERIOD + 5:
        return None

    # MA44 of setup candle vs candle before setup → slope
    ma44_setup      = calculate_sma(closes_up_to_trigger[:-1], MA_PERIOD)   # setup = [-2]
    ma44_before     = calculate_sma(closes_up_to_trigger[:-2], MA_PERIOD)   # before setup = [-3]

    trigger_open    = opens_up_to_trigger[-1]   # current candle open = entry
    setup_open      = opens_up_to_trigger[-2]   # setup candle open

    if pending_direction == 'LONG':
        slope_ok   = ma44_setup > ma44_before          # MA44 sloping up
        open_ok    = trigger_open > setup_open         # current open > setup open
        if slope_ok and open_ok:
            return trigger_open                        # entry price

    elif pending_direction == 'SHORT':
        slope_ok   = ma44_setup < ma44_before          # MA44 sloping down
        open_ok    = trigger_open < setup_open         # current open < setup open
        if slope_ok and open_ok:
            return trigger_open                        # entry price

    return None

# ============================================================================
# OUTCOME CHECKER
# ============================================================================

def check_trade_outcome(signal_time_ms, entry, sl, tp, signal_type, symbol):
    """
    Check if TP or SL was hit within 48 hours after the trigger candle opens.
    Starts checking from the trigger candle itself (entry is at its open).
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

            # For the first candle (trigger candle), use close as effective low/high
            # since entry is at open — price can only move from open onward
            if idx == 0:
                open_price = float(candle[1])
                if signal_type == 'LONG':
                    # Can only go down to close or up to high from open
                    effective_low  = min(open_price, float(candle[4]))
                    effective_high = high
                    low  = effective_low
                    high = effective_high
                else:
                    effective_high = max(open_price, float(candle[4]))
                    effective_low  = low
                    high = effective_high
                    low  = effective_low

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
    Fetch candles and scan for signals using the 2-step logic.
    Returns list of signal dicts, or None on fetch error.
    """
    warmup_ms     = 110 * 15 * 60 * 1000   # 110 candles warmup for indicators
    fetch_start   = start_ts - warmup_ms
    all_candles   = []
    current_start = fetch_start

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

    if len(all_candles) < MA_PERIOD + 10:
        return None

    closes_all = [float(c[4]) for c in all_candles]
    opens_all  = [float(c[1]) for c in all_candles]
    times_all  = [int(c[0])   for c in all_candles]

    signals          = []
    pending_direction = None   # 'LONG' or 'SHORT' — set when setup candle passes
    pending_setup_i   = None   # index of the setup candle
    COOLDOWN_MS       = 5 * 60 * 1000

    last_signal_ts = 0

    # Need at least MA_PERIOD + 5 candles before we can evaluate setup
    # and one more for the trigger → start at MA_PERIOD + 5
    for i in range(MA_PERIOD + 5, len(all_candles)):
        candle_ts = times_all[i]
        in_window = (start_ts <= candle_ts <= end_ts)

        # ── CHECK A: Trigger candle ───────────────────────────────────────────
        # If a setup is pending, check whether THIS candle triggers the signal
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

                    signals.append({
                        'symbol':     symbol,
                        'type':       pending_direction,
                        'setup_ts':   times_all[pending_setup_i],
                        'trigger_ts': candle_ts,
                        'time_str':   datetime.utcfromtimestamp(candle_ts / 1000)
                                          .strftime('%Y-%m-%d %H:%M UTC'),
                        'entry':      entry,
                        'sl':         sl,
                        'tp':         tp,
                        'rsi':        calculate_rsi(closes_all[:pending_setup_i + 1], RSI_PERIOD),
                        'ema9':       calculate_ema(closes_all[:pending_setup_i + 1], EMA_SHORT),
                        'ema26':      calculate_ema(closes_all[:pending_setup_i + 1], EMA_LONG),
                        'ma44':       calculate_sma(closes_all[:pending_setup_i + 1], MA_PERIOD),
                        'outcome':    outcome,
                    })
                    last_signal_ts = candle_ts

            # Either triggered or not — setup is consumed (option A: discard if not triggered)
            pending_direction = None
            pending_setup_i   = None

        # ── CHECK B: Setup candle ─────────────────────────────────────────────
        # Check if THIS candle qualifies as a setup candle
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
    terminal.write("30-DAY BACKTEST — Updated Signal Logic\n")
    terminal.write("=" * 70 + "\n")
    terminal.write(f"Period  : {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')} UTC\n")
    terminal.write(f"Symbols : {len(SYMBOLS)}\n")
    terminal.write("=" * 70 + "\n\n")
    terminal.write("SETUP CANDLE  : RSI range + EMA9 vs EMA26 position + both EMAs vs MA44\n")
    terminal.write("              + bullish/bearish candle + close above/below all 3 MAs\n")
    terminal.write("TRIGGER CANDLE: MA44 slope confirmed + current open > setup open (LONG)\n")
    terminal.write("              :                      + current open < setup open (SHORT)\n")
    terminal.write("ENTRY         : Open of trigger candle\n")
    terminal.write("=" * 70 + "\n\n")

    all_signals   = []
    symbols_ok    = 0
    symbols_err   = 0

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
        p("30-DAY BACKTEST REPORT — Updated Signal Logic")
        p("=" * 80)
        p(f"Period    : {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')} UTC")
        p(f"Generated : {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        p(f"Symbols   : {symbols_ok} scanned  |  {symbols_err} errors")
        p()
        p("LOGIC SUMMARY:")
        p("  SETUP candle (previous closed candle):")
        p("    LONG : RSI 45.1-85 | EMA9>EMA26 | both EMAs>MA44 | bullish | close>all 3 MAs")
        p("    SHORT: RSI 10-45   | EMA9<EMA26 | both EMAs<MA44 | bearish | close<all 3 MAs")
        p("  TRIGGER candle (current candle, fires at open):")
        p("    LONG : MA44(setup) > MA44(before setup)  AND  open > setup candle open")
        p("    SHORT: MA44(setup) < MA44(before setup)  AND  open < setup candle open")
        p("  Entry = open of trigger candle")
        p("  SL/TP from entry: LONG SL=-0.5% TP=+1.5% | SHORT SL=+0.5% TP=-1.5%")
        p("=" * 80)
        p()

        total  = len(all_signals)
        wins   = sum(1 for s in all_signals if s['outcome'] == 'WIN')
        losses = sum(1 for s in all_signals if s['outcome'] == 'LOSS')
        longs  = sum(1 for s in all_signals if s['type'] == 'LONG')
        shorts = sum(1 for s in all_signals if s['type'] == 'SHORT')
        ongoing= sum(1 for s in all_signals if s['outcome'] == 'ONGOING')
        unknown= sum(1 for s in all_signals if s['outcome'] == 'UNKNOWN')

        if total == 0:
            p("NO SIGNALS found in the past 30 days.")
            p()
            p("Possible reasons:")
            p("  - Condition 5 (close above/below ALL 3 MAs) is quite strict")
            p("  - MA44 slope requires confirmed directional move")
            p("  - Open price gap condition filters out flat opens")
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
                p(f"  Setup  : {setup_time}")
                p(f"  Entry  : ${sig['entry']:.4f}  "
                  f"SL: ${sig['sl']:.4f}  TP: ${sig['tp']:.4f}")
                p(f"  RSI={sig['rsi']:.1f}  EMA9={sig['ema9']:.4f}  "
                  f"EMA26={sig['ema26']:.4f}  MA44={sig['ma44']:.4f}")
            p()

            # ── Summary ───────────────────────────────────────────────────────
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
                p(f"  R/R ratio     : 1:{TP_PERCENT/SL_PERCENT:.0f}  "
                  f"(SL {SL_PERCENT}%  /  TP {TP_PERCENT}%)")
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

                # Per-symbol breakdown
                p("=" * 80)
                p("PER-SYMBOL BREAKDOWN")
                p("=" * 80)
                p(f"  {'Symbol':<14} {'Sigs':>5} {'Long':>5} {'Short':>6} "
                  f"{'Win':>5} {'Loss':>5} {'Open':>5} {'WinRate':>8}")
                p("  " + "-" * 60)
                for sym in sorted(set(s['symbol'] for s in all_signals)):
                    ss   = [s for s in all_signals if s['symbol'] == sym]
                    sw   = sum(1 for s in ss if s['outcome'] == 'WIN')
                    sl_  = sum(1 for s in ss if s['outcome'] == 'LOSS')
                    so   = sum(1 for s in ss if s['outcome'] == 'ONGOING')
                    lo   = sum(1 for s in ss if s['type'] == 'LONG')
                    sh   = sum(1 for s in ss if s['type'] == 'SHORT')
                    wr   = f"{sw/(sw+sl_)*100:.0f}%" if sw + sl_ > 0 else "n/a"
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
        p()
        p("  Entry = open of trigger candle.")
        p("  Outcome checked from trigger candle open onward.")
        p("=" * 80)

    wins_final   = sum(1 for s in all_signals if s['outcome'] == 'WIN')
    losses_final = sum(1 for s in all_signals if s['outcome'] == 'LOSS')
    closed_final = wins_final + losses_final

    terminal.write(f"\nDone. Report → signal_analysis_report_new.txt\n")
    terminal.write(f"Signals: {len(all_signals)}  |  "
                   f"Wins: {wins_final}  Losses: {losses_final}  "
                   + (f"Win rate: {wins_final/closed_final*100:.1f}%"
                      if closed_final > 0 else "No closed trades") + "\n")


if __name__ == "__main__":
    main()