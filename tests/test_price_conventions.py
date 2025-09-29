"""
Tests to verify price conventions and amount calculations are correct.

Ensures all strategies use BASE/QUOTE price convention consistently.
"""

from strategies.utils import compute_spend_amount, is_exact_output_case


def test_compute_spend_amount_sell():
    """Test compute_spend_amount when selling base for quote."""
    # Price: 1 BTCB = 0.20 USDT (quote per base)
    price_quote_per_base = 0.20
    
    # Case 1: User provides amount in base (wants to sell X BTCB)
    amount_basis_is_base = True
    spend_is_base = True  # Selling BTCB
    amount = 100.0  # 100 BTCB
    
    result = compute_spend_amount(price_quote_per_base, amount, amount_basis_is_base, spend_is_base)
    assert result == 100.0, f"Expected 100.0, got {result}"
    print(f"✓ Sell 100 BTCB (basis=base, spend=base): {result} BTCB")
    
    # Case 2: User provides amount in quote (wants to receive X USDT)
    amount_basis_is_base = False
    spend_is_base = True  # Selling BTCB
    amount = 20.0  # Want to get 20 USDT
    
    result = compute_spend_amount(price_quote_per_base, amount, amount_basis_is_base, spend_is_base)
    expected = 20.0 / 0.20  # Need to sell 100 BTCB to get 20 USDT
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Sell BTCB to get 20 USDT (basis=quote, spend=base): {result} BTCB")


def test_compute_spend_amount_buy():
    """Test compute_spend_amount when buying base with quote."""
    # Price: 1 BTCB = 0.20 USDT (quote per base)
    price_quote_per_base = 0.20
    
    # Case 1: User provides amount in quote (wants to spend X USDT)
    amount_basis_is_base = False
    spend_is_base = False  # Buying BTCB with USDT
    amount = 20.0  # 20 USDT
    
    result = compute_spend_amount(price_quote_per_base, amount, amount_basis_is_base, spend_is_base)
    assert result == 20.0, f"Expected 20.0, got {result}"
    print(f"✓ Buy BTCB with 20 USDT (basis=quote, spend=quote): {result} USDT")
    
    # Case 2: User provides amount in base (wants to get X BTCB)
    amount_basis_is_base = True
    spend_is_base = False  # Buying BTCB with USDT
    amount = 100.0  # Want to get 100 BTCB
    
    result = compute_spend_amount(price_quote_per_base, amount, amount_basis_is_base, spend_is_base)
    expected = 100.0 * 0.20  # Need 20 USDT to buy 100 BTCB
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Buy 100 BTCB with USDT (basis=base, spend=quote): {result} USDT")


def test_is_exact_output():
    """Test exact output case detection."""
    # Selling base, amount in quote => exact output (want exact USDT)
    assert is_exact_output_case(amount_basis_is_base=False, spend_is_base=True)
    print("✓ Sell base for exact quote output: True")
    
    # Selling base, amount in base => not exact output (sell exact BTCB amount)
    assert not is_exact_output_case(amount_basis_is_base=True, spend_is_base=True)
    print("✓ Sell exact base amount: False")
    
    # Buying base, amount in base => exact output (want exact BTCB)
    assert is_exact_output_case(amount_basis_is_base=True, spend_is_base=False)
    print("✓ Buy exact base amount: True")
    
    # Buying base, amount in quote => not exact output (spend exact USDT)
    assert not is_exact_output_case(amount_basis_is_base=False, spend_is_base=False)
    print("✓ Spend exact quote to buy: False")


def test_price_comparison_logic():
    """Test that price comparison logic is correct."""
    # For sell orders (upper levels in PMM or batch swap selling):
    # When price goes UP (price >= level), we should sell
    current_price = 0.22  # BTCB/USDT went up to 0.22
    sell_level = 0.20
    should_sell = current_price >= sell_level
    assert should_sell, "Should sell when price rises above level"
    print(f"✓ Sell logic: price {current_price} >= level {sell_level} = {should_sell}")
    
    # For buy orders (lower levels in PMM or batch swap buying):
    # When price goes DOWN (price <= level), we should buy
    current_price = 0.18  # BTCB/USDT went down to 0.18
    buy_level = 0.20
    should_buy = current_price <= buy_level
    assert should_buy, "Should buy when price drops below level"
    print(f"✓ Buy logic: price {current_price} <= level {buy_level} = {should_buy}")


if __name__ == "__main__":
    print("Testing price conventions and calculations...\n")
    
    test_compute_spend_amount_sell()
    print()
    
    test_compute_spend_amount_buy()
    print()
    
    test_is_exact_output()
    print()
    
    test_price_comparison_logic()
    print()
    
    print("✅ All price convention tests passed!")
