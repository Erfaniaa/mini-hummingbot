"""
Comprehensive strategy tests for all trading strategies.

This file contains integration tests for:
- DexSimpleSwap: Single market swap execution
- DexBatchSwap: Ladder of price-triggered orders
- DexPureMarketMaking: Symmetric market making around mid-price  
- DexDCA: Dollar-cost averaging with periodic execution

Note: This file is large (798 lines). Consider splitting into separate
files per strategy if it grows significantly larger or becomes hard to maintain.
"""
from __future__ import annotations

from dataclasses import dataclass

from strategies.dex_simple_swap import DexSimpleSwap, DexSimpleSwapConfig
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig
from strategies.dex_pure_market_making import DexPureMarketMaking, DexPureMMConfig
from strategies.dex_dca import DexDCA, DexDCAConfig


class FakeWeb3Client:
    """Fake Web3 client for testing"""
    def __init__(self):
        pass
    
    def get_transaction_count(self, address):
        """Return nonce for address"""
        return 1
    
    def to_wei(self, token_address_or_amount, amount_or_unit='ether'):
        """
        Convert to wei - handles both formats:
        1. to_wei(token_address, amount) - for ERC20 tokens
        2. to_wei(amount, 'ether') - for ETH
        """
        # If first arg is a dict (token info from _resolve), second arg is the amount
        if isinstance(token_address_or_amount, dict):
            amount = amount_or_unit
            decimals = token_address_or_amount.get('decimals', 18)
            return int(amount * 10**decimals)
        # Otherwise, standard web3 to_wei conversion
        else:
            amount = token_address_or_amount
            if amount_or_unit == 'ether':
                return int(amount * 10**18)
            return int(amount)
    
    def from_wei(self, token_or_wei, wei_or_unit=None):
        """
        Convert from wei - handles both formats:
        1. from_wei(token_address, wei_amount) - for ERC20 tokens (used in validation)
        2. from_wei(wei_amount, 'ether') - for ETH (standard web3)
        """
        if isinstance(token_or_wei, dict):
            # Format: from_wei(token_address, wei_amount)
            token_address = token_or_wei
            wei_amount = wei_or_unit
            decimals = token_address.get('decimals', 18)
            return wei_amount / 10**decimals
        else:
            # Format: from_wei(wei_amount, 'ether')
            wei_amount = token_or_wei
            unit = wei_or_unit or 'ether'
            if unit == 'ether':
                return wei_amount / 10**18
            return wei_amount


