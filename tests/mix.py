"""
COMBINED DUAL-STRATEGY BACKTEST
================================
Binance  |  15-minute candles  |  01 Sep 2025 → 28 Feb 2026
87 symbols from Crypto_universe_copy_2026-03-16.csv

STRATEGY 1 — EMA 9/26 Cross + 6-Filter Suite
  Both directions (LONG + SHORT)
  F1  EMA9 crosses EMA26
  F2  Candle confirm (dir + close vs EMA9/EMA26)
  F3  Close on correct side of EMA200
  F4  ADX(14) > 25  (Wilder smoothing)
  F5  DI direction aligned
  F6  MACD(12,26,9) momentum aligned
  Entry: close of crossover candle N or N+1
  SL: 0.5%  |  TP: 1.5%  |  No time limit
  Concurrent trade blocks new signals (per symbol)

STRATEGY 2 — MA44 Bounce  (SHORT ONLY)
  Two-step signal on 15m candles
  Step 1 — Setup candle: bearish, MA44 falling 8 bars, body below MA44, F1–F9 pass
  Step 2 — Validation: next candle opens below MA44 → entry at open
  F1  body_ratio >= 0.60
  F2a dist zone A  0.20–0.35%
  F2b dist zone B  0.50–0.65%  [0.35–0.50% middle band REJECTED]
  F4  wick range   0.35–1.00%
  F5  slope 8-bar  abs >= 0.10%  HARD REJECT
  F6  ma_accel     slope_recent < slope_prior < 0  STRICT SIGN
  F7  ATR(14)      < 0.60% of close
  F8  4H MA44      must be FALLING
  F9  consec loss  2 losses → 8h pause (resets on WIN)
  SL: 2.0%  |  TP: 6.0%  |  Cooldown: 4h  |  No time limit

Output: combined_backtest_report.txt
"""

import requests
from datetime import datetime, timezone
import sys
import time

# ============================================================================
# SHARED PARAMETERS
# ============================================================================

INTERVAL    = '15m'
WARMUP_BARS = 250

PERIOD = {
    'label':    '01 Sep 2025 -> 28 Feb 2026',
    'start_dt': datetime(2025, 9,  1,  0,  0,  0, tzinfo=timezone.utc),
    'end_dt':   datetime(2026, 2, 28, 23, 59, 59, tzinfo=timezone.utc),
}

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "TRXUSDT", "DOGEUSDT", "ADAUSDT", "HYPEUSDT", "BCHUSDT",
    "LINKUSDT", "XMRUSDT", "XLMUSDT", "AVAXUSDT", "LTCUSDT",
    "HBARUSDT", "SUIUSDT", "ZECUSDT", "SHIBUSDT", "TONUSDT",
    "CROUSDT", "TAOUSDT", "DOTUSDT", "MNTUSDT", "UNIUSDT",
    "AAVEUSDT", "ASTERUSDT", "NEARUSDT", "PEPEUSDT", "SKYUSDT",
    "ICPUSDT", "ETCUSDT", "ONDOUSDT", "MKRUSDT", "WLDUSDT",
    "POLUSDT", "ENAUSDT", "RENDERUSDT", "ATOMUSDT", "TRUMPUSDT",
    "KASUSDT", "ALGOUSDT", "QNTUSDT", "APTUSDT", "FILUSDT",
    "PUMPUSDT", "ZROUSDT", "VETUSDT", "ARBUSDT", "NEXOUSDT",
    "JUPUSDT", "BONKUSDT", "PENGUUSDT", "CAKEUSDT", "VIRTUALUSDT",
    "FETUSDT", "DCRUSDT", "STXUSDT", "SEIUSDT", "DASHUSDT",
    "ETHFIUSDT", "XTZUSDT", "CHZUSDT", "GNOUSDT", "CRVUSDT",
    "BTTUSDT", "IMXUSDT", "TIAUSDT", "INJUSDT", "SYRUPUSDT",
    "FLOKIUSDT", "2ZUSDT", "JASMYUSDT", "PYTHUSDT", "GRTUSDT",
    "IOTAUSDT", "OPUSDT", "LDOUSDT", "SANDUSDT", "ENSUSDT",
    "BARDUSDT", "LUNCUSDT", "STRKUSDT", "TWTUSDT", "RUNEUSDT",
    "SUIUSDT",
]
# Deduplicate while preserving order
_seen = set(); _deduped = []
for _s in SYMBOLS:
    if _s not in _seen:
        _seen.add(_s); _deduped.append(_s)
SYMBOLS = _deduped

# ── Strategy 1 parameters ────────────────────────────────────────────────────
S1_EMA_FAST   = 9
S1_EMA_SLOW   = 26
S1_EMA_TREND  = 200
S1_MACD_FAST  = 12
S1_MACD_SLOW  = 26
S1_MACD_SIG   = 9
S1_ADX_PERIOD = 14
S1_SL         = 0.5
S1_TP         = 1.5

