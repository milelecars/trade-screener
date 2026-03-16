"""
MULTI-SYMBOL BACKTEST — EMA 9/26 Cross + Advanced Filters
==========================================================
Binance  |  15-minute candles  |  01 Sep 2025 → 28 Feb 2026
97 symbols

6-FILTER SIGNAL (all must pass simultaneously):
  F1  EMA crossover   : EMA9 crosses above/below EMA26
  F2  Candle confirm  : close > open + close > EMA9 + close > EMA26  (LONG)
                        close < open + close < EMA9 + close < EMA26  (SHORT)
  F3  EMA200 trend    : close > EMA200 (LONG)  |  close < EMA200 (SHORT)
  F4  ADX strength    : ADX(14) > 25  (Wilder smoothing)
  F5  DI direction    : DI+ > DI−  (LONG)  |  DI− > DI+  (SHORT)
  F6  MACD momentum   : MACD Line > Signal AND Histogram > 0  (LONG)
                        MACD Line < Signal AND Histogram < 0  (SHORT)

CANDLE SELECTION:
  Check crossover candle N first → if qualifies, enter at close of N
  Else check candle N+1 → if qualifies, enter at close of N+1
  Else skip — one trade per crossover, no re-use

CONCURRENT TRADES:
  If a trade is open, ignore all new crossover signals until closed by SL/TP

SL  : −0.5%   TP : +1.5%   (R:R 1:3)
Time limit: NONE — runs until SL or TP hit; ONGOING = still open at report time
"""

import requests
from datetime import datetime, timezone
import sys
import time

# ============================================================================
# PARAMETERS
# ============================================================================

EMA_FAST      = 9
EMA_SLOW      = 26
EMA_TREND     = 200
MACD_FAST     = 12
MACD_SLOW     = 26
MACD_SIG      = 9
ADX_PERIOD    = 14
SL_PERCENT    = 0.5
TP_PERCENT    = 1.5
INTERVAL      = '15m'
WARMUP_BARS   = 250   # > EMA200; ADX needs 28, MACD 35

SYMBOLS = [
    '1INCHUSDT', '2ZUSDT', 'AAVEUSDT', 'ADAUSDT', 'ALGOUSDT',
    'AMPUSDT', 'APTUSDT', 'ARBUSDT', 'ASTERUSDT', 'ATOMUSDT',
    'AVAXUSDT', 'AXSUSDT', 'BARDUSDT', 'BATUSDT', 'BCHUSDT',
    'BNBUSDT', 'BONKUSDT', 'BTCUSDT', 'BTTUSDT', 'CAKEUSDT',
    'CHZUSDT', 'COWUSDT', 'CRVUSDT', 'DASHUSDT', 'DCRUSDT',
    'DOGEUSDT', 'DOTUSDT', 'EGLDUSDT', 'EIGENUSDT', 'ENAUSDT',
    'ENSUSDT', 'ETCUSDT', 'ETHUSDT', 'ETHFIUSDT', 'FETUSDT',
    'FILUSDT', 'GALAUSDT', 'GLMUSDT', 'GNOUSDT', 'GRTUSDT',
    'HBARUSDT', 'ICPUSDT', 'IMXUSDT', 'INJUSDT', 'IOTAUSDT',
    'JASMYUSDT', 'JTOUSDT', 'JUPUSDT', 'LDOUSDT', 'LINKUSDT',
    'LPTUSDT', 'LTCUSDT', 'LUNCUSDT', 'MANAUSDT', 'NEARUSDT',
    'NEOUSDT', 'NEXOUSDT', 'ONDOUSDT', 'OPUSDT', 'PENDLEUSDT',
    'PENGUUSDT', 'PEPEUSDT', 'POLUSDT', 'PUMPUSDT', 'PYTHUSDT',
    'QNTUSDT', 'RUNEUSDT', 'RAYUSDT', 'RENDERUSDT', 'SUSDT',
    'SANDUSDT', 'SEIUSDT', 'SFPUSDT', 'SHIBUSDT', 'SKYUSDT',
    'SOLUSDT', 'STRKUSDT', 'STXUSDT', 'SUIUSDT', 'SYRUPUSDT',
    'TAOUSDT', 'THETAUSDT', 'TIAUSDT', 'TRUMPUSDT', 'TWTUSDT',
    'UNIUSDT', 'VETUSDT', 'VIRTUALUSDT', 'WALUSDT', 'WIFUSDT',
    'WLDUSDT', 'XMRUSDT', 'XPLUSDT', 'XRPUSDT', 'XTZUSDT',
    'ZECUSDT', 'ZKUSDT', 'ZROUSDT',
]