class FakeConnector:
    """
    Realistic fake connector for testing strategies.
    Simulates:
    - Balance tracking
    - Price with spread
    - Swap execution with side effects
    - Token resolution and validation
    """
    def __init__(self, base_balance=100.0, quote_balance=100.0, price=2.0):
        self._balances = {"BASE": base_balance, "QUOTE": quote_balance}
        self._txs = []
        self.chain_id = 56
        self._price = price  # price in BASE/QUOTE
        self._tokens = {
            "BASE": {"symbol": "BASE", "address": "0xBASE", "decimals": 18},
            "QUOTE": {"symbol": "QUOTE", "address": "0xQUOTE", "decimals": 18},
        }
        self.client = FakeWeb3Client()  # Add Web3 client for validation

    def _resolve(self, symbol):
        """Resolve token symbol to token info"""
        if symbol in self._tokens:
            return self._tokens[symbol]
        return {"symbol": symbol, "address": f"0x{symbol}", "decimals": 18}

    def get_price(self, base_symbol, quote_symbol):
        """Return current market price"""
        # Allow price to be a callable for dynamic prices
        if callable(self._price):
            return self._price()
        return self._price

    def get_price_fast(self, base_symbol, quote_symbol):
        """Return fast price (same as regular price for testing)"""
        if callable(self._price):
            return self._price()
        return self._price

    def get_price_side(self, base_symbol, quote_symbol, side='buy', fast=True):
        """Return price with side consideration"""
        if callable(self._price):
            return self._price()
        return self._price

    def get_balance(self, symbol):
        """Get balance for a token"""
        return self._balances.get(symbol, 0.0)

    def approve(self, symbol, amount):
        """Mock approve - always succeeds"""
        return f"0xapprove_{symbol}"

    def check_approval(self, symbol, amount):
        """Check if approval is needed - always returns False (already approved)"""
        return False

    def get_allowance(self, symbol):
        """Get current allowance - always returns a very large number (unlimited approval)"""
        return 10**36  # Very large number in wei to simulate unlimited approval

    def swap_exact_out(self, token_in_symbol, token_out_symbol, target_out_amount, 
                      max_in_amount, slippage_bps=50, **kwargs):
        """
        Execute exact-output swap (specify exact output, variable input).
        Compatible with actual connector signature.
        """
        tx = f"0xswap_exact_out{len(self._txs)}"
        self._txs.append(tx)
        
        # Determine which is base and which is quote
        if token_out_symbol == "BASE":
            # Buying BASE (output is BASE)
            base_received = target_out_amount
            quote_spent = base_received / self._price
            self._balances["BASE"] += base_received
            self._balances["QUOTE"] -= quote_spent
        else:
            # Selling BASE for QUOTE (output is QUOTE)
            quote_received = target_out_amount
            base_spent = quote_received * self._price
            self._balances["QUOTE"] += quote_received
            self._balances["BASE"] -= base_spent
        
        return tx

    def market_swap(self, base_symbol, quote_symbol, amount, amount_is_base, slippage_bps=50, side=None):
        """
        Execute swap and update balances.
        
        Args:
            base_symbol: Base token symbol
            quote_symbol: Quote token symbol
            amount: Amount to swap
            amount_is_base: If True, amount is in base; else in quote
            slippage_bps: Allowed slippage in basis points
            side: 'buy' or 'sell' (from base perspective)
        
        Returns:
            Transaction hash
        """
        tx = f"0xswap{len(self._txs)}"
        self._txs.append(tx)
        
        # Determine actual swap amounts based on side and amount basis
        if side == 'buy':
            # Buying base with quote
            if amount_is_base:
                # Amount is target base to receive
                base_received = amount
                quote_spent = base_received / self._price
            else:
                # Amount is quote to spend
                quote_spent = amount
                base_received = quote_spent * self._price
            
            self._balances["QUOTE"] -= quote_spent
            self._balances["BASE"] += base_received
            
        elif side == 'sell':
            # Selling base for quote
            if amount_is_base:
                # Amount is base to sell
                base_spent = amount
                quote_received = base_spent / self._price
            else:
                # Amount is target quote to receive
                quote_received = amount
                base_spent = quote_received * self._price
            
            self._balances["BASE"] -= base_spent
            self._balances["QUOTE"] += quote_received
        else:
            # Legacy: no side specified, use amount_is_base
            if amount_is_base:
                self._balances["BASE"] -= amount
                self._balances["QUOTE"] += amount / self._price
            else:
                self._balances["QUOTE"] -= amount
                self._balances["BASE"] += amount * self._price
        
        return tx

    def tx_explorer_url(self, tx_hash):
        """Return explorer URL for transaction"""
        return f"https://bscscan.com/tx/{tx_hash}"


def test_dex_simple_swap_sell_base_exact_amount():
    """Test selling exact amount of BASE for QUOTE"""
    fake = FakeConnector(base_balance=10.0, quote_balance=50.0, price=2.0)
    cfg = DexSimpleSwapConfig(
        rpc_url="",
        private_key="",
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=5.0,
        amount_is_base=True,
        spend_is_base=True,  # Sell BASE
        amount_basis_is_base=True,  # Amount is in BASE
    )
    strat = DexSimpleSwap(cfg, connector=fake)  # type: ignore[arg-type]
    
    initial_base = fake.get_balance("BASE")
    initial_quote = fake.get_balance("QUOTE")
    
    tx = strat.run()
    
    assert tx.startswith("0xswap"), "Transaction hash should start with 0xswap"
    assert fake.get_balance("BASE") < initial_base, "BASE balance should decrease"
    assert fake.get_balance("QUOTE") > initial_quote, "QUOTE balance should increase"


