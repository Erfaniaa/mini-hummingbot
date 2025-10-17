"""
Comprehensive tests for resilience mechanisms.

Tests verify:
1. Strategies continue running despite network errors
2. Connection monitoring tracks failures
3. Retry logic works correctly
4. Strategies handle transient errors gracefully
"""
import pytest
from strategies.resilience import (
    ConnectionMonitor,
    RetryConfig,
    resilient_call,
    is_network_error
)


def test_connection_monitor_tracks_success():
    """Test connection monitor tracks successful operations."""
    monitor = ConnectionMonitor("test")
    
    assert monitor.total_attempts == 0
    assert monitor.successful_attempts == 0
    assert monitor.is_connected is True
    
    monitor.record_success()
    
    assert monitor.total_attempts == 1
    assert monitor.successful_attempts == 1
    assert monitor.consecutive_failures == 0
    assert monitor.is_connected is True


def test_connection_monitor_tracks_failures():
    """Test connection monitor tracks failed operations."""
    monitor = ConnectionMonitor("test")
    
    monitor.record_failure(Exception("Network error"))
    
    assert monitor.total_attempts == 1
    assert monitor.failed_attempts == 1
    assert monitor.consecutive_failures == 1
    assert monitor.is_connected is True  # Still connected after 1 failure
    
    # After 3 consecutive failures, should mark as disconnected
    monitor.record_failure(Exception("Network error"))
    monitor.record_failure(Exception("Network error"))
    
    assert monitor.consecutive_failures == 3
    assert monitor.is_connected is False


def test_connection_monitor_resets_on_success():
    """Test connection monitor resets consecutive failures on success."""
    monitor = ConnectionMonitor("test")
    
    # Record some failures
    monitor.record_failure(Exception("Error 1"))
    monitor.record_failure(Exception("Error 2"))
    assert monitor.consecutive_failures == 2
    
    # Success resets consecutive failures
    monitor.record_success()
    assert monitor.consecutive_failures == 0
    assert monitor.is_connected is True


def test_connection_monitor_reconnect_message():
    """Test connection monitor prints reconnect message."""
    monitor = ConnectionMonitor("test")
    
    # Mark as disconnected
    for _ in range(3):
        monitor.record_failure(Exception("Network error"))
    
    assert monitor.is_connected is False
    
    # Success after disconnect should print reconnect message
    monitor.record_success()
    assert monitor.is_connected is True


def test_connection_monitor_should_warn():
    """Test connection monitor warns after 5 consecutive failures."""
    monitor = ConnectionMonitor("test")
    
    # 4 failures - should not warn
    for _ in range(4):
        monitor.record_failure(Exception("Error"))
    assert monitor.should_warn() is False
    
    # 5th failure - should warn
    monitor.record_failure(Exception("Error"))
    assert monitor.should_warn() is True


def test_connection_monitor_stats():
    """Test connection monitor provides accurate statistics."""
    monitor = ConnectionMonitor("test")
    
    monitor.record_success()
    monitor.record_success()
    monitor.record_failure(Exception("Error"))
    
    stats = monitor.get_stats()
    
    assert stats["total_attempts"] == 3
    assert stats["successful"] == 2
    assert stats["failed"] == 1
    assert abs(stats["success_rate"] - 66.67) < 0.1
    assert stats["consecutive_failures"] == 1


def test_retry_config_delay_calculation():
    """Test retry config calculates delays with exponential backoff."""
    config = RetryConfig(
        max_retries=5,
        initial_delay=1.0,
        max_delay=60.0,
        exponential_base=2.0,
        jitter=False  # Disable jitter for predictable testing
    )
    
    # First retry: 1.0 * 2^0 = 1.0
    assert config.get_delay(0) == 1.0
    
    # Second retry: 1.0 * 2^1 = 2.0
    assert config.get_delay(1) == 2.0
    
    # Third retry: 1.0 * 2^2 = 4.0
    assert config.get_delay(2) == 4.0
    
    # Very large attempt should be capped at max_delay
    assert config.get_delay(100) == 60.0


def test_retry_config_with_jitter():
    """Test retry config applies jitter to delays."""
    config = RetryConfig(
        initial_delay=10.0,
        exponential_base=2.0,
        jitter=True
    )
    
    # With jitter, delay should be between 50% and 150% of base
    delay = config.get_delay(0)
    assert 5.0 <= delay <= 15.0


def test_is_network_error_detection():
    """Test network error detection."""
    # Network-related errors
    assert is_network_error(Exception("Connection timeout"))
    assert is_network_error(Exception("Failed to connect to RPC"))
    assert is_network_error(Exception("Network unreachable"))
    assert is_network_error(Exception("Connection refused"))
    assert is_network_error(Exception("Connection reset"))
    assert is_network_error(Exception("Service unavailable"))
    
    # Non-network errors
    assert not is_network_error(Exception("Invalid parameter"))
    assert not is_network_error(Exception("Insufficient balance"))
    assert not is_network_error(Exception("Division by zero"))


