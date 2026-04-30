#!/usr/bin/env python3
"""
Arbitrage Scanner Web Service for Render.com
Runs continuously and serves a web dashboard
"""

import asyncio
import sys
import json
import os
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from threading import Thread
from colorama import init, Fore, Style
from exchanges import ExchangeManager
from arbitrage import ArbitrageCalculator

# Initialize colorama
init(autoreset=True)

# Create Flask app
app = Flask(__name__)

# Global storage for latest opportunities
latest_opportunities = []
last_scan_time = None
scan_count = 0

# Configuration from environment variables
MIN_PROFIT_PERCENT = float(os.environ.get('MIN_PROFIT_PERCENT', 0.3))
SCAN_INTERVAL_SECONDS = int(os.environ.get('SCAN_INTERVAL', 5))

class ArbitrageScanner:
    """Main scanner application"""
    
    def __init__(self, min_profit_percent: float = 0.3, scan_interval: int = 5):
        self.min_profit_percent = min_profit_percent
        self.scan_interval = scan_interval
        self.scan_count = 0
        
        # Coins from the images (all to USDT)
        self.coins = {
            'TIER_1': [
                'ETH', 'XRP', 'BNB', 'SOL', 'DOGE', 'ADA', 'TRX', 'LINK',
                'AVAX', 'TON', 'SHIB', 'DOT', 'LTC', 'BCH', 'NEAR', 'APT', 'ICP'
            ],
            'TIER_2': [
                'POL', 'MATIC', 'ARB', 'OP', 'ATOM', 'HBAR', 'FIL', 'XLM',
                'VET', 'RNDR', 'INJ', 'KAS', 'ALGO', 'ETC', 'CRO', 'XMR',
                'PEPE', 'BONK', 'JUP'
            ],
            'TIER_3': [
                'SUI', 'SEI', 'STRK', 'TIA', 'BLUR', 'DYDX', 'SUSHI', 'UNI',
                'AAVE', 'GRT', 'GALA', 'ENJ', 'SAND', 'AXS', 'FLOW', 'FTM', 'BEAM'
            ]
        }
        
        # Generate all USDT pairs
        self.all_coins = []
        for tier_coins in self.coins.values():
            self.all_coins.extend(tier_coins)
        self.all_coins = list(set(self.all_coins))
        self.symbols = [f"{coin}USDT" for coin in self.all_coins]
        
        # Initialize components
        self.exchange_manager = ExchangeManager(self.symbols)
        self.calculator = ArbitrageCalculator(self.exchange_manager, min_profit_percent)
        
        print(f"✅ Loaded {len(self.all_coins)} coins | {len(self.exchange_manager.exchanges)} exchanges")
    
    async def scan_once(self):
        """Perform a single arbitrage scan"""
        global latest_opportunities, last_scan_time, scan_count
        
        self.scan_count += 1
        scan_count = self.scan_count
        print(f"\n{Fore.CYAN}{'='*50}")
        print(f"🔍 SCAN #{self.scan_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*50}{Style.RESET_ALL}")
        
        start_time = datetime.now()
        last_scan_time = start_time
        
        # Fetch prices from all exchanges
        print(f"📡 Fetching prices from {len(self.exchange_manager.exchanges)} exchanges...")
        prices = await self.exchange_manager.fetch_prices()
        
        # Find arbitrage opportunities
        print(f"🔎 Analyzing {len(self.symbols)} trading pairs...")
        opportunities = self.calculator.find_opportunities(prices)
        
        # Store latest opportunities
        latest_opportunities = []
        for opp in opportunities[:20]:  # Store top 20
            coin = opp.symbol.replace('USDT', '')
            tier = self.get_coin_tier(opp.symbol)
            
            latest_opportunities.append({
                'coin': coin,
                'symbol': opp.symbol,
                'tier': tier[0],
                'tier_icon': tier[2],
                'buy_exchange': opp.buy_exchange,
                'sell_exchange': opp.sell_exchange,
                'buy_price': opp.buy_price,
                'sell_price': opp.sell_price,
                'profit_percent': opp.profit_percent,
                'profit_absolute': opp.profit_absolute,
                'spread': opp.spread,
                'timestamp': opp.timestamp.isoformat(),
                'profit_per_1k': (1000 * opp.profit_percent / 100)
            })
        
        # Print summary
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"✅ Found {len(opportunities)} opportunities in {elapsed:.2f}s")
        
        if opportunities:
            print(f"🏆 Best: {opportunities[0].symbol} - {opportunities[0].profit_percent:.2f}% profit")
        
        return opportunities
    
    def get_coin_tier(self, symbol: str):
        """Get coin tier information"""
        coin = symbol.replace('USDT', '')
        if coin in self.coins['TIER_1']:
            return ('TIER_1', 'Large Cap', '👑', 5000)
        elif coin in self.coins['TIER_2']:
            return ('TIER_2', 'Medium Cap', '⭐', 2000)
        elif coin in self.coins['TIER_3']:
            return ('TIER_3', 'Volatile', '⚡', 500)
        return ('UNKNOWN', 'Standard', '📊', 1000)
    
    async def run_continuous(self):
        """Continuous scanning loop"""
        print(f"\n{Fore.GREEN}✅ Scanner initialized!")
        print(f"{Fore.YELLOW}⚠️  Scanning every {self.scan_interval} seconds{Style.RESET_ALL}")
        
        while True:
            try:
                await self.scan_once()
                await asyncio.sleep(self.scan_interval)
            except Exception as e:
                print(f"{Fore.RED}❌ Error in scan: {e}")
                await asyncio.sleep(self.scan_interval)

