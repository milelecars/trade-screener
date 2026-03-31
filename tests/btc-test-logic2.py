"""
BTC/USDT BACKTEST — EMA44 Rejection SHORT Strategy
===================================================
Binance  |  15-minute candles  |  01 Sep 2025 → 28 Feb 2026

ENTRY CONDITIONS (ALL 8 must be true on signal candle):
  C1  Price touched EMA44 : High >= EMA44 × 0.9975  (within 0.25% of EMA44)
  C2  Candle closed below : Close < EMA44            (confirms rejection)
  C3  EMA44 slope neg     : EMA44[i] − EMA44[i-3] < 0  (downtrend)
  C4  RSI14 neutral zone  : 35 < RSI14 < 65          (no extremes)
  C5  Upper wick rejects  : Upper Wick > Body × 0.20 (rejection structure)
  C6  EMA9 < EMA21        (short-term trend aligned short)
  C7  Close < EMA200      (macro trend aligned short)
  C8  ATR% > 0.15%        ATR14 / Close > 0.0015

NOTE on Entry Timing:
  The doc says "next candle open after signal close" for live trading,
  but section 3.1 explicitly states "Entry: At close of signal candle
  (simulating next-candle market order)".
  → Backtest uses CLOSE of signal candle as entry price.

TRADE MANAGEMENT:
  SL      : 1.0% above entry  (entry × 1.010)
  TP      : 2.0% below entry  (entry × 0.980)
  Timeout : exit at close of candle 16 after signal candle (4 hours)
            SL checked before TP each candle (worst-case fill)
  Max 1 concurrent trade — new signals skipped while trade is open
  Max 5 consecutive losses → 24h pause

RISK MANAGEMENT:
  ATR% < 0.15% → skip signal
  First 3 candles of each session → skip (gap risk)
  Sessions: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC (6 × 4h sessions)

Output: btc_ema44_rejection_report.txt
"""

import requests
from datetime import datetime, timezone
import sys
import time
import math

# ============================================================================
# PARAMETERS
# ============================================================================

SYMBOL        = 'BTCUSDT'
INTERVAL      = '15m'

EMA_FAST      = 9
EMA_MID       = 21
EMA_SIGNAL    = 44
EMA_TREND     = 200
RSI_PERIOD    = 14
ATR_PERIOD    = 14

EMA44_TOUCH_PCT = 0.9975   # C1: High >= EMA44 × 0.9975
EMA44_SLOPE_LB  = 3        # C3: lookback candles
RSI_LOW         = 35.0     # C4
RSI_HIGH        = 65.0     # C4
WICK_BODY_RATIO = 0.20     # C5: upper wick > body × 0.20
ATR_MIN_PCT     = 0.00040   # C8: ATR14/Close > 0.15%

SL_PERCENT    = 1.0        # 1.0% above entry
TP_PERCENT    = 2.0        # 2.0% below entry
MAX_HOLD      = 16         # candles (4 hours)

CONSEC_LOSS_MAX   = 5
CONSEC_LOSS_PAUSE = 24 * 60 * 60 * 1000   # 24h in ms

SESSION_SKIP  = 3          # skip first 3 candles of each 4h session
SESSION_OPENS = {0, 4, 8, 12, 16, 20}    # UTC hours

WARMUP_BARS   = 250        # enough for EMA200 + ATR + RSI

PERIOD = {
    'label':    '01 Sep 2025 -> 28 Feb 2026',
    'start_dt': datetime(2025, 9,  1,  0,  0,  0, tzinfo=timezone.utc),
    'end_dt':   datetime(2026, 2, 28, 23, 59, 59, tzinfo=timezone.utc),
}

# ============================================================================
# INDICATORS
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


def calc_rsi_series(closes, period):
    """
    Wilder RSI: initial avg gain/loss = SMA of first `period` changes,
    then Wilder-smoothed (RMA).
    """
    n = len(closes)
    rsi = [None] * n
    if n < period + 1:
        return rsi

    gains  = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        chg = closes[i] - closes[i - 1]
        if chg > 0:
            gains[i]  = chg
        else:
            losses[i] = -chg

    # Seed: average of first `period` changes (indices 1..period)
    avg_gain = sum(gains[1:period + 1])  / period
    avg_loss = sum(losses[1:period + 1]) / period

    seed_i = period   # index of first RSI value
    if avg_loss == 0:
        rsi[seed_i] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[seed_i] = 100.0 - 100.0 / (1.0 + rs)

    for i in range(seed_i + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i])  / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)

    return rsi


