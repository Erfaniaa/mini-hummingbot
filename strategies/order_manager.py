"""
Order management utilities for strategies.

Provides order validation, retry logic, and enhanced logging.
"""
from __future__ import annotations

import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any
from decimal import Decimal


def format_timestamp(strategy_start_time: Optional[float] = None) -> str:
    """
    Format current timestamp with UTC time and elapsed time.
    
    Args:
        strategy_start_time: Unix timestamp when strategy started (optional)
    
    Returns:
        Formatted string like "[2025-09-29 12:34:56 UTC | +123s]" or "[2025-09-29 12:34:56 UTC]"
    """
    now = time.time()
    utc_time = datetime.utcfromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    if strategy_start_time:
        elapsed = int(now - strategy_start_time)
        return f"[{utc_time} | +{elapsed}s]"
    else:
        return f"[{utc_time}]"


@dataclass
class OrderInfo:
    """Tracks information about a single order."""
    internal_id: int
    wallet_name: str
    strategy_name: str
    base_symbol: str
    quote_symbol: str
    side: str  # "sell" or "buy"
    amount: float
    price: Optional[float]
    reason: str  # why this order was placed
    amount_symbol: Optional[str] = None  # symbol of the amount field (for display)
    tx_hash: Optional[str] = None
    bscscan_url: Optional[str] = None
    status: str = "pending"  # pending, submitted, filled, failed, cancelled
    submit_time: Optional[float] = None
    complete_time: Optional[float] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    gas_used: Optional[float] = None
    actual_output: Optional[float] = None


@dataclass
class PreOrderCheck:
    """Result of pre-order validation."""
    passed: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


