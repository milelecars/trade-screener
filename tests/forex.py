"""
MA44 BOUNCE STRATEGY BACKTEST — MULTI-PAIR
===========================================
OANDA fxPractice REST API v20  |  15-minute candles
Period  : 01 Jan 2025 → 28 Feb 2026  (14 months)
Pairs   : EUR_USD, GBP_USD, AUD_USD, NZD_USD, USD_CAD

NOTE on USD_CAD: The user requested CAD/USD, but this pair is quoted
as USD_CAD on OANDA (and all standard forex markets). The strategy
logic is identical — MA44 bounce SHORT on USD_CAD means shorting USD
vs CAD (i.e. expecting USD to weaken / CAD to strengthen).

STRATEGY: Logic No. 2b Enhanced v3  (SHORT ONLY) — FOREX CALIBRATED
Two-step signal on 15m candles.
  Step 1 — Setup candle: bearish, MA44 falling 8 bars consecutively,
            body strictly below MA44, all filters F1–F9 pass.
  Step 2 — Validation: next candle opens below MA44 → entry at open.

FILTERS:
  F1  body_ratio   >= 0.25
  F2a dist zone A  0.005%–0.020%
  F2b dist zone B  0.025%–0.050%
  F4  wick range   0.020%–0.150%
  F5  slope 8-bar  abs >= 0.020%   ← raised from 0.005%
  F6  ma_accel     slope_recent < slope_prior < 0
  F7  ATR(14)      0.040%–0.120%   ← floor added at 0.040%
  F8  4H MA44      must be FALLING for SHORT
  F9  consec loss  2 losses → 8h pause (resets on WIN)

SL: 0.30%  |  TP: 0.90%  |  R:R 1:3  |  Cooldown: 4h  |  No time limit
LONGs: DISABLED

HOW TO RUN:
  1. Add to .env:   OANDA_TOKEN=your_token_here
  2. pip install requests python-dotenv
  3. python ma44_bounce_multi_oanda.py

Output: ma44_multi_report.txt  +  ma44_{PAIR}_report.txt per pair
"""

import os
import requests
import time
import sys
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================================
# CONFIGURATION
# ============================================================================

OANDA_TOKEN = os.getenv("OANDA_TOKEN", "YOUR_OANDA_TOKEN")

BASE_URL    = "https://api-fxpractice.oanda.com"
WARMUP_BARS = 250

# ── Pairs to test ─────────────────────────────────────────────────────────────
INSTRUMENTS = [
    # USD majors
    "USD_JPY",
    "USD_CHF",
    "EUR_USD",
    "GBP_USD",
    "AUD_USD",
    "NZD_USD",
    "USD_CAD",   # user requested CAD_USD — quoted as USD_CAD on OANDA
    # EUR crosses
    "EUR_JPY",
    "EUR_GBP",
    "EUR_AUD",
    "EUR_CAD",
    "EUR_CHF",
    # GBP crosses
    "GBP_JPY",
    "GBP_AUD",
    "GBP_CAD",
    "GBP_CHF",
    "GBP_NZD",
    # JPY crosses
    "AUD_JPY",
    "NZD_JPY",
    # Other crosses
    "AUD_CAD",
    "AUD_NZD",
    "NZD_CAD",
]

PERIOD = {
    "label":    "01 Mar 2023 → 28 Feb 2026  (3 years)",
    "start_dt": datetime(2023,  3,  1,  0,  0,  0, tzinfo=timezone.utc),
    "end_dt":   datetime(2026,  2, 28, 23, 59,  0, tzinfo=timezone.utc),
}

# ── Strategy parameters ───────────────────────────────────────────────────────
MA_PERIOD       = 44
SL_PCT          = 0.30
TP_PCT          = 0.90
COOLDOWN_MS     = 4 * 60 * 60 * 1000
MIN_BODY_RATIO  = 0.25
DIST_A_MIN      = 0.00005       # 0.005%
DIST_A_MAX      = 0.00020       # 0.020%
DIST_B_MIN      = 0.00025       # 0.025%
DIST_B_MAX      = 0.00050       # 0.050%
MIN_WICK_PCT    = 0.00020       # 0.020%
MAX_WICK_PCT    = 0.00150       # 0.150%
SLOPE_LB        = 8
MA_SLOPE_MIN    = 0.020         # 0.020%  (raised from 0.005%)
ACCEL_BARS      = 4
ATR_PERIOD      = 14
ATR_MAX_PCT     = 0.0012        # 0.120% ceiling
ATR_MIN_PCT     = 0.00040       # 0.040% floor (new — filters low-vol candles)
H4_MA_PERIOD    = 44
H4_SLOPE_BARS   = 4
CONSEC_LOSS_MAX = 2
CONSEC_LOSS_MS  = 8 * 60 * 60 * 1000

REQUEST_SLEEP   = 0.6           # 0.6s between requests
RETRY_MAX       = 5             # retries on 5xx / network errors
RETRY_BACKOFF   = [5, 15, 30, 60, 120]  # seconds between retries


# ============================================================================
# OANDA API HELPERS
# ============================================================================

def headers():
    return {
        "Authorization": f"Bearer {OANDA_TOKEN}",
        "Content-Type":  "application/json",
    }


