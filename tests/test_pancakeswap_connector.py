from __future__ import annotations

from connectors.dex.pancakeswap import PancakeSwapConnector


class FakeClient:
    DEFAULTS = {56: {"WBNB": "0xWBNB"}}

    def __init__(self):
        self._balances = {}
        self._allowances = {}
        self._decimals = {}
        self._txs = []

    def get_decimals(self, token):
        return self._decimals.get(token, 18)

    def from_wei(self, token, amt):
        d = self.get_decimals(token)
        return float(amt) / float(10 ** d)

    def to_wei(self, token, v):
        d = self.get_decimals(token)
        return int(v * (10 ** d))

    def get_balance(self, token):
        return int(self._balances.get(token, 0))

    def get_allowance(self, token):
        return int(self._allowances.get(token, 0))

    def approve(self, token, amt):
        self._allowances[token] = int(amt)
        tx = f"0xapprove{len(self._txs)}"
        self._txs.append(tx)
        return tx

    def quote_v3_exact_input_single(self, base, quote, fee, one_base, slippage_bps=0):
        # Return 1:1
        class Q: pass
        q = Q()
        q.amount_out = one_base
        q.min_amount_out = one_base
        return q

    def quote_v3_exact_input_path(self, tokens, fees, one_base, slippage_bps=0):
        return self.quote_v3_exact_input_single(tokens[0], tokens[-1], 500, one_base, slippage_bps)

    def swap_v3_exact_input_single(self, token_in, token_out, fee, amount_in, slippage_bps=0):
        tx = f"0xswap{len(self._txs)}"
        self._txs.append(tx)
        return tx

    def swap_v3_exact_input_path(self, tokens, fees, amount_in, slippage_bps=0):
        return self.swap_v3_exact_input_single(tokens[0], tokens[-1], fees[0], amount_in, slippage_bps)


def test_connector_market_swap_with_approval(monkeypatch):
    conn = PancakeSwapConnector(rpc_url="http://localhost", private_key="0x11" * 32, chain_id=56)
    fake = FakeClient()
    fake._decimals = {"0xBASE": 18, "0xQUOTE": 18}
    fake._balances = {"0xBASE": fake.to_wei("0xBASE", 10)}
    fake._allowances = {"0xBASE": 0}

    # patch resolver and client
    conn._resolve = lambda s: "0xBASE" if s == "BASE" else "0xQUOTE"
    conn.client = fake

    tx = conn.market_swap("BASE", "QUOTE", amount=1.0, amount_is_base=True)
    assert tx.startswith("0xswap")


def test_connector_get_price(monkeypatch):
    conn = PancakeSwapConnector(rpc_url="http://localhost", private_key="0x11" * 32, chain_id=56)
    fake = FakeClient()
    fake._decimals = {"0xBASE": 18, "0xQUOTE": 18}
    conn._resolve = lambda s: "0xBASE" if s == "BASE" else "0xQUOTE"
    conn.client = fake

    p = conn.get_price("BASE", "QUOTE")
    assert p == 1.0
