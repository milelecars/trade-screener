"""
filter_by_correlation.py
========================
STEP 1 OF 4  —  Validate all coins from your list against Binance
                and output the SYMBOLS list for main_backtest.py

Checks all 136 coins extracted from both correlation tables.
Skips stablecoins, synthetic assets, and exchange tokens automatically.
Prints the final SYMBOLS list — copy it into main_backtest.py.

Usage:
  python filter_by_correlation.py
"""

import requests
import time

# ── All coins from both correlation tables ────────────────────────────────
# Source: Excel sheets provided. 136 unique symbols.
ALL_COINS = [
    '1INCH', '2Z',    'AAVE',  'AB',    'ADA',   'AERO',  'ALGO',  'AMP',
    'APT',   'ARB',   'ASTER', 'ATOM',  'AVAX',  'AXS',   'BARD',  'BAT',
    'BCH',   'BDX',   'BNB',   'BONK',  'BORG',  'BSV',   'BTC',   'BTT',
    'CAKE',  'CHZ',   'COW',   'CRO',   'CRV',   'DASH',  'DCR',   'DOGE',
    'DOT',   'EGLD',  'EIGEN', 'ENA',   'ENS',   'ETC',   'ETH',   'ETHFI',
    'FET',   'FIL',   'FLR',   'FLUID', 'FT',    'GALA',  'GLM',   'GNO',
    'GRT',   'GT',    'HBAR',  'HYPE',  'ICP',   'IMX',   'INJ',   'IOTA',
    'IP',    'JASMY', 'JTO',   'JUP',   'KAS',   'KCS',   'LDO',   'LINK',
    'LPT',   'LTC',   'LUNC',  'MANA',  'MNT',   'MON',   'MX',    'NEAR',
    'NEO',   'NEXO',  'OHM',   'ONDO',  'OP',    'PENDLE','PENGU', 'PEPE',
    'POL',   'PUMP',  'PYTH',  'QNT',   'RUNE',  'RAY',   'REAL',  'RENDER',
    'RLB',   'S',     'SAND',  'SEI',   'SFP',   'SHIB',  'SKY',   'SOL',
    'SPX',   'STRK',  'STX',   'SUI',   'SYRUP', 'TAO',   'THETA', 'TIA',
    'TKX',   'TRUMP', 'TWT',   'UNI',   'VET',   'VIRTUAL','VVV',  'WAL',
    'WBT',   'WIF',   'WLD',   'XDC',   'XMR',   'XPL',   'XRP',   'XTZ',
    'ZBCN',  'ZEC',   'ZK',    'ZRO',
]

# ── Skip list: stablecoins, synthetic USD, exchange tokens not worth trading
SKIP = {
    'FDUSD', 'USDD', 'USDE', 'USYC', 'AVUSD', 'EURC', 'EUTBL', 'RLUSD',
    'GUSD', 'ABUSDT',   # stable or synthetic
    'KCS', 'GT', 'MX', 'WBT', 'TKX',  # centralised exchange tokens
}

BASE_URL = 'https://api.binance.com/api/v3/ticker/price'


def check_binance(ticker: str) -> bool:
    """Returns True if ticker is live on Binance USDT spot."""
    try:
        r = requests.get(BASE_URL, params={'symbol': ticker}, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def main():
    print('=' * 60)
    print('STEP 1 — Binance availability check')
    print(f'Checking {len(ALL_COINS)} coins...')
    print('=' * 60)
    print()

    valid   = []
    invalid = []
    skipped = []

    for coin in ALL_COINS:
        if coin in SKIP:
            skipped.append(coin)
            print(f'  ⏭  {coin:<10}  (skipped — stable/exchange token)')
            continue

        ticker = coin + 'USDT'
        ok = check_binance(ticker)
        if ok:
            valid.append((coin, ticker))
            print(f'  ✅  {coin:<10}  {ticker}')
        else:
            invalid.append(coin)
            print(f'  ❌  {coin:<10}  not found on Binance')
        time.sleep(0.05)

    print()
    print('=' * 60)
    print(f'  ✅ Valid on Binance : {len(valid)}')
    print(f'  ❌ Not on Binance   : {len(invalid)}')
    print(f'  ⏭ Skipped           : {len(skipped)}')
    print()

    if invalid:
        print(f'Not on Binance: {invalid}')
        print()

    print('=' * 60)
    print('SYMBOLS list for main_backtest.py:')
    print('=' * 60)
    print()
    print('SYMBOLS = [')
    for coin, ticker in valid:
        print(f"    '{ticker}',")
    print(f']')
    print()
    print(f'# Total: {len(valid)} symbols')


if __name__ == '__main__':
    main()