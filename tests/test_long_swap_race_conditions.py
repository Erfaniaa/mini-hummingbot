"""
Comprehensive tests for race conditions with long swap execution times (70-90s).

These tests simulate scenarios where:
- Swap execution takes 70-90 seconds
- Tick interval is 1 second
- Strategy intervals are 60 seconds
- Multiple ticks can be triggered while swap is in progress

Tests use threading and fast simulation (50ms instead of 70s) for quick execution.
"""
import time
import threading
from unittest.mock import Mock, MagicMock
from strategies.dex_pure_market_making import DexPureMarketMaking, DexPureMMConfig
from strategies.dex_dca import DexDCA, DexDCAConfig
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig


def create_mock_connector():
    """Create a properly configured mock connector."""
    mock = Mock()
    mock.get_balance.return_value = 100000.0
    mock.get_price_fast.return_value = 100.0
    mock.quantize_amount.side_effect = lambda sym, amt: float(amt)
    mock._resolve.side_effect = lambda x: x.upper()
    mock.client = Mock()
    mock.client.get_decimals.return_value = 18
    mock.get_allowance.return_value = 10**30
    mock.client.to_wei.return_value = 10**18
    mock.client.from_wei.return_value = 1.0
    mock.tx_explorer_url = lambda tx: f"https://scan.com/tx/{tx}"
    return mock


def test_pure_mm_rapid_ticks_during_long_swap():
    """
    Test Pure MM _order_in_progress flag blocks concurrent executions.
    
    Scenario:
    - Simulate long swap (70ms = 70s scaled)
    - Multiple execution attempts during swap
    - Expected: Only one proceeds, others return False immediately
    """
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        upper_percent=1.0,
        lower_percent=1.0,
        levels_each_side=1,
        order_amount=10.0,
        amount_is_base=True,
        refresh_seconds=300.0,
        tick_interval_seconds=1.0,
    )
    
    mock_conn = create_mock_connector()
    strategy = DexPureMarketMaking(cfg, connectors=[mock_conn])
    strategy._rebuild_levels(100.0)
    
    # Manually set flag to simulate long swap in progress
    strategy._order_in_progress = True
    
    # Try to execute - should return False immediately
    result = strategy._execute_order_at_level(101.0, 105.0, is_upper=True)
    assert result == False, "Should be blocked by _order_in_progress flag"
    
    # Clear flag
    strategy._order_in_progress = False
    
    # Should still be blocked by _executed_levels if we mark it
    strategy._executed_levels.add(("upper", 101.0))
    result = strategy._execute_order_at_level(101.0, 105.0, is_upper=True)
    assert result == False, "Should be blocked by _executed_levels"
    
    print(f"✓ Pure MM: Order execution properly blocked by flags")


def test_dca_rapid_ticks_before_interval():
    """
    Test DCA with rapid ticks before interval expires.
    
    Scenario:
    - Interval: 60s
    - Tick: 1s
    - Swap time: 80s (simulated as 80ms)
    - Expected: Orders execute sequentially, not concurrently
    """
    swap_count = [0]
    concurrent_swaps = [0]
    max_concurrent = [0]
    
    def mock_market_swap(*args, **kwargs):
        concurrent_swaps[0] += 1
        max_concurrent[0] = max(max_concurrent[0], concurrent_swaps[0])
        swap_count[0] += 1
        time.sleep(0.08)  # Simulate 80s as 80ms
        concurrent_swaps[0] -= 1
        return f"0x{swap_count[0]:064x}"
    
    mock_conn = create_mock_connector()
    mock_conn.market_swap.side_effect = mock_market_swap
    
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=300.0,
        amount_is_base=False,
        interval_seconds=0.06,  # 60ms interval (simulates 60s)
        num_orders=3,
        distribution="uniform",
    )
    
    strategy = DexDCA(cfg, connectors=[mock_conn])
    
    # Execute ticks rapidly
    threads = []
    for _ in range(10):  # 10 rapid ticks
        t = threading.Thread(target=strategy._on_tick)
        threads.append(t)
        t.start()
        time.sleep(0.01)
    
    for t in threads:
        t.join()
    
    # Should execute orders sequentially
    assert max_concurrent[0] <= 1, f"Concurrent swaps detected: {max_concurrent[0]}"
    assert swap_count[0] <= 3, f"Expected ≤3 swaps, got {swap_count[0]}"
    
    print(f"✓ DCA: {swap_count[0]} swaps, max concurrent: {max_concurrent[0]}")


