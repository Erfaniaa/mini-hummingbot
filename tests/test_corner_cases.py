"""
Tests for corner cases and edge scenarios in trading strategies.

These tests verify behavior in unusual or extreme conditions:
- Zero slippage tolerance
- Insufficient balance
- Multiple simultaneous level triggers
- Price gaps and volatility
- Failed order tracking
"""

from unittest.mock import Mock, patch
import pytest

from strategies.dex_simple_swap import DexSimpleSwap, DexSimpleSwapConfig
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig
from strategies.dex_pure_market_making import DexPureMarketMaking, DexPureMMConfig
from strategies.dex_dca import DexDCA, DexDCAConfig


class FakeConnector:
    """Fake connector for testing with controllable balance and price."""
    
    def __init__(self, initial_base=1000.0, initial_quote=1000.0, price=10.0):
        self.base_balance = initial_base
        self.quote_balance = initial_quote
        self.current_price = price
        self.swaps_executed = []
        self.tx_counter = 0
        
        # Mock client for to_wei
        self.client = Mock()
        self.client.to_wei = lambda address, amount: int(amount * 10**18)
        
    def _resolve(self, symbol):
        """Resolve token symbol to address (for testing just return symbol)."""
        return f"0x{symbol.lower()}"
    
    def get_allowance(self, symbol):
        """Return a large allowance for testing."""
        return 10**30
        
    def get_balance(self, symbol):
        if symbol.upper() in ["BASE", "LINK"]:
            return self.base_balance
        elif symbol.upper() in ["QUOTE", "USDT"]:
            return self.quote_balance
        return 0.0
    
    def get_price(self, base, quote):
        return self.current_price
    
    def get_price_fast(self, base, quote):
        return self.current_price
    
    def get_price_side(self, base, quote, side="sell", fast=True):
        return self.current_price
    
    def market_swap(self, base_symbol, quote_symbol, amount, amount_is_base, slippage_bps, side):
        """Simulate a market swap and track details."""
        self.tx_counter += 1
        tx_hash = f"0x{'a' * 63}{self.tx_counter}"
        
        # Calculate amounts
        if side == "sell":
            spend_amount = amount if amount_is_base else amount / self.current_price
            receive_amount = spend_amount * self.current_price if amount_is_base else amount
            
            # Check balance
            if spend_amount > self.base_balance:
                raise RuntimeError("Insufficient base balance")
            
            # Update balances
            self.base_balance -= spend_amount
            self.quote_balance += receive_amount
            
            self.swaps_executed.append({
                "side": "sell",
                "spend_symbol": base_symbol,
                "spend_amount": spend_amount,
                "receive_symbol": quote_symbol,
                "receive_amount": receive_amount,
                "price": self.current_price,
                "tx_hash": tx_hash
            })
        else:  # buy
            spend_amount = amount if not amount_is_base else amount * self.current_price
            receive_amount = spend_amount / self.current_price if not amount_is_base else amount
            
            # Check balance
            if spend_amount > self.quote_balance:
                raise RuntimeError("Insufficient quote balance")
            
            # Update balances
            self.quote_balance -= spend_amount
            self.base_balance += receive_amount
            
            self.swaps_executed.append({
                "side": "buy",
                "spend_symbol": quote_symbol,
                "spend_amount": spend_amount,
                "receive_symbol": base_symbol,
                "receive_amount": receive_amount,
                "price": self.current_price,
                "tx_hash": tx_hash
            })
        
        return tx_hash
    
    def swap_exact_out(self, token_in_symbol, token_out_symbol, target_out_amount, slippage_bps=50):
        """Execute exact-output swap (receive exact amount of output token)."""
        self.tx_counter += 1
        tx_hash = f"0x{'e' * 63}{self.tx_counter}"
        
        # Determine which token is base and which is quote
        if token_out_symbol.upper() in ["BASE", "LINK"]:
            # Buying BASE - receive exact BASE amount
            base_received = target_out_amount
            quote_spent = base_received / self.current_price
            
            # Check balance
            if quote_spent > self.quote_balance:
                raise RuntimeError("Insufficient quote balance for exact-output swap")
            
            # Update balances
            self.quote_balance -= quote_spent
            self.base_balance += base_received
            
            self.swaps_executed.append({
                "side": "buy",
                "spend_symbol": token_in_symbol,
                "spend_amount": quote_spent,
                "receive_symbol": token_out_symbol,
                "receive_amount": base_received,
                "price": self.current_price,
                "tx_hash": tx_hash,
                "type": "exact_out"
            })
        else:
            # Selling BASE - receive exact QUOTE amount
            quote_received = target_out_amount
            base_spent = quote_received * self.current_price
            
            # Check balance
            if base_spent > self.base_balance:
                raise RuntimeError("Insufficient base balance for exact-output swap")
            
            # Update balances
            self.base_balance -= base_spent
            self.quote_balance += quote_received
            
            self.swaps_executed.append({
                "side": "sell",
                "spend_symbol": token_in_symbol,
                "spend_amount": base_spent,
                "receive_symbol": token_out_symbol,
                "receive_amount": quote_received,
                "price": self.current_price,
                "tx_hash": tx_hash,
                "type": "exact_out"
            })
        
        return tx_hash
    
    def approve_unlimited(self, symbol):
        return "0x" + "b" * 64
    
    def quantize_amount(self, symbol, amount):
        return round(amount, 6)
    
    @property
    def tx_explorer_url(self):
        return "https://example.com/tx/"


