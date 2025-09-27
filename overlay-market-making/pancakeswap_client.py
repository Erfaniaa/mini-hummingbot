"""
Standalone PancakeSwap v3 client for BSC (mainnet/testnet) using web3.py.

This module is self-contained and independent from Hummingbot.

Features:
- Read-only: token decimals, symbol, balances, allowances
- v3 quotes via QuoterV2.quoteExactInputSingle
- v3 swaps via SwapRouter.exactInputSingle
- Embedded minimal ABIs (ERC20 + v3 QuoterV2 + v3 SwapRouter)
- Safe defaults for BSC mainnet/testnet (v3 SOR/Router + Quoter, WBNB)

Requirements (install in your target project):
    pip install web3==6.* eth-account==0.*

Quick start:
    from pancakeswap_client import PancakeSwapClient
    client = PancakeSwapClient(
        rpc_url="https://bsc-dataseed.binance.org/",
        private_key="<YOUR_PRIVATE_KEY>",
        chain_id=56,  # 56 mainnet, 97 testnet
    )

    usdt = "0x55d398326f99059fF775485246999027B3197955"
    wbnb = client.DEFAULTS[client.chain_id]["WBNB"]
    amount_in_wei = client.to_wei(usdt, 1)

    # v3 quote (500 = 0.05% fee tier)
    v3_quote = client.quote_v3_exact_input_single(usdt, wbnb, 500, amount_in_wei, slippage_bps=50)
    print("v3 minOut (wei):", v3_quote.min_amount_out)

    # Approve router to spend USDT and perform swap
    client.approve(usdt, amount_in_wei)
    v3_tx = client.swap_v3_exact_input_single(usdt, wbnb, 500, amount_in_wei, slippage_bps=50)
    print("v3 swap tx:", v3_tx)

Security note:
- Never hardcode private keys in code. Prefer secure env vars or secret managers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.contract import Contract
from web3.middleware import ExtraDataToPOAMiddleware


@dataclass
class QuoteV3:
    token_in: str
    token_out: str
    fee: int
    amount_in: int
    amount_out: int
    min_amount_out: int


@dataclass
class Quote:
    # Backward alias if needed by callers; same fields as v3 single-path result
    token_in: str
    token_out: str
    fee: int
    amount_in: int
    amount_out: int
    min_amount_out: int


class PancakeSwapClient:
    """
    Lightweight PancakeSwap v2 Router client for Binance Smart Chain.

    - Supports read-only calls without a private key
    - For write calls (approve/swap), provide a private_key
    - Defaults include BSC mainnet/testnet router + WBNB addresses
    """

    # Minimal ERC20 ABI subset
    ERC20_ABI: List[Dict] = [
        {"constant": True, "inputs": [{"name": "", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
        {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
        {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
        {"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    ]

    # No v2 ABI – v3-only client

    # Minimal QuoterV2 (Uniswap/Pancake v3) ABI subset
    QUOTER_V2_ABI: List[Dict] = [
        {
            "inputs": [
                {"internalType": "address", "name": "tokenIn", "type": "address"},
                {"internalType": "address", "name": "tokenOut", "type": "address"},
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "uint24", "name": "fee", "type": "uint24"},
                {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
            ],
            "name": "quoteExactInputSingle",
            "outputs": [
                {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                {"internalType": "uint160", "name": "sqrtPriceX96After", "type": "uint160"},
                {"internalType": "uint32", "name": "initializedTicksCrossed", "type": "uint32"},
                {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"},
            ],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [
                {"internalType": "bytes", "name": "path", "type": "bytes"},
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            ],
            "name": "quoteExactInput",
            "outputs": [
                {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                {"internalType": "uint160", "name": "sqrtPriceX96After", "type": "uint160"},
                {"internalType": "uint32", "name": "initializedTicksCrossed", "type": "uint32"},
                {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"},
            ],
            "stateMutability": "view",
            "type": "function",
        }
    ]

    # Minimal SwapRouter (v3) ABI subset (exactInputSingle)
    SWAP_ROUTER_V3_ABI: List[Dict] = [
        {
            "inputs": [
                {
                    "components": [
                        {"internalType": "address", "name": "tokenIn", "type": "address"},
                        {"internalType": "address", "name": "tokenOut", "type": "address"},
                        {"internalType": "uint24", "name": "fee", "type": "uint24"},
                        {"internalType": "address", "name": "recipient", "type": "address"},
                        {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                        {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
                    ],
                    "internalType": "struct ISwapRouter.ExactInputSingleParams",
                    "name": "params",
                    "type": "tuple",
                }
            ],
            "name": "exactInputSingle",
            "outputs": [
                {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
            ],
            "stateMutability": "payable",
            "type": "function",
        },
        {
            "inputs": [
                {
                    "components": [
                        {"internalType": "bytes", "name": "path", "type": "bytes"},
                        {"internalType": "address", "name": "recipient", "type": "address"},
                        {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                    ],
                    "internalType": "struct ISwapRouter.ExactInputParams",
                    "name": "params",
                    "type": "tuple",
                }
            ],
            "name": "exactInput",
            "outputs": [
                {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
            ],
            "stateMutability": "payable",
            "type": "function",
        }
    ]

    # Defaults for BSC
    # WBNB:
    #   - Mainnet: 0xBB4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c
    #   - Testnet: 0xae13d989dac2f0debff460ac112a837c89baa7cd
    DEFAULTS: Dict[int, Dict[str, str]] = {
        56: {
            "WBNB": "0xBB4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
            "V3_SMART_ORDER_ROUTER": "0x1b81D678ffb9C0263b24A97847620C99d213eB14",
            "V3_NFT_MANAGER": "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
            "V3_QUOTER_V2": "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997",
            # In many deployments, the Smart Order Router handles routing. exactInputSingle is on SwapRouter.
            # If needed, set V3_SWAP_ROUTER to SOR; exactInputSingle should still be available.
            "V3_SWAP_ROUTER": "0x1b81D678ffb9C0263b24A97847620C99d213eB14",
        },
        97: {
            "WBNB": "0xae13d989dac2f0debff460ac112a837c89baa7cd",
            "V3_SMART_ORDER_ROUTER": "0x1b81D678ffb9C0263b24A97847620C99d213eB14",
            "V3_NFT_MANAGER": "0x427bF5b37357632377eCbEC9de3626C71A5396c1",
            "V3_QUOTER_V2": "0xbC203d7f83677c7ed3F7acEc959963E7F4ECC5C2",
            "V3_SWAP_ROUTER": "0x1b81D678ffb9C0263b24A97847620C99d213eB14",
        },
    }

    def __init__(
        self,
        rpc_url: str,
        private_key: Optional[str] = None,
        chain_id: int = 56,
        v3_swap_router_address: Optional[str] = None,
        v3_quoter_address: Optional[str] = None,
    ) -> None:
        self.web3 = Web3(Web3.HTTPProvider(rpc_url))
        # Inject POA middleware for BSC-like chains to normalize extraData
        try:
            self.web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception:
            pass
        if not self.web3.is_connected():
            raise RuntimeError("Failed to connect to RPC provider")

        self.chain_id: int = chain_id
        self.defaults: Dict[int, Dict[str, str]] = self.DEFAULTS

        self._account: Optional[LocalAccount] = Account.from_key(private_key) if private_key else None
        # v3
        self._v3_quoter_address: str = self.to_checksum(v3_quoter_address or self.defaults[chain_id]["V3_QUOTER_V2"]) if "V3_QUOTER_V2" in self.defaults[chain_id] else None
        self._v3_swap_router_address: str = self.to_checksum(v3_swap_router_address or self.defaults[chain_id]["V3_SWAP_ROUTER"]) if "V3_SWAP_ROUTER" in self.defaults[chain_id] else None
        self._v3_quoter: Optional[Contract] = self.web3.eth.contract(address=self._v3_quoter_address, abi=self.QUOTER_V2_ABI) if self._v3_quoter_address else None
        self._v3_router: Optional[Contract] = self.web3.eth.contract(address=self._v3_swap_router_address, abi=self.SWAP_ROUTER_V3_ABI) if self._v3_swap_router_address else None

    # ----------------------------
    # Utilities
    # ----------------------------
    def to_checksum(self, address: str) -> str:
        return self.web3.to_checksum_address(address)

    @property
    def address(self) -> Optional[str]:
        return self._account.address if self._account else None

    def erc20(self, token: str) -> Contract:
        return self.web3.eth.contract(address=self.to_checksum(token), abi=self.ERC20_ABI)

    def get_decimals(self, token: str) -> int:
        return int(self.erc20(token).functions.decimals().call())

    def get_symbol(self, token: str) -> str:
        return str(self.erc20(token).functions.symbol().call())

    def get_name(self, token: str) -> str:
        return str(self.erc20(token).functions.name().call())

    def get_balance(self, token: str, owner: Optional[str] = None) -> int:
        """Return ERC20 token balance (wei)."""
        owner_addr = self.to_checksum(owner or (self.address or "0x0000000000000000000000000000000000000000"))
        return int(self.erc20(token).functions.balanceOf(owner_addr).call())

    def get_native_balance(self, owner: Optional[str] = None) -> int:
        owner_addr = self.to_checksum(owner or (self.address or "0x0000000000000000000000000000000000000000"))
        return int(self.web3.eth.get_balance(owner_addr))

    def get_allowance(self, token: str, spender: Optional[str] = None, owner: Optional[str] = None) -> int:
        owner_addr = self.to_checksum(owner or (self.address or "0x0000000000000000000000000000000000000000"))
        default_spender = self._v3_swap_router_address or self._v3_quoter_address
        spender_addr = self.to_checksum(spender or default_spender)
        return int(self.erc20(token).functions.allowance(owner_addr, spender_addr).call())

    def to_wei(self, token: str, amount_decimal: float) -> int:
        decimals = self.get_decimals(token)
        return int(amount_decimal * (10 ** decimals))

    def from_wei(self, token: str, amount_wei: int) -> float:
        decimals = self.get_decimals(token)
        return float(amount_wei) / float(10 ** decimals)

    # ----------------------------
    # Quotes (read-only, v3)
    # ----------------------------

    # v3 quote (single pool)
    def quote_v3_exact_input_single(
        self,
        token_in: str,
        token_out: str,
        fee: int,
        amount_in: int,
        slippage_bps: int = 50,
        sqrt_price_limit_x96: int = 0,
    ) -> QuoteV3:
        if self._v3_quoter is None:
            raise RuntimeError("V3 Quoter not configured for this chain/network")
        token_in = self.to_checksum(token_in)
        token_out = self.to_checksum(token_out)
        out_amount, _, _, _ = self._v3_quoter.functions.quoteExactInputSingle(
            token_in,
            token_out,
            int(amount_in),
            int(fee),
            int(sqrt_price_limit_x96),
        ).call()
        min_out = int(out_amount) * (10_000 - int(slippage_bps)) // 10_000
        return QuoteV3(token_in=token_in, token_out=token_out, fee=int(fee), amount_in=int(amount_in), amount_out=int(out_amount), min_amount_out=min_out)

    # v3 path encoding helper
    def _encode_v3_path(self, tokens: List[str], fees: List[int]) -> str:
        if len(tokens) < 2 or len(fees) != len(tokens) - 1:
            raise ValueError("Invalid path specification: require N tokens and N-1 fees")
        parts: List[bytes] = []
        for i, token in enumerate(tokens):
            addr = self.to_checksum(token)
            addr_bytes = bytes.fromhex(addr[2:])
            parts.append(addr_bytes)
            if i < len(fees):
                fee_bytes = int(fees[i]).to_bytes(3, byteorder="big")
                parts.append(fee_bytes)
        path_bytes = b"".join(parts)
        return "0x" + path_bytes.hex()

    # v3 quote (multi-hop path)
    def quote_v3_exact_input_path(
        self,
        tokens: List[str],
        fees: List[int],
        amount_in: int,
        slippage_bps: int = 50,
    ) -> QuoteV3:
        if self._v3_quoter is None:
            raise RuntimeError("V3 Quoter not configured for this chain/network")
        checksummed_tokens = [self.to_checksum(t) for t in tokens]
        path = self._encode_v3_path(checksummed_tokens, fees)
        out_amount, _, _, _ = self._v3_quoter.functions.quoteExactInput(path, int(amount_in)).call()
        min_out = int(out_amount) * (10_000 - int(slippage_bps)) // 10_000
        return QuoteV3(token_in=checksummed_tokens[0], token_out=checksummed_tokens[-1], fee=0, amount_in=int(amount_in), amount_out=int(out_amount), min_amount_out=min_out)

    # ----------------------------
    # Transactions (write)
    # ----------------------------
    def _require_account(self) -> LocalAccount:
        if self._account is None:
            raise RuntimeError("Private key is required for this operation")
        return self._account

    def _default_tx_params(self, gas_price_gwei: Optional[int] = None, gas_limit: Optional[int] = None) -> Dict:
        params = {
            "chainId": self.chain_id,
            "from": self.address,
            "nonce": self.web3.eth.get_transaction_count(self.address),
        }
        if gas_price_gwei is not None:
            params["gasPrice"] = self.web3.to_wei(gas_price_gwei, "gwei")
        if gas_limit is not None:
            params["gas"] = int(gas_limit)
        return params

    def _sign_and_send(self, tx: Dict) -> str:
        account = self._require_account()
        signed = self.web3.eth.account.sign_transaction(tx, private_key=account.key)
        # Support both eth-account attribute styles: rawTransaction (camel) and raw_transaction (snake)
        raw_tx = getattr(signed, "rawTransaction", None)
        if raw_tx is None:
            raw_tx = getattr(signed, "raw_transaction", None)
        if raw_tx is None:
            raise RuntimeError("SignedTransaction missing raw transaction bytes")
        tx_hash = self.web3.eth.send_raw_transaction(raw_tx)
        return self.web3.to_hex(tx_hash)

    def approve(
        self,
        token: str,
        amount: int,
        spender: Optional[str] = None,
        gas_price_gwei: Optional[int] = None,
        gas_limit: Optional[int] = None,
    ) -> str:
        """Approve v3 swap router (or custom spender) to spend ERC20 tokens."""
        self._require_account()
        default_spender = self._v3_swap_router_address or self._v3_quoter_address
        if default_spender is None:
            raise RuntimeError("No default v3 router/quoter configured for approvals")
        spender_addr = self.to_checksum(spender or default_spender)
        contract = self.erc20(token)
        tx = contract.functions.approve(spender_addr, int(amount)).build_transaction(self._default_tx_params(gas_price_gwei, gas_limit))
        if gas_limit is None:
            gas_limit = int(self.web3.eth.estimate_gas(tx))
        tx["gas"] = gas_limit
        return self._sign_and_send(tx)

    # v3 swap (single pool)
    def swap_v3_exact_input_single(
        self,
        token_in: str,
        token_out: str,
        fee: int,
        amount_in: int,
        slippage_bps: int = 50,
        recipient: Optional[str] = None,
        deadline_seconds: int = 600,
        sqrt_price_limit_x96: int = 0,
        gas_price_gwei: Optional[int] = None,
        gas_limit: Optional[int] = None,
    ) -> str:
        self._require_account()
        if self._v3_router is None:
            raise RuntimeError("V3 SwapRouter not configured for this chain/network")
        token_in = self.to_checksum(token_in)
        token_out = self.to_checksum(token_out)
        # quote to compute minOut
        q = self.quote_v3_exact_input_single(token_in, token_out, int(fee), int(amount_in), slippage_bps, sqrt_price_limit_x96)
        to_addr = self.to_checksum(recipient or self.address)
        deadline = int(time.time()) + int(deadline_seconds)
        params = (
            token_in,
            token_out,
            int(fee),
            to_addr,
            int(deadline),
            int(amount_in),
            int(q.min_amount_out),
            int(sqrt_price_limit_x96),
        )
        tx = self._v3_router.functions.exactInputSingle(params).build_transaction(self._default_tx_params(gas_price_gwei, gas_limit))
        if gas_limit is None:
            gas_limit = int(self.web3.eth.estimate_gas(tx))
        tx["gas"] = gas_limit
        # Some routers expect msg.value for native input swaps; here we assume ERC20->ERC20
        return self._sign_and_send(tx)

    # v3 swap (multi-hop path)
    def swap_v3_exact_input_path(
        self,
        tokens: List[str],
        fees: List[int],
        amount_in: int,
        slippage_bps: int = 50,
        recipient: Optional[str] = None,
        deadline_seconds: int = 600,
        gas_price_gwei: Optional[int] = None,
        gas_limit: Optional[int] = None,
    ) -> str:
        self._require_account()
        if self._v3_router is None:
            raise RuntimeError("V3 SwapRouter not configured for this chain/network")
        checksummed_tokens = [self.to_checksum(t) for t in tokens]
        path = self._encode_v3_path(checksummed_tokens, fees)
        # quote to compute minOut
        q = self.quote_v3_exact_input_path(checksummed_tokens, fees, int(amount_in), slippage_bps)
        to_addr = self.to_checksum(recipient or self.address)
        deadline = int(time.time()) + int(deadline_seconds)
        params = (
            path,
            to_addr,
            int(deadline),
            int(amount_in),
            int(q.min_amount_out),
        )
        tx = self._v3_router.functions.exactInput(params).build_transaction(self._default_tx_params(gas_price_gwei, gas_limit))
        if gas_limit is None:
            gas_limit = int(self.web3.eth.estimate_gas(tx))
        tx["gas"] = gas_limit
        return self._sign_and_send(tx)


__all__ = ["PancakeSwapClient", "Quote", "QuoteV3"]