# ── Strategy 2 parameters ────────────────────────────────────────────────────
S2_MA_PERIOD       = 44
S2_SL              = 2.0
S2_TP              = 6.0
S2_COOLDOWN_MS     = 4 * 60 * 60 * 1000
S2_MIN_BODY_RATIO  = 0.60
S2_DIST_A_MIN      = 0.0020
S2_DIST_A_MAX      = 0.0035
S2_DIST_B_MIN      = 0.0050
S2_DIST_B_MAX      = 0.0065
S2_MIN_WICK_PCT    = 0.0035
S2_MAX_WICK_PCT    = 0.0100
S2_SLOPE_LB        = 8
S2_MA_SLOPE_MIN    = 0.10
S2_ACCEL_BARS      = 4
S2_ATR_PERIOD      = 14
S2_ATR_MAX_PCT     = 0.0060
S2_H4_MA_PERIOD    = 44
S2_H4_SLOPE_BARS   = 4
S2_CONSEC_LOSS_MAX = 2
S2_CONSEC_LOSS_MS  = 8 * 60 * 60 * 1000

# ============================================================================
# SHARED INDICATOR HELPERS
# ============================================================================

def calc_ema_series(closes, period):
    n = len(closes)
    result = [None] * n
    if n < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = sum(closes[:period]) / period
    for i in range(period, n):
        result[i] = closes[i] * k + result[i - 1] * (1 - k)
    return result


def calc_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calc_macd_series(closes):
    ema12 = calc_ema_series(closes, S1_MACD_FAST)
    ema26 = calc_ema_series(closes, S1_MACD_SLOW)
    n = len(closes)
    macd_line = [None] * n
    for i in range(n):
        if ema12[i] is not None and ema26[i] is not None:
            macd_line[i] = ema12[i] - ema26[i]
    signal = [None] * n
    hist   = [None] * n
    k = 2.0 / (S1_MACD_SIG + 1)
    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if first_valid is None:
        return macd_line, signal, hist
    seed_end = first_valid + S1_MACD_SIG
    if seed_end > n:
        return macd_line, signal, hist
    vals = [macd_line[i] for i in range(first_valid, seed_end) if macd_line[i] is not None]
    if len(vals) < S1_MACD_SIG:
        return macd_line, signal, hist
    signal[seed_end - 1] = sum(vals) / S1_MACD_SIG
    for i in range(seed_end, n):
        if macd_line[i] is not None and signal[i - 1] is not None:
            signal[i] = macd_line[i] * k + signal[i - 1] * (1 - k)
    for i in range(n):
        if macd_line[i] is not None and signal[i] is not None:
            hist[i] = macd_line[i] - signal[i]
    return macd_line, signal, hist


def calc_adx_series(highs, lows, closes):
    n = len(closes)
    p = S1_ADX_PERIOD
    adx    = [None] * n
    di_pos = [None] * n
    di_neg = [None] * n
    if n < p * 2 + 2:
        return adx, di_pos, di_neg
    tr_raw = [0.0] * n
    dm_p   = [0.0] * n
    dm_n   = [0.0] * n
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr_raw[i] = max(h - l, abs(h - pc), abs(l - pc))
        up   = highs[i]    - highs[i - 1]
        down = lows[i - 1] - lows[i]
        if up > down and up > 0:   dm_p[i] = up
        if down > up and down > 0: dm_n[i] = down
    s_tr = [0.0] * n; s_dp = [0.0] * n; s_dn = [0.0] * n
    s_tr[p] = sum(tr_raw[1:p+1])
    s_dp[p] = sum(dm_p[1:p+1])
    s_dn[p] = sum(dm_n[1:p+1])
    for i in range(p + 1, n):
        s_tr[i] = s_tr[i-1] - s_tr[i-1]/p + tr_raw[i]
        s_dp[i] = s_dp[i-1] - s_dp[i-1]/p + dm_p[i]
        s_dn[i] = s_dn[i-1] - s_dn[i-1]/p + dm_n[i]
    dx_vals = [None] * n
    for i in range(p, n):
        atr = s_tr[i]
        if atr == 0: continue
        dip = 100.0 * s_dp[i] / atr
        din = 100.0 * s_dn[i] / atr
        di_pos[i] = dip; di_neg[i] = din
        denom = dip + din
        dx_vals[i] = 0.0 if denom == 0 else 100.0 * abs(dip - din) / denom
    first_dx = next((i for i in range(n) if dx_vals[i] is not None), None)
    if first_dx is None: return adx, di_pos, di_neg
    se = first_dx + p
    if se > n: return adx, di_pos, di_neg
    sv = [dx_vals[i] for i in range(first_dx, se) if dx_vals[i] is not None]
    if len(sv) < p: return adx, di_pos, di_neg
    adx[se - 1] = sum(sv) / p
    for i in range(se, n):
        if dx_vals[i] is not None and adx[i-1] is not None:
            adx[i] = (adx[i-1] * (p-1) + dx_vals[i]) / p
    return adx, di_pos, di_neg


def calc_atr_wilder(highs, lows, closes, period):
    """Wilder ATR — returns list aligned to closes."""
    n = len(closes)
    atr = [None] * n
    if n < period + 1:
        return atr
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    atr[period] = sum(tr[1:period+1]) / period
    for i in range(period + 1, n):
        atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
    return atr

