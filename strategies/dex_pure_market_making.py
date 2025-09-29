from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from connectors.dex.pancakeswap import PancakeSwapConnector
from strategies.engine import StrategyLoop, StrategyLoopConfig


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
        self._loop = StrategyLoop(StrategyLoopConfig(
            interval_seconds=cfg.tick_interval_seconds,
            on_tick=self._on_tick,
            on_error=self._on_error,
        ))

    def _price(self) -> float | None:
        try:
            return self.connectors[0].get_price(self.cfg.base_symbol, self.cfg.quote_symbol)
        except Exception:
            return None

    def _rebuild_levels(self, mid: float) -> None:
        # Compute geometric steps by percentage around mid price
        up = []
        dn = []
        for i in range(1, self.cfg.levels_each_side + 1):
            up.append(mid * (1.0 + self.cfg.upper_percent / 100.0 * i))
            dn.append(mid * (1.0 - self.cfg.lower_percent / 100.0 * i))
        self.upper_levels = up
        self.lower_levels = dn

    def _execute(self, amount: float, amount_is_base: bool) -> bool:
        ok_all = True
        for c in self.connectors:
            try:
                tx = c.market_swap(
                    base_symbol=self.cfg.base_symbol,
                    quote_symbol=self.cfg.quote_symbol,
                    amount=amount,
                    amount_is_base=amount_is_base,
                    slippage_bps=self.cfg.slippage_bps,
                )
                print("tx:", tx, "explorer:", c.tx_explorer_url(tx))
            except Exception:
                ok_all = False
        return ok_all

    def _on_tick(self) -> None:
        import time
        now = time.time()
        px = self._price()
        if px is None:
            return
        # Refresh levels periodically
        if now - self._last_refresh_ts >= float(self.cfg.refresh_seconds) or not (self.upper_levels and self.lower_levels):
            self._rebuild_levels(px)
            self._last_refresh_ts = now

        # Decide side and execute when crosses levels
        # If price above an upper level, sell base for quote (amount_is_base=True)
        # If price below a lower level, buy base with quote (amount_is_base=False)
        fired = False
        for lvl in sorted(self.upper_levels):
            if px >= lvl:
                if self._execute(self.cfg.order_amount, True if self.cfg.amount_is_base else True):
                    fired = True
                break
        if not fired:
            for lvl in sorted(self.lower_levels, reverse=True):
                if px <= lvl:
                    if self._execute(self.cfg.order_amount, False if self.cfg.amount_is_base else False):
                        fired = True
                    break
        if int(now) % 1 == 0:
            try:
                b = self.connectors[0].get_balance(self.cfg.base_symbol)
                q = self.connectors[0].get_balance(self.cfg.quote_symbol)
                print(f"[dex_pure_mm] px={px:.8f} fired={fired} bal[{self.cfg.base_symbol}={b:.6f},{self.cfg.quote_symbol}={q:.6f}]")
            except Exception:
                print(f"[dex_pure_mm] px={px:.8f} fired={fired}")

    def _on_error(self, e: Exception) -> None:
        print(f"[dex_pure_mm] Error: {e}")

    def start(self) -> None:
        self._loop.start()

    def stop(self) -> None:
        self._loop.stop()


