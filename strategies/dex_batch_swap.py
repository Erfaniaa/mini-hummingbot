from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from connectors.dex.pancakeswap import PancakeSwapConnector
from strategies.engine import StrategyLoop, StrategyLoopConfig
from strategies.utils import compute_spend_amount, is_exact_output_case


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
        self._loop = StrategyLoop(StrategyLoopConfig(
            interval_seconds=cfg.interval_seconds,
            on_tick=self._on_tick,
            on_error=self._on_error,
        ))

    def _current_price(self) -> Optional[Tuple[float, str]]:
        try:
            px = self.connectors[0].get_price_fast(self.cfg.base_symbol, self.cfg.quote_symbol)
            return px, "get_price_fast"
        except Exception:
            try:
                px = self.connectors[0].get_price(self.cfg.base_symbol, self.cfg.quote_symbol)
                return px, "get_price"
            except Exception:
                return None

    def _should_execute(self, price: float, level: float) -> bool:
        if self.cfg.amount_is_base:
            return price >= level
        else:
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
        basis_is_base = self.cfg.amount_basis_is_base if self.cfg.amount_basis_is_base is not None else self.cfg.amount_is_base
        spend_is_base = self.cfg.spend_is_base if self.cfg.spend_is_base is not None else self.cfg.amount_is_base
        # exact-output if user amount represents output side
        if is_exact_output_case(basis_is_base, spend_is_base):
            target_out_symbol = self.cfg.quote_symbol if spend_is_base else self.cfg.base_symbol
            for conn in self.connectors:
                try:
                    if spend_is_base:
                        tx = conn.swap_exact_out(self.cfg.base_symbol, self.cfg.quote_symbol, target_out_amount=amount_user_basis, slippage_bps=self.cfg.slippage_bps)
                    else:
                        tx = conn.swap_exact_out(self.cfg.quote_symbol, self.cfg.base_symbol, target_out_amount=amount_user_basis, slippage_bps=self.cfg.slippage_bps)
                    print("tx:", tx, "explorer:", conn.tx_explorer_url(tx))
                except Exception:
                    return
            self.done[li] = True
            self.remaining[li] = 0.0
            return
        # Else compute spend amount normally
        spend_symbol = self.cfg.base_symbol if spend_is_base else self.cfg.quote_symbol
        spend_amt = compute_spend_amount(price, amount_user_basis, basis_is_base, spend_is_base)
        amount_q = self._quantize(spend_symbol, spend_amt)
        if amount_q <= 0:
            self.done[li] = True
            self.remaining[li] = 0.0
            return
        for conn in self.connectors:
            try:
                tx = conn.market_swap(
                    base_symbol=self.cfg.base_symbol,
                    quote_symbol=self.cfg.quote_symbol,
                    amount=amount_q,
                    amount_is_base=spend_is_base,
                    slippage_bps=self.cfg.slippage_bps,
                    side=("sell" if spend_is_base else "buy"),
                )
                print("tx:", tx, "explorer:", conn.tx_explorer_url(tx))
            except Exception:
                return
        self.done[li] = True
        self.remaining[li] = 0.0

    def _balances_summary(self) -> str:
        try:
            b = self.connectors[0].get_balance(self.cfg.base_symbol)
            q = self.connectors[0].get_balance(self.cfg.quote_symbol)
            return f"bal[{self.cfg.base_symbol}={b:.6f}, {self.cfg.quote_symbol}={q:.6f}]"
        except Exception:
            return "bal[unavailable]"

    def _on_tick(self) -> None:
        self._tick_counter += 1
        price_info = self._current_price()
        if price_info is None:
            if self._tick_counter % 5 == 0:
                print("[dex_batch_swap] Network issue; waiting to reconnect...")
            return
        price, method = price_info
        for i, (lvl, amt, done) in enumerate(zip(self.levels, self.remaining, self.done)):
            if done or amt <= 0:
                continue
            if self._should_execute(price, lvl):
                self._execute_level(i, amt, price)

        remaining_levels = sum(1 for d in self.done if not d)
        if self._tick_counter % 1 == 0:
            print(f"[dex_batch_swap] fetched via {method}(base={self.cfg.base_symbol}, quote={self.cfg.quote_symbol}); price({self.cfg.base_symbol}/{self.cfg.quote_symbol})={price:.8f} levels_left={remaining_levels} {self._balances_summary()}")

        if all(self.done):
            self.stop()

    def _on_error(self, e: Exception) -> None:
        print(f"[dex_batch_swap] Error: {e}")

    def start(self) -> None:
        self._loop.start()

    def stop(self) -> None:
        self._loop.stop()