def test_dex_simple_swap_buy_base_with_quote():
    """Test buying BASE with exact amount of QUOTE"""
    fake = FakeConnector(base_balance=10.0, quote_balance=50.0, price=2.0)
    cfg = DexSimpleSwapConfig(
        rpc_url="",
        private_key="",
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=10.0,
        amount_is_base=False,
        spend_is_base=False,  # Buy BASE (spend QUOTE)
        amount_basis_is_base=False,  # Amount is in QUOTE
    )
    strat = DexSimpleSwap(cfg, connector=fake)  # type: ignore[arg-type]
    
    initial_base = fake.get_balance("BASE")
    initial_quote = fake.get_balance("QUOTE")
    
    tx = strat.run()
    
    assert tx.startswith("0xswap"), "Transaction hash should start with 0xswap"
    assert fake.get_balance("BASE") > initial_base, "BASE balance should increase"
    assert fake.get_balance("QUOTE") < initial_quote, "QUOTE balance should decrease"


def test_dex_simple_swap_sell_base_target_quote():
    """Test selling BASE to receive exact amount of QUOTE"""
    fake = FakeConnector(base_balance=100.0, quote_balance=50.0, price=2.0)
    cfg = DexSimpleSwapConfig(
        rpc_url="",
        private_key="",
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=20.0,
        amount_is_base=False,
        spend_is_base=True,  # Sell BASE
        amount_basis_is_base=False,  # Amount is target QUOTE
    )
    strat = DexSimpleSwap(cfg, connector=fake)  # type: ignore[arg-type]
    
    initial_base = fake.get_balance("BASE")
    
    tx = strat.run()
    
    assert tx.startswith("0xswap"), "Transaction hash should start with 0xswap"
    assert fake.get_balance("BASE") < initial_base, "BASE should be spent"


def test_dex_simple_swap_buy_base_target_amount():
    """Test buying exact amount of BASE with QUOTE"""
    fake = FakeConnector(base_balance=10.0, quote_balance=100.0, price=2.0)
    cfg = DexSimpleSwapConfig(
        rpc_url="",
        private_key="",
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=5.0,
        amount_is_base=True,
        spend_is_base=False,  # Buy BASE
        amount_basis_is_base=True,  # Amount is target BASE
    )
    strat = DexSimpleSwap(cfg, connector=fake)  # type: ignore[arg-type]
    
    initial_quote = fake.get_balance("QUOTE")
    
    tx = strat.run()
    
    assert tx.startswith("0xswap"), "Transaction hash should start with 0xswap"
    assert fake.get_balance("QUOTE") < initial_quote, "QUOTE should be spent"


def test_dex_simple_swap_with_different_slippage():
    """Test that different slippage values are accepted"""
    fake = FakeConnector(base_balance=10.0, quote_balance=50.0, price=2.0)
    
    for slippage in [10, 50, 100, 500]:
        cfg = DexSimpleSwapConfig(
            rpc_url="",
            private_key="",
            chain_id=56,
            base_symbol="BASE",
            quote_symbol="QUOTE",
            amount=1.0,
            amount_is_base=True,
            spend_is_base=True,
            slippage_bps=slippage,
        )
        strat = DexSimpleSwap(cfg, connector=fake)  # type: ignore[arg-type]
        tx = strat.run()
        assert tx.startswith("0xswap"), f"Slippage {slippage} should work"


def test_dex_batch_swap_uniform_distribution_sell():
    """Test batch swap with uniform distribution selling BASE"""
    fake = FakeConnector(base_balance=100.0, quote_balance=50.0, price=2.0)
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=10.0,
        amount_is_base=True,
        min_price=1.8,
        max_price=2.2,
        num_orders=5,
        distribution="uniform",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=True,
    )
    strat = DexBatchSwap(cfg, connectors=[fake])  # type: ignore[arg-type]
    
    initial_base = fake.get_balance("BASE")
    
    # Execute multiple ticks to place orders
    for _ in range(5):
        strat._on_tick()
    
    assert len(fake._txs) >= 1, "Should have placed at least one order"
    assert fake.get_balance("BASE") < initial_base, "BASE should decrease"


