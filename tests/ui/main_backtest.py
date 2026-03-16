"""
main_backtest.py
================
STEP 2 OF 4  —  MA44 Bounce Strategy Backtest  |  SHORT ONLY
                Multi-symbol  |  Oct 2025 – Feb 2026
                Logic No. 2b Enhanced v3

STRATEGY:
  Two-step signal on 15m candles.
  Step 1 — Setup candle: bearish, MA44 falling 8 bars consecutively,
            body strictly below MA44, all filters F1–F9 pass.
  Step 2 — Validation: next candle opens below MA44 → entry at open.

FILTERS:
  F1  body_ratio      >= 0.60
  F2a dist zone A     0.20%–0.35%  (close bounce)
  F2b dist zone B     0.50%–0.65%  (far bounce)
      [0.35–0.50% middle band REJECTED — 19% WR historically]
  F4  wick range      0.35%–1.00%
  F5  slope 8-bar     abs >= 0.10%  HARD REJECT
  F6  ma_accel        slope_recent < slope_prior < 0  STRICT SIGN
  F7  ATR(14)         < 0.60% of close
  F8  4H MA44         must be FALLING for SHORT
  F9  consec loss     2 losses → 8h pause (resets on WIN)

SL: 2.0%  TP: 6.0%  Cooldown: 4h  Time limit: NONE
LONGs: DISABLED (1W/8T over 5 months — no edge)

OUTPUT: multi_backtest_report.txt
"""

import requests
from datetime import datetime, timezone
import sys
import time

# ============================================================================
# PARAMETERS
# ============================================================================

MA_PERIOD         = 44
SL_PERCENT        = 2.0
TP_PERCENT        = 6.0
COOLDOWN_MS       = 4 * 60 * 60 * 1000

MIN_BODY_RATIO    = 0.60

DIST_ZONE_A_MIN   = 0.0020   # 0.20%
DIST_ZONE_A_MAX   = 0.0035   # 0.35%
DIST_ZONE_B_MIN   = 0.0050   # 0.50%
DIST_ZONE_B_MAX   = 0.0065   # 0.65%

MIN_WICK_PCT      = 0.0035   # 0.35%
MAX_WICK_PCT      = 0.0100   # 1.00%

SLOPE_LOOKBACK    = 8
MA_SLOPE_MIN_PCT  = 0.10

MA_ACCEL_BARS     = 4

ATR_PERIOD        = 14
ATR_MAX_PCT       = 0.0060   # 0.60%

H4_MA_PERIOD      = 44
H4_SLOPE_BARS     = 4

CONSEC_LOSS_PAUSE = 2
CONSEC_LOSS_MS    = 8 * 60 * 60 * 1000

ENABLE_LONG       = False
ENABLE_SHORT      = True

