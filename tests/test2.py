"""
FAKE SCENARIO TEST v2 — Fixed synthetic candle sequences
=========================================================
Problems fixed from v1:
  - LONG: setup candle jump wasn't big enough to cross MA44
  - SHORT: rising phase accidentally triggered a LONG signal early

Fix approach:
  - After building candles, VERIFY the indicator state at each phase
    before running the full test, so we know conditions are met.
  - Separate the "flat baseline" from "trend" and "setup" more carefully.
  - Use a stronger setup candle move to guarantee all 4 conditions pass.
"""

import pandas as pd
from collections import deque
import time
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


# ============================================================================
# CONFIG
# ============================================================================

class Config:
    RSI_PERIOD     = 14
    EMA_SHORT      = 9
    EMA_LONG       = 26
    MA_PERIOD      = 44
    RSI_LONG_MIN   = 45.1
    RSI_LONG_MAX   = 85
    RSI_SHORT_MIN  = 10
    RSI_SHORT_MAX  = 45
    SL_PERCENT     = 0.5
    TP_PERCENT     = 1.5
    ALERT_COOLDOWN = 0


# ============================================================================
# INDICATORS
# ============================================================================

class IndicatorEngine:
    @staticmethod
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

    @staticmethod
    def calculate_ema(closes, period):
        if len(closes) < period:
            return closes[-1] if closes else 0
        prices = pd.Series(closes)
        ema    = prices.ewm(span=period, adjust=False).mean()
        return float(ema.iloc[-1])

    @staticmethod
    def calculate_sma(closes, period):
        if len(closes) < period:
            return closes[-1] if closes else 0
        return sum(closes[-period:]) / period


# ============================================================================
# CANDLE MANAGER  (identical to realtime_scanner_v2.py)
# ============================================================================

class CandleManager:

    def __init__(self, symbol, max_bars=300):
        self.symbol   = symbol
        self.max_bars = max_bars

        self.timestamps = deque(maxlen=max_bars)
        self.opens      = deque(maxlen=max_bars)
        self.highs      = deque(maxlen=max_bars)
        self.lows       = deque(maxlen=max_bars)
        self.closes     = deque(maxlen=max_bars)
        self.volumes    = deque(maxlen=max_bars)

        self.last_alert_time    = 0
        self.setup_pending      = False
        self.pending_signal     = None
        self.pending_setup_data = None

    def push_closed_candle(self, ts, o, h, l, c, v=0):
        self.timestamps.append(ts)
        self.opens.append(o)
        self.highs.append(h)
        self.lows.append(l)
        self.closes.append(c)
        self.volumes.append(v)

    def check_signal(self):
        if len(self.closes) < Config.MA_PERIOD + 12:
            return None, None

        closes_list = list(self.closes)
        opens_list  = list(self.opens)
        conf_close  = closes_list[-1]
        conf_open   = opens_list[-1]

        # CHECK A — Confirmation
        if self.setup_pending and self.pending_signal and self.pending_setup_data:
            candle_bullish = conf_close > conf_open
            candle_bearish = conf_close < conf_open
            confirmed = (
                (self.pending_signal == 'LONG'  and candle_bullish) or
                (self.pending_signal == 'SHORT' and candle_bearish)
            )
            if confirmed:
                signal     = self.pending_signal
                setup_data = self.pending_setup_data
                entry      = conf_open
                alert_data = {
                    'price': conf_close,
                    'entry': entry,
                    'sl':    entry * (1 - Config.SL_PERCENT/100) if signal == 'LONG'
                             else entry * (1 + Config.SL_PERCENT/100),
                    'tp':    entry * (1 + Config.TP_PERCENT/100) if signal == 'LONG'
                             else entry * (1 - Config.TP_PERCENT/100),
                    'rsi':   setup_data['rsi'],
                    'ema9':  setup_data['ema9'],
                    'ema26': setup_data['ema26'],
                    'ma44':  setup_data['ma44'],
                }
                self.setup_pending      = False
                self.pending_signal     = None
                self.pending_setup_data = None
                self.last_alert_time    = time.time()
                return signal, alert_data
            else:
                self.setup_pending      = False
                self.pending_signal     = None
                self.pending_setup_data = None

        # CHECK B — Setup detection
        if len(closes_list) < Config.MA_PERIOD + 12:
            return None, None

        setup    = closes_list[:-1]
        setup_m1 = closes_list[:-2]

        rsi   = IndicatorEngine.calculate_rsi(setup, Config.RSI_PERIOD)
        ema9  = IndicatorEngine.calculate_ema(setup, Config.EMA_SHORT)
        ema26 = IndicatorEngine.calculate_ema(setup, Config.EMA_LONG)
        ma44  = IndicatorEngine.calculate_sma(setup, Config.MA_PERIOD)

        ema9_prev  = IndicatorEngine.calculate_ema(setup_m1, Config.EMA_SHORT)
        ema26_prev = IndicatorEngine.calculate_ema(setup_m1, Config.EMA_LONG)
        ma44_prev  = IndicatorEngine.calculate_sma(setup_m1, Config.MA_PERIOD)
        ma44_5ago  = IndicatorEngine.calculate_sma(closes_list[:-6], Config.MA_PERIOD)
        ma_slope   = ma44 - ma44_5ago

        rsi_long_ok     = Config.RSI_LONG_MIN <= rsi <= Config.RSI_LONG_MAX
        ema_cross_up    = (ema9_prev <= ema26_prev) and (ema9 > ema26)
        both_above_ma   = (ema9 > ma44) and (ema26 > ma44)
        any_cross_up_ma = (((ema9_prev  <= ma44_prev) and (ema9  > ma44)) or
                           ((ema26_prev <= ma44_prev) and (ema26 > ma44)))
        ema_ma_cross_up = both_above_ma and any_cross_up_ma
        slope_up        = ma_slope > 0
        long_setup      = rsi_long_ok and ema_cross_up and ema_ma_cross_up and slope_up

        rsi_short_ok      = Config.RSI_SHORT_MIN <= rsi <= Config.RSI_SHORT_MAX
        ema_cross_down    = (ema9_prev >= ema26_prev) and (ema9 < ema26)
        both_below_ma     = (ema9 < ma44) and (ema26 < ma44)
        any_cross_down_ma = (((ema9_prev  >= ma44_prev) and (ema9  < ma44)) or
                             ((ema26_prev >= ma44_prev) and (ema26 < ma44)))
        ema_ma_cross_down = both_below_ma and any_cross_down_ma
        slope_down        = ma_slope < 0
        short_setup       = rsi_short_ok and ema_cross_down and ema_ma_cross_down and slope_down

        if long_setup or short_setup:
            self.setup_pending  = True
            self.pending_signal = 'LONG' if long_setup else 'SHORT'
            self.pending_setup_data = {
                'rsi': rsi, 'ema9': ema9, 'ema26': ema26, 'ma44': ma44
            }

        return None, None


