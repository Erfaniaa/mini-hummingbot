"""
Advanced corner case tests for trading strategies.

Focus on:
1. Extreme price movements
2. Very large/small numbers
3. Division by zero protection
4. Negative price level handling
5. Empty wallet lists
"""
import pytest
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig, _generate_levels, _compute_distribution_weights
from strategies.dex_pure_market_making import DexPureMarketMaking, DexPureMMConfig
from strategies.dex_dca import DexDCA, DexDCAConfig


def test_generate_levels_single_order():
    """Test level generation with single order."""
    levels = _generate_levels(min_price=10.0, max_price=10.0, num_orders=1)
    assert len(levels) == 1
    assert levels[0] == 10.0


def test_generate_levels_two_orders():
    """Test level generation with two orders."""
    levels = _generate_levels(min_price=10.0, max_price=20.0, num_orders=2)
    assert len(levels) == 2
    assert levels[0] == 10.0
    assert levels[1] == 20.0


def test_generate_levels_zero_orders():
    """Test level generation with zero orders."""
    levels = _generate_levels(min_price=10.0, max_price=20.0, num_orders=0)
    assert len(levels) == 0


def test_generate_levels_many_orders():
    """Test level generation with many orders."""
    levels = _generate_levels(min_price=1.0, max_price=100.0, num_orders=100)
    assert len(levels) == 100
    assert levels[0] == 1.0
    assert levels[-1] == 100.0
    # Check spacing is approximately uniform
    expected_step = (100.0 - 1.0) / 99.0
    for i in range(1, len(levels)):
        actual_step = levels[i] - levels[i-1]
        assert abs(actual_step - expected_step) < 0.001


def test_distribution_weights_uniform():
    """Test uniform distribution weights."""
    weights = _compute_distribution_weights(5, "uniform")
    assert len(weights) == 5
    assert all(abs(w - 0.2) < 0.0001 for w in weights)
    assert abs(sum(weights) - 1.0) < 0.0001


def test_distribution_weights_bell():
    """Test bell distribution weights."""
    weights = _compute_distribution_weights(5, "bell")
    assert len(weights) == 5
    assert abs(sum(weights) - 1.0) < 0.0001
    # Center should have highest weight
    center_idx = 2  # Middle of 5 elements (0,1,2,3,4)
    for i in range(len(weights)):
        if i != center_idx:
            assert weights[center_idx] >= weights[i]


def test_distribution_weights_zero():
    """Test distribution with zero orders."""
    weights = _compute_distribution_weights(0, "uniform")
    assert len(weights) == 0


def test_distribution_weights_single():
    """Test distribution with single order."""
    weights = _compute_distribution_weights(1, "uniform")
    assert len(weights) == 1
    assert abs(weights[0] - 1.0) < 0.0001


def test_pure_mm_extreme_spread():
    """Test Pure MM with extremely wide spread."""
    class FakeConn:
        def __init__(self):
            self.price = 100.0
            self.balances = {"BASE": 1000, "QUOTE": 100000}
            self.txs = []
        def get_price_fast(self, b, q): return self.price
        def get_price(self, b, q): return self.price
        def get_balance(self, s): return self.balances.get(s, 0)
        def get_allowance(self, s): return 10**30
        def market_swap(self, *args, **kwargs): 
            self.txs.append("0xtx")
            return "0xtx"
        def swap_exact_out(self, *args, **kwargs): 
            self.txs.append("0xtx")
            return "0xtx"
        def tx_explorer_url(self, h): return f"https://scan/{h}"
        def quantize_amount(self, s, a): return a
    
    conn = FakeConn()
    
    # Very wide spread: 500% above and below
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        upper_percent=500.0,  # 500%
        lower_percent=500.0,  # 500%
        levels_each_side=1,
        order_amount=10.0,
        amount_is_base=True,
        refresh_seconds=9999,
        tick_interval_seconds=0.01
    )
    
    strat = DexPureMarketMaking(cfg, connectors=[conn])
    strat._rebuild_levels(100.0)
    
    # Upper level should be at 100 * (1 + 5) = 600
    # Lower level should be at 100 * (1 - 5) = -400 -> clamped to 1% = 1
    assert len(strat.upper_levels) == 1
    assert len(strat.lower_levels) == 1
    assert strat.upper_levels[0] == 600.0
    # Lower level should be clamped to minimum (1% of mid)
    assert strat.lower_levels[0] == 1.0  # Clamped from negative