# ── Backtest period ───────────────────────────────────────────────────────
PERIOD_START = datetime(2025, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
PERIOD_END   = datetime(2026, 2, 28, 23, 59, 59, tzinfo=timezone.utc)

# ── Symbol list (update after running filter_by_correlation.py) ───────────
# This list is pre-populated with all coins confirmed on Binance.
# Re-run filter_by_correlation.py to refresh if needed.

SYMBOLS = [
    '1INCHUSDT',
    '2ZUSDT',
    'AAVEUSDT',
    'ADAUSDT',
    'ALGOUSDT',
    'AMPUSDT',
    'APTUSDT',
    'ARBUSDT',
    'ASTERUSDT',
    'ATOMUSDT',
    'AVAXUSDT',
    'AXSUSDT',
    'BARDUSDT',
    'BATUSDT',
    'BCHUSDT',
    'BNBUSDT',
    'BONKUSDT',
    'BTCUSDT',
    'BTTUSDT',
    'CAKEUSDT',
    'CHZUSDT',
    'COWUSDT',
    'CRVUSDT',
    'DASHUSDT',
    'DCRUSDT',
    'DOGEUSDT',
    'DOTUSDT',
    'EGLDUSDT',
    'EIGENUSDT',
    'ENAUSDT',
    'ENSUSDT',
    'ETCUSDT',
    'ETHUSDT',
    'ETHFIUSDT',
    'FETUSDT',
    'FILUSDT',
    'GALAUSDT',
    'GLMUSDT',
    'GNOUSDT',
    'GRTUSDT',
    'HBARUSDT',
    'ICPUSDT',
    'IMXUSDT',
    'INJUSDT',
    'IOTAUSDT',
    'JASMYUSDT',
    'JTOUSDT',
    'JUPUSDT',
    'LDOUSDT',
    'LINKUSDT',
    'LPTUSDT',
    'LTCUSDT',
    'LUNCUSDT',
    'MANAUSDT',
    'NEARUSDT',
    'NEOUSDT',
    'NEXOUSDT',
    'ONDOUSDT',
    'OPUSDT',
    'PENDLEUSDT',
    'PENGUUSDT',
    'PEPEUSDT',
    'POLUSDT',
    'PUMPUSDT',
    'PYTHUSDT',
    'QNTUSDT',
    'RUNEUSDT',
    'RAYUSDT',
    'RENDERUSDT',
    'SUSDT',
    'SANDUSDT',
    'SEIUSDT',
    'SFPUSDT',
    'SHIBUSDT',
    'SKYUSDT',
    'SOLUSDT',
    'STRKUSDT',
    'STXUSDT',
    'SUIUSDT',
    'SYRUPUSDT',
    'TAOUSDT',
    'THETAUSDT',
    'TIAUSDT',
    'TRUMPUSDT',
    'TWTUSDT',
    'UNIUSDT',
    'VETUSDT',
    'VIRTUALUSDT',
    'WALUSDT',
    'WIFUSDT',
    'WLDUSDT',
    'XMRUSDT',
    'XPLUSDT',
    'XRPUSDT',
    'XTZUSDT',
    'ZECUSDT',
    'ZKUSDT',
    'ZROUSDT',
]

OUTPUT_FILE = 'multi_backtest_report.txt'

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
    return (
        (DIST_ZONE_A_MIN <= dist_pct_raw <= DIST_ZONE_A_MAX) or
        (DIST_ZONE_B_MIN <= dist_pct_raw <= DIST_ZONE_B_MAX)
    )

# ============================================================================
# STEP 1 — SETUP CANDLE CHECK
# ============================================================================

def check_setup_candle(closes, opens, highs, lows):
    """Returns ('SHORT', diag) or (None, None)."""
    min_len = MA_PERIOD + SLOPE_LOOKBACK + ATR_PERIOD + 5
    if len(closes) < min_len:
        return None, None

    c_close = closes[-1]
    c_open  = opens[-1]
    c_high  = highs[-1]
    c_low   = lows[-1]

    if c_close >= c_open:
        return None, None   # must be bearish

    ma44 = calculate_sma(closes, MA_PERIOD)
    if ma44 is None:
        return None, None

    # ── F5: slope magnitude — HARD REJECT ────────────────────────────────
    ma44_8ago = calculate_sma(closes[:-SLOPE_LOOKBACK], MA_PERIOD)
    if ma44_8ago is None:
        return None, None
    ma_slope_pct = (ma44 - ma44_8ago) / ma44 * 100

    if abs(ma_slope_pct) < MA_SLOPE_MIN_PCT:
        return None, None   # F5 HARD REJECT

    # ── Monotonic: MA44 must fall every candle for SLOPE_LOOKBACK bars ───
    ma44_series = []
    for k in range(SLOPE_LOOKBACK, -1, -1):
        val = calculate_sma(closes[:-k] if k > 0 else closes, MA_PERIOD)
        if val is None:
            return None, None
        ma44_series.append(val)

    if not all(ma44_series[i] > ma44_series[i + 1] for i in range(len(ma44_series) - 1)):
        return None, None

    # ── F6: acceleration — strict sign ───────────────────────────────────
    ma44_4ago  = calculate_sma(closes[:-MA_ACCEL_BARS],       MA_PERIOD)
    ma44_8ago2 = calculate_sma(closes[:-MA_ACCEL_BARS * 2],   MA_PERIOD)
    if ma44_4ago is None or ma44_8ago2 is None:
        return None, None

    slope_recent = ma44 - ma44_4ago        # last 4 bars
    slope_prior  = ma44_4ago - ma44_8ago2  # prior 4 bars
    ma_accel_val = slope_recent - slope_prior

    # Both must be negative AND recent steeper (more negative) than prior
    if not (slope_recent < 0 and slope_prior < 0 and slope_recent < slope_prior):
        return None, None   # F6 HARD REJECT

    # ── Candle geometry ───────────────────────────────────────────────────
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

    # F2/F3 — body strictly below MA44 + distance zone
    if body_top >= ma44:
        return None, None
    dist_raw = ma44 - body_top
    if not dist_in_zone(dist_raw / ma44):
        return None, None

    diag = {
        'ma_slope_8bar': ma_slope_pct,
        'ma_accel':      ma_accel_val,
        'slope_recent':  slope_recent,
        'slope_prior':   slope_prior,
    }
    return 'SHORT', diag

# ============================================================================
# STEP 2 — VALIDATION CANDLE
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
# OUTCOME CHECKER — no time limit, scan until SL/TP or now
# ============================================================================

def check_trade_outcome(symbol, signal_ts_ms, entry, sl, tp, stype):
    """
    Fetches 15m candles from entry forward in batches of 1000.
    Scans until SL or TP is hit. No time cap.
    Returns ONGOING if neither hit by current time.
    """
    now_ms        = int(time.time() * 1000)
    current_start = signal_ts_ms
    first_candle  = True

    while current_start < now_ms:
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    'symbol':    symbol,
                    'interval':  '15m',
                    'startTime': current_start,
                    'endTime':   now_ms,
                    'limit':     1000,
                },
                timeout=15
            )
            if resp.status_code != 200:
                return 'UNKNOWN'
            candles = resp.json()
            if not isinstance(candles, list) or len(candles) == 0:
                break
        except Exception:
            return 'UNKNOWN'

        for idx, c in enumerate(candles):
            h = float(c[2])
            l = float(c[3])

            if first_candle and idx == 0:
                # Entry is at open — ignore wicks before entry on first candle
                if stype == 'LONG':
                    l = min(float(c[1]), float(c[4]))
                else:
                    h = max(float(c[1]), float(c[4]))
                first_candle = False

            if stype == 'LONG':
                if l <= sl: return 'LOSS'
                if h >= tp: return 'WIN'
            else:
                if h >= sl: return 'LOSS'
                if l <= tp: return 'WIN'

        current_start = int(candles[-1][0]) + 1
        if len(candles) < 1000:
            break

    return 'ONGOING'

