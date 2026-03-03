"""
BTC/USDT BACKTEST — Two Specific Date Ranges
=============================================
Period 1: 10 Oct 2024 -> 18 Dec 2024
Period 2: 07 Oct 2025 -> 25 Nov 2025

Output: btc_backtest_report.txt

PARAMETERS (updated):
  - RSI_SHORT_MAX   : 45 -> 55  (catches sharp drops before RSI reacts)
  - CROSS_LOOKBACK  : 4  -> 8   (catches crosses up to 2hrs ago)
  - MA44 slope      : 3 candles back  (current slope, not historical)
  - Cross logic     : 1 freshly crossed + other already on correct side of MA44
"""

import requests
import pandas as pd
from datetime import datetime, timezone
import sys
import time

# ============================================================================
# STRATEGY PARAMETERS
# ============================================================================

RSI_PERIOD         = 14
EMA_SHORT          = 9
EMA_LONG           = 26
MA_PERIOD          = 44
RSI_LONG_MIN       = 45.1
RSI_LONG_MAX       = 85
RSI_SHORT_MIN      = 10
RSI_SHORT_MAX      = 55    # expanded from 45
SL_PERCENT         = 0.5
TP_PERCENT         = 1.5
SIDEWAYS_LOOKBACK  = 20
SIDEWAYS_THRESHOLD = 0.002
CROSS_LOOKBACK     = 8     # expanded from 4
COOLDOWN_MS        = 60 * 60 * 1000   # 1 hour

SYMBOL = 'BTCUSDT'

