"""
Core arbitrage calculation logic
Finds profitable opportunities across exchanges
"""

from typing import Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ArbitrageOpportunity:
    """Stores a single arbitrage opportunity"""
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
    """Calculates arbitrage opportunities from price data"""
    
    def __init__(self, exchange_manager, min_profit_percent: float = 0.3):
        self.exchange_manager = exchange_manager
        self.min_profit_percent = min_profit_percent
    
    def find_opportunities(self, prices: Dict[str, Dict[str, float]]) -> List[ArbitrageOpportunity]:
        """
        Find all profitable arbitrage opportunities
        
        Args:
            prices: Dictionary of {exchange: {symbol: price}}
        
        Returns:
            List of ArbitrageOpportunity objects sorted by profit
        """
        opportunities = []
        
        # Get all symbols from price data
        all_symbols = set()
        for exchange_data in prices.values():
            all_symbols.update(exchange_data.keys())
        
        for symbol in all_symbols:
            coin_data = {}
            
            # Collect prices with fees from all exchanges
            for exchange, price_dict in prices.items():
                if symbol in price_dict and price_dict[symbol] > 0:
                    fee = self.exchange_manager.get_fee(exchange)
                    price = price_dict[symbol]
                    
                    # Calculate effective prices after fees
                    coin_data[exchange] = {
                        'price': price,
                        'ask_effective': price * (1 + fee),  # Cost to buy
                        'bid_effective': price * (1 - fee)   # Revenue from sell
                    }
            
            if len(coin_data) < 2:
                continue
            
            # Find best exchange to buy from (lowest ask)
            best_buy = min(coin_data.items(), key=lambda x: x[1]['ask_effective'])
            # Find best exchange to sell on (highest bid)
            best_sell = max(coin_data.items(), key=lambda x: x[1]['bid_effective'])
            
            # Must be different exchanges
            if best_buy[0] != best_sell[0]:
                buy_cost = best_buy[1]['ask_effective']
                sell_revenue = best_sell[1]['bid_effective']
                profit_absolute = sell_revenue - buy_cost
                profit_percent = (profit_absolute / buy_cost) * 100
                spread = ((best_sell[1]['price'] - best_buy[1]['price']) / best_buy[1]['price']) * 100
                
                # Check if profitable after minimum threshold
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
        
        # Sort by profit percentage (highest first)
        return sorted(opportunities, key=lambda x: x.profit_percent, reverse=True)
    
    def calculate_trade_profit(self, opportunity: ArbitrageOpportunity, 
                               trade_amount: float = 1000) -> Dict:
        """
        Calculate detailed profit for a specific trade amount
        
        Returns:
            Dictionary with trade details including units, gross profit, net profit
        """
        units = trade_amount / opportunity.buy_price
        gross_revenue = units * opportunity.sell_price
        net_profit = gross_revenue - trade_amount
        
        return {
            'trade_amount': trade_amount,
            'units': units,
            'gross_revenue': gross_revenue,
            'net_profit': net_profit,
            'profit_percent': (net_profit / trade_amount) * 100
        }
