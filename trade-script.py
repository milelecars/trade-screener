"""
REAL-TIME CRYPTO SCANNER - Binance WebSocket (Windows Compatible)
TRUE real-time monitoring - alerts sent THE SECOND signal triggers

2-STEP SIGNAL LOGIC:
  Step 1 — SETUP candle:    4 indicator conditions met on the last CLOSED candle
  Step 2 — CONFIRMATION:    Next candle closes bearish (SHORT) or bullish (LONG)
  Entry price               = OPEN of the confirmation candle

- WebSocket streaming (instant price updates)
- Checks indicators on every candle close
- Telegram alert within 1 second of signal
- Monitors 40+ crypto pairs
- Completely FREE
- No rate limits

For CRYPTO ONLY (uses Binance)
"""

import websocket
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
from collections import deque
import logging
import sys
import io
import os
# from dotenv import load_dotenv

# load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

    # Gemini AI (Optional - leave empty to use default analysis)
    GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
    USE_AI_ANALYSIS = True

    # Strategy Parameters
    RSI_PERIOD    = 14
    EMA_SHORT     = 9
    EMA_LONG      = 26
    MA_PERIOD     = 44
    RSI_LONG_MIN  = 45.1
    RSI_LONG_MAX  = 85
    RSI_SHORT_MIN = 10
    RSI_SHORT_MAX = 45
    SL_PERCENT    = 0.5
    TP_PERCENT    = 1.5

    # Real-time Settings
    CANDLE_INTERVAL = '15m'
    HISTORY_BARS    = 100

    # Alert Settings
    ALERT_COOLDOWN       = 300   # 5 minutes between alerts per symbol
    SEND_INSTANT_ALERTS  = True

# ============================================================================
# YOUR 40+ CRYPTO SYMBOLS
# ============================================================================

SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT',
    'DOGEUSDT', 'TRXUSDT', 'ADAUSDT', 'LINKUSDT', 'AVAXUSDT',
    'BCHUSDT', 'SUIUSDT', 'LTCUSDT', 'PEPEUSDT', 'UNIUSDT',
    'DOTUSDT', 'NEARUSDT', 'SHIBUSDT', 'APTUSDT', 'OPUSDT',
    'MATICUSDT', 'ICPUSDT', 'FILUSDT', 'ARBUSDT', 'RUNEUSDT',
    'INJUSDT', 'ATOMUSDT', 'CHZUSDT', 'CRVUSDT', 'COMPUSDT',
    'BONKUSDT', 'SNXUSDT', 'PENDLEUSDT', 'YFIUSDT', 'LDOUSDT',
    'AXSUSDT', 'SANDUSDT', 'ALGOUSDT', 'ACHUSDT', 'ENSUSDT',
    'TIAUSDT', 'VETUSDT', 'MANAUSDT', 'ZRXUSDT', 'JUPUSDT',
    'ARKMUSDT', 'ARUSDT', 'GRTUSDT', 'APEUSDT', 'JTOUSDT',
    'WUSDT', 'IMXUSDT', 'PYTHUSDT', 'SUSDT', 'HOTUSDT',
    'QTUMUSDT', 'NEOUSDT', '1INCHUSDT', 'CVXUSDT', 'ZILUSDT',
    'BATUSDT', 'QNTUSDT', 'ONTUSDT', 'FLOWUSDT', 'STXUSDT',
    'ROSEUSDT', 'IOTAUSDT', 'CFXUSDT', 'KSMUSDT', 'ACTUSDT',
    'LUNCUSDT', 'TWTUSDT', 'NEXOUSDT', 'IOTXUSDT', 'ENJUSDT',
    'DYDXUSDT', 'REZUSDT', 'RSRUSDT', 'AXLUSDT', 'PEOPLEUSDT',
    'INITUSDT', 'THETAUSDT', 'API3USDT', 'BIGTIMEUSDT', 'NOTUSDT',
    'EGLDUSDT', 'IOSTUSDT', 'C98USDT', 'IOUSDT', 'XVSUSDT',
    'SUPERUSDT', 'NMRUSDT', 'ILVUSDT', 'DCRUSDT', 'COWUSDT',
    'MAGICUSDT', 'XLMUSDT', 'XTZUSDT', 'GLMUSDT', 'SKLUSDT',
    'HNTUSDT', 'GMXUSDT', 'CTSIUSDT', 'WOOUSDT', 'JASMYUSDT',
    'MKRUSDT', 'AAVEUSDT', 'AGIXUSDT', 'FETUSDT', 'CKBUSDT',
    'BANDUSDT', 'DUSKUSDT', 'SFPUSDT', 'RLCUSDT', 'OMGUSDT',
    'BLZUSDT', 'ZENUSDT', 'OGNUSDT', 'RENUSDT', 'PONDUSDT',
    'RVNUSDT', 'AUCTIONUSDT', 'CTKUSDT', 'CELRUSDT', 'BELUSDT',
    'RIFUSDT', 'OXTUSDT', 'BAKEUSDT', 'AUDIOUSDT', 'UNFIUSDT',
    'CELOUSDT', 'ICXUSDT', 'TRBUSDT', 'STMXUSDT', 'HIVEUSDT',
    'MDTUSDT', 'SCUSDT', 'POLYUSDT', 'REEFUSDT', 'LRCUSDT',
    'ONEUSDT', 'DENTUSDT', 'FLUXUSDT', 'RAYUSDT', 'AEUSDT',
    'BALUSDT', 'SXPUSDT', 'TKOUSDT', 'NUUSDT', 'RAREUSDT',
    'COMBOUSDT', 'MCUSDT', 'PAXGUSDT', 'TUSDT', 'LTOUSDT',
    'BLURUSDT', 'SANTOSUSDT', 'PORTOUSDT', 'PERPUSDT', 'IDUSDT',
    'SLPUSDT', 'STPTUSDT', 'DARUSDT', 'GALAUSDT', 'JOEUSDT',
    'MOVRUSDT', 'OOKIUSDT', 'FARMUSDT', 'VOXELUSDT', 'HIGHUSDT',
    'BETAUSDT', 'RADUSDT', 'CVPUSDT', 'CLVUSDT', 'EPXUSDT',
    'PROSUSDT', 'FXSUSDT', 'FISUSDT', 'VICUSDT', 'POWRUSDT',
    'VITEUSDT', 'QUICKUSDT', 'PHAUSDT'
]

