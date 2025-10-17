from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional
from decimal import Decimal

from connectors.dex.pancakeswap import PancakeSwapConnector
from strategies.utils import compute_spend_amount, is_exact_output_case
from strategies.order_manager import OrderManager, PreOrderCheck
from strategies.periodic_reporter import PeriodicReporter
from strategies.resilience import ConnectionMonitor

# Telegram notifier (optional)
try:
    from core.telegram_notifier import TelegramNotifier, get_notifier
except ImportError:
    TelegramNotifier = None
    get_notifier = None


@dataclass
class DexSimpleSwapConfig:
    rpc_url: str
    private_key: str
    chain_id: int
    base_symbol: str
    quote_symbol: str
    amount: float
    amount_is_base: bool  # backward-compat; if new fields provided, this may differ
    slippage_bps: int = 50
    # New optional fields to decouple direction from basis
    spend_is_base: Optional[bool] = None
    amount_basis_is_base: Optional[bool] = None
    # Optional label for logging (e.g., wallet name)
    label: Optional[str] = None
    # MEV protection: custom defensive strategies (higher gas, shorter deadlines)
    use_mev_protection: bool = False


class DexSimpleSwap:
    """
    Executes a single market swap on PancakeSwap.
    - Validates balances and approvals
    - Performs the swap and returns tx hash
    """

    def __init__(self, cfg: DexSimpleSwapConfig, connector: Optional[PancakeSwapConnector] = None) -> None:
        self.cfg = cfg
        
        # Validate configuration
        if cfg.amount <= 0:
            raise ValueError(f"amount must be positive: {cfg.amount}")
        
        self.connector = connector or PancakeSwapConnector(
            rpc_url=cfg.rpc_url,
            private_key=cfg.private_key,
            chain_id=cfg.chain_id,
            use_mev_protection=cfg.use_mev_protection,
        )
        
        # Initialize order manager and reporter
        wallet_name = cfg.label or "default"
        
        # Get Telegram notifier if available
        telegram_notifier = get_notifier() if get_notifier else None
        
        self.order_manager = OrderManager(
            wallet_name=wallet_name, 
            strategy_name="dex_simple_swap",
            telegram_notifier=telegram_notifier
        )
        self.reporter = PeriodicReporter(
            wallet_name=wallet_name,
            strategy_name="dex_simple_swap",
            base_symbol=cfg.base_symbol,
            quote_symbol=cfg.quote_symbol
        )
        
        # Connection monitoring
        self._connection_monitor = ConnectionMonitor(f"dex_simple_swap-{wallet_name}")
        
        # Store telegram notifier for strategy-level notifications
        self.telegram_notifier = telegram_notifier

    def _prefix(self) -> str:
        return f"[{self.cfg.label}] " if self.cfg.label else ""

    def _quantize(self, symbol: str, amount: float) -> float:
        qf = getattr(self.connector, "quantize_amount", None)
        if callable(qf):
            try:
                return float(qf(symbol, amount))
            except Exception:
                return float(amount)
        return float(amount)
    
    def _finalize(self, tx_hash: str) -> str:
        """Finalize swap: take final snapshot and print reports."""
        # Wait briefly for transaction to be mined and balance to update
        time.sleep(3)
        
        # Take final snapshot
        self.reporter.take_snapshot(self.connector, force=True)
        
        # Print final reports
        self.reporter.print_final_report()
        
        # Print order summary
        summary = self.order_manager.get_summary()
        prefix = f"[{self.cfg.label}]" if self.cfg.label else ""
        print(f"\n{prefix} === Order Summary ===")
        print(f"{prefix} Total Orders: {summary['total']}")
        print(f"{prefix} Filled: {summary['filled']}")
        print(f"{prefix} Failed: {summary['failed']}")
        print(f"{prefix} Success Rate: {summary['success_rate']:.1f}%\n")
        
        # Send Telegram notification for strategy completion
        if self.telegram_notifier:
            msg = f"Strategy COMPLETED: dex_simple_swap\nWallet: {self.cfg.label or 'default'}\nPair: {self.cfg.base_symbol.upper()}/{self.cfg.quote_symbol.upper()}\nTotal Orders: {summary['total']}\nFilled: {summary['filled']}\nFailed: {summary['failed']}\nSuccess Rate: {summary['success_rate']:.1f}%"
            self.telegram_notifier.notify_info(msg)
            # Flush to ensure message is sent before strategy ends
            self.telegram_notifier.flush()
        
        return tx_hash

    def run(self) -> str:
        # Send Telegram notification for strategy start
        if self.telegram_notifier:
            msg = f"Strategy STARTED: dex_simple_swap\nWallet: {self.cfg.label or 'default'}\nPair: {self.cfg.base_symbol.upper()}/{self.cfg.quote_symbol.upper()}\nAmount: {self.cfg.amount}"
            self.telegram_notifier.notify_info(msg)
        
        # Take initial snapshot
        self.reporter.take_snapshot(self.connector, force=True)
        
        base = self.cfg.base_symbol.upper()
        quote = self.cfg.quote_symbol.upper()
        amount = float(self.cfg.amount)
        if amount <= 0:
            raise ValueError("Amount must be positive")

        # Determine basis and spend side (direction)
        basis_is_base = self.cfg.amount_basis_is_base if self.cfg.amount_basis_is_base is not None else self.cfg.amount_is_base
        spend_is_base = self.cfg.spend_is_base if self.cfg.spend_is_base is not None else self.cfg.amount_is_base
        side = "sell" if spend_is_base else "buy"

        # Determine spend symbol
        spend_symbol = base if spend_is_base else quote
        
        # Get current price for order tracking
        try:
            current_price = self.connector.get_price_fast(base, quote)
        except Exception:
            try:
                current_price = self.connector.get_price(base, quote)
            except Exception:
                current_price = None

        # If user amount is on the output side, prefer exact-output swap to guarantee target receive amount
        if is_exact_output_case(basis_is_base, spend_is_base):
            target_out_symbol = quote if spend_is_base else base
            spend_symbol = base if spend_is_base else quote
            
            # Create order for tracking
            order = self.order_manager.create_order(
                base_symbol=base,
                quote_symbol=quote,
                side=side,
                amount=amount,
                price=current_price,
                reason=f"Exact-output swap: receive exactly {amount} {target_out_symbol}"
            )
            order.amount_symbol = target_out_symbol  # amount is target output
            
            # Best-effort balance pre-check using estimator (padded by slippage for safety)
            try:
                est_in = float(self.connector.estimate_in_for_exact_out(
                    token_in_symbol=spend_symbol,
                    token_out_symbol=target_out_symbol,
                    amount_out_human=amount,
                ))
            except Exception:
                est_in = 0.0
            
            if est_in > 0:
                # Use 2x slippage as buffer for volatile markets
                # This provides more safety margin for exact-output swaps
                pad = (10_000 + int(self.cfg.slippage_bps) * 2) / 10_000.0
                est_in_padded = est_in * pad
                bal_check_amt = self._quantize(spend_symbol, est_in_padded)
                
                # Validate before submission
                check = self.order_manager.validate_order(
                    self.connector,
                    spend_symbol,
                    bal_check_amt
                )
                
                if not check.passed:
                    print(f"{self._prefix()}⚠ Pre-order validation failed: {check.reason}")
                    if check.details:
                        for key, val in check.details.items():
                            print(f"{self._prefix()}  {key}: {val}")
                    raise RuntimeError(f"{self._prefix()}Cannot place order: {check.reason}")
            
            print(f"{self._prefix()}[swap] exact-out: target {amount} {target_out_symbol}, side={side}")
            
            # Submit with retry
            def submit_swap():
                return self.connector.swap_exact_out(
                    token_in_symbol=spend_symbol,
                    token_out_symbol=target_out_symbol,
                    target_out_amount=float(amount),
                    slippage_bps=int(self.cfg.slippage_bps),
                )
            
            success = self.order_manager.submit_order_with_retry(
                order,
                submit_swap,
                self.connector.tx_explorer_url
            )
            
            if success:
                self.order_manager.mark_filled(order, actual_output=amount)
                return self._finalize(order.tx_hash)
            else:
                # If all retries failed, try fallback
                print(f"{self._prefix()}[swap] exact-out failed; falling back to market swap with computed spend amount...")
                # Fallback to market swap by computing spend amount
                try:
                    est_spend = self.connector.estimate_in_for_exact_out(
                        token_in_symbol=spend_symbol,
                        token_out_symbol=target_out_symbol,
                        amount_out_human=amount,
                    )
                except Exception:
                    est_spend = 0.0
                if est_spend and est_spend > 0:
                    spend_amt = float(est_spend)
                    price_qpb = None
                else:
                    try:
                        print(f"{self._prefix()}[swap] fetching price via get_price_side(base={base}, quote={quote}, side={side}, fast=True)...")
                        price_qpb = self.connector.get_price_side(base, quote, side=side, fast=True)
                        print(f"{self._prefix()}[swap] fetched price ({base}/{quote})={price_qpb}")
                    except Exception:
                        print(f"{self._prefix()}[swap] fast price failed; fetching via get_price_side(base={base}, quote={quote}, side={side}, fast=False)...")
                        price_qpb = self.connector.get_price_side(base, quote, side=side, fast=False)
                        print(f"{self._prefix()}[swap] fetched price ({base}/{quote})={price_qpb}")
                    if not price_qpb or price_qpb <= 0:
                        raise RuntimeError(f"{self._prefix()}Swap failed: cannot compute spend amount after exact-out failure")
                    spend_amt = compute_spend_amount(price_qpb, amount, basis_is_base, spend_is_base)
                amount_q = self._quantize(spend_symbol, spend_amt)
                
                # Create fallback order
                fallback_order = self.order_manager.create_order(
                    base_symbol=base,
                    quote_symbol=quote,
                    side=side,
                    amount=amount_q,
                    price=current_price,
                    reason=f"Fallback market swap after exact-out failure"
                )
                fallback_order.amount_symbol = spend_symbol  # amount is spend
                
                # Validate fallback order
                check = self.order_manager.validate_order(
                    self.connector,
                    spend_symbol,
                    amount_q
                )
                
                if not check.passed:
                    print(f"{self._prefix()}⚠ Fallback validation failed: {check.reason}")
                    raise RuntimeError(f"{self._prefix()}Cannot execute fallback: {check.reason}")
                
                print(f"{self._prefix()}[swap] spending {amount_q} {'BASE' if spend_is_base else 'QUOTE'} token ({spend_symbol}), side={side}")
                
                # Submit fallback with retry
                def submit_fallback():
                    return self.connector.market_swap(
                        base_symbol=base,
                        quote_symbol=quote,
                        amount=amount_q,
                        amount_is_base=spend_is_base,
                        slippage_bps=self.cfg.slippage_bps,
                        side=side,
                    )
                
                success = self.order_manager.submit_order_with_retry(
                    fallback_order,
                    submit_fallback,
                    self.connector.tx_explorer_url
                )
                
                if not success:
                    raise RuntimeError(f"{self._prefix()}Fallback swap failed after {self.order_manager.max_retries} attempts")
                
                self.order_manager.mark_filled(fallback_order)
                return self._finalize(fallback_order.tx_hash)
        # Otherwise, compute spend amount using side-aware price (approx-output with slippage guard)
        if basis_is_base == spend_is_base:
            spend_amt = amount
            price_qpb = None
        else:
            # Try estimating spend via exact-out quoter first
            try:
                est_spend = self.connector.estimate_in_for_exact_out(
                    token_in_symbol=base if spend_is_base else quote,
                    token_out_symbol=quote if spend_is_base else base,
                    amount_out_human=amount,
                )
            except Exception:
                est_spend = 0.0
            if est_spend and est_spend > 0:
                spend_amt = float(est_spend)
                price_qpb = None
            else:
                try:
                    print(f"{self._prefix()}[swap] fetching price via get_price_side(base={base}, quote={quote}, side={side}, fast=True)...")
                    price_qpb = self.connector.get_price_side(base, quote, side=side, fast=True)
                    print(f"{self._prefix()}[swap] fetched price ({base}/{quote})={price_qpb}")
                except Exception:
                    print(f"{self._prefix()}[swap] fast price failed; fetching via get_price_side(base={base}, quote={quote}, side={side}, fast=False)...")
                    price_qpb = self.connector.get_price_side(base, quote, side=side, fast=False)
                    print(f"{self._prefix()}[swap] fetched price ({base}/{quote})={price_qpb}")
                if price_qpb <= 0:
                    raise RuntimeError("Failed to fetch price")
                spend_amt = compute_spend_amount(price_qpb, amount, basis_is_base, spend_is_base)

        # Quantize to token decimals before checks and execution
        amount_q = self._quantize(spend_symbol, spend_amt)

        # Create order for tracking
        order = self.order_manager.create_order(
            base_symbol=base,
            quote_symbol=quote,
            side=side,
            amount=amount_q,
            price=current_price,
            reason=f"Market swap: spend {amount_q} {spend_symbol}"
        )
        order.amount_symbol = spend_symbol  # amount is spend

        # Validate before submission
        check = self.order_manager.validate_order(
            self.connector,
            spend_symbol,
            amount_q
        )
        
        if not check.passed:
            print(f"{self._prefix()}⚠ Pre-order validation failed: {check.reason}")
            if check.details:
                for key, val in check.details.items():
                    print(f"{self._prefix()}  {key}: {val}")
            raise RuntimeError(f"{self._prefix()}Cannot place order: {check.reason}")

        # Approve and swap (connector expects amount in spend token units)
        print(f"{self._prefix()}[swap] spending {amount_q} {'BASE' if spend_is_base else 'QUOTE'} token ({spend_symbol}), side={side}")
        
        # Submit with retry
        def submit_swap():
            return self.connector.market_swap(
                base_symbol=base,
                quote_symbol=quote,
                amount=amount_q,
                amount_is_base=spend_is_base,
                slippage_bps=self.cfg.slippage_bps,
                side=side,
            )
        
        success = self.order_manager.submit_order_with_retry(
            order,
            submit_swap,
            self.connector.tx_explorer_url
        )
        
        if not success:
            raise RuntimeError(f"{self._prefix()}Swap failed after {self.order_manager.max_retries} attempts")
        
        self.order_manager.mark_filled(order)
        return self._finalize(order.tx_hash)