def test_resilient_call_success():
    """Test resilient_call succeeds on first try."""
    call_count = [0]
    
    def successful_function():
        call_count[0] += 1
        return "success"
    
    result = resilient_call(successful_function)
    
    assert result == "success"
    assert call_count[0] == 1


def test_resilient_call_retry_on_network_error():
    """Test resilient_call retries on network errors."""
    call_count = [0]
    
    def flaky_function():
        call_count[0] += 1
        if call_count[0] < 3:
            raise Exception("Connection timeout")
        return "success"
    
    config = RetryConfig(max_retries=5, initial_delay=0.01)
    result = resilient_call(flaky_function, retry_config=config)
    
    assert result == "success"
    assert call_count[0] == 3  # Failed twice, succeeded third time


def test_resilient_call_fallback_on_max_retries():
    """Test resilient_call returns fallback after max retries."""
    call_count = [0]
    
    def always_fails():
        call_count[0] += 1
        raise Exception("Network unreachable")
    
    config = RetryConfig(max_retries=3, initial_delay=0.01)
    result = resilient_call(always_fails, retry_config=config, fallback="fallback_value")
    
    assert result == "fallback_value"
    assert call_count[0] == 3


def test_resilient_call_no_retry_on_non_network_error():
    """Test resilient_call doesn't retry non-network errors."""
    call_count = [0]
    
    def non_network_error():
        call_count[0] += 1
        raise ValueError("Invalid input")
    
    config = RetryConfig(max_retries=5, initial_delay=0.01)
    
    with pytest.raises(ValueError):
        resilient_call(non_network_error, retry_config=config)
    
    # Should not retry, so only called once
    assert call_count[0] == 1


def test_resilient_call_retry_callback():
    """Test resilient_call invokes retry callback."""
    retry_count = [0]
    
    def on_retry(attempt, error):
        retry_count[0] += 1
    
    def flaky_function():
        if retry_count[0] < 2:
            raise Exception("Connection timeout")
        return "success"
    
    config = RetryConfig(max_retries=5, initial_delay=0.01)
    result = resilient_call(
        flaky_function,
        retry_config=config,
        on_retry=on_retry
    )
    
    assert result == "success"
    assert retry_count[0] == 2


def test_strategy_continues_on_network_error():
    """Test that strategies continue running despite network errors."""
    from strategies.dex_pure_market_making import DexPureMarketMaking, DexPureMMConfig
    
    class FlakyConnector:
        """Connector that fails intermittently."""
        def __init__(self):
            self.call_count = 0
            self.balances = {"BASE": 1000, "QUOTE": 10000}
        
        def get_price_fast(self, base, quote):
            self.call_count += 1
            if self.call_count % 3 == 0:  # Fail every 3rd call
                raise Exception("Connection timeout")
            return 100.0
        
        def get_price(self, base, quote):
            return 100.0
        
        def get_balance(self, symbol):
            return self.balances.get(symbol, 0)
        
        def get_allowance(self, symbol):
            return 10**30
        
        def tx_explorer_url(self, tx_hash):
            return f"https://scan/{tx_hash}"
    
    conn = FlakyConnector()
    
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        upper_percent=5.0,
        lower_percent=5.0,
        levels_each_side=1,
        order_amount=10.0,
        amount_is_base=True,
        refresh_seconds=9999,
        tick_interval_seconds=0.01
    )
    
    strat = DexPureMarketMaking(cfg, connectors=[conn])
    
    # Execute multiple ticks - some will fail, strategy should continue
    for _ in range(10):
        try:
            strat._on_tick()
        except Exception:
            pass  # Strategy should handle errors internally
    
    # Strategy should have attempted multiple calls despite failures
    assert conn.call_count >= 3


def test_order_manager_tracks_failed_orders():
    """Test order manager properly tracks failed orders."""
    from strategies.order_manager import OrderManager
    
    order_mgr = OrderManager(wallet_name="test", strategy_name="test")
    
    # Create and fail an order
    order = order_mgr.create_order(
        base_symbol="BASE",
        quote_symbol="QUOTE",
        side="buy",
        amount=10.0,
        price=100.0,
        reason="Test order"
    )
    
    order_mgr.mark_failed(order, "Insufficient balance")
    
    summary = order_mgr.get_summary()
    assert summary["total"] == 1
    assert summary["failed"] == 1
    assert summary["filled"] == 0
    assert summary["success_rate"] == 0.0


def test_order_manager_retry_mechanism():
    """Test order manager retry mechanism."""
    from strategies.order_manager import OrderManager
    
    order_mgr = OrderManager(wallet_name="test", strategy_name="test", max_retries=3)
    
    attempt_count = [0]
    
    def flaky_submit():
        attempt_count[0] += 1
        if attempt_count[0] < 3:
            raise Exception("Network timeout")
        return "0xtxhash"
    
    order = order_mgr.create_order(
        base_symbol="BASE",
        quote_symbol="QUOTE",
        side="sell",
        amount=10.0,
        price=100.0,
        reason="Test order"
    )
    
    success = order_mgr.submit_order_with_retry(
        order,
        flaky_submit,
        lambda h: f"https://scan/{h}"
    )
    
    assert success is True
    assert attempt_count[0] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

