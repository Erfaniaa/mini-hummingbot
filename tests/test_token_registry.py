from __future__ import annotations

import json
import os

from core import token_registry as tr
from core.token_registry import TokenRegistry


SAMPLE_LIST = {
    "name": "Sample",
    "tokens": [
        {"name": "USD Tether", "symbol": "USDT", "address": "0x55d398326f99059fF775485246999027B3197955", "decimals": 18},
        {"name": "Wrapped BNB", "symbol": "WBNB", "address": "0xBB4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c", "decimals": 18},
    ],
}


def test_token_registry_load_and_get(tmp_path):
    tokens_dir = os.path.join(tmp_path, "tokens")
    os.makedirs(tokens_dir)
    mainnet_path = os.path.join(tokens_dir, "bep20_tokens_mainnet.json")
    with open(mainnet_path, "w", encoding="utf-8") as f:
        json.dump(SAMPLE_LIST, f)

    tr.TOKENS_DIR = tokens_dir
    tr.BEP20_MAINNET_FILE = mainnet_path

    reg = TokenRegistry("mainnet")
    usdt = reg.get("usdt")
    assert usdt.symbol == "USDT"
    assert usdt.address.startswith("0x")
    assert usdt.decimals == 18
