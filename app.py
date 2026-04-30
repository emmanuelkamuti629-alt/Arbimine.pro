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
MIN_PROFIT = float(os.getenv("MIN_PROFIT", "0.05")) # 0.05% to debug
MIN_LIQUIDITY = int(os.getenv("MIN_LIQUIDITY", "500")) # $500 to debug
TOP_N_COINS = 500

# All 20 exchanges from your screenshot -> ccxt IDs
EXCHANGES_TO_SCAN = {
    'mexc': 'mexc',
    'bybit': 'bybit', 
    'ascendex': 'ascendex',
    'htx': 'htx',
    'kucoin': 'kucoin',
    'bingx': 'bingx',
    'gate': 'gateio',
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
    'upbit': 'upbit',
    # 'indodax': 'indodax', # Not in ccxt
}

# Global state
latest_opportunities = []
last_scan_time = None
scan_count = 0
price_table = defaultdict(dict)
top_500_symbols = []
last_coin_update = None
symbol_count_by_exchange = {}
exchange_status = {} # live/blocked/error
table_lock = threading.Lock()

EXCHANGE_FEES = {
    'binance': 0.001, 'bybit': 0.001, 'okx': 0.001, 'kucoin': 0.001,
    'gateio': 0.002, 'mexc': 0.002, 'htx': 0.002, 'bitget': 0.001,
    'bitmart': 0.0025, 'coinex': 0.002, 'lbank': 0.002, 'bingx': 0.001,
    'xt': 0.002, 'ascendex': 0.001, 'upbit': 0.0025, 'whitebit': 0.001,
    'poloniex': 0.0025, 'bitfinex': 0.002, 'bitstamp': 0.005,
}

# =========================
# TOP 500 COIN FETCHER
# =========================
def get_top_500_coins():
    global top_500_symbols, last_coin_update
    
    if last_coin_update and datetime.utcnow() - last_coin_update < timedelta(hours=2):
        return top_500_symbols
    
    try:
        print("🔍 Fetching top 500 coins from CoinGecko...")
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {'vs_currency': 'usd', 'order': 'volume_desc', 'per_page': 250, 'page': 1}
        r1 = requests.get(url, params=params, timeout=20).json()
        params['page'] = 2
        r2 = requests.get(url, params=params, timeout=20).json()
        
        coins = r1 + r2
        top_500_symbols = [f"{c['symbol'].upper()}/USDT" for c in coins][:TOP_N_COINS]
        last_coin_update = datetime.utcnow()
        print(f"✅ Loaded {len(top_500_symbols)} coins by volume")
        return top_500_symbols
    except Exception as e:
        print(f"CoinGecko error: {e}. Using fallback")
        return [f"{s}/USDT" for s in ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "TRX", "LINK", "AVAX", "TON", "SHIB", "DOT", "LTC", "BCH", "NEAR", "APT", "MATIC", "ARB", "OP", "SUI", "PEPE", "WIF", "BONK", "SEI", "TIA", "INJ", "FET", "RNDR", "TAO"]]

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

    async def discover_symbols_per_exchange(self):
        global symbol_count_by_exchange
        coins = get_top_500_coins()
        
        for name, exchange in self.exchanges.items():
            try:
                await exchange.load_markets()
                available = [s for s in coins if s in exchange.markets and exchange.markets[s].get('active')]
                symbol_count_by_exchange[name] = len(available)
                exchange_status[name] = f"ok: {len(available)} pairs"
                print(f"[{name}] {len(available)}/{len(coins)} pairs available")
            except Exception as e:
                print(f"[{name}] BLOCKED: {type(e).__name__}")
                symbol_count_by_exchange[name] = 0
                exchange_status[name] = f"blocked: {type(e).__name__}"

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
                if time.time() - data['ts'] > 30: # 30s stale for 20 exchanges
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
                        "profit_percent": round(profit_pct, 3),
                        "liquidity": int(liquidity),
                        "buy_price": round(best_buy[1]['ask'], 6),
                        "sell_price": round(best_sell[1]['bid'], 6),
                        "timestamp": datetime.utcnow().strftime('%H:%M:%S')
                    })

        opps.sort(key=lambda x: x['profit_percent'], reverse=True)
        latest_opportunities = opps[:100]
        last_scan_time = datetime.utcnow()
        scan_count += 1
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
                        'bidVolume': float(ticker.get('quoteVolume') or ticker.get('baseVolume') or 0),
                        'askVolume': float(ticker.get('quoteVolume') or ticker.get('baseVolume') or 0),
                        'ts': now
                    }
                    count += 1
        if count > 0:
            exchange_status[name] = f"live: {count}"
        return name, count
    except Exception as e:
        exchange_status[name] = f"error: {type(e).__name__}"
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
            coins = get_top_500_coins()
            batch_size = 50
            
            for name, exchange in engine.exchanges.items():
                if symbol_count_by_exchange.get(name, 0) == 0:
                    continue
                ex_symbols = [s for s in coins if s in exchange.markets][:250]
                for i in range(0, len(ex_symbols), batch_size):
                    batch = ex_symbols[i:i+batch_size]
                    tasks.append(fetch_exchange_batch(name, exchange, batch))
                    await asyncio.sleep(0.3) # Rate limit protection
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_updates = sum(r[1] for r in results if isinstance(r, tuple))
            
            elapsed = time.time() - start
            print(f"REST poll: {total_updates} prices in {elapsed:.1f}s")
            await asyncio.sleep(max(15, 60 - elapsed)) # 60s cycle for 20 exchanges
    
    loop.run_until_complete(init_and_poll())