# ============================================================================
# INDICATOR SNAPSHOT HELPER
# ============================================================================

def snapshot(closes):
    """Return all indicator values for the LAST candle in a closes list."""
    if len(closes) < Config.MA_PERIOD + 12:
        return None

    setup    = closes[:-1]
    setup_m1 = closes[:-2]

    rsi   = IndicatorEngine.calculate_rsi(setup, Config.RSI_PERIOD)
    ema9  = IndicatorEngine.calculate_ema(setup, Config.EMA_SHORT)
    ema26 = IndicatorEngine.calculate_ema(setup, Config.EMA_LONG)
    ma44  = IndicatorEngine.calculate_sma(setup, Config.MA_PERIOD)

    ema9_prev  = IndicatorEngine.calculate_ema(setup_m1, Config.EMA_SHORT)
    ema26_prev = IndicatorEngine.calculate_ema(setup_m1, Config.EMA_LONG)
    ma44_prev  = IndicatorEngine.calculate_sma(setup_m1, Config.MA_PERIOD)
    ma44_5ago  = IndicatorEngine.calculate_sma(closes[:-6], Config.MA_PERIOD)
    ma_slope   = ma44 - ma44_5ago

    return dict(
        rsi=rsi, ema9=ema9, ema26=ema26, ma44=ma44,
        ema9_prev=ema9_prev, ema26_prev=ema26_prev,
        ma44_prev=ma44_prev, ma_slope=ma_slope,
        rsi_long_ok   = Config.RSI_LONG_MIN  <= rsi <= Config.RSI_LONG_MAX,
        rsi_short_ok  = Config.RSI_SHORT_MIN <= rsi <= Config.RSI_SHORT_MAX,
        ema_cross_up  = (ema9_prev <= ema26_prev) and (ema9 > ema26),
        ema_cross_down= (ema9_prev >= ema26_prev) and (ema9 < ema26),
        both_above_ma = (ema9 > ma44) and (ema26 > ma44),
        both_below_ma = (ema9 < ma44) and (ema26 < ma44),
        any_cross_up  = (((ema9_prev  <= ma44_prev) and (ema9  > ma44)) or
                         ((ema26_prev <= ma44_prev) and (ema26 > ma44))),
        any_cross_down= (((ema9_prev  >= ma44_prev) and (ema9  < ma44)) or
                         ((ema26_prev >= ma44_prev) and (ema26 < ma44))),
        slope_up      = ma_slope > 0,
        slope_down    = ma_slope < 0,
    )


