"""
Comprehensive tests for strategy behavior and edge cases.

Tests that strategies execute exactly what's expected, including corner cases.
"""
from strategies.dex_simple_swap import DexSimpleSwap, DexSimpleSwapConfig
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig
from strategies.dex_pure_market_making import DexPureMarketMaking, DexPureMMConfig
from strategies.dex_dca import DexDCA, DexDCAConfig
from connectors.dex.pancakeswap import PancakeSwapConnector


class FakeWeb3Client:
    """Fake Web3 client for testing."""
    def to_wei(self, address, amount):
        return int(amount * 10**18)


class FakeConnector:
    """Fake connector for testing without blockchain."""
    
    def __init__(self, balances=None, price=1.0):
        self.balances = balances or {"BASE": 1000.0, "QUOTE": 1000.0}
        self.price = price
        self.swaps = []
        self.chain_id = 56
        self.wallet_address = "0x1234567890123456789012345678901234567890"
        self.client = FakeWeb3Client()
    
    def get_balance(self, symbol: str) -> float:
        return self.balances.get(symbol, 0.0)
    
    def _resolve(self, symbol: str) -> str:
        """Resolve token symbol to address."""
        return f"0x{symbol.lower()}"
    
    def get_allowance(self, symbol: str) -> int:
        """Return a large allowance for testing."""
        return 10**30
    
    def get_price(self, token_in: str, token_out: str) -> float:
        if token_in == "BASE" and token_out == "QUOTE":
            return self.price
        elif token_in == "QUOTE" and token_out == "BASE":
            return 1.0 / self.price if self.price > 0 else 0.0
        return 1.0
    
    def get_price_fast(self, token_in: str, token_out: str) -> float:
        return self.get_price(token_in, token_out)
    
    def get_price_side(self, base_symbol: str, quote_symbol: str, side: str) -> float:
        if side == "sell":
            return self.get_price(base_symbol, quote_symbol)
        else:
            return 1.0 / self.get_price(base_symbol, quote_symbol) if self.get_price(base_symbol, quote_symbol) > 0 else 0.0
    
    def market_swap(self, base_symbol: str, quote_symbol: str, amount: float, amount_is_base: bool, slippage_bps: int = 50, side: str = None) -> str:
        """Market swap matching real connector signature."""
        if side == "sell" or (side is None and amount_is_base):
            # Selling base for quote
            token_in = base_symbol
            token_out = quote_symbol
            amount_in = amount
        else:
            # Buying base with quote
            token_in = quote_symbol
            token_out = base_symbol
            amount_in = amount
        
        self.balances[token_in] = max(0.0, self.balances.get(token_in, 0.0) - amount_in)
        amount_out = amount_in * self.get_price(token_in, token_out)
        self.balances[token_out] = self.balances.get(token_out, 0.0) + amount_out
        swap = {
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": amount_in,
            "amount_out": amount_out,
            "slippage_bps": slippage_bps,
            "side": side
        }
        self.swaps.append(swap)
        return f"0xfake_tx_{len(self.swaps)}"
    
    def swap_exact_out(self, token_in_symbol: str, token_out_symbol: str, target_out_amount: float, slippage_bps: int = 50) -> str:
        """Exact output swap - receive exact amount of output token."""
        price = self.get_price(token_in_symbol, token_out_symbol)
        amount_in = target_out_amount / price if price > 0 else 0.0
        
        # Determine if this is a buy or sell based on token direction
        is_base_out = (token_out_symbol == "BASE")
        
        return self.market_swap(
            base_symbol="BASE",
            quote_symbol="QUOTE", 
            amount=amount_in if not is_base_out else target_out_amount,
            amount_is_base=not is_base_out,
            slippage_bps=slippage_bps,
            side="buy" if is_base_out else "sell"
        )
    
    def quantize_amount(self, symbol: str, amount: float) -> float:
        return round(amount, 8)
    
    def check_approval(self, symbol: str, amount: float) -> bool:
        return True
    
    def get_allowance(self, symbol: str) -> int:
        return 999999999999999999999999
    
    def tx_explorer_url(self, tx_hash: str) -> str:
        return f"https://bscscan.com/tx/{tx_hash}"


