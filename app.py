#!/usr/bin/env python3
import os
import asyncio
import threading
import time
import requests
import gc
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
import ccxt.pro as ccxt_pro

app = Flask(__name__)
CORS(app)

# =========================
# CONFIGURATION
# =========================
MIN_PROFIT = float(os.getenv("MIN_PROFIT", "0.1"))
MIN_LIQUIDITY = int(os.getenv("MIN_LIQUIDITY", "1000"))
TOP_N_COINS = 300

EXCHANGES_TO_SCAN = {
    'mexc': 'mexc',
    'kucoin': 'kucoin', 
    'coinex': 'coinex',
    'bitmart': 'bitmart',
    'gateio': 'gateio',
}

# Global state
latest_opportunities = []
last_scan_time = None
scan_count = 0
price_table = {}
top_300_symbols = []
symbol_count_by_exchange = {}
exchange_status = {}
table_lock = threading.Lock()

EXCHANGE_FEES = {
    'mexc': 0.002, 'kucoin': 0.001, 'coinex': 0.002,
    'bitmart': 0.0025, 'gateio': 0.002,
}

# =========================
# TOP 300 COIN FETCHER
# =========================
def get_top_300_coins():
    global top_300_symbols
    if top_300_symbols:
        return top_300_symbols
    
    try:
        print("🔍 Fetching top 300 coins...")
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {'vs_currency': 'usd', 'order': 'volume_desc', 'per_page': 250, 'page': 1}
        r1 = requests.get(url, params=params, timeout=20)
        
        coins = []
        if isinstance(r1.json(), list):
            coins.extend(r1.json())
        
        params['page'] = 2
        r2 = requests.get(url, params=params, timeout=20)
        if isinstance(r2.json(), list):
            coins.extend(r2.json())
        
        if coins:
            top_300_symbols = [f"{c['symbol'].upper()}/USDT" for c in coins][:TOP_N_COINS]
            print(f"✅ Loaded {len(top_300_symbols)} coins")
        else:
            raise Exception("CoinGecko returned no valid data")
            
        return top_300_symbols
    except Exception as e:
        print(f"CoinGecko error: {e}. Using fallback")
        fallback = ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","TRX","LINK","AVAX","TON","SHIB","DOT","LTC","BCH","NEAR","APT","MATIC","ARB","OP","SUI","PEPE","WIF","BONK","SEI","TIA","INJ","FET","RNDR","TAO","WLD","PYTH","JUP","DOGS","NOT","ORDI","1000SATS","FLOKI","LUNC","LUNA","ATOM","ICP","FTM","HBAR","CRO","VET","FIL","XLM","ALGO","EGLD","AXS","MANA","SAND","APE","CHZ","GRT","IMX","FLOW","XTZ","EOS","NEO","KAVA","CAKE","1INCH","CRV","AAVE","MKR","SNX","COMP","UNI","SUSHI","ZRX","BAT","ENJ","OMG","KNC","LRC","BAND","ANKR","STORJ","SKL","REN","BAL","YFI","BADGER","ALPHA","REEF","CTSI","OCEAN","ROSE","CELR","ONE","ZIL","ONT","QTUM","ICX","IOST","WAVES","DASH","XMR","ZEC","ZEN","RVN","DGB","SC","XEM","NANO","KSM","GLMR","MOVR","ASTR","ACA","PARA","XOR","VAL","PSWAP","KAR","BNC","AIR","PHALA","CRAB","LT","RING","KMA","TEER","BSX","CHAOS","MATH","MIR","LIT","PDEX","BPX","HKO","KMW","KUSD","KINT","EQ","EQD","ZERO","ZLK","MOM","RMRK","DED","PINK","GMX","GALA","LDO","ENS","BLUR","RPL","MASK","AGIX","DYDX","STX","KAS","CFX","RUNE","PENDLE","SSV","AR","MINA","IOTA","XDC","QNT","THETA","GALA","LDO","BLUR","RPL","ENS","SSV","PENDLE","ARKM","C98","ID","EDU","SUI","TIA","PYTH","JUP","JTO","DYM","STRK","PIXEL","PORTAL","ALT","MANTA","ONDO","AEVO","ETHFI","ENA","W","TNSR","SAGA","TAO","OMNI","REZ","BB","NOT","IO","ZK","ZRO","LISTA","G","BANANA","RENDER","NOT","DOGS","HMSTR","CATI","PNUT","ACT","GOAT","MOODENG","X","CHILLGUY","BAN","PUFFER","SWELL","GRASS","DRIFT","ME","MOVE","VANA","PENGU","USUAL","FARTCOIN","AIXBT","VIRTUAL","AI16Z","ARC","GRIFFAIN","ZEREBRO","ELIZA","COOKIE","AVA","MORPHO","DBR","SPX","MOG","NPC","BRETT","DEGEN","TOSHI","KEYCAT","HIGHER","DOGINME","TYBG","WOLF","GIGA","POPCAT","MICHI","FWOG","SCF","RETARDIO","SIGMA","HARAMBE","BITCOIN","PEPECOIN","WOJAK","MEME","TURBO","LADYS","PEPE2","PONKE","ANDY","LANDWOLF","MYRO","WEN","SLERF","BOME","WEN","JUP","JTO","PYTH","RAY","ORCA","MNGO","COPE","STEP","SAMO","KIN","FIDA","MAPS","MEDIA","ATLAS","POLIS","STAR","GST","GMT","APEX","PERP","HEGIC","RARI","MASK","RARE","SUPER","GHST","AXS","SLP","YGG","ALICE","TLM","SAND","MANA","ENJ","ILV","GODS","PYR","DAR","VGX","WIN","BTT","JST","SUN","NFT"]
        top_300_symbols = [f"{s}/USDT" for s in fallback[:TOP_N_COINS]]
        return top_300_symbols