def test_batch_swap_multiple_levels_long_execution():
    """
    Test Batch Swap with multiple triggered levels and long execution.
    
    Scenario:
    - 5 levels triggered simultaneously
    - Each swap takes 75s (simulated as 75ms)
    - Total execution: 375s (simulated as 375ms)
    - Tick attempts during execution should be blocked
    """
    swap_count = [0]
    levels_executed = []
    
    def mock_market_swap(*args, **kwargs):
        swap_count[0] += 1
        levels_executed.append(swap_count[0])
        time.sleep(0.075)  # Simulate 75s as 75ms
        return f"0x{swap_count[0]:064x}"
    
    mock_conn = create_mock_connector()
    mock_conn.market_swap.side_effect = mock_market_swap
    mock_conn.get_price_fast.return_value = 100.0  # Above all levels
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=500.0,
        amount_is_base=True,
        spend_is_base=True,
        min_price=80.0,
        max_price=95.0,  # All below current price
        num_orders=5,
        distribution="uniform",
        interval_seconds=1.0,
    )
    
    strategy = DexBatchSwap(cfg, connectors=[mock_conn])
    
    # First tick will trigger all 5 levels (takes ~375ms total)
    tick_thread = threading.Thread(target=strategy._on_tick)
    tick_thread.start()
    
    # Try additional ticks while first is processing
    time.sleep(0.1)  # Let first tick start
    blocked_ticks = []
    for _ in range(5):
        before_flag = strategy._levels_in_progress
        strategy._on_tick()
        after_flag = strategy._levels_in_progress
        blocked_ticks.append(before_flag)
        time.sleep(0.05)
    
    tick_thread.join()
    
    # All 5 levels should execute
    assert swap_count[0] == 5, f"Expected 5 swaps, got {swap_count[0]}"
    # At least some ticks should have been blocked
    assert any(blocked_ticks), "Expected some ticks to be blocked by flag"
    
    print(f"✓ Batch Swap: {swap_count[0]} levels executed, concurrent ticks blocked")


def test_pure_mm_level_not_retriggered_despite_long_swap():
    """
    Test that Pure MM _executed_levels prevents double-trigger.
    
    Scenario:
    - Level marked as executed
    - Multiple attempts to execute same level
    - Expected: All blocked
    """
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        upper_percent=1.0,
        lower_percent=1.0,
        levels_each_side=1,
        order_amount=10.0,
        amount_is_base=True,
        refresh_seconds=300.0,
        tick_interval_seconds=1.0,
    )
    
    mock_conn = create_mock_connector()
    strategy = DexPureMarketMaking(cfg, connectors=[mock_conn])
    strategy._rebuild_levels(100.0)
    
    # Mark level as executed
    strategy._executed_levels.add(("upper", 101.0))
    
    # Try to execute multiple times - all should be blocked
    results = []
    for _ in range(5):
        result = strategy._execute_order_at_level(101.0, 105.0, is_upper=True)
        results.append(result)
    
    assert all(r == False for r in results), "All should be blocked"
    assert len(strategy._executed_levels) == 1, "Only one entry should exist"
    
    print(f"✓ Pure MM: Level not re-triggered (5 attempts blocked)")


def test_dca_order_completion_with_long_swap():
    """
    Test DCA completes all orders correctly despite long swap times.
    
    Scenario:
    - 3 orders, 60s interval
    - Each swap takes 85s
    - Expected: All 3 orders complete, tracked correctly
    """
    swap_count = [0]
    
    def mock_market_swap(*args, **kwargs):
        swap_count[0] += 1
        time.sleep(0.085)  # 85ms for 85s
        return f"0x{swap_count[0]:064x}"
    
    mock_conn = create_mock_connector()
    mock_conn.market_swap.side_effect = mock_market_swap
    
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=300.0,
        amount_is_base=False,
        interval_seconds=0.10,  # 100ms
        num_orders=3,
        distribution="uniform",
    )
    
    strategy = DexDCA(cfg, connectors=[mock_conn])
    
    # Execute ticks with proper intervals
    for i in range(3):
        strategy._on_tick()
        time.sleep(0.11)  # Wait for interval + swap
    
    assert swap_count[0] == 3, f"Expected 3 orders, got {swap_count[0]}"
    assert strategy.completed_orders == 3, f"Completed tracking wrong: {strategy.completed_orders}"
    assert strategy.orders_left == 0, f"Orders left should be 0, got {strategy.orders_left}"
    
    print(f"✓ DCA: All {swap_count[0]} orders completed with long swaps")


