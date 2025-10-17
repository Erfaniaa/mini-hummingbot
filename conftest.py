"""Pytest configuration to disable problematic plugins and speed up tests."""

import pytest
from unittest.mock import patch
import time

# Disable web3.tools.pytest_ethereum plugin which has compatibility issues
pytest_plugins = []


def pytest_configure(config):
    """Configure pytest to skip problematic plugins."""
    config.pluginmanager.set_blocked("web3.tools.pytest_ethereum")


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Mock time.sleep to make tests run faster."""
    import time as time_module
    original_sleep = time_module.sleep
    
    def mock_sleep(seconds):
        # For tests, sleep very briefly instead of full duration
        if seconds > 0.1:
            original_sleep(0.001)  # Sleep 1ms instead of seconds
        else:
            original_sleep(seconds)
    
    monkeypatch.setattr(time_module, 'sleep', mock_sleep)

