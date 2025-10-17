"""Extreme and corner case tests for Batch Swap strategy."""
from unittest.mock import Mock
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig, _generate_levels, _compute_distribution_weights
import pytest


def test_batch_swap_single_level():
    """Test batch swap with just 1 level (edge case)."""
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 10000.0
    mock_conn.get_price_fast.return_value = 15.0
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    
    # Single level: num_orders=1 with any valid range
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=100.0,
        amount_is_base=True,
        spend_is_base=True,
        min_price=10.0,
        max_price=20.0,  # Range doesn't matter for single level
        num_orders=1,      # Only 1 level at min_price
        distribution="uniform",
        interval_seconds=1.0,
    )
    
    strategy = DexBatchSwap(cfg, connectors=[mock_conn])
    
    assert len(strategy.levels) == 1, "Should have exactly 1 level"
    assert len(strategy.done) == 1, "Should have 1 done flag"
    assert len(strategy.remaining) == 1, "Should have 1 remaining amount"
    assert strategy.remaining[0] == 100.0, "All amount in single level"
    assert strategy.levels[0] == 10.0, "Single level should be at min_price"
    
    print(f"✓ Batch Swap single level: {strategy.levels[0]}")


def test_batch_swap_many_levels():
    """Test batch swap with large number of levels (100)."""
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=10000.0,
        amount_is_base=True,
        spend_is_base=True,
        min_price=1.0,
        max_price=100.0,
        num_orders=100,  # Many levels
        distribution="uniform",
        interval_seconds=1.0,
    )
    
    mock_conn = Mock()
    strategy = DexBatchSwap(cfg, connectors=[mock_conn])
    
    assert len(strategy.levels) == 100, "Should have 100 levels"
    assert len(strategy.done) == 100, "Should have 100 done flags"
    
    # Check levels are properly spaced
    expected_step = (100.0 - 1.0) / 99
    for i in range(1, 100):
        actual_diff = strategy.levels[i] - strategy.levels[i-1]
        assert abs(actual_diff - expected_step) < 0.01, f"Level spacing incorrect at {i}"
    
    # Check distribution sums to total
    total_distributed = sum(strategy.remaining)
    assert abs(total_distributed - 10000.0) < 0.01, f"Distribution should sum to 10000, got {total_distributed}"
    
    print(f"✓ Batch Swap 100 levels: properly spaced and distributed")


def test_batch_swap_all_levels_above_price():
    """Test when all levels are above current price (none trigger)."""
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 10000.0
    mock_conn.get_price_fast.return_value = 5.0  # Below all levels
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=100.0,
        amount_is_base=True,
        spend_is_base=True,
        min_price=10.0,
        max_price=20.0,  # All above current price
        num_orders=5,
        distribution="uniform",
        interval_seconds=1.0,
    )
    
    strategy = DexBatchSwap(cfg, connectors=[mock_conn])
    
    # Execute tick - nothing should trigger
    strategy._on_tick()
    
    # No levels should be done
    assert not any(strategy.done), "No levels should be done"
    assert all(amt > 0 for amt in strategy.remaining), "All amounts should remain"
    
    print(f"✓ Batch Swap all above price: no execution")


def test_batch_swap_all_levels_below_price():
    """Test when all levels are below current price (all trigger if selling)."""
    swap_count = [0]
    
    def mock_swap(*args, **kwargs):
        swap_count[0] += 1
        return f"0x{swap_count[0]:064x}"
    
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 10000.0
    mock_conn.get_price_fast.return_value = 25.0  # Above all levels
    mock_conn.market_swap.side_effect = mock_swap
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    mock_conn.get_allowance.return_value = 10**30
    mock_conn.client.to_wei.return_value = 10**18
    mock_conn.client.from_wei.return_value = 1.0
    mock_conn.tx_explorer_url = lambda tx: f"https://scan.com/tx/{tx}"
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=100.0,
        amount_is_base=True,
        spend_is_base=True,
        min_price=10.0,
        max_price=20.0,  # All below current price
        num_orders=3,
        distribution="uniform",
        interval_seconds=1.0,
    )
    
    strategy = DexBatchSwap(cfg, connectors=[mock_conn])
    
    # Execute tick - all should trigger
    strategy._on_tick()
    
    assert swap_count[0] == 3, f"All 3 levels should execute, got {swap_count[0]}"
    assert all(strategy.done), "All levels should be done"
    
    print(f"✓ Batch Swap all below price: all {swap_count[0]} executed")


