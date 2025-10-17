"""
Tests to verify price calculations and inversions are handled correctly.

Tests focus on ensuring that:
1. Price inversions (quote/base vs base/quote) are handled correctly
2. Side logic (buy vs sell) maps correctly to token spending
3. Comparison operators match the intended strategy behavior
"""
import pytest
from strategies.utils import compute_spend_amount, is_exact_output_case


def test_compute_spend_amount_sell_base_basis_base():
    """Sell BASE: amount is in BASE, price is quote/base."""
    price = 2.0  # 2 QUOTE per 1 BASE
    amount = 10.0  # 10 BASE
    
    # Selling BASE (spend_is_base=True), amount in BASE (amount_basis_is_base=True)
    result = compute_spend_amount(
        price_quote_per_base=price,
        amount=amount,
        amount_basis_is_base=True,
        spend_is_base=True
    )
    
    # Should return amount as-is (we're spending the base amount directly)
    assert result == 10.0


def test_compute_spend_amount_sell_base_basis_quote():
    """Sell BASE to get exact QUOTE: amount is target QUOTE, price is quote/base."""
    price = 2.0  # 2 QUOTE per 1 BASE
    amount = 20.0  # Want 20 QUOTE
    
    # Selling BASE (spend_is_base=True), amount in QUOTE (amount_basis_is_base=False)
    result = compute_spend_amount(
        price_quote_per_base=price,
        amount=amount,
        amount_basis_is_base=False,
        spend_is_base=True
    )
    
    # To get 20 QUOTE, need to sell 20/2 = 10 BASE
    assert result == 10.0


def test_compute_spend_amount_buy_base_basis_base():
    """Buy BASE: amount is target BASE, price is quote/base."""
    price = 2.0  # 2 QUOTE per 1 BASE
    amount = 10.0  # Want 10 BASE
    
    # Buying BASE (spend_is_base=False), amount in BASE (amount_basis_is_base=True)
    result = compute_spend_amount(
        price_quote_per_base=price,
        amount=amount,
        amount_basis_is_base=True,
        spend_is_base=False
    )
    
    # To get 10 BASE, need to spend 10 * 2 = 20 QUOTE
    assert result == 20.0


def test_compute_spend_amount_buy_base_basis_quote():
    """Buy BASE with QUOTE: amount is QUOTE to spend, price is quote/base."""
    price = 2.0  # 2 QUOTE per 1 BASE
    amount = 20.0  # Spending 20 QUOTE
    
    # Buying BASE (spend_is_base=False), amount in QUOTE (amount_basis_is_base=False)
    result = compute_spend_amount(
        price_quote_per_base=price,
        amount=amount,
        amount_basis_is_base=False,
        spend_is_base=False
    )
    
    # Should return amount as-is (we're spending the quote amount directly)
    assert result == 20.0


def test_is_exact_output_case_sell_target_quote():
    """Selling BASE to receive exact QUOTE is exact-output."""
    # Spending base (sell), amount specified in quote (target output)
    result = is_exact_output_case(
        amount_basis_is_base=False,
        spend_is_base=True
    )
    assert result is True


def test_is_exact_output_case_buy_target_base():
    """Buying exact amount of BASE is exact-output."""
    # Spending quote (buy), amount specified in base (target output)
    result = is_exact_output_case(
        amount_basis_is_base=True,
        spend_is_base=False
    )
    assert result is True


def test_is_exact_output_case_sell_exact_base():
    """Selling exact BASE amount is NOT exact-output."""
    # Spending base (sell), amount specified in base (spend amount)
    result = is_exact_output_case(
        amount_basis_is_base=True,
        spend_is_base=True
    )
    assert result is False


def test_is_exact_output_case_buy_exact_quote():
    """Buying BASE with exact QUOTE amount is NOT exact-output."""
    # Spending quote (buy), amount specified in quote (spend amount)
    result = is_exact_output_case(
        amount_basis_is_base=False,
        spend_is_base=False
    )
    assert result is False


def test_price_inversion_high_price():
    """Test with high price (1 BASE = 1000 QUOTE)."""
    price = 1000.0  # Expensive BASE
    amount = 5.0
    
    # Buy 5 BASE -> need 5000 QUOTE
    result = compute_spend_amount(
        price_quote_per_base=price,
        amount=amount,
        amount_basis_is_base=True,
        spend_is_base=False
    )
    assert result == 5000.0
    
    # Sell 5 BASE -> amount is 5
    result = compute_spend_amount(
        price_quote_per_base=price,
        amount=amount,
        amount_basis_is_base=True,
        spend_is_base=True
    )
    assert result == 5.0


def test_price_inversion_low_price():
    """Test with low price (1 BASE = 0.001 QUOTE)."""
    price = 0.001  # Very cheap BASE
    amount = 5.0
    
    # Buy 5 BASE -> need 0.005 QUOTE
    result = compute_spend_amount(
        price_quote_per_base=price,
        amount=amount,
        amount_basis_is_base=True,
        spend_is_base=False
    )
    assert abs(result - 0.005) < 1e-9
    
    # To get 100 QUOTE, sell 100/0.001 = 100000 BASE
    result = compute_spend_amount(
        price_quote_per_base=price,
        amount=100.0,
        amount_basis_is_base=False,
        spend_is_base=True
    )
    assert result == 100000.0


def test_zero_price_protection():
    """Test that zero or negative prices are handled."""
    result = compute_spend_amount(
        price_quote_per_base=0.0,
        amount=10.0,
        amount_basis_is_base=True,
        spend_is_base=False
    )
    # Should return 0 for safety
    assert result == 0.0
    
    result = compute_spend_amount(
        price_quote_per_base=-1.0,
        amount=10.0,
        amount_basis_is_base=True,
        spend_is_base=False
    )
    # Should return 0 for safety
    assert result == 0.0

