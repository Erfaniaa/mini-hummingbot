"""
Tests for resilience module.
"""
import time
from strategies.resilience import (
    ConnectionMonitor,
    is_network_error,
    resilient_call,
    RetryConfig,
)


def test_connection_monitor():
    """Test connection monitoring."""
    monitor = ConnectionMonitor("test")
    
    # Initially connected
    assert monitor.is_connected
    assert monitor.consecutive_failures == 0
    
    # Record success
    monitor.record_success()
    assert monitor.successful_attempts == 1
    assert monitor.is_connected
    
    # Record failures
    for i in range(5):
        monitor.record_failure(Exception("test"))
    
    assert monitor.failed_attempts == 5
    assert monitor.consecutive_failures == 5
    assert not monitor.is_connected
    assert monitor.should_warn()
    
    # Success resets consecutive failures
    monitor.record_success()
    assert monitor.consecutive_failures == 0
    assert monitor.is_connected


def test_is_network_error():
    """Test network error detection."""
    # Network errors
    assert is_network_error(Exception("Connection timeout"))
    assert is_network_error(Exception("Failed to connect to RPC"))
    assert is_network_error(Exception("Network unreachable"))
    assert is_network_error(Exception("Connection refused"))
    
    # Non-network errors
    assert not is_network_error(Exception("Invalid parameter"))
    assert not is_network_error(Exception("Insufficient funds"))
    assert not is_network_error(ValueError("Bad value"))


def test_resilient_call_success():
    """Test resilient_call with successful function."""
    call_count = [0]
    
    def success_func():
        call_count[0] += 1
        return "success"
    
    result = resilient_call(success_func)
    assert result == "success"
    assert call_count[0] == 1


def test_resilient_call_retry():
    """Test resilient_call with retries."""
    call_count = [0]
    
    def fail_twice_then_succeed():
        call_count[0] += 1
        if call_count[0] < 3:
            raise Exception("Connection timeout")
        return "success"
    
    retry_attempts = []
    
    def on_retry(attempt, error):
        retry_attempts.append(attempt)
    
    result = resilient_call(
        fail_twice_then_succeed,
        retry_config=RetryConfig(max_retries=5, initial_delay=0.1),
        on_retry=on_retry
    )
    
    assert result == "success"
    assert call_count[0] == 3
    assert len(retry_attempts) == 2  # Failed twice before success


def test_resilient_call_fallback():
    """Test resilient_call fallback on all failures."""
    def always_fail():
        raise Exception("Connection timeout")
    
    result = resilient_call(
        always_fail,
        retry_config=RetryConfig(max_retries=3, initial_delay=0.1),
        fallback="fallback_value"
    )
    
    assert result == "fallback_value"


def test_resilient_call_non_network_error():
    """Test resilient_call doesn't retry non-network errors."""
    call_count = [0]
    
    def non_network_fail():
        call_count[0] += 1
        raise ValueError("Invalid parameter")
    
    try:
        resilient_call(
            non_network_fail,
            retry_config=RetryConfig(max_retries=5, initial_delay=0.1)
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert str(e) == "Invalid parameter"
        assert call_count[0] == 1  # Should not retry


def test_retry_config_delay():
    """Test retry delay calculation."""
    config = RetryConfig(
        initial_delay=1.0,
        max_delay=10.0,
        exponential_base=2.0,
        jitter=False
    )
    
    # Exponential backoff
    assert config.get_delay(0) == 1.0
    assert config.get_delay(1) == 2.0
    assert config.get_delay(2) == 4.0
    assert config.get_delay(3) == 8.0
    
    # Max delay cap
    assert config.get_delay(10) == 10.0


if __name__ == "__main__":
    test_connection_monitor()
    test_is_network_error()
    test_resilient_call_success()
    test_resilient_call_retry()
    test_resilient_call_fallback()
    test_resilient_call_non_network_error()
    test_retry_config_delay()
    print("All resilience tests passed!")
