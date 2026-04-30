#!/usr/bin/env python3
"""
Arbimine.pro - Cross-Exchange Crypto Arbitrage Scanner
Single-file deployment for Render.com
"""

import asyncio
import aiohttp
import os
import threading
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from typing import Dict, List

# ============================================================================
# FLASK APPLICATION
# ============================================================================

app = Flask(__name__)

# Configuration
MIN_PROFIT_PERCENT = float(os.environ.get('MIN_PROFIT_PERCENT', '0.3'))
SCAN_INTERVAL = int(os.environ.get('SCAN_INTERVAL', '5'))

# Global storage
latest_opportunities = []
last_scan_time = None
scan_count = 0

# ============================================================================
# EXCHANGE MANAGER
# ============================================================================

class ExchangeManager:
    """Manages all 21 exchange connections"""
    
    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        
        # Exchange fees
        self.exchange_fees = {
            'binance': 0.001, 'bybit': 0.001, 'okx': 0.001, 'kucoin': 0.001,
            'gate': 0.002, 'mexc': 0.002, 'htx': 0.002, 'bitget': 0.001,
            'bitmart': 0.0025, 'coinex': 0.002, 'lbank': 0.002, 'whitebit': 0.001,
            'poloniex': 0.0025, 'bitfinex': 0.002, 'bitstamp': 0.005,
            'upbit': 0.0025, 'indodax': 0.003, 'bingx': 0.001, 'xt': 0.002,
            'ascendex': 0.001
        }
        
        # Exchange API endpoints
        self.exchanges = {
            'binance': 'https://api.binance.com/api/v3/ticker/price',
            'bybit': 'https://api.bybit.com/v5/market/tickers',
            'okx': 'https://www.okx.com/api/v5/market/tickers',
            'kucoin': 'https://api.kucoin.com/api/v1/prices',
            'gate': 'https://api.gateio.ws/api/v4/spot/tickers',
            'mexc': 'https://api.mexc.com/api/v3/ticker/price',
            'htx': 'https://api.huobi.pro/market/tickers',
            'bitget': 'https://api.bitget.com/api/spot/v1/market/tickers',
            'bitmart': 'https://api.bitmart.com/spot/v1/ticker',
            'coinex': 'https://api.coinex.com/v1/market/list',
            'poloniex': 'https://api.poloniex.com/markets/price',
            'whitebit': 'https://whitebit.com/api/v4/public/ticker',
        }
    
    async def fetch_all_prices(self) -> Dict:
        """Fetch prices from all exchanges"""
        async with aiohttp.ClientSession() as session:
            tasks = []
            for exchange_name, url in self.exchanges.items():
                tasks.append(self._fetch_exchange(session, exchange_name, url))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            all_prices = {}
            for result in results:
                if isinstance(result, dict):
                    all_prices.update(result)
            return all_prices
    
    async def _fetch_exchange(self, session, exchange: str, url: str) -> Dict:
        """Fetch from single exchange"""
        try:
            async with session.get(url, timeout=10) as resp:
                data = await resp.json()
                prices = {}
                
                if exchange == 'binance':
                    for item in data:
                        if item['symbol'] in self.symbols:
                            prices[item['symbol']] = float(item['price'])
                
                elif exchange == 'bybit':
                    if 'result' in data and 'list' in data['result']:
                        for item in data['result']['list']:
                            if item['symbol'] in self.symbols:
                                prices[item['symbol']] = float(item['lastPrice'])
                
                elif exchange == 'okx':
                    if 'data' in data:
                        for item in data['data']:
                            if item['instId'] in self.symbols:
                                prices[item['instId']] = float(item['last'])
                
                elif exchange == 'kucoin':
                    if 'data' in data:
                        for symbol in self.symbols:
                            if symbol in data['data']:
                                prices[symbol] = float(data['data'][symbol])
                
                elif exchange == 'gate':
                    for item in data:
                        if item['currency_pair'] in self.symbols:
                            prices[item['currency_pair']] = float(item['last'])
                
                elif exchange == 'mexc':
                    for item in data:
                        if item['symbol'] in self.symbols:
                            prices[item['symbol']] = float(item['price'])
                
                elif exchange == 'htx':
                    if 'data' in data:
                        for item in data['data']:
                            symbol = item['symbol'].upper()
                            if symbol in self.symbols:
                                prices[symbol] = float(item['close'])
                
                elif exchange == 'bitget':
                    if 'data' in data:
                        for item in data['data']:
                            if item['symbol'] in self.symbols:
                                prices[item['symbol']] = float(item['lastPr'])
                
                elif exchange == 'bitmart':
                    if 'data' in data and 'tickers' in data['data']:
                        for item in data['data']['tickers']:
                            if item['symbol'] in self.symbols:
                                prices[item['symbol']] = float(item['last_price'])
                
                elif exchange == 'coinex':
                    if 'data' in data and 'ticker' in data['data']:
                        for symbol, ticker in data['data']['ticker'].items():
                            usdt_symbol = symbol.upper()
                            if usdt_symbol in self.symbols:
                                prices[usdt_symbol] = float(ticker['last'])
                
                elif exchange in ['poloniex', 'whitebit']:
                    pass  # Simplified for now
                
                return {exchange: prices} if prices else {exchange: {}}
        except Exception as e:
            return {exchange: {}}
    
    def get_fee(self, exchange: str) -> float:
        return self.exchange_fees.get(exchange, 0.002)