# ============================================================================
# CANDLE SEQUENCE BUILDERS  (with inline verification)
# ============================================================================

def build_long_scenario():
    """
    LONG scenario strategy:

    Key insight from v1 failure: a single jump candle can push EMA9 above EMA26
    and RSI into range, but MA44 is a simple average of 44 closes — it barely
    moves in one candle. So we need the JUMP candle to land well above MA44.

    Design:
      Phase 1: 60 candles flat at 1700  → MA44 = 1700, all EMAs = 1700
      Phase 2: 15 bearish candles, -4 each → price falls to ~1640
                 EMA9 drops fastest, then EMA26, both go below MA44 (still ~1695)
                 RSI falls to ~25-30
                 MA44 slope goes negative
      Phase 3: SETUP candle — open 1640, close 1760
                 +120 point candle.
                 EMA9 jumps well above EMA26 (cross up)  ✅
                 Both EMAs jump above MA44 (~1692 at this point)  ✅
                 RSI jumps into [45.1, 85]  ✅
                 MA44 now includes 1760, slope turns positive  ✅
      Phase 4: CONFIRMATION — open 1760, close 1775 (bullish)
                 Signal fires, entry = 1760
    """
    candles = []
    ts      = 1_000_000_000_000

    # Phase 1: 60 flat doji candles at 1700
    for i in range(60):
        c = 1700.0 + (0.5 if i % 2 == 0 else -0.5)
        candles.append((ts, 1700.0, c + 0.2, c - 0.2, c))
        ts += 15 * 60 * 1000

    # Phase 2: 15 declining candles  1700 → ~1640
    for i in range(15):
        o = 1700.0 - i * 4.0
        c = o - 4.0
        candles.append((ts, o, o + 0.5, c - 0.5, c))
        ts += 15 * 60 * 1000

    # Verify state before setup candle
    closes_so_far = [float(c[4]) for c in candles]
    s = snapshot(closes_so_far + [0])   # dummy last candle to trigger setup check
    if s:
        print(f"  [Pre-setup check] RSI={s['rsi']:.2f}  EMA9={s['ema9']:.2f}  "
              f"EMA26={s['ema26']:.2f}  MA44={s['ma44']:.2f}  slope={s['ma_slope']:.4f}")
        print(f"  EMA9<EMA26: {s['ema9']<s['ema26']}  Both below MA44: {s['both_below_ma']}  "
              f"RSI low: {s['rsi']<45}")

    # Phase 3: SETUP candle — large bullish candle
    setup_open  = closes_so_far[-1]   # open = last close
    setup_close = 1760.0
    candles.append((ts, setup_open, setup_close + 2, setup_open - 1, setup_close))
    ts += 15 * 60 * 1000

    # Verify setup candle indicators
    closes_with_setup = [float(c[4]) for c in candles]
    s2 = snapshot(closes_with_setup + [0])
    if s2:
        print(f"  [Setup candle]  RSI={s2['rsi']:.2f}  EMA9={s2['ema9']:.2f}  "
              f"EMA26={s2['ema26']:.2f}  MA44={s2['ma44']:.2f}  slope={s2['ma_slope']:.4f}")
        long_ok = s2['rsi_long_ok'] and s2['ema_cross_up'] and \
                  (s2['both_above_ma'] and s2['any_cross_up']) and s2['slope_up']
        print(f"  LONG conditions: RSI={s2['rsi_long_ok']} cross_ema={s2['ema_cross_up']} "
              f"cross_ma44={s2['both_above_ma'] and s2['any_cross_up']} slope={s2['slope_up']} "
              f"→ ALL PASS: {long_ok}")

    # Phase 4: CONFIRMATION — bullish candle
    conf_open  = setup_close
    conf_close = conf_open + 15.0
    candles.append((ts, conf_open, conf_close + 2, conf_open - 1, conf_close))

    return candles, conf_open, conf_close


