"""
Periodic reporting for balance and P&L tracking.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Any, Dict
from decimal import Decimal


@dataclass
class WalletSnapshot:
    """Snapshot of wallet state at a point in time."""
    timestamp: float
    base_balance: float
    quote_balance: float
    base_price: Optional[float]  # quote per base
    portfolio_value_quote: float  # total value in quote currency
    

class PeriodicReporter:
    """
    Tracks and reports balance and P&L periodically.
    """
    
    def __init__(
        self,
        wallet_name: str,
        strategy_name: str,
        base_symbol: str,
        quote_symbol: str,
        report_interval: float = 60.0  # 1 minute
    ):
        self.wallet_name = wallet_name
        self.strategy_name = strategy_name
        self.base_symbol = base_symbol
        self.quote_symbol = quote_symbol
        self.report_interval = report_interval
        
        self.initial_snapshot: Optional[WalletSnapshot] = None
        self.last_snapshot: Optional[WalletSnapshot] = None
        self.last_report_time = 0.0
        self.snapshots: list[WalletSnapshot] = []
    
    def should_report(self) -> bool:
        """Check if it's time for periodic report."""
        current_time = time.time()
        return (current_time - self.last_report_time) >= self.report_interval
    
    def take_snapshot(
        self,
        connector: Any,
        force: bool = False
    ) -> Optional[WalletSnapshot]:
        """
        Take balance snapshot and report if interval elapsed.
        
        Args:
            connector: Exchange connector to query balances
            force: Force snapshot even if interval hasn't elapsed
        """
        try:
            base_balance = connector.get_balance(self.base_symbol)
            quote_balance = connector.get_balance(self.quote_symbol)
            
            # Get current price
            try:
                base_price = connector.get_price_fast(self.base_symbol, self.quote_symbol)
            except Exception:
                try:
                    base_price = connector.get_price(self.base_symbol, self.quote_symbol)
                except Exception:
                    base_price = self.last_snapshot.base_price if self.last_snapshot else None
            
            # Calculate portfolio value
            portfolio_value = quote_balance
            if base_price and base_price > 0:
                portfolio_value += base_balance * base_price
            
            snapshot = WalletSnapshot(
                timestamp=time.time(),
                base_balance=base_balance,
                quote_balance=quote_balance,
                base_price=base_price,
                portfolio_value_quote=portfolio_value
            )
            
            # Store initial snapshot
            if self.initial_snapshot is None:
                self.initial_snapshot = snapshot
                self._log_initial(snapshot)
            
            self.last_snapshot = snapshot
            self.snapshots.append(snapshot)
            
            # Report if interval elapsed or forced
            if force or self.should_report():
                self._log_periodic(snapshot)
                self.last_report_time = time.time()
            
            return snapshot
            
        except Exception as e:
            prefix = f"[{self.wallet_name}] [{self.strategy_name}]"
            print(f"{prefix} ⚠ Error taking snapshot: {e}")
            return None
    
    def _log_initial(self, snapshot: WalletSnapshot):
        """Log initial balance state."""
        prefix = f"[{self.wallet_name}] [{self.strategy_name}]"
        print(f"\n{prefix} === Initial Balance ===")
        print(f"{prefix} {self.base_symbol}: {snapshot.base_balance:.6f}")
        print(f"{prefix} {self.quote_symbol}: {snapshot.quote_balance:.2f}")
        if snapshot.base_price:
            print(f"{prefix} Price: {snapshot.base_price:.8f} {self.quote_symbol}/{self.base_symbol}")
        print(f"{prefix} Portfolio Value: {snapshot.portfolio_value_quote:.2f} {self.quote_symbol}")
        print()
    
    def _log_periodic(self, snapshot: WalletSnapshot):
        """Log periodic balance and P&L update."""
        if not self.initial_snapshot:
            return
        
        prefix = f"[{self.wallet_name}] [{self.strategy_name}]"
        
        # Calculate changes
        base_change = snapshot.base_balance - self.initial_snapshot.base_balance
        quote_change = snapshot.quote_balance - self.initial_snapshot.quote_balance
        
        # Calculate P&L
        pnl = snapshot.portfolio_value_quote - self.initial_snapshot.portfolio_value_quote
        pnl_pct = (pnl / self.initial_snapshot.portfolio_value_quote * 100) if self.initial_snapshot.portfolio_value_quote > 0 else 0
        
        print(f"\n{prefix} === Balance Update ===")
        print(f"{prefix} {self.base_symbol}: {snapshot.base_balance:.6f} ({base_change:+.6f})")
        print(f"{prefix} {self.quote_symbol}: {snapshot.quote_balance:.2f} ({quote_change:+.2f})")
        
        if snapshot.base_price:
            print(f"{prefix} Current Price: {snapshot.base_price:.8f} {self.quote_symbol}/{self.base_symbol}")
        
        print(f"{prefix} Portfolio Value: {snapshot.portfolio_value_quote:.2f} {self.quote_symbol}")
        print(f"{prefix} P&L: {pnl:+.2f} {self.quote_symbol} ({pnl_pct:+.2f}%)")
        print()
    
    def generate_final_report(self) -> Dict[str, Any]:
        """Generate final report with complete statistics."""
        if not self.initial_snapshot or not self.last_snapshot:
            return {}
        
        # Take final snapshot
        duration = self.last_snapshot.timestamp - self.initial_snapshot.timestamp
        
        # Calculate changes
        base_change = self.last_snapshot.base_balance - self.initial_snapshot.base_balance
        quote_change = self.last_snapshot.quote_balance - self.initial_snapshot.quote_balance
        
        # Calculate P&L
        pnl = self.last_snapshot.portfolio_value_quote - self.initial_snapshot.portfolio_value_quote
        pnl_pct = (pnl / self.initial_snapshot.portfolio_value_quote * 100) if self.initial_snapshot.portfolio_value_quote > 0 else 0
        
        return {
            "wallet_name": self.wallet_name,
            "duration_seconds": duration,
            "initial": {
                "base": self.initial_snapshot.base_balance,
                "quote": self.initial_snapshot.quote_balance,
                "portfolio_value": self.initial_snapshot.portfolio_value_quote,
            },
            "final": {
                "base": self.last_snapshot.base_balance,
                "quote": self.last_snapshot.quote_balance,
                "portfolio_value": self.last_snapshot.portfolio_value_quote,
            },
            "changes": {
                "base": base_change,
                "quote": quote_change,
            },
            "pnl": {
                "amount": pnl,
                "percentage": pnl_pct,
            },
            "snapshots_taken": len(self.snapshots),
        }
    
    def print_final_report(self):
        """Print formatted final report."""
        report = self.generate_final_report()
        if not report:
            return
        
        prefix = f"[{self.wallet_name}] [{self.strategy_name}]"
        
        print(f"\n{prefix} {'=' * 50}")
        print(f"{prefix} FINAL REPORT - {self.wallet_name}")
        print(f"{prefix} {'=' * 50}")
        
        print(f"{prefix}")
        print(f"{prefix} Duration: {report['duration_seconds'] / 60:.1f} minutes")
        print(f"{prefix}")
        
        print(f"{prefix} Initial Balances:")
        print(f"{prefix}   {self.base_symbol}: {report['initial']['base']:.6f}")
        print(f"{prefix}   {self.quote_symbol}: {report['initial']['quote']:.2f}")
        print(f"{prefix}   Portfolio: {report['initial']['portfolio_value']:.2f} {self.quote_symbol}")
        print(f"{prefix}")
        
        print(f"{prefix} Final Balances:")
        print(f"{prefix}   {self.base_symbol}: {report['final']['base']:.6f}")
        print(f"{prefix}   {self.quote_symbol}: {report['final']['quote']:.2f}")
        print(f"{prefix}   Portfolio: {report['final']['portfolio_value']:.2f} {self.quote_symbol}")
        print(f"{prefix}")
        
        print(f"{prefix} Changes:")
        print(f"{prefix}   {self.base_symbol}: {report['changes']['base']:+.6f}")
        print(f"{prefix}   {self.quote_symbol}: {report['changes']['quote']:+.2f}")
        print(f"{prefix}")
        
        pnl_sign = "+" if report['pnl']['amount'] >= 0 else ""
        print(f"{prefix} Profit/Loss:")
        print(f"{prefix}   Amount: {pnl_sign}{report['pnl']['amount']:.2f} {self.quote_symbol}")
        print(f"{prefix}   Percentage: {report['pnl']['percentage']:+.2f}%")
        print(f"{prefix}")
        
        print(f"{prefix} {'=' * 50}\n")