def test_batch_swap_price_exactly_at_level():
    """Test when price is exactly at a level boundary."""
    swap_count = [0]
    
    def mock_swap(*args, **kwargs):
        swap_count[0] += 1
        return f"0x{swap_count[0]:064x}"
    
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 10000.0
    mock_conn.get_price_fast.return_value = 15.0  # Exactly at middle level
    mock_conn.market_swap.side_effect = mock_swap
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    mock_conn.get_allowance.return_value = 10**30
    mock_conn.client.to_wei.return_value = 10**18
    mock_conn.client.from_wei.return_value = 1.0
    mock_conn.tx_explorer_url = lambda tx: f"https://scan.com/tx/{tx}"
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=100.0,
        amount_is_base=True,
        spend_is_base=True,
        min_price=10.0,
        max_price=20.0,
        num_orders=3,  # Levels at 10, 15, 20
        distribution="uniform",
        interval_seconds=1.0,
    )
    
    strategy = DexBatchSwap(cfg, connectors=[mock_conn])
    
    # Execute tick
    strategy._on_tick()
    
    # With sell orders and price=15:
    # Should execute levels 10 and 15 (price >= level)
    # Should not execute level 20 (price < level)
    assert swap_count[0] == 2, f"Should execute 2 levels (10, 15), got {swap_count[0]}"
    
    print(f"✓ Batch Swap price at boundary: {swap_count[0]} levels executed correctly")


def test_batch_swap_bell_distribution_vs_uniform():
    """Test bell-shaped distribution concentrates amounts in middle."""
    # Uniform distribution
    weights_uniform = _compute_distribution_weights(10, "uniform")
    assert all(abs(w - 0.1) < 0.001 for w in weights_uniform), "Uniform should be equal"
    
    # Bell distribution
    weights_bell = _compute_distribution_weights(10, "bell")
    
    # Middle should have more weight than edges
    middle_weight = weights_bell[5]
    edge_weight = weights_bell[0]
    assert middle_weight > edge_weight, f"Middle ({middle_weight}) should be > edge ({edge_weight})"
    
    # Should sum to 1
    assert abs(sum(weights_bell) - 1.0) < 0.001, "Weights should sum to 1"
    
    print(f"✓ Bell distribution: middle={middle_weight:.3f}, edge={edge_weight:.3f}")


def test_batch_swap_extreme_price_range():
    """Test with very wide price range."""
    levels = _generate_levels(min_price=0.0001, max_price=10000.0, num_orders=50)
    
    assert len(levels) == 50, "Should generate 50 levels"
    assert levels[0] == 0.0001, "First level should be min"
    assert abs(levels[-1] - 10000.0) < 0.01, "Last level should be max"
    
    # Check monotonic increase
    for i in range(1, len(levels)):
        assert levels[i] > levels[i-1], f"Levels should increase at {i}"
    
    print(f"✓ Extreme price range: {levels[0]:.4f} to {levels[-1]:.2f}")


def test_batch_swap_zero_amount_edge_case():
    """Test batch swap doesn't crash with very small amounts."""
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 10000.0
    mock_conn.get_price_fast.return_value = 15.0
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=0.0001,  # Very small amount
        amount_is_base=True,
        spend_is_base=True,
        min_price=10.0,
        max_price=20.0,
        num_orders=100,  # Distributed across many levels
        distribution="uniform",
        interval_seconds=1.0,
    )
    
    strategy = DexBatchSwap(cfg, connectors=[mock_conn])
    
    # Each level gets tiny amount
    for amt in strategy.remaining:
        assert amt >= 0, "Amounts should be non-negative"
        assert amt < 0.01, "Amounts should be very small"
    
    print(f"✓ Very small amount: {strategy.remaining[0]:.8f} per level")


