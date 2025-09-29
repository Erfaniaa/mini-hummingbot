from __future__ import annotations

from typing import Optional


def compute_spend_amount(
    price_quote_per_base: float,
    amount: float,
    amount_basis_is_base: bool,
    spend_is_base: bool,
) -> float:
    """Convert a user-entered amount (in base or quote units) to the spend token amount.

    price_quote_per_base: price as quote per 1 base (from connector.get_price)
    amount: user-entered amount
    amount_basis_is_base: True if amount is in base units; False if in quote units
    spend_is_base: True if we will spend base token; False if we will spend quote token

    Returns: spend token amount (float)
    """
    if price_quote_per_base <= 0:
        return 0.0
    if spend_is_base:
        # spending base
        if amount_basis_is_base:
            return amount
        # amount given in quote, convert to base
        return amount / float(price_quote_per_base)
    else:
        # spending quote
        if amount_basis_is_base:
            # amount given in base, convert to quote
            return amount * float(price_quote_per_base)
        return amount


def compute_quote_value(price_quote_per_base: float, spend_amount: float, spend_is_base: bool) -> float:
    """Compute notional quote value for the swap based on spend.

    - If spending base: value_in_quote = spend_amount * price
    - If spending quote: value_in_quote = spend_amount
    """
    if price_quote_per_base <= 0:
        return 0.0
    return spend_amount * float(price_quote_per_base) if spend_is_base else spend_amount
