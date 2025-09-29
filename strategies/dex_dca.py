from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import List, Optional

from connectors.dex.pancakeswap import PancakeSwapConnector
from strategies.engine import StrategyLoop, StrategyLoopConfig
from strategies.utils import compute_spend_amount


@dataclass
class DexDCAConfig:
    rpc_url: str
    private_keys: List[str]
    chain_id: int
    base_symbol: str
    quote_symbol: str
    total_amount: float
    amount_is_base: bool
    interval_seconds: float
    num_orders: int
    distribution: str  # "uniform" | "random_uniform"
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

    def _execute(self, spend_amount: float) -> bool:
        # Quantize by spend token decimals
        spend_symbol = self.cfg.base_symbol if self.cfg.amount_is_base else self.cfg.quote_symbol
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
                    amount_is_base=self.cfg.amount_is_base,
                    slippage_bps=self.cfg.slippage_bps,
                )
                print("tx:", tx, "explorer:", c.tx_explorer_url(tx))
            except Exception:
                ok_all = False
        return ok_all

    def _on_tick(self) -> None:
        if self.orders_left <= 0 or self.remaining <= 0.0:
            self.stop()
            return
        amount = self._pick_chunk()
        if amount <= 0.0:
            self.stop()
            return
        # Convert user basis chunk to spend token using current price (fast first)
        try:
            px = self.connectors[0].get_price_fast(self.cfg.base_symbol, self.cfg.quote_symbol)
        except Exception:
            try:
                px = self.connectors[0].get_price(self.cfg.base_symbol, self.cfg.quote_symbol)
            except Exception:
                px = None
        if not px or px <= 0:
            return
        spend_amt = compute_spend_amount(px, amount, self.cfg.amount_is_base, self.cfg.amount_is_base)
        ok = self._execute(spend_amt)
        if ok:
            self.remaining = max(0.0, self.remaining - amount)
            self.orders_left -= 1
        try:
            b = self.connectors[0].get_balance(self.cfg.base_symbol)
            q = self.connectors[0].get_balance(self.cfg.quote_symbol)
            print(f"[dex_dca] price({self.cfg.quote_symbol}/{self.cfg.base_symbol})={px:.8f} executed={ok} chunk={spend_amt:.6f} remaining={self.remaining:.6f} orders_left={self.orders_left} bal[{self.cfg.base_symbol}={b:.6f},{self.cfg.quote_symbol}={q:.6f}]")
        except Exception:
            print(f"[dex_dca] price({self.cfg.quote_symbol}/{self.cfg.base_symbol})={px:.8f} executed={ok} chunk={spend_amt:.6f} remaining={self.remaining:.6f} orders_left={self.orders_left}")

    def _on_error(self, e: Exception) -> None:
        print(f"[dex_dca] Error: {e}")

    def start(self) -> None:
        self._loop.start()

    def stop(self) -> None:
        self._loop.stop()


