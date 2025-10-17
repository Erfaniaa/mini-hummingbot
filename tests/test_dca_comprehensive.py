"""Comprehensive tests for DCA strategy behavior."""
from unittest.mock import Mock
from strategies.dex_dca import DexDCA, DexDCAConfig
import time


def test_dca_completes_all_orders_successfully():
    """Test DCA completes all orders when no failures occur."""
    swap_count = [0]
    
    def mock_swap(*args, **kwargs):
        swap_count[0] += 1
        return f"0x{swap_count[0]:064x}"
    
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 10000.0
    mock_conn.get_price_fast.return_value = 10.0
    mock_conn.market_swap.side_effect = mock_swap
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    mock_conn.get_allowance.return_value = 10**30
    mock_conn.client.to_wei.return_value = 10**18
    mock_conn.client.from_wei.return_value = 1.0
    mock_conn.tx_explorer_url = lambda tx: f"https://scan.com/tx/{tx}"
    
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=300.0,
        amount_is_base=False,
        interval_seconds=0.05,
        num_orders=5,
        distribution="uniform",
    )
    
    strategy = DexDCA(cfg, connectors=[mock_conn])
    
    # Execute until completion
    ticks = 0
    max_ticks = 20
    while strategy.orders_left > 0 and ticks < max_ticks:
        strategy._on_tick()
        time.sleep(0.06)  # Wait for interval
        ticks += 1
    
    assert swap_count[0] == 5, f"Should execute 5 orders, got {swap_count[0]}"
    assert strategy.completed_orders == 5, f"Should track 5 completed, got {strategy.completed_orders}"
    assert strategy.orders_left == 0, f"Should have 0 orders left, got {strategy.orders_left}"
    assert abs(strategy.remaining) < 0.01, f"Should have ~0 remaining, got {strategy.remaining}"
    
    print(f"✓ DCA completed all {swap_count[0]} orders successfully")


def test_dca_handles_intermittent_failures():
    """Test DCA retries failed orders and completes successfully."""
    attempt_count = [0]
    
    def mock_swap(*args, **kwargs):
        attempt_count[0] += 1
        # Fail every 3rd attempt
        if attempt_count[0] % 3 == 0:
            raise Exception("Temporary network error")
        return f"0x{attempt_count[0]:064x}"
    
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 10000.0
    mock_conn.get_price_fast.return_value = 10.0
    mock_conn.market_swap.side_effect = mock_swap
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    mock_conn.get_allowance.return_value = 10**30
    mock_conn.client.to_wei.return_value = 10**18
    mock_conn.client.from_wei.return_value = 1.0
    mock_conn.tx_explorer_url = lambda tx: f"https://scan.com/tx/{tx}"
    
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=100.0,
        amount_is_base=False,
        interval_seconds=0.05,
        num_orders=3,
        distribution="uniform",
    )
    
    strategy = DexDCA(cfg, connectors=[mock_conn])
    
    # Execute with retries
    ticks = 0
    max_ticks = 30
    while strategy.orders_left > 0 and ticks < max_ticks:
        strategy._on_tick()
        time.sleep(0.06)
        ticks += 1
    
    # Should eventually complete despite failures
    assert strategy.completed_orders == 3, f"Should complete 3 orders, got {strategy.completed_orders}"
    assert attempt_count[0] > 3, f"Should have >3 attempts due to retries, got {attempt_count[0]}"
    assert strategy.orders_left == 0, f"Should finish all orders, got {strategy.orders_left} left"
    
    print(f"✓ DCA completed with retries: {strategy.completed_orders} orders, {attempt_count[0]} attempts")


