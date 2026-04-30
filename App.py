import asyncio
import aiohttp
import time
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict

@dataclass
class ArbitrageOpportunity:
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    profit_percent: float
    profit_absolute: float
    spread: float
    timestamp: datetime

class CompleteArbitrageScanner:
    def __init__(self, min_profit_percent: float = 0.3):
        """
        Scanner for all coins across 21 exchanges, all compared to USDT
        """
        self.min_profit_percent = min_profit_percent
        
        # Complete coin list from your images (ALL to USDT)
        self.coins = {
            # Tier 1: Large Cap (from first image) - MOST LIQUID
            'tier1': [
                'ETH', 'XRP', 'BNB', 'SOL', 'DOGE', 'ADA', 'TRX', 'LINK',
                'AVAX', 'TON', 'SHIB', 'DOT', 'LTC', 'BCH', 'NEAR', 'APT', 'ICP'
            ],
            # Tier 2: Medium Cap (20-100 from second/third images)
            'tier2': [
                'POL', 'MATIC', 'ARB', 'OP', 'ATOM', 'HBAR', 'FIL', 'XLM',
                'VET', 'RNDR', 'INJ', 'KAS', 'ALGO', 'ETC', 'CRO', 'XMR',
                'PEPE', 'BONK', 'JUP'
            ],
            # Tier 3: Short Burst / Volatility Coins (from fourth image)
            'tier3': [
                'SUI', 'SEI', 'STRK', 'TIA', 'BLUR', 'DYDX', 'SUSHI', 'UNI',
                'AAVE', 'GRT', 'GALA', 'ENJ', 'SAND', 'AXS', 'FLOW', 'FTM', 'BEAM'
            ]
        }
        
        # Combine all coins, remove duplicates
        self.all_coins = list(set(
            self.coins['tier1'] + self.coins['tier2'] + self.coins['tier3']
        ))
        
        # Generate USDT pairs
        self.symbols = [f"{coin}USDT" for coin in self.all_coins]
        
        # Exchange configurations (all 21 exchanges)
        self.exchanges = {
            'bybit': {'url': 'https://api.bybit.com/v5/market/tickers', 'fee': 0.001},
            'mexc': {'url': 'https://api.mexc.com/api/v3/ticker/price', 'fee': 0.002},
            'ascendex': {'url': 'https://ascendex.com/api/pro/v1/spot/tickers', 'fee': 0.001},
            'htx': {'url': 'https://api.huobi.pro/market/tickers', 'fee': 0.002},
            'kucoin': {'url': 'https://api.kucoin.com/api/v1/prices', 'fee': 0.001},
            'bingx': {'url': 'https://open-api.bingx.com/openApi/spot/v1/ticker/24hr', 'fee': 0.001},
            'gate': {'url': 'https://api.gateio.ws/api/v4/spot/tickers', 'fee': 0.002},
            'bitmart': {'url': 'https://api.bitmart.com/spot/v1/ticker', 'fee': 0.0025},
            'xt': {'url': 'https://api.xt.com/v4/public/ticker', 'fee': 0.002},
            'coinex': {'url': 'https://api.coinex.com/v1/market/list', 'fee': 0.002},
            'binance': {'url': 'https://api.binance.com/api/v3/ticker/price', 'fee': 0.001},
            'lbank': {'url': 'https://api.lbank.info/api/ticker.do', 'fee': 0.002},
            'okx': {'url': 'https://www.okx.com/api/v5/market/tickers', 'fee': 0.001},
            'bitfinex': {'url': 'https://api.bitfinex.com/v1/symbols_details', 'fee': 0.002, 'quote': 'USD'},
            'indodax': {'url': 'https://indodax.com/api/ticker_all', 'fee': 0.003, 'quote': 'IDR'},
            'bitget': {'url': 'https://api.bitget.com/api/spot/v1/market/tickers', 'fee': 0.001},
            'whitebit': {'url': 'https://whitebit.com/api/v4/public/ticker', 'fee': 0.001},
            'poloniex': {'url': 'https://api.poloniex.com/markets/price', 'fee': 0.0025},
            'bitstamp': {'url': 'https://www.bitstamp.net/api/v2/ticker/', 'fee': 0.005, 'quote': 'USD'},
            'upbit': {'url': 'https://api.upbit.com/v1/ticker', 'fee': 0.0025, 'quote': 'KRW'}
        }
        
        # Map USDT symbols to exchange-specific formats
        self.symbol_mapping = {}
        for exchange, config in self.exchanges.items():
            self.symbol_mapping[exchange] = {}
            for symbol in self.symbols:
                if config.get('quote') == 'USD':
                    self.symbol_mapping[exchange][symbol] = symbol.replace('USDT', 'USD')
                elif config.get('quote') == 'KRW':
                    self.symbol_mapping[exchange][symbol] = symbol.replace('USDT', 'KRW')
                elif config.get('quote') == 'IDR':
                    self.symbol_mapping[exchange][symbol] = symbol.replace('USDT', 'IDR')
                else:
                    self.symbol_mapping[exchange][symbol] = symbol
    
    async def fetch_generic_ticker(self, session: aiohttp.ClientSession, exchange: str, config: dict) -> Dict:
        """Generic fetcher for exchanges with simple ticker endpoints"""
        try:
            async with session.get(config['url']) as resp:
                data = await resp.json()
                prices = {}
                
                # Different exchanges have different response formats
                if exchange == 'binance':
                    for item in data:
                        if item['symbol'] in self.symbols:
                            prices[item['symbol']] = float(item['price'])
                
                elif exchange == 'bybit':
                    if 'result' in data and 'list' in data['result']:
                        for item in data['result']['list']:
                            if item['symbol'] in self.symbols:
                                prices[item['symbol']] = float(item['lastPrice'])
                
                elif exchange == 'mexc':
                    for item in data:
                        if item['symbol'] in self.symbols:
                            prices[item['symbol']] = float(item['price'])
                
                elif exchange == 'kucoin':
                    if 'data' in data:
                        for symbol in self.symbols:
                            if symbol in data['data']:
                                prices[symbol] = float(data['data'][symbol])
                
                elif exchange == 'gate':
                    for item in data:
                        if item['currency_pair'] in self.symbols:
                            prices[item['currency_pair']] = float(item['last'])
                
                elif exchange == 'okx':
                    if 'data' in data:
                        for item in data['data']:
                            if item['instId'] in self.symbols:
                                prices[item['instId']] = float(item['last'])
                
                elif exchange == 'bitget':
                    if 'data' in data:
                        for item in data['data']:
                            if item['symbol'] in self.symbols:
                                prices[item['symbol']] = float(item['lastPr'])
                
                elif exchange == 'whitebit':
                    for symbol in self.symbols:
                        pair = symbol.replace('USDT', '_USDT')
                        if pair in data:
                            prices[symbol] = float(data[pair]['last'])
                
                elif exchange == 'poloniex':
                    for item in data:
                        symbol = item['symbol'].split('_')[0] + 'USDT'
                        if symbol in self.symbols:
                            prices[symbol] = float(item['price'])
                
                elif exchange == 'htx':
                    if 'data' in data:
                        for item in data['data']:
                            symbol = item['symbol'].upper()
                            if symbol in self.symbols:
                                prices[symbol] = float(item['close'])
                
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
                
                return {exchange: prices}
        except Exception as e:
            return {exchange: {}}
    
    async def fetch_quote_exchange(self, session: aiohttp.ClientSession, exchange: str, config: dict) -> Dict:
        """Fetch from exchanges with different quote currencies (USD, KRW, IDR)"""
        try:
            prices = {}
            mapping = self.symbol_mapping[exchange]
            
            if exchange == 'bitfinex':
                async with session.get(config['url']) as resp:
                    data = await resp.json()
                    for item in data:
                        pair = item['pair'].upper()
                        for usdt_symbol, quote_symbol in mapping.items():
                            if pair == quote_symbol:
                                prices[usdt_symbol] = float(item['last_price'])
            
            elif exchange == 'bitstamp':
                for usdt_symbol, quote_symbol in mapping.items():
                    clean_symbol = quote_symbol.lower()
                    url = f"{config['url']}{clean_symbol}/"
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if 'last' in data:
                                prices[usdt_symbol] = float(data['last'])
            
            elif exchange == 'upbit':
                markets = list(mapping.values())
                if markets:
                    params = f'markets={",".join(markets)}'
                    async with session.get(f"{config['url']}?{params}") as resp:
                        data = await resp.json()
                        reverse_map = {v: k for k, v in mapping.items()}
                        for item in data:
                            market = item['market']
                            if market in reverse_map:
                                prices[reverse_map[market]] = float(item['trade_price'])
            
            elif exchange == 'indodax':
                async with session.get(config['url']) as resp:
                    data = await resp.json()
                    reverse_map = {v.lower(): k for k, v in mapping.items()}
                    for ticker_id, ticker_data in data.get('tickers', {}).items():
                        if ticker_id in reverse_map:
                            prices[reverse_map[ticker_id]] = float(ticker_data['last'])
            
            return {exchange: prices}
        except Exception as e:
            return {exchange: {}}
    
    async def fetch_lbank(self, session: aiohttp.ClientSession) -> Dict:
        """Special handler for LBank"""
        try:
            prices = {}
            for symbol in self.symbols:
                url = f'https://api.lbank.info/api/v1/ticker.do?symbol={symbol.lower()}'
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if 'ticker' in data and 'latest' in data['ticker']:
                            prices[symbol] = float(data['ticker']['latest'])
            return {'lbank': prices}
        except Exception:
            return {'lbank': {}}
    
    async def fetch_bingx(self, session: aiohttp.ClientSession) -> Dict:
        """Special handler for BingX"""
        try:
            async with session.get(self.exchanges['bingx']['url']) as resp:
                data = await resp.json()
                prices = {}
                if 'data' in data:
                    for item in data['data']:
                        if item['symbol'] in self.symbols:
                            prices[item['symbol']] = float(item['lastPrice'])
                return {'bingx': prices}
        except Exception:
            return {'bingx': {}}
    
    async def fetch_ascendex(self, session: aiohttp.ClientSession) -> Dict:
        """Special handler for AscendEX"""
        try:
            async with session.get(self.exchanges['ascendex']['url']) as resp:
                data = await resp.json()
                prices = {}
                if 'data' in data:
                    for item in data['data']:
                        if item['symbol'] in self.symbols:
                            prices[item['symbol']] = float(item['ask'][0])
                return {'ascendex': prices}
        except Exception:
            return {'ascendex': {}}
    
    async def fetch_all_prices(self) -> Dict[str, Dict[str, float]]:
        """Fetch prices from all 21 exchanges for all coins"""
        async with aiohttp.ClientSession() as session:
            tasks = []
            
            # Standard exchanges
            for exchange in ['binance', 'bybit', 'mexc', 'kucoin', 'gate', 'okx', 
                            'bitget', 'whitebit', 'poloniex', 'htx', 'bitmart', 
                            'coinex', 'xt']:
                if exchange in self.exchanges:
                    tasks.append(self.fetch_generic_ticker(session, exchange, self.exchanges[exchange]))
            
            # Quote currency exchanges
            for exchange in ['bitfinex', 'bitstamp', 'upbit', 'indodax']:
                if exchange in self.exchanges:
                    tasks.append(self.fetch_quote_exchange(session, exchange, self.exchanges[exchange]))
            
            # Special handlers
            tasks.append(self.fetch_lbank(session))
            tasks.append(self.fetch_bingx(session))
            tasks.append(self.fetch_ascendex(session))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            all_prices = {}
            for result in results:
                if isinstance(result, dict):
                    all_prices.update(result)
            return all_prices
    
    def calculate_arbitrage(self, prices: Dict[str, Dict[str, float]]) -> List[ArbitrageOpportunity]:
        """Calculate arbitrage opportunities with fees"""
        opportunities = []
        
        for symbol in self.symbols:
            coin_data = {}
            
            for exchange, price_dict in prices.items():
                if symbol in price_dict and price_dict[symbol] > 0:
                    fee = self.exchanges.get(exchange, {}).get('fee', 0.002)
                    coin_data[exchange] = {
                        'price': price_dict[symbol],
                        'fee': fee,
                        'ask_effective': price_dict[symbol] * (1 + fee),  # Buy cost
                        'bid_effective': price_dict[symbol] * (1 - fee)   # Sell revenue
                    }
            
            if len(coin_data) < 2:
                continue
            
            # Find best buy (lowest ask)
            best_buy = min(coin_data.items(), key=lambda x: x[1]['ask_effective'])
            # Find best sell (highest bid)
            best_sell = max(coin_data.items(), key=lambda x: x[1]['bid_effective'])
            
            # Only consider if different exchanges
            if best_buy[0] != best_sell[0]:
                buy_cost = best_buy[1]['ask_effective']
                sell_revenue = best_sell[1]['bid_effective']
                profit_absolute = sell_revenue - buy_cost
                profit_percent = (profit_absolute / buy_cost) * 100
                spread = ((best_sell[1]['price'] - best_buy[1]['price']) / best_buy[1]['price']) * 100
                
                if profit_percent > self.min_profit_percent:
                    opportunities.append(ArbitrageOpportunity(
                        symbol=symbol,
                        buy_exchange=best_buy[0],
                        sell_exchange=best_sell[0],
                        buy_price=best_buy[1]['price'],
                        sell_price=best_sell[1]['price'],
                        profit_percent=profit_percent,
                        profit_absolute=profit_absolute,
                        spread=spread,
                        timestamp=datetime.now()
                    ))
        
        return sorted(opportunities, key=lambda x: x.profit_percent, reverse=True)
    
    def get_coin_tier(self, symbol: str) -> str:
        """Determine which tier a coin belongs to"""
        coin = symbol.replace('USDT', '')
        if coin in self.coins['tier1']:
            return '👑 TIER 1 (High Liquidity)'
        elif coin in self.coins['tier2']:
            return '⭐ TIER 2 (Medium Cap)'
        elif coin in self.coins['tier3']:
            return '⚡ TIER 3 (Volatility/Burst)'
        return '📊 Standard'
    
    def display_opportunities(self, opportunities: List[ArbitrageOpportunity]):
        """Display all arbitrage opportunities"""
        if not opportunities:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔍 Scanning {len(self.symbols)} coins across 21 exchanges... No opportunities > {self.min_profit_percent}%")
            return
        
        print("\n" + "="*120)
        print(f"🚀 ARBITRAGE OPPORTUNITIES - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*120)
        
        # Group by tier
        tier1_opps = [o for o in opportunities if 'TIER 1' in self.get_coin_tier(o.symbol)]
        tier2_opps = [o for o in opportunities if 'TIER 2' in self.get_coin_tier(o.symbol)]
        tier3_opps = [o for o in opportunities if 'TIER 3' in self.get_coin_tier(o.symbol)]
        
        if tier1_opps:
            print("\n👑 TIER 1 - LARGE CAP (High Liquidity, Reliable)")
            print("-"*100)
            for opp in tier1_opps[:5]:
                self._print_opportunity(opp)
        
        if tier2_opps:
            print("\n⭐ TIER 2 - MEDIUM CAP (Good Opportunities)")
            print("-"*100)
            for opp in tier2_opps[:5]:
                self._print_opportunity(opp)
        
        if tier3_opps:
            print("\n⚡ TIER 3 - VOLATILITY (Best for Short Bursts)")
            print("-"*100)
            for opp in tier3_opps[:5]:
                self._print_opportunity(opp)
        
        print("\n" + "="*120)
    
    def _print_opportunity(self, opp: ArbitrageOpportunity):
        """Print single opportunity"""
        coin = opp.symbol.replace('USDT', '')
        print(f"\n💰 {coin} ({opp.symbol})")
        print(f"   📥 BUY  at {opp.buy_exchange.upper():12} @ ${opp.buy_price:,.6f}")
        print(f"   📤 SELL at {opp.sell_exchange.upper():12} @ ${opp.sell_price:,.6f}")
        print(f"   📈 Profit: {opp.profit_percent:.3f}% | Spread: {opp.spread:.3f}%")
        print(f"   💵 Per ${1000:,.0f} trade: ~${(1000 * opp.profit_percent / 100):.2f} profit")
        
        # Recommend best trade size based on tier
        if 'TIER 1' in self.get_coin_tier(opp.symbol):
            print(f"   💡 Recommended: Up to $5000 per trade (high liquidity)")
        elif 'TIER 2' in self.get_coin_tier(opp.symbol):
            print(f"   💡 Recommended: $1000-2000 per trade (medium liquidity)")
        else:
            print(f"   💡 Recommended: $200-500 per trade (low liquidity, high volatility)")
    
    def display_summary(self, prices: Dict):
        """Show which exchanges are responding"""
        working = [ex for ex, data in prices.items() if data]
        total_coins_found = sum(len(data) for data in prices.values())
        
        print(f"\n📊 Exchange Status: {len(working)}/{len(self.exchanges)} active")
        print(f"💰 Total price points: {total_coins_found}")
        
        # Show top exchanges by data
        exchange_data_count = [(ex, len(data)) for ex, data in prices.items() if data]
        exchange_data_count.sort(key=lambda x: x[1], reverse=True)
        if exchange_data_count:
            top_exchanges = [f"{ex}({count})" for ex, count in exchange_data_count[:5]]
            print(f"📡 Best data sources: {', '.join(top_exchanges)}")
    
    async def continuous_scan(self, interval_seconds: int = 3):
        """Continuous scanning loop"""
        print("\n" + "="*60)
        print("🔍 COMPLETE CROSS-EXCHANGE ARBITRAGE SCANNER")
        print("="*60)
        print(f"📊 Exchanges: {len(self.exchanges)}")
        print(f"💰 Coins: {len(self.all_coins)} (All to USDT)")
        print(f"🎯 Target profit: >{self.min_profit_percent}% after fees")
        print(f"⏱️  Scan interval: {interval_seconds}s")
        print("="*60)
        
        scan_count = 0
        while True:
            try:
                start = time.time()
                scan_count += 1
                
                print(f"\n🔎 Scan #{scan_count} - {datetime.now().strftime('%H:%M:%S')}")
                
                # Fetch all prices
                prices = await self.fetch_all_prices()
                
                # Show status
                self.display_summary(prices)
                
                # Find opportunities
                opportunities = self.calculate_arbitrage(prices)
                
                # Display results
                if opportunities:
                    self.display_opportunities(opportunities)
                else:
                    print(f"\n❌ No profitable opportunities found")
                
                # Timing control
                elapsed = time.time() - start
                sleep_time = max(0, interval_seconds - elapsed)
                print(f"\n⏱️  Scan completed in {elapsed:.2f}s")
                
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    
            except KeyboardInterrupt:
                print("\n\n⚠️ Scanner stopped by user")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                await asyncio.sleep(interval_seconds)

async def main():
    scanner = CompleteArbitrageScanner(min_profit_percent=0.3)  # 0.3% after fees
    await scanner.continuous_scan(interval_seconds=3)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Scanner shutdown complete")
