#!/usr/bin/env python3
"""
Main Arbitrage Scanner Application
Monitors 21 exchanges and 50+ coins for arbitrage opportunities
"""

import asyncio
import sys
from datetime import datetime
from colorama import init, Fore, Style, Back
from tabulate import tabulate

from exchanges import ExchangeManager
from arbitrage import ArbitrageCalculator

# Initialize colorama for colored output
init(autoreset=True)

class ArbitrageScanner:
    """Main scanner application"""
    
    def __init__(self, min_profit_percent: float = 0.3, scan_interval: int = 3):
        """
        Initialize scanner with all coins from images
        
        Args:
            min_profit_percent: Minimum profit percentage to show (after fees)
            scan_interval: Seconds between scans
        """
        self.min_profit_percent = min_profit_percent
        self.scan_interval = scan_interval
        self.scan_count = 0
        
        # Coins from the images (all to USDT)
        self.coins = {
            'TIER_1': [  # Large cap - high liquidity
                'ETH', 'XRP', 'BNB', 'SOL', 'DOGE', 'ADA', 'TRX', 'LINK',
                'AVAX', 'TON', 'SHIB', 'DOT', 'LTC', 'BCH', 'NEAR', 'APT', 'ICP'
            ],
            'TIER_2': [  # Medium cap - good opportunities
                'POL', 'MATIC', 'ARB', 'OP', 'ATOM', 'HBAR', 'FIL', 'XLM',
                'VET', 'RNDR', 'INJ', 'KAS', 'ALGO', 'ETC', 'CRO', 'XMR',
                'PEPE', 'BONK', 'JUP'
            ],
            'TIER_3': [  # Volatile - best for short bursts
                'SUI', 'SEI', 'STRK', 'TIA', 'BLUR', 'DYDX', 'SUSHI', 'UNI',
                'AAVE', 'GRT', 'GALA', 'ENJ', 'SAND', 'AXS', 'FLOW', 'FTM', 'BEAM'
            ]
        }
        
        # Generate all USDT pairs
        self.all_coins = []
        for tier_coins in self.coins.values():
            self.all_coins.extend(tier_coins)
        self.all_coins = list(set(self.all_coins))  # Remove duplicates
        
        self.symbols = [f"{coin}USDT" for coin in self.all_coins]
        
        # Initialize components
        self.exchange_manager = ExchangeManager(self.symbols)
        self.calculator = ArbitrageCalculator(self.exchange_manager, min_profit_percent)
        
        print(f"✅ Loaded {len(self.all_coins)} coins | {len(self.exchange_manager.exchanges)} exchanges")
    
    def get_coin_info(self, symbol: str) -> Tuple[str, str, str, int]:
        """Get coin tier and trading recommendation"""
        coin = symbol.replace('USDT', '')
        
        if coin in self.coins['TIER_1']:
            return ('TIER_1', 'Large Cap', '👑', 5000)
        elif coin in self.coins['TIER_2']:
            return ('TIER_2', 'Medium Cap', '⭐', 2000)
        elif coin in self.coins['TIER_3']:
            return ('TIER_3', 'Volatile', '⚡', 500)
        else:
            return ('UNKNOWN', 'Standard', '📊', 1000)
    
    def print_header(self):
        """Display application header"""
        print(Fore.CYAN + Style.BRIGHT + "\n" + "="*100)
        print(Fore.CYAN + Style.BRIGHT + "🚀 CROSS-EXCHANGE CRYPTO ARBITRAGE SCANNER")
        print(Fore.CYAN + "="*100)
        print(f"📊 {len(self.exchange_manager.exchanges)} Exchanges Active")
        print(f"💰 {len(self.all_coins)} Coins Monitored (All to USDT)")
        print(f"🎯 Minimum Profit: {self.min_profit_percent}% (After Fees)")
        print(f"⏱️  Scan Interval: {self.scan_interval} seconds")
        print(Fore.CYAN + "="*100 + Style.RESET_ALL)
        
        # Show coin breakdown
        print(f"\n📈 Coin Distribution:")
        print(f"   👑 TIER 1 (Large Cap): {len(self.coins['TIER_1'])} coins - High liquidity")
        print(f"   ⭐ TIER 2 (Medium Cap): {len(self.coins['TIER_2'])} coins - Good opportunities")
        print(f"   ⚡ TIER 3 (Volatile): {len(self.coins['TIER_3'])} coins - Best for bursts")
    
    def print_exchange_status(self, prices: dict):
        """Show which exchanges are responding"""
        working = [ex for ex, data in prices.items() if data]
        total_prices = sum(len(data) for data in prices.values())
        
        print(f"\n✅ Active Exchanges: {len(working)}/{len(self.exchange_manager.exchanges)}")
        print(f"💰 Total Price Points: {total_prices}")
        
        # Show top 5 exchanges by data volume
        exchange_data = [(ex, len(data)) for ex, data in prices.items() if data]
        exchange_data.sort(key=lambda x: x[1], reverse=True)
        if exchange_data:
            top_exchanges = [f"{ex.upper()}({count})" for ex, count in exchange_data[:5]]
            print(f"📡 Best Data Sources: {', '.join(top_exchanges)}")
    
    def print_opportunities(self, opportunities: list):
        """Display arbitrage opportunities in formatted tables"""
        if not opportunities:
            print(f"\n❌ No arbitrage opportunities found above {self.min_profit_percent}%")
            return
        
        # Group opportunities by tier
        grouped = {'TIER_1': [], 'TIER_2': [], 'TIER_3': []}
        for opp in opportunities:
            tier, _, _, _ = self.get_coin_info(opp.symbol)
            grouped[tier].append(opp)
        
        # Display each tier
        for tier in ['TIER_1', 'TIER_2', 'TIER_3']:
            if grouped[tier]:
                tier_name = {
                    'TIER_1': '👑 TIER 1 - LARGE CAP (High Liquidity)',
                    'TIER_2': '⭐ TIER 2 - MEDIUM CAP (Good Opportunities)',
                    'TIER_3': '⚡ TIER 3 - VOLATILE (Best for Short Bursts)'
                }[tier]
                
                print(f"\n{Fore.YELLOW}{Style.BRIGHT}{tier_name}")
                print(Fore.WHITE + "-"*100)
                
                # Prepare table data
                table_data = []
                for opp in grouped[tier][:10]:  # Show top 10 per tier
                    coin = opp.symbol.replace('USDT', '')
                    profit_per_1k = (1000 * opp.profit_percent / 100)
                    
                    # Color code profit
                    profit_color = Fore.GREEN if opp.profit_percent > 0.5 else Fore.YELLOW
                    
                    table_data.append([
                        f"{Fore.CYAN}{coin}",
                        f"{Fore.GREEN}{opp.buy_exchange.upper()}",
                        f"${opp.buy_price:.6f}",
                        f"{Fore.GREEN}{opp.sell_exchange.upper()}",
                        f"${opp.sell_price:.6f}",
                        f"{profit_color}{opp.profit_percent:.3f}%",
                        f"{Fore.WHITE}${profit_per_1k:.2f}",
                        f"{Fore.MAGENTA}{opp.spread:.3f}%"
                    ])
                
                # Print table
                headers = ['Coin', 'Buy From', 'Buy Price', 'Sell To', 'Sell Price', 'Profit', 'Profit/$1k', 'Spread']
                print(tabulate(table_data, headers=headers, tablefmt='grid'))
                
                # Show recommendation for best opportunity in tier
                if grouped[tier]:
                    best = grouped[tier][0]
                    _, _, icon, max_trade = self.get_coin_info(best.symbol)
                    print(f"\n{icon} Best in {tier}: {best.symbol.replace('USDT', '')} - "
                          f"{best.profit_percent:.2f}% profit | "
                          f"Recommended trade: ${max_trade:,}")
    
    async def scan_once(self):
        """Perform a single arbitrage scan"""
        self.scan_count += 1
        print(f"\n{Fore.CYAN}{'='*50}")
        print(f"🔍 SCAN #{self.scan_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*50}{Style.RESET_ALL}")
        
        start_time = datetime.now()
        
        # Fetch prices from all exchanges
        print(f"📡 Fetching prices from {len(self.exchange_manager.exchanges)} exchanges...")
        prices = await self.exchange_manager.fetch_prices()
        
        # Show exchange status
        self.print_exchange_status(prices)
        
        # Find arbitrage opportunities
        print(f"🔎 Analyzing {len(self.symbols)} trading pairs...")
        opportunities = self.calculator.find_opportunities(prices)
        
        # Display results
        self.print_opportunities(opportunities)
        
        # Performance metrics
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n⏱️  Scan completed in {elapsed:.2f} seconds")
        
        return opportunities
    
    async def run(self):
        """Main execution loop"""
        self.print_header()
        
        print(f"\n{Fore.GREEN}✅ Scanner initialized successfully!")
        print(f"{Fore.YELLOW}⚠️  Press Ctrl+C to stop scanning{Style.RESET_ALL}")
        
        try:
            while True:
                await self.scan_once()
                
                # Wait for next scan
                if self.scan_interval > 0:
                    print(f"\n💤 Waiting {self.scan_interval} seconds until next scan...")
                    await asyncio.sleep(self.scan_interval)
                    
        except KeyboardInterrupt:
            print(f"\n\n{Fore.YELLOW}⚠️ Scanner stopped by user{Style.RESET_ALL}")
            print(f"{Fore.GREEN}📊 Final Stats: {self.scan_count} scans completed{Style.RESET_ALL}")
            print(f"{Fore.CYAN}👋 Goodbye!{Style.RESET_ALL}")

async def main():
    """Entry point"""
    # Configuration - adjust these as needed
    MIN_PROFIT_PERCENT = 0.3  # Minimum 0.3% profit after fees
    SCAN_INTERVAL_SECONDS = 3  # Scan every 3 seconds
    
    scanner = ArbitrageScanner(
        min_profit_percent=MIN_PROFIT_PERCENT,
        scan_interval=SCAN_INTERVAL_SECONDS
    )
    
    await scanner.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Exiting...{Style.RESET_ALL}")
        sys.exit(0)
