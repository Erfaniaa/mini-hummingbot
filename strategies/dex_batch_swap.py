from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from connectors.dex.pancakeswap import PancakeSwapConnector
from strategies.engine import StrategyLoop, StrategyLoopConfig
from strategies.utils import compute_spend_amount, is_exact_output_case
from strategies.order_manager import OrderManager, format_timestamp
from strategies.periodic_reporter import PeriodicReporter, AggregateReporter
from strategies.resilience import ConnectionMonitor, resilient_call, RetryConfig


@dataclass
class DexBatchSwapConfig:
    rpc_url: str
    private_keys: List[str]  # one per wallet (supports multi-wallet)
    chain_id: int
    base_symbol: str
    quote_symbol: str
    total_amount: float
    min_price: float  # observed as quote per base
    max_price: float
    num_orders: int
    distribution: str  # "uniform" | "bell"
    # amount basis separate from spend side
    amount_is_base: bool  # backward compat; prefer amount_basis_is_base when provided
    amount_basis_is_base: Optional[bool] = None
    spend_is_base: Optional[bool] = None
    interval_seconds: float = 1.0
    slippage_bps: int = 50


def _compute_distribution_weights(n: int, kind: str) -> List[float]:
    if n <= 0:
        return []
    if kind == "uniform":
        return [1.0 / n] * n
    # bell-shaped: sample Gaussian centered in the middle
    center = (n - 1) / 2.0
    sigma = max(1.0, n / 6.0)
    weights = []
    for i in range(n):
        w = math.exp(-0.5 * ((i - center) / sigma) ** 2)
        weights.append(w)
    s = sum(weights)
    return [w / s for w in weights]


def _generate_levels(min_price: float, max_price: float, num_orders: int) -> List[float]:
    if num_orders == 1:
        return [min_price]
    step = (max_price - min_price) / float(num_orders - 1)
    return [min_price + i * step for i in range(num_orders)]


