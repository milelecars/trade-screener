"""
BTC/USDT BACKTEST — Logic No. 2b Enhanced
==========================================
MA44 Bounce Strategy — F2 Sensitivity Test

Runs the full backtest TWICE on each period:
  Run A : F2 min dist >= 0.10%
  Run B : F2 min dist >= 0.15%

All other parameters identical.
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
SL_PERCENT         = 2
TP_PERCENT         = 6
COOLDOWN_MS        = 4 * 60 * 60 * 1000

MIN_BODY_RATIO     = 0.45
MAX_DISTANCE_PCT   = 0.0065  # F3 — 0.65% max (unchanged)
MAX_WICK_PCT       = 0.0100  # F4 max
MIN_WICK_PCT       = 0.0035  # F4 min
SLOPE_LOOKBACK     = 8       # F5 window
MA_SLOPE_MIN_PCT   = 0.10    # F5 magnitude
MA_ACCEL_BARS      = 4       # F6
ATR_PERIOD         = 14      # F7
ATR_MAX_PCT        = 0.0060  # F7
H4_MA_PERIOD       = 44      # F8
H4_SLOPE_BARS      = 4       # F8
CONSEC_LOSS_PAUSE  = 2       # F9
CONSEC_LOSS_MS     = 8 * 60 * 60 * 1000  # F9

# ── F2 variants being compared ───────────────────────────────────────────────
F2_VARIANTS = [
    {'label': 'F2 >= 0.10%', 'min_dist': 0.0010},
    {'label': 'F2 >= 0.15%', 'min_dist': 0.0015},
]

SYMBOL = 'BTCUSDT'

PERIODS = [
    {
        'label':    'Period 1 -- BTC/USDT  |  27 Feb 2025 -> 26 Feb 2026',
        'start_dt': datetime(2025, 2, 27, 0, 0, 0, tzinfo=timezone.utc),
        'end_dt':   datetime(2026, 2, 26, 23, 59, 59, tzinfo=timezone.utc),
    },
]

# ============================================================================
# HELPERS
# ============================================================================

def calculate_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calculate_atr(highs, lows, closes, period):
    if len(highs) < period + 1:
        return None
    ranges = [highs[i] - lows[i] for i in range(len(highs) - period, len(highs))]
    return sum(ranges) / period


def fetch_h4_candles(symbol, end_ts, limit=200):
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={'symbol': symbol, 'interval': '4h',
                    'endTime': end_ts, 'limit': limit},
            timeout=15
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, list) or len(data) < H4_MA_PERIOD + H4_SLOPE_BARS + 1:
            return None
        return data
    except Exception:
        return None


def get_h4_ma44_direction(symbol, ts_ms):
    candles = fetch_h4_candles(symbol, ts_ms, limit=H4_MA_PERIOD + H4_SLOPE_BARS + 10)
    if candles is None:
        return None
    h4_closes = [float(c[4]) for c in candles]
    ma_now  = calculate_sma(h4_closes,                  H4_MA_PERIOD)
    ma_prev = calculate_sma(h4_closes[:-H4_SLOPE_BARS], H4_MA_PERIOD)
    if ma_now is None or ma_prev is None:
        return None
    return ma_now > ma_prev

# ============================================================================
# STEP 1 — SETUP CANDLE CHECK
# ============================================================================

def check_setup_candle(closes, opens, highs, lows, min_distance_pct):
    min_len = MA_PERIOD + SLOPE_LOOKBACK + ATR_PERIOD + 5
    if len(closes) < min_len:
        return None

    c_close = closes[-1]
    c_open  = opens[-1]
    c_high  = highs[-1]
    c_low   = lows[-1]

    ma44 = calculate_sma(closes, MA_PERIOD)
    if ma44 is None:
        return None

    # F5 — slope magnitude
    ma44_8ago = calculate_sma(closes[:-SLOPE_LOOKBACK], MA_PERIOD)
    if ma44_8ago is None:
        return None
    ma_slope_pct = (ma44 - ma44_8ago) / ma44 * 100
    if abs(ma_slope_pct) < MA_SLOPE_MIN_PCT:
        return None

    # monotonic slope check
    ma44_series = []
    for k in range(SLOPE_LOOKBACK, -1, -1):
        val = calculate_sma(closes[:-k] if k > 0 else closes, MA_PERIOD)
        if val is None:
            return None
        ma44_series.append(val)

    ma44_continuously_down = all(ma44_series[i] > ma44_series[i + 1] for i in range(len(ma44_series) - 1))
    ma44_continuously_up   = all(ma44_series[i] < ma44_series[i + 1] for i in range(len(ma44_series) - 1))

    # F6 — acceleration
    ma44_4ago  = calculate_sma(closes[:-MA_ACCEL_BARS],           MA_PERIOD)
    ma44_8ago2 = calculate_sma(closes[:-MA_ACCEL_BARS * 2],       MA_PERIOD)
    if ma44_4ago is None or ma44_8ago2 is None:
        return None
    slope_recent     = ma44 - ma44_4ago
    slope_prior      = ma44_4ago - ma44_8ago2
    ma_accel_ok_down = (slope_recent < slope_prior < 0)
    ma_accel_ok_up   = (slope_recent > slope_prior > 0)

    # candle geometry
    body_top    = max(c_open, c_close)
    body_bottom = min(c_open, c_close)
    candle_size = c_high - c_low
    body_size   = body_top - body_bottom
    wick_pct    = candle_size / c_high if c_high > 0 else 0
    body_ratio  = body_size / candle_size if candle_size > 0 else 0
    min_dist    = ma44 * min_distance_pct        # ← F2: variable
    max_dist    = ma44 * MAX_DISTANCE_PCT         # ← F3: fixed

    # F1
    if body_ratio < MIN_BODY_RATIO:
        return None
    # F4
    if wick_pct < MIN_WICK_PCT or wick_pct > MAX_WICK_PCT:
        return None

    # SHORT
    if c_close < c_open:
        dist     = ma44 - body_top
        if (ma44_continuously_down and body_top < ma44 and
                min_dist <= dist <= max_dist and ma_accel_ok_down):
            return 'SHORT'

    # LONG
    if c_close > c_open:
        dist     = body_bottom - ma44
        if (ma44_continuously_up and body_bottom > ma44 and
                min_dist <= dist <= max_dist and ma_accel_ok_up):
            return 'LONG'

    return None

# ============================================================================
# STEP 2 — VALIDATION CANDLE CHECK
# ============================================================================

def check_validation_candle(opens, closes, direction, setup_index):
    ma44 = calculate_sma(closes[:setup_index + 1], MA_PERIOD)
    if ma44 is None:
        return None
    val_open = opens[setup_index + 1]
    if direction == 'SHORT' and val_open < ma44:
        return val_open
    if direction == 'LONG'  and val_open > ma44:
        return val_open
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

def scan_period(start_ts, end_ts, min_distance_pct):
    warmup_ms     = (MA_PERIOD + SLOPE_LOOKBACK + ATR_PERIOD + 10) * 15 * 60 * 1000
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

    if len(all_candles) < MA_PERIOD + SLOPE_LOOKBACK + ATR_PERIOD + 10:
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
    consec_loss       = {'LONG': 0, 'SHORT': 0}
    pause_until       = {'LONG': 0, 'SHORT': 0}
    h4_cache          = {}
    start_i           = MA_PERIOD + SLOPE_LOOKBACK + ATR_PERIOD + 5

    for i in range(start_i, len(all_candles) - 1):
        candle_ts = times_all[i]
        in_window = (start_ts <= candle_ts <= end_ts)

        # STEP 2 — fire if pending
        if pending_direction is not None:
            entry = check_validation_candle(opens_all, closes_all, pending_direction, pending_setup_i)

            if entry is not None and in_window:
                side = pending_direction
                if candle_ts >= pause_until[side] and candle_ts - last_signal_ts >= COOLDOWN_MS:
                    sl  = entry * (1 - SL_PERCENT / 100) if side == 'LONG' else entry * (1 + SL_PERCENT / 100)
                    tp  = entry * (1 + TP_PERCENT / 100) if side == 'LONG' else entry * (1 - TP_PERCENT / 100)
                    si  = pending_setup_i

                    ma44_val    = calculate_sma(closes_all[:si + 1], MA_PERIOD)
                    setup_open  = opens_all[si]
                    setup_close = closes_all[si]
                    setup_high  = highs_all[si]
                    setup_low   = lows_all[si]
                    candle_size = setup_high - setup_low
                    body_top    = max(setup_open, setup_close)
                    body_bot    = min(setup_open, setup_close)
                    body_size   = body_top - body_bot
                    wick_pct_s  = candle_size / setup_high * 100 if setup_high > 0 else 0
                    body_ratio  = body_size / candle_size if candle_size > 0 else 0
                    dist_pct    = (
                        (ma44_val - body_top) / ma44_val * 100
                        if side == 'SHORT'
                        else (body_bot - ma44_val) / ma44_val * 100
                    )
                    ma44_8ago   = calculate_sma(closes_all[:si + 1 - SLOPE_LOOKBACK], MA_PERIOD)
                    slope_pct   = (ma44_val - ma44_8ago) / ma44_val * 100 if ma44_8ago else 0
                    atr_val     = calculate_atr(highs_all[:si + 1], lows_all[:si + 1], closes_all[:si + 1], ATR_PERIOD)
                    atr_pct     = atr_val / closes_all[si] * 100 if atr_val else 0

                    outcome = check_trade_outcome(candle_ts, entry, sl, tp, side)

                    signals.append({
                        'type': side, 'setup_ts': times_all[si],
                        'setup_time':  datetime.fromtimestamp(times_all[si] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                        'entry_ts':    candle_ts,
                        'entry_time':  datetime.fromtimestamp(candle_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                        'entry': entry, 'sl': sl, 'tp': tp,
                        'ma44': ma44_val, 'slope_pct': slope_pct, 'atr_pct': atr_pct,
                        'setup_open': setup_open, 'setup_close': setup_close,
                        'setup_high': setup_high, 'setup_low': setup_low,
                        'wick_pct': wick_pct_s, 'body_ratio': body_ratio,
                        'dist_pct': dist_pct, 'outcome': outcome,
                    })
                    last_signal_ts = candle_ts

                    if outcome == 'LOSS':
                        consec_loss[side] += 1
                        other = 'LONG' if side == 'SHORT' else 'SHORT'
                        consec_loss[other] = 0
                        if consec_loss[side] >= CONSEC_LOSS_PAUSE:
                            pause_until[side] = candle_ts + CONSEC_LOSS_MS
                            consec_loss[side] = 0
                    elif outcome == 'WIN':
                        consec_loss[side] = 0

            pending_direction = None
            pending_setup_i   = None

        # STEP 1 — check setup
        if not in_window:
            continue

        direction = check_setup_candle(
            closes_all[:i + 1], opens_all[:i + 1],
            highs_all[:i + 1],  lows_all[:i + 1],
            min_distance_pct
        )
        if direction is None:
            continue

        # F7 — ATR
        atr_now = calculate_atr(highs_all[:i + 1], lows_all[:i + 1], closes_all[:i + 1], ATR_PERIOD)
        if atr_now is not None and (atr_now / closes_all[i] * 100) >= ATR_MAX_PCT * 100:
            continue

        # F8 — 4H gate
        h4_bucket = (candle_ts // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
        if h4_bucket not in h4_cache:
            h4_cache[h4_bucket] = get_h4_ma44_direction(SYMBOL, candle_ts)
        h4_rising = h4_cache[h4_bucket]
        if h4_rising is not None:
            if direction == 'LONG'  and not h4_rising: continue
            if direction == 'SHORT' and h4_rising:     continue

        pending_direction = direction
        pending_setup_i   = i

    return signals

# ============================================================================
# OHLC CSV EXPORT
# ============================================================================

def generate_ohlc_csv(start_ts, end_ts, filename='btc_ohlc_15m.csv'):
    all_candles   = []
    current_start = start_ts
    while current_start < end_ts:
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={'symbol': SYMBOL, 'interval': '15m',
                        'startTime': current_start, 'endTime': end_ts, 'limit': 1000},
                timeout=15
            )
        except Exception as e:
            print(f"OHLC fetch error: {e}")
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
    if not all_candles:
        return None
    with open(filename, 'w', encoding='utf-8') as f:
        f.write('datetime_utc,open,high,low,close,volume\n')
        for c in all_candles:
            dt = datetime.fromtimestamp(int(c[0]) / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
            f.write(f'{dt},{c[1]},{c[2]},{c[3]},{c[4]},{c[5]}\n')
    return filename

# ============================================================================
# TEXT REPORT
# ============================================================================

def _period_block(f, period_num, period, signals, min_dist_pct, p, div):
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
        return

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
        'EXCELLENT  (>60%)'   if wr >= 60 else
        'GOOD       (>50%)'   if wr >= 50 else
        'MARGINAL   (40-50%)' if wr >= 40 else
        'WEAK       (25-40%)' if wr >= 25 else
        'POOR       (<25%)'
    ) if closed > 0 else 'NO CLOSED TRADES'

    p('  SUMMARY')
    div('-')
    p(f'  F2 min dist     : >= {min_dist_pct*100:.2f}%')
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
        ol       = {'WIN': '[WIN ]', 'LOSS': '[LOSS]', 'ONGOING': '[OPEN]', 'UNKNOWN': '[????]'}.get(s['outcome'], '[????]')
        sl_label = f'-{SL_PERCENT}%' if s['type'] == 'LONG' else f'+{SL_PERCENT}%'
        tp_label = f'+{TP_PERCENT}%' if s['type'] == 'LONG' else f'-{TP_PERCENT}%'
        p(f'  Signal #{idx:<3}  {ol}  {s["type"]:<6}  Entry: {s["entry_time"]}')
        p(f'  Setup candle  : {s["setup_time"]}  '
          f'open={s["setup_open"]:.2f}  close={s["setup_close"]:.2f}  '
          f'wick={s["wick_pct"]:.2f}%  body={s["body_ratio"]*100:.1f}%  dist={s["dist_pct"]:.3f}%')
        p(f'  MA44          : {s["ma44"]:.2f}  slope_8bar={s["slope_pct"]:+.3f}%  ATR={s["atr_pct"]:.3f}%')
        p(f'  Entry         : ${s["entry"]:.2f}')
        p(f'  Stop Loss     : ${s["sl"]:.2f}  ({sl_label})')
        p(f'  Take Profit   : ${s["tp"]:.2f}  ({tp_label})')
        p()

    div('-')
    p()


def generate_txt(all_results, filename='btc_backtest_v2b_report.txt'):
    W   = 80
    gen = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    with open(filename, 'w', encoding='utf-8') as f:

        def p(line=''):
            print(line, file=f)

        def div(char='='):
            p(char * W)

        div('=')
        p('BTC/USDT -- BACKTEST REPORT  (Logic No. 2b Enhanced -- F2 Sensitivity)')
        p('15-minute candles  |  Binance  |  No RSI  |  No Crossovers')
        p(f'Generated : {gen}')
        p(f'SL: -{SL_PERCENT}%  |  TP: +{TP_PERCENT}%  |  R/R 1:3  |  Cooldown: 4h')
        p()
        p('F2 VARIANTS COMPARED:')
        p('  Run A : F2 min dist >= 0.10%')
        p('  Run B : F2 min dist >= 0.15%')
        p()
        p('ALL OTHER FILTERS (unchanged):')
        p(f'  F1  body_ratio  >= {MIN_BODY_RATIO:.2f}')
        p(f'  F3  max dist    <= {MAX_DISTANCE_PCT*100:.2f}%')
        p(f'  F4  wick range  {MIN_WICK_PCT*100:.2f}%–{MAX_WICK_PCT*100:.2f}%')
        p(f'  F5  slope 8-bar abs >= {MA_SLOPE_MIN_PCT:.2f}%')
        p(f'  F6  ma accel    current 4-bar > prior 4-bar')
        p(f'  F7  ATR(14)     < {ATR_MAX_PCT*100:.2f}% of price')
        p(f'  F8  4H MA gate  direction must match')
        p(f'  F9  consec loss {CONSEC_LOSS_PAUSE} losses → {CONSEC_LOSS_MS//3600000}h pause')
        div('=')
        p()

        # ── Comparison summary table ──────────────────────────────────────────
        div('*')
        p('  COMPARISON SUMMARY')
        div('*')
        p()
        p(f'  {"Period":<38}  {"Variant":<14}  {"Sig":>4}  {"W":>4}  {"L":>4}  {"WR%":>6}  {"PnL%":>7}')
        div('-')
        for variant, period_results in all_results:
            for period, signals in period_results:
                wins   = sum(1 for s in signals if s['outcome'] == 'WIN')
                losses = sum(1 for s in signals if s['outcome'] == 'LOSS')
                closed = wins + losses
                total  = len(signals)
                wr     = f'{wins/closed*100:.1f}' if closed > 0 else 'n/a'
                pnl    = f'{(wins*TP_PERCENT)-(losses*SL_PERCENT):+.2f}' if closed > 0 else 'n/a'
                plabel = period['label'].split('|')[-1].strip()[:36]
                p(f'  {plabel:<38}  {variant["label"]:<14}  {total:>4}  {wins:>4}  {losses:>4}  {wr:>6}  {pnl:>7}')
        div('-')
        p()

        # ── Full detail per variant ───────────────────────────────────────────
        for variant, period_results in all_results:
            div('=')
            p(f'  VARIANT: {variant["label"]}  (F2 min dist >= {variant["min_dist"]*100:.2f}%)')
            div('=')
            p()
            for period_num, (period, signals) in enumerate(period_results, 1):
                _period_block(f, period_num, period, signals, variant['min_dist'], p, div)

        div('=')
        p('METHODOLOGY')
        div('=')
        p('  WIN     : TP hit before SL within 48h of entry')
        p('  LOSS    : SL hit before TP within 48h of entry')
        p('  ONGOING : Neither hit within 48h')
        p('  UNKNOWN : Data unavailable')
        p()
        p('  F2 tests whether tightening the minimum distance floor from 0.10% to')
        p('  0.15% improves quality by rejecting candles that barely clear MA44.')
        div('=')

    return filename

# ============================================================================
# MAIN
# ============================================================================

def main():
    t = sys.__stdout__
    t.write('\n' + '=' * 60 + '\n')
    t.write('BTC/USDT BACKTEST -- Logic No. 2b  F2 Sensitivity Test\n')
    t.write('=' * 60 + '\n\n')
    t.write('  Comparing F2 >= 0.10%  vs  F2 >= 0.15%\n')
    t.write('  All other parameters unchanged.\n\n')

    all_results = []

    for variant in F2_VARIANTS:
        t.write(f"\n── Variant: {variant['label']} ──\n")
        period_results = []

        for period in PERIODS:
            t.write(f"  --- {period['label']}\n")
            start_ts = int(period['start_dt'].timestamp() * 1000)
            end_ts   = int(period['end_dt'].timestamp()   * 1000)
            days     = (period['end_dt'] - period['start_dt']).days

            t.write(f'      Scanning {days} days... ')
            t.flush()

            signals = scan_period(start_ts, end_ts, variant['min_dist'])

            if signals is None:
                t.write('ERROR fetching data\n')
                period_results.append((period, []))
                continue

            wins   = sum(1 for s in signals if s['outcome'] == 'WIN')
            losses = sum(1 for s in signals if s['outcome'] == 'LOSS')
            closed = wins + losses
            wr     = f'{wins/closed*100:.1f}%' if closed > 0 else 'n/a'
            t.write(f'{len(signals)} signals  [W:{wins} L:{losses} WR:{wr}]\n')

            period_results.append((period, signals))
            time.sleep(0.2)

        all_results.append((variant, period_results))

    # ── OHLC CSV (once, shared across variants) ───────────────────────────────
    t.write('\nExporting OHLC data...\n')
    for period in PERIODS:
        start_ts = int(period['start_dt'].timestamp() * 1000)
        end_ts   = int(period['end_dt'].timestamp()   * 1000)
        safe     = (period['label']
                    .replace(' ', '_').replace('|', '').replace('/', '-')
                    .replace('→', '-').replace('>', '-').replace(':', ''))
        csv_name = f"ohlc_{safe[:50].strip()}.csv"
        csv_file = generate_ohlc_csv(start_ts, end_ts, csv_name)
        if csv_file:
            candle_count = sum(1 for _ in open(csv_file)) - 1
            t.write(f'  Done -> {csv_file}  ({candle_count} candles)\n')
        else:
            t.write(f'  ERROR exporting OHLC for {period["label"]}\n')

    t.write('\nWriting report...\n')
    fname = generate_txt(all_results)
    t.write(f'Done -> {fname}\n\n')


if __name__ == '__main__':
    main()