def test_pure_mm_negative_price_protection():
    """Test Pure MM clamps negative price levels."""
    class FakeConn:
        def __init__(self):
            self.price = 10.0
            self.balances = {"BASE": 1000, "QUOTE": 10000}
        def get_price_fast(self, b, q): return self.price
        def get_price(self, b, q): return self.price
        def get_balance(self, s): return self.balances.get(s, 0)
        def get_allowance(self, s): return 10**30
        def tx_explorer_url(self, h): return f"https://scan/{h}"
    
    conn = FakeConn()
    
    # Extreme lower spread that would cause negative prices
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        upper_percent=10.0,
        lower_percent=50.0,  # 50% per level
        levels_each_side=3,  # Would create: 50%, 100%, 150% below = negative!
        order_amount=5.0,
        amount_is_base=True,
        refresh_seconds=9999,
        tick_interval_seconds=0.01
    )
    
    strat = DexPureMarketMaking(cfg, connectors=[conn])
    strat._rebuild_levels(10.0)
    
    # All lower levels should be positive (clamped)
    assert all(lvl > 0 for lvl in strat.lower_levels)
    assert len(strat.lower_levels) == 3


def test_batch_swap_price_range_validation():
    """Test batch swap validates price ranges."""
    # Invalid: min_price >= max_price
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=100.0,
        amount_is_base=True,
        min_price=20.0,
        max_price=10.0,  # Less than min!
        num_orders=5,
        distribution="uniform"
    )
    with pytest.raises(ValueError, match="min_price.*must be.*max_price"):
        DexBatchSwap(cfg)


def test_batch_swap_zero_price_validation():
    """Test batch swap rejects zero/negative prices."""
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=100.0,
        amount_is_base=True,
        min_price=0.0,  # Zero!
        max_price=10.0,
        num_orders=5,
        distribution="uniform"
    )
    with pytest.raises(ValueError, match="Prices must be positive"):
        DexBatchSwap(cfg)


def test_batch_swap_negative_num_orders():
    """Test batch swap rejects negative number of orders."""
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=100.0,
        amount_is_base=True,
        min_price=10.0,
        max_price=20.0,
        num_orders=-5,  # Negative!
        distribution="uniform"
    )
    with pytest.raises(ValueError, match="num_orders must be positive"):
        DexBatchSwap(cfg)


def test_dca_negative_num_orders():
    """Test DCA rejects negative number of orders."""
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=100.0,
        amount_is_base=True,
        num_orders=-3,  # Negative!
        interval_seconds=60.0,
        distribution="uniform"
    )
    with pytest.raises(ValueError, match="num_orders must be positive"):
        DexDCA(cfg)


def test_dca_zero_total_amount():
    """Test DCA rejects zero total amount."""
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=0.0,  # Zero!
        amount_is_base=True,
        num_orders=5,
        interval_seconds=60.0,
        distribution="uniform"
    )
    with pytest.raises(ValueError, match="total_amount must be positive"):
        DexDCA(cfg)


def test_dca_negative_interval():
    """Test DCA rejects negative interval."""
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=100.0,
        amount_is_base=True,
        num_orders=5,
        interval_seconds=-1.0,  # Negative!
        distribution="uniform"
    )
    with pytest.raises(ValueError, match="interval_seconds must be positive"):
        DexDCA(cfg)


def test_very_small_amounts():
    """Test strategies handle very small amounts (dust)."""
    class FakeConn:
        def __init__(self):
            self.price = 100.0
            self.balances = {"BASE": 0.000001, "QUOTE": 0.0001}
        def get_price_fast(self, b, q): return self.price
        def get_price(self, b, q): return self.price
        def get_balance(self, s): return self.balances.get(s, 0)
        def get_allowance(self, s): return 10**30
        def quantize_amount(self, s, a): return round(a, 18)
    
    conn = FakeConn()
    
    # DCA with very small amount
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=0.000001,  # Dust amount
        amount_is_base=True,
        num_orders=1,
        interval_seconds=1.0,
        distribution="uniform",
        spend_is_base=True
    )
    
    strat = DexDCA(cfg, connectors=[conn])
    
    # Should handle small amounts without crashing
    chunk = strat._pick_chunk()
    assert chunk >= 0.0
    assert chunk <= 0.000001


def test_very_large_amounts():
    """Test strategies handle very large amounts."""
    class FakeConn:
        def __init__(self):
            self.price = 1.0
            self.balances = {"BASE": 10**18, "QUOTE": 10**18}
        def get_price_fast(self, b, q): return self.price
        def get_price(self, b, q): return self.price
        def get_balance(self, s): return self.balances.get(s, 0)
        def get_allowance(self, s): return 10**30
        def quantize_amount(self, s, a): return a
    
    conn = FakeConn()
    
    # DCA with very large amount
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=10**15,  # Very large
        amount_is_base=True,
        num_orders=100,
        interval_seconds=1.0,
        distribution="uniform",
        spend_is_base=True
    )
    
    strat = DexDCA(cfg, connectors=[conn])
    
    # Should handle large amounts
    chunk = strat._pick_chunk()
    assert chunk >= 0.0
    assert chunk <= 10**15

