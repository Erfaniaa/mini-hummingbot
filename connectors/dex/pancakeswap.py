from __future__ import annotations

from typing import Optional

from web3.exceptions import ContractLogicError

from core.token_registry import TokenRegistry
from connectors.base import ExchangeConnector
from pancakeswap_client import PancakeSwapClient


class PancakeSwapConnector(ExchangeConnector):
    """
    Thin wrapper over PancakeSwapClient to expose a strategy-friendly API.

    Price convention: returns quote per 1 base, computed using a small probe amount.
    """

    def __init__(
        self,
        rpc_url: str,
        private_key: str,
        chain_id: int = 56,
        network: str = "mainnet",
        default_fee_tier: int = 2500,
    ) -> None:
        self.registry = TokenRegistry("testnet" if chain_id == 97 else network)
        self.client = PancakeSwapClient(rpc_url=rpc_url, private_key=private_key, chain_id=chain_id)
        self.chain_id = chain_id
        self.default_fee_tier = default_fee_tier

    def _resolve(self, symbol: str) -> str:
        return self.registry.get(symbol).address

    def get_price(self, base_symbol: str, quote_symbol: str) -> float:
        base = self._resolve(base_symbol)
        quote = self._resolve(quote_symbol)
        one_base = 10 ** self.client.get_decimals(base)
        fee_candidates = [self.default_fee_tier, 500, 2500, 10000]
        for fee in fee_candidates:
            try:
                q = self.client.quote_v3_exact_input_single(base, quote, fee, one_base, slippage_bps=0)
                if q.amount_out > 0:
                    # amount_out is quote received for 1 base
                    return self.client.from_wei(quote, q.amount_out)
            except ContractLogicError:
                continue
        # Try multi-hop via WBNB
        wbnb = self.client.DEFAULTS[self.chain_id]["WBNB"]
        for fees in ([500, 500], [500, 2500], [2500, 500], [2500, 2500], [10000, 500], [500, 10000]):
            try:
                q = self.client.quote_v3_exact_input_path([base, wbnb, quote], list(fees), one_base, slippage_bps=0)
                if q.amount_out > 0:
                    return self.client.from_wei(quote, q.amount_out)
            except ContractLogicError:
                continue
        raise RuntimeError(f"No route available for {base_symbol}/{quote_symbol}")

    def get_balance(self, symbol: str) -> float:
        token = self._resolve(symbol)
        bal_wei = self.client.get_balance(token)
        return self.client.from_wei(token, bal_wei)

    def approve(self, symbol: str, amount: float) -> str:
        token = self._resolve(symbol)
        amount_wei = self.client.to_wei(token, amount)
        return self.client.approve(token, int(amount_wei))

    def approve_unlimited(self, symbol: str) -> str:
        token = self._resolve(symbol)
        max_uint = (1 << 256) - 1
        return self.client.approve(token, max_uint)

    def get_allowance(self, symbol: str) -> int:
        token = self._resolve(symbol)
        return int(self.client.get_allowance(token))

    def market_swap(self, base_symbol: str, quote_symbol: str, amount: float, amount_is_base: bool, slippage_bps: int = 50) -> str:
        base = self._resolve(base_symbol)
        quote = self._resolve(quote_symbol)
        # If amount_is_base: we spend base to get quote. Otherwise we spend quote to get base.
        token_in = base if amount_is_base else quote
        token_out = quote if amount_is_base else base
        amount_in_wei = self.client.to_wei(token_in, amount)

        # Ensure sufficient balance pre-check to avoid revert
        bal_wei = self.client.get_balance(token_in)
        if bal_wei < amount_in_wei:
            raise RuntimeError("Insufficient token balance for swap")
        # Ensure allowance
        allowance = self.client.get_allowance(token_in)
        if int(allowance) < int(amount_in_wei):
            self.client.approve(token_in, int(amount_in_wei))

        # Try direct pool first; fall back via WBNB
        fee_candidates = [self.default_fee_tier, 500, 2500, 10000]
        try:
            for fee in fee_candidates:
                try:
                    return self.client.swap_v3_exact_input_single(token_in, token_out, fee, int(amount_in_wei), slippage_bps=slippage_bps)
                except ContractLogicError:
                    continue
            wbnb = self.client.DEFAULTS[self.chain_id]["WBNB"]
            for fees in ([500, 500], [500, 2500], [2500, 500], [2500, 2500], [10000, 500], [500, 10000]):
                try:
                    return self.client.swap_v3_exact_input_path([token_in, wbnb, token_out], list(fees), int(amount_in_wei), slippage_bps=slippage_bps)
                except ContractLogicError:
                    continue
        except Exception as e:
            raise RuntimeError(f"Swap failed: {e}")
        raise RuntimeError("No available route for swap")

    def tx_explorer_url(self, tx_hash: str) -> str:
        base = "https://bscscan.com/tx/" if self.chain_id == 56 else "https://testnet.bscscan.com/tx/"
        return f"{base}{tx_hash}"