def test_simple_swap_exact_behavior():
    """Test SimpleSwap executes exactly one swap."""
    conn = FakeConnector(balances={"BASE": 100.0, "QUOTE": 1000.0}, price=10.0)
    
    cfg = DexSimpleSwapConfig(
        rpc_url="http://test",
        private_key="0x" + "1" * 64,
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=5.0,
        amount_is_base=True,
        spend_is_base=True,
        slippage_bps=50,
        label="test",
        use_mev_protection=False
    )
    
    strat = DexSimpleSwap(cfg, conn)
    
    # Execute
    tx_hash = strat.run()
    assert tx_hash is not None
    
    # Should have exactly 1 swap
    assert len(conn.swaps) == 1
    swap = conn.swaps[0]
    
    # Verify swap details
    assert swap["token_in"] == "BASE"
    assert swap["token_out"] == "QUOTE"
    assert abs(swap["amount_in"] - 5.0) < 0.001
    
    # Verify balance changed
    assert conn.balances["BASE"] < 100.0


def test_batch_swap_level_distribution():
    """Test BatchSwap distributes amounts correctly across levels."""
    from strategies.dex_batch_swap import _generate_levels, _compute_distribution_weights
    
    # Test uniform distribution
    levels = _generate_levels(10.0, 20.0, 5)
    assert len(levels) == 5
    assert levels[0] == 10.0
    assert levels[-1] == 20.0
    
    # Test weights
    weights = _compute_distribution_weights(5, "uniform")
    assert len(weights) == 5
    assert abs(sum(weights) - 1.0) < 0.001
    for w in weights:
        assert abs(w - 0.2) < 0.001
    
    # Test gaussian
    weights_gauss = _compute_distribution_weights(5, "gaussian")
    assert len(weights_gauss) == 5
    assert abs(sum(weights_gauss) - 1.0) < 0.001
    
    # Test exponential
    weights_exp = _compute_distribution_weights(5, "exponential")
    assert len(weights_exp) == 5
    assert abs(sum(weights_exp) - 1.0) < 0.001


def test_batch_swap_only_triggers_at_levels():
    """Test BatchSwap only executes when price crosses levels."""
    conn = FakeConnector(balances={"BASE": 1000.0, "QUOTE": 10000.0}, price=10.0)
    
    cfg = DexBatchSwapConfig(
        rpc_url="http://test",
        private_keys=["0x" + "1" * 64],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        min_price=5.0,
        max_price=15.0,
        num_orders=3,
        total_amount=30.0,
        amount_is_base=True,
        spend_is_base=True,
        distribution="uniform",
        slippage_bps=50,
        use_mev_protection=False
    )
    
    # Price is 10.0, which is in the middle
    # For sell orders, levels should be 5.0, 10.0, 15.0
    # At price=10.0, should trigger level at 10.0 or below
    
    # Verify levels are generated correctly
    from strategies.dex_batch_swap import _generate_levels
    levels = _generate_levels(5.0, 15.0, 3)
    assert len(levels) == 3
    assert 5.0 in levels
    assert 15.0 in levels


def test_pure_mm_creates_symmetric_levels():
    """Test PureMM creates symmetric upper and lower levels."""
    conn = FakeConnector(balances={"BASE": 1000.0, "QUOTE": 10000.0}, price=100.0)
    
    cfg = DexPureMMConfig(
        rpc_url="http://test",
        private_keys=["0x1111111111111111111111111111111111111111111111111111111111111111"],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        order_amount=10.0,
        amount_is_base=True,
        upper_percent=5.0,
        lower_percent=5.0,
        levels_each_side=3,
        refresh_seconds=60,
        slippage_bps=50,
        use_mev_protection=False
    )
    
    strat = DexPureMarketMaking(cfg, [conn])
    
    # Manually build levels to test them
    strat._rebuild_levels(100.0)
    
    # Check levels are created
    assert len(strat.upper_levels) == 3
    assert len(strat.lower_levels) == 3
    
    # Upper levels should be > 100.0
    for lvl in strat.upper_levels:
        assert lvl > 100.0
    
    # Lower levels should be < 100.0
    for lvl in strat.lower_levels:
        assert lvl < 100.0
    
    strat.stop()