def calc_atr_series(highs, lows, closes, period):
    """
    Wilder ATR: seed = SMA of first `period` true ranges.
    """
    n = len(closes)
    atr = [None] * n
    if n < period + 1:
        return atr

    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(
            highs[i]  - lows[i],
            abs(highs[i]  - closes[i - 1]),
            abs(lows[i]   - closes[i - 1]),
        )

    # Seed
    atr[period] = sum(tr[1:period + 1]) / period
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr

# ============================================================================
# SESSION FILTER
# ============================================================================

def is_session_skip(ts_ms):
    """
    Returns True if this candle falls within the first SESSION_SKIP candles
    of a 4-hour session boundary (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC).
    Each 15m candle = 15 min. First 3 candles = first 45 min of the session.
    """
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    if dt.hour in SESSION_OPENS and dt.minute < SESSION_SKIP * 15:
        return True
    return False

# ============================================================================
# OUTCOME CHECKER — uses pre-loaded candle arrays
# ============================================================================

def resolve_trade(signal_idx, entry, sl, tp, all_candles,
                  closes_all, highs_all, lows_all, times_all):
    """
    Scans forward from signal_idx+1 up to MAX_HOLD candles.
    SL checked before TP each candle (worst-case).
    Returns (outcome, exit_price, exit_ts, exit_candle_offset)
      outcome: 'WIN' | 'LOSS' | 'TIMEOUT'
    """
    n = len(all_candles)
    for offset in range(1, MAX_HOLD + 1):
        j = signal_idx + offset
        if j >= n:
            break
        h = highs_all[j]
        l = lows_all[j]
        c = closes_all[j]

        # SL checked first (worst-case fill order per spec)
        if h >= sl:
            return 'LOSS',    sl,              times_all[j], offset
        if l <= tp:
            return 'WIN',     tp,              times_all[j], offset

    # Timeout — exit at close of candle MAX_HOLD
    exit_j = signal_idx + MAX_HOLD
    if exit_j < n:
        exit_price = closes_all[exit_j]
        exit_ts    = times_all[exit_j]
    else:
        exit_j     = n - 1
        exit_price = closes_all[exit_j]
        exit_ts    = times_all[exit_j]

    # Timeout PnL: positive if price fell (SHORT), negative if rose
    return 'TIMEOUT', exit_price, exit_ts, MAX_HOLD

# ============================================================================
# SCANNER
# ============================================================================