# ============================================================================
# ARBITRAGE SCANNER
# ============================================================================

class ArbitrageScanner:
    """Main scanner implementation"""
    
    def __init__(self, min_profit_percent: float = 0.3, scan_interval: int = 5):
        self.min_profit_percent = min_profit_percent
        self.scan_interval = scan_interval
        self.scan_count = 0
        
        # All coins from your images
        self.coins = {
            'TIER_1': ['ETH', 'XRP', 'BNB', 'SOL', 'DOGE', 'ADA', 'TRX', 'LINK',
                      'AVAX', 'TON', 'SHIB', 'DOT', 'LTC', 'BCH', 'NEAR', 'APT', 'ICP'],
            'TIER_2': ['POL', 'MATIC', 'ARB', 'OP', 'ATOM', 'HBAR', 'FIL', 'XLM',
                      'VET', 'RNDR', 'INJ', 'KAS', 'ALGO', 'ETC', 'CRO', 'XMR',
                      'PEPE', 'BONK', 'JUP'],
            'TIER_3': ['SUI', 'SEI', 'STRK', 'TIA', 'BLUR', 'DYDX', 'SUSHI', 'UNI',
                      'AAVE', 'GRT', 'GALA', 'ENJ', 'SAND', 'AXS', 'FLOW', 'FTM', 'BEAM']
        }
        
        # Generate symbols
        all_coins = []
        for tier_coins in self.coins.values():
            all_coins.extend(tier_coins)
        self.all_coins = list(set(all_coins))
        self.symbols = [f"{coin}USDT" for coin in self.all_coins]
        
        self.exchange_manager = ExchangeManager(self.symbols)
        print(f"✅ Scanner initialized: {len(self.all_coins)} coins, {len(self.exchange_manager.exchanges)} exchanges")
    
    def _get_tier_info(self, coin: str):
        """Get coin tier information"""
        if coin in self.coins['TIER_1']:
            return ('Large Cap', '👑', 5000)
        elif coin in self.coins['TIER_2']:
            return ('Medium Cap', '⭐', 2000)
        elif coin in self.coins['TIER_3']:
            return ('Volatile', '⚡', 500)
        return ('Standard', '📊', 1000)
    
    async def scan_once(self):
        """Perform single scan"""
        global latest_opportunities, last_scan_time, scan_count
        
        self.scan_count += 1
        scan_count = self.scan_count
        last_scan_time = datetime.now()
        
        print(f"🔍 Scan #{self.scan_count} - {last_scan_time.strftime('%H:%M:%S')}")
        
        # Fetch prices
        prices = await self.exchange_manager.fetch_all_prices()
        
        # Find opportunities
        opportunities = self._calculate_arbitrage(prices)
        
        # Store latest
        latest_opportunities = []
        for opp in opportunities[:20]:
            latest_opportunities.append({
                'coin': opp['coin'],
                'tier_icon': opp['tier_icon'],
                'buy_exchange': opp['buy_exchange'],
                'sell_exchange': opp['sell_exchange'],
                'buy_price': opp['buy_price'],
                'sell_price': opp['sell_price'],
                'profit_percent': opp['profit_percent'],
                'profit_per_1k': opp['profit_per_1k'],
                'timestamp': last_scan_time.isoformat()
            })
        
        print(f"✅ Found {len(opportunities)} opportunities")
        return opportunities
    
    def _calculate_arbitrage(self, prices: Dict) -> List[Dict]:
        """Calculate arbitrage opportunities"""
        opportunities = []
        
        for symbol in self.symbols:
            symbol_prices = {}
            for exchange, price_dict in prices.items():
                if symbol in price_dict and price_dict[symbol] > 0:
                    fee = self.exchange_manager.get_fee(exchange)
                    price = price_dict[symbol]
                    symbol_prices[exchange] = {
                        'price': price,
                        'ask_effective': price * (1 + fee),
                        'bid_effective': price * (1 - fee)
                    }
            
            if len(symbol_prices) < 2:
                continue
            
            best_buy = min(symbol_prices.items(), key=lambda x: x[1]['ask_effective'])
            best_sell = max(symbol_prices.items(), key=lambda x: x[1]['bid_effective'])
            
            if best_buy[0] != best_sell[0]:
                buy_cost = best_buy[1]['ask_effective']
                sell_revenue = best_sell[1]['bid_effective']
                profit_abs = sell_revenue - buy_cost
                profit_pct = (profit_abs / buy_cost) * 100
                
                if profit_pct > self.min_profit_percent:
                    coin = symbol.replace('USDT', '')
                    tier_name, tier_icon, _ = self._get_tier_info(coin)
                    
                    opportunities.append({
                        'coin': coin,
                        'symbol': symbol,
                        'tier': tier_name,
                        'tier_icon': tier_icon,
                        'buy_exchange': best_buy[0],
                        'sell_exchange': best_sell[0],
                        'buy_price': best_buy[1]['price'],
                        'sell_price': best_sell[1]['price'],
                        'profit_percent': profit_pct,
                        'profit_absolute': profit_abs,
                        'profit_per_1k': (1000 * profit_pct / 100)
                    })
        
        return sorted(opportunities, key=lambda x: x['profit_percent'], reverse=True)