def test_dex_batch_swap_bell_distribution_buy():
    """Test batch swap with bell distribution buying BASE"""
    fake = FakeConnector(base_balance=10.0, quote_balance=100.0, price=2.0)
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=20.0,
        amount_is_base=False,
        min_price=1.8,
        max_price=2.2,
        num_orders=4,
        distribution="bell",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=False,
    )
    strat = DexBatchSwap(cfg, connectors=[fake])  # type: ignore[arg-type]
    
    initial_quote = fake.get_balance("QUOTE")
    
    # Execute multiple ticks
    for _ in range(4):
        strat._on_tick()
    
    assert len(fake._txs) >= 1, "Should have placed at least one order"
    assert fake.get_balance("QUOTE") < initial_quote, "QUOTE should decrease"


def test_dex_batch_swap_single_order():
    """Test batch swap with just one order"""
    fake = FakeConnector(base_balance=50.0, quote_balance=50.0, price=2.0)
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=5.0,
        amount_is_base=True,
        min_price=2.0,
        max_price=2.0,
        num_orders=1,
        distribution="uniform",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=True,
    )
    strat = DexBatchSwap(cfg, connectors=[fake])  # type: ignore[arg-type]
    
    strat._on_tick()
    
    assert len(fake._txs) == 1, "Should place exactly one order"


def test_dex_batch_swap_multi_wallet():
    """Test batch swap with multiple wallets"""
    fake1 = FakeConnector(base_balance=50.0, quote_balance=50.0, price=2.0)
    fake2 = FakeConnector(base_balance=50.0, quote_balance=50.0, price=2.0)
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=["key1", "key2"],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=10.0,
        amount_is_base=True,
        min_price=1.8,
        max_price=2.2,
        num_orders=4,
        distribution="uniform",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=True,
    )
    strat = DexBatchSwap(cfg, connectors=[fake1, fake2])  # type: ignore[arg-type]
    
    # Execute ticks
    for _ in range(4):
        strat._on_tick()
    
    total_txs = len(fake1._txs) + len(fake2._txs)
    assert total_txs >= 1, "Should have placed orders across wallets"


def test_dex_batch_swap_varying_num_orders():
    """Test batch swap with different number of orders"""
    for num_orders in [1, 3, 5, 10]:
        fake = FakeConnector(base_balance=100.0, quote_balance=100.0, price=2.0)
        cfg = DexBatchSwapConfig(
            rpc_url="",
            private_keys=[""],
            chain_id=56,
            base_symbol="BASE",
            quote_symbol="QUOTE",
            total_amount=10.0,
            amount_is_base=True,
            min_price=1.5,
            max_price=2.5,
            num_orders=num_orders,
            distribution="uniform",
            interval_seconds=0.01,
            slippage_bps=50,
            spend_is_base=True,
        )
        strat = DexBatchSwap(cfg, connectors=[fake])  # type: ignore[arg-type]
        
        for _ in range(num_orders):
            strat._on_tick()
        
        assert len(fake._txs) >= 1, f"Should work with {num_orders} orders"


def test_dex_pure_mm_single_level_each_side():
    """Test pure MM with one level on each side - price triggers upper level"""
    price_ref = [2.0]
    fake = FakeConnector(base_balance=100.0, quote_balance=100.0, price=lambda: price_ref[0])
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        upper_percent=5.0,
        lower_percent=5.0,
        levels_each_side=1,
        order_amount=5.0,
        amount_is_base=True,
        refresh_seconds=9999,
        slippage_bps=50,
        tick_interval_seconds=0.01,
    )
    strat = DexPureMarketMaking(cfg, connectors=[fake])  # type: ignore[arg-type]
    
    # First tick: levels are built but no orders yet (price is mid-level)
    strat._on_tick()
    initial_txs = len(fake._txs)
    
    # Change price to trigger upper level (sell)
    price_ref[0] = 2.11  # Above upper level (2.0 * 1.05 = 2.1)
    strat._on_tick()
    
    # Should have placed a sell order
    assert len(fake._txs) > initial_txs, "Should place sell order when price hits upper level"


