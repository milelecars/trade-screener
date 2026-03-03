"""
BTC/USDT BACKTEST — Logic No. 2
================================
MA44 Bounce Strategy — No RSI, No Crossovers

TWO-STEP SIGNAL:
  Step 1 — Setup candle:
    SHORT: bearish candle, body entirely below MA44 (sloppiness tolerance),
           body top within 0.4% of MA44, body size >= 0.3%, MA44 sloping down.
    LONG:  bullish candle, body entirely above MA44 (sloppiness tolerance),
           body bottom within 0.4% of MA44, body size >= 0.3%, MA44 sloping up.

  Step 2 — Validation/trigger candle (next candle after setup):
    SHORT: must open below MA44
    LONG:  must open above MA44
    Entry = open of validation candle.

Sloppiness = minimum required MA44 slope over SLOPE_LOOKBACK candles (0.2%).
             MA44 must have moved at least 0.2% to be considered trending.

Cooldown : 4 hours
SL       : 0.5%
TP       : 1.5%
Output   : btc_backtest_v2_report.txt

PERIODS:
  Period 1: 10 Oct 2024 → 18 Dec 2024
  Period 2: 07 Oct 2025 → 25 Nov 2025
"""

import requests
import pandas as pd
from datetime import datetime, timezone
import sys
import time

# ============================================================================
# PARAMETERS
# ============================================================================

MA_PERIOD          = 44
SL_PERCENT         = 0.5
TP_PERCENT         = 1.5
COOLDOWN_MS        = 4 * 60 * 60 * 1000      # 4 hours

MIN_CANDLE_SIZE    = 0.0035  # 0.35% — min wick size (high to low) relative to high
MAX_DISTANCE_PCT   = 0.0075  # 0.75% — max distance of closest body edge from MA44
SLOPE_LOOKBACK     = 4       # candles back for MA44 slope check (1 hour)
SLOPE_MIN_PCT      = 0.002   # 0.2% — MA44 must have moved at least this much over SLOPE_LOOKBACK candles

SYMBOL = 'BTCUSDT'

PERIODS = [
    {
        'label':    'Period 1 -- BTC/USDT  |  27 Jan 2026 -> 26 Feb 2026',
        'start_dt': datetime(2026, 1, 27, 0, 0, 0, tzinfo=timezone.utc),
        'end_dt':   datetime(2026, 2, 26, 23, 59, 59, tzinfo=timezone.utc),
    },
]

# ============================================================================
# MA44 HELPER
# ============================================================================

def calculate_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

# ============================================================================
# STEP 1 — SETUP CANDLE CHECK
# ============================================================================

