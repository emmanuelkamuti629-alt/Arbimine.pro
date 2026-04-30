"""
Exchange handlers for all 21 exchanges
Fetches real-time prices for all USDT pairs
"""

import aiohttp
import asyncio
from typing import Dict, List, Optional

class ExchangeManager:
    """Manages all exchange connections and data fetching"""
    
    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        
        # Exchange fees (maker/taker rates)
        self.exchange_fees = {
            'binance': 0.001,
            'bybit': 0.001,
            'okx': 0.001,
            'kucoin': 0.001,
            'gate': 0.002,
            'mexc': 0.002,
            'htx': 0.002,
            'bitget': 0.001,
            'bitmart': 0.0025,
            'coinex': 0.002,
            'lbank': 0.002,
            'whitebit': 0.001,
            'poloniex': 0.0025,
            'bitfinex': 0.002,
            'bitstamp': 0.005,
            'upbit': 0.0025,
            'indodax': 0.003,
            'bingx': 0.001,
            'xt': 0.002,
            'ascendex': 0.001
        }
        
        # Exchange API configurations
        self.exchanges = {
            'binance': {
                'url': 'https://api.binance.com/api/v3/ticker/price',
                'type': 'standard'
            },
            'bybit': {
                'url': 'https://api.bybit.com/v5/market/tickers',
                'type': 'standard'
            },
            'okx': {
                'url': 'https://www.okx.com/api/v5/market/tickers',
                'type': 'standard'
            },
            'kucoin': {
                'url': 'https://api.kucoin.com/api/v1/prices',
                'type': 'standard'
            },
            'gate': {
                'url': 'https://api.gateio.ws/api/v4/spot/tickers',
                'type': 'standard'
            },
            'mexc': {
                'url': 'https://api.mexc.com/api/v3/ticker/price',
                'type': 'standard'
            },
            'htx': {
                'url': 'https://api.huobi.pro/market/tickers',
                'type': 'standard'
            },
            'bitget': {
                'url': 'https://api.bitget.com/api/spot/v1/market/tickers',
                'type': 'standard'
            },
            'bitmart': {
                'url': 'https://api.bitmart.com/spot/v1/ticker',
                'type': 'standard'
            },
            'coinex': {
                'url': 'https://api.coinex.com/v1/market/list',
                'type': 'standard'
            },
            'lbank': {
                'url': 'https://api.lbank.info/api/ticker.do',
                'type': 'lbank'
            },
            'whitebit': {
                'url': 'https://whitebit.com/api/v4/public/ticker',
                'type': 'whitebit'
            },
            'poloniex': {
                'url': 'https://api.poloniex.com/markets/price',
                'type': 'standard'
            },
            'bitfinex': {
                'url': 'https://api.bitfinex.com/v1/symbols_details',
                'type': 'quote',
                'quote_currency': 'USD'
            },
            'bitstamp': {
                'url': 'https://www.bitstamp.net/api/v2/ticker/',
                'type': 'quote',
                'quote_currency': 'USD'
            },
            'upbit': {
                'url': 'https://api.upbit.com/v1/ticker',
                'type': 'quote',
                'quote_currency': 'KRW'
            },
            'indodax': {
                'url': 'https://indodax.com/api/ticker_all',
                'type': 'quote',
                'quote_currency': 'IDR'
            },
            'bingx': {
                'url': 'https://open-api.bingx.com/openApi/spot/v1/ticker/24hr',
                'type': 'bingx'
            },
            'xt': {
                'url': 'https://api.xt.com/v4/public/ticker',
                'type': 'standard'
            },
            'ascendex': {
                'url': 'https://ascendex.com/api/pro/v1/spot/tickers',
                'type': 'ascendex'
            }
        }
    
    async def fetch_prices(self) -> Dict[str, Dict[str, float]]:
        """Fetch prices from all exchanges concurrently"""
        async with aiohttp.ClientSession() as session:
            tasks = []
            for exchange_name, config in self.exchanges.items():
                tasks.append(self._fetch_exchange(session, exchange_name, config))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            all_prices = {}
            for result in results:
                if isinstance(result, dict):
                    all_prices.update(result)
            return all_prices
    
    async def _fetch_exchange(self, session: aiohttp.ClientSession, 
                              exchange: str, config: dict) -> Dict:
        """Fetch data from specific exchange based on its type"""
        try:
            if config['type'] == 'standard':
                return await self._fetch_standard(session, exchange, config)
            elif config['type'] == 'quote':
                return await self._fetch_quote_exchange(session, exchange, config)
            else:
                return await self._fetch_special(session, exchange, config)
        except Exception as e:
            return {exchange: {}}
    
    async def _fetch_standard(self, session: aiohttp.ClientSession, 
                               exchange: str, config: dict) -> Dict:
        """Handle standard exchange API format"""
        try:
            async with session.get(config['url'], timeout=10) as resp:
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
                
                elif exchange == 'poloniex':
                    for item in data:
                        symbol = item['symbol'].split('_')[0] + 'USDT'
                        if symbol in self.symbols:
                            prices[symbol] = float(item['price'])
                
                elif exchange == 'xt':
                    if 'result' in data and 'tickers' in data['result']:
                        for item in data['result']['tickers']:
                            if item['symbol'] in self.symbols:
                                prices[item['symbol']] = float(item['last'])
                
                return {exchange: prices}
        except Exception:
            return {exchange: {}}
    
    async def _fetch_quote_exchange(self, session: aiohttp.ClientSession,
                                      exchange: str, config: dict) -> Dict:
        """Handle exchanges with different quote currencies (USD, KRW, IDR)"""
        try:
            prices = {}
            
            if exchange == 'bitfinex':
                async with session.get(config['url']) as resp:
                    data = await resp.json()
                    for item in data:
                        pair = item['pair'].upper()
                        for symbol in self.symbols:
                            if pair == symbol.replace('USDT', 'USD'):
                                prices[symbol] = float(item['last_price'])
            
            elif exchange == 'bitstamp':
                for symbol in self.symbols:
                    pair = symbol.replace('USDT', 'USD').lower()
                    url = f"{config['url']}{pair}/"
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if 'last' in data:
                                prices[symbol] = float(data['last'])
            
            elif exchange == 'upbit':
                markets = [s.replace('USDT', 'KRW') for s in self.symbols]
                params = f'markets={",".join(markets)}'
                async with session.get(f"{config['url']}?{params}") as resp:
                    data = await resp.json()
                    for item in data:
                        market = item['market']
                        for symbol in self.symbols:
                            if market == symbol.replace('USDT', 'KRW'):
                                prices[symbol] = float(item['trade_price'])
            
            elif exchange == 'indodax':
                async with session.get(config['url']) as resp:
                    data = await resp.json()
                    for ticker_id, ticker_data in data.get('tickers', {}).items():
                        for symbol in self.symbols:
                            if symbol.replace('USDT', 'IDR').lower() in ticker_id:
                                prices[symbol] = float(ticker_data['last'])
            
            return {exchange: prices}
        except Exception:
            return {exchange: {}}
    
    async def _fetch_special(self, session: aiohttp.ClientSession,
                               exchange: str, config: dict) -> Dict:
        """Handle special exchange API formats"""
        try:
            prices = {}
            
            if exchange == 'lbank':
                for symbol in self.symbols:
                    url = f"{config['url']}?symbol={symbol.lower()}"
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if 'ticker' in data and 'latest' in data['ticker']:
                                prices[symbol] = float(data['ticker']['latest'])
            
            elif exchange == 'whitebit':
                async with session.get(config['url']) as resp:
                    data = await resp.json()
                    for symbol in self.symbols:
                        pair = symbol.replace('USDT', '_USDT')
                        if pair in data:
                            prices[symbol] = float(data[pair]['last'])
            
            elif exchange == 'bingx':
                async with session.get(config['url']) as resp:
                    data = await resp.json()
                    if 'data' in data:
                        for item in data['data']:
                            if item['symbol'] in self.symbols:
                                prices[item['symbol']] = float(item['lastPrice'])
            
            elif exchange == 'ascendex':
                async with session.get(config['url']) as resp:
                    data = await resp.json()
                    if 'data' in data:
                        for item in data['data']:
                            if item['symbol'] in self.symbols:
                                prices[item['symbol']] = float(item['ask'][0])
            
            return {exchange: prices}
        except Exception:
            return {exchange: {}}
    
    def get_fee(self, exchange: str) -> float:
        """Get trading fee for an exchange"""
        return self.exchange_fees.get(exchange, 0.002)
