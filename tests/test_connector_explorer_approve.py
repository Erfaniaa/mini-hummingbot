from __future__ import annotations

from connectors.dex.pancakeswap import PancakeSwapConnector


class FakeClient:
    DEFAULTS = {56: {"WBNB": "0xWBNB"}}

    def __init__(self):
        self._allowances = {}
        self.chain_id = 56

    def approve(self, token, amt):
        self._allowances[token] = int(amt)
        return "0xapprove"

    def get_allowance(self, token):
        return self._allowances.get(token, 0)


def test_tx_explorer_url():
    conn = PancakeSwapConnector(rpc_url="", private_key="", chain_id=56, client=FakeClient())  # type: ignore[arg-type]
    url = conn.tx_explorer_url("0xabc")
    assert url.endswith("0xabc")
    assert "bscscan.com" in url


def test_approve_unlimited_sets_large_allowance():
    conn = PancakeSwapConnector(rpc_url="", private_key="", chain_id=56, client=FakeClient())  # type: ignore[arg-type]
    # resolve returns token address
    conn._resolve = lambda s: s
    tx = conn.approve_unlimited("0xTOKEN")
    assert tx == "0xapprove"
    assert conn.get_allowance("0xTOKEN") > 0