# ============================================================================
# DATA FETCHER
# ============================================================================

def fetch_candles(symbol, start_ts, end_ts):
    """Fetch all 15m candles with warmup. Returns (lists...) or None."""
    warmup_ms     = WARMUP_BARS * 15 * 60 * 1000
    fetch_start   = start_ts - warmup_ms
    all_candles   = []
    current_start = fetch_start

    while current_start < end_ts:
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={'symbol': symbol, 'interval': INTERVAL,
                        'startTime': current_start, 'endTime': end_ts, 'limit': 1000},
                timeout=15
            )
        except Exception as e:
            return None, f'FETCH ERROR: {e}'
        if resp.status_code == 400:
            return None, 'NOT LISTED'
        if resp.status_code != 200:
            return None, f'HTTP {resp.status_code}'
        batch = resp.json()
        if not isinstance(batch, list) or len(batch) == 0:
            break
        all_candles.extend(batch)
        current_start = batch[-1][0] + 1
        if len(batch) < 1000:
            break

    if len(all_candles) < WARMUP_BARS + 2:
        return None, 'NOT ENOUGH DATA'

    closes = [float(c[4]) for c in all_candles]
    opens  = [float(c[1]) for c in all_candles]
    highs  = [float(c[2]) for c in all_candles]
    lows   = [float(c[3]) for c in all_candles]
    times  = [int(c[0])   for c in all_candles]
    return (closes, opens, highs, lows, times), 'OK'


def fetch_h4_candles(symbol, end_ts):
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={'symbol': symbol, 'interval': '4h',
                    'endTime': end_ts,
                    'limit': S2_H4_MA_PERIOD + S2_H4_SLOPE_BARS + 10},
            timeout=15
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, list) or len(data) < S2_H4_MA_PERIOD + S2_H4_SLOPE_BARS + 1:
            return None
        return data
    except Exception:
        return None


def get_h4_ma44_direction(symbol, ts_ms):
    candles = fetch_h4_candles(symbol, ts_ms)
    if candles is None:
        return None
    h4_closes = [float(c[4]) for c in candles]
    ma_now  = calc_sma(h4_closes,                     S2_H4_MA_PERIOD)
    ma_prev = calc_sma(h4_closes[:-S2_H4_SLOPE_BARS], S2_H4_MA_PERIOD)
    if ma_now is None or ma_prev is None:
        return None
    return ma_now > ma_prev   # True = rising, False = falling

# ============================================================================
# OUTCOME CHECKER — no time limit, scans forward until SL/TP or now
# ============================================================================

def check_outcome_unlimited(symbol, entry_ts_ms, entry, sl, tp, stype):
    now_ms        = int(time.time() * 1000)
    current_start = entry_ts_ms + 1

    while current_start < now_ms:
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={'symbol': symbol, 'interval': INTERVAL,
                        'startTime': current_start, 'endTime': now_ms, 'limit': 1000},
                timeout=15
            )
            if resp.status_code != 200:
                return 'UNKNOWN'
            candles = resp.json()
            if not isinstance(candles, list) or len(candles) == 0:
                break
        except Exception:
            return 'UNKNOWN'
        for c in candles:
            h = float(c[2]); l = float(c[3])
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
# STRATEGY 1 SCANNER — EMA 9/26 Cross + 6 Filters
# ============================================================================

