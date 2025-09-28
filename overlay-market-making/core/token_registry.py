from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional


TOKENS_DIR = os.path.join(os.path.dirname(__file__), "..", "tokens")
BEP20_MAINNET_FILE = os.path.abspath(os.path.join(TOKENS_DIR, "bep20_tokens_mainnet.json"))
BEP20_TESTNET_FILE = os.path.abspath(os.path.join(TOKENS_DIR, "bep20_tokens_testnet.json"))


@dataclass
class TokenInfo:
    symbol: str
    address: str
    decimals: int
    name: Optional[str] = None


class TokenRegistry:
    """
    Loads and resolves token metadata by symbol for BSC (PancakeSwap).

    - Supports mainnet and testnet lists (extended Pancake token list)
    - Case-insensitive symbol lookup
    - Handles duplicate symbols by returning the first match unless an address filter is provided
    """

    def __init__(self, network: str = "mainnet") -> None:
        if network not in {"mainnet", "testnet"}:
            raise ValueError("network must be 'mainnet' or 'testnet'")
        self.network = network
        self._tokens_by_symbol: Dict[str, List[TokenInfo]] = {}
        self._load()

    def _load(self) -> None:
        path = BEP20_MAINNET_FILE if self.network == "mainnet" else BEP20_TESTNET_FILE
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Token list not found at {path}. Copy Pancake token lists into 'tokens/'."
            )
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tokens = data.get("tokens", [])
        by_symbol: Dict[str, List[TokenInfo]] = {}
        for t in tokens:
            info = TokenInfo(
                symbol=str(t.get("symbol", "")).upper(),
                address=str(t.get("address")),
                decimals=int(t.get("decimals", 18)),
                name=t.get("name"),
            )
            by_symbol.setdefault(info.symbol, []).append(info)
        self._tokens_by_symbol = by_symbol

    def get(self, symbol: str) -> TokenInfo:
        candidates = self._tokens_by_symbol.get(symbol.upper(), [])
        if not candidates:
            raise KeyError(f"Token symbol '{symbol}' not found in registry ({self.network})")
        return candidates[0]

    def find(self, symbol: str) -> List[TokenInfo]:
        return list(self._tokens_by_symbol.get(symbol.upper(), []))

    def list_symbols(self) -> List[str]:
        return sorted(self._tokens_by_symbol.keys())