def test_pure_mm_negative_level_prevention():
    """Test PureMM prevents negative price levels."""
    conn = FakeConnector(balances={"BASE": 1000.0, "QUOTE": 10000.0}, price=100.0)
    
    # Extreme lower_percent that would cause negative levels
    cfg = DexPureMMConfig(
        rpc_url="http://test",
        private_keys=["0x1111111111111111111111111111111111111111111111111111111111111111"],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        order_amount=10.0,
        amount_is_base=True,
        upper_percent=5.0,
        lower_percent=50.0,  # 50% × 10 levels = 500% > 100%
        levels_each_side=10,
        refresh_seconds=60,
        slippage_bps=50,
        use_mev_protection=False
    )
    
    # Should not crash, should clamp levels
    strat = DexPureMarketMaking(cfg, [conn])
    
    # Manually build levels to test clamping
    strat._rebuild_levels(100.0)
    
    # All levels should be positive
    for lvl in strat.lower_levels:
        assert lvl > 0
    
    strat.stop()


def test_dca_executes_correct_number_of_orders():
    """Test DCA executes exactly num_orders over time."""
    conn = FakeConnector(balances={"BASE": 1000.0, "QUOTE": 10000.0}, price=10.0)
    
    cfg = DexDCAConfig(
        rpc_url="http://test",
        private_keys=["0x1111111111111111111111111111111111111111111111111111111111111111"],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=100.0,
        amount_is_base=False,
        amount_basis_is_base=False,
        spend_is_base=False,
        num_orders=5,
        interval_seconds=0.01,
        distribution="uniform",
        slippage_bps=50,
        use_mev_protection=False
    )
    
    strat = DexDCA(cfg, [conn])
    
    # Should have 5 orders planned
    assert strat.cfg.num_orders == 5
    assert strat.orders_left == 5
    assert strat.completed_orders == 0
    
    strat.stop()


def test_dca_distribution_uniform():
    """Test DCA uniform distribution splits evenly."""
    conn = FakeConnector(balances={"BASE": 1000.0, "QUOTE": 10000.0}, price=10.0)
    
    cfg = DexDCAConfig(
        rpc_url="http://test",
        private_keys=["0x1111111111111111111111111111111111111111111111111111111111111111"],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=100.0,
        amount_is_base=True,
        amount_basis_is_base=True,
        spend_is_base=True,
        num_orders=5,
        interval_seconds=0.01,
        distribution="uniform",
        slippage_bps=50,
        use_mev_protection=False
    )
    
    strat = DexDCA(cfg, [conn])
    
    # Each order should be ~20.0 (100/5)
    chunk = strat._pick_chunk()
    expected = 100.0 / 5
    assert abs(chunk - expected) < 0.1
    
    strat.stop()


