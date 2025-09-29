from __future__ import annotations

import time
from dataclasses import dataclass

from strategies.dex_simple_swap import DexSimpleSwap, DexSimpleSwapConfig
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig
from strategies.dex_pure_market_making import DexPureMarketMaking, DexPureMMConfig
from strategies.dex_dca import DexDCA, DexDCAConfig


class FakeConnector:
    def __init__(self):
        self._balances = {"BASE": 10.0, "QUOTE": 0.0}
        self._txs = []
        self.chain_id = 56

    def get_price(self, base_symbol, quote_symbol):
        return 1.0

    def get_balance(self, symbol):
        return self._balances.get(symbol, 0.0)

    def approve(self, symbol, amount):
        return "0xapprove"

    def market_swap(self, base_symbol, quote_symbol, amount, amount_is_base, slippage_bps=50, side=None):
        tx = f"0xswap{len(self._txs)}"
        self._txs.append(tx)
        if amount_is_base:
            self._balances["BASE"] -= amount
            self._balances["QUOTE"] += amount
        else:
            self._balances["QUOTE"] -= amount
            self._balances["BASE"] += amount
        return tx

    def tx_explorer_url(self, tx_hash):
        return f"https://bscscan.com/tx/{tx_hash}"


def run_simple_swap(fake: FakeConnector):
    cfg = DexSimpleSwapConfig(
        rpc_url="",
        private_key="",
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=1.0,
        amount_is_base=True,
    )
    s = DexSimpleSwap(cfg, connector=fake)  # type: ignore[arg-type]
    s.run()


def run_batch_swap(fake: FakeConnector):
    cfg = DexBatchSwapConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=2.0,
        amount_is_base=True,
        min_price=1.0,
        max_price=1.0,
        num_orders=2,
        distribution="uniform",
        interval_seconds=0.01,
    )
    from strategies.dex_batch_swap import DexBatchSwap
    s = DexBatchSwap(cfg, connectors=[fake])  # type: ignore[arg-type]
    s.start()
    time.sleep(0.05)
    s.stop()


def run_pure_mm(fake: FakeConnector):
    cfg = DexPureMMConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        upper_percent=0.0,
        lower_percent=0.0,
        levels_each_side=1,
        order_amount=0.5,
        amount_is_base=True,
        refresh_seconds=9999,
        tick_interval_seconds=0.01,
    )
    s = DexPureMarketMaking(cfg, connectors=[fake])  # type: ignore[arg-type]
    s.start()
    time.sleep(0.05)
    s.stop()


def run_dca(fake: FakeConnector):
    cfg = DexDCAConfig(
        rpc_url="",
        private_keys=[""],
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        total_amount=1.0,
        amount_is_base=True,
        interval_seconds=0.01,
        num_orders=2,
        distribution="uniform",
    )
    s = DexDCA(cfg, connectors=[fake])  # type: ignore[arg-type]
    s.start()
    time.sleep(0.05)
    s.stop()


if __name__ == "__main__":
    fake = FakeConnector()
    print("-- simple swap --")
    run_simple_swap(fake)
    print("-- batch swap --")
    run_batch_swap(fake)
    print("-- pure mm --")
    run_pure_mm(fake)
    print("-- dca --")
    run_dca(fake)
    print("Done.")