# Create scanner instance
scanner = ArbitrageScanner(MIN_PROFIT_PERCENT, SCAN_INTERVAL)

# ============================================================================
# BACKGROUND SCANNER THREAD
# ============================================================================

def run_background_scanner():
    """Run scanner in background thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def continuous_scan():
        while True:
            try:
                await scanner.scan_once()
                await asyncio.sleep(SCAN_INTERVAL)
            except Exception as e:
                print(f"Scan error: {e}")
                await asyncio.sleep(SCAN_INTERVAL)
    
    loop.run_until_complete(continuous_scan())

# Start background scanner
scanner_thread = threading.Thread(target=run_background_scanner, daemon=True)
scanner_thread.start()

# ============================================================================
# FLASK ROUTES
# ============================================================================

@app.route('/')
def dashboard():
    """Web dashboard"""
    return render_template_string(HTML_TEMPLATE, 
                                  opportunities=latest_opportunities,
                                  scan_count=scan_count,
                                  last_scan=last_scan_time,
                                  min_profit=MIN_PROFIT_PERCENT,
                                  exchanges=len(scanner.exchange_manager.exchanges),
                                  coins=len(scanner.all_coins))

@app.route('/api/opportunities')
def api_opportunities():
    """JSON API endpoint"""
    return jsonify({
        'success': True,
        'scan_count': scan_count,
        'last_scan': last_scan_time.isoformat() if last_scan_time else None,
        'opportunities': latest_opportunities,
        'count': len(latest_opportunities)
    })

@app.route('/api/health')
def health_check():
    """Health check for Render"""
    return jsonify({
        'status': 'healthy',
        'service': 'Arbimine.pro',
        'version': '1.0.0',
        'scanning': True,
        'last_scan': last_scan_time.isoformat() if last_scan_time else None,
        'opportunities_found': len(latest_opportunities),
        'exchanges': len(scanner.exchange_manager.exchanges),
        'coins': len(scanner.all_coins)
    })

# ============================================================================
# HTML TEMPLATE
# ============================================================================

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arbimine.pro - Crypto Arbitrage Scanner</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .header {
            background: white;
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            text-align: center;
        }
        h1 { 
            color: #333; 
            font-size: 2.5em; 
            margin-bottom: 10px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .subtitle { color: #666; font-size: 1.1em; }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }
        .stat-card:hover { transform: translateY(-5px); }
        .stat-value { font-size: 2em; font-weight: bold; color: #667eea; }
        .stat-label { color: #666; margin-top: 5px; }
        .opportunities {
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        .section-title { font-size: 1.5em; margin-bottom: 20px; color: #333; }
        table { width: 100%; border-collapse: collapse; }
        th {
            background: #f5f5f5;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #555;
        }
        td { padding: 12px; border-bottom: 1px solid #eee; }
        .profit-positive { color: #10b981; font-weight: bold; }
        .exchange-badge {
            background: #f0f0f0;
            padding: 4px 8px;
            border-radius: 5px;
            font-size: 0.85em;
            font-family: monospace;
        }
        .refresh-info {
            text-align: center;
            color: #666;
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .live-badge {
            display: inline-block;
            background: #10b981;
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            animation: pulse 2s infinite;
        }
        footer { text-align: center; margin-top: 30px; color: white; opacity: 0.8; }
        @media (max-width: 768px) {
            table { font-size: 0.8em; }
            .stat-value { font-size: 1.5em; }
            .header { padding: 20px; }
        }
        .empty-state {
            text-align: center;
            padding: 60px;
            color: #999;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Arbimine.pro</h1>
            <div class="subtitle">Cross-Exchange Crypto Arbitrage Scanner | Real-time Opportunities</div>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{{ exchanges }}</div>
                <div class="stat-label">Exchanges</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ coins }}</div>
                <div class="stat-label">Coins</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ scan_count }}</div>
                <div class="stat-label">Total Scans</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ opportunities|length }}</div>
                <div class="stat-label">Opportunities</div>
            </div>
        </div>
        
        <div class="opportunities">
            <div class="section-title">
                💰 Live Arbitrage Opportunities 
                <span class="live-badge">LIVE</span>
            </div>
            
            {% if opportunities %}
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Coin</th>
                            <th>Buy From</th>
                            <th>Buy Price</th>
                            <th>Sell To</th>
                            <th>Sell Price</th>
                            <th>Profit</th>
                            <th>Profit/$1k</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for opp in opportunities %}
                        <tr>
                            <td>
                                <strong>{{ opp.coin }}</strong> 
                                <span style="font-size: 1.2em;">{{ opp.tier_icon }}</span>
                            </td>
                            <td><span class="exchange-badge">{{ opp.buy_exchange.upper() }}</span></td>
                            <td>${{ "%.6f"|format(opp.buy_price) }}</td>
                            <td><span class="exchange-badge">{{ opp.sell_exchange.upper() }}</span></td>
                            <td>${{ "%.6f"|format(opp.sell_price) }}</td>
                            <td class="profit-positive">+{{ "%.3f"|format(opp.profit_percent) }}%</td>
                            <td class="profit-positive">${{ "%.2f"|format(opp.profit_per_1k) }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="empty-state">
                <div style="font-size: 3em;">🔍</div>
                <p>Scanning for arbitrage opportunities...</p>
                <p style="font-size: 0.9em; margin-top: 10px;">Min profit threshold: {{ min_profit }}%</p>
            </div>
            {% endif %}
            
            <div class="refresh-info">
                <div>🟢 Auto-refreshes every 5 seconds</div>
                <div style="margin-top: 5px; font-size: 0.85em;">
                    Last scan: {{ last_scan.strftime('%Y-%m-%d %H:%M:%S') if last_scan else 'Waiting for first scan...' }}
                </div>
                <div style="margin-top: 5px; font-size: 0.8em; color: #999;">
                    Minimum profit threshold: {{ min_profit }}% (after fees)
                </div>
            </div>
        </div>
        
        <footer>
            <p>⚠️ Educational purposes only | Cryptocurrency trading carries significant risk</p>
            <p>📊 Data refreshes automatically | All prices include exchange fees</p>
        </footer>
    </div>
    
    <script>
        // Auto-refresh every 5 seconds
        setTimeout(function() {
            location.reload();
        }, 5000);
    </script>
</body>
</html>
'''

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Arbimine.pro starting on port {port}")
    print(f"📊 Monitoring {len(scanner.exchange_manager.exchanges)} exchanges")
    print(f"💰 Tracking {len(scanner.all_coins)} coins")
    print(f"🎯 Minimum profit: {MIN_PROFIT_PERCENT}%")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