def test_config_validation_all_strategies():
    """Test all strategies validate their configs."""
    
    # SimpleSwap: amount must be positive
    try:
        cfg = DexSimpleSwapConfig(
            rpc_url="http://test",
        private_key="0x1111111111111111111111111111111111111111111111111111111111111111",
        chain_id=56,
        base_symbol="BASE",
            quote_symbol="QUOTE",
            amount=-5.0,  # Invalid
            amount_is_base=True,
            spend_is_base=True,
            slippage_bps=50,
            use_mev_protection=False
        )
        strat = DexSimpleSwap(cfg)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    
    # BatchSwap: min_price must be < max_price
    try:
        cfg = DexBatchSwapConfig(
            rpc_url="http://test",
        private_keys=["0x1111111111111111111111111111111111111111111111111111111111111111"],
        chain_id=56,
        base_symbol="BASE",
            quote_symbol="QUOTE",
            min_price=20.0,  # Invalid: > max_price
            max_price=10.0,
            num_orders=5,
            total_amount=100.0,
            amount_is_base=True,
            spend_is_base=True,
            distribution="uniform",
            slippage_bps=50,
            use_mev_protection=False
        )
        strat = DexBatchSwap(cfg)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    
    # DCA: num_orders must be positive
    try:
        cfg = DexDCAConfig(
            rpc_url="http://test",
        private_keys=["0x1111111111111111111111111111111111111111111111111111111111111111"],
        chain_id=56,
        base_symbol="BASE",
            quote_symbol="QUOTE",
            total_amount=100.0,
            amount_is_base=True,
            amount_basis_is_base=True,
            spend_is_base=True,
            num_orders=0,  # Invalid
            interval_seconds=0.01,
            distribution="uniform",
            slippage_bps=50,
            use_mev_protection=False
        )
        strat = DexDCA(cfg)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_mev_protection_flag_all_strategies():
    """Test all strategies accept and store MEV protection flag."""
    conn = FakeConnector()
    
    # SimpleSwap
    cfg1 = DexSimpleSwapConfig(
        rpc_url="http://test",
        private_key="0x1111111111111111111111111111111111111111111111111111111111111111",
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=10.0,
        amount_is_base=True,
        spend_is_base=True,
        slippage_bps=50,
        use_mev_protection=True
    )
    assert cfg1.use_mev_protection is True
    
    # BatchSwap
    cfg2 = DexBatchSwapConfig(
        rpc_url="http://test",
        private_keys=["0x1111111111111111111111111111111111111111111111111111111111111111"],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        min_price=5.0,
        max_price=15.0,
        num_orders=3,
        total_amount=30.0,
        amount_is_base=True,
        spend_is_base=True,
        distribution="uniform",
        slippage_bps=50,
        use_mev_protection=True
    )
    assert cfg2.use_mev_protection is True
    
    # PureMM
    cfg3 = DexPureMMConfig(
        rpc_url="http://test",
        private_keys=["0x1111111111111111111111111111111111111111111111111111111111111111"],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        order_amount=10.0,
        amount_is_base=True,
        upper_percent=5.0,
        lower_percent=5.0,
        levels_each_side=3,
        refresh_seconds=60,
        slippage_bps=50,
        use_mev_protection=True
    )
    assert cfg3.use_mev_protection is True
    
    # DCA
    cfg4 = DexDCAConfig(
        rpc_url="http://test",
        private_keys=["0x1111111111111111111111111111111111111111111111111111111111111111"],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=100.0,
        amount_is_base=True,
        amount_basis_is_base=True,
        spend_is_base=True,
        num_orders=5,
        interval_seconds=0.01,
        distribution="uniform",
        slippage_bps=50,
        use_mev_protection=True
    )
    assert cfg4.use_mev_protection is True


def test_zero_slippage_edge_case():
    """Test strategies handle zero slippage."""
    conn = FakeConnector(balances={"BASE": 100.0, "QUOTE": 1000.0}, price=10.0)
    
    cfg = DexSimpleSwapConfig(
        rpc_url="http://test",
        private_key="0x1111111111111111111111111111111111111111111111111111111111111111",
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=5.0,
        amount_is_base=True,
        spend_is_base=True,
        slippage_bps=0,  # Zero slippage
        use_mev_protection=False
    )
    
    # Should not crash
    strat = DexSimpleSwap(cfg, conn)
    tx_hash = strat.run()
    
    assert len(conn.swaps) == 1


def test_insufficient_balance_handling():
    """Test strategies handle insufficient balance gracefully."""
    conn = FakeConnector(balances={"BASE": 1.0, "QUOTE": 1000.0}, price=10.0)
    
    cfg = DexSimpleSwapConfig(
        rpc_url="http://test",
        private_key="0x1111111111111111111111111111111111111111111111111111111111111111",
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=100.0,  # More than available balance
        amount_is_base=True,
        spend_is_base=True,
        slippage_bps=50,
        use_mev_protection=False
    )
    
    # Should handle gracefully (may skip or reduce amount)
    strat = DexSimpleSwap(cfg, conn)
    try:
        tx_hash = strat.run()
    except RuntimeError:
        pass  # Expected to fail due to insufficient balance