def check_setup_candle(closes, opens, highs, lows):
    """
    Returns 'LONG', 'SHORT', or None.

    SHORT setup:
      - Bearish candle (close < open)
      - MA44 continuously decreasing for each of the last 4 candles (monotonic drop)
      - Entire body strictly below MA44 (body_top < ma44, no sloppiness)
      - Body top within MAX_DISTANCE_PCT of MA44
      - Wick size (high - low) >= MIN_CANDLE_SIZE (0.35%)

    LONG setup (mirror):
      - Bullish candle (close > open)
      - MA44 continuously increasing for each of the last 4 candles (monotonic rise)
      - Entire body strictly above MA44 (body_bottom > ma44, no sloppiness)
      - Body bottom within MAX_DISTANCE_PCT of MA44
      - Wick size (high - low) >= MIN_CANDLE_SIZE (0.35%)
    """
    if len(closes) < MA_PERIOD + SLOPE_LOOKBACK + 2:
        return None

    c_close  = closes[-1]
    c_open   = opens[-1]
    c_high   = highs[-1]
    c_low    = lows[-1]

    ma44 = calculate_sma(closes, MA_PERIOD)
    if ma44 is None:
        return None

    # Check MA44 is continuously decreasing/increasing over last SLOPE_LOOKBACK candles
    # i.e. each candle's MA44 is lower/higher than the previous one
    ma44_series = []
    for k in range(SLOPE_LOOKBACK, -1, -1):   # from oldest to current
        val = calculate_sma(closes[:-k] if k > 0 else closes, MA_PERIOD)
        if val is None:
            return None
        ma44_series.append(val)

    ma44_continuously_down = all(ma44_series[i] > ma44_series[i+1] for i in range(len(ma44_series)-1))
    ma44_continuously_up   = all(ma44_series[i] < ma44_series[i+1] for i in range(len(ma44_series)-1))

    body_top    = max(c_open, c_close)
    body_bottom = min(c_open, c_close)
    wick_size   = (c_high - c_low) / c_high   # wick as % of high
    dist_abs    = ma44 * MAX_DISTANCE_PCT

    # ── SHORT ──────────────────────────────────────────────────────────────
    if c_close < c_open:                               # bearish candle
        slope_ok = ma44_continuously_down              # MA44 falling every candle for 4
        below_ok = body_top < ma44                     # body strictly below MA44 (no sloppiness)
        dist_ok  = (ma44 - body_top) <= dist_abs       # body top within 0.75% of MA44
        size_ok  = wick_size >= MIN_CANDLE_SIZE        # wick >= 0.35%
        if slope_ok and below_ok and dist_ok and size_ok:
            return 'SHORT'

    # ── LONG ───────────────────────────────────────────────────────────────
    if c_close > c_open:                               # bullish candle
        slope_ok = ma44_continuously_up                # MA44 rising every candle for 4
        above_ok = body_bottom > ma44                  # body strictly above MA44 (no sloppiness)
        dist_ok  = (body_bottom - ma44) <= dist_abs    # body bottom within 0.75% of MA44
        size_ok  = wick_size >= MIN_CANDLE_SIZE        # wick >= 0.35%
        if slope_ok and above_ok and dist_ok and size_ok:
            return 'LONG'

    return None

# ============================================================================
# STEP 2 — VALIDATION CANDLE CHECK
# ============================================================================

def check_validation_candle(opens, closes, direction, setup_index):
    """
    The validation candle is the candle immediately after the setup candle.
    SHORT: validation candle must open below MA44
    LONG:  validation candle must open above MA44

    We compute MA44 using data up to and including the setup candle.
    Entry = open of validation candle.
    """
    # MA44 at setup candle (setup_index = i, validation = i+1)
    ma44 = calculate_sma(closes[:setup_index + 1], MA_PERIOD)
    if ma44 is None:
        return None

    val_open = opens[setup_index + 1]

    if direction == 'SHORT' and val_open < ma44:
        return val_open   # entry price
    if direction == 'LONG'  and val_open > ma44:
        return val_open   # entry price

    return None

# ============================================================================
# OUTCOME CHECKER
# ============================================================================

def check_trade_outcome(signal_ts_ms, entry, sl, tp, stype):
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={'symbol': SYMBOL, 'interval': '15m',
                    'startTime': signal_ts_ms,
                    'endTime':   signal_ts_ms + 48 * 3600 * 1000,
                    'limit': 200},
            timeout=10
        )
        if resp.status_code != 200:
            return 'UNKNOWN'
        candles = resp.json()
        if not isinstance(candles, list) or len(candles) == 0:
            return 'ONGOING'
        for idx, c in enumerate(candles):
            h = float(c[2])
            l = float(c[3])
            if idx == 0:
                # First candle: entry is at open, use open as starting reference
                if stype == 'LONG':  l = min(float(c[1]), float(c[4]))
                else:                h = max(float(c[1]), float(c[4]))
            if stype == 'LONG':
                if l <= sl: return 'LOSS'
                if h >= tp: return 'WIN'
            else:
                if h >= sl: return 'LOSS'
                if l <= tp: return 'WIN'
        return 'ONGOING'
    except Exception:
        return 'UNKNOWN'