class AggregateReporter:
    """Aggregates reports from multiple wallets."""
    
    def __init__(self, strategy_name: str, base_symbol: str, quote_symbol: str):
        self.strategy_name = strategy_name
        self.base_symbol = base_symbol
        self.quote_symbol = quote_symbol
        self.reporters: list[PeriodicReporter] = []
    
    def add_reporter(self, reporter: PeriodicReporter):
        """Add a wallet reporter."""
        self.reporters.append(reporter)
    
    def print_aggregate_report(self):
        """Print aggregated final report across all wallets."""
        if not self.reporters:
            return
        
        reports = [r.generate_final_report() for r in self.reporters]
        reports = [r for r in reports if r]  # Filter empty reports
        
        if not reports:
            return
        
        # Aggregate statistics
        total_initial_value = sum(r['initial']['portfolio_value'] for r in reports)
        total_final_value = sum(r['final']['portfolio_value'] for r in reports)
        total_pnl = total_final_value - total_initial_value
        total_pnl_pct = (total_pnl / total_initial_value * 100) if total_initial_value > 0 else 0
        
        total_base_change = sum(r['changes']['base'] for r in reports)
        total_quote_change = sum(r['changes']['quote'] for r in reports)
        
        print(f"\n[{self.strategy_name}] {'=' * 50}")
        print(f"[{self.strategy_name}] AGGREGATE REPORT - All Wallets")
        print(f"[{self.strategy_name}] {'=' * 50}")
        print(f"[{self.strategy_name}]")
        print(f"[{self.strategy_name}] Total Wallets: {len(reports)}")
        print(f"[{self.strategy_name}]")
        
        print(f"[{self.strategy_name}] Initial Portfolio Value: {total_initial_value:.2f} {self.quote_symbol}")
        print(f"[{self.strategy_name}] Final Portfolio Value: {total_final_value:.2f} {self.quote_symbol}")
        print(f"[{self.strategy_name}]")
        
        print(f"[{self.strategy_name}] Total Changes:")
        print(f"[{self.strategy_name}]   {self.base_symbol}: {total_base_change:+.6f}")
        print(f"[{self.strategy_name}]   {self.quote_symbol}: {total_quote_change:+.2f}")
        print(f"[{self.strategy_name}]")
        
        pnl_sign = "+" if total_pnl >= 0 else ""
        print(f"[{self.strategy_name}] Total Profit/Loss:")
        print(f"[{self.strategy_name}]   Amount: {pnl_sign}{total_pnl:.2f} {self.quote_symbol}")
        print(f"[{self.strategy_name}]   Percentage: {total_pnl_pct:+.2f}%")
        print(f"[{self.strategy_name}]")
        print(f"[{self.strategy_name}] {'=' * 50}\n")
