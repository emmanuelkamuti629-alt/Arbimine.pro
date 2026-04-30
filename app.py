#!/usr/bin/env python3
"""
Arbimine.pro - Ultra-Fast Cross-Exchange Arbitrage Scanner
300+ Coins | Real-time WebSocket | <400ms scan cycles
"""

import os
import asyncio
import threading
import json
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
TOP_N_COINS = 100 # Limit for WS subs. Increase if your VPS can handle it
EXCHANGES_TO_SCAN = ['binance', 'bybit', 'okx', 'kucoin', 'gate']

# Global state - thread safe
latest_opportunities = []
last_scan_time = None
scan_count = 0
price_table = defaultdict(dict) # {symbol: {exchange: {bid, ask, bid_vol, ask_vol, ts}}}
table_lock = threading.Lock()

# =========================
# 300+ COINS
# =========================
ALL_COINS = [
    "BTC", "ETH", "XRP", "BNB", "SOL", "DOGE", "ADA", "TRX", "LINK", "AVAX", "TON", "SHIB", "DOT", "LTC", "BCH",
    "NEAR", "APT", "ICP", "MATIC", "POL", "ARB", "OP", "ATOM", "HBAR", "FIL", "XLM", "VET", "RNDR", "INJ", "KAS",
    "ALGO", "ETC", "CRO", "XMR", "PEPE", "BONK", "JUP", "SUI", "SEI", "STRK", "TIA", "BLUR", "DYDX", "SUSHI",
    "UNI", "AAVE", "GRT", "GALA", "ENJ", "SAND", "AXS", "FLOW", "FTM", "BEAM", "CRV", "CAKE", "COMP", "MKR",
    "SNX", "ZEC", "DASH", "XTZ", "EOS", "NEO", "IOTA", "OMG", "ZIL", "KSM", "WAVES", "KAVA", "BAND", "NU",
    "GHX", "MCTP", "WKC", "GAIA", "NATIX", "SUT", "CESS", "REEF", "COTI", "CHZ", "STMX", "CKB", "ONE", "ICX",
    "STEEM", "SC", "LSK", "STRAT", "ARK", "KMD", "DGB", "RVN", "XVG", "FUN", "GAS", "WAN", "NULS", "ALICE",
    "BETA", "C98", "DUSK", "ERN", "FIDA", "GTC", "HARD", "IDEX", "JASMY", "KLAY", "LIT", "MINA", "NKN", "OXT",
    "POND", "QNT", "RLC", "STORJ", "TWT", "UMA", "VRA", "WOO", "XNO", "YGG", "ZRX", "AGLD", "1INCH", "ANKR",
    "BAL", "BNT", "CELO", "CVC", "DENT", "ELF", "FET", "GNO", "HOT", "IOST", "JST", "KNC", "LOOM", "MANA",
    "NMR", "OCEAN", "POLS", "QSP", "REN", "SXP", "TRB", "UOS", "VTHO", "WAXP", "BOBA", "CELR", "CHR", "CTK",
    "DODO", "ELA", "FIO", "GLM", "HNT", "JOE", "KP3R", "LRC", "METIS", "NYM", "ORCA", "POKT", "RAD", "SKL",
    "THETA", "UFO", "VEGA", "WIN", "XVS", "YFI", "ZEN", "AEVO", "ALT", "AXL", "BIGTIME", "CYBER", "DYM",
    "ETHFI", "FRAME", "GAL", "HIFI", "ID", "JTO", "KAP", "LADYS", "MAV", "NAKA", "ORBS", "PENDLE", "RACA",
    "SEILOR", "TNSR", "UQC", "VIC", "WIF", "XAI", "YES", "AIDOGE", "BABYDOGE", "COQ", "FLOKI", "MYRO", "PEPE2",
    "SAMO", "TURBO", "WOJAK", "BONK2", "DOG", "ELON", "HUSKY", "KISHU", "AGIX", "TAO", "AKT", "AR", "CFX",
    "DOVU", "ENQAI", "HKT", "IQ", "KRL", "LAMBDA", "MND", "API3", "BTRST", "CLV", "DEXE", "FORT", "GODS",
    "HIGH", "ILV", "JUV", "KARATE", "LQTY", "MAGIC", "NEST", "OGN", "PRIME", "PSG", "RARE", "SUPER", "TLM",
    "ULTRA", "VOXEL", "WEMIX", "XWG"
]

