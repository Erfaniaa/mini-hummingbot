"""
Resilience utilities for handling network failures and errors.

Ensures strategies continue running despite temporary failures.
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar, Optional, Any
from functools import wraps

T = TypeVar('T')


class NetworkError(Exception):
    """Raised when network-related errors occur."""
    pass


class RetryConfig:
    """Configuration for retry logic."""
    
    def __init__(
        self,
        max_retries: int = 5,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt with exponential backoff."""
        delay = min(
            self.initial_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        
        if self.jitter:
            import random
            delay *= (0.5 + random.random())
        
        return delay


def is_network_error(error: Exception) -> bool:
    """Check if error is network-related."""
    error_str = str(error).lower()
    network_keywords = [
        'connection',
        'timeout',
        'network',
        'unreachable',
        'refused',
        'reset',
        'broken pipe',
        'connect to rpc',
        'failed to connect',
        'unavailable',
        'service unavailable',
        'bad gateway',
    ]
    
    return any(keyword in error_str for keyword in network_keywords)


def resilient_call(
    func: Callable[..., T],
    *args,
    retry_config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
    fallback: Optional[T] = None,
    **kwargs
) -> Optional[T]:
    """
    Execute function with retry logic for network failures.
    
    Args:
        func: Function to execute
        retry_config: Retry configuration
        on_retry: Callback when retrying (attempt, error)
        fallback: Value to return if all retries fail
    
    Returns:
        Function result or fallback value
    """
    config = retry_config or RetryConfig()
    
    for attempt in range(config.max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            is_last_attempt = (attempt == config.max_retries - 1)
            
            if is_network_error(e):
                if is_last_attempt:
                    if on_retry:
                        on_retry(attempt, e)
                    return fallback
                
                delay = config.get_delay(attempt)
                
                if on_retry:
                    on_retry(attempt, e)
                
                time.sleep(delay)
            else:
                # Non-network error, don't retry
                raise
    
    return fallback


class ConnectionMonitor:
    """Monitors connection health and provides statistics."""
    
    def __init__(self, name: str = "connection"):
        self.name = name
        self.total_attempts = 0
        self.successful_attempts = 0
        self.failed_attempts = 0
        self.consecutive_failures = 0
        self.last_success_time = 0.0
        self.last_failure_time = 0.0
        self.is_connected = True
    
    def record_success(self):
        """Record successful operation."""
        self.total_attempts += 1
        self.successful_attempts += 1
        self.consecutive_failures = 0
        self.last_success_time = time.time()
        
        if not self.is_connected:
            print(f"[{self.name}] ✓ Connection restored")
            self.is_connected = True
    
    def record_failure(self, error: Exception):
        """Record failed operation."""
        self.total_attempts += 1
        self.failed_attempts += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        
        if self.is_connected and self.consecutive_failures >= 3:
            print(f"[{self.name}] ⚠ Connection issues detected ({self.consecutive_failures} consecutive failures)")
            self.is_connected = False
    
    def get_stats(self) -> dict:
        """Get connection statistics."""
        success_rate = 0.0
        if self.total_attempts > 0:
            success_rate = (self.successful_attempts / self.total_attempts) * 100
        
        return {
            "name": self.name,
            "is_connected": self.is_connected,
            "total_attempts": self.total_attempts,
            "successful": self.successful_attempts,
            "failed": self.failed_attempts,
            "consecutive_failures": self.consecutive_failures,
            "success_rate": success_rate,
            "last_success_time": self.last_success_time,
            "last_failure_time": self.last_failure_time,
        }
    
    def should_warn(self) -> bool:
        """Check if we should warn about connection issues."""
        return self.consecutive_failures >= 5


def resilient_method(
    retry_config: Optional[RetryConfig] = None,
    fallback: Any = None,
    monitor_attr: str = "_connection_monitor"
):
    """
    Decorator to make methods resilient to network failures.
    
    Usage:
        class MyClass:
            def __init__(self):
                self._connection_monitor = ConnectionMonitor("MyClass")
            
            @resilient_method()
            def fetch_data(self):
                # Network call
                pass
    """
    config = retry_config or RetryConfig()
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            monitor: Optional[ConnectionMonitor] = getattr(self, monitor_attr, None)
            
            def on_retry(attempt: int, error: Exception):
                error_msg = f"Attempt {attempt + 1}/{config.max_retries} failed: {error}"
                if monitor:
                    print(f"[{monitor.name}] {error_msg}")
                else:
                    print(f"[resilient] {error_msg}")
                
                if attempt < config.max_retries - 1:
                    delay = config.get_delay(attempt)
                    print(f"[resilient] Retrying in {delay:.1f}s...")
            
            result = resilient_call(
                func,
                self,
                *args,
                retry_config=config,
                on_retry=on_retry,
                fallback=fallback,
                **kwargs
            )
            
            if monitor:
                if result is not None or fallback is None:
                    monitor.record_success()
                else:
                    monitor.record_failure(Exception("Call returned None"))
            
            return result
        
        return wrapper
    
    return decorator


class SafeExecutor:
    """Executes operations safely, preventing crashes from errors."""
    
    @staticmethod
    def safe_execute(
        func: Callable,
        *args,
        on_error: Optional[Callable[[Exception], None]] = None,
        error_message: str = "Operation failed",
        **kwargs
    ) -> tuple[bool, Any]:
        """
        Safely execute a function, catching all errors.
        
        Returns:
            (success: bool, result: Any)
        """
        try:
            result = func(*args, **kwargs)
            return True, result
        except Exception as e:
            if on_error:
                on_error(e)
            else:
                print(f"[SafeExecutor] {error_message}: {e}")
            return False, None
    
    @staticmethod
    def safe_call_multiple(
        funcs: list[Callable],
        stop_on_first_success: bool = True,
        on_error: Optional[Callable[[Exception], None]] = None
    ) -> tuple[bool, Any]:
        """
        Try multiple functions until one succeeds.
        
        Returns:
            (success: bool, result: Any)
        """
        for func in funcs:
            success, result = SafeExecutor.safe_execute(
                func,
                on_error=on_error
            )
            if success and stop_on_first_success:
                return True, result
        
        return False, None
