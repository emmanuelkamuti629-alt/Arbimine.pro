#!/usr/bin/env python3
import os
import asyncio
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
import ccxt.pro as ccxt_pro
from collections import defaultdict

app = Flask(__name__)
CORS(app)

# =========================
# CONFIGURATION
# =========================
MIN_PROFIT = float(os.getenv("MIN_PROFIT", "0.1")) # Start low to see results
MIN_LIQUIDITY = int(os.getenv("MIN_LIQUIDITY", "500")) # $500 USD

# Only the 5 exchanges you want - these work on Render
EXCHANGES_TO_SCAN = {
    'mexc': 'mexc',
    'kucoin': 'kucoin', 
    'coinex': 'coinex',
    'bitmart': 'bitmart',
    'gateio': 'gateio', # Gate.io
}

# Global state
latest_opportunities = []
last_scan_time = None
scan_count = 0
price_table = defaultdict(dict)
all_symbols = set()
symbol_count_by_exchange = {}
exchange_status = {}
table_lock = threading.Lock()

EXCHANGE_FEES = {
    'mexc': 0.002,
    'kucoin': 0.001,
    'coinex': 0.002,
    'bitmart': 0.0025,
    'gateio': 0.002,
}

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
                exchange_status[name] = "init"
            except Exception as e:
                print(f"Failed to init {name}: {e}")
                exchange_status[name] = f"init_failed"

    async def discover_all_symbols(self):
        """Load ALL USDT markets from the 5 exchanges"""
        global all_symbols, symbol_count_by_exchange
        print("🔍 Discovering ALL USDT pairs on 5 exchanges...")
        
        for name, exchange in self.exchanges.items():
            try:
                await exchange.load_markets()
                # Get ALL active spot USDT pairs
                usdt_pairs = [
                    s for s, m in exchange.markets.items() 
                    if m.get('quote') == 'USDT' 
                    and m.get('spot') 
                    and m.get('active')
                ]
                symbol_count_by_exchange[name] = len(usdt_pairs)
                all_symbols.update(usdt_pairs)
                exchange_status[name] = f"ok: {len(usdt_pairs)} pairs"
                print(f"[{name}] Found {len(usdt_pairs)} USDT pairs")
            except Exception as e:
                print(f"[{name}] BLOCKED: {type(e).__name__}: {e}")
                symbol_count_by_exchange[name] = 0
                exchange_status[name] = f"blocked: {type(e).__name__}"
        
        all_symbols = list(all_symbols)
        print(f"✅ Total unique USDT pairs across 5 exchanges: {len(all_symbols)}")

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
                if time.time() - data['ts'] > 45: # 45s stale for slow scans
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