# =========================
# PRICE ENGINE - FIXED STATUS UPDATE
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
                exchange_status[name] = f"init_failed"

    async def get_available_symbols(self, exchange, coins):
        try:
            await exchange.load_markets()
            available = [s for s in coins if s in exchange.markets and exchange.markets[s].get('active')]
            exchange.markets = {}
            gc.collect()
            return available
        except Exception as e:
            print(f"Market load error: {type(e).__name__}")
            exchange.markets = {}
            gc.collect()
            return []

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
            items = list(price_table.items())

        for symbol, ex_data in items:
            if len(ex_data) < 2:
                continue

            best_buy = None
            best_sell = None
            min_ask_eff = float('inf')
            max_bid_eff = 0

            for ex_name, data in ex_data.items():
                if time.time() - data['ts'] > 90:
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
        latest_opportunities = opps[:50]
        last_scan_time = datetime.utcnow()
        scan_count += 1
        print(f"Scan #{scan_count}: {len(opps)} opps from {len(items)} symbols")
        del items, opps
        gc.collect()

# =========================
# BACKGROUND TASKS - FIXED STATUS
# =========================
async def fetch_exchange_sequential(name, exchange, coins):
    try:
        available = await engine.get_available_symbols(exchange, coins)
        symbol_count_by_exchange[name] = len(available)
        
        if len(available) == 0:
            exchange_status[name] = "no_pairs"
            return name, 0
            
        # CRITICAL FIX: Update status to "ready" after discovery
        exchange_status[name] = f"ready: {len(available)}"
        
        batch_size = 40
        total_count = 0
        for i in range(0, len(available), batch_size):
            batch = available[i:i+batch_size]
            tickers = await exchange.fetch_tickers(batch)
            now = time.time()
            
            with table_lock:
                for symbol, ticker in tickers.items():
                    if ticker.get('bid') and ticker.get('ask') and ticker['bid'] > 0:
                        if symbol not in price_table:
                            price_table[symbol] = {}
                        price_table[symbol][name] = {
                            'bid': float(ticker['bid']),
                            'ask': float(ticker['ask']),
                            'bidVolume': float(ticker.get('quoteVolume') or 0),
                            'askVolume': float(ticker.get('quoteVolume') or 0),
                            'ts': now
                        }
                        total_count += 1
            
            del tickers
            gc.collect()
            await asyncio.sleep(0.4)
        
        exchange_status[name] = f"live: {total_count}"
        return name, total_count
    except Exception as e:
        exchange_status[name] = f"error"
        print(f"[{name}] Error: {e}")
        return name, 0

def run_rest_poller():
    global engine
    engine = PriceEngine()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def poll_sequential():
        coins = get_top_300_coins()
        
        while True:
            start = time.time()
            total_updates = 0
            
            for name, exchange in engine.exchanges.items():
                print(f"Polling {name}...")
                _, count = await fetch_exchange_sequential(name, exchange, coins)
                total_updates += count
                gc.collect()
                await asyncio.sleep(3)
            
            elapsed = time.time() - start
            print(f"Full poll cycle: {total_updates} prices in {elapsed:.1f}s")
            gc.collect()
            await asyncio.sleep(max(60, 180 - elapsed))
    
    loop.run_until_complete(poll_sequential())