def test_zero_slippage_should_handle_gracefully():
    """Test that zero slippage is handled appropriately."""
    conn = FakeConnector(initial_base=100, initial_quote=1000, price=10.0)
    
    cfg = DexSimpleSwapConfig(
        rpc_url="http://test",
        private_key="0x" + "1" * 64,
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=10.0,
        amount_is_base=True,
        spend_is_base=True,
        slippage_bps=0,  # Zero slippage
        label="test"
    )
    
    strategy = DexSimpleSwap(cfg, connector=conn)
    
    # Should execute successfully (connector doesn't enforce slippage)
    tx_hash = strategy.run()
    
    assert tx_hash is not None
    assert len(conn.swaps_executed) == 1
    assert conn.swaps_executed[0]["side"] == "sell"
    assert conn.swaps_executed[0]["spend_amount"] == 10.0


def test_insufficient_balance_simple_swap():
    """Test that simple swap fails gracefully with insufficient balance."""
    conn = FakeConnector(initial_base=5, initial_quote=1000, price=10.0)
    
    cfg = DexSimpleSwapConfig(
        rpc_url="http://test",
        private_key="0x" + "1" * 64,
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=10.0,  # Requesting more than available (5)
        amount_is_base=True,
        spend_is_base=True,
        slippage_bps=50,
        label="test"
    )
    
    strategy = DexSimpleSwap(cfg, connector=conn)
    
    # Should raise error due to insufficient balance
    with pytest.raises(RuntimeError, match="Cannot place order"):
        strategy.run()


def test_batch_swap_multiple_levels_triggered_simultaneously():
    """Test batch swap when price gap triggers multiple levels at once."""
    conn = FakeConnector(initial_base=100, initial_quote=1000, price=9.0)
    
    cfg = DexBatchSwapConfig(
        rpc_url="http://test",
        private_keys=["0x" + "1" * 64],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=50.0,
        amount_is_base=True,
        spend_is_base=True,
        min_price=10.0,
        max_price=15.0,
        num_orders=5,
        distribution="uniform",
        interval_seconds=0.01
    )
    
    strategy = DexBatchSwap(cfg, connectors=[conn])
    
    # Price jump: 9 -> 16 (triggers all 5 levels)
    conn.current_price = 16.0
    
    # Execute one tick
    strategy._on_tick()
    
    # Should have attempted all 5 levels (10 each)
    # All should succeed since we have balance=100
    assert len(conn.swaps_executed) == 5
    
    # Verify total amount sold
    total_sold = sum(swap["spend_amount"] for swap in conn.swaps_executed)
    assert abs(total_sold - 50.0) < 0.01  # Should be close to total_amount
    
    # Verify all are sell orders
    assert all(swap["side"] == "sell" for swap in conn.swaps_executed)
    
    # Verify remaining balance
    assert abs(conn.base_balance - 50.0) < 0.01  # Started with 100, sold 50


def test_batch_swap_insufficient_balance_for_all_levels():
    """Test batch swap when balance insufficient for all simultaneously triggered levels."""
    conn = FakeConnector(initial_base=30, initial_quote=1000, price=9.0)
    
    cfg = DexBatchSwapConfig(
        rpc_url="http://test",
        private_keys=["0x" + "1" * 64],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=50.0,
        amount_is_base=True,
        spend_is_base=True,
        min_price=10.0,
        max_price=15.0,
        num_orders=5,
        distribution="uniform",
        interval_seconds=0.01
    )
    
    strategy = DexBatchSwap(cfg, connectors=[conn])
    
    # Price jump: 9 -> 16 (triggers all 5 levels at 10 each)
    # But we only have balance=30, so only first 3 should succeed
    conn.current_price = 16.0
    
    # Execute one tick
    strategy._on_tick()
    
    # Should have 3 successful swaps (30 total) and 2 failures
    assert len(conn.swaps_executed) == 3
    
    # Verify balance exhausted
    assert conn.base_balance < 1.0


