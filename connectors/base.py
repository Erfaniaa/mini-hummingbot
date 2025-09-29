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
    def market_swap(self, base_symbol: str, quote_symbol: str, amount: float, amount_is_base: bool, slippage_bps: int = 50, side: Optional[str] = None) -> str:
        """
        Execute a market swap.

        Direction can be specified either via amount_is_base or explicitly via side.
        - side == "sell": spend base to receive quote (amount is in base units)
        - side == "buy":  spend quote to receive base (amount is in quote units)
        If side is None, amount_is_base determines direction:
        - amount_is_base True  => sell
        - amount_is_base False => buy
        Implementations should prefer 'side' when provided.
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


