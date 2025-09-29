from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from decimal import Decimal

from connectors.dex.pancakeswap import PancakeSwapConnector
from strategies.utils import compute_spend_amount, is_exact_output_case


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
    # Optional label for logging (e.g., wallet name)
    label: Optional[str] = None


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

    def _prefix(self) -> str:
        return f"[{self.cfg.label}] " if self.cfg.label else ""

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
        side = "sell" if spend_is_base else "buy"

        # Determine spend symbol
        spend_symbol = base if spend_is_base else quote

        # If user amount is on the output side, prefer exact-output swap to guarantee target receive amount
        if is_exact_output_case(basis_is_base, spend_is_base):
            target_out_symbol = quote if spend_is_base else base
            spend_symbol = base if spend_is_base else quote
            # Best-effort balance pre-check using estimator (padded by slippage for safety)
            try:
                est_in = float(self.connector.estimate_in_for_exact_out(
                    token_in_symbol=spend_symbol,
                    token_out_symbol=target_out_symbol,
                    amount_out_human=amount,
                ))
            except Exception:
                est_in = 0.0
            if est_in > 0:
                pad = (10_000 + int(self.cfg.slippage_bps) + 50) / 10_000.0
                est_in_padded = est_in * pad
                bal_check_amt = self._quantize(spend_symbol, est_in_padded)
                bal_avail = self.connector.get_balance(spend_symbol)
                if bal_avail < bal_check_amt:
                    raise RuntimeError(f"{self._prefix()}Insufficient balance: {spend_symbol} balance {bal_avail} < {bal_check_amt}")
            print(f"{self._prefix()}[swap] exact-out: target {amount} {target_out_symbol}, side={side}")
            try:
                tx_hash = self.connector.swap_exact_out(
                    token_in_symbol=spend_symbol,
                    token_out_symbol=target_out_symbol,
                    target_out_amount=float(amount),
                    slippage_bps=int(self.cfg.slippage_bps),
                )
                url = self.connector.tx_explorer_url(tx_hash)
                print(f"{self._prefix()}submitted: {url}")
                return tx_hash
            except Exception as e:
                print(f"{self._prefix()}[swap] exact-out failed ({e}); falling back to market swap with computed spend amount...")
                # Fallback to market swap by computing spend amount
                try:
                    est_spend = self.connector.estimate_in_for_exact_out(
                        token_in_symbol=spend_symbol,
                        token_out_symbol=target_out_symbol,
                        amount_out_human=amount,
                    )
                except Exception:
                    est_spend = 0.0
                if est_spend and est_spend > 0:
                    spend_amt = float(est_spend)
                    price_qpb = None
                else:
                    try:
                        print(f"{self._prefix()}[swap] fetching price via get_price_side(base={base}, quote={quote}, side={side}, fast=True)...")
                        price_qpb = self.connector.get_price_side(base, quote, side=side, fast=True)
                        print(f"{self._prefix()}[swap] fetched price ({base}/{quote})={price_qpb}")
                    except Exception:
                        print(f"{self._prefix()}[swap] fast price failed; fetching via get_price_side(base={base}, quote={quote}, side={side}, fast=False)...")
                        price_qpb = self.connector.get_price_side(base, quote, side=side, fast=False)
                        print(f"{self._prefix()}[swap] fetched price ({base}/{quote})={price_qpb}")
                    if not price_qpb or price_qpb <= 0:
                        raise RuntimeError(f"{self._prefix()}Swap failed: cannot compute spend amount after exact-out failure")
                    spend_amt = compute_spend_amount(price_qpb, amount, basis_is_base, spend_is_base)
                amount_q = self._quantize(spend_symbol, spend_amt)
                bal = self.connector.get_balance(spend_symbol)
                if bal < amount_q:
                    raise RuntimeError(f"{self._prefix()}Insufficient balance: {spend_symbol} balance {bal} < {amount_q}")
                print(f"{self._prefix()}[swap] spending {amount_q} {'BASE' if spend_is_base else 'QUOTE'} token ({spend_symbol}), side={side}")
                try:
                    tx_hash = self.connector.market_swap(
                        base_symbol=base,
                        quote_symbol=quote,
                        amount=amount_q,
                        amount_is_base=spend_is_base,
                        slippage_bps=self.cfg.slippage_bps,
                        side=side,
                    )
                    url = self.connector.tx_explorer_url(tx_hash)
                    print(f"{self._prefix()}submitted: {url}")
                    return tx_hash
                except Exception as e2:
                    raise RuntimeError(f"{self._prefix()}Swap failed after fallback: {e2}")
        # Otherwise, compute spend amount using side-aware price (approx-output with slippage guard)
        if basis_is_base == spend_is_base:
            spend_amt = amount
            price_qpb = None
        else:
            # Try estimating spend via exact-out quoter first
            try:
                est_spend = self.connector.estimate_in_for_exact_out(
                    token_in_symbol=base if spend_is_base else quote,
                    token_out_symbol=quote if spend_is_base else base,
                    amount_out_human=amount,
                )
            except Exception:
                est_spend = 0.0
            if est_spend and est_spend > 0:
                spend_amt = float(est_spend)
                price_qpb = None
            else:
                try:
                    print(f"{self._prefix()}[swap] fetching price via get_price_side(base={base}, quote={quote}, side={side}, fast=True)...")
                    price_qpb = self.connector.get_price_side(base, quote, side=side, fast=True)
                    print(f"{self._prefix()}[swap] fetched price ({base}/{quote})={price_qpb}")
                except Exception:
                    print(f"{self._prefix()}[swap] fast price failed; fetching via get_price_side(base={base}, quote={quote}, side={side}, fast=False)...")
                    price_qpb = self.connector.get_price_side(base, quote, side=side, fast=False)
                    print(f"{self._prefix()}[swap] fetched price ({base}/{quote})={price_qpb}")
                if price_qpb <= 0:
                    raise RuntimeError("Failed to fetch price")
                spend_amt = compute_spend_amount(price_qpb, amount, basis_is_base, spend_is_base)

        # Quantize to token decimals before checks and execution
        amount_q = self._quantize(spend_symbol, spend_amt)

        # Check balances
        bal = self.connector.get_balance(spend_symbol)
        if bal < amount_q:
            raise RuntimeError(f"{self._prefix()}Insufficient balance: {spend_symbol} balance {bal} < {amount_q}")

        # Approve and swap (connector expects amount in spend token units)
        print(f"{self._prefix()}[swap] spending {amount_q} {'BASE' if spend_is_base else 'QUOTE'} token ({spend_symbol}), side={side}")
        try:
            tx_hash = self.connector.market_swap(
                base_symbol=base,
                quote_symbol=quote,
                amount=amount_q,
                amount_is_base=spend_is_base,
                slippage_bps=self.cfg.slippage_bps,
                side=side,
            )
            url = self.connector.tx_explorer_url(tx_hash)
            print(f"{self._prefix()}submitted: {url}")
        except Exception as e:
            raise RuntimeError(f"{self._prefix()}Swap failed: {e}")
        return tx_hash


