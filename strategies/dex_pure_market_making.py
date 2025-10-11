from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional

from connectors.dex.pancakeswap import PancakeSwapConnector
from strategies.engine import StrategyLoop, StrategyLoopConfig
from strategies.utils import compute_spend_amount, is_exact_output_case
from strategies.order_manager import OrderManager, format_timestamp
from strategies.periodic_reporter import PeriodicReporter, AggregateReporter
from strategies.resilience import ConnectionMonitor, resilient_call, RetryConfig


@dataclass
class DexPureMMConfig:
    rpc_url: str
    private_keys: List[str]
    chain_id: int
    base_symbol: str
    quote_symbol: str
    upper_percent: float  # e.g., 0.5 for +0.5%
    lower_percent: float  # e.g., 0.5 for -0.5%
    levels_each_side: int
    order_amount: float
    amount_is_base: bool
    refresh_seconds: float
    amount_basis_is_base: Optional[bool] = None
    slippage_bps: int = 50
    tick_interval_seconds: float = 1.0


class DexPureMarketMaking:
    """
    Simulates symmetric limit orders around current price with periodic refresh.

    - Builds levels above/below current price at configured percentage spacing
    - Executes orders when triggers are crossed, across all wallets
    - Periodically cancels (no on-chain cancel needed for simulated) and rebuilds around latest price
    - Retries failed orders on subsequent ticks
    """

    def __init__(self, cfg: DexPureMMConfig, connectors: Optional[List[PancakeSwapConnector]] = None) -> None:
        self.cfg = cfg
        self.connectors: List[PancakeSwapConnector] = connectors or [
            PancakeSwapConnector(rpc_url=cfg.rpc_url, private_key=pk, chain_id=cfg.chain_id)
            for pk in cfg.private_keys
        ]
        self.upper_levels: List[float] = []
        self.lower_levels: List[float] = []
        self._last_refresh_ts: float = 0.0
        self._stopped: bool = False
        self._start_time: Optional[float] = None  # Set when strategy starts
        
        # Initialize order managers and reporters per wallet
        self.order_managers: List[OrderManager] = []
        self.reporters: List[PeriodicReporter] = []
        
        for i, conn in enumerate(self.connectors):
            wallet_name = f"wallet_{i+1}"
            self.order_managers.append(OrderManager(wallet_name=wallet_name, strategy_name="dex_pmm"))
            self.reporters.append(PeriodicReporter(
                wallet_name=wallet_name,
                strategy_name="dex_pmm",
                base_symbol=cfg.base_symbol,
                quote_symbol=cfg.quote_symbol,
                report_interval=60.0
            ))
        
        # Aggregate reporter
        self.aggregate_reporter = AggregateReporter(
            strategy_name="dex_pmm",
            base_symbol=cfg.base_symbol,
            quote_symbol=cfg.quote_symbol
        )
        for reporter in self.reporters:
            self.aggregate_reporter.add_reporter(reporter)
        
        # Connection monitoring
        self._connection_monitor = ConnectionMonitor("dex_pmm")
        self._retry_config = RetryConfig(max_retries=5, initial_delay=2.0)
        
        self._loop = StrategyLoop(StrategyLoopConfig(
            interval_seconds=cfg.tick_interval_seconds,
            on_tick=self._on_tick,
            on_error=self._on_error,
        ))

    def _price(self) -> Optional[tuple[float, str]]:
        """Get current price with resilience to network failures."""
        def get_fast_price():
            px = self.connectors[0].get_price_fast(self.cfg.base_symbol, self.cfg.quote_symbol)
            return px, "get_price_fast"
        
        def get_regular_price():
            px = self.connectors[0].get_price(self.cfg.base_symbol, self.cfg.quote_symbol)
            return px, "get_price"
        
        result = resilient_call(
            get_fast_price,
            retry_config=self._retry_config,
            on_retry=lambda attempt, error: print(f"[dex_pmm] Price fetch attempt {attempt + 1} failed: {error}"),
            fallback=None
        )
        
        if result is not None:
            self._connection_monitor.record_success()
            return result
        
        result = resilient_call(
            get_regular_price,
            retry_config=self._retry_config,
            on_retry=lambda attempt, error: print(f"[dex_pmm] Price fetch (fallback) attempt {attempt + 1} failed: {error}"),
            fallback=None
        )
        
        if result is not None:
            self._connection_monitor.record_success()
        else:
            self._connection_monitor.record_failure(Exception("Failed to fetch price"))
        
        return result

    def _rebuild_levels(self, mid: float) -> None:
        # Compute geometric steps by percentage around mid price
        up = []
        dn = []
        for i in range(1, self.cfg.levels_each_side + 1):
            up.append(mid * (1.0 + self.cfg.upper_percent / 100.0 * i))
            dn.append(mid * (1.0 - self.cfg.lower_percent / 100.0 * i))
        self.upper_levels = up
        self.lower_levels = dn

    def _quantize(self, symbol: str, amount: float) -> float:
        qf = getattr(self.connectors[0], "quantize_amount", None)
        if callable(qf):
            try:
                return float(qf(symbol, amount))
            except Exception:
                return float(amount)
        return float(amount)

    def _execute_order_at_level(self, level: float, price: float, is_upper: bool) -> bool:
        """Execute market making order using OrderManager."""
        if self._stopped:
            return False
        
        basis_is_base = self.cfg.amount_basis_is_base if self.cfg.amount_basis_is_base is not None else self.cfg.amount_is_base
        spend_is_base = is_upper  # upper level = sell base, lower level = buy base
        side = "sell" if spend_is_base else "buy"
        
        all_success = True
        
        # Execute order for each wallet
        for wallet_idx, (conn, order_mgr) in enumerate(zip(self.connectors, self.order_managers)):
            # Determine spend symbol
            spend_symbol = self.cfg.base_symbol if spend_is_base else self.cfg.quote_symbol
            
            # Create order
            order = order_mgr.create_order(
                base_symbol=self.cfg.base_symbol,
                quote_symbol=self.cfg.quote_symbol,
                side=side,
                amount=self.cfg.order_amount,
                price=price,
                reason=f"{'Upper' if is_upper else 'Lower'} level at {level:.8f}"
            )
            
            # Determine spend amount for validation
            if is_exact_output_case(basis_is_base, spend_is_base):
                # order_amount is target output
                target_out_symbol = self.cfg.quote_symbol if spend_is_base else self.cfg.base_symbol
                order.amount_symbol = target_out_symbol
                # Estimate spend for validation (with buffer)
                spend_amt_estimate = compute_spend_amount(price, self.cfg.order_amount, basis_is_base, spend_is_base)
                spend_amt_estimate = self._quantize(spend_symbol, spend_amt_estimate * 1.1)
            else:
                # order_amount is spend amount
                order.amount_symbol = spend_symbol
                spend_amt = compute_spend_amount(price, self.cfg.order_amount, basis_is_base, spend_is_base)
                spend_amt_estimate = self._quantize(spend_symbol, spend_amt)
            
            # Pre-order validation
            check = order_mgr.validate_order(conn, spend_symbol, spend_amt_estimate)
            if not check.passed:
                order_mgr.mark_failed(order, check.reason)
                print(f"[wallet_{wallet_idx+1}] [dex_pmm] Skipping level {level:.8f}: {check.reason}")
                all_success = False
                continue
            
            # Submit order with retry
            def submit_swap():
                if is_exact_output_case(basis_is_base, spend_is_base):
                    if spend_is_base:
                        return conn.swap_exact_out(self.cfg.base_symbol, self.cfg.quote_symbol, target_out_amount=self.cfg.order_amount, slippage_bps=self.cfg.slippage_bps)
                    else:
                        return conn.swap_exact_out(self.cfg.quote_symbol, self.cfg.base_symbol, target_out_amount=self.cfg.order_amount, slippage_bps=self.cfg.slippage_bps)
                else:
                    return conn.market_swap(
                        base_symbol=self.cfg.base_symbol,
                        quote_symbol=self.cfg.quote_symbol,
                        amount=spend_amt_estimate,
                        amount_is_base=spend_is_base,
                        slippage_bps=self.cfg.slippage_bps,
                        side=side,
                    )
            
            success = order_mgr.submit_order_with_retry(order, submit_swap, conn.tx_explorer_url)
            if success:
                order_mgr.mark_filled(order)
                # Wait briefly to allow transaction to propagate and nonce to update
                import time
                time.sleep(2)
            else:
                all_success = False
        
        return all_success

    def _on_tick(self) -> None:
        """Tick handler with resilience and periodic reporting."""
        if self._stopped:
            return
        
        import time
        
        # Periodic balance reporting
        for i, reporter in enumerate(self.reporters):
            try:
                reporter.take_snapshot(self.connectors[i])
            except Exception:
                pass
        
        # Check connection health
        if self._connection_monitor.should_warn():
            print(f"[dex_pmm] ⚠ Warning: {self._connection_monitor.consecutive_failures} consecutive connection failures")
        
        now = time.time()
        p = self._price()
        if p is None:
            print("[dex_pmm] Network issue; waiting to reconnect...")
            return
        
        px, method = p
        
        # Refresh levels periodically
        if now - self._last_refresh_ts >= float(self.cfg.refresh_seconds) or not (self.upper_levels and self.lower_levels):
            self._rebuild_levels(px)
            self._last_refresh_ts = now
            
            # Show updated levels
            print(f"\n[dex_pmm] === Price Levels Refreshed (Mid: {px:.8f}) ===")
            print(f"[dex_pmm] Upper levels (SELL {self.cfg.base_symbol}):")
            for i, lvl in enumerate(sorted(self.upper_levels), 1):
                print(f"[dex_pmm]   #{i}: {lvl:.8f} (+{((lvl - px) / px * 100):.2f}%)")
            print(f"[dex_pmm] Lower levels (BUY {self.cfg.base_symbol}):")
            for i, lvl in enumerate(sorted(self.lower_levels, reverse=True), 1):
                print(f"[dex_pmm]   #{i}: {lvl:.8f} ({((lvl - px) / px * 100):.2f}%)")
            print()

        # Check price levels and execute orders
        fired = False
        fired_level = None
        
        # Check upper levels (sell base)
        for lvl in sorted(self.upper_levels):
            if px >= lvl:
                if self._execute_order_at_level(lvl, px, is_upper=True):
                    fired = True
                    fired_level = f"upper {lvl:.8f}"
                break
        
        # If no upper level triggered, check lower levels (buy base)
        if not fired:
            for lvl in sorted(self.lower_levels, reverse=True):
                if px <= lvl:
                    if self._execute_order_at_level(lvl, px, is_upper=False):
                        fired = True
                        fired_level = f"lower {lvl:.8f}"
                    break
        
        # Periodic status logging (every 10 seconds)
        if int(now) % 10 == 0:
            # Find nearest levels
            nearest_upper = min([lvl for lvl in self.upper_levels if lvl > px], default=None)
            nearest_lower = max([lvl for lvl in self.lower_levels if lvl < px], default=None)
            
            status_parts = []
            if fired:
                status_parts.append(f"✓ Order fired at {fired_level}")
            else:
                status_parts.append("Waiting")
            
            if nearest_upper:
                dist_up = ((nearest_upper - px) / px * 100)
                status_parts.append(f"Next SELL: {nearest_upper:.8f} (+{dist_up:.2f}%)")
            
            if nearest_lower:
                dist_down = ((px - nearest_lower) / nearest_lower * 100)
                status_parts.append(f"Next BUY: {nearest_lower:.8f} (-{dist_down:.2f}%)")
            
            timestamp = format_timestamp(self._start_time)
            try:
                total_base = sum(conn.get_balance(self.cfg.base_symbol) for conn in self.connectors)
                total_quote = sum(conn.get_balance(self.cfg.quote_symbol) for conn in self.connectors)
                portfolio_value = total_quote + (total_base * px)
                print(f"{timestamp} [dex_pmm] Price: {px:.8f} | {' | '.join(status_parts)} | Total balance (all wallets): {self.cfg.base_symbol}={total_base:.6f}, {self.cfg.quote_symbol}={total_quote:.2f} | Portfolio value: {portfolio_value:.2f} USDT")
            except Exception:
                print(f"{timestamp} [dex_pmm] Price: {px:.8f} | {' | '.join(status_parts)}")

    def _on_error(self, e: Exception) -> None:
        """Error handler - logs error but allows strategy to continue."""
        print(f"[dex_pmm] ⚠ Error in strategy loop: {e}")
        print(f"[dex_pmm] Strategy will continue running...")
        self._connection_monitor.record_failure(e)

    def start(self) -> None:
        """Start strategy with initial balance snapshots."""
        self._start_time = time.time()
        print("[dex_pmm] Starting strategy...")
        
        # Update order managers with start time
        for order_mgr in self.order_managers:
            order_mgr.strategy_start_time = self._start_time
        
        # Take initial snapshots
        for i, reporter in enumerate(self.reporters):
            try:
                reporter.take_snapshot(self.connectors[i], force=True)
            except Exception as e:
                print(f"[dex_pmm] Warning: Could not take initial snapshot for wallet {i+1}: {e}")
        
        print(f"[dex_pmm] Monitoring {len(self.connectors)} wallet(s)")
        print(f"[dex_pmm] Levels per side: {self.cfg.levels_each_side}")
        print(f"[dex_pmm] Spread: ±{self.cfg.upper_percent}%/±{self.cfg.lower_percent}%")
        print(f"[dex_pmm] Order amount: {self.cfg.order_amount} ({self.cfg.base_symbol if self.cfg.amount_is_base else self.cfg.quote_symbol})")
        print(f"[dex_pmm] Strategy will continue running even if network errors occur\n")
        
        self._loop.start()

    def stop(self) -> None:
        """Stop strategy and print final reports."""
        if self._stopped:
            return
        
        self._stopped = True
        self._loop.stop()
        
        print("\n[dex_pmm] Stopping strategy...")
        
        # Wait briefly for any pending transactions to be confirmed
        import time
        time.sleep(1)
        
        # Print final snapshots and P&L reports
        for i, reporter in enumerate(self.reporters):
            try:
                reporter.take_snapshot(self.connectors[i], force=True)
                reporter.print_final_report()
            except Exception as e:
                print(f"[dex_pmm] Error generating report for wallet {i+1}: {e}")
        
        # Print aggregate report
        try:
            self.aggregate_reporter.print_aggregate_report()
        except Exception as e:
            print(f"[dex_pmm] Error generating aggregate report: {e}")
        
        # Print order summary for each wallet
        for i, order_manager in enumerate(self.order_managers):
            summary = order_manager.get_summary()
            print(f"\n[wallet_{i+1}] === Order Summary ===")
            print(f"[wallet_{i+1}] Total Orders: {summary['total']}")
            print(f"[wallet_{i+1}] Filled: {summary['filled']}")
            print(f"[wallet_{i+1}] Failed: {summary['failed']}")
            print(f"[wallet_{i+1}] Success Rate: {summary['success_rate']:.1f}%")
        
        # Print connection statistics
        stats = self._connection_monitor.get_stats()
        print(f"\n[dex_pmm] === Connection Statistics ===")
        print(f"[dex_pmm] Total Attempts: {stats['total_attempts']}")
        print(f"[dex_pmm] Successful: {stats['successful']}")
        print(f"[dex_pmm] Failed: {stats['failed']}")
        print(f"[dex_pmm] Success Rate: {stats['success_rate']:.1f}%\n")