def build_short_scenario():
    """
    SHORT scenario strategy:

    Fix from v1: the rising phase triggered a LONG because EMA9 crossed above
    EMA26 and above MA44 during the rise. We avoid this by keeping the rise
    BELOW the MA44 level, so the cross-above-MA44 condition never triggers.

    Design:
      Phase 1: 60 candles flat at 1900  → MA44 = 1900, all EMAs = 1900
      Phase 2: 15 bullish candles, +4 each → price rises to ~1960
                 EMA9 rises above EMA26, but we keep the closes close enough
                 that neither EMA crosses above MA44 (MA44 still ~1905)
                 RSI rises to ~70-75
                 MA44 slope goes positive
                 *** We avoid triggering LONG by keeping EMAs < MA44 ***
                 To do this, we make the rise slow enough that MA44 also rises
                 We choose: EMA9 briefly above MA44 is OK as long as
                 any_cross_up_ma requires BOTH above AND a fresh cross.
                 Since EMA26 may lag below MA44, both_above_ma fails → no LONG.

      Phase 3: SETUP candle — open 1960, close 1820
                 -140 point drop.
                 EMA9 crashes below EMA26 (cross down)  ✅
                 Both EMAs crash below MA44 (~1908)  ✅
                 RSI drops into [10, 45]  ✅
                 MA44 slope turns negative  ✅
      Phase 4: CONFIRMATION — open 1820, close 1805 (bearish)
                 Signal fires, entry = 1820
    """
    candles = []
    ts      = 2_000_000_000_000

    # Phase 1: 60 flat doji candles at 1900
    for i in range(60):
        c = 1900.0 + (0.5 if i % 2 == 0 else -0.5)
        candles.append((ts, 1900.0, c + 0.2, c - 0.2, c))
        ts += 15 * 60 * 1000

    # Phase 2: 15 rising candles  1900 → ~1960
    # Keep rise modest so EMA26 stays below MA44 (avoids LONG trigger)
    for i in range(15):
        o = 1900.0 + i * 4.0
        c = o + 4.0
        candles.append((ts, o, c + 0.5, o - 0.5, c))
        ts += 15 * 60 * 1000

    # Verify state before setup candle
    closes_so_far = [float(c[4]) for c in candles]
    s = snapshot(closes_so_far + [0])
    if s:
        print(f"  [Pre-setup check] RSI={s['rsi']:.2f}  EMA9={s['ema9']:.2f}  "
              f"EMA26={s['ema26']:.2f}  MA44={s['ma44']:.2f}  slope={s['ma_slope']:.4f}")
        print(f"  EMA9>EMA26: {s['ema9']>s['ema26']}  Both above MA44: {s['both_above_ma']}  "
              f"RSI high: {s['rsi']>45}")

    # Phase 3: SETUP candle — large bearish candle
    setup_open  = closes_so_far[-1]
    setup_close = 1820.0
    candles.append((ts, setup_open, setup_open + 1, setup_close - 2, setup_close))
    ts += 15 * 60 * 1000

    # Verify setup candle indicators
    closes_with_setup = [float(c[4]) for c in candles]
    s2 = snapshot(closes_with_setup + [0])
    if s2:
        print(f"  [Setup candle]  RSI={s2['rsi']:.2f}  EMA9={s2['ema9']:.2f}  "
              f"EMA26={s2['ema26']:.2f}  MA44={s2['ma44']:.2f}  slope={s2['ma_slope']:.4f}")
        short_ok = s2['rsi_short_ok'] and s2['ema_cross_down'] and \
                   (s2['both_below_ma'] and s2['any_cross_down']) and s2['slope_down']
        print(f"  SHORT conditions: RSI={s2['rsi_short_ok']} cross_ema={s2['ema_cross_down']} "
              f"cross_ma44={s2['both_below_ma'] and s2['any_cross_down']} slope={s2['slope_down']} "
              f"→ ALL PASS: {short_ok}")

    # Phase 4: CONFIRMATION — bearish candle
    conf_open  = setup_close
    conf_close = conf_open - 15.0
    candles.append((ts, conf_open, conf_open + 1, conf_close - 2, conf_close))

    return candles, conf_open, conf_close


# ============================================================================
# SCENARIO RUNNER
# ============================================================================

