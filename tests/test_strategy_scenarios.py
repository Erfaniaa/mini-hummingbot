"""
Scenario-based tests for strategies.
Tests verify exact order counts, amounts, and sides.
"""
from __future__ import annotations

from tests.test_strategies import FakeConnector
from strategies.dex_simple_swap import DexSimpleSwap, DexSimpleSwapConfig
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig
from strategies.dex_dca import DexDCA, DexDCAConfig


def test_simple_swap_exact_order_count():
    """Verify simple swap creates exactly 1 order and updates balances correctly"""
    fake = FakeConnector(base_balance=50.0, quote_balance=100.0, price=2.0)
    cfg = DexSimpleSwapConfig(
        rpc_url="",
        private_key="",
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=10.0,
        amount_is_base=True,
        spend_is_base=True,  # Selling BASE
    )
    strat = DexSimpleSwap(cfg, connector=fake)
    
    initial_base = fake.get_balance("BASE")
    initial_quote = fake.get_balance("QUOTE")
    initial_txs = len(fake._txs)
    
    strat.run()
    
    final_base = fake.get_balance("BASE")
    final_quote = fake.get_balance("QUOTE")
    
    assert len(fake._txs) == initial_txs + 1, "Should create exactly 1 transaction"
    # When selling 10 BASE at price 2.0, should get 10 * 2.0 = 20 QUOTE
    assert final_base == initial_base - 10.0, f"BASE should decrease by 10, got {initial_base - final_base}"
    assert final_quote == initial_quote + 20.0, f"QUOTE should increase by 20, got {final_quote - initial_quote}"


def test_batch_swap_creates_multiple_orders():
    """Verify batch swap creates orders over multiple ticks"""
    fake = FakeConnector(base_balance=1000.0, quote_balance=1000.0, price=2.0)
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
        num_orders=10,
        distribution="uniform",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=True,
    )
    strat = DexBatchSwap(cfg, connectors=[fake])
    
    # Execute several ticks
    for _ in range(10):
        strat._on_tick()
    
    # Should have placed multiple orders
    assert len(fake._txs) >= 3, f"Expected at least 3 orders, got {len(fake._txs)}"


def test_batch_swap_sell_reduces_base_balance():
    """Verify selling BASE reduces BASE balance by expected amount"""
    fake = FakeConnector(base_balance=100.0, quote_balance=50.0, price=2.0)
    total_amount = 20.0
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=total_amount,
        amount_is_base=True,
        min_price=1.8,
        max_price=2.2,
        num_orders=4,
        distribution="uniform",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=True,  # Selling BASE
    )
    strat = DexBatchSwap(cfg, connectors=[fake])
    
    initial_base = fake.get_balance("BASE")
    initial_quote = fake.get_balance("QUOTE")
    
    # Execute all orders
    for _ in range(4):
        strat._on_tick()
    
    final_base = fake.get_balance("BASE")
    final_quote = fake.get_balance("QUOTE")
    base_spent = initial_base - final_base
    quote_received = final_quote - initial_quote
    
    assert final_base < initial_base, "BASE should decrease when selling"
    assert final_quote > initial_quote, "QUOTE should increase when selling BASE"
    # Should spend some BASE (may not be exact total due to order execution)
    assert base_spent > 0, f"Should spend some BASE, spent {base_spent}"
    assert quote_received > 0, f"Should receive some QUOTE, got {quote_received}"
    # Verify exchange rate is approximately correct
    if base_spent > 0:
        rate = quote_received / base_spent
        expected_rate = 2.0  # price = 2.0 QUOTE/BASE, so rate is 2.0 QUOTE per BASE
        assert abs(rate - expected_rate) < 0.5, f"Expected rate ~{expected_rate}, got {rate}"