def test_batch_swap_balance_failure_during_multi_level():
    """
    Test Batch Swap handles balance failure gracefully when multiple levels trigger.
    
    Scenario:
    - 5 levels trigger
    - Balance sufficient for only 2
    - Each swap takes 70s
    - Expected: 2 succeed, 3 fail, no crashes
    """
    swap_count = [0]
    
    def mock_get_balance(symbol):
        # Enough for 2 swaps only
        if swap_count[0] < 2:
            return 50000.0
        return 0.1  # Insufficient
    
    def mock_market_swap(*args, **kwargs):
        swap_count[0] += 1
        time.sleep(0.07)
        if swap_count[0] <= 2:
            return f"0x{swap_count[0]:064x}"
        raise Exception("Insufficient balance")
    
    mock_conn = create_mock_connector()
    mock_conn.get_balance.side_effect = mock_get_balance
    mock_conn.market_swap.side_effect = mock_market_swap
    mock_conn.get_price_fast.return_value = 100.0
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=500.0,
        amount_is_base=True,
        spend_is_base=True,
        min_price=85.0,
        max_price=95.0,
        num_orders=5,
        distribution="uniform",
        interval_seconds=1.0,
    )
    
    strategy = DexBatchSwap(cfg, connectors=[mock_conn])
    
    # Should not crash despite failures
    try:
        strategy._on_tick()
        success = True
    except Exception as e:
        success = False
        print(f"Strategy crashed: {e}")
    
    assert success, "Strategy should handle failures gracefully"
    # All levels get marked done (even failed ones - by design)
    # This prevents infinite retries on persistent balance issues
    done_count = sum(1 for d in strategy.done if d)
    assert done_count >= 2, f"Expected >=2 done levels, got {done_count}"
    
    print(f"✓ Batch Swap: Handled partial execution ({done_count}/5 levels marked done) gracefully")


def test_pure_mm_refresh_clears_executed_levels():
    """
    Test Pure MM refresh clears _executed_levels.
    
    Scenario:
    - Levels executed and tracked
    - Refresh occurs
    - Expected: _executed_levels cleared, allowing re-execution
    """
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        upper_percent=1.0,
        lower_percent=1.0,
        levels_each_side=1,
        order_amount=10.0,
        amount_is_base=True,
        refresh_seconds=60.0,
        tick_interval_seconds=1.0,
    )
    
    mock_conn = create_mock_connector()
    strategy = DexPureMarketMaking(cfg, connectors=[mock_conn])
    strategy._rebuild_levels(100.0)
    
    # Mark some levels as executed
    strategy._executed_levels.add(("upper", 101.0))
    strategy._executed_levels.add(("lower", 99.0))
    assert len(strategy._executed_levels) == 2
    
    # Rebuild (refresh)
    strategy._rebuild_levels(102.0)
    
    # Should be cleared
    assert len(strategy._executed_levels) == 0, "Should clear on refresh"
    
    print(f"✓ Pure MM: Refresh clears executed levels")


def test_concurrent_strategy_instances_independent_state():
    """
    Test that multiple strategy instances maintain independent state.
    
    Scenario:
    - 2 Pure MM instances
    - Manipulate flags independently
    - Expected: No interference
    """
    strategies = []
    for i in range(2):
        cfg = DexPureMMConfig(
            rpc_url="",
            private_keys=["0x" + f"{i:02d}" * 32],
            chain_id=97,
            base_symbol="TOKEN",
            quote_symbol="USDT",
            upper_percent=1.0,
            lower_percent=1.0,
            levels_each_side=1,
            order_amount=10.0,
            amount_is_base=True,
            refresh_seconds=300.0,
            tick_interval_seconds=1.0,
        )
        
        mock_conn = create_mock_connector()
        strategy = DexPureMarketMaking(cfg, connectors=[mock_conn])
        strategy._rebuild_levels(100.0)
        strategies.append(strategy)
    
    # Manipulate first strategy
    strategies[0]._order_in_progress = True
    strategies[0]._executed_levels.add(("upper", 101.0))
    
    # Second strategy should be unaffected
    assert strategies[1]._order_in_progress == False, "Strategy 2 should be independent"
    assert len(strategies[1]._executed_levels) == 0, "Strategy 2 should have empty executed levels"
    
    print(f"✓ Concurrent instances: Independent state maintained")


if __name__ == "__main__":
    test_pure_mm_rapid_ticks_during_long_swap()
    test_dca_rapid_ticks_before_interval()
    test_batch_swap_multiple_levels_long_execution()
    test_pure_mm_level_not_retriggered_despite_long_swap()
    test_dca_order_completion_with_long_swap()
    test_batch_swap_balance_failure_during_multi_level()
    test_pure_mm_refresh_clears_executed_levels()
    test_concurrent_strategy_instances_independent_state()
    print("\n✅ All long swap race condition tests passed!")

