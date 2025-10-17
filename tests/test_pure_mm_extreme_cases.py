"""Test Pure Market Making strategy with extreme parameters."""
from unittest.mock import Mock
from strategies.dex_pure_market_making import DexPureMarketMaking, DexPureMMConfig
import pytest


def test_pure_mm_negative_price_level_protection():
    """Test that pure MM prevents negative price levels even with extreme spreads."""
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 100.0
    mock_conn.get_price_fast.return_value = 1.0  # Very low mid price
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    mock_conn.get_allowance.return_value = 10**30
    mock_conn.client.to_wei.return_value = 10**18
    mock_conn.client.from_wei.return_value = 1.0
    mock_conn.tx_explorer_url = lambda tx: f"https://bscscan.com/tx/{tx}"
    
    # Extreme configuration: 50% spread with 10 levels
    # This would create: 1.0 * (1 - 0.5 * 10) = 1.0 * (1 - 5.0) = -4.0 (negative!)
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        upper_percent=5.0,  # 5% per level
        lower_percent=15.0,  # 15% per level (extreme!)
        levels_each_side=10,
        order_amount=1.0,
        amount_is_base=True,
        refresh_seconds=60.0,
    )
    
    strategy = DexPureMarketMaking(cfg, connectors=[mock_conn])
    
    # Trigger level rebuild
    strategy._rebuild_levels(mid=1.0)
    
    # Check that lower levels are clamped and not negative
    for level in strategy.lower_levels:
        assert level > 0, f"Lower level {level} should be positive"
        assert level >= 0.01, f"Lower level {level} should be at least 1% of mid price"
    
    print(f"Lower levels (clamped): {strategy.lower_levels}")
    print(f"Upper levels: {strategy.upper_levels}")


def test_pure_mm_very_narrow_spread():
    """Test pure MM with very narrow spreads."""
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 100.0
    mock_conn.get_price_fast.return_value = 100.0
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    
    # Very narrow spread: 0.01% per level
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        upper_percent=0.01,  # 0.01% per level
        lower_percent=0.01,
        levels_each_side=5,
        order_amount=1.0,
        amount_is_base=True,
        refresh_seconds=60.0,
    )
    
    strategy = DexPureMarketMaking(cfg, connectors=[mock_conn])
    strategy._rebuild_levels(mid=100.0)
    
    # Verify levels are properly spaced
    expected_upper = [100.01, 100.02, 100.03, 100.04, 100.05]
    expected_lower = [99.99, 99.98, 99.97, 99.96, 99.95]
    
    for i, (actual, expected) in enumerate(zip(strategy.upper_levels, expected_upper)):
        assert abs(actual - expected) < 0.01, f"Upper level {i}: {actual} vs {expected}"
    
    for i, (actual, expected) in enumerate(zip(strategy.lower_levels, expected_lower)):
        assert abs(actual - expected) < 0.01, f"Lower level {i}: {actual} vs {expected}"
    
    print(f"Narrow spread test passed")


def test_pure_mm_asymmetric_extreme_spread():
    """Test pure MM with very asymmetric spreads."""
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 100.0
    mock_conn.get_price_fast.return_value = 50.0
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    
    # Very asymmetric: 20% up vs 2% down
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        upper_percent=20.0,  # 20% per level up
        lower_percent=2.0,   # 2% per level down
        levels_each_side=3,
        order_amount=1.0,
        amount_is_base=True,
        refresh_seconds=60.0,
    )
    
    strategy = DexPureMarketMaking(cfg, connectors=[mock_conn])
    strategy._rebuild_levels(mid=50.0)
    
    # Upper levels: 50 * (1 + 0.2*i) for i in [1,2,3]
    expected_upper = [60.0, 70.0, 80.0]
    # Lower levels: 50 * (1 - 0.02*i) for i in [1,2,3]
    expected_lower = [49.0, 48.0, 47.0]
    
    for i, (actual, expected) in enumerate(zip(strategy.upper_levels, expected_upper)):
        assert abs(actual - expected) < 0.1, f"Upper level {i}: {actual} vs {expected}"
    
    for i, (actual, expected) in enumerate(zip(strategy.lower_levels, expected_lower)):
        assert abs(actual - expected) < 0.1, f"Lower level {i}: {actual} vs {expected}"
    
    print(f"Asymmetric spread test passed")


def test_pure_mm_single_level():
    """Test pure MM with just 1 level on each side."""
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 100.0
    mock_conn.get_price_fast.return_value = 10.0
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        upper_percent=1.0,
        lower_percent=1.0,
        levels_each_side=1,  # Just 1 level each side
        order_amount=1.0,
        amount_is_base=True,
        refresh_seconds=60.0,
    )
    
    strategy = DexPureMarketMaking(cfg, connectors=[mock_conn])
    strategy._rebuild_levels(mid=10.0)
    
    assert len(strategy.upper_levels) == 1
    assert len(strategy.lower_levels) == 1
    assert abs(strategy.upper_levels[0] - 10.1) < 0.01
    assert abs(strategy.lower_levels[0] - 9.9) < 0.01
    
    print(f"Single level test passed")


if __name__ == "__main__":
    test_pure_mm_negative_price_level_protection()
    test_pure_mm_very_narrow_spread()
    test_pure_mm_asymmetric_extreme_spread()
    test_pure_mm_single_level()
    print("All Pure MM extreme case tests passed!")