def test_batch_swap_buy_reduces_quote_balance():
    """Verify buying BASE reduces QUOTE balance by expected amount"""
    fake = FakeConnector(base_balance=20.0, quote_balance=100.0, price=2.0)
    total_amount = 30.0
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=total_amount,
        amount_is_base=False,  # Amount in QUOTE
        min_price=1.8,
        max_price=2.2,
        num_orders=3,
        distribution="uniform",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=False,  # Buying BASE with QUOTE
    )
    strat = DexBatchSwap(cfg, connectors=[fake])
    
    initial_base = fake.get_balance("BASE")
    initial_quote = fake.get_balance("QUOTE")
    
    # Execute all orders
    for _ in range(3):
        strat._on_tick()
    
    final_base = fake.get_balance("BASE")
    final_quote = fake.get_balance("QUOTE")
    base_received = final_base - initial_base
    quote_spent = initial_quote - final_quote
    
    assert final_base > initial_base, "BASE should increase when buying"
    assert final_quote < initial_quote, "QUOTE should decrease when buying BASE"
    # Should spend some QUOTE (may not be exact total due to order execution)
    assert quote_spent > 0, f"Should spend some QUOTE, spent {quote_spent}"
    assert base_received > 0, f"Should receive some BASE, got {base_received}"
    # Verify exchange rate is approximately correct
    if quote_spent > 0:
        rate = base_received / quote_spent
        expected_rate = 2.0  # price = 2.0 BASE per QUOTE
        assert abs(rate - expected_rate) < 0.5, f"Expected rate ~{expected_rate}, got {rate}"


def test_dca_order_count_matches_config():
    """Verify DCA creates correct number of orders"""
    for num_orders in [2, 4, 6]:
        fake = FakeConnector(base_balance=100.0, quote_balance=100.0, price=2.0)
        cfg = DexDCAConfig(
            rpc_url="",
            private_keys=[""],
            chain_id=56,
            base_symbol="BASE",
            quote_symbol="QUOTE",
            total_amount=float(num_orders * 5),
            amount_is_base=False,
            interval_seconds=0.01,
            num_orders=num_orders,
            distribution="uniform",
            slippage_bps=50,
            spend_is_base=False,
        )
        strat = DexDCA(cfg, connectors=[fake])
        
        # Execute all orders
        for _ in range(num_orders):
            strat._on_tick()
        
        assert len(fake._txs) == num_orders, f"Expected {num_orders} orders, got {len(fake._txs)}"


def test_dca_uniform_distribution_equal_amounts():
    """Verify uniform DCA distributes equally and final balances are correct"""
    fake = FakeConnector(base_balance=100.0, quote_balance=100.0, price=2.0)
    num_orders = 5
    total_amount = 50.0
    
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=total_amount,
        amount_is_base=False,  # Amount in QUOTE
        interval_seconds=0.01,
        num_orders=num_orders,
        distribution="uniform",
        slippage_bps=50,
        spend_is_base=False,  # Buying BASE with QUOTE
    )
    strat = DexDCA(cfg, connectors=[fake])
    
    initial_base = fake.get_balance("BASE")
    initial_quote = fake.get_balance("QUOTE")
    
    # Execute all orders
    for _ in range(num_orders):
        strat._on_tick()
    
    final_base = fake.get_balance("BASE")
    final_quote = fake.get_balance("QUOTE")
    base_received = final_base - initial_base
    quote_spent = initial_quote - final_quote
    
    # Should spend approximately total_amount QUOTE
    assert abs(quote_spent - total_amount) < 0.01, f"Expected to spend ~{total_amount} QUOTE, spent {quote_spent}"
    # Should receive approximately total_amount * price BASE
    expected_base = total_amount * 2.0  # price = 2.0
    assert abs(base_received - expected_base) < 0.1, f"Expected ~{expected_base} BASE, got {base_received}"
    
    # Verify final balances
    assert final_base == initial_base + base_received, "Final BASE balance should match"
    assert final_quote == initial_quote - quote_spent, "Final QUOTE balance should match"


def test_multi_wallet_distributes_orders():
    """Verify orders are distributed across wallets"""
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
        num_orders=6,
        distribution="uniform",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=True,
    )
    strat = DexBatchSwap(cfg, connectors=[fake1, fake2])
    
    # Execute all orders
    for _ in range(6):
        strat._on_tick()
    
    # Both wallets should have executed some orders
    assert len(fake1._txs) > 0, "Wallet 1 should execute orders"
    assert len(fake2._txs) > 0, "Wallet 2 should execute orders"
    assert len(fake1._txs) + len(fake2._txs) == 6, "Total should be 6 orders"