def test_batch_swap_buy_vs_sell_logic():
    """Test sell vs buy trigger logic is correct."""
    # Sell logic: price >= level triggers
    cfg_sell = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=100.0,
        amount_is_base=True,
        spend_is_base=True,  # Selling
        min_price=10.0,
        max_price=20.0,
        num_orders=3,
        distribution="uniform",
        interval_seconds=1.0,
    )
    
    mock_conn = Mock()
    strategy_sell = DexBatchSwap(cfg_sell, connectors=[mock_conn])
    
    # Price = 15, level = 10: should trigger (price >= level)
    assert strategy_sell._should_execute(price=15.0, level=10.0) == True
    # Price = 15, level = 20: should not trigger
    assert strategy_sell._should_execute(price=15.0, level=20.0) == False
    
    # Buy logic: price <= level triggers
    cfg_buy = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=100.0,
        amount_is_base=False,
        spend_is_base=False,  # Buying
        min_price=10.0,
        max_price=20.0,
        num_orders=3,
        distribution="uniform",
        interval_seconds=1.0,
    )
    
    strategy_buy = DexBatchSwap(cfg_buy, connectors=[mock_conn])
    
    # Price = 15, level = 20: should trigger (price <= level)
    assert strategy_buy._should_execute(price=15.0, level=20.0) == True
    # Price = 15, level = 10: should not trigger
    assert strategy_buy._should_execute(price=15.0, level=10.0) == False
    
    print(f"✓ Sell/Buy logic: correct trigger conditions")


def test_batch_swap_multi_wallet_partial_failures():
    """Test batch swap with multiple wallets where some fail."""
    swap_counts = [0, 0]  # Track per wallet
    
    def create_swap_fn(wallet_idx):
        def mock_swap(*args, **kwargs):
            swap_counts[wallet_idx] += 1
            if wallet_idx == 1:  # Second wallet fails
                raise Exception("Wallet 2 insufficient balance")
            return f"0x{swap_counts[wallet_idx]:064x}"
        return mock_swap
    
    connectors = []
    for i in range(2):
        mock_conn = Mock()
        mock_conn.get_balance.return_value = 10000.0 if i == 0 else 10.0  # Wallet 2 low balance
        mock_conn.get_price_fast.return_value = 15.0
        mock_conn.market_swap.side_effect = create_swap_fn(i)
        mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
        mock_conn._resolve.side_effect = lambda x: x.upper()
        mock_conn.client = Mock()
        mock_conn.client.get_decimals.return_value = 18
        mock_conn.get_allowance.return_value = 10**30
        mock_conn.client.to_wei.return_value = 10**18
        mock_conn.client.from_wei.return_value = 1.0
        mock_conn.tx_explorer_url = lambda tx: f"https://scan.com/tx/{tx}"
        connectors.append(mock_conn)
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32, "0x" + "11" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=100.0,
        amount_is_base=True,
        spend_is_base=True,
        min_price=10.0,
        max_price=14.0,
        num_orders=3,
        distribution="uniform",
        interval_seconds=1.0,
    )
    
    strategy = DexBatchSwap(cfg, connectors=connectors)
    
    # Execute - wallet 1 succeeds, wallet 2 fails
    try:
        strategy._on_tick()
    except:
        pass  # Expected some failures
    
    # Wallet 1 should have executed
    assert swap_counts[0] == 3, f"Wallet 1 should execute 3, got {swap_counts[0]}"
    # Levels should still be marked done (to prevent infinite retries)
    assert all(strategy.done), "Levels should be marked done despite wallet 2 failures"
    
    print(f"✓ Multi-wallet partial failures: wallet1={swap_counts[0]}, wallet2={swap_counts[1]}")


if __name__ == "__main__":
    test_batch_swap_single_level()
    test_batch_swap_many_levels()
    test_batch_swap_all_levels_above_price()
    test_batch_swap_all_levels_below_price()
    test_batch_swap_price_exactly_at_level()
    test_batch_swap_bell_distribution_vs_uniform()
    test_batch_swap_extreme_price_range()
    test_batch_swap_zero_amount_edge_case()
    test_batch_swap_buy_vs_sell_logic()
    test_batch_swap_multi_wallet_partial_failures()
    print("\n✅ All Batch Swap extreme case tests passed!")