def test_dex_pure_mm_multiple_levels():
    """Test pure MM with multiple levels - triggers different levels"""
    # Use a list to make price mutable and shared
    price_ref = [2.0]
    fake = FakeConnector(base_balance=100.0, quote_balance=100.0, price=lambda: price_ref[0])
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        upper_percent=10.0,
        lower_percent=10.0,
        levels_each_side=3,
        order_amount=2.0,
        amount_is_base=True,
        refresh_seconds=9999,
        slippage_bps=50,
        tick_interval_seconds=0.01,
    )
    strat = DexPureMarketMaking(cfg, connectors=[fake])  # type: ignore[arg-type]
    
    # Build levels
    strat._on_tick()
    
    # Trigger lower level (buy) - level is at 2.0 * 0.9 = 1.8
    price_ref[0] = 1.79  # Below 1.8
    strat._on_tick()
    assert len(fake._txs) >= 1, "Should place buy order"
    
    # Trigger upper level (sell) - level is at 2.0 * 1.1 = 2.2
    price_ref[0] = 2.21  # Above 2.2
    strat._on_tick()
    assert len(fake._txs) >= 2, "Should place sell order too"


def test_dex_pure_mm_asymmetric_spreads():
    """Test pure MM with asymmetric spreads - tighter lower, wider upper"""
    price_ref = [2.0]
    fake = FakeConnector(base_balance=100.0, quote_balance=100.0, price=lambda: price_ref[0])
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        upper_percent=15.0,  # Wider spread above
        lower_percent=5.0,   # Tighter spread below
        levels_each_side=2,
        order_amount=3.0,
        amount_is_base=True,
        refresh_seconds=9999,
        slippage_bps=50,
        tick_interval_seconds=0.01,
    )
    strat = DexPureMarketMaking(cfg, connectors=[fake])  # type: ignore[arg-type]
    
    strat._on_tick()
    
    # Price drops to trigger lower level - level is at 2.0 * 0.95 = 1.9
    price_ref[0] = 1.89  # Below 1.9
    strat._on_tick()
    assert len(fake._txs) >= 1, "Should trigger lower level with tighter spread"


def test_dex_pure_mm_quote_denominated():
    """Test pure MM with quote-denominated order amounts"""
    price_ref = [2.0]
    fake = FakeConnector(base_balance=100.0, quote_balance=100.0, price=lambda: price_ref[0])
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
        amount_is_base=False,  # Quote-denominated
        refresh_seconds=9999,
        slippage_bps=50,
        tick_interval_seconds=0.01,
    )
    strat = DexPureMarketMaking(cfg, connectors=[fake])  # type: ignore[arg-type]
    
    strat._on_tick()
    
    # Price rises to trigger upper level - level is at 2.0 * 1.05 = 2.1
    price_ref[0] = 2.11  # Above 2.1
    strat._on_tick()
    assert len(fake._txs) >= 1, "Should work with quote-denominated amounts"


def test_dex_pure_mm_multi_wallet():
    """Test pure MM with multiple wallets - each wallet independently"""
    # Shared price reference
    price_ref = [2.0]
    fake1 = FakeConnector(base_balance=100.0, quote_balance=100.0, price=lambda: price_ref[0])
    fake2 = FakeConnector(base_balance=100.0, quote_balance=100.0, price=lambda: price_ref[0])
    
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=["key1", "key2"],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        upper_percent=5.0,
        lower_percent=5.0,
        levels_each_side=2,
        order_amount=5.0,
        amount_is_base=True,
        refresh_seconds=9999,
        slippage_bps=50,
        tick_interval_seconds=0.01,
    )
    strat = DexPureMarketMaking(cfg, connectors=[fake1, fake2])  # type: ignore[arg-type]
    
    strat._on_tick()
    
    # Change shared price to trigger a level - level at 2.0 * 0.95 = 1.9
    price_ref[0] = 1.89  # Below 1.9
    strat._on_tick()
    
    total_txs = len(fake1._txs) + len(fake2._txs)
    assert total_txs >= 1, "Should place orders when price triggers level"


def test_dex_dca_uniform_distribution_sell():
    """Test DCA with uniform distribution selling BASE"""
    fake = FakeConnector(base_balance=100.0, quote_balance=50.0, price=2.0)
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=20.0,
        amount_is_base=True,
        interval_seconds=0.01,
        num_orders=5,
        distribution="uniform",
        slippage_bps=50,
        spend_is_base=True,
    )
    strat = DexDCA(cfg, connectors=[fake])  # type: ignore[arg-type]
    
    initial_base = fake.get_balance("BASE")
    
    # Execute multiple ticks
    for _ in range(5):
        strat._on_tick()
    
    assert len(fake._txs) >= 1, "Should place at least one order"
    assert fake.get_balance("BASE") < initial_base, "BASE should decrease"


