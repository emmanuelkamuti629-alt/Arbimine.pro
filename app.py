#!/usr/bin/env python3
import os
import asyncio
import threading
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
import ccxt.pro as ccxt_pro
from collections import defaultdict

app = Flask(__name__)
CORS(app)

# =========================
# CONFIGURATION
# =========================
MIN_PROFIT = float(os.getenv("MIN_PROFIT", "0.3"))
MIN_LIQUIDITY = int(os.getenv("MIN_LIQUIDITY", "5000")) # USD
TOP_N_COINS = 500

# Map your screenshot to ccxt exchange IDs
EXCHANGES_TO_SCAN = {
    'mexc': 'mexc',
    'bybit': 'bybit', 
    'ascendex': 'ascendex',
    'htx': 'htx', # HTX = Huobi
    'kucoin': 'kucoin',
    'bingx': 'bingx',
    'gate': 'gateio', # Gate.io
    'bitmart': 'bitmart',
    'xt': 'xt',
    'coinex': 'coinex',
    'binance': 'binance',
    'lbank': 'lbank',
    'okx': 'okx',
    'bitfinex': 'bitfinex',
    'bitget': 'bitget',
    'whitebit': 'whitebit',
    'poloniex': 'poloniex',
    'bitstamp': 'bitstamp',
    'upbit': 'upbit'
    # INDODAX not in ccxt, skip for now
}

# Global state
latest_opportunities = []
last_scan_time = None
scan_count = 0
price_table = defaultdict(dict)
top_500_symbols = []
last_coin_update = None
symbol_count_by_exchange = {}
table_lock = threading.Lock()

EXCHANGE_FEES = {
    'binance': 0.001, 'bybit': 0.001, 'okx': 0.001, 'kucoin': 0.001,
    'gateio': 0.002, 'mexc': 0.002, 'htx': 0.002, 'bitget': 0.001,
    'bitmart': 0.0025, 'coinex': 0.002, 'lbank': 0.002, 'whitebit': 0.001,
    'poloniex': 0.0025, 'bitfinex': 0.002, 'bitstamp': 0.005, 'bingx': 0.001,
    'xt': 0.002, 'ascendex': 0.001, 'upbit': 0.0025
}

# =========================
# TOP 500 COIN FETCHER
# =========================
def get_top_500_coins():
    """Fetch top 500 coins by volume from CoinGecko once per hour"""
    global top_500_symbols, last_coin_update
    
    if last_coin_update and datetime.utcnow() - last_coin_update < timedelta(hours=1):
        return top_500_symbols
    
    try:
        print("🔍 Fetching top 500 coins from CoinGecko...")
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            'vs_currency': 'usd',
            'order': 'volume_desc',
            'per_page': 250,
            'page': 1,
            'sparkline': False
        }
        r1 = requests.get(url, params=params, timeout=10).json()
        params['page'] = 2
        r2 = requests.get(url, params=params, timeout=10).json()
        
        coins = r1 + r2
        # Convert to CCXT format: BTC/USDT
        top_500_symbols = [f"{c['symbol'].upper()}/USDT" for c in coins]
        last_coin_update = datetime.utcnow()
        print(f"✅ Loaded top {len(top_500_symbols)} coins by volume")
        return top_500_symbols
    except Exception as e:
        print(f"CoinGecko error: {e}. Using fallback list")
        # Fallback if API fails
        return [f"{s}/USDT" for s in ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "TRX", "LINK", "AVAX"]]

