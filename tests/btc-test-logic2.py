"""
BTC/USDT BACKTEST — Logic No. 2b (Enhanced v3)
===============================================
MA44 Bounce Strategy — SHORT ONLY — No RSI, No Crossovers

PERIOD : 01 Oct 2025 → 26 Feb 2026

CHANGES vs previous version:
  - SHORT only (LONGs disabled — 1W/8T over 5 months)
  - F5 hard reject: abs 8-bar slope < 0.10% → skip, no fallthrough
  - F6 strict sign: ma_accel must be negative for SHORT (steepening down)
  - F9 fixed: counter resets on WIN, pause compared against entry_ts
  - Distance zone split: accept 0.20–0.35% AND 0.50–0.65%, reject 0.35–0.50%
  - SL 2.0% / TP 6.0%  (was 1.5% / 4.5%)
  - Per-signal output: ma_slope_8bar, ma_accel, h4_ma_dir, atr_14_pct

TWO-STEP SIGNAL:
  Step 1 — Setup candle (all filters must pass):
    F1  body_ratio      : body / candle range >= 0.60
    F2a dist_from_MA44  : 0.20% <= dist <= 0.35%  (close bounce zone)
    F2b dist_from_MA44  : 0.50% <= dist <= 0.65%  (far bounce zone)
        [0.35–0.50% middle band REJECTED — 19% WR historically]
    F4  wick_pct        : 0.35% <= range/high <= 1.00%
    F5  ma_slope_8bar   : abs((MA[0]-MA[-8])/MA[0]*100) >= 0.10%  HARD REJECT
    F6  ma_accel        : slope_recent < slope_prior < 0  (steepening downtrend)
    F7  atr_14_pct      : ATR(14)/close < 0.60%
    F8  h4_ma44_dir     : 4h MA44 must be FALLING for SHORT
    F9  consec_loss     : 2 consecutive SHORT losses → pause 8h

  Step 2 — Validation candle (next candle after setup):
    SHORT: must open below MA44
    Entry = open of validation candle.

SL : 2.0%
TP : 6.0%
Cooldown : 4 hours
"""

import requests
import pandas as pd
from datetime import datetime, timezone
import sys
import time

# ============================================================================
# PARAMETERS
# ============================================================================

MA_PERIOD         = 44
SL_PERCENT        = 2.0
TP_PERCENT        = 6.0
COOLDOWN_MS       = 4 * 60 * 60 * 1000        # 4 hours

# F1
MIN_BODY_RATIO    = 0.60

# F2 — split distance zones (middle band 0.35–0.50% rejected)
DIST_ZONE_A_MIN   = 0.0020   # 0.20%
DIST_ZONE_A_MAX   = 0.0035   # 0.35%
DIST_ZONE_B_MIN   = 0.0050   # 0.50%
DIST_ZONE_B_MAX   = 0.0065   # 0.65%

# F4
MIN_WICK_PCT      = 0.0035   # 0.35%
MAX_WICK_PCT      = 0.0100   # 1.00%

# F5
SLOPE_LOOKBACK    = 8
MA_SLOPE_MIN_PCT  = 0.10     # hard reject below this

# F6
MA_ACCEL_BARS     = 4

# F7
ATR_PERIOD        = 14
ATR_MAX_PCT       = 0.0060   # 0.60%

# F8
H4_MA_PERIOD      = 44
H4_SLOPE_BARS     = 4

# F9
CONSEC_LOSS_PAUSE = 2
CONSEC_LOSS_MS    = 8 * 60 * 60 * 1000        # 8 hours

# Direction gate — LONGs disabled
ENABLE_LONG       = False
ENABLE_SHORT      = True

SYMBOL = 'BTCUSDT'

