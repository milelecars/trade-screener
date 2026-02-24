"""
REAL-TIME CRYPTO SCANNER - Binance WebSocket (Windows Compatible)
TRUE real-time monitoring - alerts sent THE SECOND signal triggers

- WebSocket streaming (instant price updates)
- Checks indicators every second
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
from dotenv import load_dotenv


load_dotenv()



# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Gemini AI (Optional - leave empty to use default analysis)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    USE_AI_ANALYSIS = True
    
    # Strategy Parameters
    RSI_PERIOD = 14
    EMA_SHORT = 9
    EMA_LONG = 26
    MA_PERIOD = 44
    RSI_LONG_MIN = 45.1      
    RSI_LONG_MAX = 85
    RSI_SHORT_MIN = 10       
    RSI_SHORT_MAX = 45
    SL_PERCENT = 0.5
    TP_PERCENT = 1.5
    
    # Real-time Settings
    CANDLE_INTERVAL = '15m'  # 15-minute candles
    HISTORY_BARS = 100
    
    # Alert Settings
    ALERT_COOLDOWN = 300  # 5 minutes
    SEND_INSTANT_ALERTS = True

# ============================================================================
# YOUR 40+ CRYPTO SYMBOLS
# ============================================================================

SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT',
    'DOGEUSDT', 'SOLUSDT', 'DOTUSDT', 'MATICUSDT', 'AVAXUSDT',
    'LINKUSDT', 'UNIUSDT', 'ATOMUSDT', 'LTCUSDT', 'XLMUSDT',
    'ALGOUSDT', 'VETUSDT', 'FILUSDT', 'TRXUSDT', 'NEARUSDT',
    'SHIBUSDT', 'APEUSDT', 'SANDUSDT', 'MANAUSDT', 'CRVUSDT',
    'AAVEUSDT', 'GRTUSDT', 'ENJUSDT', 'CHZUSDT', 'THETAUSDT',
    'FTMUSDT', 'AXSUSDT', 'HBARUSDT', 'EOSUSDT', 'FLOWUSDT',
    'ICPUSDT', 'XTZUSDT', 'EGLDUSDT', 'QNTUSDT', 'INJUSDT',
]

# ============================================================================
# LOGGING - Windows Compatible
# ============================================================================

# Fix Windows console encoding
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
    
    url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        'chat_id': Config.TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML',
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

    # If you use Gemini, return response.text only (no <code> tags)
    try:
        import google.generativeai as genai
        genai.configure(api_key=Config.GEMINI_API_KEY)
        model = genai.GenerativeModel("models/gemini-2.5-flash")

        prompt = f"""Analyze this {signal} trading signal for {symbol} in 2-3 sentences.

Entry: {data['entry']:.2f}, RSI: {data['rsi']:.2f}, EMA9: {data['ema9']:.2f}, EMA26: {data['ema26']:.2f}, MA44: {data['ma44']:.2f}.
Explain trend alignment, momentum, and risk."""
        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return "💡 Insight unavailable (AI error)."


def format_signal_alert(symbol: str, signal: str, data: dict) -> str:
    """Format signal message with structured sections"""
    
    # Calculate price deviation limits (±0.2%)
    entry_price = data['entry']
    max_entry_price = entry_price * 1.002  # +0.2%
    min_entry_price = entry_price * 0.998  # -0.2%
    
    # Get current timestamp 
    current_time = datetime.now()  # Local time
    expiry_time = current_time + timedelta(minutes=30)
    expiry_label = expiry_time.strftime('%H:%M:%S')
    
    # Signal emoji
    emoji = '🟢' if signal == 'LONG' else '🔴'
    
    # Build the message - EXACT content, NO leading spaces
    message = f"""{emoji} <b>{signal} SIGNAL - {symbol}</b>

━━━━━━━━━━━━━━━━
                CAUTION           
━━━━━━━━━━━━━━━━

⏰ Trade expires: {expiry_label}

❌ Do NOT enter if price is
    Less than  ${min_entry_price:.2f}
    More than ${max_entry_price:.2f}


━━━━━━━━━━━━━━━━
                    SIGNAL     