# ============================================================================
# SCANNER — single symbol
# ============================================================================

def scan_symbol(symbol, start_ts, end_ts):
    warmup_ms     = (MA_PERIOD + SLOPE_LOOKBACK + ATR_PERIOD + 10) * 15 * 60 * 1000
    fetch_start   = start_ts - warmup_ms
    all_candles   = []
    current_start = fetch_start

    while current_start < end_ts:
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={'symbol': symbol, 'interval': '15m',
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
        return []   # not enough history — return empty, not None

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
    consec_loss       = {'LONG': 0, 'SHORT': 0}
    pause_until       = {'LONG': 0, 'SHORT': 0}
    h4_cache          = {}
    start_i           = MA_PERIOD + SLOPE_LOOKBACK + ATR_PERIOD + 5

    for i in range(start_i, len(all_candles) - 1):
        candle_ts = times_all[i]
        in_window = (start_ts <= candle_ts <= end_ts)

        # ── STEP 2: fire pending setup ────────────────────────────────────
        if pending_direction is not None:
            entry_price = check_validation_candle(
                opens_all, closes_all, pending_direction, pending_setup_i
            )

            if entry_price is not None and in_window:
                side = pending_direction

                if candle_ts < pause_until[side]:
                    pending_direction = None
                    pending_setup_i   = None
                    pending_diag      = None
                    continue

                if candle_ts - last_signal_ts >= COOLDOWN_MS:
                    sl = entry_price * (1 + SL_PERCENT / 100)   # SHORT SL above
                    tp = entry_price * (1 - TP_PERCENT / 100)   # SHORT TP below

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
                    dist_pct    = (ma44_val - body_top) / ma44_val * 100 if ma44_val else 0

                    atr_val    = calculate_atr(
                        highs_all[:si + 1], lows_all[:si + 1],
                        closes_all[:si + 1], ATR_PERIOD
                    )
                    atr_pct    = atr_val / closes_all[si] * 100 if atr_val else 0

                    h4_bucket  = (times_all[si] // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
                    h4_rising  = h4_cache.get(h4_bucket)
                    h4_dir_str = ('FALLING' if h4_rising is False else
                                  'RISING'  if h4_rising is True  else 'N/A')

                    outcome = check_trade_outcome(symbol, candle_ts, entry_price, sl, tp, side)

                    signals.append({
                        'symbol':        symbol,
                        'type':          side,
                        'setup_ts':      times_all[si],
                        'setup_time':    datetime.fromtimestamp(times_all[si] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                        'entry_ts':      candle_ts,
                        'entry_time':    datetime.fromtimestamp(candle_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                        'entry':         entry_price,
                        'sl':            sl,
                        'tp':            tp,
                        'ma44':          ma44_val,
                        'ma_slope_8bar': diag.get('ma_slope_8bar', 0.0),
                        'ma_accel':      diag.get('ma_accel', 0.0),
                        'h4_ma_dir':     h4_dir_str,
                        'atr_14_pct':    atr_pct,
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

                    if outcome == 'LOSS':
                        consec_loss[side] += 1
                        if consec_loss[side] >= CONSEC_LOSS_PAUSE:
                            pause_until[side] = candle_ts + CONSEC_LOSS_MS
                            consec_loss[side] = 0
                    elif outcome == 'WIN':
                        consec_loss[side] = 0

            pending_direction = None
            pending_setup_i   = None
            pending_diag      = None

        # ── STEP 1: check setup candle ────────────────────────────────────
        if not in_window:
            continue

        direction, diag = check_setup_candle(
            closes_all[:i + 1], opens_all[:i + 1],
            highs_all[:i + 1],  lows_all[:i + 1]
        )
        if direction is None:
            continue
        if direction == 'LONG'  and not ENABLE_LONG:  continue
        if direction == 'SHORT' and not ENABLE_SHORT: continue

        # F7 — ATR
        atr_now = calculate_atr(
            highs_all[:i + 1], lows_all[:i + 1],
            closes_all[:i + 1], ATR_PERIOD
        )
        if atr_now is not None:
            if (atr_now / closes_all[i] * 100) >= ATR_MAX_PCT * 100:
                continue

        # F8 — 4H gate (cached)
        h4_bucket = (candle_ts // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
        if h4_bucket not in h4_cache:
            h4_cache[h4_bucket] = get_h4_ma44_direction(symbol, candle_ts)
        h4_rising = h4_cache[h4_bucket]
        if h4_rising is not None:
            if direction == 'LONG'  and not h4_rising: continue
            if direction == 'SHORT' and h4_rising:     continue

        pending_direction = direction
        pending_setup_i   = i
        pending_diag      = diag

    return signals

# ============================================================================
# REPORT WRITER
# ============================================================================

def generate_report(all_symbol_results, filename=OUTPUT_FILE):
    gen = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    W = 80

    # Flatten all signals
    all_signals = []
    for sym, signals in all_symbol_results:
        all_signals.extend(signals)

    total_w = sum(1 for s in all_signals if s['outcome'] == 'WIN')
    total_l = sum(1 for s in all_signals if s['outcome'] == 'LOSS')
    total_o = sum(1 for s in all_signals if s['outcome'] == 'ONGOING')
    total_c = total_w + total_l
    total_wr = total_w / total_c * 100 if total_c > 0 else 0
    total_pnl = (total_w * TP_PERCENT) - (total_l * SL_PERCENT)

    with open(filename, 'w', encoding='utf-8') as f:

        def p(line=''):
            print(line, file=f)

        def div(char='='):
            p(char * W)

        div('=')
        p('MULTI-SYMBOL BACKTEST  —  MA44 Bounce  |  SHORT ONLY  |  Logic v3')
        p('15-minute candles  |  Binance  |  No RSI  |  No Crossovers')
        p(f'Generated  : {gen}')
        p(f'Period     : {PERIOD_START.strftime("%d %b %Y")} → {PERIOD_END.strftime("%d %b %Y")}')
        p(f'Symbols    : {len(all_symbol_results)}')
        p(f'SL: +{SL_PERCENT}%  |  TP: -{TP_PERCENT}%  |  R/R 1:3  |  Cooldown: 4h')
        p(f'Time limit : NONE — trades run until SL or TP hit')
        p()
        p('FILTERS:')
        p(f'  F1  body_ratio    >= {MIN_BODY_RATIO:.2f}')
        p(f'  F2a dist zone A   {DIST_ZONE_A_MIN*100:.2f}%–{DIST_ZONE_A_MAX*100:.2f}%  (close bounce)')
        p(f'  F2b dist zone B   {DIST_ZONE_B_MIN*100:.2f}%–{DIST_ZONE_B_MAX*100:.2f}%  (far bounce)')
        p(f'      [0.35–0.50% middle band REJECTED]')
        p(f'  F4  wick range    {MIN_WICK_PCT*100:.2f}%–{MAX_WICK_PCT*100:.2f}%')
        p(f'  F5  slope 8-bar   abs >= {MA_SLOPE_MIN_PCT:.2f}%  HARD REJECT')
        p(f'  F6  ma_accel      slope_recent < slope_prior < 0  STRICT SIGN')
        p(f'  F7  ATR(14)       < {ATR_MAX_PCT*100:.2f}% of close')
        p(f'  F8  4H MA44       must be FALLING for SHORT')
        p(f'  F9  consec loss   {CONSEC_LOSS_PAUSE} losses → {CONSEC_LOSS_MS//3600000}h pause  (resets on WIN)')
        div('=')
        p()

        # ── Overall summary ───────────────────────────────────────────────
        div('*')
        p('  OVERALL SUMMARY')
        div('*')
        p(f'  Total signals  : {len(all_signals)}')
        p(f'  Wins           : {total_w}')
        p(f'  Losses         : {total_l}')
        p(f'  Ongoing        : {total_o}')
        p(f'  Win rate       : {total_wr:.1f}%  ({total_w}/{total_c} closed)')
        p(f'  Total PnL      : {total_pnl:+.2f}%  (equal-size, closed trades only)')
        div('*')
        p()

        # ── Per-symbol summary table ──────────────────────────────────────
        p(f'  {"Symbol":<14}  {"Sig":>4}  {"W":>4}  {"L":>4}  {"Open":>4}  {"WR%":>6}  {"PnL%":>8}')
        div('-')
        for sym, signals in sorted(all_symbol_results, key=lambda x: x[0]):
            w  = sum(1 for s in signals if s['outcome'] == 'WIN')
            l  = sum(1 for s in signals if s['outcome'] == 'LOSS')
            o  = sum(1 for s in signals if s['outcome'] == 'ONGOING')
            c  = w + l
            wr = f'{w/c*100:.1f}' if c > 0 else 'n/a'
            pnl = f'{(w*TP_PERCENT)-(l*SL_PERCENT):+.2f}' if c > 0 else 'n/a'
            p(f'  {sym:<14}  {len(signals):>4}  {w:>4}  {l:>4}  {o:>4}  {wr:>6}  {pnl:>8}')
        div('-')
        p()

        # ── Per-symbol detail ─────────────────────────────────────────────
        for sym, signals in sorted(all_symbol_results, key=lambda x: x[0]):
            div('#')
            p(f'  {sym}  —  {len(signals)} signals')
            div('#')
            p()

            if not signals:
                p('  No signals.')
                p()
                continue

            w  = sum(1 for s in signals if s['outcome'] == 'WIN')
            l  = sum(1 for s in signals if s['outcome'] == 'LOSS')
            o  = sum(1 for s in signals if s['outcome'] == 'ONGOING')
            c  = w + l
            wr = w / c * 100 if c > 0 else 0
            pnl = (w * TP_PERCENT) - (l * SL_PERCENT)
            p(f'  Win rate : {wr:.1f}%  ({w}/{c} closed)  PnL: {pnl:+.2f}%  Ongoing: {o}')
            p()

            for idx, s in enumerate(sorted(signals, key=lambda x: x['entry_ts']), 1):
                ol   = {'WIN': '[WIN ]', 'LOSS': '[LOSS]',
                        'ONGOING': '[OPEN]', 'UNKNOWN': '[????]'}.get(s['outcome'], '[????]')
                zone = ('A' if DIST_ZONE_A_MIN*100 <= s['dist_pct'] <= DIST_ZONE_A_MAX*100
                        else 'B' if DIST_ZONE_B_MIN*100 <= s['dist_pct'] <= DIST_ZONE_B_MAX*100
                        else '?')

                p(f'  Signal #{idx:<3}  {ol}  SHORT   Entry: {s["entry_time"]}')
                p(f'  Setup  : {s["setup_time"]}  '
                  f'open={s["setup_open"]:.4f}  close={s["setup_close"]:.4f}  '
                  f'wick={s["wick_pct"]:.2f}%  body={s["body_ratio"]*100:.1f}%  '
                  f'dist={s["dist_pct"]:.3f}%  zone={zone}')
                p(f'  MA44   : {s["ma44"]:.4f}  '
                  f'slope_8bar={s["ma_slope_8bar"]:+.3f}%  '
                  f'ma_accel={s["ma_accel"]:+.6f}  '
                  f'h4={s["h4_ma_dir"]}  '
                  f'atr={s["atr_14_pct"]:.3f}%')
                p(f'  Entry  : {s["entry"]:.4f}  '
                  f'SL={s["sl"]:.4f} (+{SL_PERCENT}%)  '
                  f'TP={s["tp"]:.4f} (-{TP_PERCENT}%)')
                p()

            div('-')
            p()

        div('=')
        p('METHODOLOGY')
        div('=')
        p('  WIN     : TP hit before SL — no time limit')
        p('  LOSS    : SL hit before TP — no time limit')
        p('  ONGOING : Trade still open at report generation time')
        p('  UNKNOWN : Data fetch error')
        p()
        p('  F5 HARD REJECT : abs(slope) < 0.10% — immediate discard')
        p('  F6 STRICT SIGN : slope_recent < slope_prior < 0 required')
        p('  F9 FIXED       : counter resets on WIN, pause vs entry_ts')
        p('  DIST ZONES     : 0.20–0.35% (A) and 0.50–0.65% (B)')
        p('  LONGs DISABLED : 1W/8T over 5 months — no edge')
        div('=')

    return filename

# ============================================================================
# MAIN
# ============================================================================

def main():
    t = sys.stdout
    t.write('\n' + '=' * 60 + '\n')
    t.write('MULTI-SYMBOL BACKTEST — Logic No. 2b Enhanced v3\n')
    t.write(f'SHORT ONLY  |  {PERIOD_START.strftime("%b %Y")} – {PERIOD_END.strftime("%b %Y")}\n')
    t.write('=' * 60 + '\n\n')
    t.write(f'  Symbols    : {len(SYMBOLS)}\n')
    t.write(f'  SL / TP    : {SL_PERCENT}% / {TP_PERCENT}%\n')
    t.write(f'  Time limit : NONE\n\n')

    start_ts = int(PERIOD_START.timestamp() * 1000)
    end_ts   = int(PERIOD_END.timestamp()   * 1000)

    all_results = []
    total_signals = 0

    for idx, symbol in enumerate(SYMBOLS, 1):
        t.write(f'  [{idx:>3}/{len(SYMBOLS)}]  {symbol:<16}  scanning... ')
        t.flush()

        signals = scan_symbol(symbol, start_ts, end_ts)

        if signals is None:
            t.write('ERROR (fetch failed)\n')
            all_results.append((symbol, []))
            continue

        w = sum(1 for s in signals if s['outcome'] == 'WIN')
        l = sum(1 for s in signals if s['outcome'] == 'LOSS')
        c = w + l
        wr = f'{w/c*100:.1f}%' if c > 0 else 'n/a'
        t.write(f'{len(signals):>3} signals  [W:{w} L:{l} WR:{wr}]\n')

        all_results.append((symbol, signals))
        total_signals += len(signals)
        time.sleep(0.1)

    t.write(f'\n  Total signals found: {total_signals}\n')
    t.write('\nWriting report...\n')
    fname = generate_report(all_results)
    t.write(f'Done → {fname}\n\n')
    t.write('Now run:  python parse_results.py\n\n')


if __name__ == '__main__':
    main()