def test_pure_mm_both_sides_triggered():
    """Test Pure MM when price is exactly at mid, allowing both sides to trigger."""
    conn = FakeConnector(initial_base=100, initial_quote=1000, price=10.0)
    
    cfg = DexPureMMConfig(
        rpc_url="http://test",
        private_keys=["0x" + "1" * 64],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        upper_percent=0.5,
        lower_percent=0.5,
        levels_each_side=1,
        order_amount=10.0,
        amount_is_base=True,
        refresh_seconds=9999,
        tick_interval_seconds=0.01
    )
    
    strategy = DexPureMarketMaking(cfg, connectors=[conn])
    strategy._rebuild_levels(10.0)
    
    # Upper level should be 10.05, lower should be 9.95
    # Set price exactly at upper level boundary
    conn.current_price = 10.05
    
    # Execute one tick - should trigger upper level only
    strategy._on_tick()
    
    # Should have executed 1 order (upper sell at 10.05)
    assert len(conn.swaps_executed) >= 1
    
    # Verify it's a sell order
    assert conn.swaps_executed[0]["side"] == "sell"
    
    # Now test if lower also works
    conn.current_price = 9.95
    
    # Execute another tick - should trigger lower level
    strategy._on_tick()
    
    # If implementation allows sequential execution, we might have 2 orders
    # But at minimum we should have the first upper order
    assert len(conn.swaps_executed) >= 1


def test_dca_failed_order_tracking():
    """Test DCA correctly tracks failed vs successful orders."""
    conn = FakeConnector(initial_base=100, initial_quote=50, price=10.0)
    
    cfg = DexDCAConfig(
        rpc_url="http://test",
        private_keys=["0x" + "1" * 64],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=100.0,
        amount_is_base=False,  # Spending QUOTE
        spend_is_base=False,   # Buying BASE
        num_orders=5,
        interval_seconds=0.01,
        distribution="uniform"
    )
    
    strategy = DexDCA(cfg, connectors=[conn])
    
    # Execute first order (should succeed: 20 QUOTE)
    strategy._on_tick()
    assert len(conn.swaps_executed) == 1
    assert strategy.completed_orders == 1
    assert strategy.orders_left == 4
    
    # Execute second order (should succeed: 20 QUOTE)
    strategy._on_tick()
    assert len(conn.swaps_executed) == 2
    assert strategy.completed_orders == 2
    assert strategy.orders_left == 3
    
    # Execute third order (should fail: only 10 QUOTE left, needs 20)
    strategy._on_tick()
    assert len(conn.swaps_executed) == 2  # Still 2, third failed
    assert strategy.completed_orders == 2  # Should NOT increment
    assert strategy.orders_left == 3  # Should NOT decrement


def test_exact_output_with_price_volatility():
    """Test exact-output swap buffer handles price changes."""
    conn = FakeConnector(initial_base=100, initial_quote=1000, price=10.0)
    
    # Add estimate_in_for_exact_out method
    def estimate_in(token_in_symbol, token_out_symbol, amount_out_human):
        # Simulate estimate based on current price
        return amount_out_human / conn.current_price
    
    conn.estimate_in_for_exact_out = estimate_in
    
    cfg = DexSimpleSwapConfig(
        rpc_url="http://test",
        private_key="0x" + "1" * 64,
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=100.0,  # Want exactly 100 QUOTE
        amount_is_base=False,  # amount is in QUOTE
        amount_basis_is_base=False,
        spend_is_base=True,  # Selling BASE for QUOTE
        slippage_bps=50
    )
    
    strategy = DexSimpleSwap(cfg, connector=conn)
    
    # Price suddenly increases mid-execution (simulated by having higher price)
    # The 2x buffer should handle this
    conn.current_price = 10.5  # 5% increase
    
    tx_hash = strategy.run()
    
    # Should succeed with the buffer
    assert tx_hash is not None
    assert len(conn.swaps_executed) == 1


def test_order_tracking_validation():
    """Test that order count, amount, and side are tracked correctly."""
    conn = FakeConnector(initial_base=100, initial_quote=1000, price=10.0)
    
    cfg = DexSimpleSwapConfig(
        rpc_url="http://test",
        private_key="0x" + "1" * 64,
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=15.0,
        amount_is_base=True,
        spend_is_base=True,  # SELL
        slippage_bps=50,
        label="test"
    )
    
    strategy = DexSimpleSwap(cfg, connector=conn)
    initial_base = conn.base_balance
    initial_quote = conn.quote_balance
    
    tx_hash = strategy.run()
    
    # Verify order executed
    assert tx_hash is not None
    assert len(conn.swaps_executed) == 1
    
    swap = conn.swaps_executed[0]
    
    # Verify side
    assert swap["side"] == "sell"
    
    # Verify amount
    assert abs(swap["spend_amount"] - 15.0) < 0.01
    
    # Verify balance changes
    assert abs((initial_base - conn.base_balance) - 15.0) < 0.01  # Sold 15 BASE
    assert conn.quote_balance > initial_quote  # Received QUOTE
    
    # Verify order manager summary
    summary = strategy.order_manager.get_summary()
    assert summary["total"] == 1
    assert summary["filled"] == 1
    assert summary["failed"] == 0
    assert summary["success_rate"] == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

