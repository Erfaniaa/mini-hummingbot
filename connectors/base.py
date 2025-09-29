from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class ExchangeConnector(ABC):
    """
    Abstract connector API for exchanges.

    We separate DEX and CEX connectors under this abstraction so that
    strategies can be implemented once against this interface.
    """

    @abstractmethod
    def get_price(self, base_symbol: str, quote_symbol: str) -> float:
        """
        Return price as quote per one base. Must clarify direction in implementations.
        """

    @abstractmethod
    def get_balance(self, symbol: str) -> float:
        """Return token balance in human-readable units (decimal)."""

    @abstractmethod
    def approve(self, symbol: str, amount: float) -> str:
        """Approve router/spender to spend 'symbol'. Return tx hash."""

    @abstractmethod
    def market_swap(self, base_symbol: str, quote_symbol: str, amount: float, amount_is_base: bool, slippage_bps: int = 50) -> str:
        """
        Execute a market swap.

        - If amount_is_base is True: spend 'base' amount to receive quote
        - If amount_is_base is False: spend 'quote' amount to receive base
        Return transaction hash.
        """

    @abstractmethod
    def tx_explorer_url(self, tx_hash: str) -> str:
        """Return a block explorer URL for a transaction."""

    @abstractmethod
    def get_token_decimals(self, symbol: str) -> int:
        """Return the on-chain decimals for the given token symbol."""

    @abstractmethod
    def quantize_amount(self, symbol: str, amount: float) -> float:
        """
        Return amount rounded down to the token's decimal precision.
        Implementations should avoid rounding up to prevent overspending.
        """