━━━━━━━━━━━━━━━━

💰 Entry:     ${data['entry']:.2f}
    Stop Loss: ${data['sl']:.2f} 
    Take Prof: ${data['tp']:.2f}

📈 Indicators:
- RSI:    {data['rsi']:.2f}
- EMA 9:  ${data['ema9']:.2f}
- EMA 26: ${data['ema26']:.2f}
- MA 44:  ${data['ma44']:.2f}
- R/R:    1:{Config.TP_PERCENT/Config.SL_PERCENT:.1f}

<pre>━━━━━━━━━━━━━━━━
   DISCLAIMER
━━━━━━━━━━━━━━━━

This isn't financial advice — 
I'm documenting how I allocate my own capital
so you can see how a serious operator approaches alternative markets.</pre>

<pre>━━━━━━━━━━━━━━━━
    INSIGHT
━━━━━━━━━━━━━━━━
{get_ai_analysis(symbol, signal, data)}</pre>"""
    
    return message.strip()


# ============================================================================
# INDICATOR CALCULATOR
# ============================================================================

class IndicatorEngine:
    """Fast indicator calculations"""
    
    @staticmethod
    def calculate_rsi(closes: list, period: int = 14) -> float:
        """Calculate RSI"""
        if len(closes) < period + 1:
            return 50.0
        
        prices = pd.Series(closes)
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])
    
    @staticmethod
    def calculate_ema(closes: list, period: int) -> float:
        """Calculate EMA"""
        if len(closes) < period:
            return closes[-1] if closes else 0
        
        prices = pd.Series(closes)
        ema = prices.ewm(span=period, adjust=False).mean()
        return float(ema.iloc[-1])
    
    @staticmethod
    def calculate_sma(closes: list, period: int) -> float:
        """Calculate SMA"""
        if len(closes) < period:
            return closes[-1] if closes else 0
        
        return sum(closes[-period:]) / period

# ============================================================================
# CANDLE MANAGER
# ============================================================================

class CandleManager:
    """Manages real-time candle data"""
    
    def __init__(self, symbol: str, max_bars: int = 100):
        self.symbol = symbol
        self.max_bars = max_bars
        
        # Candle storage
        self.timestamps = deque(maxlen=max_bars)
        self.opens = deque(maxlen=max_bars)
        self.highs = deque(maxlen=max_bars)
        self.lows = deque(maxlen=max_bars)
        self.closes = deque(maxlen=max_bars)
        self.volumes = deque(maxlen=max_bars)
        
        self.current_candle = None
        self.last_alert_time = 0
        
        self.load_history()
    
    def load_history(self):
        """Load historical candles"""
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': self.symbol,
                'interval': Config.CANDLE_INTERVAL,
                'limit': self.max_bars
            }
            
            response = requests.get(url, params=params, timeout=10)
            candles = response.json()
            
            for candle in candles:
                self.timestamps.append(int(candle[0]))
                self.opens.append(float(candle[1]))
                self.highs.append(float(candle[2]))
                self.lows.append(float(candle[3]))
                self.closes.append(float(candle[4]))
                self.volumes.append(float(candle[5]))
            
            logger.info(f"{self.symbol}: Loaded {len(self.closes)} bars")
            return True
            
        except Exception as e:
            logger.error(f"{self.symbol}: Load failed - {e}")
            return False
    
    def update_tick(self, price: float, timestamp: int = None):
        """Update with new price"""
        if timestamp is None:
            timestamp = int(time.time() * 1000)
        
        candle_start = (timestamp // 60000) * 60000
        
        # New candle?
        if not self.current_candle or candle_start > self.current_candle['timestamp']:
            # Save previous candle
            if self.current_candle:
                self.timestamps.append(self.current_candle['timestamp'])
                self.opens.append(self.current_candle['open'])
                self.highs.append(self.current_candle['high'])
                self.lows.append(self.current_candle['low'])
                self.closes.append(self.current_candle['close'])
                self.volumes.append(self.current_candle['volume'])
                
                return True  # New candle closed - check signal!
            
            # Start new candle
            self.current_candle = {
                'timestamp': candle_start,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 0
            }
        else:
            # Update current candle
            if self.current_candle:
                self.current_candle['high'] = max(self.current_candle['high'], price)
                self.current_candle['low'] = min(self.current_candle['low'], price)
                self.current_candle['close'] = price
        
        return False
    
    def check_signal(self) -> tuple:
        """Check for trading signal"""
        if len(self.closes) < Config.MA_PERIOD + 10:
            return None, None
        
        # Cooldown check
        if time.time() - self.last_alert_time < Config.ALERT_COOLDOWN:
            return None, None
        
        # Get data
        closes_list = list(self.closes)
        opens_list = list(self.opens)
        
        # Calculate indicators
        rsi = IndicatorEngine.calculate_rsi(closes_list, Config.RSI_PERIOD)
        ema9 = IndicatorEngine.calculate_ema(closes_list, Config.EMA_SHORT)
        ema26 = IndicatorEngine.calculate_ema(closes_list, Config.EMA_LONG)
        ma44 = IndicatorEngine.calculate_sma(closes_list, Config.MA_PERIOD)
        
        # Previous values
        ema9_prev = IndicatorEngine.calculate_ema(closes_list[:-1], Config.EMA_SHORT)
        ema26_prev = IndicatorEngine.calculate_ema(closes_list[:-1], Config.EMA_LONG)
        ma44_prev = IndicatorEngine.calculate_sma(closes_list[:-1], Config.MA_PERIOD)
        
        current_close = closes_list[-1]
        current_open = opens_list[-1]
        
        # MA Slope
        ma_slope = ma44 - IndicatorEngine.calculate_sma(closes_list[:-5], Config.MA_PERIOD)
        
        # LONG SIGNAL
        rsi_long_ok = Config.RSI_LONG_MIN <= rsi <= Config.RSI_LONG_MAX
        ema_cross_up = (ema9_prev <= ema26_prev) and (ema9 > ema26)
        both_above = (ema9 > ma44) and (ema26 > ma44)
        ema9_crossed_up = (ema9_prev <= ma44_prev) and (ema9 > ma44)
        ema26_crossed_up = (ema26_prev <= ma44_prev) and (ema26 > ma44)
        both_crossed_up = both_above and (ema9_crossed_up or ema26_crossed_up)
        slope_up = ma_slope > 0
        bullish = current_close > current_open
        above_mas = current_close > max(ema9, ema26, ma44)
        candle_ok_long = bullish and above_mas
        
        long_signal = (rsi_long_ok and ema_cross_up and both_crossed_up and 
                      slope_up and candle_ok_long)
        
        # SHORT SIGNAL
        rsi_short_ok = Config.RSI_SHORT_MIN <= rsi <= Config.RSI_SHORT_MAX
        ema_cross_down = (ema9_prev >= ema26_prev) and (ema9 < ema26)
        both_below = (ema9 < ma44) and (ema26 < ma44)
        ema9_crossed_down = (ema9_prev >= ma44_prev) and (ema9 < ma44)
        ema26_crossed_down = (ema26_prev >= ma44_prev) and (ema26 < ma44)
        both_crossed_down = both_below and (ema9_crossed_down or ema26_crossed_down)
        slope_down = ma_slope < 0
        bearish = current_close < current_open
        below_mas = current_close < min(ema9, ema26, ma44)
        candle_ok_short = bearish and below_mas
        
        short_signal = (rsi_short_ok and ema_cross_down and both_crossed_down and 
                       slope_down and candle_ok_short)
        
        # Return signal
        if long_signal:
            self.last_alert_time = time.time()
            return 'LONG', {
                'price': current_close,
                'entry': current_close,
                'sl': current_close * (1 - Config.SL_PERCENT/100),
                'tp': current_close * (1 + Config.TP_PERCENT/100),
                'rsi': rsi,
                'ema9': ema9,
                'ema26': ema26,
                'ma44': ma44
            }
        elif short_signal:
            self.last_alert_time = time.time()
            return 'SHORT', {
                'price': current_close,
                'entry': current_close,
                'sl': current_close * (1 + Config.SL_PERCENT/100),
                'tp': current_close * (1 - Config.TP_PERCENT/100),
                'rsi': rsi,
                'ema9': ema9,
                'ema26': ema26,
                'ma44': ma44
            }
        
        return None, None

# ============================================================================
# WEBSOCKET SCANNER
# ============================================================================

class RealtimeScanner:
    """Real-time scanner"""
    
    def __init__(self, symbols: list):
        self.symbols = symbols
        self.candle_managers = {}
        self.ws = None
        self.running = False
        
        for symbol in symbols:
            self.candle_managers[symbol] = CandleManager(symbol)
    
    def on_message(self, ws, message):
        """Handle message"""
        try:
            data = json.loads(message)
            
            if 'stream' in data:
                ticker_data = data['data']
                symbol = ticker_data['s']
                price = float(ticker_data['c'])
            else:
                symbol = data['s']
                price = float(data['c'])
            
            if symbol in self.candle_managers:
                manager = self.candle_managers[symbol]
                new_candle_closed = manager.update_tick(price)
                
                if new_candle_closed:
                    signal, data = manager.check_signal()
                    
                    if signal:
                        message = format_signal_alert(symbol, signal, data)
                        if send_telegram_alert(message):
                            logger.info(f"[SIGNAL] {symbol} - {signal} @ ${data['entry']:.4f}")
                        
        except Exception as e:
            logger.error(f"Error: {e}")
    
    def on_error(self, ws, error):
        """Handle error"""
        if str(error).strip():  # Only log non-empty errors
            logger.error(f"WebSocket error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        """Handle close"""
        logger.warning("WebSocket closed")
        if self.running:
            logger.info("Reconnecting in 5 seconds...")
            time.sleep(5)
            self.start()
    
    def on_open(self, ws):
        """Handle open"""
        logger.info("[OK] WebSocket connected - REAL-TIME monitoring active!")
    
    def start(self):
        """Start scanner"""
        self.running = True
        
        streams = [f"{s.lower()}@ticker" for s in self.symbols]
        stream_str = '/'.join(streams)
        ws_url = f"wss://stream.binance.com:9443/stream?streams={stream_str}"
        
        logger.info("="*80)
        logger.info("REAL-TIME CRYPTO SCANNER STARTING")
        logger.info("="*80)
        logger.info(f"Monitoring: {len(self.symbols)} symbols")
        logger.info(f"Mode: INSTANT ALERTS (WebSocket)")
        logger.info(f"Telegram: {'ENABLED' if Config.SEND_INSTANT_ALERTS else 'DISABLED'}")
        logger.info("="*80)
        
        # Send startup to Telegram
        startup_msg = f"""