# ============================================================================
# LOGGING - Windows Compatible
# ============================================================================

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler('realtime_scanner.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# TELEGRAM
# ============================================================================

def send_telegram_alert(message: str) -> bool:
    """Send INSTANT Telegram alert"""
    if not Config.SEND_INSTANT_ALERTS:
        return False

    url     = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id':                  Config.TELEGRAM_CHAT_ID,
        'text':                     message,
        'parse_mode':               'HTML',
        'disable_web_page_preview': True
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram failed: {e}")
        return False


def get_ai_analysis(symbol: str, signal: str, data: dict) -> str:
    if not Config.USE_AI_ANALYSIS or not Config.GEMINI_API_KEY:
        if signal == 'LONG':
            return (
                "💡 Setup Analysis:\n"
                f"EMA crossover confirms momentum shift.\n"
                f"RSI ({data['rsi']:.1f}) shows buying pressure without overbought.\n"
                "MA 44 trend supports directional bias.\n"
                "Risk-reward is favorable."
            )
        else:
            return (
                "💡 Setup Analysis:\n"
                f"EMA crossover signals downside momentum.\n"
                f"RSI ({data['rsi']:.1f}) shows selling pressure without extreme oversold.\n"
                "MA 44 slope confirms trend direction.\n"
                "Risk-reward is favorable."
            )

    try:
        import google.generativeai as genai
        genai.configure(api_key=Config.GEMINI_API_KEY)
        model  = genai.GenerativeModel("models/gemini-2.0-flash-exp")
        prompt = f"""Analyze this {signal} trading signal for {symbol} in 2-3 sentences.

Entry: {data['entry']:.2f}, RSI: {data['rsi']:.2f}, EMA9: {data['ema9']:.2f}, EMA26: {data['ema26']:.2f}, MA44: {data['ma44']:.2f}.
Explain trend alignment, momentum, and risk."""
        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return "💡 Insight unavailable (AI error)."


def format_signal_alert(symbol: str, signal: str, data: dict) -> str:
    """Format signal message"""
    entry_price     = data['entry']
    max_entry_price = entry_price * 1.002
    min_entry_price = entry_price * 0.998
    emoji           = '🟢' if signal == 'LONG' else '🔴'

    message = f"""{emoji} <b>{signal} - {symbol}</b>

💰 Entry:     ${data['entry']:.2f}
Stop Loss: ${data['sl']:.2f} 
Take Prof: ${data['tp']:.2f}

📈 Indicators:
- RSI:    {data['rsi']:.2f}
- EMA 9:  ${data['ema9']:.2f}
- EMA 26: ${data['ema26']:.2f}
- MA 44:  ${data['ma44']:.2f}
- R/R:    1:{Config.TP_PERCENT/Config.SL_PERCENT:.1f}

━━━━━━━━━━━━━━━━
CAUTION           
━━━━━━━━━━━━━━━━

⏰ Trade expires in 30 minutes

❌ Do NOT enter if price is
Less than  ${min_entry_price:.2f}
More than ${max_entry_price:.2f}


<pre>━━━━━━━━━━━━━━━━
INSIGHT
━━━━━━━━━━━━━━━━
{get_ai_analysis(symbol, signal, data)}</pre>

<pre>━━━━━━━━━━━━━━━━
DISCLAIMER
━━━━━━━━━━━━━━━━

This isn't financial advice — 
I'm documenting how I allocate my own capital
so you can see how a serious operator approaches alternative markets.</pre>"""

    return message.strip()


# ============================================================================
# INDICATOR CALCULATOR
# ============================================================================

class IndicatorEngine:
    """Fast indicator calculations"""

    @staticmethod
    def calculate_rsi(closes: list, period: int = 14) -> float:
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
    def calculate_ema(closes: list, period: int) -> float:
        if len(closes) < period:
            return closes[-1] if closes else 0
        prices = pd.Series(closes)
        ema    = prices.ewm(span=period, adjust=False).mean()
        return float(ema.iloc[-1])

    @staticmethod
    def calculate_sma(closes: list, period: int) -> float:
        if len(closes) < period:
            return closes[-1] if closes else 0
        return sum(closes[-period:]) / period

# ============================================================================
# CANDLE MANAGER
# ============================================================================

class CandleManager:
    """Manages real-time candle data with 2-step signal logic"""

    def __init__(self, symbol: str, max_bars: int = 100):
        self.symbol   = symbol
        self.max_bars = max_bars

        self.timestamps = deque(maxlen=max_bars)
        self.opens      = deque(maxlen=max_bars)
        self.highs      = deque(maxlen=max_bars)
        self.lows       = deque(maxlen=max_bars)
        self.closes     = deque(maxlen=max_bars)
        self.volumes    = deque(maxlen=max_bars)

        self.current_candle  = None
        self.last_alert_time = 0

        # ── 2-Step Logic State ────────────────────────────────────────────────
        # When 4 setup conditions pass, we store them here and wait for
        # the confirmation candle (next candle closes in the right direction).
        self.setup_pending       = False   # True = waiting for confirmation candle
        self.pending_signal      = None    # 'LONG' or 'SHORT'
        self.pending_setup_data  = None    # indicator snapshot from setup candle
        # ─────────────────────────────────────────────────────────────────────

        self.load_history()

    def load_history(self):
        """Load historical candles"""
        try:
            url    = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol':   self.symbol,
                'interval': Config.CANDLE_INTERVAL,
                'limit':    self.max_bars
            }

            response = requests.get(url, params=params, timeout=10)

            if response.status_code != 200:
                logger.error(f"{self.symbol}: HTTP {response.status_code}")
                return False

            candles = response.json()

            if not isinstance(candles, list):
                logger.error(f"{self.symbol}: Invalid response format")
                return False

            if len(candles) < 50:
                logger.error(f"{self.symbol}: Insufficient data ({len(candles)} bars)")
                return False

            for candle in candles:
                try:
                    self.timestamps.append(int(candle[0]))
                    self.opens.append(float(candle[1]))
                    self.highs.append(float(candle[2]))
                    self.lows.append(float(candle[3]))
                    self.closes.append(float(candle[4]))
                    self.volumes.append(float(candle[5]))
                except (ValueError, IndexError, TypeError) as e:
                    logger.error(f"{self.symbol}: Parse error - {e}")
                    return False

            logger.info(f"{self.symbol}: Loaded {len(self.closes)} bars")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"{self.symbol}: Network error - {e}")
            return False
        except Exception as e:
            logger.error(f"{self.symbol}: Unexpected error - {e}")
            return False

    def update_tick(self, price: float, timestamp: int = None):
        """
        Update with new price tick.
        Returns True when a new 15-min candle has just closed.
        """
        if timestamp is None:
            timestamp = int(time.time() * 1000)

        # Align to 15-minute boundary
        candle_ms    = 15 * 60 * 1000
        candle_start = (timestamp // candle_ms) * candle_ms

        if not self.current_candle or candle_start > self.current_candle['timestamp']:
            # ── Previous candle just closed → save it ────────────────────────
            if self.current_candle:
                self.timestamps.append(self.current_candle['timestamp'])
                self.opens.append(self.current_candle['open'])
                self.highs.append(self.current_candle['high'])
                self.lows.append(self.current_candle['low'])
                self.closes.append(self.current_candle['close'])
                self.volumes.append(self.current_candle['volume'])
                return True   # ← signal check should happen now

            # ── Start fresh candle ───────────────────────────────────────────
            self.current_candle = {
                'timestamp': candle_start,
                'open':  price,
                'high':  price,
                'low':   price,
                'close': price,
                'volume': 0
            }
        else:
            # Update running candle
            if self.current_candle:
                self.current_candle['high']  = max(self.current_candle['high'], price)
                self.current_candle['low']   = min(self.current_candle['low'],  price)
                self.current_candle['close'] = price

        return False

    # ─────────────────────────────────────────────────────────────────────────
    # 2-STEP SIGNAL LOGIC
    # Called once per closed candle (when update_tick returns True)
    # ─────────────────────────────────────────────────────────────────────────

    def check_signal(self) -> tuple:
        """
        2-Step logic:

        On every newly closed candle we do TWO checks:

        CHECK A — Confirmation check (if a setup is already pending):
            Look at the candle that JUST closed.
            If it's bullish  → fire the pending LONG signal.
            If it's bearish  → fire the pending SHORT signal.
            If it's neither  → cancel the pending setup (stale signal).

        CHECK B — Setup check (on the candle that just closed):
            Evaluate the 4 indicator conditions on closes[:-1]
            (i.e. the candle BEFORE the one that just closed, which is the
            last fully settled candle with stable indicator values).
            If all 4 pass → mark setup_pending = True and store the data.

        This means a signal fires at most ONE candle after the setup is detected.
        """

        if len(self.closes) < Config.MA_PERIOD + 12:
            return None, None

        # Cooldown guard
        if time.time() - self.last_alert_time < Config.ALERT_COOLDOWN:
            return None, None

        closes_list = list(self.closes)
        opens_list  = list(self.opens)

        # The candle that just closed
        conf_close = closes_list[-1]
        conf_open  = opens_list[-1]

        # ── CHECK A: Confirmation ─────────────────────────────────────────────
        if self.setup_pending and self.pending_signal and self.pending_setup_data:

            candle_bullish = conf_close > conf_open
            candle_bearish = conf_close < conf_open

            confirmed = (
                (self.pending_signal == 'LONG'  and candle_bullish) or
                (self.pending_signal == 'SHORT' and candle_bearish)
            )

            if confirmed:
                signal      = self.pending_signal
                setup_data  = self.pending_setup_data

                # Entry = open of this confirmation candle
                entry = conf_open

                # Build alert data using setup-candle indicators + confirmation entry
                if signal == 'LONG':
                    alert_data = {
                        'price': conf_close,
                        'entry': entry,
                        'sl':    entry * (1 - Config.SL_PERCENT / 100),
                        'tp':    entry * (1 + Config.TP_PERCENT / 100),
                        'rsi':   setup_data['rsi'],
                        'ema9':  setup_data['ema9'],
                        'ema26': setup_data['ema26'],
                        'ma44':  setup_data['ma44'],
                    }
                else:
                    alert_data = {
                        'price': conf_close,
                        'entry': entry,
                        'sl':    entry * (1 + Config.SL_PERCENT / 100),
                        'tp':    entry * (1 - Config.TP_PERCENT / 100),
                        'rsi':   setup_data['rsi'],
                        'ema9':  setup_data['ema9'],
                        'ema26': setup_data['ema26'],
                        'ma44':  setup_data['ma44'],
                    }

                # Reset pending state
                self.setup_pending      = False
                self.pending_signal     = None
                self.pending_setup_data = None
                self.last_alert_time    = time.time()

                return signal, alert_data

            else:
                # Confirmation candle did not cooperate → cancel setup
                logger.info(
                    f"{self.symbol}: Pending {self.pending_signal} setup cancelled "
                    f"(confirmation candle was {'bullish' if candle_bullish else 'bearish' if candle_bearish else 'doji'})"
                )
                self.setup_pending      = False
                self.pending_signal     = None
                self.pending_setup_data = None

        # ── CHECK B: Setup detection ──────────────────────────────────────────
        # Evaluate indicators on the SETUP candle = closes[:-1]
        # (one candle before the one that just closed)

        if len(closes_list) < Config.MA_PERIOD + 12:
            return None, None

        setup    = closes_list[:-1]    # setup candle is the last item here
        setup_m1 = closes_list[:-2]    # one candle before setup

        rsi   = IndicatorEngine.calculate_rsi(setup, Config.RSI_PERIOD)
        ema9  = IndicatorEngine.calculate_ema(setup, Config.EMA_SHORT)
        ema26 = IndicatorEngine.calculate_ema(setup, Config.EMA_LONG)
        ma44  = IndicatorEngine.calculate_sma(setup, Config.MA_PERIOD)

        ema9_prev  = IndicatorEngine.calculate_ema(setup_m1, Config.EMA_SHORT)
        ema26_prev = IndicatorEngine.calculate_ema(setup_m1, Config.EMA_LONG)
        ma44_prev  = IndicatorEngine.calculate_sma(setup_m1, Config.MA_PERIOD)
        ma44_5ago  = IndicatorEngine.calculate_sma(closes_list[:-6], Config.MA_PERIOD)

        ma_slope = ma44 - ma44_5ago

        # ── LONG setup conditions (4 of 5) ───────────────────────────────────
        rsi_long_ok     = Config.RSI_LONG_MIN <= rsi <= Config.RSI_LONG_MAX
        ema_cross_up    = (ema9_prev <= ema26_prev) and (ema9 > ema26)
        both_above_ma   = (ema9 > ma44) and (ema26 > ma44)
        any_cross_up_ma = (
            ((ema9_prev  <= ma44_prev) and (ema9  > ma44)) or
            ((ema26_prev <= ma44_prev) and (ema26 > ma44))
        )
        ema_ma_cross_up = both_above_ma and any_cross_up_ma
        slope_up        = ma_slope > 0

        long_setup = rsi_long_ok and ema_cross_up and ema_ma_cross_up and slope_up

        # ── SHORT setup conditions (4 of 5) ──────────────────────────────────
        rsi_short_ok      = Config.RSI_SHORT_MIN <= rsi <= Config.RSI_SHORT_MAX
        ema_cross_down    = (ema9_prev >= ema26_prev) and (ema9 < ema26)
        both_below_ma     = (ema9 < ma44) and (ema26 < ma44)
        any_cross_down_ma = (
            ((ema9_prev  >= ma44_prev) and (ema9  < ma44)) or
            ((ema26_prev >= ma44_prev) and (ema26 < ma44))
        )
        ema_ma_cross_down = both_below_ma and any_cross_down_ma
        slope_down        = ma_slope < 0

        short_setup = rsi_short_ok and ema_cross_down and ema_ma_cross_down and slope_down

        # ── Store pending setup ───────────────────────────────────────────────
        if long_setup or short_setup:
            self.setup_pending  = True
            self.pending_signal = 'LONG' if long_setup else 'SHORT'
            self.pending_setup_data = {
                'rsi':  rsi,
                'ema9': ema9,
                'ema26':ema26,
                'ma44': ma44,
            }
            logger.info(
                f"{self.symbol}: {self.pending_signal} setup detected — "
                f"waiting for confirmation candle  "
                f"(RSI={rsi:.1f}, EMA9={ema9:.2f}, EMA26={ema26:.2f}, MA44={ma44:.2f})"
            )

        return None, None   # signal fires only on confirmation (Check A above)


# ============================================================================
# WEBSOCKET SCANNER
# ============================================================================

class RealtimeScanner:
    """Real-time scanner"""

    def __init__(self, symbols: list):
        self.symbols         = symbols
        self.candle_managers = {}
        self.ws              = None
        self.running         = False

        for symbol in symbols:
            self.candle_managers[symbol] = CandleManager(symbol)

    def on_message(self, ws, message):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)

            if 'stream' in data:
                ticker_data = data['data']
                symbol      = ticker_data['s']
                price       = float(ticker_data['c'])
            else:
                symbol = data['s']
                price  = float(data['c'])

            if symbol in self.candle_managers:
                manager          = self.candle_managers[symbol]
                new_candle_closed = manager.update_tick(price)

                # Only evaluate signals on candle close
                if new_candle_closed:
                    signal, alert_data = manager.check_signal()

                    if signal and alert_data:
                        msg = format_signal_alert(symbol, signal, alert_data)
                        if send_telegram_alert(msg):
                            logger.info(
                                f"[SIGNAL] {symbol} - {signal} @ ${alert_data['entry']:.4f}"
                            )

        except Exception as e:
            logger.error(f"on_message error: {e}")

    def on_error(self, ws, error):
        if str(error).strip():
            logger.error(f"WebSocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        logger.warning("WebSocket closed")
        if self.running:
            logger.info("Reconnecting in 5 seconds...")
            time.sleep(5)
            self.start()

    def on_open(self, ws):
        logger.info("[OK] WebSocket connected - REAL-TIME monitoring active!")

    def start(self):
        """Start the scanner"""
        self.running = True

        streams    = [f"{s.lower()}@ticker" for s in self.symbols]
        stream_str = '/'.join(streams)
        ws_url     = f"wss://stream.binance.com:9443/stream?streams={stream_str}"

        logger.info("=" * 80)
        logger.info("REAL-TIME CRYPTO SCANNER  v2  —  2-Step Signal Logic")
        logger.info("=" * 80)
        logger.info(f"Monitoring : {len(self.symbols)} symbols")
        logger.info(f"Logic      : Setup candle (4 conditions) → Confirmation candle (direction)")
        logger.info(f"Entry price: Open of confirmation candle")
        logger.info(f"Telegram   : {'ENABLED' if Config.SEND_INSTANT_ALERTS else 'DISABLED'}")
        logger.info("=" * 80)

        startup_msg = f"""🚀 <b>REAL-TIME Scanner Started  v2</b>

⚡ <b>2-STEP SIGNAL LOGIC ACTIVE</b>

✅ Monitoring: {len(self.symbols)} crypto pairs
✅ Setup candle → Confirmation candle
✅ Entry = open of confirmation candle

⏰ Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        # send_telegram_alert(startup_msg)

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message = self.on_message,
            on_error   = self.on_error,
            on_close   = self.on_close,
            on_open    = self.on_open
        )

        self.ws.run_forever()

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

# ============================================================================
# MAIN
# ============================================================================

def main():
    if Config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("ERROR: Please configure TELEGRAM_BOT_TOKEN!")
        return

    scanner = RealtimeScanner(SYMBOLS)

    try:
        scanner.start()
    except KeyboardInterrupt:
        print("\nScanner stopped by user")
        scanner.stop()

        shutdown_msg = f"""🛑 <b>Scanner Stopped</b>

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        # send_telegram_alert(shutdown_msg)


def send_test_signal():
    """Send a fake signal for testing message format"""
    test_data = {
        'price': 65724.10,
        'entry': 65724.10,
        'sl':    65395.38,
        'tp':    66709.95,
        'rsi':   52.34,
        'ema9':  65800.00,
        'ema26': 65978.00,
        'ma44':  66044.00
    }

    message = format_signal_alert('BTCUSDT', 'LONG', test_data)
    send_telegram_alert(message)
    print("Test signal sent to Telegram!")


# Uncomment to send test signal immediately
# send_test_signal()

if __name__ == "__main__":
    main()