def test_dex_dca_random_uniform_distribution_buy():
    """Test DCA with random_uniform distribution buying BASE"""
    fake = FakeConnector(base_balance=10.0, quote_balance=100.0, price=2.0)
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=30.0,
        amount_is_base=False,
        interval_seconds=0.01,
        num_orders=4,
        distribution="random_uniform",
        slippage_bps=50,
        spend_is_base=False,
    )
    strat = DexDCA(cfg, connectors=[fake])  # type: ignore[arg-type]
    
    initial_quote = fake.get_balance("QUOTE")
    
    # Execute multiple ticks
    for _ in range(4):
        strat._on_tick()
    
    assert len(fake._txs) >= 1, "Should place at least one order"
    assert fake.get_balance("QUOTE") < initial_quote, "QUOTE should decrease"


def test_dex_dca_single_order():
    """Test DCA with just one order"""
    fake = FakeConnector(base_balance=50.0, quote_balance=50.0, price=2.0)
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=5.0,
        amount_is_base=True,
        interval_seconds=0.01,
        num_orders=1,
        distribution="uniform",
        slippage_bps=50,
        spend_is_base=True,
    )
    strat = DexDCA(cfg, connectors=[fake])  # type: ignore[arg-type]
    
    strat._on_tick()
    
    assert len(fake._txs) == 1, "Should place exactly one order"


def test_dex_dca_multi_wallet():
    """Test DCA with multiple wallets"""
    fake1 = FakeConnector(base_balance=50.0, quote_balance=50.0, price=2.0)
    fake2 = FakeConnector(base_balance=50.0, quote_balance=50.0, price=2.0)
    
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=["key1", "key2"],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=10.0,
        amount_is_base=True,
        interval_seconds=0.01,
        num_orders=4,
        distribution="uniform",
        slippage_bps=50,
        spend_is_base=True,
    )
    strat = DexDCA(cfg, connectors=[fake1, fake2])  # type: ignore[arg-type]
    
    # Execute ticks
    for _ in range(4):
        strat._on_tick()
    
    total_txs = len(fake1._txs) + len(fake2._txs)
    assert total_txs >= 1, "Should place orders across wallets"


def test_dex_dca_varying_intervals():
    """Test DCA with different intervals"""
    for num_orders in [1, 3, 5, 8]:
        fake = FakeConnector(base_balance=100.0, quote_balance=100.0, price=2.0)
        cfg = DexDCAConfig(
            rpc_url="",
            private_keys=[""],
            chain_id=56,
            base_symbol="BASE",
            quote_symbol="QUOTE",
            total_amount=10.0,
            amount_is_base=True,
            interval_seconds=0.01,
            num_orders=num_orders,
            distribution="uniform",
            slippage_bps=50,
            spend_is_base=True,
        )
        strat = DexDCA(cfg, connectors=[fake])  # type: ignore[arg-type]
        
        for _ in range(num_orders):
            strat._on_tick()
        
        assert len(fake._txs) >= 1, f"Should work with {num_orders} orders"


def test_dex_dca_quote_denominated():
    """Test DCA with quote-denominated amounts"""
    fake = FakeConnector(base_balance=100.0, quote_balance=100.0, price=2.0)
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=20.0,
        amount_is_base=False,  # Quote-denominated
        interval_seconds=0.01,
        num_orders=3,
        distribution="uniform",
        slippage_bps=50,
        spend_is_base=False,
    )
    strat = DexDCA(cfg, connectors=[fake])  # type: ignore[arg-type]
    
    initial_quote = fake.get_balance("QUOTE")
    
    for _ in range(3):
        strat._on_tick()
    
    assert len(fake._txs) >= 1, "Should work with quote-denominated amounts"
    assert fake.get_balance("QUOTE") < initial_quote, "QUOTE should decrease when buying"