def run_calculator_loop():
    engine = PriceEngine()
    calc = ArbitrageCalculator(engine)
    while True:
        try:
            calc.find_opportunities()
            time.sleep(15)
        except Exception as e:
            print(f"Calculator error: {e}")
            time.sleep(15)

# Start threads
threading.Thread(target=run_rest_poller, daemon=True).start()
time.sleep(60)
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
                                  coins=len(top_300_symbols),
                                  exchanges=symbol_count_by_exchange,
                                  status=exchange_status)

@app.route('/api/debug')
def debug():
    with table_lock:
        tracked = len(price_table)
        symbols_with_2plus = sum(1 for s in price_table.values() if len(s) >= 2)
    active_count = sum(1 for s in exchange_status.values() if 'live' in s or 'ready' in s)
    return jsonify({
        "scan_count": scan_count,
        "total_coins": len(top_300_symbols),
        "symbols_tracked": tracked,
        "symbols_on_2plus_exchanges": symbols_with_2plus,
        "exchange_status": exchange_status,
        "symbols_per_exchange": symbol_count_by_exchange,
        "active_count": f"{active_count}/5"
    })

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arbimine.pro - 300 Coins</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Courier New', monospace; background: #0a0e27; padding: 15px; color: #ccc; }
.container { max-width: 1800px; margin: 0 auto; }
.header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 10px; margin-bottom: 20px; color: white; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 10px; margin-bottom: 20px; }
.stat-card { background: #1a1f3f; padding: 10px; border-radius: 8px; text-align: center; }
.stat-value { font-size: 1.2em; font-weight: bold; color: #667eea; }
.stat-label { font-size: 0.6em; opacity: 0.8; }
.opportunities { background: #1a1f3f; border-radius: 10px; padding: 15px; overflow-x: auto; }
.arb-row { display: grid; grid-template-columns: 35px 60px 60px 50px 55px 75px; gap: 6px; padding: 5px 0; border-bottom: 1px solid #2a2f4f; align-items: center; font-size: 0.7em; }
.arb-header { font-weight: bold; color: #667eea; border-bottom: 2px solid #667eea; margin-bottom: 8px; }
.buy { color: #10b981; }.sell { color: #f59e0b; }.profit { color: #10b981; font-weight: bold; }
.exchange { background: #2a2f4f; padding: 2px 3px; border-radius: 3px; font-size: 0.55em; }
.live { display: inline-block; width: 8px; height: 8px; background: #10b981; border-radius: 50%; animation: pulse 1s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        footer { text-align: center; margin-top: 15px; color: #666; font-size: 0.6em; }
.debug { background: #2a2f4f; padding: 8px; border-radius: 5px; margin: 10px 0; font-size: 0.6em; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Arbimine.pro <span class="live"></span></h1>
            <p>5 Exchanges | 300 Coins | Render Optimized</p>
        </div>

        <div class="stats">
            <div class="stat-card"><div class="stat-value">{{ opportunities|length }}</div><div class="stat-label">Opps</div></div>
            <div class="stat-card"><div class="stat-value">{{ coins }}</div><div class="stat-label">Coins</div></div>
            <div class="stat-card"><div class="stat-value">{{ exchanges|selectattr('value')|list|length }}/5</div><div class="stat-label">Active</div></div>
            <div class="stat-card"><div class="stat-value">{{ scan_count }}</div><div class="stat-label">Scans</div></div>
            <div class="stat-card"><div class="stat-value">{{ last_scan }}</div><div class="stat-label">Updated</div></div>
            <div class="stat-card"><div class="stat-value">{{ min_profit }}%</div><div class="stat-label">Min</div></div>
        </div>

        <div class="debug">
            <b>Status:</b> {% for ex, stat in status.items() %}{{ ex }}:{{ stat }} | {% endfor %}
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
            <p style="text-align: center; padding: 30px;">🔍 Scanning 300 coins... Full cycle = ~4 min. Check /api/debug</p>
            {% endif %}
        </div>

        <footer>
            Active: {% for ex, count in exchanges.items() if count > 0 %}{{ ex }}:{{ count }} {% endfor %}
        </footer>
    </div>
    <script>setInterval(() => location.reload(), 20000);</script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print("="*70)
    print("🚀 Arbimine.pro - 300 COIN VERSION")
    print("="*70)
    print(f"📊 Exchanges: MEXC, KuCoin, CoinEx, BitMart, Gate.io")
    print(f"⚡ 300 coins | 3-4 min cycles | ~280MB RAM usage")
    print(f"🌐 Dashboard: http://localhost:{port} | Debug: /api/debug")
    print("="*70)
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
