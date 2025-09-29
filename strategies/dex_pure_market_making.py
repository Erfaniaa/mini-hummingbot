from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from connectors.dex.pancakeswap import PancakeSwapConnector
from strategies.engine import StrategyLoop, StrategyLoopConfig
from strategies.utils import compute_spend_amount, is_exact_output_case
from strategies.order_manager import OrderManager
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

    def _execute(self, spend_amount: float, amount_is_base: bool) -> bool:
        # Quantize to spend token decimals
        spend_symbol = self.cfg.base_symbol if amount_is_base else self.cfg.quote_symbol
        amount_q = self._quantize(spend_symbol, spend_amount)
        if amount_q <= 0:
            return False
        ok_all = True
        for c in self.connectors:
            try:
                tx = c.market_swap(
                    base_symbol=self.cfg.base_symbol,
                    quote_symbol=self.cfg.quote_symbol,
                    amount=amount_q,
                    amount_is_base=amount_is_base,
                    slippage_bps=self.cfg.slippage_bps,
                    side=("sell" if amount_is_base else "buy"),
                )
                print(f"[dex_pmm] Transaction: {c.tx_explorer_url(tx)}")
            except Exception:
                ok_all = False
        return ok_all

    def _on_tick(self) -> None:
        """Tick handler with resilience and periodic reporting."""
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

        basis_is_base = self.cfg.amount_basis_is_base if self.cfg.amount_basis_is_base is not None else self.cfg.amount_is_base
        # Decide side and execute when crosses levels
        fired = False
        for lvl in sorted(self.upper_levels):
            if px >= lvl:
                # upper: sell base
                if is_exact_output_case(basis_is_base, True):
                    try:
                        ok = True
                        for c in self.connectors:
                            tx = c.swap_exact_out(self.cfg.base_symbol, self.cfg.quote_symbol, target_out_amount=self.cfg.order_amount, slippage_bps=self.cfg.slippage_bps)
                            print(f"[dex_pmm] Transaction: {c.tx_explorer_url(tx)}")
                        fired = ok
                    except Exception:
                        pass
                else:
                    spend_amount = compute_spend_amount(px, self.cfg.order_amount, basis_is_base, True)
                    if self._execute(spend_amount, True):
                        fired = True
                break
        if not fired:
            for lvl in sorted(self.lower_levels, reverse=True):
                if px <= lvl:
                    # lower: buy base
                    if is_exact_output_case(basis_is_base, False):
                        try:
                            ok = True
                            for c in self.connectors:
                                tx = c.swap_exact_out(self.cfg.quote_symbol, self.cfg.base_symbol, target_out_amount=self.cfg.order_amount, slippage_bps=self.cfg.slippage_bps)
                                print(f"[dex_pmm] Transaction: {c.tx_explorer_url(tx)}")
                            fired = ok
                        except Exception:
                            pass
                    else:
                        spend_q = compute_spend_amount(px, self.cfg.order_amount, basis_is_base, False)
                        if self._execute(spend_q, False):
                            fired = True
                    break
        if int(now) % 1 == 0:
            try:
                b = self.connectors[0].get_balance(self.cfg.base_symbol)
                q = self.connectors[0].get_balance(self.cfg.quote_symbol)
                print(f"[dex_pure_mm] fetched via {method}(base={self.cfg.base_symbol}, quote={self.cfg.quote_symbol}); price({self.cfg.base_symbol}/{self.cfg.quote_symbol})={px:.8f} fired={fired} balance[{self.cfg.base_symbol}={b:.6f},{self.cfg.quote_symbol}={q:.6f}]")
            except Exception:
                print(f"[dex_pure_mm] fetched via {method}(base={self.cfg.base_symbol}, quote={self.cfg.quote_symbol}); price({self.cfg.base_symbol}/{self.cfg.quote_symbol})={px:.8f} fired={fired}")

    def _on_error(self, e: Exception) -> None:
        """Error handler - logs error but allows strategy to continue."""
        print(f"[dex_pmm] ⚠ Error in strategy loop: {e}")
        print(f"[dex_pmm] Strategy will continue running...")
        self._connection_monitor.record_failure(e)

    def start(self) -> None:
        """Start strategy with initial balance snapshots."""
        print("[dex_pmm] Starting strategy...")
        
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
        print("\n[dex_pmm] Stopping strategy...")
        
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
        
        self._loop.stop()