class OrderManager:
    """
    Manages order lifecycle with validation, retries, and logging.
    """
    
    def __init__(self, wallet_name: str, strategy_name: str, max_retries: int = 3, strategy_start_time: Optional[float] = None):
        self.wallet_name = wallet_name
        self.strategy_name = strategy_name
        self.max_retries = max_retries
        self.strategy_start_time = strategy_start_time
        self._order_counter = 0
        self.orders: Dict[int, OrderInfo] = {}
    
    def next_order_id(self) -> int:
        """Generate next internal order ID."""
        self._order_counter += 1
        return self._order_counter
    
    def create_order(
        self,
        base_symbol: str,
        quote_symbol: str,
        side: str,
        amount: float,
        price: Optional[float],
        reason: str
    ) -> OrderInfo:
        """Create and track a new order."""
        order = OrderInfo(
            internal_id=self.next_order_id(),
            wallet_name=self.wallet_name,
            strategy_name=self.strategy_name,
            base_symbol=base_symbol,
            quote_symbol=quote_symbol,
            side=side,
            amount=amount,
            price=price,
            reason=reason,
        )
        self.orders[order.internal_id] = order
        return order
    
    def validate_order(
        self,
        connector: Any,
        spend_symbol: str,
        spend_amount: float,
        native_balance: Optional[float] = None
    ) -> PreOrderCheck:
        """
        Validate order before submission.
        
        Checks:
        - Sufficient token balance
        - Sufficient native token (BNB) for gas
        - Token approval
        """
        try:
            # Check token balance
            token_balance = connector.get_balance(spend_symbol)
            if token_balance < spend_amount:
                return PreOrderCheck(
                    passed=False,
                    reason=f"Insufficient {spend_symbol} balance",
                    details={
                        "required": spend_amount,
                        "available": token_balance,
                        "deficit": spend_amount - token_balance
                    }
                )
            
            # Check native balance for gas (if provided)
            if native_balance is not None:
                min_native_required = 0.001  # Minimum BNB needed for gas
                if native_balance < min_native_required:
                    return PreOrderCheck(
                        passed=False,
                        reason="Insufficient BNB for gas fees",
                        details={
                            "required": min_native_required,
                            "available": native_balance
                        }
                    )
            
            # Check token approval
            token_address = connector._resolve(spend_symbol)
            allowance = connector.get_allowance(spend_symbol)
            spend_wei = connector.client.to_wei(token_address, spend_amount)
            
            if allowance < spend_wei:
                return PreOrderCheck(
                    passed=False,
                    reason=f"{spend_symbol} not approved for spending",
                    details={
                        "required": spend_amount,
                        "allowance_human": connector.client.from_wei(token_address, allowance)
                    }
                )
            
            return PreOrderCheck(passed=True, reason="All checks passed")
            
        except Exception as e:
            return PreOrderCheck(
                passed=False,
                reason=f"Validation error: {str(e)}"
            )
    
    def submit_order_with_retry(
        self,
        order: OrderInfo,
        submit_fn: Callable[[], str],
        get_explorer_url: Callable[[str], str]
    ) -> bool:
        """
        Submit order with retry logic.
        
        Returns True if successful, False otherwise.
        """
        order.submit_time = time.time()
        
        for attempt in range(self.max_retries):
            try:
                order.retry_count = attempt
                
                # Log submission attempt
                self._log_submission(order, attempt)
                
                # Execute swap
                tx_hash = submit_fn()
                
                # Success
                order.tx_hash = tx_hash
                order.bscscan_url = get_explorer_url(tx_hash)
                order.status = "submitted"
                
                self._log_success(order)
                return True
                
            except Exception as e:
                order.error_message = str(e)
                
                if attempt < self.max_retries - 1:
                    self._log_retry(order, attempt, e)
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    order.status = "failed"
                    order.complete_time = time.time()
                    self._log_failure(order, e)
                    return False
        
        return False
    
    def mark_filled(self, order: OrderInfo, actual_output: Optional[float] = None):
        """Mark order as filled."""
        order.status = "filled"
        order.complete_time = time.time()
        order.actual_output = actual_output
        self._log_filled(order)
    
    def mark_failed(self, order: OrderInfo, reason: str = ""):
        """Mark order as failed."""
        order.status = "failed"
        order.complete_time = time.time()
        order.error_message = reason
        prefix = f"[{order.wallet_name}] [{order.strategy_name}]"
        timestamp = format_timestamp(self.strategy_start_time)
        print(f"{timestamp} {prefix} ✗ Order #{order.internal_id} FAILED: {reason}")
    
    def _log_submission(self, order: OrderInfo, attempt: int):
        """Log order submission."""
        prefix = f"[{order.wallet_name}] [{order.strategy_name}]"
        side_str = order.side.upper()
        timestamp = format_timestamp(self.strategy_start_time)
        
        print(f"{timestamp} {prefix} Submitting order #{order.internal_id} (attempt {attempt + 1}/{self.max_retries})")
        print(f"{prefix}   Side: {side_str} {order.base_symbol}/{order.quote_symbol}")
        # Use amount_symbol if available, otherwise fall back to old logic
        amount_symbol = order.amount_symbol if order.amount_symbol else (order.quote_symbol if order.side == 'buy' else order.base_symbol)
        print(f"{prefix}   Amount: {order.amount} {amount_symbol}")
        if order.price:
            print(f"{prefix}   Price: {order.price:.8f} {order.base_symbol}/{order.quote_symbol}")
        print(f"{prefix}   Reason: {order.reason}")
    
    def _log_success(self, order: OrderInfo):
        """Log successful submission."""
        prefix = f"[{order.wallet_name}] [{order.strategy_name}]"
        print(f"{prefix} ✓ Order #{order.internal_id} submitted successfully")
        print(f"{prefix}   Transaction: {order.bscscan_url}")
    
    def _log_retry(self, order: OrderInfo, attempt: int, error: Exception):
        """Log retry attempt."""
        prefix = f"[{order.wallet_name}] [{order.strategy_name}]"
        print(f"{prefix} ⚠ Order #{order.internal_id} failed (attempt {attempt + 1}): {error}")
        print(f"{prefix}   Retrying in {2 ** attempt} seconds...")
    
    def _log_failure(self, order: OrderInfo, error: Exception):
        """Log final failure."""
        prefix = f"[{order.wallet_name}] [{order.strategy_name}]"
        print(f"{prefix} ✗ Order #{order.internal_id} FAILED after {self.max_retries} attempts")
        print(f"{prefix}   Error: {error}")
    
    def _log_filled(self, order: OrderInfo):
        """Log order fill."""
        prefix = f"[{order.wallet_name}] [{order.strategy_name}]"
        duration = order.complete_time - order.submit_time if order.complete_time and order.submit_time else 0
        timestamp = format_timestamp(self.strategy_start_time)
        
        print(f"{timestamp} {prefix} ✓ Order #{order.internal_id} FILLED")
        if order.actual_output:
            print(f"{prefix}   Received: {order.actual_output}")
        print(f"{prefix}   Execution time: {duration:.1f}s")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get order summary statistics."""
        total = len(self.orders)
        submitted = sum(1 for o in self.orders.values() if o.status == "submitted")
        filled = sum(1 for o in self.orders.values() if o.status == "filled")
        failed = sum(1 for o in self.orders.values() if o.status == "failed")
        pending = sum(1 for o in self.orders.values() if o.status == "pending")
        
        return {
            "total": total,
            "submitted": submitted,
            "filled": filled,
            "failed": failed,
            "pending": pending,
            "success_rate": (filled / total * 100) if total > 0 else 0,
        }
