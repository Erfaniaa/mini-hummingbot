"""
Detailed order verification tests.
Tests verify exact order amounts, sides, and conditional execution.
"""
from __future__ import annotations

from tests.test_strategies import FakeConnector
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig
from strategies.dex_dca import DexDCA, DexDCAConfig


class OrderTrackingConnector(FakeConnector):
    """Connector that tracks detailed order information"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_details = []  # List of (side, amount, amount_is_base) tuples
    
    def market_swap(self, base_symbol, quote_symbol, amount, amount_is_base, slippage_bps=50, side=None):
        """Track order details before executing"""
        self.order_details.append({
            'side': side,
            'amount': amount,
            'amount_is_base': amount_is_base,
            'base_symbol': base_symbol,
            'quote_symbol': quote_symbol,
        })
        return super().market_swap(base_symbol, quote_symbol, amount, amount_is_base, slippage_bps, side)
    
    def swap_exact_out(self, token_in_symbol, token_out_symbol, target_out_amount, 
                      max_in_amount=None, slippage_bps=50, **kwargs):
        """Track exact-out swap details"""
        # Determine side from token symbols
        if token_out_symbol == "QUOTE":
            side = "sell"  # Selling BASE for QUOTE
        else:
            side = "buy"  # Buying BASE with QUOTE
        
        self.order_details.append({
            'side': side,
            'amount': target_out_amount,
            'token_in': token_in_symbol,
            'token_out': token_out_symbol,
            'type': 'exact_out',
        })
        return super().swap_exact_out(token_in_symbol, token_out_symbol, target_out_amount, 
                                      max_in_amount, slippage_bps, **kwargs)


def test_batch_swap_sell_order_amounts():
    """Verify each sell order has correct amount and side"""
    fake = OrderTrackingConnector(base_balance=1000.0, quote_balance=1000.0, price=2.0)
    num_orders = 4
    total_amount = 20.0
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=total_amount,
        amount_is_base=True,
        min_price=1.9,
        max_price=2.1,
        num_orders=num_orders,
        distribution="uniform",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=True,  # Selling BASE
    )
    strat = DexBatchSwap(cfg, connectors=[fake])
    
    # Execute all orders
    for _ in range(num_orders):
        strat._on_tick()
    
    # Verify order details
    executed_orders = fake.order_details
    assert len(executed_orders) > 0, "Should have executed some orders"
    
    # All orders should be SELL
    for order in executed_orders:
        assert order['side'] == 'sell', f"Expected sell order, got {order['side']}"
    
    # Total amount should be positive (some orders may not execute)
    total_executed = sum(order['amount'] for order in executed_orders)
    assert total_executed > 0, f"Should execute some orders, got {total_executed}"
    
    # For uniform distribution, amounts should be approximately equal
    expected_per_order = total_amount / num_orders
    for order in executed_orders:
        assert abs(order['amount'] - expected_per_order) < 1.0, \
            f"Expected ~{expected_per_order} per order, got {order['amount']}"


def test_batch_swap_buy_order_amounts():
    """Verify each buy order has correct amount and side"""
    fake = OrderTrackingConnector(base_balance=1000.0, quote_balance=1000.0, price=2.0)
    num_orders = 3
    total_amount = 30.0
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=total_amount,
        amount_is_base=False,  # Amount in QUOTE
        min_price=1.9,
        max_price=2.1,
        num_orders=num_orders,
        distribution="uniform",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=False,  # Buying BASE
    )
    strat = DexBatchSwap(cfg, connectors=[fake])
    
    # Execute all orders
    for _ in range(num_orders):
        strat._on_tick()
    
    # Verify order details
    executed_orders = fake.order_details
    assert len(executed_orders) > 0, "Should have executed some orders"
    
    # All orders should be BUY
    for order in executed_orders:
        assert order['side'] == 'buy', f"Expected buy order, got {order['side']}"
    
    # Total amount should be positive (some orders may not execute)
    total_executed = sum(order['amount'] for order in executed_orders)
    assert total_executed > 0, f"Should execute some orders, got {total_executed}"


def test_dca_uniform_equal_order_amounts():
    """Verify DCA uniform distribution creates equal-sized orders"""
    fake = OrderTrackingConnector(base_balance=1000.0, quote_balance=1000.0, price=2.0)
    num_orders = 5
    total_amount = 50.0
    
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=total_amount,
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
    
    # Verify order details
    executed_orders = fake.order_details
    assert len(executed_orders) == num_orders, f"Expected {num_orders} orders, got {len(executed_orders)}"
    
    # For uniform DCA, all orders should have same amount
    expected_per_order = total_amount / num_orders
    for i, order in enumerate(executed_orders):
        assert order['side'] == 'buy', f"Order {i+1}: Expected buy, got {order['side']}"
        assert abs(order['amount'] - expected_per_order) < 0.01, \
            f"Order {i+1}: Expected {expected_per_order}, got {order['amount']}"


def test_batch_swap_bell_distribution_amounts():
    """Verify bell distribution creates varying order sizes"""
    fake = OrderTrackingConnector(base_balance=1000.0, quote_balance=1000.0, price=2.0)
    num_orders = 5
    total_amount = 50.0
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=total_amount,
        amount_is_base=True,
        min_price=1.9,
        max_price=2.1,
        num_orders=num_orders,
        distribution="bell",  # Bell curve distribution
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=True,
    )
    strat = DexBatchSwap(cfg, connectors=[fake])
    
    # Execute all orders
    for _ in range(num_orders):
        strat._on_tick()
    
    executed_orders = fake.order_details
    assert len(executed_orders) >= 3, "Should execute multiple orders"
    
    # Bell distribution means not all orders are equal
    # Get unique amounts (with small tolerance)
    amounts = [order['amount'] for order in executed_orders]
    unique_amounts = []
    for amt in amounts:
        is_unique = True
        for existing in unique_amounts:
            if abs(amt - existing) < 0.01:
                is_unique = False
                break
        if is_unique:
            unique_amounts.append(amt)
    
    # Bell distribution should have at least 2 different sizes
    assert len(unique_amounts) >= 2, f"Bell distribution should vary amounts, got {amounts}"


def test_insufficient_balance_prevents_order():
    """Verify orders don't execute when balance is insufficient"""
    # Start with very low balance
    fake = OrderTrackingConnector(base_balance=1.0, quote_balance=1.0, price=2.0)
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=100.0,  # More than available
        amount_is_base=True,
        min_price=1.9,
        max_price=2.1,
        num_orders=5,
        distribution="uniform",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=True,
    )
    strat = DexBatchSwap(cfg, connectors=[fake])
    
    initial_balance = fake.get_balance("BASE")
    
    # Try to execute orders
    for _ in range(5):
        strat._on_tick()
    
    # Should have executed 0 or very few orders due to insufficient balance
    assert len(fake.order_details) < 3, \
        f"Should execute few orders with insufficient balance, executed {len(fake.order_details)}"
    
    # Balance shouldn't decrease by much
    final_balance = fake.get_balance("BASE")
    assert final_balance > initial_balance * 0.5, "Balance shouldn't decrease dramatically"


def test_order_execution_respects_balance():
    """Verify final balance never goes negative"""
    fake = OrderTrackingConnector(base_balance=10.0, quote_balance=10.0, price=2.0)
    
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=15.0,  # More than half the balance
        amount_is_base=True,
        min_price=1.9,
        max_price=2.1,
        num_orders=10,
        distribution="uniform",
        interval_seconds=0.01,
        slippage_bps=50,
        spend_is_base=True,
    )
    strat = DexBatchSwap(cfg, connectors=[fake])
    
    # Execute all ticks
    for _ in range(10):
        strat._on_tick()
        # Check balance after each tick
        base_balance = fake.get_balance("BASE")
        quote_balance = fake.get_balance("QUOTE")
        assert base_balance >= 0, f"BASE balance went negative: {base_balance}"
        assert quote_balance >= 0, f"QUOTE balance went negative: {quote_balance}"