def scan_s1(symbol, closes, opens, highs, lows, times, start_ts, end_ts):
    ema9_all   = calc_ema_series(closes, S1_EMA_FAST)
    ema26_all  = calc_ema_series(closes, S1_EMA_SLOW)
    ema200_all = calc_ema_series(closes, S1_EMA_TREND)
    macd_all, sig_all, hist_all = calc_macd_series(closes)
    adx_all, dip_all, din_all   = calc_adx_series(highs, lows, closes)

    signals        = []
    used_cross_idx = set()
    trade_open     = False

    for i in range(WARMUP_BARS, len(closes) - 1):
        candle_ts = times[i]
        if not (start_ts <= candle_ts <= end_ts):
            continue
        if None in (ema9_all[i], ema26_all[i], ema200_all[i],
                    adx_all[i], dip_all[i], din_all[i],
                    macd_all[i], sig_all[i], hist_all[i]):
            continue
        if None in (ema9_all[i-1], ema26_all[i-1]):
            continue

        ef_now,  es_now  = ema9_all[i],     ema26_all[i]
        ef_prev, es_prev = ema9_all[i - 1], ema26_all[i - 1]
        bullish_cross = (ef_prev <= es_prev) and (ef_now > es_now)
        bearish_cross = (ef_prev >= es_prev) and (ef_now < es_now)

        if not (bullish_cross or bearish_cross):
            continue
        if i in used_cross_idx:
            continue
        direction = 'LONG' if bullish_cross else 'SHORT'
        if trade_open:
            continue

        fired = False
        for j in (i, i + 1):
            if j >= len(closes):
                break
            if None in (ema9_all[j], ema26_all[j], ema200_all[j],
                        adx_all[j], dip_all[j], din_all[j],
                        macd_all[j], sig_all[j], hist_all[j]):
                continue

            c_c = closes[j]; c_o = opens[j]
            ef_j = ema9_all[j]; es_j = ema26_all[j]
            e2   = ema200_all[j]
            adx_j = adx_all[j]; dip_j = dip_all[j]; din_j = din_all[j]
            mac_j = macd_all[j]; msi_j = sig_all[j]; mhi_j = hist_all[j]

            # F2
            if direction == 'LONG':
                if not ((c_c > c_o) and (c_c > ef_j) and (c_c > es_j)): continue
            else:
                if not ((c_c < c_o) and (c_c < ef_j) and (c_c < es_j)): continue
            # F3
            if direction == 'LONG'  and c_c <= e2: continue
            if direction == 'SHORT' and c_c >= e2: continue
            # F4
            if adx_j <= 25: continue
            # F5
            if direction == 'LONG'  and not (dip_j > din_j): continue
            if direction == 'SHORT' and not (din_j > dip_j): continue
            # F6
            if direction == 'LONG'  and not (mac_j > msi_j and mhi_j > 0): continue
            if direction == 'SHORT' and not (mac_j < msi_j and mhi_j < 0): continue

            entry    = c_c
            entry_ts = times[j]
            sl = entry * (1 - S1_SL/100) if direction == 'LONG' else entry * (1 + S1_SL/100)
            tp = entry * (1 + S1_TP/100) if direction == 'LONG' else entry * (1 - S1_TP/100)
            outcome = check_outcome_unlimited(symbol, entry_ts, entry, sl, tp, direction)

            signals.append({
                'strategy':     'S1_EMA_CROSS',
                'symbol':       symbol,
                'type':         direction,
                'cross_time':   datetime.fromtimestamp(times[i]/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                'entry_time':   datetime.fromtimestamp(entry_ts/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                'entry_ts':     entry_ts,
                'entry_candle': 'same' if j == i else 'next',
                'entry':        entry,
                'sl':           sl,
                'tp':           tp,
                'ema9':         ef_j,
                'ema26':        es_j,
                'ema200':       e2,
                'adx':          adx_j,
                'di_plus':      dip_j,
                'di_minus':     din_j,
                'macd':         mac_j,
                'macd_sig':     msi_j,
                'macd_hist':    mhi_j,
                'outcome':      outcome,
            })

            used_cross_idx.add(i)
            trade_open = True
            fired = True
            break

        if fired and signals[-1]['outcome'] in ('WIN', 'LOSS'):
            trade_open = False

    return signals

# ============================================================================
# STRATEGY 2 SCANNER — MA44 Bounce SHORT ONLY
# ============================================================================

def s2_dist_in_zone(dist_pct):
    return ((S2_DIST_A_MIN <= dist_pct <= S2_DIST_A_MAX) or
            (S2_DIST_B_MIN <= dist_pct <= S2_DIST_B_MAX))


def s2_check_setup(closes, opens, highs, lows, i, ma44_series, atr_series):
    """Returns ('SHORT', diag) or (None, None)."""
    if closes[i] >= opens[i]:
        return None, None   # must be bearish

    c_close = closes[i]; c_open = opens[i]
    c_high  = highs[i];  c_low  = lows[i]

    # MA44 value and slope
    ma44 = ma44_series[i]
    if ma44 is None:
        return None, None

    # F5 — slope magnitude HARD REJECT
    if i < S2_SLOPE_LB or ma44_series[i - S2_SLOPE_LB] is None:
        return None, None
    ma44_8ago = ma44_series[i - S2_SLOPE_LB]
    ma_slope_pct = (ma44 - ma44_8ago) / ma44 * 100
    if abs(ma_slope_pct) < S2_MA_SLOPE_MIN:
        return None, None

    # Monotonic: MA44 must fall every candle for SLOPE_LB bars
    for k in range(1, S2_SLOPE_LB + 1):
        if ma44_series[i - k + 1] is None or ma44_series[i - k] is None:
            return None, None
        if ma44_series[i - k + 1] >= ma44_series[i - k]:
            return None, None  # not continuously falling

    # F6 — MA acceleration strict sign check
    if i < S2_ACCEL_BARS * 2 or ma44_series[i - S2_ACCEL_BARS] is None or ma44_series[i - S2_ACCEL_BARS*2] is None:
        return None, None
    ma44_4ago  = ma44_series[i - S2_ACCEL_BARS]
    ma44_8ago2 = ma44_series[i - S2_ACCEL_BARS * 2]
    slope_recent = ma44 - ma44_4ago
    slope_prior  = ma44_4ago - ma44_8ago2
    if not (slope_recent < 0 and slope_prior < 0 and slope_recent < slope_prior):
        return None, None
    ma_accel_val = slope_recent - slope_prior

    # Candle geometry
    body_top    = max(c_open, c_close)
    body_bottom = min(c_open, c_close)
    candle_size = c_high - c_low
    body_size   = body_top - body_bottom
    wick_pct    = candle_size / c_high if c_high > 0 else 0
    body_ratio  = body_size / candle_size if candle_size > 0 else 0

    # F1 — body ratio
    if body_ratio < S2_MIN_BODY_RATIO:
        return None, None
    # F4 — wick bounds
    if wick_pct < S2_MIN_WICK_PCT or wick_pct > S2_MAX_WICK_PCT:
        return None, None
    # Body strictly below MA44
    if body_top >= ma44:
        return None, None
    # F2/F3 — split distance zone
    dist_raw = ma44 - body_top
    if not s2_dist_in_zone(dist_raw / ma44):
        return None, None

    diag = {
        'ma_slope_8bar': ma_slope_pct,
        'ma_accel':      ma_accel_val,
    }
    return 'SHORT', diag


def scan_s2(symbol, closes, opens, highs, lows, times, start_ts, end_ts):
    # Compute MA44 series (SMA — stored per bar for full lookback)
    n = len(closes)
    ma44_series = [None] * n
    for i in range(S2_MA_PERIOD - 1, n):
        ma44_series[i] = sum(closes[i - S2_MA_PERIOD + 1: i + 1]) / S2_MA_PERIOD

    atr_series = calc_atr_wilder(highs, lows, closes, S2_ATR_PERIOD)

    signals          = []
    last_signal_ts   = 0
    pending_dir      = None
    pending_setup_i  = None
    pending_diag     = None
    consec_loss      = {'SHORT': 0}
    pause_until      = {'SHORT': 0}
    h4_cache         = {}

    start_i = max(WARMUP_BARS, S2_MA_PERIOD + S2_SLOPE_LB + S2_ATR_PERIOD + 5)

    for i in range(start_i, n - 1):
        candle_ts = times[i]
        in_window = (start_ts <= candle_ts <= end_ts)

        # ── STEP 2: fire pending setup ────────────────────────────────────────
        if pending_dir is not None:
            ma44_val = ma44_series[pending_setup_i]
            if ma44_val is not None and opens[i] < ma44_val and in_window:
                side = pending_dir
                if candle_ts >= pause_until[side] and candle_ts - last_signal_ts >= S2_COOLDOWN_MS:
                    entry    = opens[i]
                    sl       = entry * (1 + S2_SL / 100)
                    tp       = entry * (1 - S2_TP / 100)
                    si       = pending_setup_i
                    diag     = pending_diag or {}

                    setup_open  = opens[si]; setup_close = closes[si]
                    setup_high  = highs[si]; setup_low   = lows[si]
                    candle_size = setup_high - setup_low
                    body_top    = max(setup_open, setup_close)
                    body_bot    = min(setup_open, setup_close)
                    wick_pct_s  = (setup_high - body_top) / setup_high * 100 if setup_high > 0 else 0
                    body_ratio  = (body_top - body_bot) / candle_size if candle_size > 0 else 0
                    dist_pct    = (ma44_val - body_top) / ma44_val * 100
                    atr_val     = atr_series[si]
                    atr_pct     = atr_val / closes[si] * 100 if atr_val and closes[si] > 0 else 0

                    h4_bucket = (times[si] // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
                    h4_rising = h4_cache.get(h4_bucket)
                    h4_dir    = ('FALLING' if h4_rising is False else
                                 'RISING'  if h4_rising is True  else 'N/A')

                    outcome = check_outcome_unlimited(symbol, candle_ts, entry, sl, tp, side)

                    signals.append({
                        'strategy':      'S2_MA44_BOUNCE',
                        'symbol':        symbol,
                        'type':          'SHORT',
                        'setup_time':    datetime.fromtimestamp(times[si]/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                        'entry_time':    datetime.fromtimestamp(candle_ts/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                        'entry_ts':      candle_ts,
                        'entry':         entry,
                        'sl':            sl,
                        'tp':            tp,
                        'ma44':          ma44_val,
                        'ma_slope_8bar': diag.get('ma_slope_8bar', 0.0),
                        'ma_accel':      diag.get('ma_accel', 0.0),
                        'h4_ma_dir':     h4_dir,
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
                        if consec_loss[side] >= S2_CONSEC_LOSS_MAX:
                            pause_until[side] = candle_ts + S2_CONSEC_LOSS_MS
                            consec_loss[side] = 0
                    elif outcome == 'WIN':
                        consec_loss[side] = 0

            pending_dir = None; pending_setup_i = None; pending_diag = None

        # ── STEP 1: check setup candle ────────────────────────────────────────
        if not in_window:
            continue

        direction, diag = s2_check_setup(closes, opens, highs, lows, i, ma44_series, atr_series)
        if direction is None:
            continue

        # F7 — ATR
        atr_now = atr_series[i]
        if atr_now is not None and closes[i] > 0:
            if (atr_now / closes[i] * 100) >= S2_ATR_MAX_PCT * 100:
                continue

        # F8 — 4H gate (cached)
        h4_bucket = (candle_ts // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
        if h4_bucket not in h4_cache:
            h4_cache[h4_bucket] = get_h4_ma44_direction(symbol, candle_ts)
        h4_rising = h4_cache[h4_bucket]
        if h4_rising is True:   # rising = skip SHORT
            continue

        pending_dir     = direction
        pending_setup_i = i
        pending_diag    = diag

    return signals

# ============================================================================
# REPORT GENERATOR
# ============================================================================

def generate_report(all_results, skipped, filename='combined_backtest_report.txt'):
    W   = 80
    gen = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    with open(filename, 'w', encoding='utf-8') as f:
        def p(line=''):   print(line, file=f)
        def div(c='='):   p(c * W)

        # ── Global header ─────────────────────────────────────────────────────
        div('=')
        p('COMBINED DUAL-STRATEGY BACKTEST')
        p('15-minute candles  |  Binance  |  87 symbols from Crypto Universe CSV')
        p(f'Period    : {PERIOD["label"]}')
        p(f'Generated : {gen}')
        p()
        p('STRATEGY 1 — EMA 9/26 Cross + 6-Filter Suite')
        p(f'  SL: {S1_SL}%  |  TP: {S1_TP}%  |  R:R 1:3  |  Both directions  |  No time limit')
        p()
        p('STRATEGY 2 — MA44 Bounce  (SHORT ONLY)')
        p(f'  SL: {S2_SL}%  |  TP: {S2_TP}%  |  R:R 1:3  |  Cooldown: 4h  |  No time limit')
        div('=')
        p()

        # Flatten all signals
        all_s1 = [s for sym, r in all_results for s in r['s1']]
        all_s2 = [s for sym, r in all_results for s in r['s2']]
        all_signals = all_s1 + all_s2

        def summary_block(signals, label, sl_pct, tp_pct):
            if not signals:
                p(f'  {label}: No signals')
                return
            wins    = sum(1 for s in signals if s['outcome'] == 'WIN')
            losses  = sum(1 for s in signals if s['outcome'] == 'LOSS')
            ongoing = sum(1 for s in signals if s['outcome'] == 'ONGOING')
            total   = len(signals)
            closed  = wins + losses
            wr      = wins / closed * 100 if closed > 0 else 0
            pnl     = (wins * tp_pct) - (losses * sl_pct)
            exp     = (wr/100 * tp_pct) - ((100-wr)/100 * sl_pct) if closed > 0 else 0
            p(f'  {label}')
            p(f'    Signals : {total}  W:{wins}  L:{losses}  Open:{ongoing}')
            if closed > 0:
                p(f'    Win rate: {wr:.1f}%  ({wins}/{closed} closed)')
                p(f'    PnL     : {pnl:+.2f}%  |  Expectancy: {exp:+.3f}%/trade')

        # ── Aggregate summary ─────────────────────────────────────────────────
        div('*')
        p('  AGGREGATE SUMMARY — ALL SYMBOLS')
        div('*')
        p()
        summary_block(all_s1, 'Strategy 1 (EMA Cross)', S1_SL, S1_TP)
        p()
        summary_block(all_s2, 'Strategy 2 (MA44 Bounce)', S2_SL, S2_TP)
        p()

        if skipped:
            p(f'  Skipped symbols ({len(skipped)}):')
            for sym, reason in skipped:
                p(f'    {sym:<16} {reason}')
        p()

        # ── Per-symbol leaderboard — S1 ───────────────────────────────────────
        div('-')
        p('  LEADERBOARD — STRATEGY 1 (EMA Cross)  sorted by WR%')
        div('-')
        p(f'  {"Symbol":<14} {"Sig":>4}  {"W":>4}  {"L":>4}  {"Ong":>3}  {"WR%":>6}  {"PnL%":>8}  {"L/S"}')
        div('-')
        s1_rows = []
        for sym, r in all_results:
            sigs = r['s1']
            w = sum(1 for s in sigs if s['outcome']=='WIN')
            l = sum(1 for s in sigs if s['outcome']=='LOSS')
            o = sum(1 for s in sigs if s['outcome']=='ONGOING')
            cl = w + l
            wr = w/cl*100 if cl>0 else -1
            pnl = (w*S1_TP)-(l*S1_SL)
            lng = sum(1 for s in sigs if s['type']=='LONG')
            sht = sum(1 for s in sigs if s['type']=='SHORT')
            s1_rows.append((sym, len(sigs), w, l, o, cl, wr, pnl, lng, sht))
        s1_rows.sort(key=lambda r: (-(r[6] if r[5]>0 else -999), -r[1]))
        for sym, tot, w, l, o, cl, wr, pnl, lng, sht in s1_rows:
            if tot == 0: continue
            wr_s  = f'{wr:.1f}%' if cl>0 else 'n/a'
            pnl_s = f'{pnl:+.2f}%' if cl>0 else 'n/a'
            p(f'  {sym:<14} {tot:>4}  {w:>4}  {l:>4}  {o:>3}  {wr_s:>6}  {pnl_s:>8}  L:{lng} S:{sht}')
        div('-')
        p()

        # ── Per-symbol leaderboard — S2 ───────────────────────────────────────
        div('-')
        p('  LEADERBOARD — STRATEGY 2 (MA44 Bounce)  sorted by WR%')
        div('-')
        p(f'  {"Symbol":<14} {"Sig":>4}  {"W":>4}  {"L":>4}  {"Ong":>3}  {"WR%":>6}  {"PnL%":>8}  {"Zone A/B"}')
        div('-')
        s2_rows = []
        for sym, r in all_results:
            sigs = r['s2']
            w = sum(1 for s in sigs if s['outcome']=='WIN')
            l = sum(1 for s in sigs if s['outcome']=='LOSS')
            o = sum(1 for s in sigs if s['outcome']=='ONGOING')
            cl = w + l
            wr = w/cl*100 if cl>0 else -1
            pnl = (w*S2_TP)-(l*S2_SL)
            za = sum(1 for s in sigs if S2_DIST_A_MIN*100 <= s['dist_pct'] <= S2_DIST_A_MAX*100)
            zb = sum(1 for s in sigs if S2_DIST_B_MIN*100 <= s['dist_pct'] <= S2_DIST_B_MAX*100)
            s2_rows.append((sym, len(sigs), w, l, o, cl, wr, pnl, za, zb))
        s2_rows.sort(key=lambda r: (-(r[6] if r[5]>0 else -999), -r[1]))
        for sym, tot, w, l, o, cl, wr, pnl, za, zb in s2_rows:
            if tot == 0: continue
            wr_s  = f'{wr:.1f}%' if cl>0 else 'n/a'
            pnl_s = f'{pnl:+.2f}%' if cl>0 else 'n/a'
            p(f'  {sym:<14} {tot:>4}  {w:>4}  {l:>4}  {o:>3}  {wr_s:>6}  {pnl_s:>8}  A:{za} B:{zb}')
        div('-')
        p()
        div('=')
        p()

        # ── Per-symbol detail sections ────────────────────────────────────────
        for sym, r in all_results:
            s1_sigs = r['s1']
            s2_sigs = r['s2']
            if not s1_sigs and not s2_sigs:
                continue

            div('#')
            p(f'  {sym}  |  {PERIOD["label"]}')
            div('#')
            p()

            # S1 summary
            if s1_sigs:
                w  = sum(1 for s in s1_sigs if s['outcome']=='WIN')
                l  = sum(1 for s in s1_sigs if s['outcome']=='LOSS')
                o  = sum(1 for s in s1_sigs if s['outcome']=='ONGOING')
                cl = w + l
                wr = f'{w/cl*100:.1f}%' if cl>0 else 'n/a'
                pnl= f'{(w*S1_TP)-(l*S1_SL):+.2f}%' if cl>0 else 'n/a'
                p(f'  [S1 EMA CROSS]  {len(s1_sigs)} signals  W:{w} L:{l} Open:{o}  WR:{wr}  PnL:{pnl}')
                div('-')
                for idx, s in enumerate(sorted(s1_sigs, key=lambda x: x['entry_ts']), 1):
                    ol     = {'WIN':'[WIN ]','LOSS':'[LOSS]','ONGOING':'[OPEN]','UNKNOWN':'[????]'}.get(s['outcome'],'[????]')
                    sl_lbl = f'-{S1_SL}%' if s['type']=='LONG' else f'+{S1_SL}%'
                    tp_lbl = f'+{S1_TP}%' if s['type']=='LONG' else f'-{S1_TP}%'
                    p(f'  #{idx:<3} {ol} {s["type"]:<6} Entry:{s["entry_time"]} [{s["entry_candle"]} candle]')
                    p(f'       Cross:{s["cross_time"]}  ADX={s["adx"]:.1f}  DI+={s["di_plus"]:.1f}  DI-={s["di_minus"]:.1f}')
                    p(f'       EMA9={s["ema9"]:.4f}  EMA26={s["ema26"]:.4f}  EMA200={s["ema200"]:.4f}')
                    p(f'       MACD={s["macd"]:.4f}  Sig={s["macd_sig"]:.4f}  Hist={s["macd_hist"]:.4f}')
                    p(f'       Entry=${s["entry"]:.4f}  SL=${s["sl"]:.4f}({sl_lbl})  TP=${s["tp"]:.4f}({tp_lbl})')
                    p()
                div('-')
                p()

            # S2 summary
            if s2_sigs:
                w  = sum(1 for s in s2_sigs if s['outcome']=='WIN')
                l  = sum(1 for s in s2_sigs if s['outcome']=='LOSS')
                o  = sum(1 for s in s2_sigs if s['outcome']=='ONGOING')
                cl = w + l
                wr = f'{w/cl*100:.1f}%' if cl>0 else 'n/a'
                pnl= f'{(w*S2_TP)-(l*S2_SL):+.2f}%' if cl>0 else 'n/a'
                za = sum(1 for s in s2_sigs if S2_DIST_A_MIN*100 <= s['dist_pct'] <= S2_DIST_A_MAX*100)
                zb = sum(1 for s in s2_sigs if S2_DIST_B_MIN*100 <= s['dist_pct'] <= S2_DIST_B_MAX*100)
                p(f'  [S2 MA44 BOUNCE]  {len(s2_sigs)} signals  W:{w} L:{l} Open:{o}  WR:{wr}  PnL:{pnl}  ZoneA:{za} ZoneB:{zb}')
                div('-')
                for idx, s in enumerate(sorted(s2_sigs, key=lambda x: x['entry_ts']), 1):
                    ol   = {'WIN':'[WIN ]','LOSS':'[LOSS]','ONGOING':'[OPEN]','UNKNOWN':'[????]'}.get(s['outcome'],'[????]')
                    zone = ('A' if S2_DIST_A_MIN*100 <= s['dist_pct'] <= S2_DIST_A_MAX*100
                            else 'B' if S2_DIST_B_MIN*100 <= s['dist_pct'] <= S2_DIST_B_MAX*100
                            else '?')
                    p(f'  #{idx:<3} {ol} SHORT  Entry:{s["entry_time"]}  Setup:{s["setup_time"]}')
                    p(f'       MA44={s["ma44"]:.4f}  slope={s["ma_slope_8bar"]:+.3f}%  accel={s["ma_accel"]:+.5f}')
                    p(f'       dist={s["dist_pct"]:.3f}% zone={zone}  ATR={s["atr_14_pct"]:.3f}%  H4={s["h4_ma_dir"]}')
                    p(f'       wick={s["wick_pct"]:.2f}%  body={s["body_ratio"]*100:.1f}%')
                    p(f'       Entry=${s["entry"]:.4f}  SL=${s["sl"]:.4f}(+{S2_SL}%)  TP=${s["tp"]:.4f}(-{S2_TP}%)')
                    p()
                div('-')
                p()

        div('=')
        p('METHODOLOGY')
        div('=')
        p('  S1 WIN/LOSS : TP or SL hit — no time limit — ONGOING if still open')
        p('  S2 WIN/LOSS : TP or SL hit — no time limit — ONGOING if still open')
        p('  S1 EMA: seeded with SMA(N), k=2/(N+1)  |  ADX: Wilder smoothing')
        p('  S2 MA44: simple SMA  |  ATR: Wilder  |  4H gate cached per 4h bucket')
        p('  Both strategies: SL/TP checked candle-by-candle from bar after entry')
        div('=')

    return filename

# ============================================================================
# MAIN
# ============================================================================

def main():
    t = sys.__stdout__
    t.write('\n' + '=' * 60 + '\n')
    t.write('COMBINED DUAL-STRATEGY BACKTEST\n')
    t.write(f'{len(SYMBOLS)} symbols  |  {PERIOD["label"]}\n')
    t.write('S1: EMA 9/26 Cross  |  S2: MA44 Bounce SHORT\n')
    t.write('=' * 60 + '\n\n')

    start_ts = int(PERIOD['start_dt'].timestamp() * 1000)
    end_ts   = int(PERIOD['end_dt'].timestamp()   * 1000)

    all_results = []
    skipped     = []

    for idx, symbol in enumerate(SYMBOLS, 1):
        t.write(f'[{idx:>2}/{len(SYMBOLS)}]  {symbol:<16} ')
        t.flush()

        candle_data, status = fetch_candles(symbol, start_ts, end_ts)

        if candle_data is None:
            reason = status
            t.write(f'SKIP ({reason})\n')
            skipped.append((symbol, reason))
            continue

        closes, opens, highs, lows, times = candle_data
        t.write(f'{len(closes)} candles | ')
        t.flush()

        try:
            s1_sigs = scan_s1(symbol, closes, opens, highs, lows, times, start_ts, end_ts)
        except Exception as e:
            t.write(f'S1 ERROR: {e}\n')
            import traceback; traceback.print_exc()
            s1_sigs = []

        try:
            s2_sigs = scan_s2(symbol, closes, opens, highs, lows, times, start_ts, end_ts)
        except Exception as e:
            t.write(f'S2 ERROR: {e}\n')
            import traceback; traceback.print_exc()
            s2_sigs = []

        s1_w = sum(1 for s in s1_sigs if s['outcome']=='WIN')
        s1_l = sum(1 for s in s1_sigs if s['outcome']=='LOSS')
        s1_o = sum(1 for s in s1_sigs if s['outcome']=='ONGOING')
        s2_w = sum(1 for s in s2_sigs if s['outcome']=='WIN')
        s2_l = sum(1 for s in s2_sigs if s['outcome']=='LOSS')
        s2_o = sum(1 for s in s2_sigs if s['outcome']=='ONGOING')

        s1_cl = s1_w + s1_l
        s2_cl = s2_w + s2_l
        s1_wr = f'{s1_w/s1_cl*100:.0f}%' if s1_cl>0 else 'n/a'
        s2_wr = f'{s2_w/s2_cl*100:.0f}%' if s2_cl>0 else 'n/a'

        t.write(f'S1:{len(s1_sigs):>2}sig W{s1_w}L{s1_l}O{s1_o}({s1_wr})  '
                f'S2:{len(s2_sigs):>2}sig W{s2_w}L{s2_l}O{s2_o}({s2_wr})\n')

        all_results.append((symbol, {'s1': s1_sigs, 's2': s2_sigs}))
        time.sleep(0.1)

    t.write(f'\n{len(all_results)} symbols done  |  {len(skipped)} skipped\n')
    t.write('Writing report...\n')
    fname = generate_report(all_results, skipped)
    t.write(f'Done → {fname}\n\n')


if __name__ == '__main__':
    main()