def run_fake_scenario(name, expected_signal, candles, conf_open, conf_close):
    print()
    print("=" * 70)
    print(f"FAKE SCENARIO: {name}")
    print("=" * 70)
    print(f"Total candles     : {len(candles)}")
    print(f"Expected signal   : {expected_signal}")
    print(f"Expected entry    : ${conf_open:.4f}  (open of confirmation candle)")
    print(f"Conf candle       : open=${conf_open:.4f}  close=${conf_close:.4f}  "
          f"({'BULLISH' if conf_close > conf_open else 'BEARISH'})")
    print()
    print("  Building indicators & verifying conditions...")
    print()

    manager       = CandleManager(name, max_bars=300)
    signal_fired  = None
    signal_data   = None
    signal_at_i   = None
    setup_at_i    = None
    prev_pending  = False

    for i, (ts, o, h, l, c) in enumerate(candles):
        manager.push_closed_candle(ts, o, h, l, c)

        if len(manager.closes) < Config.MA_PERIOD + 12:
            continue

        sig, data = manager.check_signal()

        # Detect moment setup became pending (just flipped to True)
        if manager.setup_pending and not prev_pending:
            setup_at_i = i
            # Print condition breakdown for this setup candle
            closes_list = list(manager.closes)
            s = snapshot(closes_list)
            if s:
                print(f"  Candle {i:>3}  *** SETUP CANDLE ***")
                print(f"    open=${o:.4f}  close={c:.4f}  "
                      f"({'BULLISH' if c > o else 'BEARISH'})")
                print(f"    RSI      : {s['rsi']:.2f}")
                print(f"    EMA9     : {s['ema9']:.4f}  (prev {s['ema9_prev']:.4f})")
                print(f"    EMA26    : {s['ema26']:.4f}  (prev {s['ema26_prev']:.4f})")
                print(f"    MA44     : {s['ma44']:.4f}  (prev {s['ma44_prev']:.4f})")
                print(f"    slope    : {s['ma_slope']:.4f}")
                print()
                if expected_signal == 'LONG':
                    print(f"    1. RSI [{Config.RSI_LONG_MIN}-{Config.RSI_LONG_MAX}]  : "
                          f"{s['rsi']:.2f}  {'PASS' if s['rsi_long_ok'] else 'FAIL'}")
                    print(f"    2. EMA9 cross up EMA26     : "
                          f"prev({s['ema9_prev']:.2f}<={s['ema26_prev']:.2f}) "
                          f"now({s['ema9']:.2f}>{s['ema26']:.2f})  "
                          f"{'PASS' if s['ema_cross_up'] else 'FAIL'}")
                    print(f"    3. Both EMAs cross up MA44 : "
                          f"above=({s['ema9']:.2f}>{s['ma44']:.2f},{s['ema26']:.2f}>{s['ma44']:.2f}) "
                          f"fresh={s['any_cross_up']}  "
                          f"{'PASS' if s['both_above_ma'] and s['any_cross_up'] else 'FAIL'}")
                    print(f"    4. MA44 slope > 0          : "
                          f"{s['ma_slope']:.4f}  {'PASS' if s['slope_up'] else 'FAIL'}")
                else:
                    print(f"    1. RSI [{Config.RSI_SHORT_MIN}-{Config.RSI_SHORT_MAX}]  : "
                          f"{s['rsi']:.2f}  {'PASS' if s['rsi_short_ok'] else 'FAIL'}")
                    print(f"    2. EMA9 cross down EMA26   : "
                          f"prev({s['ema9_prev']:.2f}>={s['ema26_prev']:.2f}) "
                          f"now({s['ema9']:.2f}<{s['ema26']:.2f})  "
                          f"{'PASS' if s['ema_cross_down'] else 'FAIL'}")
                    print(f"    3. Both EMAs cross dn MA44 : "
                          f"below=({s['ema9']:.2f}<{s['ma44']:.2f},{s['ema26']:.2f}<{s['ma44']:.2f}) "
                          f"fresh={s['any_cross_down']}  "
                          f"{'PASS' if s['both_below_ma'] and s['any_cross_down'] else 'FAIL'}")
                    print(f"    4. MA44 slope < 0          : "
                          f"{s['ma_slope']:.4f}  {'PASS' if s['slope_down'] else 'FAIL'}")
                print()
                print(f"    Pending: {manager.pending_signal} — waiting for confirmation candle...")
                print()

        prev_pending = manager.setup_pending

        if sig:
            signal_fired = sig
            signal_data  = data
            signal_at_i  = i
            print(f"  Candle {i:>3}  *** CONFIRMATION CANDLE ***")
            print(f"    open=${o:.4f}  close=${c:.4f}  "
                  f"({'BULLISH' if c > o else 'BEARISH'})")
            print(f"    SIGNAL FIRED: {sig}")
            print(f"    Entry: ${data['entry']:.4f}  SL: ${data['sl']:.4f}  TP: ${data['tp']:.4f}")
            print()
            break

    # ── Verdict ───────────────────────────────────────────────────────────────
    print("─" * 70)
    print("VERDICT")
    print("─" * 70)

    if signal_fired is None:
        print("  FAIL — no signal fired")
        if manager.setup_pending:
            sd = manager.pending_setup_data
            print(f"  Setup was pending ({manager.pending_signal}) but confirmation")
            print(f"  candle did not close in the right direction.")
            print(f"  RSI={sd['rsi']:.2f}  EMA9={sd['ema9']:.4f}  "
                  f"EMA26={sd['ema26']:.4f}  MA44={sd['ma44']:.4f}")
        return False

    direction_ok   = signal_fired == expected_signal
    timing_ok      = signal_at_i  == len(candles) - 1
    entry_ok       = abs(signal_data['entry'] - conf_open) < 0.01
    sequence_ok    = (setup_at_i is not None) and (signal_at_i == setup_at_i + 1)

    print(f"  Signal direction        : {signal_fired}  "
          f"{'PASS' if direction_ok else 'FAIL'}  (expected {expected_signal})")
    print(f"  Fired on last candle    : idx={signal_at_i}  "
          f"{'PASS' if timing_ok else 'FAIL'}  (last={len(candles)-1})")
    print(f"  Fired exactly setup+1   : setup={setup_at_i} conf={signal_at_i}  "
          f"{'PASS' if sequence_ok else 'FAIL'}")
    print(f"  Entry == conf open      : ${signal_data['entry']:.4f}  "
          f"{'PASS' if entry_ok else 'FAIL'}  (expected ${conf_open:.4f})")
    print(f"  SL                      : ${signal_data['sl']:.4f}")
    print(f"  TP                      : ${signal_data['tp']:.4f}")
    print(f"  RSI  (from setup)       : {signal_data['rsi']:.2f}")
    print(f"  EMA9 (from setup)       : {signal_data['ema9']:.4f}")
    print(f"  EMA26(from setup)       : {signal_data['ema26']:.4f}")
    print(f"  MA44 (from setup)       : {signal_data['ma44']:.4f}")
    print()

    passed = direction_ok and timing_ok and entry_ok and sequence_ok
    print(f"  OVERALL: {'PASS' if passed else 'FAIL'}")
    print("─" * 70)
    return passed


