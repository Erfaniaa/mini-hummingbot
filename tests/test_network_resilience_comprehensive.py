"""Comprehensive tests for network resilience and disconnection scenarios."""
from unittest.mock import Mock, MagicMock
from strategies.dex_dca import DexDCA, DexDCAConfig
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig
from strategies.dex_pure_market_making import DexPureMarketMaking, DexPureMMConfig
from strategies.resilience import ConnectionMonitor, resilient_call, RetryConfig
import pytest


def test_dca_continues_after_temporary_network_failure():
    """Test DCA strategy continues running after temporary network failures."""
    call_count = [0]
    
    def mock_get_price_fast(*args, **kwargs):
        call_count[0] += 1
        # Fail on attempts 2-4, then succeed
        if 2 <= call_count[0] <= 4:
            raise ConnectionError("Network timeout")
        return 10.0
    
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 1000.0
    mock_conn.get_price_fast.side_effect = mock_get_price_fast
    mock_conn.get_price.return_value = 10.0  # Fallback
    mock_conn.market_swap.return_value = "0x123"
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
        total_amount=100.0,
        amount_is_base=False,
        interval_seconds=0.01,
        num_orders=3,
        distribution="uniform",
    )
    
    strategy = DexDCA(cfg, connectors=[mock_conn])
    
    # Execute several ticks - should handle network failures gracefully
    for _ in range(10):
        strategy._on_tick()
        if strategy._stopped:
            break
    
    # Strategy should have completed successfully despite network issues
    assert strategy.completed_orders == 3
    assert strategy._stopped
    
    # Connection monitor should show some failures but also successes
    stats = strategy._connection_monitor.get_stats()
    print(f"DCA network resilience: {stats}")
    assert stats['successful'] > 0
    assert stats['total_attempts'] >= 3


def test_batch_swap_handles_intermittent_price_fetch_failures():
    """Test batch swap continues when price fetching intermittently fails."""
    price_call_count = [0]
    
    def mock_get_price_fast(*args, **kwargs):
        price_call_count[0] += 1
        # Fail every 3rd call
        if price_call_count[0] % 3 == 0:
            raise Exception("RPC unavailable")
        return 15.0  # Price in range to trigger levels
    
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 1000.0
    mock_conn.get_price_fast.side_effect = mock_get_price_fast
    mock_conn.get_price.return_value = 15.0  # Fallback
    mock_conn.market_swap.return_value = "0x456"
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    mock_conn.get_allowance.return_value = 10**30
    mock_conn.client.to_wei.return_value = 10**18
    mock_conn.client.from_wei.return_value = 1.0
    mock_conn.tx_explorer_url = lambda tx: f"https://bscscan.com/tx/{tx}"
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["0x" + "00" * 32],
        chain_id=97,
        base_symbol="TOKEN",
        quote_symbol="USDT",
        total_amount=50.0,
        amount_is_base=True,
        spend_is_base=True,
        min_price=10.0,
        max_price=14.0,  # Price is 15, so all levels below will trigger
        num_orders=3,
        distribution="uniform",
        interval_seconds=0.01,
    )
    
    strategy = DexBatchSwap(cfg, connectors=[mock_conn])
    
    # Execute several ticks with intermittent failures
    for _ in range(20):
        strategy._on_tick()
        if strategy._stopped:
            break
    
    # Strategy should eventually complete despite intermittent failures
    # At least some levels should execute successfully
    executed_levels = sum(1 for done in strategy.done if done)
    assert executed_levels > 0, "At least some levels should execute despite network issues"
    assert strategy._stopped or executed_levels == len(strategy.levels)
    
    print(f"Batch swap completed with intermittent network issues")


def test_pure_mm_recovers_from_connection_loss():
    """Test Pure MM strategy recovers from temporary connection loss."""
    connection_quality = [True]  # True = good connection, False = bad
    tick_count = [0]
    
    def mock_get_price_fast(*args, **kwargs):
        tick_count[0] += 1
        # Simulate connection loss for ticks 3-5
        if 3 <= tick_count[0] <= 5:
            connection_quality[0] = False
            raise Exception("Connection lost")
        connection_quality[0] = True
        return 10.0
    
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 1000.0
    mock_conn.get_price_fast.side_effect = mock_get_price_fast
    mock_conn.get_price.return_value = 10.0  # Fallback
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
        levels_each_side=2,
        order_amount=1.0,
        amount_is_base=True,
        refresh_seconds=0.5,
        tick_interval_seconds=0.01,
    )
    
    strategy = DexPureMarketMaking(cfg, connectors=[mock_conn])
    
    # Execute multiple ticks - strategy should continue despite connection loss
    for _ in range(10):
        strategy._on_tick()
    
    # Connection should be restored after tick 5
    assert connection_quality[0] == True, "Connection should be restored"
    
    # Connection monitor should show recovery
    stats = strategy._connection_monitor.get_stats()
    print(f"Pure MM connection recovery: {stats}")
    assert stats['successful'] > 0, "Should have successful attempts after recovery"


