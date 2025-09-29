from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from decimal import Decimal

from connectors.dex.pancakeswap import PancakeSwapConnector
from strategies.utils import compute_spend_amount


@dataclass
class DexSimpleSwapConfig:
    rpc_url: str
    private_key: str
    chain_id: int
    base_symbol: str
    quote_symbol: str
    amount: float
    amount_is_base: bool  # backward-compat; if new fields provided, this may differ
    slippage_bps: int = 50
    # New optional fields to decouple direction from basis
    spend_is_base: Optional[bool] = None
    amount_basis_is_base: Optional[bool] = None


class DexSimpleSwap:
    """
    Executes a single market swap on PancakeSwap.
    - Validates balances and approvals
    - Performs the swap and returns tx hash
    """

    def __init__(self, cfg: DexSimpleSwapConfig, connector: Optional[PancakeSwapConnector] = None) -> None:
        self.cfg = cfg
        self.connector = connector or PancakeSwapConnector(
            rpc_url=cfg.rpc_url,
            private_key=cfg.private_key,
            chain_id=cfg.chain_id,
        )

    def _quantize(self, symbol: str, amount: float) -> float:
        qf = getattr(self.connector, "quantize_amount", None)
        if callable(qf):
            try:
                return float(qf(symbol, amount))
            except Exception:
                return float(amount)
        return float(amount)

    def run(self) -> str:
        base = self.cfg.base_symbol.upper()
        quote = self.cfg.quote_symbol.upper()
        amount = float(self.cfg.amount)
        if amount <= 0:
            raise ValueError("Amount must be positive")

        # Determine basis and spend side (direction)
        basis_is_base = self.cfg.amount_basis_is_base if self.cfg.amount_basis_is_base is not None else self.cfg.amount_is_base
        spend_is_base = self.cfg.spend_is_base if self.cfg.spend_is_base is not None else self.cfg.amount_is_base

        # Determine spend symbol
        spend_symbol = base if spend_is_base else quote

        # Convert user-entered basis to spend token amount
        if basis_is_base == spend_is_base:
            spend_amt = amount
        else:
            # Need price to convert between base and quote basis
            try:
                price = self.connector.get_price(base, quote)  # quote per 1 base
            except Exception as e:
                raise RuntimeError("Failed to fetch price for basis conversion") from e
            if price <= 0:
                raise RuntimeError("Failed to fetch price")
            spend_amt = compute_spend_amount(
                price_quote_per_base=price,
                amount=amount,
                amount_basis_is_base=basis_is_base,
                spend_is_base=spend_is_base,
            )

        # Quantize to token decimals before checks and execution
        amount_q = self._quantize(spend_symbol, spend_amt)

        # Check balances
        bal = self.connector.get_balance(spend_symbol)
        if bal < amount_q:
            raise RuntimeError(f"Insufficient balance: {spend_symbol} balance {bal} < {amount_q}")

        # Approve and swap (connector expects amount in spend token units)
        try:
            tx_hash = self.connector.market_swap(
                base_symbol=base,
                quote_symbol=quote,
                amount=amount_q,
                amount_is_base=spend_is_base,
                slippage_bps=self.cfg.slippage_bps,
            )
            print("tx:", tx_hash)
            print("explorer:", self.connector.tx_explorer_url(tx_hash))
        except Exception as e:
            raise RuntimeError(f"Swap failed: {e}")
        return tx_hash


