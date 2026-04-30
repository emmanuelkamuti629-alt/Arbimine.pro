#!/usr/bin/env python3
import os
import asyncio
import threading
import time
import random
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
MIN_PROFIT = float(os.getenv("MIN_PROFIT", "0.3"))
EXCHANGES_TO_SCAN = ['binance', 'bybit', 'okx', 'kucoin', 'gate', 'mexc', 'bitget']
MAX_PAIRS_PER_EXCHANGE = int(os.getenv("MAX_PAIRS", "300")) # Render limit

# Global state
latest_opportunities = []
last_scan_time = None
scan_count = 0
price_table = defaultdict(dict)
all_symbols = set() # Dynamic list of all USDT pairs found
symbol_count_by_exchange = {}
table_lock = threading.Lock()

EXCHANGE_FEES = {
    'binance': 0.001, 'bybit': 0.001, 'okx': 0.001, 'kucoin': 0.001,
    'gate': 0.002, 'mexc': 0.002, 'bitget': 0.001, 'huobi': 0.002,
}

print("✅ Starting dynamic coin discovery...")

# =========================
# DYNAMIC PRICE ENGINE
# =========================
class PriceEngine:
    def __init__(self):
        self.exchanges = {}
        for name in EXCHANGES_TO_SCAN:
            try:
                exchange_class = getattr(ccxt_pro, name)
                self.exchanges[name] = exchange_class({
                    'enableRateLimit': True,
                    'options': {'defaultType': 'spot'},
                    'timeout': 30000,
                })
            except Exception as e:
                print(f"Failed to init {name}: {e}")

    async def discover_all_symbols(self):
        """Load all USDT markets from all exchanges on startup"""
        global all_symbols, symbol_count_by_exchange
        print("🔍 Discovering all USDT pairs...")
        
        for name, exchange in self.exchanges.items():
            try:
                await exchange.load_markets()
                # Get all active spot USDT pairs
                usdt_pairs = [
                    s for s, m in exchange.markets.items() 
                    if m.get('quote') == 'USDT' 
                    and m.get('spot') 
                    and m.get('active')
                ]
                # Limit to prevent overload
                usdt_pairs = usdt_pairs[:MAX_PAIRS_PER_EXCHANGE]
                symbol_count_by_exchange[name] = len(usdt_pairs)
                all_symbols.update(usdt_pairs)
                print(f"[{name}] Found {len(usdt_pairs)} USDT pairs")
            except Exception as e:
                print(f"[{name}] Market load error: {e}")
                symbol_count_by_exchange[name] = 0
        
        all_symbols = list(all_symbols)
        print(f"✅ Total unique USDT pairs across all exchanges: {len(all_symbols)}")

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

        # Only check symbols that exist on 2+ exchanges
        for symbol, ex_data in snapshot.items():
            if len(ex_data) < 2:
                continue

            best_buy = None
            best_sell = None
            min_ask_eff = float('inf')
            max_bid_eff = 0

            for ex_name, data in ex_data.items():
                if time.time() - data['ts'] > 10: # 10s stale cutoff for REST
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

                if profit_pct >= MIN_PROFIT:
                    buy_liquidity = best_buy[1]['askVolume'] * best_buy[1]['ask']
                    sell_liquidity = best_sell[1]['bidVolume'] * best_sell[1]['bid']
                    liquidity = min(buy_liquidity, sell_liquidity)

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
        latest_opportunities = opps[:100] # Show top 100
        last_scan_time = datetime.utcnow()
        scan_count += 1

        elapsed_ms = (time.time() - start) * 1000
        if scan_count % 5 == 0:
            print(f"Scan #{scan_count}: {len(opps)} opps from {len(snapshot)} symbols in {elapsed_ms:.0f}ms")

# =========================
# BACKGROUND TASKS - REST POLLING FOR RENDER
# =========================
async def fetch_exchange_batch(name, exchange, symbols_batch):
    """Fetch one batch of tickers from one exchange"""
    try:
        # fetch_tickers with specific symbols is much faster than all
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
        print(f"[{name}] Batch error: {type(e).__name__}: {e}")
        return name, 0

def run_rest_poller():
    """Poll all exchanges in batches to avoid rate limits"""
    engine = PriceEngine()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def init_and_poll():
        await engine.discover_all_symbols()
        
        while True:
            start = time.time()
            tasks = []
            
            # Batch symbols: 50 per request to stay under rate limits
            batch_size = 50
            for name, exchange in engine.exchanges.items():
                # Only request symbols that exist on this exchange
                ex_symbols = [s for s in all_symbols if s in exchange.markets][:MAX_PAIRS_PER_EXCHANGE]
                for i in range(0, len(ex_symbols), batch_size):
                    batch = ex_symbols[i:i+batch_size]
                    tasks.append(fetch_exchange_batch(name, exchange, batch))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_updates = sum(r[1] for r in results if isinstance(r, tuple))
            
            elapsed = time.time() - start
            print(f"REST poll: {total_updates} prices updated in {elapsed:.1f}s")
            
            # Sleep to avoid rate limits. 400+ pairs = ~10s cycle
            await asyncio.sleep(max(3, 15 - elapsed))
    
    loop.run_until_complete(init_and_poll())

