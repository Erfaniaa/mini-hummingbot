"""Test DCA strategy behavior when orders fail."""
from unittest.mock import Mock, MagicMock
from strategies.dex_dca import DexDCA, DexDCAConfig


def test_dca_with_persistent_failures():
    """Test that DCA doesn't run forever when orders persistently fail."""
    # Create mock connector that always fails swaps
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 100.0
    mock_conn.get_price_fast.return_value = 1.0
    mock_conn.swap_exact_out.side_effect = Exception("Insufficient balance")
    mock_conn.market_swap.side_effect = Exception("Insufficient balance")
    mock_conn.quantize_amount.return_value = 10.0
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    mock_conn.tx_explorer_url = lambda tx: f"https://bscscan.com/tx/{tx}"
    
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=50.0,
        amount_is_base=True,
        interval_seconds=0.1,
        num_orders=5,
        distribution="uniform",
    )
    
    strategy = DexDCA(cfg, connectors=[mock_conn])
    
    # Simulate 20 ticks (should stop after 5 orders are attempted)
    tick_count = 0
    max_ticks = 20
    
    while not strategy._stopped and tick_count < max_ticks:
        strategy._on_tick()
        tick_count += 1
    
    # Strategy should have stopped after attempting all orders
    # Even if they all failed
    print(f"Tick count: {tick_count}")
    print(f"Orders left: {strategy.orders_left}")
    print(f"Completed orders: {strategy.completed_orders}")
    print(f"Stopped: {strategy._stopped}")
    
    # Check behavior
    assert tick_count <= max_ticks, "Strategy ran too many ticks (possible infinite loop)"
    
    # With current implementation, if all orders fail:
    # - completed_orders = 0 (no successful orders)
    # - orders_left = 5 (never decremented on failure)
    # - Strategy runs forever until manually stopped or max ticks reached
    
    # This is a BUG: Strategy should stop after num_orders attempts,
    # regardless of success/failure
    if strategy.orders_left > 0 and tick_count == max_ticks:
        print("BUG FOUND: DCA strategy runs indefinitely when all orders fail")
        print(f"  Expected: Stop after {cfg.num_orders} attempts")
        print(f"  Actual: Still running after {tick_count} ticks")


def test_dca_with_some_failures():
    """Test DCA behavior when some orders succeed and some fail."""
    call_count = [0]
    
    def mock_swap(*args, **kwargs):
        call_count[0] += 1
        # Fail on attempts 2 and 4
        if call_count[0] in [2, 4]:
            raise Exception("Temporary failure")
        return "0x123456"
    
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 100.0
    mock_conn.get_price_fast.return_value = 1.0
    mock_conn.market_swap.side_effect = mock_swap
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    mock_conn.get_allowance.return_value = 10**30
    mock_conn.client.to_wei.return_value = 10**18
    mock_conn.client.from_wei.return_value = 1.0
    mock_conn.tx_explorer_url = lambda tx: f"https://bscscan.com/tx/{tx}"
    
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=50.0,
        amount_is_base=False,
        interval_seconds=0.1,
        num_orders=5,
        distribution="uniform",
    )
    
    strategy = DexDCA(cfg, connectors=[mock_conn])
    
    # Simulate ticks until strategy stops or max iterations
    tick_count = 0
    max_ticks = 30
    
    while not strategy._stopped and tick_count < max_ticks:
        strategy._on_tick()
        tick_count += 1
    
    print(f"\nPartial failure test:")
    print(f"  Ticks: {tick_count}")
    print(f"  Completed orders: {strategy.completed_orders}")
    print(f"  Orders left: {strategy.orders_left}")
    print(f"  Swap calls: {call_count[0]}")
    
    # With failures on attempts 2 and 4, we should see:
    # - More than 5 ticks (because failures cause retries)
    # - Eventually complete 5 successful orders
    # But this might take many more than 5 ticks


if __name__ == "__main__":
    test_dca_with_persistent_failures()
    test_dca_with_some_failures()