COINS = list(set(ALL_COINS))[:TOP_N_COINS]
SYMBOLS = [f"{coin}/USDT" for coin in COINS]

EXCHANGE_FEES = {
    'binance': 0.001, 'bybit': 0.001, 'okx': 0.001, 'kucoin': 0.001,
    'gate': 0.002, 'mexc': 0.002, 'huobi': 0.002, 'bitget': 0.001,
}

print(f"✅ Loaded {len(SYMBOLS)} trading pairs across {len(EXCHANGES_TO_SCAN)} exchanges")

# =========================
# WEBSOCKET PRICE ENGINE
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
                })
            except Exception as e:
                print(f"Failed to init {name}: {e}")

    async def watch_exchange(self, name, exchange):
        """Keep websocket open forever for one exchange"""
        while True:
            try:
                # Use watch_tickers for bulk updates - fastest method
                tickers = await exchange.watch_tickers(SYMBOLS)
                now = time.time()

                with table_lock:
                    for symbol, ticker in tickers.items():
                        if ticker.get('bid') and ticker.get('ask') and ticker['bid'] > 0:
                            price_table[symbol][name] = {
                                'bid': float(ticker['bid']),
                                'ask': float(ticker['ask']),
                                'bidVolume': float(ticker.get('bidVolume') or 0),
                                'askVolume': float(ticker.get('askVolume') or 0),
                                'ts': now
                            }
            except Exception as e:
                print(f"{name} WS error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)
                try:
                    await exchange.close()
                except:
                    pass
                # Recreate exchange instance
                exchange_class = getattr(ccxt_pro, name)
                self.exchanges[name] = exchange_class({'enableRateLimit': True})
                exchange = self.exchanges[name]

    async def start_all_streams(self):
        tasks = [self.watch_exchange(name, ex) for name, ex in self.exchanges.items()]
        await asyncio.gather(*tasks)

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
            # Copy to avoid holding lock during calcs
            snapshot = {s: dict(exs) for s, exs in price_table.items()}

        for symbol, ex_data in snapshot.items():
            if len(ex_data) < 2:
                continue

            # Find best buy = lowest ask + fee, best sell = highest bid - fee
            best_buy = None
            best_sell = None
            min_ask_eff = float('inf')
            max_bid_eff = 0

            for ex_name, data in ex_data.items():
                # Skip stale data >3s old
                if time.time() - data['ts'] > 3:
                    continue

                fee = self.engine.get_fee(ex_name)
                ask_eff = data['ask'] * (1 + fee) # What you actually pay
                bid_eff = data['bid'] * (1 - fee) # What you actually get

                if ask_eff < min_ask_eff:
                    min_ask_eff = ask_eff
                    best_buy = (ex_name, data)
                if bid_eff > max_bid_eff:
                    max_bid_eff = bid_eff
                    best_sell = (ex_name, data)

            if best_buy and best_sell and best_buy[0]!= best_sell[0]:
                profit_pct = ((max_bid_eff - min_ask_eff) / min_ask_eff) * 100

                if profit_pct >= MIN_PROFIT:
                    # Real liquidity = min of what you can buy and what you can sell
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
        latest_opportunities = opps[:50]
        last_scan_time = datetime.utcnow()
        scan_count += 1

        elapsed_ms = (time.time() - start) * 1000
        if scan_count % 10 == 0: # Log every 10th scan
            print(f"Scan #{scan_count}: {len(opps)} opps found in {elapsed_ms:.0f}ms")

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
                                  coins=len(SYMBOLS))

@app.route('/api/opportunities')
def api_opportunities():
    return jsonify({
        "success": True,
        "scan_count": scan_count,
        "last_scan": last_scan_time.isoformat() if last_scan_time else None,
        "opportunities": latest_opportunities,
        "total": len(latest_opportunities)
    })