PERIODS = [
    {
        'label':    'Period 1 -- BTC/USDT  |  27 Jan 2026 -> 26 Feb 2026',
        'start_dt': datetime(2026, 1, 27, 0, 0, 0, tzinfo=timezone.utc),
        'end_dt':   datetime(2026, 2, 26, 23, 59, 59, tzinfo=timezone.utc),
    }
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
    return float(prices.ewm(span=period, adjust=False).mean().iloc[-1])

def calculate_sma(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    return sum(closes[-period:]) / period

# ============================================================================
# LAYER 1 — SIDEWAYS FILTER
# ============================================================================

def is_trending(closes):
    if len(closes) < MA_PERIOD + SIDEWAYS_LOOKBACK:
        return False
    ma44_values = []
    for k in range(SIDEWAYS_LOOKBACK, 0, -1):
        ma44_values.append(calculate_sma(closes[:-k], MA_PERIOD))
    ma44_values.append(calculate_sma(closes, MA_PERIOD))
    ma44_range = max(ma44_values) - min(ma44_values)
    threshold  = closes[-1] * SIDEWAYS_THRESHOLD
    return ma44_range > threshold

# ============================================================================
# LAYER 2 — CROSS CONFIRMATION (relaxed)
# Passes if: (EMA9 freshly crossed AND EMA26 on correct side)
#         OR (EMA26 freshly crossed AND EMA9 on correct side)
# EMA9 is faster so it typically crosses first — EMA26 may lag.
# ============================================================================

def had_cross_above_ma44(closes):
    if len(closes) < MA_PERIOD + CROSS_LOOKBACK + 2:
        return False
    ema9_now  = calculate_ema(closes, EMA_SHORT)
    ema26_now = calculate_ema(closes, EMA_LONG)
    ma44_now  = calculate_sma(closes, MA_PERIOD)
    ema9_above  = ema9_now  > ma44_now
    ema26_above = ema26_now > ma44_now
    if not ema9_above and not ema26_above:
        return False
    ema9_crossed = ema26_crossed = False
    for k in range(1, CROSS_LOOKBACK + 1):
        cn  = closes[:-k + 1] if k > 1 else closes
        cp  = closes[:-k]
        if len(cn) < MA_PERIOD or len(cp) < MA_PERIOD:
            continue
        e9n  = calculate_ema(cn, EMA_SHORT);  e9p  = calculate_ema(cp, EMA_SHORT)
        e26n = calculate_ema(cn, EMA_LONG);   e26p = calculate_ema(cp, EMA_LONG)
        m44n = calculate_sma(cn, MA_PERIOD);  m44p = calculate_sma(cp, MA_PERIOD)
        if not ema9_crossed  and (e9p  <= m44p) and (e9n  > m44n): ema9_crossed  = True
        if not ema26_crossed and (e26p <= m44p) and (e26n > m44n): ema26_crossed = True
    return (ema9_crossed and ema26_above) or (ema26_crossed and ema9_above)

def had_cross_below_ma44(closes):
    if len(closes) < MA_PERIOD + CROSS_LOOKBACK + 2:
        return False
    ema9_now  = calculate_ema(closes, EMA_SHORT)
    ema26_now = calculate_ema(closes, EMA_LONG)
    ma44_now  = calculate_sma(closes, MA_PERIOD)
    ema9_below  = ema9_now  < ma44_now
    ema26_below = ema26_now < ma44_now
    if not ema9_below and not ema26_below:
        return False
    ema9_crossed = ema26_crossed = False
    for k in range(1, CROSS_LOOKBACK + 1):
        cn  = closes[:-k + 1] if k > 1 else closes
        cp  = closes[:-k]
        if len(cn) < MA_PERIOD or len(cp) < MA_PERIOD:
            continue
        e9n  = calculate_ema(cn, EMA_SHORT);  e9p  = calculate_ema(cp, EMA_SHORT)
        e26n = calculate_ema(cn, EMA_LONG);   e26p = calculate_ema(cp, EMA_LONG)
        m44n = calculate_sma(cn, MA_PERIOD);  m44p = calculate_sma(cp, MA_PERIOD)
        if not ema9_crossed  and (e9p  >= m44p) and (e9n  < m44n): ema9_crossed  = True
        if not ema26_crossed and (e26p >= m44p) and (e26n < m44n): ema26_crossed = True
    return (ema9_crossed and ema26_below) or (ema26_crossed and ema9_below)

# ============================================================================
# LAYER 3 — SETUP CANDLE
# ============================================================================

def check_setup_candle(closes, opens):
    if len(closes) < MA_PERIOD + SIDEWAYS_LOOKBACK + CROSS_LOOKBACK + 5:
        return None
    if not is_trending(closes):
        return None

    sc   = closes[-1]
    so   = opens[-1]
    rsi  = calculate_rsi(closes, RSI_PERIOD)
    ema9 = calculate_ema(closes, EMA_SHORT)
    ema26= calculate_ema(closes, EMA_LONG)
    ma44 = calculate_sma(closes, MA_PERIOD)

    long_setup = (
        had_cross_above_ma44(closes) and
        RSI_LONG_MIN <= rsi <= RSI_LONG_MAX and
        ema9 > ema26 and
        ema9 > ma44 and ema26 > ma44 and
        sc > so and
        sc > ema9 and sc > ema26 and sc > ma44
    )

    short_setup = (
        had_cross_below_ma44(closes) and
        RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX and
        ema9 < ema26 and
        ema9 < ma44 and ema26 < ma44 and
        sc < so and
        sc < ema9 and sc < ema26 and sc < ma44
    )

    if long_setup:  return 'LONG'
    if short_setup: return 'SHORT'
    return None

# ============================================================================
# LAYER 4 — TRIGGER CANDLE
# MA44 slope checked over last 3 candles (current direction, not historical)
# ============================================================================

def check_trigger_candle(closes, opens, direction):
    if len(closes) < MA_PERIOD + 5:
        return None
    ma44_now  = calculate_sma(closes[:-1], MA_PERIOD)   # setup candle
    ma44_3ago = calculate_sma(closes[:-4], MA_PERIOD)   # 3 candles before setup
    topen     = opens[-1]
    sopen     = opens[-2]
    if direction == 'LONG'  and ma44_now > ma44_3ago and topen > sopen: return topen
    if direction == 'SHORT' and ma44_now < ma44_3ago and topen < sopen: return topen
    return None

# ============================================================================
# OUTCOME CHECKER
# ============================================================================

def check_trade_outcome(signal_ts_ms, entry, sl, tp, stype, symbol):
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={'symbol': symbol, 'interval': '15m',
                    'startTime': signal_ts_ms,
                    'endTime':   signal_ts_ms + 48 * 3600 * 1000,
                    'limit': 200},
            timeout=10
        )
        if resp.status_code != 200: return 'UNKNOWN'
        candles = resp.json()
        if not isinstance(candles, list) or len(candles) == 0: return 'ONGOING'
        for idx, c in enumerate(candles):
            h = float(c[2]); l = float(c[3])
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
# SYMBOL SCANNER
# ============================================================================

def scan_symbol(symbol, start_ts, end_ts):
    warmup_ms     = (MA_PERIOD + SIDEWAYS_LOOKBACK + CROSS_LOOKBACK + 20) * 15 * 60 * 1000
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
        if resp.status_code != 200: return None
        batch = resp.json()
        if not isinstance(batch, list) or len(batch) == 0: break
        all_candles.extend(batch)
        current_start = batch[-1][0] + 1
        if len(batch) < 1000: break

    if len(all_candles) < MA_PERIOD + SIDEWAYS_LOOKBACK + CROSS_LOOKBACK + 10:
        return None

    closes_all = [float(c[4]) for c in all_candles]
    opens_all  = [float(c[1]) for c in all_candles]
    times_all  = [int(c[0])   for c in all_candles]

    signals           = []
    pending_direction = None
    pending_setup_i   = None
    last_signal_ts    = 0
    start_i           = MA_PERIOD + SIDEWAYS_LOOKBACK + CROSS_LOOKBACK + 5

    for i in range(start_i, len(all_candles)):
        candle_ts = times_all[i]
        in_window = (start_ts <= candle_ts <= end_ts)

        # CHECK A — Trigger
        if pending_direction is not None:
            entry = check_trigger_candle(closes_all[:i+1], opens_all[:i+1], pending_direction)
            if entry is not None and in_window:
                if candle_ts - last_signal_ts >= COOLDOWN_MS:
                    sl = entry * (1 - SL_PERCENT/100) if pending_direction == 'LONG' else entry * (1 + SL_PERCENT/100)
                    tp = entry * (1 + TP_PERCENT/100) if pending_direction == 'LONG' else entry * (1 - TP_PERCENT/100)
                    si = pending_setup_i
                    signals.append({
                        'symbol':     symbol,
                        'type':       pending_direction,
                        'setup_ts':   times_all[si],
                        'trigger_ts': candle_ts,
                        'time_str':   datetime.fromtimestamp(candle_ts/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                        'entry':      entry,
                        'sl':         sl,
                        'tp':         tp,
                        'rsi':        calculate_rsi(closes_all[:si+1], RSI_PERIOD),
                        'ema9':       calculate_ema(closes_all[:si+1], EMA_SHORT),
                        'ema26':      calculate_ema(closes_all[:si+1], EMA_LONG),
                        'ma44':       calculate_sma(closes_all[:si+1], MA_PERIOD),
                        'outcome':    check_trade_outcome(candle_ts, entry, sl, tp, pending_direction, symbol),
                    })
                    last_signal_ts = candle_ts
            pending_direction = None
            pending_setup_i   = None

        # CHECK B — Setup
        direction = check_setup_candle(closes_all[:i+1], opens_all[:i+1])
        if direction is not None:
            pending_direction = direction
            pending_setup_i   = i

    return signals

# ============================================================================
# TEXT REPORT
# ============================================================================

def generate_txt(results, filename='btc_backtest_report.txt'):
    W   = 80
    gen = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    with open(filename, 'w', encoding='utf-8') as f:

        def p(line=''):
            print(line, file=f)

        def div(char='='):
            p(char * W)

        div('=')
        p('BTC/USDT -- BACKTEST REPORT')
        p('15-minute candles  |  Binance  |  4-Layer Signal Logic')
        p(f'Generated : {gen}')
        p(f'SL: -{SL_PERCENT}%  |  TP: +{TP_PERCENT}%  |  R/R 1:3  |  Cooldown: 1h')
        p()
        p('PARAMETERS:')
        p(f'  RSI_SHORT_MAX  : {RSI_SHORT_MAX}  (expanded from 45)')
        p(f'  CROSS_LOOKBACK : {CROSS_LOOKBACK} candles  (expanded from 4)')
        p(f'  MA44 slope ref : 3 candles back  (current slope, not historical)')
        p(f'  Cross logic    : 1 freshly crossed + other already on correct side of MA44')
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
            exp     = (wr/100 * TP_PERCENT) - ((100-wr)/100 * SL_PERCENT) if closed > 0 else 0
            pnl     = (wins * TP_PERCENT) - (losses * SL_PERCENT)
            verdict = (
                'EXCELLENT  (win rate > 60%)'  if wr >= 60 else
                'GOOD       (win rate > 50%)'  if wr >= 50 else
                'MARGINAL   (win rate 40-50%)' if wr >= 40 else
                'WEAK       (win rate 25-40%)' if wr >= 25 else
                'POOR       (win rate < 25%)'
            ) if closed > 0 else 'NO CLOSED TRADES YET'

            p('  SUMMARY')
            div('-')
            p(f'  Total signals   : {total}  (Long: {longs}  Short: {shorts})')
            p(f'  Wins            : {wins}')
            p(f'  Losses          : {losses}')
            p(f'  Ongoing (<48h)  : {ongoing}')
            p(f'  Unknown         : {unknown}')
            p()
            if closed > 0:
                p(f'  Win rate        : {wr:.1f}%  ({wins}/{closed} closed trades)')
                p(f'  Expectancy      : {exp:+.3f}% per trade')
                p(f'  Total PnL       : {pnl:+.2f}%  (equal-size positions)')
                p(f'  Verdict         : {verdict}')
            else:
                p('  Win rate        : n/a  (no closed trades)')
            div('-')
            p()

            p('  SIGNALS')
            div('-')
            p()

            for idx, s in enumerate(sorted(signals, key=lambda x: x['trigger_ts']), 1):
                ol         = {'WIN':'[WIN ]','LOSS':'[LOSS]','ONGOING':'[OPEN]','UNKNOWN':'[????]'}.get(s['outcome'],'[????]')
                setup_time = datetime.fromtimestamp(s['setup_ts']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
                sl_label   = f'-{SL_PERCENT}%' if s['type'] == 'LONG' else f'+{SL_PERCENT}%'
                tp_label   = f'+{TP_PERCENT}%' if s['type'] == 'LONG' else f'-{TP_PERCENT}%'

                p(f'  Signal #{idx:<3}  {ol}  {s["type"]:<6}  {s["time_str"]}')
                p(f'  Setup candle  : {setup_time}')
                p(f'  Entry         : ${s["entry"]:.2f}')
                p(f'  Stop Loss     : ${s["sl"]:.2f}  ({sl_label})')
                p(f'  Take Profit   : ${s["tp"]:.2f}  ({tp_label})')
                p(f'  RSI           : {s["rsi"]:.2f}')
                p(f'  EMA9          : {s["ema9"]:.2f}')
                p(f'  EMA26         : {s["ema26"]:.2f}')
                p(f'  MA44          : {s["ma44"]:.2f}')
                p()

            div('-')
            p()

        div('=')
        p('METHODOLOGY')
        div('=')
        p('  WIN     : TP hit before SL within 48-hour window after entry')
        p('  LOSS    : SL hit before TP within 48-hour window after entry')
        p('  ONGOING : Neither TP nor SL hit within 48 hours')
        p('  UNKNOWN : Data unavailable')
        p('  Entry   = open of trigger candle')
        p()
        p('  SIGNAL LOGIC (4 LAYERS):')
        p(f'  Layer 1 -- Sideways filter  : MA44 range > {SIDEWAYS_THRESHOLD*100:.1f}% over {SIDEWAYS_LOOKBACK} candles')
        p(f'  Layer 2 -- Cross confirm    : 1 freshly crossed MA44 within last {CROSS_LOOKBACK} candles')
        p(f'                                + other EMA already on correct side of MA44')
        p('  Layer 3 -- Setup candle     : RSI + EMA positions + bullish/bearish + close above/below all 3 MAs')
        p('  Layer 4 -- Trigger candle   : MA44 sloping in right direction (3 candles) + open gap')
        div('=')

    return filename

# ============================================================================
# MAIN
# ============================================================================

def main():
    t = sys.__stdout__
    t.write("\n" + "=" * 60 + "\n")
    t.write("BTC/USDT BACKTEST -- Two Date Ranges\n")
    t.write("=" * 60 + "\n\n")

    results = []

    for period in PERIODS:
        t.write(f"--- {period['label']}\n")
        start_ts = int(period['start_dt'].timestamp() * 1000)
        end_ts   = int(period['end_dt'].timestamp()   * 1000)
        days     = (period['end_dt'] - period['start_dt']).days

        t.write(f"    Scanning {days} days... ")
        t.flush()

        signals = scan_symbol(SYMBOL, start_ts, end_ts)

        if signals is None:
            t.write("ERROR fetching data\n\n")
            results.append((period, []))
            continue

        wins   = sum(1 for s in signals if s['outcome'] == 'WIN')
        losses = sum(1 for s in signals if s['outcome'] == 'LOSS')
        closed = wins + losses
        wr     = f"{wins/closed*100:.1f}%" if closed > 0 else "n/a"

        t.write(f"{len(signals)} signals  [W:{wins} L:{losses} WR:{wr}]\n")
        results.append((period, signals))
        time.sleep(0.2)

    t.write("\nWriting report...\n")
    fname = generate_txt(results, 'btc_backtest_report.txt')
    t.write(f"Done -> {fname}\n\n")


if __name__ == "__main__":
    main()