PERIOD = {
    'label':    '01 Sep 2025 -> 28 Feb 2026',
    'start_dt': datetime(2025, 9,  1,  0,  0,  0, tzinfo=timezone.utc),
    'end_dt':   datetime(2026, 2, 28, 23, 59, 59, tzinfo=timezone.utc),
}

# ============================================================================
# INDICATOR CALCULATIONS
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


def calc_macd_series(closes):
    ema12 = calc_ema_series(closes, MACD_FAST)
    ema26 = calc_ema_series(closes, MACD_SLOW)
    n = len(closes)
    macd_line = [None] * n
    for i in range(n):
        if ema12[i] is not None and ema26[i] is not None:
            macd_line[i] = ema12[i] - ema26[i]

    signal = [None] * n
    hist   = [None] * n
    k      = 2.0 / (MACD_SIG + 1)

    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if first_valid is None:
        return macd_line, signal, hist

    seed_end = first_valid + MACD_SIG
    if seed_end > n:
        return macd_line, signal, hist

    valid_macd_vals = [macd_line[i] for i in range(first_valid, seed_end) if macd_line[i] is not None]
    if len(valid_macd_vals) < MACD_SIG:
        return macd_line, signal, hist

    signal[seed_end - 1] = sum(valid_macd_vals) / MACD_SIG
    for i in range(seed_end, n):
        if macd_line[i] is not None and signal[i - 1] is not None:
            signal[i] = macd_line[i] * k + signal[i - 1] * (1 - k)

    for i in range(n):
        if macd_line[i] is not None and signal[i] is not None:
            hist[i] = macd_line[i] - signal[i]

    return macd_line, signal, hist


def calc_adx_series(highs, lows, closes):
    n = len(closes)
    p = ADX_PERIOD
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
        up_move   = highs[i]    - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        if up_move > down_move and up_move > 0:
            dm_p[i] = up_move
        if down_move > up_move and down_move > 0:
            dm_n[i] = down_move

    smooth_tr = [0.0] * n
    smooth_dp = [0.0] * n
    smooth_dn = [0.0] * n
    smooth_tr[p] = sum(tr_raw[1: p + 1])
    smooth_dp[p] = sum(dm_p[1: p + 1])
    smooth_dn[p] = sum(dm_n[1: p + 1])

    for i in range(p + 1, n):
        smooth_tr[i] = smooth_tr[i - 1] - smooth_tr[i - 1] / p + tr_raw[i]
        smooth_dp[i] = smooth_dp[i - 1] - smooth_dp[i - 1] / p + dm_p[i]
        smooth_dn[i] = smooth_dn[i - 1] - smooth_dn[i - 1] / p + dm_n[i]

    dx_vals = [None] * n
    for i in range(p, n):
        atr = smooth_tr[i]
        if atr == 0:
            continue
        dip = 100.0 * smooth_dp[i] / atr
        din = 100.0 * smooth_dn[i] / atr
        di_pos[i] = dip
        di_neg[i] = din
        denom = dip + din
        dx_vals[i] = 0.0 if denom == 0 else 100.0 * abs(dip - din) / denom

    first_dx = next((i for i in range(n) if dx_vals[i] is not None), None)
    if first_dx is None:
        return adx, di_pos, di_neg

    adx_seed_end = first_dx + p
    if adx_seed_end > n:
        return adx, di_pos, di_neg

    seed_vals = [dx_vals[i] for i in range(first_dx, adx_seed_end) if dx_vals[i] is not None]
    if len(seed_vals) < p:
        return adx, di_pos, di_neg

    adx[adx_seed_end - 1] = sum(seed_vals) / p
    for i in range(adx_seed_end, n):
        if dx_vals[i] is not None and adx[i - 1] is not None:
            adx[i] = (adx[i - 1] * (p - 1) + dx_vals[i]) / p

    return adx, di_pos, di_neg

# ============================================================================
# OUTCOME CHECKER — symbol-aware, no time limit
# ============================================================================

def check_trade_outcome(symbol, entry_ts_ms, entry, sl, tp, stype):
    """
    Scans forward from entry in 1000-candle batches until SL or TP is hit.
    Returns ONGOING if still open at call time.
    """
    now_ms        = int(time.time() * 1000)
    current_start = entry_ts_ms + 1   # skip entry candle — entry was at its close

    while current_start < now_ms:
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    'symbol':    symbol,
                    'interval':  INTERVAL,
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

        for c in candles:
            h = float(c[2])
            l = float(c[3])
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
# SCANNER — one symbol, one period
# ============================================================================