PERIODS = [
    {
        'label':    'Period 1 -- BTC/USDT  |  01 Oct 2025 -> 26 Feb 2026',
        'start_dt': datetime(2025, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
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
    """True = rising, False = falling, None = unavailable."""
    candles = fetch_h4_candles(symbol, ts_ms, limit=H4_MA_PERIOD + H4_SLOPE_BARS + 10)
    if candles is None:
        return None
    h4_closes = [float(c[4]) for c in candles]
    ma_now  = calculate_sma(h4_closes,                  H4_MA_PERIOD)
    ma_prev = calculate_sma(h4_closes[:-H4_SLOPE_BARS], H4_MA_PERIOD)
    if ma_now is None or ma_prev is None:
        return None
    return ma_now > ma_prev


def dist_in_zone(dist_pct_raw):
    """
    Returns True if distance falls in accepted zones:
      Zone A: 0.20–0.35%
      Zone B: 0.50–0.65%
    Rejects the 0.35–0.50% middle band.
    """
    return (
        (DIST_ZONE_A_MIN <= dist_pct_raw <= DIST_ZONE_A_MAX) or
        (DIST_ZONE_B_MIN <= dist_pct_raw <= DIST_ZONE_B_MAX)
    )

# ============================================================================
# STEP 1 — SETUP CANDLE CHECK
# ============================================================================

def check_setup_candle(closes, opens, highs, lows):
    """
    Returns ('SHORT', diagnostics_dict) or (None, None).
    LONGs disabled. F5 and F6 are hard rejects with no fallthrough.
    """
    min_len = MA_PERIOD + SLOPE_LOOKBACK + ATR_PERIOD + 5
    if len(closes) < min_len:
        return None, None

    c_close = closes[-1]
    c_open  = opens[-1]
    c_high  = highs[-1]
    c_low   = lows[-1]

    # Must be bearish for SHORT
    if c_close >= c_open:
        return None, None

    ma44 = calculate_sma(closes, MA_PERIOD)
    if ma44 is None:
        return None, None

    # ── F5: MA slope — HARD REJECT ───────────────────────────────────────────
    ma44_8ago = calculate_sma(closes[:-SLOPE_LOOKBACK], MA_PERIOD)
    if ma44_8ago is None:
        return None, None
    ma_slope_pct = (ma44 - ma44_8ago) / ma44 * 100   # negative = falling

    if abs(ma_slope_pct) < MA_SLOPE_MIN_PCT:
        return None, None   # F5 HARD REJECT — flat MA, no fallthrough

    # ── Monotonic slope: MA44 must fall every candle for SLOPE_LOOKBACK bars ─
    ma44_series = []
    for k in range(SLOPE_LOOKBACK, -1, -1):
        val = calculate_sma(closes[:-k] if k > 0 else closes, MA_PERIOD)
        if val is None:
            return None, None
        ma44_series.append(val)

    if not all(ma44_series[i] > ma44_series[i + 1] for i in range(len(ma44_series) - 1)):
        return None, None   # MA44 not continuously falling

    # ── F6: MA acceleration — strict sign check ───────────────────────────────
    ma44_4ago  = calculate_sma(closes[:-MA_ACCEL_BARS],       MA_PERIOD)
    ma44_8ago2 = calculate_sma(closes[:-MA_ACCEL_BARS * 2],   MA_PERIOD)
    if ma44_4ago is None or ma44_8ago2 is None:
        return None, None

    slope_recent = ma44 - ma44_4ago        # last 4 bars (must be negative)
    slope_prior  = ma44_4ago - ma44_8ago2  # prior 4 bars (must be negative)
    ma_accel_val = slope_recent - slope_prior

    # Strict: both slopes negative AND recent steeper (more negative) than prior
    if not (slope_recent < 0 and slope_prior < 0 and slope_recent < slope_prior):
        return None, None   # F6 HARD REJECT — not a steepening downtrend

    # ── Candle geometry ───────────────────────────────────────────────────────
    body_top    = max(c_open, c_close)
    body_bottom = min(c_open, c_close)
    candle_size = c_high - c_low
    body_size   = body_top - body_bottom
    wick_pct    = candle_size / c_high if c_high > 0 else 0
    body_ratio  = body_size / candle_size if candle_size > 0 else 0

    # F1 — body ratio
    if body_ratio < MIN_BODY_RATIO:
        return None, None

    # F4 — wick bounds
    if wick_pct < MIN_WICK_PCT or wick_pct > MAX_WICK_PCT:
        return None, None

    # F2/F3 — body strictly below MA44 + split distance zone
    if body_top >= ma44:
        return None, None
    dist_raw = ma44 - body_top   # absolute distance
    if not dist_in_zone(dist_raw / ma44):
        return None, None

    # All candle-level filters passed — return with diagnostics
    diag = {
        'ma_slope_8bar': ma_slope_pct,
        'ma_accel':      ma_accel_val,
        'slope_recent':  slope_recent,
        'slope_prior':   slope_prior,
    }
    return 'SHORT', diag

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

def scan_period(start_ts, end_ts):
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
    pending_diag      = None

    # F9 — per-side consecutive loss counter (SHORT only but keep structure)
    consec_loss       = {'LONG': 0, 'SHORT': 0}
    pause_until       = {'LONG': 0, 'SHORT': 0}

    h4_cache          = {}
    start_i           = MA_PERIOD + SLOPE_LOOKBACK + ATR_PERIOD + 5

    for i in range(start_i, len(all_candles) - 1):
        candle_ts = times_all[i]
        in_window = (start_ts <= candle_ts <= end_ts)

        # ── STEP 2: fire pending setup ────────────────────────────────────────
        if pending_direction is not None:
            entry = check_validation_candle(
                opens_all, closes_all, pending_direction, pending_setup_i
            )

            if entry is not None and in_window:
                side = pending_direction

                # F9 — compare against entry timestamp (fixed)
                if candle_ts < pause_until[side]:
                    pending_direction = None
                    pending_setup_i   = None
                    pending_diag      = None
                    continue

                if candle_ts - last_signal_ts >= COOLDOWN_MS:
                    sl = entry * (1 + SL_PERCENT / 100)   # SHORT SL above entry
                    tp = entry * (1 - TP_PERCENT / 100)   # SHORT TP below entry

                    si          = pending_setup_i
                    diag        = pending_diag or {}
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
                    dist_pct    = (ma44_val - body_top) / ma44_val * 100

                    atr_val     = calculate_atr(
                        highs_all[:si + 1], lows_all[:si + 1],
                        closes_all[:si + 1], ATR_PERIOD
                    )
                    atr_pct     = atr_val / closes_all[si] * 100 if atr_val else 0

                    # H4 direction at setup time (from cache)
                    h4_bucket   = (times_all[si] // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
                    h4_rising   = h4_cache.get(h4_bucket)
                    h4_dir_str  = ('FALLING' if h4_rising is False else
                                   'RISING'  if h4_rising is True  else 'N/A')

                    outcome = check_trade_outcome(candle_ts, entry, sl, tp, side)

                    signals.append({
                        'type':          side,
                        'setup_ts':      times_all[si],
                        'setup_time':    datetime.fromtimestamp(times_all[si] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                        'entry_ts':      candle_ts,
                        'entry_time':    datetime.fromtimestamp(candle_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                        'entry':         entry,
                        'sl':            sl,
                        'tp':            tp,
                        'ma44':          ma44_val,
                        # ── four audit fields ──────────────────────────────
                        'ma_slope_8bar': diag.get('ma_slope_8bar', 0.0),
                        'ma_accel':      diag.get('ma_accel', 0.0),
                        'h4_ma_dir':     h4_dir_str,
                        'atr_14_pct':    atr_pct,
                        # ── candle detail ──────────────────────────────────
                        'setup_open':    setup_open,
                        'setup_close':   setup_close,
                        'setup_high':    setup_high,
                        'setup_low':     setup_low,
                        'wick_pct':      wick_pct_s,
                        'body_ratio':    body_ratio,
                        'dist_pct':      dist_pct,
                        'outcome':       outcome,
                    })
                    last_signal_ts = candle_ts

                    # F9 — update counter; reset on WIN (fixed)
                    if outcome == 'LOSS':
                        consec_loss[side] += 1
                        if consec_loss[side] >= CONSEC_LOSS_PAUSE:
                            pause_until[side] = candle_ts + CONSEC_LOSS_MS
                            consec_loss[side] = 0   # reset after triggering pause
                    elif outcome == 'WIN':
                        consec_loss[side] = 0       # reset on win (fixed)

            pending_direction = None
            pending_setup_i   = None
            pending_diag      = None

        # ── STEP 1: check setup candle ────────────────────────────────────────
        if not in_window:
            continue

        direction, diag = check_setup_candle(
            closes_all[:i + 1], opens_all[:i + 1],
            highs_all[:i + 1],  lows_all[:i + 1]
        )
        if direction is None:
            continue

        # Direction gate
        if direction == 'LONG'  and not ENABLE_LONG:  continue
        if direction == 'SHORT' and not ENABLE_SHORT: continue

        # F7 — ATR hard check
        atr_now = calculate_atr(
            highs_all[:i + 1], lows_all[:i + 1],
            closes_all[:i + 1], ATR_PERIOD
        )
        if atr_now is not None:
            if (atr_now / closes_all[i] * 100) >= ATR_MAX_PCT * 100:
                continue   # F7 fail

        # F8 — 4H gate (cached per 4h bucket)
        h4_bucket = (candle_ts // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
        if h4_bucket not in h4_cache:
            h4_cache[h4_bucket] = get_h4_ma44_direction(SYMBOL, candle_ts)
        h4_rising = h4_cache[h4_bucket]

        if h4_rising is not None:
            if direction == 'LONG'  and not h4_rising: continue  # need rising 4H
            if direction == 'SHORT' and h4_rising:     continue  # need falling 4H

        pending_direction = direction
        pending_setup_i   = i
        pending_diag      = diag

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

def generate_txt(results, filename='btc_backtest_v2b_report.txt'):
    W   = 80
    gen = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    with open(filename, 'w', encoding='utf-8') as f:

        def p(line=''):
            print(line, file=f)

        def div(char='='):
            p(char * W)

        div('=')
        p('BTC/USDT -- BACKTEST REPORT  (Logic No. 2b Enhanced v3 -- SHORT ONLY)')
        p('15-minute candles  |  Binance  |  No RSI  |  No Crossovers')
        p(f'Generated : {gen}')
        p(f'SL: +{SL_PERCENT}%  |  TP: -{TP_PERCENT}%  |  R/R 1:3  |  Cooldown: 4h')
        p(f'Direction : SHORT ONLY  (LONGs disabled — insufficient edge)')
        p()
        p('FILTERS:')
        p(f'  F1  body_ratio    >= {MIN_BODY_RATIO:.2f}  (no doji/spinning top)')
        p(f'  F2a dist zone A   {DIST_ZONE_A_MIN*100:.2f}%–{DIST_ZONE_A_MAX*100:.2f}%  (close bounce)')
        p(f'  F2b dist zone B   {DIST_ZONE_B_MIN*100:.2f}%–{DIST_ZONE_B_MAX*100:.2f}%  (far bounce)')
        p(f'      [0.35–0.50% middle band REJECTED — 19% WR historically]')
        p(f'  F4  wick range    {MIN_WICK_PCT*100:.2f}%–{MAX_WICK_PCT*100:.2f}%')
        p(f'  F5  slope 8-bar   abs >= {MA_SLOPE_MIN_PCT:.2f}%  [HARD REJECT — no fallthrough]')
        p(f'  F6  ma_accel      slope_recent < slope_prior < 0  [STRICT SIGN — both negative]')
        p(f'  F7  ATR(14)       < {ATR_MAX_PCT*100:.2f}% of close')
        p(f'  F8  4H MA44       must be FALLING for SHORT')
        p(f'  F9  consec loss   {CONSEC_LOSS_PAUSE} losses → {CONSEC_LOSS_MS//3600000}h pause  [resets on WIN]')
        p()
        p('SIGNAL LOGIC (TWO-STEP):')
        p('  Step 1  bearish candle | MA44 falling 8 consecutive candles')
        p('          body strictly below MA44 | dist in zone A or B')
        p('          F5 hard reject | F6 strict negative accel | F7 ATR | F8 4H falling')
        p('  Step 2  next candle open must be below MA44 → entry')
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

            # Zone breakdown
            zone_a = [s for s in signals if DIST_ZONE_A_MIN*100 <= s['dist_pct'] <= DIST_ZONE_A_MAX*100]
            zone_b = [s for s in signals if DIST_ZONE_B_MIN*100 <= s['dist_pct'] <= DIST_ZONE_B_MAX*100]
            za_w   = sum(1 for s in zone_a if s['outcome'] == 'WIN')
            za_l   = sum(1 for s in zone_a if s['outcome'] == 'LOSS')
            zb_w   = sum(1 for s in zone_b if s['outcome'] == 'WIN')
            zb_l   = sum(1 for s in zone_b if s['outcome'] == 'LOSS')
            za_wr  = f"{za_w/(za_w+za_l)*100:.1f}%" if (za_w+za_l) > 0 else 'n/a'
            zb_wr  = f"{zb_w/(zb_w+zb_l)*100:.1f}%" if (zb_w+zb_l) > 0 else 'n/a'

            p('  SUMMARY')
            div('-')
            p(f'  Total signals   : {total}  (Short: {shorts})')
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
            p()
            p('  ZONE BREAKDOWN')
            p(f'  Zone A (0.20–0.35%) : {len(zone_a)} signals  W:{za_w} L:{za_l}  WR:{za_wr}')
            p(f'  Zone B (0.50–0.65%) : {len(zone_b)} signals  W:{zb_w} L:{zb_l}  WR:{zb_wr}')
            div('-')
            p()

            p('  SIGNALS')
            div('-')
            p()

            for idx, s in enumerate(sorted(signals, key=lambda x: x['entry_ts']), 1):
                ol    = {'WIN': '[WIN ]', 'LOSS': '[LOSS]',
                         'ONGOING': '[OPEN]', 'UNKNOWN': '[????]'}.get(s['outcome'], '[????]')
                zone  = ('A' if DIST_ZONE_A_MIN*100 <= s['dist_pct'] <= DIST_ZONE_A_MAX*100
                         else 'B' if DIST_ZONE_B_MIN*100 <= s['dist_pct'] <= DIST_ZONE_B_MAX*100
                         else '?')
                accel_sign = '↓steep' if s['ma_accel'] < 0 else '↑flat'

                p(f'  Signal #{idx:<3}  {ol}  SHORT   Entry: {s["entry_time"]}')
                p(f'  Setup         : {s["setup_time"]}  '
                  f'open={s["setup_open"]:.2f}  close={s["setup_close"]:.2f}  '
                  f'wick={s["wick_pct"]:.2f}%  body={s["body_ratio"]*100:.1f}%  '
                  f'dist={s["dist_pct"]:.3f}%  zone={zone}')
                p(f'  MA44          : {s["ma44"]:.2f}  '
                  f'slope_8bar={s["ma_slope_8bar"]:+.3f}%  '
                  f'ma_accel={s["ma_accel"]:+.5f} ({accel_sign})  '
                  f'h4_ma_dir={s["h4_ma_dir"]}  '
                  f'atr_14={s["atr_14_pct"]:.3f}%')
                p(f'  Entry         : ${s["entry"]:.2f}')
                p(f'  Stop Loss     : ${s["sl"]:.2f}  (+{SL_PERCENT}%)')
                p(f'  Take Profit   : ${s["tp"]:.2f}  (-{TP_PERCENT}%)')
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
        p('  F5 HARD REJECT  : abs(slope) < 0.10% kills the candle immediately,')
        p('                    no other checks run after this failure')
        p('  F6 STRICT SIGN  : slope_recent < slope_prior < 0 required for SHORT')
        p('                    both halves of 8-bar window must be negative AND')
        p('                    recent must be steeper (more negative) than prior')
        p('  F9 FIXED        : counter resets on WIN; pause compared vs entry_ts')
        p('  DIST ZONES      : 0.20–0.35% (zone A) and 0.50–0.65% (zone B)')
        p('                    0.35–0.50% middle band excluded (historically 19% WR)')
        p('  LONGs DISABLED  : 1W/8T (12.5%) over 5 months — no statistical edge')
        div('=')

    return filename

# ============================================================================
# MAIN
# ============================================================================

def main():
    t = sys.__stdout__
    t.write('\n' + '=' * 60 + '\n')
    t.write('BTC/USDT BACKTEST -- Logic No. 2b Enhanced v3\n')
    t.write('SHORT ONLY  |  Oct 2025 – Feb 2026\n')
    t.write('=' * 60 + '\n\n')
    t.write(f'  Direction      : SHORT only (LONGs off)\n')
    t.write(f'  SL / TP        : {SL_PERCENT}% / {TP_PERCENT}%\n')
    t.write(f'  F1  body ratio : >= {MIN_BODY_RATIO:.0%}\n')
    t.write(f'  F2  dist zones : {DIST_ZONE_A_MIN*100:.2f}–{DIST_ZONE_A_MAX*100:.2f}%  |  {DIST_ZONE_B_MIN*100:.2f}–{DIST_ZONE_B_MAX*100:.2f}%\n')
    t.write(f'  F4  wick range : {MIN_WICK_PCT*100:.2f}%–{MAX_WICK_PCT*100:.2f}%\n')
    t.write(f'  F5  slope      : abs >= {MA_SLOPE_MIN_PCT:.2f}%  HARD REJECT\n')
    t.write(f'  F6  accel      : slope_recent < slope_prior < 0  STRICT SIGN\n')
    t.write(f'  F7  ATR(14)    : < {ATR_MAX_PCT*100:.2f}%\n')
    t.write(f'  F8  4H gate    : FALLING required\n')
    t.write(f'  F9  circuit    : {CONSEC_LOSS_PAUSE} losses → {CONSEC_LOSS_MS//3600000}h pause  (resets on WIN)\n')
    t.write(f'  Cooldown       : 4h\n\n')

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

    # ── OHLC CSV export ───────────────────────────────────────────────────────
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

    # ── Report ────────────────────────────────────────────────────────────────
    t.write('\nWriting report...\n')
    fname = generate_txt(results)
    t.write(f'Done -> {fname}\n\n')


if __name__ == '__main__':
    main()