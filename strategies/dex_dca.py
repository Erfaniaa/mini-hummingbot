from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import List, Optional

from connectors.dex.pancakeswap import PancakeSwapConnector
from strategies.engine import StrategyLoop, StrategyLoopConfig
from strategies.utils import compute_spend_amount, is_exact_output_case
from strategies.order_manager import OrderManager
from strategies.periodic_reporter import PeriodicReporter, AggregateReporter
from strategies.resilience import ConnectionMonitor, resilient_call, RetryConfig


@dataclass
class DexDCAConfig:
    rpc_url: str
    private_keys: List[str]
    chain_id: int
    base_symbol: str
    quote_symbol: str
    total_amount: float
    amount_is_base: bool  # backward compat; prefer amount_basis_is_base when set
    interval_seconds: float
    num_orders: int
    distribution: str  # "uniform" | "random_uniform"
    amount_basis_is_base: Optional[bool] = None
    spend_is_base: Optional[bool] = None
    slippage_bps: int = 50


class DexDCA:
    """
    Periodically executes market swaps to complete a total allocation over N orders.
    """

    def __init__(self, cfg: DexDCAConfig, connectors: Optional[List[PancakeSwapConnector]] = None) -> None:
        self.cfg = cfg
        self.connectors: List[PancakeSwapConnector] = connectors or [
            PancakeSwapConnector(rpc_url=cfg.rpc_url, private_key=pk, chain_id=cfg.chain_id)
            for pk in cfg.private_keys
        ]
        self.remaining = float(cfg.total_amount)
        self.orders_left = int(cfg.num_orders)
        self._stopped: bool = False
        
        # Initialize order managers and reporters per wallet
        self.order_managers: List[OrderManager] = []
        self.reporters: List[PeriodicReporter] = []
        
        for i, conn in enumerate(self.connectors):
            wallet_name = f"wallet_{i+1}"
            self.order_managers.append(OrderManager(wallet_name=wallet_name, strategy_name="dex_dca"))
            self.reporters.append(PeriodicReporter(
                wallet_name=wallet_name,
                strategy_name="dex_dca",
                base_symbol=cfg.base_symbol,
                quote_symbol=cfg.quote_symbol,
                report_interval=60.0
            ))
        
        # Aggregate reporter
        self.aggregate_reporter = AggregateReporter(
            strategy_name="dex_dca",
            base_symbol=cfg.base_symbol,
            quote_symbol=cfg.quote_symbol
        )
        for reporter in self.reporters:
            self.aggregate_reporter.add_reporter(reporter)
        
        # Connection monitoring
        self._connection_monitor = ConnectionMonitor("dex_dca")
        self._retry_config = RetryConfig(max_retries=5, initial_delay=2.0)
        
        self._loop = StrategyLoop(StrategyLoopConfig(
            interval_seconds=cfg.interval_seconds,
            on_tick=self._on_tick,
            on_error=self._on_error,
        ))

    def _pick_chunk(self) -> float:
        if self.orders_left <= 1:
            return max(0.0, self.remaining)
        if self.cfg.distribution == "random_uniform":
            mean = self.remaining / self.orders_left
            chunk = random.uniform(0.5 * mean, 1.5 * mean)
        else:
            chunk = self.remaining / self.orders_left
        chunk = min(chunk, self.remaining)
        return max(0.0, chunk)

    def _quantize(self, symbol: str, amount: float) -> float:
        qf = getattr(self.connectors[0], "quantize_amount", None)
        if callable(qf):
            try:
                return float(qf(symbol, amount))
            except Exception:
                return float(amount)
        return float(amount)

    def _execute_order(self, amount: float, price: float, order_num: int) -> bool:
        """Execute DCA order using OrderManager for proper tracking."""
        if self._stopped:
            return False
        
        basis_is_base = self.cfg.amount_basis_is_base if self.cfg.amount_basis_is_base is not None else self.cfg.amount_is_base
        spend_is_base = self.cfg.spend_is_base if self.cfg.spend_is_base is not None else self.cfg.amount_is_base
        side = "sell" if spend_is_base else "buy"
        
        all_success = True
        
        # Execute order for each wallet
        for wallet_idx, (conn, order_mgr) in enumerate(zip(self.connectors, self.order_managers)):
            # Create order
            order = order_mgr.create_order(
                base_symbol=self.cfg.base_symbol,
                quote_symbol=self.cfg.quote_symbol,
                side=side,
                amount=amount,
                price=price,
                reason=f"DCA order {order_num}/{self.cfg.num_orders}"
            )
            
            # Determine spend amount for validation
            spend_symbol = self.cfg.base_symbol if spend_is_base else self.cfg.quote_symbol
            if is_exact_output_case(basis_is_base, spend_is_base):
                # Estimate spend for validation (with buffer)
                spend_amt_estimate = compute_spend_amount(price, amount, basis_is_base, spend_is_base)
                spend_amt_estimate = self._quantize(spend_symbol, spend_amt_estimate * 1.1)
            else:
                spend_amt = compute_spend_amount(price, amount, basis_is_base, spend_is_base)
                spend_amt_estimate = self._quantize(spend_symbol, spend_amt)
            
            # Pre-order validation
            check = order_mgr.validate_order(conn, spend_symbol, spend_amt_estimate)
            if not check.passed:
                order_mgr.mark_failed(order, check.reason)
                print(f"[wallet_{wallet_idx+1}] [dex_dca] Skipping order {order_num}: {check.reason}")
                all_success = False
                continue
            
            # Submit order with retry
            def submit_swap():
                if is_exact_output_case(basis_is_base, spend_is_base):
                    if spend_is_base:
                        return conn.swap_exact_out(self.cfg.base_symbol, self.cfg.quote_symbol, target_out_amount=amount, slippage_bps=self.cfg.slippage_bps)
                    else:
                        return conn.swap_exact_out(self.cfg.quote_symbol, self.cfg.base_symbol, target_out_amount=amount, slippage_bps=self.cfg.slippage_bps)
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
            else:
                all_success = False
        
        return all_success

    def _on_tick(self) -> None:
        """Tick handler with resilience and periodic reporting."""
        if self._stopped:
            return
        
        # Periodic balance reporting
        for i, reporter in enumerate(self.reporters):
            try:
                reporter.take_snapshot(self.connectors[i])
            except Exception:
                pass
        
        # Check connection health
        if self._connection_monitor.should_warn():
            print(f"[dex_dca] ⚠ Warning: {self._connection_monitor.consecutive_failures} consecutive connection failures")
        
        if self.orders_left <= 0 or self.remaining <= 0.0:
            self.stop()
            return
        
        amount = self._pick_chunk()
        if amount <= 0.0:
            self.stop()
            return
        
        # Get price with resilience
        def get_fast_price():
            px = self.connectors[0].get_price_fast(self.cfg.base_symbol, self.cfg.quote_symbol)
            return px, "get_price_fast"
        
        def get_regular_price():
            px = self.connectors[0].get_price(self.cfg.base_symbol, self.cfg.quote_symbol)
            return px, "get_price"
        
        result = resilient_call(
            get_fast_price,
            retry_config=self._retry_config,
            on_retry=lambda attempt, error: print(f"[dex_dca] Price fetch attempt {attempt + 1} failed: {error}"),
            fallback=None
        )
        
        if result is None:
            result = resilient_call(
                get_regular_price,
                retry_config=self._retry_config,
                on_retry=lambda attempt, error: print(f"[dex_dca] Price fetch (fallback) attempt {attempt + 1} failed: {error}"),
                fallback=None
            )
        
        if result is None:
            self._connection_monitor.record_failure(Exception("Failed to fetch price"))
            print("[dex_dca] Network issue; waiting to reconnect...")
            return
        
        px, method = result
        self._connection_monitor.record_success()
        
        if not px or px <= 0:
            return
        
        # Execute DCA order
        current_order_num = self.cfg.num_orders - self.orders_left + 1
        ok = self._execute_order(amount, px, current_order_num)
        
        if ok:
            self.remaining = max(0.0, self.remaining - amount)
            self.orders_left -= 1
        
        # Log status with total balances across all wallets
        try:
            total_base = sum(conn.get_balance(self.cfg.base_symbol) for conn in self.connectors)
            total_quote = sum(conn.get_balance(self.cfg.quote_symbol) for conn in self.connectors)
            portfolio_value = total_quote + (total_base * px)
            print(f"[dex_dca] Price: {px:.8f} {self.cfg.base_symbol}/{self.cfg.quote_symbol} | Order {current_order_num}/{self.cfg.num_orders} executed={ok} | Remaining: {self.remaining:.6f} | Orders left: {self.orders_left} | Total balance (all wallets): {self.cfg.base_symbol}={total_base:.6f}, {self.cfg.quote_symbol}={total_quote:.2f} | Portfolio value: {portfolio_value:.2f} USDT")
        except Exception:
            print(f"[dex_dca] Price: {px:.8f} {self.cfg.base_symbol}/{self.cfg.quote_symbol} | Order {current_order_num}/{self.cfg.num_orders} executed={ok} | Remaining: {self.remaining:.6f} | Orders left: {self.orders_left}")

    def _on_error(self, e: Exception) -> None:
        """Error handler - logs error but allows strategy to continue."""
        print(f"[dex_dca] ⚠ Error in strategy loop: {e}")
        print(f"[dex_dca] Strategy will continue running...")
        self._connection_monitor.record_failure(e)

    def start(self) -> None:
        """Start strategy with initial balance snapshots."""
        print("[dex_dca] Starting strategy...")
        
        # Take initial snapshots
        for i, reporter in enumerate(self.reporters):
            try:
                reporter.take_snapshot(self.connectors[i], force=True)
            except Exception as e:
                print(f"[dex_dca] Warning: Could not take initial snapshot for wallet {i+1}: {e}")
        
        print(f"[dex_dca] Monitoring {len(self.connectors)} wallet(s)")
        print(f"[dex_dca] Total orders: {self.cfg.num_orders}")
        print(f"[dex_dca] Total amount: {self.cfg.total_amount} ({self.cfg.base_symbol if self.cfg.amount_is_base else self.cfg.quote_symbol})")
        print(f"[dex_dca] Interval: {self.cfg.interval_seconds}s")
        print(f"[dex_dca] Strategy will continue running even if network errors occur\n")
        
        self._loop.start()

    def stop(self) -> None:
        """Stop strategy and print final reports."""
        if self._stopped:
            return
        
        self._stopped = True
        self._loop.stop()
        
        print("\n[dex_dca] Stopping strategy...")
        
        # Print final snapshots and P&L reports
        for i, reporter in enumerate(self.reporters):
            try:
                reporter.take_snapshot(self.connectors[i], force=True)
                reporter.print_final_report()
            except Exception as e:
                print(f"[dex_dca] Error generating report for wallet {i+1}: {e}")
        
        # Print aggregate report
        try:
            self.aggregate_reporter.print_aggregate_report()
        except Exception as e:
            print(f"[dex_dca] Error generating aggregate report: {e}")
        
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
        print(f"\n[dex_dca] === Connection Statistics ===")
        print(f"[dex_dca] Total Attempts: {stats['total_attempts']}")
        print(f"[dex_dca] Successful: {stats['successful']}")
        print(f"[dex_dca] Failed: {stats['failed']}")
        print(f"[dex_dca] Success Rate: {stats['success_rate']:.1f}%\n")


