from __future__ import annotations

import pytest

from strategies.dex_simple_swap import DexSimpleSwap, DexSimpleSwapConfig


class LowBalanceConnector:
    def __init__(self):
        self.chain_id = 56

    def get_balance(self, symbol):
        return 0.0

    def market_swap(self, *args, **kwargs):
        raise AssertionError("should not reach swap when balance is zero")

    def tx_explorer_url(self, tx):
        return ""


def test_simple_swap_insufficient_balance():
    cfg = DexSimpleSwapConfig(
        rpc_url="",
        private_key="",
        chain_id=56,
        base_symbol="BASE",
        quote_symbol="QUOTE",
        amount=1.0,
        amount_is_base=True,
    )
    strat = DexSimpleSwap(cfg, connector=LowBalanceConnector())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        strat.run()