def run_calculator_loop():
    engine = PriceEngine()
    calc = ArbitrageCalculator(engine)
    while True:
        try:
            calc.find_opportunities()
            time.sleep(5)
        except Exception as e:
            print(f"Calculator error: {e}")
            time.sleep(5)

# Start threads
threading.Thread(target=run_rest_poller, daemon=True).start()
time.sleep(30) # Wait for discovery
threading.Thread(target=run_calculator_loop, daemon=True).start()

# =========================
# FLASK ROUTES
# =========================
@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE,
                                  opportunities=latest_opportunities,
                                  scan_count=scan_count,
                                  last_scan=last_scan_time.strftime('%H:%M:%S UTC') if last_scan_time else 'Starting...',
                                  min_profit=MIN_PROFIT,
                                  min_liquidity=MIN_LIQUIDITY,
                                  coins=len(top_500_symbols),
                                  exchanges=symbol_count_by_exchange,
                                  status=exchange_status)

@app.route('/api/debug')
def debug():
    with table_lock:
        tracked = len(price_table)
        symbols_with_2plus = sum(1 for s in price_table.values() if len(s) >= 2)
    return jsonify({
        "scan_count": scan_count,
        "total_top_500": len(top_500_symbols),
        "symbols_tracked": tracked,
        "symbols_on_2plus_exchanges": symbols_with_2plus,
        "exchange_status": exchange_status,
        "symbols_per_exchange": symbol_count_by_exchange,
        "active_exchanges": [k for k, v in exchange_status.items() if v.startswith("live") or v.startswith("ok")],
        "blocked_exchanges": [k for k, v in exchange_status.items() if "blocked" in v or "error" in v],
        "current_filters": {"min_profit": MIN_PROFIT, "min_liquidity": MIN_LIQUIDITY}
    })