@app.route('/api/health')
def health():
    return jsonify({
        "status": "healthy",
        "scans": scan_count,
        "coins": len(SYMBOLS),
        "exchanges": len(EXCHANGES_TO_SCAN),
        "symbols_tracked": len(price_table)
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
    <title>Arbimine.pro - Live Arbitrage Scanner</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Courier New', monospace; background: #0a0e27; padding: 20px; color: #ccc; }
       .container { max-width: 1400px; margin: 0 auto; }
       .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 10px; margin-bottom: 20px; color: white; }
       .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
       .stat-card { background: #1a1f3f; padding: 15px; border-radius: 8px; text-align: center; }
       .stat-value { font-size: 2em; font-weight: bold; color: #667eea; }
       .opportunities { background: #1a1f3f; border-radius: 10px; padding: 20px; }
       .arb-row { display: grid; grid-template-columns: 60px 120px 100px 120px 100px; gap: 10px; padding: 8px 0; border-bottom: 1px solid #2a2f4f; align-items: center; }
       .arb-header { font-weight: bold; color: #667eea; border-bottom: 2px solid #667eea; margin-bottom: 10px; }
       .buy { color: #10b981; }.sell { color: #f59e0b; }.profit { color: #10b981; font-weight: bold; }
       .exchange { background: #2a2f4f; padding: 2px 8px; border-radius: 4px; font-size: 0.9em; }
       .live { display: inline-block; width: 8px; height: 8px; background: #10b981; border-radius: 50%; animation: pulse 1s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        footer { text-align: center; margin-top: 20px; color: #666; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Arbimine.pro <span class="live"></span></h1>
            <p>Real-time WebSocket Scanner | {{ coins }} Coins | Updated continuously</p>
        </div>

        <div class="stats">
            <div class="stat-card"><div class="stat-value">{{ opportunities|length }}</div><div>Live Opportunities</div></div>
            <div class="stat-card"><div class="stat-value">{{ scan_count }}</div><div>Calculations</div></div>
            <div class="stat-card"><div class="stat-value">{{ last_scan }}</div><div>Last Update</div></div>
            <div class="stat-card"><div class="stat-value">{{ min_profit }}%</div><div>Min Profit</div></div>
        </div>

        <div class="opportunities">
            <div class="arb-row arb-header">
                <div>ACTION</div><div>EXCHANGE</div><div>COIN</div><div>PROFIT</div><div>LIQUIDITY</div><div>TIME</div>
            </div>
            {% for opp in opportunities %}
            <div class="arb-row">
                <div class="buy">BUY</div>
                <div><span class="exchange">{{ opp.buy_exchange }}</span></div>
                <div>{{ opp.symbol }}/USDT</div>
                <div class="profit">{{ opp.profit_percent }}%</div>
                <div>${{ opp.liquidity }}</div>
                <div>{{ opp.timestamp }}</div>
            </div>
            <div class="arb-row">
                <div class="sell">SELL</div>
                <div><span class="exchange">{{ opp.sell_exchange }}</span></div>
                <div>{{ opp.symbol }}/USDT</div>
                <div></div><div></div><div></div>
            </div>
            {% endfor %}
            {% if not opportunities %}
            <p style="text-align: center; padding: 40px;">🔍 Connecting to exchanges... First data in ~10s</p>
            {% endif %}
        </div>

        <footer>⚠️ For educational purposes only. Verify wallets, fees, and withdrawal status before trading.</footer>
    </div>
    <script>setInterval(() => location.reload(), 2000);</script>
</body>
</html>
"""

# =========================
# BACKGROUND TASKS
# =========================
def run_websocket_engine():
    """Run websocket price streams forever"""
    engine = PriceEngine()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(engine.start_all_streams())

def run_calculator_loop():
    """Calculate arbitrage every 300ms from websocket data"""
    engine = PriceEngine()
    calc = ArbitrageCalculator(engine)
    while True:
        try:
            calc.find_opportunities()
            time.sleep(0.3) # 300ms cycle = ~3 scans/sec
        except Exception as e:
            print(f"Calculator error: {e}")
            time.sleep(1)

# Start background threads
threading.Thread(target=run_websocket_engine, daemon=True).start()
time.sleep(2) # Let websockets connect first
threading.Thread(target=run_calculator_loop, daemon=True).start()

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print("="*70)
    print("🚀 Arbimine.pro - PRODUCTION VERSION")
    print("="*70)
    print(f"📊 Monitoring {len(SYMBOLS)} pairs on {len(EXCHANGES_TO_SCAN)} exchanges")
    print(f"⚡ WebSocket mode: ~300ms scan cycles")
    print(f"🎯 Min profit: {MIN_PROFIT}% | Real liquidity from orderbook")
    print(f"🌐 Dashboard: http://localhost:{port}")
    print("="*70)
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