def scan_period(start_ts, end_ts):
    warmup_ms     = WARMUP_BARS * 15 * 60 * 1000
    fetch_start   = start_ts - warmup_ms
    all_candles   = []
    current_start = fetch_start

    sys.stdout.write('  Fetching candles')
    sys.stdout.flush()

    while current_start < end_ts:
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={'symbol': SYMBOL, 'interval': INTERVAL,
                        'startTime': current_start, 'endTime': end_ts,
                        'limit': 1000},
                timeout=15
            )
        except Exception as e:
            sys.stdout.write(f'\n  FETCH ERROR: {e}\n')
            return None
        if resp.status_code != 200:
            sys.stdout.write(f'\n  HTTP {resp.status_code}\n')
            return None
        batch = resp.json()
        if not isinstance(batch, list) or len(batch) == 0:
            break
        all_candles.extend(batch)
        current_start = batch[-1][0] + 1
        if len(batch) < 1000:
            break
        sys.stdout.write('.')
        sys.stdout.flush()

    sys.stdout.write(f' {len(all_candles)} candles\n')
    sys.stdout.flush()

    if len(all_candles) < WARMUP_BARS + MAX_HOLD + 2:
        sys.stdout.write('  Not enough candles\n')
        return None

    closes_all = [float(c[4]) for c in all_candles]
    opens_all  = [float(c[1]) for c in all_candles]
    highs_all  = [float(c[2]) for c in all_candles]
    lows_all   = [float(c[3]) for c in all_candles]
    times_all  = [int(c[0])   for c in all_candles]

    sys.stdout.write('  Computing indicators...')
    sys.stdout.flush()

    ema9_all   = calc_ema_series(closes_all, EMA_FAST)
    ema21_all  = calc_ema_series(closes_all, EMA_MID)
    ema44_all  = calc_ema_series(closes_all, EMA_SIGNAL)
    ema200_all = calc_ema_series(closes_all, EMA_TREND)
    rsi_all    = calc_rsi_series(closes_all, RSI_PERIOD)
    atr_all    = calc_atr_series(highs_all, lows_all, closes_all, ATR_PERIOD)

    sys.stdout.write(' done\n')
    sys.stdout.flush()

    signals          = []
    trade_exit_idx   = -1   # candle index at which current trade exits
                            # loop blocks i <= trade_exit_idx
    consec_loss      = 0
    pause_until      = 0

    for i in range(WARMUP_BARS, len(all_candles) - MAX_HOLD - 1):
        candle_ts = times_all[i]
        if not (start_ts <= candle_ts <= end_ts):
            continue

        # Consecutive loss pause
        if candle_ts < pause_until:
            continue

        # No new signal while a trade is still open —
        # block until the loop index moves past the exit candle
        if i <= trade_exit_idx:
            continue

        # All indicators must be valid
        if None in (ema9_all[i], ema21_all[i], ema200_all[i], rsi_all[i], atr_all[i]):
            continue
        if i < EMA44_SLOPE_LB or ema44_all[i] is None or ema44_all[i - EMA44_SLOPE_LB] is None:
            continue

        c_close = closes_all[i]
        c_open  = opens_all[i]
        c_high  = highs_all[i]
        c_low   = lows_all[i]
        ema44   = ema44_all[i]
        ema9    = ema9_all[i]
        ema21   = ema21_all[i]
        ema200  = ema200_all[i]
        rsi     = rsi_all[i]
        atr     = atr_all[i]
        atr_pct = atr / c_close if c_close > 0 else 0

        # ── Session filter (first 3 candles of each 4h session) ──────────────
        if is_session_skip(candle_ts):
            continue

        # ── C1: High touched EMA44 (within 0.25%) ────────────────────────────
        if c_high < ema44 * EMA44_TOUCH_PCT:
            continue

        # ── C2: Close below EMA44 ────────────────────────────────────────────
        if c_close >= ema44:
            continue

        # ── C3: EMA44 slope negative (3-candle lookback) ─────────────────────
        if ema44 - ema44_all[i - EMA44_SLOPE_LB] >= 0:
            continue

        # ── C4: RSI in neutral zone (35–65) ──────────────────────────────────
        if not (RSI_LOW < rsi < RSI_HIGH):
            continue

        # ── C5: Upper wick > Body × 0.20 ─────────────────────────────────────
        body_top    = max(c_open, c_close)
        body_bottom = min(c_open, c_close)
        body_size   = body_top - body_bottom
        upper_wick  = c_high - body_top
        if upper_wick <= body_size * WICK_BODY_RATIO:
            continue

        # ── C6: EMA9 < EMA21 ─────────────────────────────────────────────────
        if ema9 >= ema21:
            continue

        # ── C7: Close < EMA200 ───────────────────────────────────────────────
        if c_close >= ema200:
            continue

        # ── C8: ATR% > 0.15% ─────────────────────────────────────────────────
        if atr_pct <= ATR_MIN_PCT:
            continue

        # ── All conditions met — enter at CLOSE of this candle ───────────────
        entry = c_close
        sl    = entry * (1 + SL_PERCENT / 100)
        tp    = entry * (1 - TP_PERCENT / 100)

        outcome, exit_price, exit_ts, hold_candles = resolve_trade(
            i, entry, sl, tp,
            all_candles, closes_all, highs_all, lows_all, times_all
        )

        # PnL for SHORT: positive when price falls
        if outcome == 'WIN':
            pnl_pct = TP_PERCENT
        elif outcome == 'LOSS':
            pnl_pct = -SL_PERCENT
        else:  # TIMEOUT
            pnl_pct = (entry - exit_price) / entry * 100

        ema44_slope = ema44 - ema44_all[i - EMA44_SLOPE_LB]

        signals.append({
            'signal_ts':     candle_ts,
            'signal_time':   datetime.fromtimestamp(candle_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            'entry_ts':      candle_ts,    # entry at close of signal candle
            'entry_time':    datetime.fromtimestamp(candle_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            'exit_ts':       exit_ts,
            'exit_time':     datetime.fromtimestamp(exit_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            'hold_candles':  hold_candles,
            'entry':         entry,
            'sl':            sl,
            'tp':            tp,
            'exit_price':    exit_price,
            'pnl_pct':       pnl_pct,
            # indicators at signal candle
            'ema9':          ema9,
            'ema21':         ema21,
            'ema44':         ema44,
            'ema200':        ema200,
            'ema44_slope':   ema44_slope,
            'rsi':           rsi,
            'atr':           atr,
            'atr_pct':       atr_pct * 100,
            'upper_wick':    upper_wick,
            'body_size':     body_size,
            'candle_high':   c_high,
            'outcome':       outcome,
        })

        # Block all candles up to and including the exit candle
        trade_exit_idx = i + hold_candles

        # Update consecutive loss tracker
        if outcome == 'LOSS':
            consec_loss += 1
            if consec_loss >= CONSEC_LOSS_MAX:
                pause_until = exit_ts + CONSEC_LOSS_PAUSE
                consec_loss = 0
                sys.stdout.write(f'  [!] {CONSEC_LOSS_MAX} consecutive losses at '
                                 f'{signals[-1]["exit_time"]} → 24h pause\n')
        else:
            consec_loss = 0

    return signals

# ============================================================================
# TEXT REPORT
# ============================================================================

def generate_txt(signals, filename='btc_ema44_rejection_report.txt'):
    W   = 80
    gen = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    with open(filename, 'w', encoding='utf-8') as f:

        def p(line=''):
            print(line, file=f)

        def div(char='='):
            p(char * W)

        # ── Header ────────────────────────────────────────────────────────────
        div('=')
        p('BTC/USDT — EMA44 REJECTION SHORT STRATEGY  |  BACKTEST REPORT')
        p('15-minute candles  |  Binance  |  SHORT only')
        p(f'Period    : {PERIOD["label"]}')
        p(f'Generated : {gen}')
        p(f'SL: +{SL_PERCENT}%  |  TP: -{TP_PERCENT}%  |  R:R 1:2  |  Max hold: {MAX_HOLD} candles (4h)')
        p()
        p('ENTRY CONDITIONS (all 8 must be true on signal candle):')
        p(f'  C1  High >= EMA44 × {EMA44_TOUCH_PCT}  (touched within 0.25%)')
        p(f'  C2  Close < EMA44                   (rejection confirmed)')
        p(f'  C3  EMA44[i] − EMA44[i-3] < 0       (slope negative)')
        p(f'  C4  {RSI_LOW} < RSI14 < {RSI_HIGH}                  (neutral zone)')
        p(f'  C5  Upper wick > Body × {WICK_BODY_RATIO}          (rejection candle)')
        p(f'  C6  EMA9 < EMA21                    (short-term bearish)')
        p(f'  C7  Close < EMA200                  (macro bearish)')
        p(f'  C8  ATR14/Close > {ATR_MIN_PCT*100:.2f}%              (sufficient volatility)')
        p()
        p('TRADE RULES:')
        p(f'  Entry     : Close of signal candle')
        p(f'  SL        : Entry × {1 + SL_PERCENT/100:.3f}  (+{SL_PERCENT}%)')
        p(f'  TP        : Entry × {1 - TP_PERCENT/100:.3f}  (−{TP_PERCENT}%)')
        p(f'  Timeout   : Exit at close of candle {MAX_HOLD} if SL/TP not hit')
        p(f'  Concurrent: Max 1 trade — new signals blocked while open')
        p(f'  Pause     : {CONSEC_LOSS_MAX} consecutive losses → 24h pause')
        p(f'  Session   : Skip first {SESSION_SKIP} candles of each 4h session')
        div('=')
        p()

        if not signals:
            p('  No signals found in this period.')
            div('=')
            return filename

        # ── Statistics ────────────────────────────────────────────────────────
        wins     = [s for s in signals if s['outcome'] == 'WIN']
        losses   = [s for s in signals if s['outcome'] == 'LOSS']
        timeouts = [s for s in signals if s['outcome'] == 'TIMEOUT']
        total    = len(signals)
        closed   = len(wins) + len(losses)   # TP or SL hit
        wr       = len(wins) / total * 100 if total > 0 else 0
        wr_cl    = len(wins) / closed * 100 if closed > 0 else 0

        all_pnl   = sum(s['pnl_pct'] for s in signals)
        avg_pnl   = all_pnl / total if total > 0 else 0
        avg_win   = sum(s['pnl_pct'] for s in wins)   / len(wins)   if wins   else 0
        avg_loss  = sum(s['pnl_pct'] for s in losses) / len(losses) if losses else 0
        avg_tout  = sum(s['pnl_pct'] for s in timeouts) / len(timeouts) if timeouts else 0

        t_wins    = sum(1 for s in timeouts if s['pnl_pct'] > 0)
        t_losses  = sum(1 for s in timeouts if s['pnl_pct'] < 0)
        t_flat    = sum(1 for s in timeouts if s['pnl_pct'] == 0)

        hold_avg  = sum(s['hold_candles'] for s in signals) / total if total > 0 else 0

        atr_vals  = [s['atr_pct'] for s in signals]
        rsi_vals  = [s['rsi']     for s in signals]

        verdict = (
            'EXCELLENT  (>60%)'   if wr >= 60 else
            'GOOD       (>50%)'   if wr >= 50 else
            'MARGINAL   (40-50%)' if wr >= 40 else
            'WEAK       (25-40%)' if wr >= 25 else
            'POOR       (<25%)'
        )

        div('#')
        p('  PERFORMANCE SUMMARY')
        div('#')
        p()
        p(f'  Total signals        : {total}')
        p(f'  Wins  (TP hit)       : {len(wins)}')
        p(f'  Losses (SL hit)      : {len(losses)}')
        p(f'  Timeouts (4h exit)   : {len(timeouts)}   '
          f'[+:{t_wins}  −:{t_losses}  flat:{t_flat}]')
        p()
        p(f'  Win rate (all)       : {wr:.1f}%  ({len(wins)}/{total})')
        p(f'  Win rate (SL/TP only): {wr_cl:.1f}%  ({len(wins)}/{closed})')
        p()
        p(f'  Total PnL            : {all_pnl:+.2f}%')
        p(f'  Avg PnL per trade    : {avg_pnl:+.3f}%')
        p(f'  Avg win              : {avg_win:+.3f}%')
        p(f'  Avg loss             : {avg_loss:+.3f}%')
        p(f'  Avg timeout PnL      : {avg_tout:+.3f}%')
        p()
        p(f'  Avg hold (candles)   : {hold_avg:.1f}  ({hold_avg*15/60:.1f}h)')
        p(f'  Avg ATR% at entry    : {sum(atr_vals)/len(atr_vals):.3f}%')
        p(f'  Avg RSI at entry     : {sum(rsi_vals)/len(rsi_vals):.1f}')
        p()
        p(f'  Verdict              : {verdict}')
        div('-')
        p()

        # ── Monthly breakdown ─────────────────────────────────────────────────
        from collections import defaultdict
        monthly = defaultdict(list)
        for s in signals:
            dt  = datetime.fromtimestamp(s['entry_ts'] / 1000, tz=timezone.utc)
            key = dt.strftime('%Y-%m')
            monthly[key].append(s)

        p('  MONTHLY BREAKDOWN')
        div('-')
        p(f'  {"Month":<10}  {"Sig":>4}  {"W":>4}  {"L":>4}  {"T":>4}  {"WR%":>6}  {"PnL%":>8}')
        div('-')
        for month in sorted(monthly):
            ms   = monthly[month]
            mw   = sum(1 for s in ms if s['outcome'] == 'WIN')
            ml   = sum(1 for s in ms if s['outcome'] == 'LOSS')
            mt   = sum(1 for s in ms if s['outcome'] == 'TIMEOUT')
            mwr  = f'{mw/len(ms)*100:.1f}%'
            mpnl = f'{sum(s["pnl_pct"] for s in ms):+.2f}%'
            p(f'  {month:<10}  {len(ms):>4}  {mw:>4}  {ml:>4}  {mt:>4}  {mwr:>6}  {mpnl:>8}')
        div('-')
        p()

        # ── Signal detail ─────────────────────────────────────────────────────
        p('  SIGNALS')
        div('-')
        p()

        for idx, s in enumerate(signals, 1):
            ol   = {'WIN': '[WIN ]', 'LOSS': '[LOSS]',
                    'TIMEOUT': '[TIME]'}.get(s['outcome'], '[????]')
            pnl_str = f'{s["pnl_pct"]:+.3f}%'

            p(f'  Signal #{idx:<4} {ol}  Entry: {s["entry_time"]}  '
              f'Hold: {s["hold_candles"]} candles  PnL: {pnl_str}')
            p(f'  Indicators : EMA9={s["ema9"]:.2f}  EMA21={s["ema21"]:.2f}  '
              f'EMA44={s["ema44"]:.2f}  EMA200={s["ema200"]:.2f}')
            p(f'               slope={s["ema44_slope"]:+.2f}  RSI={s["rsi"]:.1f}  '
              f'ATR%={s["atr_pct"]:.3f}%')
            p(f'  Candle     : high={s["candle_high"]:.2f}  '
              f'wick={s["upper_wick"]:.2f}  body={s["body_size"]:.2f}  '
              f'wick/body={s["upper_wick"]/s["body_size"]:.2f}x'
              if s["body_size"] > 0 else
              f'  Candle     : high={s["candle_high"]:.2f}  wick={s["upper_wick"]:.2f}  body=0')
            p(f'  Entry      : ${s["entry"]:.2f}  '
              f'SL: ${s["sl"]:.2f}  TP: ${s["tp"]:.2f}')
            p(f'  Exit       : ${s["exit_price"]:.2f}  at {s["exit_time"]}')
            p()

        div('-')
        p()

        # ── Methodology ───────────────────────────────────────────────────────
        div('=')
        p('METHODOLOGY')
        div('=')
        p('  WIN     : TP hit (−2.0%) before SL or timeout')
        p('  LOSS    : SL hit (+1.0%) before TP or timeout')
        p('  TIMEOUT : Neither SL nor TP hit within 16 candles (4h)')
        p('            Timeout PnL = (Entry − Exit Close) / Entry × 100')
        p()
        p('  SL checked before TP on each candle (worst-case fill order)')
        p('  EMA: seeded with SMA of first N closes, k = 2/(N+1)')
        p('  RSI: Wilder RMA smoothing, seeded with SMA of first 14 changes')
        p('  ATR: Wilder RMA smoothing, seeded with SMA of first 14 true ranges')
        p('  Entry: close of signal candle (section 3.1 of spec)')
        p('  Session skip: first 3 × 15m candles of 00/04/08/12/16/20 UTC sessions')
        div('=')

    return filename

# ============================================================================
# MAIN
# ============================================================================

def main():
    t = sys.__stdout__
    t.write('\n' + '=' * 60 + '\n')
    t.write('BTC/USDT — EMA44 REJECTION SHORT STRATEGY\n')
    t.write(f'{PERIOD["label"]}  |  15m  |  SHORT only\n')
    t.write(f'SL {SL_PERCENT}% / TP {TP_PERCENT}%  |  Max hold {MAX_HOLD} candles\n')
    t.write('=' * 60 + '\n\n')

    start_ts = int(PERIOD['start_dt'].timestamp() * 1000)
    end_ts   = int(PERIOD['end_dt'].timestamp()   * 1000)
    days     = (PERIOD['end_dt'] - PERIOD['start_dt']).days

    t.write(f'  Period : {days} days\n\n')
    t.flush()

    signals = scan_period(start_ts, end_ts)

    if signals is None:
        t.write('  ERROR fetching data\n')
        return

    wins     = sum(1 for s in signals if s['outcome'] == 'WIN')
    losses   = sum(1 for s in signals if s['outcome'] == 'LOSS')
    timeouts = sum(1 for s in signals if s['outcome'] == 'TIMEOUT')
    total    = len(signals)
    wr       = f'{wins/total*100:.1f}%' if total > 0 else 'n/a'
    pnl      = sum(s['pnl_pct'] for s in signals)

    t.write(f'  {total} signals  '
            f'[WIN:{wins}  LOSS:{losses}  TIMEOUT:{timeouts}  '
            f'WR:{wr}  PnL:{pnl:+.2f}%]\n\n')

    t.write('Writing report...\n')
    fname = generate_txt(signals)
    t.write(f'Done → {fname}\n\n')


if __name__ == '__main__':
    main()