def scan_symbol(symbol, start_ts, end_ts):
    """
    Returns list of signal dicts for this symbol, or None on fetch error.
    Skips symbol gracefully if not listed on Binance (HTTP 400).
    """
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
        return [], 'NOT ENOUGH DATA'

    closes_all = [float(c[4]) for c in all_candles]
    opens_all  = [float(c[1]) for c in all_candles]
    highs_all  = [float(c[2]) for c in all_candles]
    lows_all   = [float(c[3]) for c in all_candles]
    times_all  = [int(c[0])   for c in all_candles]

    ema9_all   = calc_ema_series(closes_all, EMA_FAST)
    ema26_all  = calc_ema_series(closes_all, EMA_SLOW)
    ema200_all = calc_ema_series(closes_all, EMA_TREND)
    macd_all, sig_all, hist_all = calc_macd_series(closes_all)
    adx_all, dip_all, din_all   = calc_adx_series(highs_all, lows_all, closes_all)

    signals        = []
    used_cross_idx = set()
    trade_open     = False

    for i in range(WARMUP_BARS, len(all_candles) - 1):
        candle_ts = times_all[i]
        if not (start_ts <= candle_ts <= end_ts):
            continue

        if None in (ema9_all[i], ema26_all[i], ema200_all[i],
                    adx_all[i], dip_all[i], din_all[i],
                    macd_all[i], sig_all[i], hist_all[i]):
            continue
        if None in (ema9_all[i - 1], ema26_all[i - 1]):
            continue

        # F1 — crossover detection
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

        # Try candle N then N+1
        fired = False
        for j in (i, i + 1):
            if j >= len(all_candles):
                break
            if None in (ema9_all[j], ema26_all[j], ema200_all[j],
                        adx_all[j], dip_all[j], din_all[j],
                        macd_all[j], sig_all[j], hist_all[j]):
                continue

            c_close = closes_all[j]
            c_open  = opens_all[j]
            ef_j    = ema9_all[j]
            es_j    = ema26_all[j]
            e200_j  = ema200_all[j]
            adx_j   = adx_all[j]
            dip_j   = dip_all[j]
            din_j   = din_all[j]
            macd_j  = macd_all[j]
            msig_j  = sig_all[j]
            mhst_j  = hist_all[j]

            # F2 — candle confirm
            if direction == 'LONG':
                if not ((c_close > c_open) and (c_close > ef_j) and (c_close > es_j)):
                    continue
            else:
                if not ((c_close < c_open) and (c_close < ef_j) and (c_close < es_j)):
                    continue

            # F3 — EMA200 trend gate
            if direction == 'LONG'  and c_close <= e200_j: continue
            if direction == 'SHORT' and c_close >= e200_j: continue

            # F4 — ADX > 25
            if adx_j <= 25: continue

            # F5 — DI direction
            if direction == 'LONG'  and not (dip_j > din_j): continue
            if direction == 'SHORT' and not (din_j > dip_j): continue

            # F6 — MACD momentum
            if direction == 'LONG'  and not (macd_j > msig_j and mhst_j > 0): continue
            if direction == 'SHORT' and not (macd_j < msig_j and mhst_j < 0): continue

            # All 6 filters passed
            entry_ts = times_all[j]
            entry    = c_close
            sl = entry * (1 - SL_PERCENT / 100) if direction == 'LONG' else entry * (1 + SL_PERCENT / 100)
            tp = entry * (1 + TP_PERCENT / 100) if direction == 'LONG' else entry * (1 - TP_PERCENT / 100)

            outcome = check_trade_outcome(symbol, entry_ts, entry, sl, tp, direction)

            signals.append({
                'symbol':        symbol,
                'type':          direction,
                'cross_ts':      times_all[i],
                'cross_time':    datetime.fromtimestamp(times_all[i] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                'entry_ts':      entry_ts,
                'entry_time':    datetime.fromtimestamp(entry_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                'entry_candle':  'same' if j == i else 'next',
                'entry':         entry,
                'sl':            sl,
                'tp':            tp,
                'ema9':          ef_j,
                'ema26':         es_j,
                'ema200':        e200_j,
                'adx':           adx_j,
                'di_plus':       dip_j,
                'di_minus':      din_j,
                'macd':          macd_j,
                'macd_sig':      msig_j,
                'macd_hist':     mhst_j,
                'outcome':       outcome,
            })

            used_cross_idx.add(i)
            trade_open = True
            fired = True
            break

        if fired and signals[-1]['outcome'] in ('WIN', 'LOSS'):
            trade_open = False

    return signals, 'OK'

# ============================================================================
# TEXT REPORT
# ============================================================================

def generate_txt(all_symbol_results, skipped, filename='ema_advanced_multi_report.txt'):
    W   = 80
    gen = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    with open(filename, 'w', encoding='utf-8') as f:

        def p(line=''):
            print(line, file=f)

        def div(char='='):
            p(char * W)

        # ── Global header ─────────────────────────────────────────────────────
        div('=')
        p('MULTI-SYMBOL BACKTEST — EMA 9/26 Cross + 6-Filter Suite')
        p('15-minute candles  |  Binance  |  Both directions')
        p(f'Period    : {PERIOD["label"]}')
        p(f'Generated : {gen}')
        p(f'SL: {SL_PERCENT}%  |  TP: {TP_PERCENT}%  |  R:R 1:3')
        p(f'Symbols   : {len(all_symbol_results)} scanned  |  {len(skipped)} skipped')
        p()
        p('FILTERS (all 6 must pass simultaneously):')
        p(f'  F1  EMA crossover : EMA{EMA_FAST} crosses EMA{EMA_SLOW}')
        p(f'  F2  Candle confirm: close direction + close > EMA{EMA_FAST} & EMA{EMA_SLOW}')
        p(f'  F3  EMA{EMA_TREND} trend  : close on correct side of EMA200')
        p(f'  F4  ADX strength  : ADX({ADX_PERIOD}) > 25  (Wilder smoothing)')
        p(f'  F5  DI direction  : DI+ > DI− (LONG)  |  DI− > DI+ (SHORT)')
        p(f'  F6  MACD momentum : MACD > Sig + Hist > 0 (LONG) | MACD < Sig + Hist < 0 (SHORT)')
        p()
        p('RULES: One trade per crossover  |  Concurrent trade blocks new signals')
        p('       Entry at close of candle N or N+1  |  No time limit on SL/TP')
        div('=')
        p()

        # ── Aggregate summary table ───────────────────────────────────────────
        all_signals = [s for _, sigs in all_symbol_results for s in sigs]
        total_sigs  = len(all_signals)
        total_w     = sum(1 for s in all_signals if s['outcome'] == 'WIN')
        total_l     = sum(1 for s in all_signals if s['outcome'] == 'LOSS')
        total_ong   = sum(1 for s in all_signals if s['outcome'] == 'ONGOING')
        total_unk   = sum(1 for s in all_signals if s['outcome'] == 'UNKNOWN')
        total_cl    = total_w + total_l
        total_wr    = total_w / total_cl * 100 if total_cl > 0 else 0
        total_pnl   = (total_w * TP_PERCENT) - (total_l * SL_PERCENT)
        total_exp   = (total_wr / 100 * TP_PERCENT) - ((100 - total_wr) / 100 * SL_PERCENT) if total_cl > 0 else 0

        div('*')
        p('  AGGREGATE SUMMARY — ALL SYMBOLS')
        div('*')
        p(f'  Total signals    : {total_sigs}')
        p(f'  Total wins       : {total_w}')
        p(f'  Total losses     : {total_l}')
        p(f'  Ongoing (open)   : {total_ong}')
        p(f'  Unknown          : {total_unk}')
        if total_cl > 0:
            p(f'  Overall win rate : {total_wr:.1f}%  ({total_w}/{total_cl} closed)')
            p(f'  Overall PnL      : {total_pnl:+.2f}%  (equal-size, closed trades)')
            p(f'  Expectancy       : {total_exp:+.3f}% per trade')
        p()

        # ── Per-symbol leaderboard ────────────────────────────────────────────
        p('  PER-SYMBOL LEADERBOARD  (sorted by WR%, then total signals)')
        div('-')
        p(f'  {"Symbol":<14} {"Sig":>4}  {"W":>4}  {"L":>4}  {"Ong":>4}  {"WR%":>6}  {"PnL%":>8}  {"L/S"}')
        div('-')

        rows = []
        for symbol, sigs in all_symbol_results:
            w   = sum(1 for s in sigs if s['outcome'] == 'WIN')
            l   = sum(1 for s in sigs if s['outcome'] == 'LOSS')
            ong = sum(1 for s in sigs if s['outcome'] == 'ONGOING')
            cl  = w + l
            wr  = w / cl * 100 if cl > 0 else -1
            pnl = (w * TP_PERCENT) - (l * SL_PERCENT)
            lng = sum(1 for s in sigs if s['type'] == 'LONG')
            sht = sum(1 for s in sigs if s['type'] == 'SHORT')
            rows.append((symbol, len(sigs), w, l, ong, cl, wr, pnl, lng, sht))

        rows.sort(key=lambda r: (-(r[6] if r[5] > 0 else -999), -r[1]))

        for symbol, tot, w, l, ong, cl, wr, pnl, lng, sht in rows:
            wr_str  = f'{wr:.1f}%' if cl > 0 else 'n/a'
            pnl_str = f'{pnl:+.2f}%' if cl > 0 else 'n/a'
            ls_str  = f'L:{lng} S:{sht}'
            p(f'  {symbol:<14} {tot:>4}  {w:>4}  {l:>4}  {ong:>4}  {wr_str:>6}  {pnl_str:>8}  {ls_str}')

        div('-')
        p()

        if skipped:
            p('  SKIPPED SYMBOLS:')
            for sym, reason in skipped:
                p(f'    {sym:<16} {reason}')
            p()

        div('=')
        p()

        # ── Per-symbol detail sections ────────────────────────────────────────
        for symbol, signals in all_symbol_results:
            if not signals:
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
            same_c  = sum(1 for s in signals if s['entry_candle'] == 'same')
            next_c  = sum(1 for s in signals if s['entry_candle'] == 'next')
            l_w     = sum(1 for s in signals if s['type'] == 'LONG'  and s['outcome'] == 'WIN')
            l_l     = sum(1 for s in signals if s['type'] == 'LONG'  and s['outcome'] == 'LOSS')
            s_w     = sum(1 for s in signals if s['type'] == 'SHORT' and s['outcome'] == 'WIN')
            s_l     = sum(1 for s in signals if s['type'] == 'SHORT' and s['outcome'] == 'LOSS')
            lc      = l_w + l_l
            sc      = s_w + s_l
            l_wr    = f'{l_w/lc*100:.1f}%' if lc > 0 else 'n/a'
            s_wr    = f'{s_w/sc*100:.1f}%' if sc > 0 else 'n/a'
            verdict = (
                'EXCELLENT  (>60%)'   if wr >= 60 else
                'GOOD       (>50%)'   if wr >= 50 else
                'MARGINAL   (40-50%)' if wr >= 40 else
                'WEAK       (25-40%)' if wr >= 25 else
                'POOR       (<25%)'
            ) if closed > 0 else 'NO CLOSED TRADES'

            div('#')
            p(f'  {symbol}  |  {PERIOD["label"]}')
            div('#')
            p()
            p('  SUMMARY')
            div('-')
            p(f'  Total signals   : {total}  (Long: {longs}  Short: {shorts})')
            p(f'  Entry candle    : same={same_c}  next={next_c}')
            p(f'  Wins            : {wins}')
            p(f'  Losses          : {losses}')
            p(f'  Ongoing (open)  : {ongoing}  ← still running at {gen}')
            p(f'  Unknown         : {unknown}')
            p()
            if closed > 0:
                p(f'  Win rate        : {wr:.1f}%  ({wins}/{closed} closed)')
                p(f'  Expectancy      : {exp:+.3f}% per trade')
                p(f'  Total PnL       : {pnl:+.2f}%  (closed trades only)')
                p(f'  Verdict         : {verdict}')
                p()
                p(f'  LONG  breakdown : {longs} signals  W:{l_w} L:{l_l}  WR:{l_wr}')
                p(f'  SHORT breakdown : {shorts} signals  W:{s_w} L:{s_l}  WR:{s_wr}')
            else:
                p('  Win rate        : n/a')
            div('-')
            p()

            p('  SIGNALS')
            div('-')
            p()

            for idx, s in enumerate(sorted(signals, key=lambda x: x['entry_ts']), 1):
                ol      = {'WIN': '[WIN ]', 'LOSS': '[LOSS]',
                           'ONGOING': '[OPEN]', 'UNKNOWN': '[????]'}.get(s['outcome'], '[????]')
                sl_lbl  = f'-{SL_PERCENT}%' if s['type'] == 'LONG' else f'+{SL_PERCENT}%'
                tp_lbl  = f'+{TP_PERCENT}%' if s['type'] == 'LONG' else f'-{TP_PERCENT}%'
                di_str  = f"DI+={s['di_plus']:.1f}  DI-={s['di_minus']:.1f}"
                mac_str = (f"MACD={s['macd']:.4f}  Sig={s['macd_sig']:.4f}  "
                           f"Hist={s['macd_hist']:.4f}")

                p(f'  Signal #{idx:<4} {ol}  {s["type"]:<6}  Entry: {s["entry_time"]}  [{s["entry_candle"]} candle]')
                p(f'  Crossover     : {s["cross_time"]}')
                p(f'  EMA           : EMA9={s["ema9"]:.4f}  EMA26={s["ema26"]:.4f}  EMA200={s["ema200"]:.4f}')
                p(f'  ADX / DI      : ADX={s["adx"]:.2f}  {di_str}')
                p(f'  MACD          : {mac_str}')
                p(f'  Entry         : ${s["entry"]:.4f}')
                p(f'  Stop Loss     : ${s["sl"]:.4f}  ({sl_lbl})')
                p(f'  Take Profit   : ${s["tp"]:.4f}  ({tp_lbl})')
                p()

            div('-')
            p()

        div('=')
        p('METHODOLOGY')
        div('=')
        p('  WIN     : TP hit before SL — no time limit')
        p('  LOSS    : SL hit before TP — no time limit')
        p('  ONGOING : Neither hit as of report generation time')
        p('  UNKNOWN : Data fetch error')
        p()
        p('  EMA     : Seeded with SMA of first N closes, k = 2/(N+1)')
        p('  ADX     : Wilder smoothing, seeded with mean of first 14 DX values')
        p('  MACD    : EMA(12) − EMA(26); Signal = EMA(9) of MACD line')
        p('  Warmup  : 250 candles before window start (indicator seeding only)')
        p('  Entry   : Close of qualifying candle (N or N+1 after crossover)')
        p('  SL/TP   : Checked candle-by-candle from the bar after entry close')
        p('  Concurrent trades: blocked per symbol until SL or TP is hit')
        div('=')

    return filename

# ============================================================================
# MAIN
# ============================================================================

def main():
    t = sys.__stdout__
    t.write('\n' + '=' * 60 + '\n')
    t.write('MULTI-SYMBOL EMA 9/26 CROSS BACKTEST\n')
    t.write(f'{len(SYMBOLS)} symbols  |  {PERIOD["label"]}\n')
    t.write(f'SL {SL_PERCENT}% / TP {TP_PERCENT}%  |  15m  |  No time limit\n')
    t.write('=' * 60 + '\n\n')

    start_ts = int(PERIOD['start_dt'].timestamp() * 1000)
    end_ts   = int(PERIOD['end_dt'].timestamp()   * 1000)

    all_symbol_results = []
    skipped            = []

    for sym_idx, symbol in enumerate(SYMBOLS, 1):
        t.write(f'[{sym_idx:>2}/{len(SYMBOLS)}]  {symbol:<16} ')
        t.flush()

        signals, status = scan_symbol(symbol, start_ts, end_ts)

        if status == 'NOT LISTED':
            t.write('SKIPPED (not on Binance)\n')
            skipped.append((symbol, 'NOT LISTED'))
            continue
        if signals is None:
            t.write(f'SKIPPED ({status})\n')
            skipped.append((symbol, status))
            continue
        if status == 'NOT ENOUGH DATA':
            t.write('SKIPPED (not enough candles)\n')
            skipped.append((symbol, 'NOT ENOUGH DATA'))
            continue

        wins    = sum(1 for s in signals if s['outcome'] == 'WIN')
        losses  = sum(1 for s in signals if s['outcome'] == 'LOSS')
        ongoing = sum(1 for s in signals if s['outcome'] == 'ONGOING')
        closed  = wins + losses
        wr      = f'{wins/closed*100:.1f}%' if closed > 0 else 'n/a'

        t.write(f'{len(signals):>3} signals  [W:{wins} L:{losses} Ong:{ongoing} WR:{wr}]\n')
        all_symbol_results.append((symbol, signals))

        # Small delay to avoid hammering Binance API
        time.sleep(0.1)

    t.write(f'\n{len(all_symbol_results)} symbols scanned  |  {len(skipped)} skipped\n')
    t.write('Writing report...\n')
    fname = generate_txt(all_symbol_results, skipped)
    t.write(f'Done → {fname}\n\n')


if __name__ == '__main__':
    main()