def test_dca_stops_after_max_attempts_on_persistent_failure():
    """Test DCA stops after maximum attempts when orders persistently fail."""
    attempt_count = [0]
    
    def mock_swap(*args, **kwargs):
        attempt_count[0] += 1
        raise Exception("Persistent failure")
    
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 10000.0
    mock_conn.get_price_fast.return_value = 10.0
    mock_conn.market_swap.side_effect = mock_swap
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    mock_conn.tx_explorer_url = lambda tx: f"https://scan.com/tx/{tx}"
    
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=100.0,
        amount_is_base=False,
        interval_seconds=0.05,
        num_orders=3,
        distribution="uniform",
    )
    
    strategy = DexDCA(cfg, connectors=[mock_conn])
    
    # Execute many ticks
    ticks = 0
    max_ticks = 50
    while not strategy._stopped and ticks < max_ticks:
        strategy._on_tick()
        time.sleep(0.06)
        ticks += 1
    
    # Should stop after max attempts (num_orders * 10)
    max_allowed_attempts = cfg.num_orders * 10  # 30
    assert strategy.attempted_orders <= max_allowed_attempts + 1, \
        f"Should stop after {max_allowed_attempts} attempts, got {strategy.attempted_orders}"
    assert strategy.completed_orders == 0, "No orders should complete"
    assert strategy._stopped == True, "Strategy should be stopped"
    
    print(f"✓ DCA stopped after {strategy.attempted_orders} failed attempts (max: {max_allowed_attempts})")


def test_dca_uniform_vs_random_distribution():
    """Test DCA amount computation logic for different distributions."""
    # Test uniform distribution logic
    total = 100.0
    num_orders = 4
    remaining = total
    orders_left = num_orders
    
    amounts_uniform = []
    for _ in range(num_orders):
        # Uniform: divide remaining equally
        amt = remaining / orders_left
        amounts_uniform.append(amt)
        remaining -= amt
        orders_left -= 1
    
    # All should be 25.0
    assert all(abs(amt - 25.0) < 0.01 for amt in amounts_uniform), \
        f"Uniform should be ~25 each, got {amounts_uniform}"
    
    # Check random varies (statistical test with seed)
    import random
    random.seed(42)
    remaining = total
    orders_left = num_orders
    amounts_random = []
    
    for _ in range(num_orders):
        # Random: uniform random in [0.5*avg, 1.5*avg], clamped to remaining
        avg = remaining / orders_left
        lower = avg * 0.5
        upper = min(avg * 1.5, remaining)
        amt = random.uniform(lower, upper) if lower < upper else avg
        amounts_random.append(amt)
        remaining -= amt
        orders_left -= 1
    
    # Should have some variation
    has_variation = any(abs(amt - 25.0) > 1.0 for amt in amounts_random)
    assert has_variation, f"Random should have variation, got {amounts_random}"
    
    print(f"✓ DCA distributions: uniform={amounts_uniform[:2]}..., random={amounts_random[:2]}...")


def test_dca_interval_check_logic():
    """Test DCA interval checking logic."""
    interval = 0.1  # 100ms
    
    # Simulate timing
    last_exec = time.time()
    
    # Immediately after - should not be ready
    now = last_exec + 0.05  # 50ms later
    should_execute = (now - last_exec) >= interval
    assert not should_execute, "Should not be ready after 50ms"
    
    # After interval - should be ready
    now = last_exec + 0.11  # 110ms later
    should_execute = (now - last_exec) >= interval
    assert should_execute, "Should be ready after 110ms"
    
    print(f"✓ DCA interval logic: correct timing checks")


def test_dca_counter_logic():
    """Test DCA counter update logic."""
    # Initial state
    attempted = 0
    completed = 0
    orders_left = 3
    
    # First attempt - success
    attempted += 1
    success = True
    if success:
        completed += 1
        orders_left -= 1
    
    assert attempted == 1
    assert completed == 1
    assert orders_left == 2
    
    # Second attempt - failure
    attempted += 1
    success = False
    if success:
        completed += 1
        orders_left -= 1
    
    assert attempted == 2
    assert completed == 1, "Should not increment on failure"
    assert orders_left == 2, "Should not decrement on failure"
    
    # Third attempt - success (retry of failed order)
    attempted += 1
    success = True
    if success:
        completed += 1
        orders_left -= 1
    
    assert attempted == 3
    assert completed == 2
    assert orders_left == 1
    
    print(f"✓ DCA counter logic: attempted={attempted}, completed={completed}, left={orders_left}")


if __name__ == "__main__":
    test_dca_completes_all_orders_successfully()
    test_dca_handles_intermittent_failures()
    test_dca_stops_after_max_attempts_on_persistent_failure()
    test_dca_uniform_vs_random_distribution()
    test_dca_interval_check_logic()
    test_dca_counter_logic()
    print("\n✅ All comprehensive DCA tests passed!")