# Flask routes for web dashboard
@app.route('/')
def dashboard():
    """Web dashboard showing latest opportunities"""
    return render_template_string(HTML_TEMPLATE, 
                                  opportunities=latest_opportunities,
                                  scan_count=scan_count,
                                  last_scan=last_scan_time,
                                  min_profit=MIN_PROFIT_PERCENT,
                                  exchanges=21,
                                  coins=len(ArbitrageScanner({}).all_coins) if 'ArbitrageScanner' in globals() else 50)

@app.route('/api/opportunities')
def api_opportunities():
    """JSON API for latest opportunities"""
    return jsonify({
        'success': True,
        'scan_count': scan_count,
        'last_scan': last_scan_time.isoformat() if last_scan_time else None,
        'opportunities': latest_opportunities,
        'total_opportunities': len(latest_opportunities)
    })

@app.route('/api/health')
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        'status': 'healthy',
        'scanning': True,
        'last_scan': last_scan_time.isoformat() if last_scan_time else None,
        'opportunities_found': len(latest_opportunities)
    })

# HTML Template for dashboard
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arbimine.pro - Crypto Arbitrage Scanner</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            background: white;
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        
        h1 {
            color: #333;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: #666;
            font-size: 1.1em;
        }
        
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
        }
        
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-label {
            color: #666;
            margin-top: 5px;
        }
        
        .opportunities {
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        
        .section-title {
            font-size: 1.5em;
            margin-bottom: 20px;
            color: #333;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th {
            background: #f5f5f5;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #555;
        }
        
        td {
            padding: 12px;
            border-bottom: 1px solid #eee;
        }
        
        .tier-1 {
            color: #ffd700;
            font-weight: bold;
        }
        
        .tier-2 {
            color: #c0c0c0;
            font-weight: bold;
        }
        
        .tier-3 {
            color: #cd7f32;
            font-weight: bold;
        }
        
        .profit-positive {
            color: #10b981;
            font-weight: bold;
        }
        
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
            font-size: 0.9em;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .scanning {
            animation: pulse 2s infinite;
        }
        
        footer {
            text-align: center;
            margin-top: 30px;
            color: white;
        }
        
        @media (max-width: 768px) {
            table {
                font-size: 0.85em;
            }
            
            .stat-value {
                font-size: 1.5em;
            }
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
                <div class="stat-label">Exchanges Monitored</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ coins }}</div>
                <div class="stat-label">Coins Tracked</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ scan_count }}</div>
                <div class="stat-label">Total Scans</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ opportunities|length }}</div>
                <div class="stat-label">Current Opportunities</div>
            </div>
        </div>
        
        <div class="opportunities">
            <div class="section-title">💰 Live Arbitrage Opportunities</div>
            {% if opportunities %}
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Coin</th>
                            <th>Tier</th>
                            <th>Buy From</th>
                            <th>Buy Price</th>
                            <th>Sell To</th>
                            <th>Sell Price</th>
                            <th>Profit %</th>
                            <th>Profit/$1k</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for opp in opportunities %}
                        <tr>
                            <td><strong>{{ opp.coin }}</strong></td>
                            <td><span class="tier-{{ opp.tier|lower|replace('_', '-') }}">{{ opp.tier_icon }} {{ opp.tier }}</span></td>
                            <td><span class="exchange-badge">{{ opp.buy_exchange.upper() }}</span></td>
                            <td>${{ "%.4f"|format(opp.buy_price) }}</td>
                            <td><span class="exchange-badge">{{ opp.sell_exchange.upper() }}</span></td>
                            <td>${{ "%.4f"|format(opp.sell_price) }}</td>
                            <td class="profit-positive">+{{ "%.2f"|format(opp.profit_percent) }}%</td>
                            <td class="profit-positive">${{ "%.2f"|format(opp.profit_per_1k) }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <p style="text-align: center; color: #666; padding: 40px;">
                🔍 Scanning for opportunities... Check back in a few seconds.
            </p>
            {% endif %}
            <div class="refresh-info">
                <span class="scanning">🟢 Live scanning every {{ min_profit }}% profit threshold</span><br>
                Last scan: {{ last_scan.strftime('%Y-%m-%d %H:%M:%S') if last_scan else 'Waiting for first scan...' }}
            </div>
        </div>
        
        <footer>
            <p>⚠️ Disclaimer: For educational purposes. Cryptocurrency trading carries significant risk.</p>
            <p>📊 Data refreshes automatically every few seconds</p>
        </footer>
    </div>
    
    <script>
        // Auto-refresh every 5 seconds
        setInterval(function() {
            location.reload();
        }, 5000);
    </script>
</body>
</html>
'''

def run_flask():
    """Run Flask web server"""
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

async def main():
    """Main entry point"""
    # Create scanner instance
    scanner = ArbitrageScanner(
        min_profit_percent=MIN_PROFIT_PERCENT,
        scan_interval=SCAN_INTERVAL_SECONDS
    )
    
    # Run Flask in a separate thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Run scanner
    await scanner.run_continuous()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Shutting down...{Style.RESET_ALL}")
        sys.exit(0)
