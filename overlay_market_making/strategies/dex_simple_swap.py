from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..connectors.dex.pancakeswap import PancakeSwapConnector


@dataclass
class DexSimpleSwapConfig:
    rpc_url: str
    private_key: str
    chain_id: int
    base_symbol: str
    quote_symbol: str
    amount: float
    amount_is_base: bool
    slippage_bps: int = 50


class DexSimpleSwap:
    """
    Executes a single market swap on PancakeSwap.
    - Validates balances and approvals
    - Performs the swap and returns tx hash
    """

    def __init__(self, cfg: DexSimpleSwapConfig) -> None:
        self.cfg = cfg
        self.connector = PancakeSwapConnector(
            rpc_url=cfg.rpc_url,
            private_key=cfg.private_key,
            chain_id=cfg.chain_id,
        )

    def run(self) -> str:
        base = self.cfg.base_symbol.upper()
        quote = self.cfg.quote_symbol.upper()
        amount = float(self.cfg.amount)
        if amount <= 0:
            raise ValueError("Amount must be positive")

        # Check balances
        spend_symbol = base if self.cfg.amount_is_base else quote
        bal = self.connector.get_balance(spend_symbol)
        if bal < amount:
            raise RuntimeError(f"Insufficient balance: {spend_symbol} balance {bal} < {amount}")

        # Approve and swap
        try:
            tx_hash = self.connector.market_swap(
                base_symbol=base,
                quote_symbol=quote,
                amount=amount,
                amount_is_base=self.cfg.amount_is_base,
                slippage_bps=self.cfg.slippage_bps,
            )
        except Exception as e:
            raise RuntimeError(f"Swap failed: {e}")
        return tx_hash