class DexBatchSwap:
    """
    One-sided ladder of simulated limit orders via market swaps.

    Observed price is quote_per_base from the connector.
    - For base->quote conversions: execute when price >= level
    - For quote->base conversions: execute when price <= level
    """

    def __init__(self, cfg: DexBatchSwapConfig, connectors: Optional[List[PancakeSwapConnector]] = None) -> None:
        self.cfg = cfg
        self.connectors: List[PancakeSwapConnector] = connectors or [
            PancakeSwapConnector(rpc_url=cfg.rpc_url, private_key=pk, chain_id=cfg.chain_id)
            for pk in cfg.private_keys
        ]
        self.levels: List[float] = _generate_levels(cfg.min_price, cfg.max_price, cfg.num_orders)
        self.weights: List[float] = _compute_distribution_weights(cfg.num_orders, cfg.distribution)
        self.remaining: List[float] = [cfg.total_amount * w for w in self.weights]
        self.done: List[bool] = [False] * cfg.num_orders
        self._tick_counter: int = 0
        self._stopped: bool = False
        self._start_time: Optional[float] = None  # Set when strategy starts
        
        # Initialize order managers and reporters per wallet
        self.order_managers: List[OrderManager] = []
        self.reporters: List[PeriodicReporter] = []
        
        for i, conn in enumerate(self.connectors):
            wallet_name = f"wallet_{i+1}"
            self.order_managers.append(OrderManager(wallet_name=wallet_name, strategy_name="dex_batch_swap"))
            self.reporters.append(PeriodicReporter(
                wallet_name=wallet_name,
                strategy_name="dex_batch_swap",
                base_symbol=cfg.base_symbol,
                quote_symbol=cfg.quote_symbol,
                report_interval=60.0  # 1 minute
            ))
        
        # Aggregate reporter
        self.aggregate_reporter = AggregateReporter(
            strategy_name="dex_batch_swap",
            base_symbol=cfg.base_symbol,
            quote_symbol=cfg.quote_symbol
        )
        for reporter in self.reporters:
            self.aggregate_reporter.add_reporter(reporter)
        
        # Connection monitoring
        self._connection_monitor = ConnectionMonitor("dex_batch_swap")
        self._retry_config = RetryConfig(max_retries=5, initial_delay=2.0)
        
        self._loop = StrategyLoop(StrategyLoopConfig(
            interval_seconds=cfg.interval_seconds,
            on_tick=self._on_tick,
            on_error=self._on_error,
        ))

    def _current_price(self) -> Optional[Tuple[float, str]]:
        """Get current price with resilience to network failures."""
        def get_fast_price():
            px = self.connectors[0].get_price_fast(self.cfg.base_symbol, self.cfg.quote_symbol)
            return px, "get_price_fast"
        
        def get_regular_price():
            px = self.connectors[0].get_price(self.cfg.base_symbol, self.cfg.quote_symbol)
            return px, "get_price"
        
        # Try fast price first
        result = resilient_call(
            get_fast_price,
            retry_config=self._retry_config,
            on_retry=lambda attempt, error: print(f"[dex_batch_swap] Price fetch attempt {attempt + 1} failed: {error}"),
            fallback=None
        )
        
        if result is not None:
            self._connection_monitor.record_success()
            return result
        
        # Fallback to regular price
        result = resilient_call(
            get_regular_price,
            retry_config=self._retry_config,
            on_retry=lambda attempt, error: print(f"[dex_batch_swap] Price fetch (fallback) attempt {attempt + 1} failed: {error}"),
            fallback=None
        )
        
        if result is not None:
            self._connection_monitor.record_success()
        else:
            self._connection_monitor.record_failure(Exception("Failed to fetch price"))
        
        return result

    def _should_execute(self, price: float, level: float) -> bool:
        """Check if price has reached the level to execute order."""
        spend_is_base = self.cfg.spend_is_base if self.cfg.spend_is_base is not None else self.cfg.amount_is_base
        
        if spend_is_base:
            # Selling base: execute when price reaches or exceeds level
            return price >= level
        else:
            # Buying base: execute when price reaches or drops below level
            return price <= level

    def _quantize(self, symbol: str, amount: float) -> float:
        qf = getattr(self.connectors[0], "quantize_amount", None)
        if callable(qf):
            try:
                return float(qf(symbol, amount))
            except Exception:
                return float(amount)
        return float(amount)

    def _execute_level(self, li: int, amount_user_basis: float, price: float) -> None:
        """Execute a level using OrderManager for proper tracking and validation."""
        if self._stopped:
            return
        
        basis_is_base = self.cfg.amount_basis_is_base if self.cfg.amount_basis_is_base is not None else self.cfg.amount_is_base
        spend_is_base = self.cfg.spend_is_base if self.cfg.spend_is_base is not None else self.cfg.amount_is_base
        side = "sell" if spend_is_base else "buy"
        
        # Create order for each wallet
        for wallet_idx, (conn, order_mgr) in enumerate(zip(self.connectors, self.order_managers)):
            # Determine spend symbol and amount symbol
            spend_symbol = self.cfg.base_symbol if spend_is_base else self.cfg.quote_symbol
            
            # Create order
            order = order_mgr.create_order(
                base_symbol=self.cfg.base_symbol,
                quote_symbol=self.cfg.quote_symbol,
                side=side,
                amount=amount_user_basis,
                price=price,
                reason=f"Price level {li+1}/{len(self.levels)}: {self.levels[li]:.8f}"
            )
            
            # Determine spend amount for validation
            if is_exact_output_case(basis_is_base, spend_is_base):
                # amount_user_basis is target output
                target_out_symbol = self.cfg.quote_symbol if spend_is_base else self.cfg.base_symbol
                order.amount_symbol = target_out_symbol
                # For exact output, we don't know exact spend until swap, use estimate
                spend_amt_estimate = compute_spend_amount(price, amount_user_basis, basis_is_base, spend_is_base)
                spend_amt_estimate = self._quantize(spend_symbol, spend_amt_estimate * 1.1)  # 10% buffer for slippage
            else:
                # amount_user_basis is spend amount
                order.amount_symbol = spend_symbol
                spend_amt = compute_spend_amount(price, amount_user_basis, basis_is_base, spend_is_base)
                spend_amt_estimate = self._quantize(spend_symbol, spend_amt)
            
            # Pre-order validation
            check = order_mgr.validate_order(conn, spend_symbol, spend_amt_estimate)
            if not check.passed:
                order_mgr.mark_failed(order, check.reason)
                print(f"[wallet_{wallet_idx+1}] [dex_batch_swap] Skipping level {li+1}: {check.reason}")
                continue
            
            # Submit order with retry
            def submit_swap():
                if is_exact_output_case(basis_is_base, spend_is_base):
                    if spend_is_base:
                        return conn.swap_exact_out(self.cfg.base_symbol, self.cfg.quote_symbol, target_out_amount=amount_user_basis, slippage_bps=self.cfg.slippage_bps)
                    else:
                        return conn.swap_exact_out(self.cfg.quote_symbol, self.cfg.base_symbol, target_out_amount=amount_user_basis, slippage_bps=self.cfg.slippage_bps)
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
        
        # Mark level as done
        self.done[li] = True
        self.remaining[li] = 0.0

    def _balances_summary(self) -> str:
        """Return summary of total balances across all wallets with USDT value."""
        try:
            total_base = sum(conn.get_balance(self.cfg.base_symbol) for conn in self.connectors)
            total_quote = sum(conn.get_balance(self.cfg.quote_symbol) for conn in self.connectors)
            
            # Get current price for portfolio value
            try:
                px = self.connectors[0].get_price_fast(self.cfg.base_symbol, self.cfg.quote_symbol)
                portfolio_value = total_quote + (total_base * px)
                return f"Total balance (all wallets): {self.cfg.base_symbol}={total_base:.6f}, {self.cfg.quote_symbol}={total_quote:.2f} | Portfolio value: {portfolio_value:.2f} USDT"
            except Exception:
                return f"Total balance (all wallets): {self.cfg.base_symbol}={total_base:.6f}, {self.cfg.quote_symbol}={total_quote:.2f}"
        except Exception:
            return "Total balance: unavailable"

    def _on_tick(self) -> None:
        """Tick handler with resilience - continues even if individual operations fail."""
        if self._stopped:
            return
        
        self._tick_counter += 1
        
        # Periodic balance reporting (every reporter checks its own interval)
        for i, reporter in enumerate(self.reporters):
            try:
                reporter.take_snapshot(self.connectors[i])
            except Exception as e:
                # Don't stop strategy if snapshot fails
                pass
        
        # Check connection health
        if self._connection_monitor.should_warn():
            print(f"[dex_batch_swap] ⚠ Warning: {self._connection_monitor.consecutive_failures} consecutive connection failures")
        
        price_info = self._current_price()
        if price_info is None:
            if self._tick_counter % 5 == 0:
                print("[dex_batch_swap] Network issue; waiting to reconnect...")
            return
        
        price, method = price_info
        
        # Try to execute each level independently - failure of one doesn't stop others
        for i, (lvl, amt, done) in enumerate(zip(self.levels, self.remaining, self.done)):
            if done or amt <= 0:
                continue
            if self._should_execute(price, lvl):
                try:
                    self._execute_level(i, amt, price)
                except Exception as e:
                    # Log error but continue with other levels
                    print(f"[dex_batch_swap] Error executing level {i}: {e}")
                    print(f"[dex_batch_swap] Strategy continues with remaining levels...")

        # Periodic status logging (every 10 ticks to reduce spam)
        if self._tick_counter % 10 == 0:
            remaining_levels = sum(1 for d in self.done if not d)
            
            # Find next level to execute
            spend_is_base = self.cfg.spend_is_base if self.cfg.spend_is_base is not None else self.cfg.amount_is_base
            next_level = None
            next_level_num = None
            for i, (lvl, done) in enumerate(zip(self.levels, self.done)):
                if not done:
                    if spend_is_base:
                        if price < lvl:  # Need price to go up
                            next_level = lvl
                            next_level_num = i + 1
                            break
                    else:
                        if price > lvl:  # Need price to go down
                            next_level = lvl
                            next_level_num = i + 1
                            break
            
            timestamp = format_timestamp(self._start_time)
            if next_level:
                distance = ((price - next_level) / next_level * 100) if spend_is_base else ((next_level - price) / price * 100)
                direction = "up" if spend_is_base else "down"
                print(f"{timestamp} [dex_batch_swap] Current price: {price:.8f} | Next level #{next_level_num}: {next_level:.8f} ({abs(distance):.2f}% {direction}) | Remaining: {remaining_levels}/{len(self.levels)} | {self._balances_summary()}")
            else:
                print(f"{timestamp} [dex_batch_swap] Current price: {price:.8f} | All pending levels triggered | Remaining: {remaining_levels}/{len(self.levels)} | {self._balances_summary()}")

        if all(self.done):
            self.stop()

    def _on_error(self, e: Exception) -> None:
        """Error handler - logs error but allows strategy to continue."""
        print(f"[dex_batch_swap] ⚠ Error in strategy loop: {e}")
        print(f"[dex_batch_swap] Strategy will continue running...")
        self._connection_monitor.record_failure(e)

    def start(self) -> None:
        """Start strategy with initial balance snapshots."""
        self._start_time = time.time()
        print("[dex_batch_swap] Starting strategy...")
        
        # Update order managers with start time
        for order_mgr in self.order_managers:
            order_mgr.strategy_start_time = self._start_time
        
        # Take initial snapshots
        for i, reporter in enumerate(self.reporters):
            try:
                reporter.take_snapshot(self.connectors[i], force=True)
            except Exception as e:
                print(f"[dex_batch_swap] Warning: Could not take initial snapshot for wallet {i+1}: {e}")
        
        print(f"[dex_batch_swap] Monitoring {len(self.connectors)} wallet(s)")
        print(f"[dex_batch_swap] Total amount: {self.cfg.total_amount} ({self.cfg.base_symbol if self.cfg.amount_is_base else self.cfg.quote_symbol})")
        print(f"[dex_batch_swap] Strategy will continue running even if network errors occur")
        
        # Show price levels for user reference
        spend_is_base = self.cfg.spend_is_base if self.cfg.spend_is_base is not None else self.cfg.amount_is_base
        side_str = "SELL" if spend_is_base else "BUY"
        print(f"\n[dex_batch_swap] === Price Levels ({side_str} {self.cfg.base_symbol}) ===")
        for i, lvl in enumerate(self.levels, 1):
            print(f"[dex_batch_swap]   Level {i:2d}: {lvl:.8f} {self.cfg.base_symbol}/{self.cfg.quote_symbol}")
        print(f"[dex_batch_swap] Orders will execute when price {'reaches or exceeds' if spend_is_base else 'drops to or below'} each level\n")
        
        self._loop.start()

    def stop(self) -> None:
        """Stop strategy and print final reports."""
        if self._stopped:
            return
        
        self._stopped = True
        self._loop.stop()
        
        print("\n[dex_batch_swap] Stopping strategy...")
        
        # Wait briefly for any pending transactions to be confirmed
        import time
        time.sleep(1)
        
        # Print final snapshots and P&L reports
        for i, reporter in enumerate(self.reporters):
            try:
                reporter.take_snapshot(self.connectors[i], force=True)
                reporter.print_final_report()
            except Exception as e:
                print(f"[dex_batch_swap] Error generating report for wallet {i+1}: {e}")
        
        # Print aggregate report
        try:
            self.aggregate_reporter.print_aggregate_report()
        except Exception as e:
            print(f"[dex_batch_swap] Error generating aggregate report: {e}")
        
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
        print(f"\n[dex_batch_swap] === Connection Statistics ===")
        print(f"[dex_batch_swap] Total Attempts: {stats['total_attempts']}")
        print(f"[dex_batch_swap] Successful: {stats['successful']}")
        print(f"[dex_batch_swap] Failed: {stats['failed']}")
        print(f"[dex_batch_swap] Success Rate: {stats['success_rate']:.1f}%\n")


