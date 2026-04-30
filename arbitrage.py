"""
Core arbitrage calculation logic
"""

from typing import Dict, List
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ArbitrageOpportunity:
    """Arbitrage opportunity data structure"""
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    profit_percent: float
    profit_absolute: float
    spread: float
    timestamp: datetime

class ArbitrageCalculator:
    """Calculates arbitrage opportunities"""
    
    def __init__(self, exchange_fees: Dict, min_profit_percent: float):
        self.exchange_fees = exchange_fees
        self.min_profit_percent = min_profit_percent
    
    def find_opportunities(self, prices: Dict[str, Dict[str, float]]) -> List[ArbitrageOpportunity]:
        """Find all arbitrage opportunities across exchanges"""
        opportunities = []
        
        # Get all symbols from price data
        all_symbols = set()
        for exchange_data in prices.values():
            all_symbols.update(exchange_data.keys())
        
        for symbol in all_symbols:
            coin_data = {}
            
            # Collect prices from all exchanges
            for exchange, price_dict in prices.items():
                if symbol in price_dict and price_dict[symbol] > 0:
                    fee = self.exchange_fees.get(exchange, 0.002)
                    price = price_dict[symbol]
                    
                    coin_data[exchange] = {
                        'price': price,
                        'ask_effective': price * (1 + fee),  # Buy cost
                        'bid_effective': price * (1 - fee)   # Sell revenue
                    }
            
            if len(coin_data) < 2:
                continue
            
            # Find best buy and sell
            best_buy = min(coin_data.items(), key=lambda x: x[1]['ask_effective'])
            best_sell = max(coin_data.items(), key=lambda x: x[1]['bid_effective'])
            
            if best_buy[0] != best_sell[0]:
                buy_cost = best_buy[1]['ask_effective']
                sell_revenue = best_sell[1]['bid_effective']
                profit_abs = sell_revenue - buy_cost
                profit_pct = (profit_abs / buy_cost) * 100
                spread = ((best_sell[1]['price'] - best_buy[1]['price']) / best_buy[1]['price']) * 100
                
                if profit_pct > self.min_profit_percent:
                    opportunities.append(ArbitrageOpportunity(
                        symbol=symbol,
                        buy_exchange=best_buy[0],
                        sell_exchange=best_sell[0],
                        buy_price=best_buy[1]['price'],
                        sell_price=best_sell[1]['price'],
                        profit_percent=profit_pct,
                        profit_absolute=profit_abs,
                        spread=spread,
                        timestamp=datetime.now()
                    ))
        
        return sorted(opportunities, key=lambda x: x.profit_percent, reverse=True)