🚀 <b>REAL-TIME Scanner Started</b>

⚡ <b>INSTANT ALERTS ENABLED</b>

✅ Monitoring: {len(self.symbols)} crypto pairs
✅ Mode: WebSocket streaming
✅ Speed: &lt;1 second latency

⏰ Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        send_telegram_alert(startup_msg)
        
        # Create WebSocket
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )
        
        # Run forever
        self.ws.run_forever()
    
    def stop(self):
        """Stop scanner"""
        self.running = False
        if self.ws:
            self.ws.close()

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Start scanner"""
    
    if Config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("ERROR: Please configure TELEGRAM_BOT_TOKEN!")
        return
    
    scanner = RealtimeScanner(SYMBOLS)
    
    try:
        scanner.start()
    except KeyboardInterrupt:
        print("\nScanner stopped by user")
        scanner.stop()
        
        shutdown_msg = f"""
🛑 <b>Scanner Stopped</b>

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        send_telegram_alert(shutdown_msg)

def send_test_signal():
    """Send a fake signal for testing message format"""
    test_data = {
        'price': 65724.10,
        'entry': 65724.10,
        'sl': 65395.38,
        'tp': 66709.95,
        'rsi': 52.34,
        'ema9': 65800.00,
        'ema26': 65978.00,
        'ma44': 66044.00
    }
    
    message = format_signal_alert('BTCUSDT', 'LONG', test_data)
    send_telegram_alert(message)
    print("Test signal sent to Telegram!")

# Uncomment to send test signal immediately
send_test_signal()

if __name__ == "__main__":
    main()