def dt_to_rfc3339(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")


def oanda_to_ms(ts_str):
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def oanda_get(url, params, label=""):
    """
    GET with retry on 5xx / network errors.
    Returns (response, None) on success or (None, error_str) on failure.
    Retries up to RETRY_MAX times with exponential backoff.
    """
    for attempt in range(RETRY_MAX + 1):
        try:
            resp = requests.get(url, headers=headers(), params=params, timeout=30)
        except Exception as e:
            err = f"NETWORK ERROR: {e}"
            if attempt < RETRY_MAX:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                sys.stdout.write(f"    [{label}] {err} — retry {attempt+1}/{RETRY_MAX} in {wait}s\n")
                sys.stdout.flush()
                time.sleep(wait)
                continue
            return None, err

        if resp.status_code == 200:
            return resp, None
        if resp.status_code == 401:
            return None, "UNAUTHORIZED (401) — token expired. Regenerate at fxpractice.oanda.com"
        if resp.status_code == 400:
            return None, f"BAD REQUEST (400): {resp.text[:200]}"
        if resp.status_code in (502, 503, 504, 429):
            err = f"HTTP {resp.status_code} (server error)"
            if attempt < RETRY_MAX:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                sys.stdout.write(f"    [{label}] {err} — retry {attempt+1}/{RETRY_MAX} in {wait}s\n")
                sys.stdout.flush()
                time.sleep(wait)
                continue
            return None, f"{err} after {RETRY_MAX} retries"
        # Other unexpected errors — don't retry
        return None, f"HTTP {resp.status_code}: {resp.text[:200]}"

    return None, "Max retries exceeded"


def fetch_candles(instrument, granularity, from_dt, to_dt):
    """
    Paginated candle fetch using from+count pattern (no 'to').
    Returns (list of candle dicts sorted ASC, 'OK') or (None, error_str).
    """
    BATCH = 500
    step  = timedelta(minutes=15) if granularity == "M15" else timedelta(hours=4)

    all_candles  = []
    seen_times   = set()
    current_from = from_dt

    while current_from < to_dt:
        time.sleep(REQUEST_SLEEP)
        params = {
            "granularity":  granularity,
            "from":         dt_to_rfc3339(current_from),
            "count":        BATCH,
            "price":        "M",
            "includeFirst": "true",
        }
        resp, err = oanda_get(
            f"{BASE_URL}/v3/instruments/{instrument}/candles",
            params,
            label=f"{instrument} {granularity}",
        )
        if resp is None:
            return None, err

        data    = resp.json()
        candles = data.get("candles", [])
        if not candles:
            break

        last_candle_time = None
        for c in candles:
            ts        = c["time"]
            candle_ms = oanda_to_ms(ts)
            if candle_ms > int(to_dt.timestamp() * 1000):
                break
            if ts not in seen_times and c.get("complete", True):
                seen_times.add(ts)
                all_candles.append(c)
            last_candle_time = ts

        if not last_candle_time:
            break

        last_dt = datetime.fromtimestamp(oanda_to_ms(last_candle_time) / 1000, tz=timezone.utc)
        if last_dt >= to_dt:
            break
        current_from = last_dt + step
        if len(candles) < BATCH:
            break

    if not all_candles:
        return None, "NO DATA returned"

    all_candles.sort(key=lambda c: c["time"])
    return all_candles, "OK"


def candles_to_arrays(candles):
    closes = [float(c["mid"]["c"]) for c in candles]
    opens  = [float(c["mid"]["o"]) for c in candles]
    highs  = [float(c["mid"]["h"]) for c in candles]
    lows   = [float(c["mid"]["l"]) for c in candles]
    times  = [oanda_to_ms(c["time"]) for c in candles]
    return closes, opens, highs, lows, times


# ============================================================================
# INDICATOR HELPERS
# ============================================================================

def calc_sma_series(closes, period):
    n = len(closes)
    result = [None] * n
    for i in range(period - 1, n):
        result[i] = sum(closes[i - period + 1: i + 1]) / period
    return result


def calc_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calc_atr_wilder(highs, lows, closes, period):
    n = len(closes)
    atr = [None] * n
    if n < period + 1:
        return atr
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        )
    atr[period] = sum(tr[1: period + 1]) / period
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


# ============================================================================
# OUTCOME CHECKER — paginated forward scan
# ============================================================================

def check_outcome(instrument, entry_ts_ms, entry, sl, tp):
    """
    Scan ALL 15m candles forward from entry until SL or TP hit.
    SHORT: SL above entry, TP below entry.
    Returns 'WIN', 'LOSS', or 'ONGOING'.
    """
    current_from = datetime.fromtimestamp(
        entry_ts_ms / 1000, tz=timezone.utc
    ) + timedelta(minutes=15)
    now = datetime.now(tz=timezone.utc)

    if current_from >= now:
        return "ONGOING"

    while current_from < now:
        time.sleep(REQUEST_SLEEP)
        params = {
            "granularity":  "M15",
            "from":         dt_to_rfc3339(current_from),
            "count":        500,
            "price":        "M",
            "includeFirst": "true",
        }
        resp, err = oanda_get(
            f"{BASE_URL}/v3/instruments/{instrument}/candles",
            params,
            label=f"{instrument} outcome",
        )
        if resp is None:
            return "ONGOING"   # treat fetch failure as unresolved, not loss

        candles = resp.json().get("candles", [])
        if not candles:
            break

        for c in candles:
            try:
                h = float(c["mid"]["h"])
                l = float(c["mid"]["l"])
            except (KeyError, ValueError):
                continue
            if h >= sl:
                return "LOSS"
            if l <= tp:
                return "WIN"

        last_dt = datetime.fromisoformat(candles[-1]["time"].replace("Z", "+00:00"))
        current_from = last_dt + timedelta(minutes=15)
        if len(candles) < 500:
            break

    return "ONGOING"


