from __future__ import annotations

import json
import os

from core import token_registry as tr
from core.token_registry import TokenRegistry


def test_token_registry_merges_custom(tmp_path):
    tokens_dir = os.path.join(tmp_path, "tokens")
    os.makedirs(tokens_dir)
    mainnet_path = os.path.join(tokens_dir, "bep20_tokens_mainnet.json")
    custom_path = os.path.join(tokens_dir, "custom_tokens_mainnet.json")

    base_list = {"tokens": [{"symbol": "USDT", "address": "0xBASE", "decimals": 18}]}
    custom_list = {"tokens": [{"symbol": "BTCB", "address": "0xCUSTOM", "decimals": 18}]}

    with open(mainnet_path, "w", encoding="utf-8") as f:
        json.dump(base_list, f)
    with open(custom_path, "w", encoding="utf-8") as f:
        json.dump(custom_list, f)

    tr.TOKENS_DIR = tokens_dir
    tr.BEP20_MAINNET_FILE = mainnet_path
    tr.CUSTOM_MAINNET_FILE = custom_path

    reg = TokenRegistry("mainnet")
    btcb = reg.get("btcb")
    assert btcb.address == "0xCUSTOM"