@app.route('/api/opportunities')
def api_opportunities():
    return jsonify({
        "success": True,
        "scan_count": scan_count,
        "opportunities": latest_opportunities,
        "total_symbols": len(top_500_symbols),
    })

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arbimine.pro - 500 Coin Scanner</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Courier New', monospace; background: #0a0e27; padding: 15px; color: #ccc; }
     .container { max-width: 1800px; margin: 0 auto; }
     .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 10px; margin-bottom: 20px; color: white; }
     .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }
     .stat-card { background: #1a1f3f; padding: 12px; border-radius: 8px; text-align: center; }
     .stat-value { font-size: 1.5em; font-weight: bold; color: #667eea; }
     .stat-label { font-size: 0.75em; opacity: 0.8; }
     .opportunities { background: #1a1f3f; border-radius: 10px; padding: 15px; overflow-x: auto; }
     .arb-row { display: grid; grid-template-columns: 45px 80px 80px 60px 70px 90px; gap: 8px; padding: 6px 0; border-bottom: 1px solid #2a2f4f; align-items: center; font-size: 0.8em; }
     .arb-header { font-weight: bold; color: #667eea; border-bottom: 2px solid #667eea; margin-bottom: 8px; }
     .buy { color: #10b981; }.sell { color: #f59e0b; }.profit { color: #10b981; font-weight: bold; }
     .exchange { background: #2a2f4f; padding: 2px 4px; border-radius: 3px; font-size: 0.7em; }
     .live { display: inline-block; width: 8px; height: 8px; background: #10b981; border-radius: 50%; animation: pulse 1s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        footer { text-align: center; margin-top: 15px; color: #666; font-size: 0.7em; line-height: 1.4; }
        .debug { background: #2a2f4f; padding: 10px; border-radius: 5px; margin: 10px 0; font-size: 0.75em; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Arbimine.pro <span class="live"></span></h1>
            <p>Top 500 Coins | 20 Exchanges | Real-time</p>
        </div>

        <div class="stats">
            <div class="stat-card"><div class="stat-value">{{ opportunities|length }}</div><div class="stat-label">Live Opps</div></div>
            <div class="stat-card"><div class="stat-value">{{ coins }}</div><div class="stat-label">Coins</div></div>
            <div class="stat-card"><div class="stat-value">{{ exchanges|selectattr('value')|list|length }}</div><div class="stat-label">Active Ex</div></div>
            <div class="stat-card"><div class="stat-value">{{ scan_count }}</div><div class="stat-label">Scans</div></div>
            <div class="stat-card"><div class="stat-value">{{ last_scan }}</div><div class="stat-label">Updated</div></div>
            <div class="stat-card"><div class="stat-value">{{ min_profit }}%</div><div class="stat-label">Min Profit</div></div>
        </div>

        <div class="debug">
            <b>Exchange Status:</b> {% for ex, stat in status.items() %}{{ ex }}:{{ stat }} | {% endfor %}
        </div>

        <div class="opportunities">
            <div class="arb-row arb-header">
                <div>ACT</div><div>BUY</div><div>SELL</div><div>COIN</div><div>PROFIT</div><div>LIQUID</div>
            </div>
            {% for opp in opportunities %}
            <div class="arb-row">
                <div class="buy">BUY</div>
                <div><span class="exchange">{{ opp.buy_exchange }}</span></div>
                <div><span class="exchange">{{ opp.sell_exchange }}</span></div>
                <div>{{ opp.symbol }}</div>
                <div class="profit">{{ opp.profit_percent }}%</div>
                <div>${{ "{:,}".format(opp.liquidity) }}</div>
            </div>
            {% endfor %}
            {% if not opportunities %}
            <p style="text-align: center; padding: 30px;">🔍 Scanning... First results in ~90s. Check /api/debug</p>
            {% endif %}
        </div>

        <footer>
            Active: {% for ex, count in exchanges.items() if count > 0 %}{{ ex }}:{{ count }} {% endfor %}
        </footer>
    </div>
    <script>setInterval(() => location.reload(), 5000);</script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print("="*70)
    print("🚀 Arbimine.pro - 500 COIN / 20 EXCHANGE VERSION")
    print("="*70)
    print(f"📊 Scanning top 500 coins across {len(EXCHANGES_TO_SCAN)} exchanges")
    print(f"⚡ 60s cycles | Debug filters: {MIN_PROFIT}% profit, ${MIN_LIQUIDITY} liquidity")
    print(f"🌐 Dashboard: http://localhost:{port} | Debug: /api/debug")
    print("="*70)
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