def get_h4_ma44_direction(instrument, ts_ms):
    """Returns True=rising, False=falling, None=unknown."""
    end_dt    = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    need_bars = H4_MA_PERIOD + H4_SLOPE_BARS + 10
    start_dt  = end_dt - timedelta(hours=need_bars * 4)

    time.sleep(REQUEST_SLEEP)
    params = {
        "granularity":  "H4",
        "from":         dt_to_rfc3339(start_dt),
        "count":        need_bars + 5,
        "price":        "M",
        "includeFirst": "true",
    }
    resp, err = oanda_get(
        f"{BASE_URL}/v3/instruments/{instrument}/candles",
        params,
        label=f"{instrument} H4",
    )
    if resp is None:
        return None

    candles = [c for c in resp.json().get("candles", []) if c.get("complete", True)]
    if len(candles) < H4_MA_PERIOD + H4_SLOPE_BARS + 1:
        return None

    h4_closes = [float(c["mid"]["c"]) for c in candles]
    ma_now    = calc_sma(h4_closes,                  H4_MA_PERIOD)
    ma_prev   = calc_sma(h4_closes[:-H4_SLOPE_BARS], H4_MA_PERIOD)
    if ma_now is None or ma_prev is None:
        return None
    return ma_now > ma_prev


# ============================================================================
# SETUP CANDLE CHECKER
# ============================================================================

def check_setup(closes, opens, highs, lows, i, ma44_series, atr_series):
    """Returns ('SHORT', diag_dict) or (None, None)."""

    if closes[i] >= opens[i]:
        return None, None

    ma44 = ma44_series[i]
    if ma44 is None:
        return None, None

    # F5 — slope HARD REJECT
    if i < SLOPE_LB or ma44_series[i - SLOPE_LB] is None:
        return None, None
    slope_pct = (ma44 - ma44_series[i - SLOPE_LB]) / ma44 * 100
    if abs(slope_pct) < MA_SLOPE_MIN:
        return None, None

    # Monotonic fall for SLOPE_LB bars
    for k in range(1, SLOPE_LB + 1):
        if ma44_series[i - k + 1] is None or ma44_series[i - k] is None:
            return None, None
        if ma44_series[i - k + 1] >= ma44_series[i - k]:
            return None, None

    # F6 — MA acceleration
    if (i < ACCEL_BARS * 2
            or ma44_series[i - ACCEL_BARS]     is None
            or ma44_series[i - ACCEL_BARS * 2] is None):
        return None, None
    slope_recent = ma44 - ma44_series[i - ACCEL_BARS]
    slope_prior  = ma44_series[i - ACCEL_BARS] - ma44_series[i - ACCEL_BARS * 2]
    if not (slope_recent < 0 and slope_prior < 0 and slope_recent < slope_prior):
        return None, None

    # Candle geometry
    c_open  = opens[i];  c_close = closes[i]
    c_high  = highs[i];  c_low   = lows[i]
    body_top    = max(c_open, c_close)
    body_bottom = min(c_open, c_close)
    candle_size = c_high - c_low
    body_size   = body_top - body_bottom
    wick_pct    = candle_size / c_high if c_high > 0 else 0
    body_ratio  = body_size / candle_size if candle_size > 0 else 0

    if body_ratio < MIN_BODY_RATIO:                             return None, None
    if not (MIN_WICK_PCT <= wick_pct <= MAX_WICK_PCT):          return None, None
    if body_top >= ma44:                                        return None, None

    dist_pct  = (ma44 - body_top) / ma44
    in_zone_a = DIST_A_MIN <= dist_pct <= DIST_A_MAX
    in_zone_b = DIST_B_MIN <= dist_pct <= DIST_B_MAX
    if not (in_zone_a or in_zone_b):                            return None, None

    return "SHORT", {
        "ma_slope_8bar": slope_pct,
        "ma_accel":      slope_recent - slope_prior,
        "dist_pct":      dist_pct * 100,
        "zone":          "A" if in_zone_a else "B",
        "body_ratio":    body_ratio,
        "wick_pct":      wick_pct * 100,
    }


# ============================================================================
# MAIN SCANNER — per instrument
# ============================================================================

