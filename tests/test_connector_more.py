from __future__ import annotations

import pytest

from connectors.dex.pancakeswap import PancakeSwapConnector


class FakeClient:
    DEFAULTS = {97: {"WBNB": "0xWBNB"}}

    def __init__(self):
        self._balances = {}
        self._allowances = {}
        self.chain_id = 97

    def get_decimals(self, token):
        return 18

    def to_wei(self, token, amount):
        return int(amount * (10 ** 18))

    def get_balance(self, token):
        return int(self._balances.get(token, 0))

    def get_allowance(self, token):
        return int(self._allowances.get(token, 0))

    def approve(self, token, amt):
        self._allowances[token] = int(amt)
        return "0xapprove"


def test_connector_insufficient_balance_raises():
    conn = PancakeSwapConnector(rpc_url="", private_key="", chain_id=97, client=FakeClient())  # type: ignore[arg-type]
    conn._resolve = lambda s: "0xTOKEN"
    with pytest.raises(RuntimeError):
        conn.market_swap("BASE", "QUOTE", amount=1.0, amount_is_base=True)


def test_connector_testnet_explorer_link():
    conn = PancakeSwapConnector(rpc_url="", private_key="", chain_id=97, client=FakeClient())  # type: ignore[arg-type]
    url = conn.tx_explorer_url("0xtx")
    assert "testnet.bscscan.com" in url