# ============================================================================
# SCANNER
# ============================================================================

def scan_period(start_ts, end_ts):
    warmup_ms     = (MA_PERIOD + SLOPE_LOOKBACK + 5) * 15 * 60 * 1000
    fetch_start   = start_ts - warmup_ms
    all_candles   = []
    current_start = fetch_start

    while current_start < end_ts:
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={'symbol': SYMBOL, 'interval': '15m',
                        'startTime': current_start, 'endTime': end_ts, 'limit': 1000},
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

    if len(all_candles) < MA_PERIOD + SLOPE_LOOKBACK + 5:
        return None

    closes_all = [float(c[4]) for c in all_candles]
    opens_all  = [float(c[1]) for c in all_candles]
    highs_all  = [float(c[2]) for c in all_candles]
    lows_all   = [float(c[3]) for c in all_candles]
    times_all  = [int(c[0])   for c in all_candles]

    signals           = []
    last_signal_ts    = 0
    pending_direction = None
    pending_setup_i   = None
    start_i           = MA_PERIOD + SLOPE_LOOKBACK + 2

    for i in range(start_i, len(all_candles) - 1):
        candle_ts = times_all[i]
        in_window = (start_ts <= candle_ts <= end_ts)

        # ── STEP 2: check validation candle if we have a pending setup ──────
        if pending_direction is not None:
            entry = check_validation_candle(opens_all, closes_all, pending_direction, pending_setup_i)

            if entry is not None and in_window:
                if candle_ts - last_signal_ts >= COOLDOWN_MS:
                    sl  = entry * (1 - SL_PERCENT / 100) if pending_direction == 'LONG' else entry * (1 + SL_PERCENT / 100)
                    tp  = entry * (1 + TP_PERCENT / 100) if pending_direction == 'LONG' else entry * (1 - TP_PERCENT / 100)
                    si  = pending_setup_i
                    ma44_val    = calculate_sma(closes_all[:si + 1], MA_PERIOD)
                    setup_open  = opens_all[si]
                    setup_close = closes_all[si]
                    setup_high  = highs_all[si]
                    setup_low   = lows_all[si]
                    wick_pct    = (setup_high - setup_low) / setup_high * 100
                    body_top    = max(setup_open, setup_close)
                    body_bot    = min(setup_open, setup_close)
                    dist_pct    = (
                        (ma44_val - body_top) / ma44_val * 100
                        if pending_direction == 'SHORT'
                        else (body_bot - ma44_val) / ma44_val * 100
                    )

                    signals.append({
                        'type':        pending_direction,
                        'setup_ts':    times_all[si],
                        'setup_time':  datetime.fromtimestamp(times_all[si] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                        'entry_ts':    candle_ts,
                        'entry_time':  datetime.fromtimestamp(candle_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                        'entry':       entry,
                        'sl':          sl,
                        'tp':          tp,
                        'ma44':        ma44_val,
                        'setup_open':  setup_open,
                        'setup_close': setup_close,
                        'setup_high':  setup_high,
                        'setup_low':   setup_low,
                        'wick_pct':    wick_pct,
                        'dist_pct':    dist_pct,
                        'outcome':     check_trade_outcome(candle_ts, entry, sl, tp, pending_direction),
                    })
                    last_signal_ts = candle_ts

            # Always clear pending after one candle — validation is only the immediate next candle
            pending_direction = None
            pending_setup_i   = None

        # ── STEP 1: check setup candle ──────────────────────────────────────
        if in_window:
            direction = check_setup_candle(closes_all[:i + 1], opens_all[:i + 1], highs_all[:i + 1], lows_all[:i + 1])
            if direction is not None:
                pending_direction = direction
                pending_setup_i   = i

    return signals

# ============================================================================
# TEXT REPORT
# ============================================================================

def generate_txt(results, filename='btc_backtest_v2b_report.txt'):
    W   = 80
    gen = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    with open(filename, 'w', encoding='utf-8') as f:

        def p(line=''):
            print(line, file=f)

        def div(char='='):
            p(char * W)

        div('=')
        p('BTC/USDT -- BACKTEST REPORT  (Logic No. 2b -- MA44 Bounce, dist 0.75%)')
        p('15-minute candles  |  Binance  |  No RSI  |  No Crossovers')
        p(f'Generated : {gen}')
        p(f'SL: -{SL_PERCENT}%  |  TP: +{TP_PERCENT}%  |  R/R 1:3  |  Cooldown: 4h')
        p()
        p('PARAMETERS:')
        p(f'  MA44 slope         : {SLOPE_LOOKBACK} candles  |  continuously decreasing/increasing (no magnitude req)')
        p(f'  Min candle wick    : {MIN_CANDLE_SIZE*100:.2f}%  (high to low)')
        p(f'  Max dist from MA44 : {MAX_DISTANCE_PCT*100:.2f}%  (closest body edge to MA44)')
        p(f'  Sloppiness         : NONE  (body must be strictly below/above MA44)')
        p()
        p('SIGNAL LOGIC (TWO-STEP):')
        p('  Step 1 Setup  -- SHORT: bearish candle | MA44 falling every candle for 4 | body strictly below MA44')
        p('                          body top within 0.75% of MA44 | wick >= 0.35%')
        p('                   LONG: bullish candle | MA44 rising every candle for 4  | body strictly above MA44')
        p('                          body bottom within 0.75% of MA44 | wick >= 0.35%')
        p('  Step 2 Entry  -- open of the next candle after the validation candle closes')
        div('=')
        p()

        for period_num, (period, signals) in enumerate(results, 1):
            div('#')
            p(f'  PERIOD {period_num}  --  {period["label"]}')
            p(f'  {period["start_dt"].strftime("%d %b %Y")} -> '
              f'{period["end_dt"].strftime("%d %b %Y")}  '
              f'({(period["end_dt"] - period["start_dt"]).days} days)')
            div('#')
            p()

            if not signals:
                p('  No signals found in this period.')
                p()
                continue

            wins    = sum(1 for s in signals if s['outcome'] == 'WIN')
            losses  = sum(1 for s in signals if s['outcome'] == 'LOSS')
            ongoing = sum(1 for s in signals if s['outcome'] == 'ONGOING')
            unknown = sum(1 for s in signals if s['outcome'] == 'UNKNOWN')
            longs   = sum(1 for s in signals if s['type'] == 'LONG')
            shorts  = sum(1 for s in signals if s['type'] == 'SHORT')
            total   = len(signals)
            closed  = wins + losses
            wr      = wins / closed * 100 if closed > 0 else 0
            exp     = (wr / 100 * TP_PERCENT) - ((100 - wr) / 100 * SL_PERCENT) if closed > 0 else 0
            pnl     = (wins * TP_PERCENT) - (losses * SL_PERCENT)
            verdict = (
                'EXCELLENT  (>60%)'  if wr >= 60 else
                'GOOD       (>50%)'  if wr >= 50 else
                'MARGINAL   (40-50%)' if wr >= 40 else
                'WEAK       (25-40%)' if wr >= 25 else
                'POOR       (<25%)'
            ) if closed > 0 else 'NO CLOSED TRADES'

            p('  SUMMARY')
            div('-')
            p(f'  Total signals   : {total}  (Long: {longs}  Short: {shorts})')
            p(f'  Wins            : {wins}')
            p(f'  Losses          : {losses}')
            p(f'  Ongoing (<48h)  : {ongoing}')
            p(f'  Unknown         : {unknown}')
            p()
            if closed > 0:
                p(f'  Win rate        : {wr:.1f}%  ({wins}/{closed} closed)')
                p(f'  Expectancy      : {exp:+.3f}% per trade')
                p(f'  Total PnL       : {pnl:+.2f}%  (equal-size positions)')
                p(f'  Verdict         : {verdict}')
            else:
                p('  Win rate        : n/a')
            div('-')
            p()

            p('  SIGNALS')
            div('-')
            p()

            for idx, s in enumerate(sorted(signals, key=lambda x: x['entry_ts']), 1):
                ol       = {'WIN':'[WIN ]','LOSS':'[LOSS]','ONGOING':'[OPEN]','UNKNOWN':'[????]'}.get(s['outcome'], '[????]')
                sl_label = f'-{SL_PERCENT}%' if s['type'] == 'LONG' else f'+{SL_PERCENT}%'
                tp_label = f'+{TP_PERCENT}%' if s['type'] == 'LONG' else f'-{TP_PERCENT}%'

                p(f'  Signal #{idx:<3}  {ol}  {s["type"]:<6}  Entry: {s["entry_time"]}')
                p(f'  Setup candle  : {s["setup_time"]}  '
                  f'open={s["setup_open"]:.2f}  close={s["setup_close"]:.2f}  '
                  f'wick={s["wick_pct"]:.2f}%  dist_from_MA44={s["dist_pct"]:.3f}%')
                p(f'  MA44          : {s["ma44"]:.2f}')
                p(f'  Entry         : ${s["entry"]:.2f}')
                p(f'  Stop Loss     : ${s["sl"]:.2f}  ({sl_label})')
                p(f'  Take Profit   : ${s["tp"]:.2f}  ({tp_label})')
                p()

            div('-')
            p()

        div('=')
        p('METHODOLOGY')
        div('=')
        p('  WIN     : TP hit before SL within 48h of entry')
        p('  LOSS    : SL hit before TP within 48h of entry')
        p('  ONGOING : Neither hit within 48h')
        p('  UNKNOWN : Data unavailable')
        p()
        p('  Sloppiness : min required MA44 slope over 3 candles (0.2% = MA44 must have')
        p('               moved at least 0.2% in the right direction to qualify)')
        p('  Distance   : measures from closest body edge (not wick) to MA44')
        div('=')

    return filename

# ============================================================================
# MAIN
# ============================================================================

def main():
    t = sys.__stdout__
    t.write('\n' + '=' * 60 + '\n')
    t.write('BTC/USDT BACKTEST -- Logic No. 2b (MA44 Bounce, dist 0.75%)\n')
    t.write('=' * 60 + '\n\n')
    t.write(f'  Sloppiness : NONE (strict)\n')
    t.write(f'  Min wick   : {MIN_CANDLE_SIZE*100:.2f}%  (high to low)\n')
    t.write(f'  Max dist   : {MAX_DISTANCE_PCT*100:.2f}%\n')
    t.write(f'  Slope      : {SLOPE_LOOKBACK} candles continuous\n')
    t.write(f'  Cooldown   : 4h\n\n')

    results = []

    for period in PERIODS:
        t.write(f"--- {period['label']}\n")
        start_ts = int(period['start_dt'].timestamp() * 1000)
        end_ts   = int(period['end_dt'].timestamp()   * 1000)
        days     = (period['end_dt'] - period['start_dt']).days

        t.write(f'    Scanning {days} days... ')
        t.flush()

        signals = scan_period(start_ts, end_ts)

        if signals is None:
            t.write('ERROR fetching data\n\n')
            results.append((period, []))
            continue

        wins   = sum(1 for s in signals if s['outcome'] == 'WIN')
        losses = sum(1 for s in signals if s['outcome'] == 'LOSS')
        closed = wins + losses
        wr     = f'{wins/closed*100:.1f}%' if closed > 0 else 'n/a'

        t.write(f'{len(signals)} signals  [W:{wins} L:{losses} WR:{wr}]\n')
        results.append((period, signals))
        time.sleep(0.2)

    t.write('\nWriting report...\n')
    fname = generate_txt(results)
    t.write(f'Done -> {fname}\n\n')


if __name__ == '__main__':
    main()
    