def scan(instrument, closes, opens, highs, lows, times, start_ts, end_ts):
    n           = len(closes)
    ma44_series = calc_sma_series(closes, MA_PERIOD)
    atr_series  = calc_atr_wilder(highs, lows, closes, ATR_PERIOD)

    signals         = []
    last_signal_ts  = 0
    pending_dir     = None
    pending_setup_i = None
    pending_diag    = None
    consec_loss     = 0
    pause_until     = 0
    h4_cache        = {}

    start_i = max(WARMUP_BARS, MA_PERIOD + SLOPE_LB + ATR_PERIOD + 10)

    for i in range(start_i, n - 1):
        candle_ts = times[i]
        in_window = (start_ts <= candle_ts <= end_ts)

        # ── STEP 2: fire pending setup ────────────────────────────────────────
        if pending_dir is not None:
            ma44_val = ma44_series[pending_setup_i]
            if ma44_val is not None and opens[i] < ma44_val and in_window:
                if (candle_ts - last_signal_ts) >= COOLDOWN_MS and candle_ts >= pause_until:
                    entry = opens[i]
                    sl    = entry * (1 + SL_PCT / 100)
                    tp    = entry * (1 - TP_PCT / 100)
                    si    = pending_setup_i
                    diag  = pending_diag or {}
                    atr_v = atr_series[si]
                    atr_p = (atr_v / closes[si] * 100) if atr_v and closes[si] > 0 else 0

                    outcome = check_outcome(instrument, candle_ts, entry, sl, tp)

                    signals.append({
                        "instrument":    instrument,
                        "type":          "SHORT",
                        "setup_time":    datetime.fromtimestamp(times[si] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                        "entry_time":    datetime.fromtimestamp(candle_ts  / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                        "entry_ts":      candle_ts,
                        "entry":         entry,
                        "sl":            sl,
                        "tp":            tp,
                        "ma44":          ma44_val,
                        "ma_slope_8bar": diag.get("ma_slope_8bar", 0.0),
                        "ma_accel":      diag.get("ma_accel",      0.0),
                        "dist_pct":      diag.get("dist_pct",      0.0),
                        "zone":          diag.get("zone",          "?"),
                        "body_ratio":    diag.get("body_ratio",    0.0),
                        "wick_pct":      diag.get("wick_pct",      0.0),
                        "atr_14_pct":    atr_p,
                        "h4_ma_dir":     diag.get("h4_ma_dir",    "N/A"),
                        "outcome":       outcome,
                    })
                    last_signal_ts = candle_ts

                    if outcome == "LOSS":
                        consec_loss += 1
                        if consec_loss >= CONSEC_LOSS_MAX:
                            pause_until = candle_ts + CONSEC_LOSS_MS
                            consec_loss = 0
                    elif outcome == "WIN":
                        consec_loss = 0

            pending_dir = None; pending_setup_i = None; pending_diag = None

        # ── STEP 1: check setup candle ────────────────────────────────────────
        if not in_window:
            continue

        direction, diag = check_setup(closes, opens, highs, lows, i, ma44_series, atr_series)
        if direction is None:
            continue

        # F7 — ATR gate (floor AND ceiling)
        atr_now = atr_series[i]
        if atr_now is not None and closes[i] > 0:
            atr_pct = atr_now / closes[i]
            if atr_pct >= ATR_MAX_PCT:   continue   # too volatile
            if atr_pct < ATR_MIN_PCT:    continue   # too quiet

        # F8 — 4H MA44 must be FALLING
        h4_bucket = (candle_ts // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
        if h4_bucket not in h4_cache:
            h4_cache[h4_bucket] = get_h4_ma44_direction(instrument, candle_ts)
        h4_rising = h4_cache[h4_bucket]
        if h4_rising is True:
            continue
        diag["h4_ma_dir"] = ("FALLING" if h4_rising is False else
                              "RISING"  if h4_rising is True  else "N/A")

        pending_dir     = direction
        pending_setup_i = i
        pending_diag    = diag

    return signals


# ============================================================================
# REPORT GENERATOR — per pair + combined
# ============================================================================

def write_pair_report(instrument, signals, filename):
    W   = 80
    gen = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    wins    = sum(1 for s in signals if s["outcome"] == "WIN")
    losses  = sum(1 for s in signals if s["outcome"] == "LOSS")
    ongoing = sum(1 for s in signals if s["outcome"] == "ONGOING")
    total   = len(signals)
    closed  = wins + losses
    wr      = wins / closed * 100 if closed > 0 else 0
    pnl     = (wins * TP_PCT) - (losses * SL_PCT)
    exp     = (wr / 100 * TP_PCT) - ((100 - wr) / 100 * SL_PCT) if closed > 0 else 0

    zone_a = [s for s in signals if s["zone"] == "A"]
    zone_b = [s for s in signals if s["zone"] == "B"]

    def zs(grp):
        w = sum(1 for s in grp if s["outcome"] == "WIN")
        l = sum(1 for s in grp if s["outcome"] == "LOSS")
        cl = w + l
        return w, l, (w / cl * 100 if cl > 0 else 0)

    za_w, za_l, za_wr = zs(zone_a)
    zb_w, zb_l, zb_wr = zs(zone_b)

    with open(filename, "w", encoding="utf-8") as f:
        def p(line=""):  print(line, file=f)
        def div(c="="): p(c * W)

        div("=")
        p(f"  MA44 BOUNCE STRATEGY BACKTEST — {instrument} (SHORT ONLY)")
        p("  Logic No. 2b Enhanced v3  |  OANDA fxPractice REST API v20")
        p(f"  Instrument : {instrument}  (mid prices)")
        p(f"  Period     : {PERIOD['label']}")
        p(f"  Interval   : 15-minute candles")
        p(f"  Generated  : {gen}")
        p()
        p(f"  SL: {SL_PCT}%  |  TP: {TP_PCT}%  |  R:R 1:3  |  Cooldown: 4h  |  No time limit")
        p("  LONGs: DISABLED")
        p()
        p("  FILTERS:")
        p(f"  F1 body>=0.25  F4 wick 0.020%-0.150%  F5 slope>=0.020%")
        p(f"  F2a dist 0.005%-0.020%  F2b 0.025%-0.050%  ATR 0.040%-0.120%")
        if instrument == "USD_CAD":
            p()
            p("  NOTE: USD_CAD is the standard OANDA symbol for CAD/USD.")
            p("  SHORT = expecting USD to weaken vs CAD.")
        div("=")
        p()

        div("*")
        p("  SUMMARY")
        div("*")
        p(f"  Total signals  : {total}")
        p(f"  Closed trades  : {closed}  (W:{wins}  L:{losses})")
        p(f"  Ongoing        : {ongoing}")
        if closed > 0:
            p(f"  Win Rate       : {wr:.1f}%")
            p(f"  Gross PnL      : {pnl:+.2f}%")
            p(f"  Expectancy     : {exp:+.3f}% per trade")
        p()
        div("-")
        p("  ZONE BREAKDOWN")
        div("-")
        p(f"  Zone A (0.005–0.020%) : {len(zone_a)} signals  W:{za_w} L:{za_l}  WR:{za_wr:.1f}%")
        p(f"  Zone B (0.025–0.050%) : {len(zone_b)} signals  W:{zb_w} L:{zb_l}  WR:{zb_wr:.1f}%")
        div("-")
        p()

        div("=")
        p("  TRADE LOG  (chronological)")
        div("=")
        p()

        for idx, s in enumerate(sorted(signals, key=lambda x: x["entry_ts"]), 1):
            ol = {"WIN": "[WIN ]", "LOSS": "[LOSS]", "ONGOING": "[OPEN]"}.get(s["outcome"], "[????]")
            p(f"  #{idx:<4} {ol}  SHORT  Entry: {s['entry_time']}  Setup: {s['setup_time']}")
            p(f"         MA44={s['ma44']:.5f}  slope={s['ma_slope_8bar']:+.5f}%  accel={s['ma_accel']:+.8f}")
            p(f"         dist={s['dist_pct']:.5f}% zone={s['zone']}  ATR={s['atr_14_pct']:.5f}%  4H={s['h4_ma_dir']}")
            p(f"         wick={s['wick_pct']:.5f}%  body={s['body_ratio'] * 100:.1f}%")
            p(f"         Entry={s['entry']:.5f}  SL={s['sl']:.5f}(+{SL_PCT}%)  TP={s['tp']:.5f}(-{TP_PCT}%)")
            p()

        if not signals:
            p("  No signals generated for this period.")
            p()

        div("=")
        p("  METHODOLOGY")
        div("=")
        p("  WIN/LOSS  : TP or SL hit — no time limit — ONGOING if still open")
        p("  MA44      : Simple SMA(44) computed bar by bar")
        p("  ATR       : Wilder smoothing, period 14")
        p("  4H gate   : MA44(44) on H4 candles — cached per 4h bucket")
        p("  Outcome   : SL/TP checked candle by candle from bar after entry")
        p("  Data      : OANDA fxPractice mid prices (bid/ask average)")
        p("  Rate      : 0.6s between requests — well under 2/sec limit")
        div("=")


def _pair_stats(sigs):
    """Return dict of stats for a list of signals."""
    w   = sum(1 for s in sigs if s["outcome"] == "WIN")
    l   = sum(1 for s in sigs if s["outcome"] == "LOSS")
    o   = sum(1 for s in sigs if s["outcome"] == "ONGOING")
    cl  = w + l
    wr  = w / cl * 100 if cl > 0 else 0
    pnl = (w * TP_PCT) - (l * SL_PCT)
    exp = (wr / 100 * TP_PCT) - ((100 - wr) / 100 * SL_PCT) if cl > 0 else 0
    za  = [s for s in sigs if s["zone"] == "A"]
    zb  = [s for s in sigs if s["zone"] == "B"]
    za_w = sum(1 for s in za if s["outcome"] == "WIN")
    za_l = sum(1 for s in za if s["outcome"] == "LOSS")
    zb_w = sum(1 for s in zb if s["outcome"] == "WIN")
    zb_l = sum(1 for s in zb if s["outcome"] == "LOSS")
    za_wr = za_w / (za_w + za_l) * 100 if (za_w + za_l) > 0 else None
    zb_wr = zb_w / (zb_w + zb_l) * 100 if (zb_w + zb_l) > 0 else None
    return dict(w=w, l=l, o=o, cl=cl, wr=wr, pnl=pnl, exp=exp,
                za_w=za_w, za_l=za_l, zb_w=zb_w, zb_l=zb_l,
                za_wr=za_wr, zb_wr=zb_wr,
                za_n=za_w+za_l, zb_n=zb_w+zb_l)


def write_combined_report(all_results, filename="ma44_multi_report.txt"):
    W   = 80
    BREAKEVEN = 100 * SL_PCT / (SL_PCT + TP_PCT)   # = 25.0% at 0.3/0.9
    gen = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Pre-compute stats for all pairs
    stats = {instr: _pair_stats(sigs) for instr, sigs in all_results}
    all_signals = [s for _, sigs in all_results for s in sigs]

    # Ranked by WR descending (pairs with trades only)
    ranked = sorted(
        [(instr, stats[instr]) for instr, _ in all_results if stats[instr]["cl"] > 0],
        key=lambda x: x[1]["wr"], reverse=True
    )

    with open(filename, "w", encoding="utf-8") as f:
        def p(line=""):  print(line, file=f)
        def div(c="="): p(c * W)
        def pct(v, digits=1): return f"{v:+.{digits}f}%" if v is not None else "n/a"
        def wpct(v, digits=1): return f"{v:.{digits}f}%" if v is not None else "n/a"

        # ── Header ────────────────────────────────────────────────────────────
        div("=")
        p("  MA44 BOUNCE STRATEGY — MULTI-PAIR CONSOLIDATED REPORT")
        p("  Logic No. 2b Enhanced v3  |  OANDA fxPractice REST API v20")
        p(f"  Period    : {PERIOD['label']}")
        p(f"  Generated : {gen}")
        p()
        p(f"  Pairs     : {len(INSTRUMENTS)} instruments tested")
        p(f"  Strategy  : SHORT ONLY  |  SL {SL_PCT}%  TP {TP_PCT}%  R:R 1:3")
        p(f"  Break-even WR at 1:3 = {BREAKEVEN:.1f}%")
        p()
        p("  FILTERS:")
        p(f"  F1 body>=0.25  F4 wick 0.020%-0.150%  F5 slope>=0.020%")
        p(f"  F2a dist 0.005%-0.020%  F2b 0.025%-0.050%  ATR 0.040%-0.120%")
        p(f"  F6 MA accel  F8 4H MA44 FALLING  F9 2 consec losses → 8h pause")
        div("=")
        p()

        # ── Aggregate ─────────────────────────────────────────────────────────
        agg = _pair_stats(all_signals)
        div("*")
        p("  AGGREGATE — ALL PAIRS COMBINED")
        div("*")
        p(f"  Total signals  : {len(all_signals)}")
        p(f"  Closed trades  : {agg['cl']}  (W:{agg['w']}  L:{agg['l']})")
        p(f"  Ongoing        : {agg['o']}")
        if agg["cl"] > 0:
            flag = "✓ PROFITABLE" if agg["wr"] > BREAKEVEN else "✗ BELOW BREAK-EVEN"
            p(f"  Win Rate       : {agg['wr']:.1f}%  ({flag})")
            p(f"  Gross PnL      : {pct(agg['pnl'])}")
            p(f"  Expectancy     : {pct(agg['exp'], 3)} per trade")
            p(f"  Zone A combined: {wpct(agg['za_wr'])}  ({agg['za_w']}W/{agg['za_l']}L / {agg['za_n']} trades)")
            p(f"  Zone B combined: {wpct(agg['zb_wr'])}  ({agg['zb_w']}W/{agg['zb_l']}L / {agg['zb_n']} trades)")
        p()

        # ── Leaderboard ranked by WR ──────────────────────────────────────────
        div("=")
        p("  LEADERBOARD — RANKED BY WIN RATE (pairs with trades only)")
        div("=")
        p()
        hdr = f"  {'RK':<3} {'PAIR':<10} {'SIG':>4}  {'W':>4}  {'L':>4}  {'WR%':>6}  {'PnL%':>8}  {'EXPECT':>8}  {'ZA sigs':>7}  {'ZA WR':>6}  {'ZB sigs':>7}  {'ZB WR':>6}  STATUS"
        p(hdr)
        div("-")
        for rank, (instr, st) in enumerate(ranked, 1):
            status = "✓ ABOVE BE" if st["wr"] >= BREAKEVEN else "✗ BELOW BE"
            za_s = f"{st['za_n']:>3}tr {wpct(st['za_wr']):>6}" if st["za_n"] > 0 else "  n/a   n/a"
            zb_s = f"{st['zb_n']:>3}tr {wpct(st['zb_wr']):>6}" if st["zb_n"] > 0 else "  n/a   n/a"
            p(f"  {rank:<3} {instr:<10} {len([s for _,sigs in all_results if _ == instr for s in sigs]):>4}  "
              f"{st['w']:>4}  {st['l']:>4}  {wpct(st['wr']):>6}  {pct(st['pnl']):>8}  "
              f"{pct(st['exp'],3):>8}  {za_s}  {zb_s}  {status}")
        div("-")
        # Pairs with no trades
        no_trades = [instr for instr, sigs in all_results if stats[instr]["cl"] == 0]
        if no_trades:
            p(f"  Pairs with 0 trades: {', '.join(no_trades)}")
        p()
        p(f"  NOTE: USD_CAD = CAD/USD on OANDA. SHORT = USD weakens vs CAD.")
        p()

        # ── Zone A vs Zone B breakdown ────────────────────────────────────────
        div("=")
        p("  ZONE ANALYSIS — ZONE A vs ZONE B PER PAIR")
        div("=")
        p()
        p("  Zone A = body top 0.005%–0.020% below MA44  (tight, close to MA)")
        p("  Zone B = body top 0.025%–0.050% below MA44  (wider, further from MA)")
        p(f"  Break-even WR = {BREAKEVEN:.1f}%  |  ✓ above  ✗ below")
        p()
        p(f"  {'PAIR':<10}  {'ZoneA sigs':>10}  {'ZoneA WR':>9}  {'ZoneA PnL':>10}  {'ZoneB sigs':>10}  {'ZoneB WR':>9}  {'ZoneB PnL':>10}  RECOMMENDATION")
        div("-")
        for instr, st in ranked:
            za_pnl = (st["za_w"] * TP_PCT) - (st["za_l"] * SL_PCT) if st["za_n"] > 0 else None
            zb_pnl = (st["zb_w"] * TP_PCT) - (st["zb_l"] * SL_PCT) if st["zb_n"] > 0 else None
            za_ok  = st["za_wr"] is not None and st["za_wr"] >= BREAKEVEN
            zb_ok  = st["zb_wr"] is not None and st["zb_wr"] >= BREAKEVEN
            if za_ok and zb_ok:
                rec = "Run both zones"
            elif za_ok and not zb_ok:
                rec = "Zone A only — disable B"
            elif not za_ok and zb_ok:
                rec = "Zone B only — disable A"
            else:
                rec = "Review — both below BE"
            za_str = f"{st['za_n']:>4} trades  {wpct(st['za_wr']):>7}  {pct(za_pnl):>9}" if st["za_n"] > 0 else f"{'':>4}  n/a       n/a      "
            zb_str = f"{st['zb_n']:>4} trades  {wpct(st['zb_wr']):>7}  {pct(zb_pnl):>9}" if st["zb_n"] > 0 else f"{'':>4}  n/a       n/a      "
            p(f"  {instr:<10}  {za_str}  {zb_str}  {rec}")
        div("-")
        p()

        # ── Profitability tiers ───────────────────────────────────────────────
        div("=")
        p("  PROFITABILITY TIERS")
        div("=")
        p()
        tier1 = [(i, s) for i, s in ranked if s["wr"] >= 40]
        tier2 = [(i, s) for i, s in ranked if 25 <= s["wr"] < 40]
        tier3 = [(i, s) for i, s in ranked if s["wr"] < 25]

        p("  TIER 1 — Strong (WR >= 40%)  → Recommend for live trading")
        div("-")
        if tier1:
            for instr, st in tier1:
                p(f"  {instr:<10}  WR {wpct(st['wr'])}  PnL {pct(st['pnl'])}  Expect {pct(st['exp'],3)}/trade  ({st['cl']} trades)")
        else:
            p("  None")
        p()

        p("  TIER 2 — Marginal (WR 25%–40%)  → Run with caution / paper trade first")
        div("-")
        if tier2:
            for instr, st in tier2:
                p(f"  {instr:<10}  WR {wpct(st['wr'])}  PnL {pct(st['pnl'])}  Expect {pct(st['exp'],3)}/trade  ({st['cl']} trades)")
        else:
            p("  None")
        p()

        p("  TIER 3 — Unprofitable (WR < 25%)  → Do not trade live")
        div("-")
        if tier3:
            for instr, st in tier3:
                p(f"  {instr:<10}  WR {wpct(st['wr'])}  PnL {pct(st['pnl'])}  Expect {pct(st['exp'],3)}/trade  ({st['cl']} trades)")
        else:
            p("  None")
        p()

        # ── Strategic recommendations ─────────────────────────────────────────
        div("=")
        p("  STRATEGIC RECOMMENDATIONS")
        div("=")
        p()
        p("  ZONE B DISABLE LIST (Zone B WR < 25% break-even):")
        zb_disable = [(i, s) for i, s in ranked if s["zb_wr"] is not None and s["zb_wr"] < BREAKEVEN and s["zb_n"] >= 5]
        if zb_disable:
            for instr, st in zb_disable:
                p(f"  → {instr:<10} Zone B WR = {wpct(st['zb_wr'])}  ({st['zb_n']} trades)  — DISABLE Zone B")
        else:
            p("  None — all Zone B WRs above break-even")
        p()
        p("  ZONE A STARS (Zone A WR >= 50% with >= 5 trades):")
        za_stars = [(i, s) for i, s in ranked if s["za_wr"] is not None and s["za_wr"] >= 50 and s["za_n"] >= 5]
        if za_stars:
            for instr, st in za_stars:
                p(f"  → {instr:<10} Zone A WR = {wpct(st['za_wr'])}  ({st['za_n']} trades)  ★ HIGH CONFIDENCE")
        else:
            p("  None meeting criteria")
        p()
        p("  GENERAL NOTES:")
        p(f"  - Break-even WR at 1:3 R:R = {BREAKEVEN:.1f}%")
        p(f"  - Spread not included — deduct ~0.02–0.05% expectancy per trade")
        p(f"  - JPY pairs use higher pip values — ATR thresholds may need tuning")
        p(f"  - Pairs with < 10 closed trades have low statistical confidence")
        p(f"  - Recommend extending to 5 years for final validation")
        p()

        # ── Per-pair detail sections ──────────────────────────────────────────
        for instrument, sigs in all_results:
            if not sigs:
                continue
            div("#")
            p(f"  {instrument}  |  {PERIOD['label']}")
            div("#")
            p()

            w  = sum(1 for s in sigs if s["outcome"] == "WIN")
            l  = sum(1 for s in sigs if s["outcome"] == "LOSS")
            o  = sum(1 for s in sigs if s["outcome"] == "ONGOING")
            cl = w + l
            wr = f"{w/cl*100:.1f}%" if cl > 0 else "n/a"
            pnl= f"{(w*TP_PCT)-(l*SL_PCT):+.2f}%" if cl > 0 else "n/a"
            p(f"  {len(sigs)} signals  W:{w}  L:{l}  Open:{o}  WR:{wr}  PnL:{pnl}")
            div("-")

            for idx, s in enumerate(sorted(sigs, key=lambda x: x["entry_ts"]), 1):
                ol = {"WIN": "[WIN ]", "LOSS": "[LOSS]", "ONGOING": "[OPEN]"}.get(s["outcome"], "[????]")
                p(f"  #{idx:<4} {ol}  SHORT  Entry: {s['entry_time']}  Setup: {s['setup_time']}")
                p(f"         MA44={s['ma44']:.5f}  slope={s['ma_slope_8bar']:+.5f}%  ATR={s['atr_14_pct']:.5f}%")
                p(f"         dist={s['dist_pct']:.5f}% zone={s['zone']}  4H={s['h4_ma_dir']}")
                p(f"         Entry={s['entry']:.5f}  SL={s['sl']:.5f}(+{SL_PCT}%)  TP={s['tp']:.5f}(-{TP_PCT}%)")
                p()
            div("-")
            p()

        div("=")
        p("  METHODOLOGY")
        div("=")
        p("  WIN/LOSS  : TP or SL hit — no time limit — ONGOING if still open")
        p("  MA44      : Simple SMA(44) computed bar by bar")
        p("  ATR       : Wilder smoothing, period 14 | Floor 0.040% | Ceil 0.120%")
        p("  4H gate   : MA44(44) on H4 candles — cached per 4h bucket")
        p("  Outcome   : SL/TP checked candle by candle from bar after entry")
        p("  Data      : OANDA fxPractice mid prices (bid/ask average)")
        div("=")

    return filename


# ============================================================================
# MAIN
# ============================================================================

def main():
    t = sys.stdout

    t.write("\n" + "=" * 60 + "\n")
    t.write("MA44 BOUNCE — MULTI-PAIR — SHORT ONLY\n")
    t.write(f"Pairs  : {', '.join(INSTRUMENTS)}\n")
    t.write(f"Period : {PERIOD['label']}\n")
    t.write("Source : OANDA fxPractice REST API v20\n")
    t.write("=" * 60 + "\n\n")

    if OANDA_TOKEN == "YOUR_OANDA_TOKEN":
        t.write("ERROR: OANDA_TOKEN not set.\n")
        t.write("  Add to .env:  OANDA_TOKEN=your_token_here\n\n")
        sys.exit(1)

    start_ts     = int(PERIOD["start_dt"].timestamp() * 1000)
    end_ts       = int(PERIOD["end_dt"].timestamp()   * 1000)
    warmup_delta = timedelta(minutes=15 * WARMUP_BARS)
    fetch_start  = PERIOD["start_dt"] - warmup_delta

    all_results = []

    for pair_idx, instrument in enumerate(INSTRUMENTS, 1):
        t.write(f"\n[{pair_idx}/{len(INSTRUMENTS)}] {instrument}\n")
        t.write(f"  Fetching 15m candles ({PERIOD['label']})...\n")

        candles, status = fetch_candles(instrument, "M15", fetch_start, PERIOD["end_dt"])
        if candles is None:
            t.write(f"  FAILED: {status}\n")
            all_results.append((instrument, []))
            continue

        t.write(f"  {len(candles)} candles fetched ✓\n")

        if len(candles) < WARMUP_BARS + 10:
            t.write("  NOT ENOUGH DATA — skipping.\n")
            all_results.append((instrument, []))
            continue

        closes, opens, highs, lows, times = candles_to_arrays(candles)

        t.write("  Scanning for signals...\n")
        signals = scan(instrument, closes, opens, highs, lows, times, start_ts, end_ts)

        w  = sum(1 for s in signals if s["outcome"] == "WIN")
        l  = sum(1 for s in signals if s["outcome"] == "LOSS")
        o  = sum(1 for s in signals if s["outcome"] == "ONGOING")
        cl = w + l
        wr = f"{w/cl*100:.1f}%" if cl > 0 else "n/a"

        t.write(f"  {len(signals)} signals  W:{w}  L:{l}  Open:{o}  WR:{wr}\n")

        # Write individual pair report
        pair_file = f"ma44_{instrument.lower()}_report.txt"
        write_pair_report(instrument, signals, pair_file)
        t.write(f"  → {pair_file}\n")

        all_results.append((instrument, signals))

    # Write combined report
    t.write("\nWriting combined report...\n")
    combined = write_combined_report(all_results)
    t.write(f"Done → {combined}\n\n")
    t.write("Individual pair reports:\n")
    for instrument, _ in all_results:
        t.write(f"  ma44_{instrument.lower()}_report.txt\n")
    t.write("\n")


if __name__ == "__main__":
    main()