# ============================================================================
# RUN
# ============================================================================

print()
print("=" * 70)
print("FAKE SCENARIO TEST SUITE  v2")
print("=" * 70)
print()

print("Building LONG scenario...")
long_candles,  long_conf_open,  long_conf_close  = build_long_scenario()

print()
print("Building SHORT scenario...")
short_candles, short_conf_open, short_conf_close = build_short_scenario()

result_long  = run_fake_scenario(
    name            = "Scenario A — LONG",
    expected_signal = "LONG",
    candles         = long_candles,
    conf_open       = long_conf_open,
    conf_close      = long_conf_close,
)

result_short = run_fake_scenario(
    name            = "Scenario B — SHORT",
    expected_signal = "SHORT",
    candles         = short_candles,
    conf_open       = short_conf_open,
    conf_close      = short_conf_close,
)

print()
print("=" * 70)
print("FINAL SUMMARY")
print("=" * 70)
print(f"Scenario A (LONG) : {'PASS' if result_long  else 'FAIL'}")
print(f"Scenario B (SHORT): {'PASS' if result_short else 'FAIL'}")
print()
if result_long and result_short:
    print("Both scenarios passed.")
    print("The 2-step logic is confirmed working:")
    print("  - Setup candle:        4 conditions evaluated on closes[:-1]")
    print("  - Confirmation candle: direction check on the next closed candle")
    print("  - Entry price:         open of the confirmation candle")
else:
    print("One or more scenarios failed.")
    print("Check the pre-setup and setup candle indicators printed above.")
    print("The [Pre-setup check] lines show whether Phase 2 put indicators")
    print("in the right starting position before the setup candle.")
print("=" * 70)