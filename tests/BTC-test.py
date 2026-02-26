"""
BTC/USDT BACKTEST — Two Specific Date Ranges
=============================================
Period 1: 10 Oct 2024 → 18 Dec 2024
Period 2: 07 Oct 2025 → 25 Nov 2025

Both periods in one HTML report, separated by heading.
Same 4-layer signal logic as backtest_30d_v3.py.
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
RSI_SHORT_MAX      = 45
SL_PERCENT         = 0.5
TP_PERCENT         = 1.5
SIDEWAYS_LOOKBACK  = 20
SIDEWAYS_THRESHOLD = 0.002   # 0.2% of price
CROSS_LOOKBACK     = 4
COOLDOWN_MS        = 60 * 60 * 1000   # 1 hour

SYMBOL = 'BTCUSDT'

PERIODS = [
    {
        'label':    'Period 1 — BTC/USDT  |  10 Oct 2024 → 18 Dec 2024',
        'start_dt': datetime(2024, 10, 10, 0, 0, 0, tzinfo=timezone.utc),
        'end_dt':   datetime(2024, 12, 18, 23, 59, 59, tzinfo=timezone.utc),
    },
    {
        'label':    'Period 2 — BTC/USDT  |  07 Oct 2025 → 25 Nov 2025',
        'start_dt': datetime(2025, 10,  7, 0, 0, 0, tzinfo=timezone.utc),
        'end_dt':   datetime(2025, 11, 25, 23, 59, 59, tzinfo=timezone.utc),
    },
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
    ema    = prices.ewm(span=period, adjust=False).mean()
    return float(ema.iloc[-1])

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
    ma44_range    = max(ma44_values) - min(ma44_values)
    threshold     = closes[-1] * SIDEWAYS_THRESHOLD
    return ma44_range > threshold

# ============================================================================
# LAYER 2 — CROSS CONFIRMATION
# ============================================================================

def had_cross_above_ma44(closes):
    if len(closes) < MA_PERIOD + CROSS_LOOKBACK + 2:
        return False
    ema9_crossed = ema26_crossed = False
    for k in range(1, CROSS_LOOKBACK + 1):
        cn  = closes[:-k + 1] if k > 1 else closes
        cp  = closes[:-k]
        if len(cn) < MA_PERIOD or len(cp) < MA_PERIOD:
            continue
        e9n  = calculate_ema(cn,  EMA_SHORT);  e9p  = calculate_ema(cp, EMA_SHORT)
        e26n = calculate_ema(cn,  EMA_LONG);   e26p = calculate_ema(cp, EMA_LONG)
        m44n = calculate_sma(cn,  MA_PERIOD);  m44p = calculate_sma(cp, MA_PERIOD)
        if not ema9_crossed  and (e9p  <= m44p) and (e9n  > m44n): ema9_crossed  = True
        if not ema26_crossed and (e26p <= m44p) and (e26n > m44n): ema26_crossed = True
        if ema9_crossed and ema26_crossed: return True
    return ema9_crossed and ema26_crossed

def had_cross_below_ma44(closes):
    if len(closes) < MA_PERIOD + CROSS_LOOKBACK + 2:
        return False
    ema9_crossed = ema26_crossed = False
    for k in range(1, CROSS_LOOKBACK + 1):
        cn  = closes[:-k + 1] if k > 1 else closes
        cp  = closes[:-k]
        if len(cn) < MA_PERIOD or len(cp) < MA_PERIOD:
            continue
        e9n  = calculate_ema(cn,  EMA_SHORT);  e9p  = calculate_ema(cp, EMA_SHORT)
        e26n = calculate_ema(cn,  EMA_LONG);   e26p = calculate_ema(cp, EMA_LONG)
        m44n = calculate_sma(cn,  MA_PERIOD);  m44p = calculate_sma(cp, MA_PERIOD)
        if not ema9_crossed  and (e9p  >= m44p) and (e9n  < m44n): ema9_crossed  = True
        if not ema26_crossed and (e26p >= m44p) and (e26n < m44n): ema26_crossed = True
        if ema9_crossed and ema26_crossed: return True
    return ema9_crossed and ema26_crossed

# ============================================================================
# LAYER 3 — SETUP CANDLE
# ============================================================================

def check_setup_candle(closes, opens):
    if len(closes) < MA_PERIOD + SIDEWAYS_LOOKBACK + CROSS_LOOKBACK + 5:
        return None
    if not is_trending(closes):
        return None

    sc = closes[-1]; so = opens[-1]
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
# ============================================================================

def check_trigger_candle(closes, opens, direction):
    if len(closes) < MA_PERIOD + 7:
        return None
    ma44_setup = calculate_sma(closes[:-1], MA_PERIOD)   # setup candle
    ma44_4ago  = calculate_sma(closes[:-5], MA_PERIOD)   # 4 candles before setup
    topen      = opens[-1]
    sopen      = opens[-2]
    if direction == 'LONG'  and ma44_setup > ma44_4ago and topen > sopen: return topen
    if direction == 'SHORT' and ma44_setup < ma44_4ago and topen < sopen: return topen
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
# HTML REPORT
# ============================================================================

def stats_block(signals):
    wins    = sum(1 for s in signals if s['outcome'] == 'WIN')
    losses  = sum(1 for s in signals if s['outcome'] == 'LOSS')
    ongoing = sum(1 for s in signals if s['outcome'] == 'ONGOING')
    longs   = sum(1 for s in signals if s['type'] == 'LONG')
    shorts  = sum(1 for s in signals if s['type'] == 'SHORT')
    total   = len(signals)
    closed  = wins + losses
    wr      = wins / closed * 100 if closed > 0 else 0
    exp     = (wr/100 * TP_PERCENT) - ((100-wr)/100 * SL_PERCENT) if closed > 0 else 0
    pnl     = (wins * TP_PERCENT) - (losses * SL_PERCENT)
    return dict(wins=wins, losses=losses, ongoing=ongoing, longs=longs,
                shorts=shorts, total=total, closed=closed, wr=wr, exp=exp, pnl=pnl)

def signal_rows_html(signals):
    rows = []
    for s in sorted(signals, key=lambda x: x['trigger_ts']):
        oc  = {'WIN':'win','LOSS':'loss','ONGOING':'ongoing','UNKNOWN':'unknown'}.get(s['outcome'],'unknown')
        ol  = {'WIN':'✓ WIN','LOSS':'✗ LOSS','ONGOING':'● OPEN','UNKNOWN':'? N/A'}.get(s['outcome'],'?')
        tc  = 'long' if s['type'] == 'LONG' else 'short'
        st  = datetime.fromtimestamp(s['setup_ts']/1000, tz=timezone.utc).strftime('%m/%d %H:%M')
        tr  = datetime.fromtimestamp(s['trigger_ts']/1000, tz=timezone.utc).strftime('%m/%d %H:%M')
        rows.append(f"""<tr>
          <td><span class="badge {oc}">{ol}</span></td>
          <td><span class="badge {tc}">{s['type']}</span></td>
          <td class="mono">{st}</td><td class="mono">{tr}</td>
          <td class="mono">${s['entry']:.2f}</td>
          <td class="mono lc">${s['sl']:.2f}</td>
          <td class="mono wc">${s['tp']:.2f}</td>
          <td class="mono">{s['rsi']:.1f}</td>
          <td class="mono">{s['ema9']:.2f}</td>
          <td class="mono">{s['ema26']:.2f}</td>
          <td class="mono">{s['ma44']:.2f}</td>
        </tr>""")
    return '\n'.join(rows) if rows else '<tr><td colspan="11" class="empty">No signals found</td></tr>'

def period_section_html(period_label, start_dt, end_dt, signals, period_id):
    st = stats_block(signals)
    vc = 'wc' if st['wr'] >= 50 else 'lc'
    vt = ('EXCELLENT' if st['wr']>=60 else 'GOOD' if st['wr']>=50 else
          'MARGINAL'  if st['wr']>=40 else 'WEAK' if st['wr']>=25 else 'POOR') if st['closed']>0 else 'NO CLOSED TRADES'

    return f"""
    <section class="period" id="period{period_id}">
      <div class="period-header">
        <div class="period-num">Period {period_id}</div>
        <h2>{period_label}</h2>
        <div class="period-dates mono">{start_dt.strftime('%d %b %Y')} → {end_dt.strftime('%d %b %Y')}
          &nbsp;·&nbsp; {(end_dt - start_dt).days} days
        </div>
      </div>

      <div class="stat-grid">
        <div class="stat"><div class="slabel">Signals</div><div class="sval">{st['total']}</div></div>
        <div class="stat"><div class="slabel">Wins</div><div class="sval wc">{st['wins']}</div></div>
        <div class="stat"><div class="slabel">Losses</div><div class="sval lc">{st['losses']}</div></div>
        <div class="stat"><div class="slabel">Open</div><div class="sval">{st['ongoing']}</div></div>
        <div class="stat"><div class="slabel">Long / Short</div>
          <div class="sval" style="color:var(--long)">{st['longs']}<span style="color:var(--muted);font-size:14px"> / </span>{st['shorts']}</div></div>
        <div class="stat"><div class="slabel">Win Rate</div><div class="sval {vc}">{st['wr']:.1f}%</div></div>
        <div class="stat"><div class="slabel">Expectancy</div>
          <div class="sval {'wc' if st['exp']>=0 else 'lc'}">{st['exp']:+.2f}%</div></div>
        <div class="stat"><div class="slabel">Total PnL</div>
          <div class="sval {'wc' if st['pnl']>=0 else 'lc'}">{st['pnl']:+.1f}%</div></div>
      </div>

      <div class="wr-row">
        <span class="wr-pct {vc}">{st['wr']:.1f}%</span>
        <div class="wr-track"><div class="wr-fill" style="width:{min(st['wr'],100):.1f}%"></div></div>
        <span class="wr-meta">{st['wins']}W / {st['losses']}L &nbsp;·&nbsp; <span class="verdict {vc}">{vt}</span></span>
      </div>

      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Outcome</th><th>Type</th><th>Setup UTC</th><th>Trigger UTC</th>
            <th>Entry</th><th>Stop Loss</th><th>Take Profit</th>
            <th>RSI</th><th>EMA9</th><th>EMA26</th><th>MA44</th>
          </tr></thead>
          <tbody>{signal_rows_html(signals)}</tbody>
        </table>
      </div>
    </section>"""

def generate_html(results, filename='btc_backtest_report.html'):
    gen = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    sections = ''
    for i, (period, signals) in enumerate(results, 1):
        sections += period_section_html(
            period['label'], period['start_dt'], period['end_dt'], signals, i
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BTC/USDT Backtest Report</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

:root {{
  --bg:      #080a0f;
  --card:    #0e1118;
  --border:  #191f2e;
  --text:    #b8c0d0;
  --muted:   #4a5568;
  --accent:  #e8edf5;
  --win:     #10d98a;
  --loss:    #f0455a;
  --long:    #4499ff;
  --short:   #ffaa33;
  --ongoing: #9b8cf5;
  --p1:      #4499ff;
  --p2:      #f0455a;
}}

* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text); font-family:'Space Grotesk',sans-serif; font-size:14px; }}
.mono {{ font-family:'JetBrains Mono',monospace; }}

/* ── Top bar ── */
.topbar {{
  padding: 32px 56px 24px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}}
.topbar-left h1 {{ font-size:24px; font-weight:700; color:var(--accent); letter-spacing:-.02em; }}
.topbar-left .sub {{ font-size:12px; color:var(--muted); margin-top:4px; font-family:'JetBrains Mono',monospace; }}
.topbar-right {{ font-size:11px; color:var(--muted); font-family:'JetBrains Mono',monospace; text-align:right; }}

/* ── Nav pills ── */
.nav {{
  padding: 16px 56px;
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--border);
  background: var(--card);
}}
.nav a {{
  padding: 6px 18px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .04em;
  text-decoration: none;
  color: var(--muted);
  border: 1px solid var(--border);
  transition: all .15s;
}}
.nav a:hover {{ color:var(--accent); border-color:var(--muted); }}
.nav a.p1 {{ color:var(--p1); border-color:var(--p1); background:rgba(68,153,255,.08); }}
.nav a.p2 {{ color:var(--p2); border-color:var(--p2); background:rgba(240,69,90,.08); }}

/* ── Period section ── */
.period {{ padding: 48px 56px; border-bottom: 2px solid var(--border); }}
.period + .period {{ border-top: 2px solid var(--border); }}

.period-header {{ margin-bottom: 32px; }}
.period-num {{
  font-size: 10px; font-weight: 700; letter-spacing: .2em;
  text-transform: uppercase; color: var(--muted); margin-bottom: 6px;
}}
#period1 .period-num {{ color: var(--p1); }}
#period2 .period-num {{ color: var(--p2); }}

.period-header h2 {{
  font-size: 22px; font-weight: 700; color: var(--accent);
  letter-spacing: -.02em; margin-bottom: 4px;
}}
.period-dates {{ font-size: 12px; color: var(--muted); }}

/* ── Stat grid ── */
.stat-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 24px;
}}
.stat {{ background:var(--card); padding:18px 20px; }}
.slabel {{ font-size:10px; font-weight:600; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); margin-bottom:6px; }}
.sval {{ font-size:22px; font-weight:700; font-family:'JetBrains Mono',monospace; color:var(--accent); }}
.wc {{ color:var(--win) !important; }}
.lc {{ color:var(--loss) !important; }}

/* ── Win rate bar ── */
.wr-row {{
  display: flex; align-items: center; gap: 16px;
  margin-bottom: 28px;
}}
.wr-pct {{ font-size:20px; font-weight:700; font-family:'JetBrains Mono',monospace; min-width:72px; }}
.wr-track {{ flex:1; height:6px; background:var(--border); border-radius:3px; overflow:hidden; }}
.wr-fill {{ height:100%; border-radius:3px; background:linear-gradient(90deg,var(--win),#00ffaa); transition:width 1.2s cubic-bezier(.4,0,.2,1); }}
.wr-meta {{ font-size:12px; color:var(--muted); font-family:'JetBrains Mono',monospace; }}
.verdict {{ font-weight:700; font-size:11px; letter-spacing:.08em; text-transform:uppercase; }}
.verdict.wc {{ color:var(--win); }}
.verdict.lc {{ color:var(--loss); }}

/* ── Table ── */
.table-wrap {{ overflow-x:auto; border:1px solid var(--border); border-radius:8px; }}
table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
th {{
  text-align:left; padding:10px 14px;
  font-size:10px; font-weight:600; letter-spacing:.12em;
  text-transform:uppercase; color:var(--muted);
  border-bottom:1px solid var(--border); white-space:nowrap;
  background:var(--card);
}}
td {{ padding:10px 14px; border-bottom:1px solid var(--border); white-space:nowrap; }}
tr:last-child td {{ border-bottom:none; }}
tr:hover td {{ background:rgba(255,255,255,.015); }}
td.empty {{ text-align:center; padding:32px; color:var(--muted); font-style:italic; }}

.badge {{
  display:inline-block; padding:2px 8px; border-radius:3px;
  font-size:11px; font-weight:600;
  font-family:'JetBrains Mono',monospace; letter-spacing:.04em;
}}
.badge.win     {{ background:rgba(16,217,138,.12); color:var(--win); }}
.badge.loss    {{ background:rgba(240,69,90,.12);  color:var(--loss); }}
.badge.ongoing {{ background:rgba(155,140,245,.12);color:var(--ongoing); }}
.badge.unknown {{ background:rgba(100,100,100,.1); color:var(--muted); }}
.badge.long    {{ background:rgba(68,153,255,.12); color:var(--long); }}
.badge.short   {{ background:rgba(255,170,51,.12); color:var(--short); }}

/* ── Footer ── */
footer {{
  padding: 32px 56px;
  font-size: 11px; color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  border-top: 1px solid var(--border);
  line-height: 2;
}}
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-left">
    <h1>BTC/USDT — Backtest Report</h1>
    <div class="sub">15-minute candles &nbsp;·&nbsp; Binance &nbsp;·&nbsp; 4-Layer Signal Logic</div>
  </div>
  <div class="topbar-right">Generated {gen}<br>SL: -0.5% &nbsp;·&nbsp; TP: +1.5% &nbsp;·&nbsp; R/R 1:3</div>
</div>

<nav class="nav">
  <a href="#period1" class="p1">Period 1 &nbsp;·&nbsp; Oct–Dec 2024</a>
  <a href="#period2" class="p2">Period 2 &nbsp;·&nbsp; Oct–Nov 2025</a>
</nav>

{sections}

<footer>
  WIN = TP hit before SL within 48h &nbsp;·&nbsp;
  LOSS = SL hit before TP within 48h &nbsp;·&nbsp;
  OPEN = neither hit within 48h &nbsp;·&nbsp;
  Entry = open of trigger candle &nbsp;·&nbsp;
  Cooldown = 1h per symbol
</footer>

<script>
window.addEventListener('load', () => {{
  document.querySelectorAll('.wr-fill').forEach(el => {{
    const w = el.style.width;
    el.style.width = '0%';
    setTimeout(() => {{ el.style.width = w; }}, 400);
  }});
}});
</script>

</body>
</html>"""

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html)
    return filename


# ============================================================================
# MAIN
# ============================================================================

def main():
    t = sys.__stdout__
    t.write("\n" + "=" * 60 + "\n")
    t.write("BTC/USDT BACKTEST — Two Date Ranges\n")
    t.write("=" * 60 + "\n\n")

    results = []

    for period in PERIODS:
        t.write(f"─── {period['label']}\n")
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

    t.write("\nGenerating HTML report...\n")
    fname = generate_html(results, 'btc_backtest_report.html')
    t.write(f"Done → {fname}\n")
    t.write("Open in browser to view both periods.\n\n")


if __name__ == "__main__":
    main()