def test_connection_monitor_tracks_consecutive_failures():
    """Test that connection monitor correctly tracks consecutive failures."""
    monitor = ConnectionMonitor("test")
    
    # Initial state
    assert monitor.consecutive_failures == 0
    assert monitor.is_connected == True
    
    # Record some failures
    for i in range(5):
        monitor.record_failure(Exception("Test error"))
        assert monitor.consecutive_failures == i + 1
    
    # After 3+ consecutive failures, should be marked as disconnected
    assert monitor.is_connected == False
    assert monitor.should_warn() == True
    
    # Record success should reset consecutive failures and restore connection
    monitor.record_success()
    assert monitor.consecutive_failures == 0
    assert monitor.is_connected == True
    assert monitor.should_warn() == False
    
    stats = monitor.get_stats()
    assert stats['total_attempts'] == 6
    assert stats['successful'] == 1
    assert stats['failed'] == 5
    print(f"Connection monitor stats: {stats}")


def test_resilient_call_with_network_errors():
    """Test resilient_call handles network errors correctly."""
    call_count = [0]
    
    def failing_function():
        call_count[0] += 1
        if call_count[0] < 3:
            raise ConnectionError("Network timeout")
        return "success"
    
    retry_config = RetryConfig(max_retries=5, initial_delay=0.01)
    result = resilient_call(failing_function, retry_config=retry_config)
    
    assert result == "success"
    assert call_count[0] == 3  # Failed twice, succeeded on 3rd attempt


def test_resilient_call_with_permanent_failure():
    """Test resilient_call returns fallback on permanent failure."""
    def always_fails():
        raise ConnectionError("Permanent network issue")
    
    retry_config = RetryConfig(max_retries=3, initial_delay=0.01)
    result = resilient_call(
        always_fails, 
        retry_config=retry_config, 
        fallback="fallback_value"
    )
    
    assert result == "fallback_value"


def test_resilient_call_non_network_error_no_retry():
    """Test resilient_call doesn't retry on non-network errors."""
    call_count = [0]
    
    def fails_with_value_error():
        call_count[0] += 1
        raise ValueError("Invalid input")
    
    retry_config = RetryConfig(max_retries=5, initial_delay=0.01)
    
    with pytest.raises(ValueError):
        resilient_call(fails_with_value_error, retry_config=retry_config)
    
    # Should only be called once (no retries for non-network errors)
    assert call_count[0] == 1


def test_strategy_error_handler_allows_continuation():
    """Test that strategy error handlers allow continuation with network errors."""
    call_count = [0]
    
    def mock_get_price_with_intermittent_failure(*args, **kwargs):
        call_count[0] += 1
        # Fail first call with network error, then succeed
        if call_count[0] == 1:
            raise ConnectionError("Network timeout")  # Network error will be retried
        return 10.0
    
    mock_conn = Mock()
    mock_conn.get_balance.return_value = 1000.0
    mock_conn.get_price_fast.side_effect = mock_get_price_with_intermittent_failure
    mock_conn.get_price.return_value = 10.0
    mock_conn.quantize_amount.side_effect = lambda sym, amt: amt
    mock_conn._resolve.side_effect = lambda x: x.upper()
    mock_conn.client = Mock()
    mock_conn.client.get_decimals.return_value = 18
    mock_conn.market_swap.return_value = "0x123"
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
        total_amount=100.0,
        amount_is_base=False,
        interval_seconds=0.01,
        num_orders=3,
        distribution="uniform",
    )
    
    strategy = DexDCA(cfg, connectors=[mock_conn])
    
    # Execute tick - should handle network error and continue
    strategy._on_tick()
    
    # Strategy should recover and execute order successfully
    assert strategy.attempted_orders == 1, "Should have attempted one order"
    assert call_count[0] >= 1, "Price fetch should have been attempted"


if __name__ == "__main__":
    test_dca_continues_after_temporary_network_failure()
    test_batch_swap_handles_intermittent_price_fetch_failures()
    test_pure_mm_recovers_from_connection_loss()
    test_connection_monitor_tracks_consecutive_failures()
    test_resilient_call_with_network_errors()
    test_resilient_call_with_permanent_failure()
    test_resilient_call_non_network_error_no_retry()
    test_strategy_error_handler_allows_continuation()
    print("All network resilience tests passed!")