def run_calculator_loop():
    engine = PriceEngine()
    calc = ArbitrageCalculator(engine)
    while True:
        try:
            calc.find_opportunities()
            time.sleep(1) # Calc every 1s
        except Exception as e:
            print(f"Calculator error: {e}")
            time.sleep(1)

# Start background threads
threading.Thread(target=run_rest_poller, daemon=True).start()
time.sleep(10) # Let discovery + first poll complete
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
                                  coins=len(all_symbols),
                                  exchanges=symbol_count_by_exchange)

@app.route('/api/opportunities')
def api_opportunities():
    return jsonify({
        "success": True,
        "scan_count": scan_count,
        "last_scan": last_scan_time.isoformat() if last_scan_time else None,
        "opportunities": latest_opportunities,
        "total_symbols": len(all_symbols),
        "symbols_per_exchange": symbol_count_by_exchange
    })

@app.route('/api/health')
def health():
    with table_lock:
        tracked = len(price_table)
    return jsonify({
        "status": "healthy",
        "scans": scan_count,
        "total_unique_coins": len(all_symbols),
        "symbols_tracked": tracked,
        "exchanges": len(EXCHANGES_TO_SCAN),
        "symbols_per_exchange": symbol_count_by_exchange
    })

# =========================
# HTML TEMPLATE
# =========================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arbimine.pro - Full Market Scanner</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Courier New', monospace; background: #0a0e27; padding: 20px; color: #ccc; }
      .container { max-width: 1600px; margin: 0 auto; }
      .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 10px; margin-bottom: 20px; color: white; }
      .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 20px; }
      .stat-card { background: #1a1f3f; padding: 15px; border-radius: 8px; text-align: center; }
      .stat-value { font-size: 1.8em; font-weight: bold; color: #667eea; }
      .stat-label { font-size: 0.9em; opacity: 0.8; }
      .opportunities { background: #1a1f3f; border-radius: 10px; padding: 20px; }
      .arb-row { display: grid; grid-template-columns: 60px 100px 100px 80px 100px 80px; gap: 10px; padding: 8px 0; border-bottom: 1px solid #2a2f4f; align-items: center; font-size: 0.9em; }
      .arb-header { font-weight: bold; color: #667eea; border-bottom: 2px solid #667eea; margin-bottom: 10px; }
      .buy { color: #10b981; }.sell { color: #f59e0b; }.profit { color: #10b981; font-weight: bold; }
      .exchange { background: #2a2f4f; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; }
      .live { display: inline-block; width: 8px; height: 8px; background: #10b981; border-radius: 50%; animation: pulse 1s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        footer { text-align: center; margin-top: 20px; color: #666; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Arbimine.pro <span class="live"></span></h1>
            <p>Full Market Scanner | All USDT Pairs | Real-time</p>
        </div>

        <div class="stats">
            <div class="stat-card"><div class="stat-value">{{ opportunities|length }}</div><div class="stat-label">Live Opps</div></div>
            <div class="stat-card"><div class="stat-value">{{ coins }}</div><div class="stat-label">Total Coins</div></div>
            <div class="stat-card"><div class="stat-value">{{ exchanges|length }}</div><div class="stat-label">Exchanges</div></div>
            <div class="stat-card"><div class="stat-value">{{ scan_count }}</div><div class="stat-label">Scans</div></div>
            <div class="stat-card"><div class="stat-value">{{ last_scan }}</div><div class="stat-label">Last Update</div></div>
            <div class="stat-card"><div class="stat-value">{{ min_profit }}%</div><div class="stat-label">Min Profit</div></div>
        </div>

        <div class="opportunities">
            <div class="arb-row arb-header">
                <div>ACTION</div><div>EXCHANGE</div><div>COIN</div><div>PROFIT</div><div>LIQUIDITY</div><div>TIME</div>
            </div>
            {% for opp in opportunities %}
            <div class="arb-row">
                <div class="buy">BUY</div>
                <div><span class="exchange">{{ opp.buy_exchange }}</span></div>
                <div>{{ opp.symbol }}</div>
                <div class="profit">{{ opp.profit_percent }}%</div>
                <div>${{ "{:,}".format(opp.liquidity) }}</div>
                <div>{{ opp.timestamp }}</div>
            </div>
            <div class="arb-row">
                <div class="sell">SELL</div>
                <div><span class="exchange">{{ opp.sell_exchange }}</span></div>
                <div>{{ opp.symbol }}</div>
                <div></div><div></div>
            </div>
            {% endfor %}
            {% if not opportunities %}
            <p style="text-align: center; padding: 40px;">🔍 Discovering markets... First scan in ~30s</p>
            {% endif %}
        </div>

        <footer>⚠️ Educational only. Exchanges: {% for ex, count in exchanges.items() %}{{ ex }}: {{ count }} pairs {% endfor %}</footer>
    </div>
    <script>setInterval(() => location.reload(), 3000);</script>
</body>
</html>
"""

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print("="*70)
    print("🚀 Arbimine.pro - FULL MARKET VERSION")
    print("="*70)
    print(f"📊 Auto-discovering all USDT pairs on {len(EXCHANGES_TO_SCAN)} exchanges")
    print(f"⚡ REST polling mode for Render compatibility")
    print(f"🎯 Min profit: {MIN_PROFIT}% | Max pairs/exchange: {MAX_PAIRS_PER_EXCHANGE}")
    print(f"🌐 Dashboard: http://localhost:{port}")
    print("="*70)
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