# =========================
# PRICE ENGINE
# =========================
class PriceEngine:
    def __init__(self):
        self.exchanges = {}
        for name, ccxt_id in EXCHANGES_TO_SCAN.items():
            try:
                exchange_class = getattr(ccxt_pro, ccxt_id)
                self.exchanges[name] = exchange_class({
                    'enableRateLimit': True,
                    'options': {'defaultType': 'spot'},
                    'timeout': 30000,
                })
            except Exception as e:
                print(f"Failed to init {name}: {e}")

    async def discover_symbols_per_exchange(self):
        """Check which of the top 500 each exchange actually has"""
        global symbol_count_by_exchange
        coins = get_top_500_coins()
        
        for name, exchange in self.exchanges.items():
            try:
                await exchange.load_markets()
                available = [s for s in coins if s in exchange.markets and exchange.markets[s].get('active')]
                symbol_count_by_exchange[name] = len(available)
                print(f"[{name}] {len(available)}/{len(coins)} top coins available")
            except Exception as e:
                print(f"[{name}] Market load error: {e}")
                symbol_count_by_exchange[name] = 0

    def get_fee(self, exchange):
        return EXCHANGE_FEES.get(exchange, 0.002)

# =========================
# ARBITRAGE CALCULATOR
# =========================
class ArbitrageCalculator:
    def __init__(self, engine):
        self.engine = engine

    def find_opportunities(self):
        global latest_opportunities, last_scan_time, scan_count
        start = time.time()
        opps = []

        with table_lock:
            snapshot = {s: dict(exs) for s, exs in price_table.items()}

        for symbol, ex_data in snapshot.items():
            if len(ex_data) < 2:
                continue

            best_buy = None
            best_sell = None
            min_ask_eff = float('inf')
            max_bid_eff = 0

            for ex_name, data in ex_data.items():
                if time.time() - data['ts'] > 15: # 15s stale for 20 exchanges
                    continue

                fee = self.engine.get_fee(ex_name)
                ask_eff = data['ask'] * (1 + fee)
                bid_eff = data['bid'] * (1 - fee)

                if ask_eff < min_ask_eff:
                    min_ask_eff = ask_eff
                    best_buy = (ex_name, data)
                if bid_eff > max_bid_eff:
                    max_bid_eff = bid_eff
                    best_sell = (ex_name, data)

            if best_buy and best_sell and best_buy[0]!= best_sell[0]:
                profit_pct = ((max_bid_eff - min_ask_eff) / min_ask_eff) * 100
                liquidity = min(
                    best_buy[1]['askVolume'] * best_buy[1]['ask'],
                    best_sell[1]['bidVolume'] * best_sell[1]['bid']
                )

                if profit_pct >= MIN_PROFIT and liquidity >= MIN_LIQUIDITY:
                    opps.append({
                        "buy_exchange": best_buy[0].upper(),
                        "sell_exchange": best_sell[0].upper(),
                        "symbol": symbol.replace("/USDT", ""),
                        "profit_percent": round(profit_pct, 2),
                        "liquidity": int(liquidity),
                        "buy_price": round(best_buy[1]['ask'], 6),
                        "sell_price": round(best_sell[1]['bid'], 6),
                        "timestamp": datetime.utcnow().strftime('%H:%M:%S')
                    })

        opps.sort(key=lambda x: x['profit_percent'], reverse=True)
        latest_opportunities = opps[:100]
        last_scan_time = datetime.utcnow()
        scan_count += 1

        if scan_count % 5 == 0:
            print(f"Scan #{scan_count}: {len(opps)} opps from {len(snapshot)} symbols")

# =========================
# BACKGROUND TASKS
# =========================
async def fetch_exchange_batch(name, exchange, symbols_batch):
    try:
        tickers = await exchange.fetch_tickers(symbols_batch)
        now = time.time()
        count = 0
        with table_lock:
            for symbol, ticker in tickers.items():
                if ticker.get('bid') and ticker.get('ask') and ticker['bid'] > 0:
                    price_table[symbol][name] = {
                        'bid': float(ticker['bid']),
                        'ask': float(ticker['ask']),
                        'bidVolume': float(ticker.get('baseVolume') or 0),
                        'askVolume': float(ticker.get('baseVolume') or 0),
                        'ts': now
                    }
                    count += 1
        return name, count
    except Exception as e:
        print(f"[{name}] Batch error: {type(e).__name__}")
        return name, 0

def run_rest_poller():
    engine = PriceEngine()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def init_and_poll():
        await engine.discover_symbols_per_exchange()
        
        while True:
            start = time.time()
            tasks = []
            coins = get_top_500_coins
