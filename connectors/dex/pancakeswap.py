# TODO: Consider refactoring this file (1116 lines) into separate modules:
# - pancakeswap_client.py: Low-level PancakeSwapClient class
# - pancakeswap_connector.py: High-level PancakeSwapConnector wrapper
# This would improve maintainability without breaking existing functionality.

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Dict, List, Iterable
from decimal import Decimal, getcontext, ROUND_DOWN

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.contract import Contract
# Try multiple POA middleware variants for broad web3 compatibility
try:
    from web3.middleware import ExtraDataToPOAMiddleware  # type: ignore
except Exception:  # pragma: no cover
    ExtraDataToPOAMiddleware = None  # type: ignore
try:
    from web3.middleware.geth_poa import GethPOAMiddleware, geth_poa_middleware  # type: ignore
except Exception:  # pragma: no cover
    try:
        # Older location
        from web3.middleware import geth_poa_middleware  # type: ignore
        GethPOAMiddleware = None  # type: ignore
    except Exception:
        GethPOAMiddleware = None  # type: ignore
        geth_poa_middleware = None  # type: ignore
from web3.exceptions import ContractLogicError

from core.token_registry import TokenRegistry
from connectors.base import ExchangeConnector


# Inlined minimal PancakeSwap v3 client
@dataclass
class QuoteV3:
    token_in: str
    token_out: str
    fee: int
    amount_in: int
    amount_out: int
    min_amount_out: int


class PancakeSwapClient:
    # MEV Protection: Custom defensive strategies to reduce MEV attack surface
    # MEV (Maximal Extractable Value) includes frontrunning, sandwich attacks, etc.
    # 
    # Our implementation uses multiple defensive techniques:
    # 1. Higher gas price (20% premium) for faster inclusion and priority
    # 2. Tight slippage tolerance (limits sandwich attack profitability)
    #
    # Note: We use standard 90s deadline (for ~70s actual swap time + 20s buffer)
    # Shorter deadlines would cause failures rather than improve MEV protection
    # Real MEV protection comes from gas premium and slippage, not deadline
    #
    # BSC lacks true private mempool solutions like Ethereum's Flashbots
    
    ERC20_ABI: List[Dict] = [
        {"constant": True, "inputs": [{"name": "", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
        {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
        {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
        {"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    ]

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
                {"internalType": "address", "name": "tokenIn", "type": "address"},
                {"internalType": "address", "name": "tokenOut", "type": "address"},
                {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                {"internalType": "uint24", "name": "fee", "type": "uint24"},
                {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
            ],
            "name": "quoteExactOutputSingle",
            "outputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
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
        },
        {
            "inputs": [
                {"internalType": "bytes", "name": "path", "type": "bytes"},
                {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
            ],
            "name": "quoteExactOutput",
            "outputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "uint160", "name": "sqrtPriceX96After", "type": "uint160"},
                {"internalType": "uint32", "name": "initializedTicksCrossed", "type": "uint32"},
                {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"},
            ],
            "stateMutability": "view",
            "type": "function",
        },
    ]

    # Minimal PancakeSwap V2 Router ABI subset
    V2_ROUTER_ABI: List[Dict] = [
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"},
            ],
            "name": "swapExactTokensForTokens",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                {"internalType": "uint256", "name": "amountInMax", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"},
            ],
            "name": "swapTokensForExactTokens",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
            ],
            "name": "getAmountsOut",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
            ],
            "name": "getAmountsIn",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "view",
            "type": "function",
        },
    ]

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
            "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
            "stateMutability": "payable",
            "type": "function",
        },
        {
            "inputs": [
                {
                    "components": [
                        {"internalType": "address", "name": "tokenIn", "type": "address"},
                        {"internalType": "address", "name": "tokenOut", "type": "address"},
                        {"internalType": "uint24", "name": "fee", "type": "uint24"},
                        {"internalType": "address", "name": "recipient", "type": "address"},
                        {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountInMaximum", "type": "uint256"},
                        {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
                    ],
                    "internalType": "struct ISwapRouter.ExactOutputSingleParams",
                    "name": "params",
                    "type": "tuple",
                }
            ],
            "name": "exactOutputSingle",
            "outputs": [{"internalType": "uint256", "name": "amountIn", "type": "uint256"}],
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
            "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
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
                        {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountInMaximum", "type": "uint256"},
                    ],
                    "internalType": "struct ISwapRouter.ExactOutputParams",
                    "name": "params",
                    "type": "tuple",
                }
            ],
            "name": "exactOutput",
            "outputs": [{"internalType": "uint256", "name": "amountIn", "type": "uint256"}],
            "stateMutability": "payable",
            "type": "function",
        },
    ]

    DEFAULTS: Dict[int, Dict[str, str]] = {
        56: {
            "WBNB": "0xBB4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
            "V3_SMART_ORDER_ROUTER": "0x1b81D678ffb9C0263b24A97847620C99d213eB14",
            "V3_NFT_MANAGER": "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
            "V3_QUOTER_V2": "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997",
            "V3_SWAP_ROUTER": "0x1b81D678ffb9C0263b24A97847620C99d213eB14",
            "V2_ROUTER": "0x10ED43C718714eb63d5aA57B78B54704E256024E",
        },
        97: {
            "WBNB": "0xae13d989dac2f0debff460ac112a837c89baa7cd",
            "V3_SMART_ORDER_ROUTER": "0x1b81D678ffb9C0263b24A97847620C99d213eB14",
            "V3_NFT_MANAGER": "0x427bF5b37357632377eCbEC9de3626C71A5396c1",
            "V3_QUOTER_V2": "0xbC203d7f83677c7ed3F7acEc959963E7F4ECC5C2",
            "V3_SWAP_ROUTER": "0x1b81D678ffb9C0263b24A97847620C99d213eB14",
            "V2_ROUTER": "0x9Ac64Cc6e4415144C455BD8E4837Fea55603e5c3",
        },
    }

    def __init__(self, rpc_url: str, private_key: Optional[str] = None, chain_id: int = 56, v3_swap_router_address: Optional[str] = None, v3_quoter_address: Optional[str] = None, use_mev_protection: bool = False) -> None:
        # Store MEV protection preference
        self.use_mev_protection = use_mev_protection
        if use_mev_protection:
            print(f"[MEV Protection] Enabled - Using defensive strategies:")
            print(f"  • Higher gas price (20% premium) for faster inclusion and priority")
            print(f"  • Tight slippage tolerance to limit sandwich attack profitability")
            print(f"  • Standard 90s deadline (sufficient for ~70s actual swap time)")
        
        # Add request timeout to avoid indefinite hangs on slow/unresponsive RPCs
        self.web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 15}))
        # Inject POA middleware for BSC-like chains (handles 280-byte extraData)
        try:
            if ExtraDataToPOAMiddleware is not None:
                self.web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            elif geth_poa_middleware is not None:
                self.web3.middleware_onion.inject(geth_poa_middleware, layer=0)
            elif GethPOAMiddleware is not None:
                self.web3.middleware_onion.inject(GethPOAMiddleware, layer=0)
        except Exception:
            # Best-effort; proceed even if injection path differs in this web3 version
            pass
        if not self.web3.is_connected():
            raise RuntimeError("Failed to connect to RPC provider")
        self.chain_id: int = chain_id
        self.defaults: Dict[int, Dict[str, str]] = self.DEFAULTS
        self._account: Optional[LocalAccount] = Account.from_key(private_key) if private_key else None
        self._v3_quoter_address: str = self.to_checksum(v3_quoter_address or self.defaults[chain_id]["V3_QUOTER_V2"]) if "V3_QUOTER_V2" in self.defaults[chain_id] else None
        self._v3_swap_router_address: str = self.to_checksum(v3_swap_router_address or self.defaults[chain_id]["V3_SWAP_ROUTER"]) if "V3_SWAP_ROUTER" in self.defaults[chain_id] else None
        self._v3_quoter: Optional[Contract] = self.web3.eth.contract(address=self._v3_quoter_address, abi=self.QUOTER_V2_ABI) if self._v3_quoter_address else None
        self._v3_router: Optional[Contract] = self.web3.eth.contract(address=self._v3_swap_router_address, abi=self.SWAP_ROUTER_V3_ABI) if self._v3_swap_router_address else None
        # v2 router
        self._v2_router_address: str = self.to_checksum(self.defaults[chain_id].get("V2_ROUTER")) if self.defaults[chain_id].get("V2_ROUTER") else None
        self._v2_router: Optional[Contract] = self.web3.eth.contract(address=self._v2_router_address, abi=self.V2_ROUTER_ABI) if self._v2_router_address else None

    def to_checksum(self, address: str) -> str:
        return self.web3.to_checksum_address(address)

    @property
    def address(self) -> Optional[str]:
        return self._account.address if self._account else None

    def erc20(self, token: str) -> Contract:
        return self.web3.eth.contract(address=self.to_checksum(token), abi=self.ERC20_ABI)

    def get_decimals(self, token: str) -> int:
        return int(self.erc20(token).functions.decimals().call())

    def get_balance(self, token: str, owner: Optional[str] = None) -> int:
        owner_addr = self.to_checksum(owner or (self.address or "0x0000000000000000000000000000000000000000"))
        return int(self.erc20(token).functions.balanceOf(owner_addr).call())

    def get_allowance(self, token: str, spender: Optional[str] = None, owner: Optional[str] = None) -> int:
        owner_addr = self.to_checksum(owner or (self.address or "0x0000000000000000000000000000000000000000"))
        default_spender = self._v3_swap_router_address or self._v3_quoter_address
        spender_addr = self.to_checksum(spender or default_spender)
        return int(self.erc20(token).functions.allowance(owner_addr, spender_addr).call())

    def to_wei(self, token: str, amount_decimal: float) -> int:
        # Use Decimal for precise conversion and round down to avoid exceeding balances
        getcontext().prec = 50
        d = Decimal(self.get_decimals(token))
        value = (Decimal(str(amount_decimal)) * (Decimal(10) ** d)).to_integral_value(rounding=ROUND_DOWN)
        return int(value)

    def from_wei(self, token: str, amount_wei: int) -> float:
        getcontext().prec = 50
        d = Decimal(self.get_decimals(token))
        value = Decimal(int(amount_wei)) / (Decimal(10) ** d)
        return float(value)

    def quote_v3_exact_input_single(self, token_in: str, token_out: str, fee: int, amount_in: int, slippage_bps: int = 50, sqrt_price_limit_x96: int = 0) -> QuoteV3:
        if self._v3_quoter is None:
            raise RuntimeError("V3 Quoter not configured for this chain/network")
        token_in = self.to_checksum(token_in)
        token_out = self.to_checksum(token_out)
        out_amount, _, _, _ = self._v3_quoter.functions.quoteExactInputSingle(token_in, token_out, int(amount_in), int(fee), int(sqrt_price_limit_x96)).call()
        min_out = int(out_amount) * (10_000 - int(slippage_bps)) // 10_000
        return QuoteV3(token_in=token_in, token_out=token_out, fee=int(fee), amount_in=int(amount_in), amount_out=int(out_amount), min_amount_out=min_out)

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

    def quote_v3_exact_input_path(self, tokens: List[str], fees: List[int], amount_in: int, slippage_bps: int = 50) -> QuoteV3:
        if self._v3_quoter is None:
            raise RuntimeError("V3 Quoter not configured for this chain/network")
        checksummed_tokens = [self.to_checksum(t) for t in tokens]
        path = self._encode_v3_path(checksummed_tokens, fees)
        out_amount, _, _, _ = self._v3_quoter.functions.quoteExactInput(path, int(amount_in)).call()
        min_out = int(out_amount) * (10_000 - int(slippage_bps)) // 10_000
        return QuoteV3(token_in=checksummed_tokens[0], token_out=checksummed_tokens[-1], fee=0, amount_in=int(amount_in), amount_out=int(out_amount), min_amount_out=min_out)

    def _require_account(self) -> LocalAccount:
        if self._account is None:
            raise RuntimeError("Private key is required for this operation")
        return self._account

    def _default_tx_params(self, gas_price_gwei: Optional[int] = None, gas_limit: Optional[int] = None) -> Dict:
        # Use 'pending' to include pending transactions in nonce calculation
        # This prevents "nonce too low" errors when multiple transactions are sent quickly
        params = {"chainId": self.chain_id, "from": self.address, "nonce": self.web3.eth.get_transaction_count(self.address, 'pending')}
        
        # MEV Protection: Use higher gas price for faster inclusion
        if hasattr(self, 'use_mev_protection') and self.use_mev_protection:
            if gas_price_gwei is None:
                # Get current gas price and add 20% premium for priority
                current_gas_price = self.web3.eth.gas_price
                params["gasPrice"] = int(current_gas_price * 1.20)
            else:
                # User-specified gas price + 20% premium
                params["gasPrice"] = self.web3.to_wei(int(gas_price_gwei * 1.20), "gwei")
        else:
            if gas_price_gwei is not None:
                params["gasPrice"] = self.web3.to_wei(gas_price_gwei, "gwei")
        
        if gas_limit is not None:
            params["gas"] = int(gas_limit)
        return params

    def _sign_and_send(self, tx: Dict) -> str:
        account = self._require_account()
        signed = self.web3.eth.account.sign_transaction(tx, private_key=account.key)
        raw_tx = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
        if raw_tx is None:
            raise RuntimeError("SignedTransaction missing raw transaction bytes")
        tx_hash = self.web3.eth.send_raw_transaction(raw_tx)
        return self.web3.to_hex(tx_hash)

    # ----------------------------
    # v2 helpers
    # ----------------------------
    def v2_get_amounts_out(self, path_tokens: List[str], amount_in: int) -> List[int]:
        if self._v2_router is None:
            raise RuntimeError("V2 Router not configured for this chain/network")
        path = [self.to_checksum(t) for t in path_tokens]
        return list(self._v2_router.functions.getAmountsOut(int(amount_in), path).call())

    def v2_get_amounts_in(self, path_tokens: List[str], amount_out: int) -> List[int]:
        if self._v2_router is None:
            raise RuntimeError("V2 Router not configured for this chain/network")
        path = [self.to_checksum(t) for t in path_tokens]
        return list(self._v2_router.functions.getAmountsIn(int(amount_out), path).call())

    def v2_swap_exact_tokens_for_tokens(self, path_tokens: List[str], amount_in: int, min_out: int, gas_price_gwei: Optional[int] = None, gas_limit: Optional[int] = None) -> str:
        self._require_account()
        if self._v2_router is None:
            raise RuntimeError("V2 Router not configured for this chain/network")
        path = [self.to_checksum(t) for t in path_tokens]
        to_addr = self.to_checksum(self.address)
        # Use 90s deadline for ~70s actual swap time + 20s buffer
        # MEV protection comes from higher gas price (20% premium) and tight slippage
        # Not from shorter deadline (which would cause transaction failures)
        deadline_duration = 90
        deadline = int(time.time()) + deadline_duration
        tx = self._v2_router.functions.swapExactTokensForTokens(int(amount_in), int(min_out), path, to_addr, int(deadline)).build_transaction(self._default_tx_params(gas_price_gwei, gas_limit))
        if gas_limit is None:
            gas_limit = int(self.web3.eth.estimate_gas(tx))
        tx["gas"] = gas_limit
        return self._sign_and_send(tx)

    def v2_swap_tokens_for_exact_tokens(self, path_tokens: List[str], amount_out: int, amount_in_max: int, gas_price_gwei: Optional[int] = None, gas_limit: Optional[int] = None) -> str:
        self._require_account()
        if self._v2_router is None:
            raise RuntimeError("V2 Router not configured for this chain/network")
        path = [self.to_checksum(t) for t in path_tokens]
        to_addr = self.to_checksum(self.address)
        # Use 90s deadline for ~70s actual swap time + 20s buffer
        # MEV protection comes from higher gas price (20% premium) and tight slippage
        # Not from shorter deadline (which would cause transaction failures)
        deadline_duration = 90
        deadline = int(time.time()) + deadline_duration
        tx = self._v2_router.functions.swapTokensForExactTokens(int(amount_out), int(amount_in_max), path, to_addr, int(deadline)).build_transaction(self._default_tx_params(gas_price_gwei, gas_limit))
        if gas_limit is None:
            gas_limit = int(self.web3.eth.estimate_gas(tx))
        tx["gas"] = gas_limit
        return self._sign_and_send(tx)

    def approve(self, token: str, amount: int, spender: Optional[str] = None, gas_price_gwei: Optional[int] = None, gas_limit: Optional[int] = None) -> str:
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

    def swap_v3_exact_input_single(self, token_in: str, token_out: str, fee: int, amount_in: int, slippage_bps: int = 50, recipient: Optional[str] = None, deadline_seconds: int = 90, sqrt_price_limit_x96: int = 0, gas_price_gwei: Optional[int] = None, gas_limit: Optional[int] = None, _mev_override_deadline: bool = False) -> str:
        self._require_account()
        if self._v3_router is None:
            raise RuntimeError("V3 SwapRouter not configured for this chain/network")
        token_in = self.to_checksum(token_in)
        token_out = self.to_checksum(token_out)
        q = self.quote_v3_exact_input_single(token_in, token_out, int(fee), int(amount_in), slippage_bps, sqrt_price_limit_x96)
        to_addr = self.to_checksum(recipient or self.address)
        # Use standard 90s deadline for reliable execution
        # MEV protection comes from gas premium, not shorter deadline
        if deadline_seconds < 90:
            deadline_seconds = 90
        deadline = int(time.time()) + int(deadline_seconds)
        params = (token_in, token_out, int(fee), to_addr, int(deadline), int(amount_in), int(q.min_amount_out), int(sqrt_price_limit_x96))
        tx = self._v3_router.functions.exactInputSingle(params).build_transaction(self._default_tx_params(gas_price_gwei, gas_limit))
        if gas_limit is None:
            gas_limit = int(self.web3.eth.estimate_gas(tx))
        tx["gas"] = gas_limit
        return self._sign_and_send(tx)

    def swap_v3_exact_input_path(self, tokens: List[str], fees: List[int], amount_in: int, slippage_bps: int = 50, recipient: Optional[str] = None, deadline_seconds: int = 90, gas_price_gwei: Optional[int] = None, gas_limit: Optional[int] = None, _mev_override_deadline: bool = False) -> str:
        self._require_account()
        if self._v3_router is None:
            raise RuntimeError("V3 SwapRouter not configured for this chain/network")
        checksummed_tokens = [self.to_checksum(t) for t in tokens]
        path = self._encode_v3_path(checksummed_tokens, fees)
        q = self.quote_v3_exact_input_path(checksummed_tokens, fees, int(amount_in), slippage_bps)
        to_addr = self.to_checksum(recipient or self.address)
        # Use standard 90s deadline for reliable execution
        # MEV protection comes from gas premium, not shorter deadline
        if deadline_seconds < 90:
            deadline_seconds = 90
        deadline = int(time.time()) + int(deadline_seconds)
        params = (path, to_addr, int(deadline), int(amount_in), int(q.min_amount_out))
        tx = self._v3_router.functions.exactInput(params).build_transaction(self._default_tx_params(gas_price_gwei, gas_limit))
        if gas_limit is None:
            gas_limit = int(self.web3.eth.estimate_gas(tx))
        tx["gas"] = gas_limit
        return self._sign_and_send(tx)


class PancakeSwapConnector(ExchangeConnector):
    """
    Thin wrapper over PancakeSwapClient to expose a strategy-friendly API.

    Price convention: returns quote per 1 base, computed using a small probe amount.
    """

    def __init__(
        self,
        rpc_url: str,
        private_key: str,
        chain_id: int = 56,
        network: str = "mainnet",
        default_fee_tier: int = 2500,
        client: Optional[PancakeSwapClient] = None,
        use_mev_protection: bool = False,
    ) -> None:
        self.registry = TokenRegistry("testnet" if chain_id == 97 else network)
        self.client = client or PancakeSwapClient(rpc_url=rpc_url, private_key=private_key, chain_id=chain_id, use_mev_protection=use_mev_protection)
        self.chain_id = chain_id
        self.default_fee_tier = default_fee_tier
        self.use_mev_protection = use_mev_protection

    def _resolve(self, symbol: str) -> str:
        return self.registry.get(symbol).address

    def _fee_sets(self, edges: int) -> Iterable[List[int]]:
        tiers = [500, 2500, 10000]
        # include 0.01% tier (100) as Pancake V3 supports it for some pairs
        if 100 not in tiers:
            tiers = [100] + tiers
        if edges <= 0:
            return []
        if edges == 1:
            for t in tiers:
                yield [t]
            return
        # Cartesian product for up to 3 edges (27 combos)
        def prod(opts: List[int], k: int, prefix: Optional[List[int]] = None):
            prefix = prefix or []
            if k == 0:
                yield list(prefix)
                return
            for v in opts:
                prefix.append(v)
                yield from prod(opts, k - 1, prefix)
                prefix.pop()
        yield from prod(tiers, edges)

    def _limited_paths(self, token_in: str, token_out: str) -> List[List[str]]:
        """Return a limited set of likely paths for performance.

        Includes up to 2-hop paths using WBNB and USDC only.
        """
        paths: List[List[str]] = []
        try:
            wbnb = self.client.DEFAULTS[self.chain_id]["WBNB"]
        except Exception:
            wbnb = None
        try:
            usdc = self._resolve("USDC")
        except Exception:
            usdc = None
        if wbnb is not None and wbnb not in (token_in, token_out):
            paths.append([token_in, wbnb, token_out])
        if usdc is not None and usdc not in (token_in, token_out):
            paths.append([token_in, usdc, token_out])
        if wbnb is not None and usdc is not None and len({token_in, wbnb, usdc, token_out}) == 4:
            paths.append([token_in, wbnb, usdc, token_out])
            paths.append([token_in, usdc, wbnb, token_out])
        return paths

    def _quote_amount_out_limited(self, token_in: str, token_out: str, amount_in_wei: int) -> int:
        """Best-effort amountOut using limited routes (fast). Returns wei."""
        # v3 direct (common fees)
        for fee in [self.default_fee_tier, 100, 500, 2500, 10000]:
            try:
                q = self.client.quote_v3_exact_input_single(token_in, token_out, int(fee), int(amount_in_wei), slippage_bps=0)
                if int(q.amount_out) > 0:
                    return int(q.amount_out)
            except Exception:
                continue
        # v3 limited paths
        for path_tokens in self._limited_paths(token_in, token_out):
            edges = len(path_tokens) - 1
            for fees in self._fee_sets(edges):
                try:
                    q = self.client.quote_v3_exact_input_path(path_tokens, list(fees), int(amount_in_wei), slippage_bps=0)
                    if int(q.amount_out) > 0:
                        return int(q.amount_out)
                except Exception:
                    continue
        # v2 limited paths
        for path_tokens in self._limited_paths(token_in, token_out):
            try:
                amounts = self.client.v2_get_amounts_out(path_tokens, int(amount_in_wei))
                out_amount = int(amounts[-1])
                if out_amount > 0:
                    return out_amount
            except Exception:
                continue
        return 0

    def get_price_side(self, base_symbol: str, quote_symbol: str, side: str, fast: bool = False) -> float:
        """Return price as BASE/QUOTE in the user's conventional sense (quote per 1 base).

        side: 'sell' (spend base → receive quote) or 'buy' (spend quote → receive base)
        If fast=True, only limited/quick routes are used; otherwise full get_price fallback is applied.
        """
        base = self._resolve(base_symbol)
        quote = self._resolve(quote_symbol)
        if side not in ("sell", "buy"):
            raise ValueError("side must be 'sell' or 'buy'")
        if side == "sell":
            # tokenIn = base; we want quote_per_base (QUOTE/BASE) directly
            one_base = 10 ** self.client.get_decimals(base)
            if fast:
                out_q = self._quote_amount_out_limited(base, quote, int(one_base))
                if out_q <= 0:
                    raise RuntimeError("No route for fast sell price")
                quote_per_base = self.client.from_wei(quote, out_q)
            else:
                qpb = self._try_paths_quote(base, quote, int(one_base))
                if qpb is None:
                    # try v2 limited
                    out_q = self._quote_amount_out_limited(base, quote, int(one_base))
                    if out_q <= 0:
                        raise RuntimeError("No route for sell price")
                    quote_per_base = self.client.from_wei(quote, out_q)
                else:
                    quote_per_base = float(qpb)
            if quote_per_base <= 0:
                raise RuntimeError("Invalid sell price")
            return quote_per_base
        else:
            # side == 'buy': tokenIn = quote; compute base_per_quote then invert to quote_per_base
            one_quote = 10 ** self.client.get_decimals(quote)
            if fast:
                out_b = self._quote_amount_out_limited(quote, base, int(one_quote))
                if out_b <= 0:
                    raise RuntimeError("No route for fast buy price")
                base_per_quote = self.client.from_wei(base, out_b)
            else:
                # reuse v3/v2 limited by swapping token_in/out
                out_b = self._quote_amount_out_limited(quote, base, int(one_quote))
                if out_b <= 0:
                    # As a slow fallback, try full get_price (quote/base)
                    qpb = self.get_price(base_symbol, quote_symbol)
                    base_per_quote = 1.0 / float(qpb)
                else:
                    base_per_quote = self.client.from_wei(base, out_b)
            if base_per_quote <= 0:
                raise RuntimeError("Invalid buy price")
            quote_per_base = 1.0 / base_per_quote
            return quote_per_base
    def _try_paths_quote(self, base: str, quote: str, one_base: int) -> Optional[float]:
        # Direct
        for fee in [self.default_fee_tier, 100, 500, 2500, 10000]:
            try:
                q = self.client.quote_v3_exact_input_single(base, quote, fee, one_base, slippage_bps=0)
                if q.amount_out > 0:
                    return self.client.from_wei(quote, q.amount_out)
            except ContractLogicError:
                continue
        # Multi-hop paths via limited intermediaries (WBNB/USDC)
        for path_tokens in self._limited_paths(base, quote):
            edges = len(path_tokens) - 1
            for fees in self._fee_sets(edges):
                try:
                    q = self.client.quote_v3_exact_input_path(path_tokens, list(fees), one_base, slippage_bps=0)
                    if q.amount_out > 0:
                        return self.client.from_wei(quote, q.amount_out)
                except ContractLogicError:
                    continue
        return None

    def get_price(self, base_symbol: str, quote_symbol: str) -> float:
        base = self._resolve(base_symbol)
        quote = self._resolve(quote_symbol)
        # Returns quote per 1 base; PancakeSwap quoter is queried with token_in=base -> token_out=quote.
        # When selling base for quote, this is the inverse convention from a SELL UI perspective.
        one_base = 10 ** self.client.get_decimals(base)
        px = self._try_paths_quote(base, quote, one_base)
        if px is not None:
            return px
        # v2 fallback pricing via getAmountsOut across limited paths
        for path_tokens in self._limited_paths(base, quote):
            try:
                amounts = self.client.v2_get_amounts_out(path_tokens, int(one_base))
                out_amount = amounts[-1]
                if out_amount > 0:
                    return self.client.from_wei(quote, out_amount)
            except Exception:
                continue
        raise RuntimeError(f"No route available for {base_symbol}/{quote_symbol}")

    def get_price_fast(self, base_symbol: str, quote_symbol: str) -> float:
        """Try fastest routes first, then fallback to full search.

        Order:
        1) v2 getAmountsOut direct and 2-hop WBNB/USDC
        2) v3 direct 500 fee
        3) v3 2-hop (WBNB/USDC) with 500-500 fees
        4) fallback to get_price (full)
        """
        base = self._resolve(base_symbol)
        quote = self._resolve(quote_symbol)
        one_base = 10 ** self.client.get_decimals(base)
        # v2 quick try
        quick_paths = [[base, quote]] + self._limited_paths(base, quote)
        for path_tokens in quick_paths:
            try:
                amounts = self.client.v2_get_amounts_out(path_tokens, int(one_base))
                out_amount = amounts[-1]
                if out_amount > 0:
                    return self.client.from_wei(quote, out_amount)
            except Exception:
                pass
        # v3 direct 100 then 500
        try:
            q = self.client.quote_v3_exact_input_single(base, quote, 100, int(one_base), slippage_bps=0)
            if q.amount_out > 0:
                return self.client.from_wei(quote, q.amount_out)
        except Exception:
            pass
        try:
            q = self.client.quote_v3_exact_input_single(base, quote, 500, int(one_base), slippage_bps=0)
            if q.amount_out > 0:
                return self.client.from_wei(quote, q.amount_out)
        except Exception:
            pass
        # v3 2-hop 500-500
        try:
            wbnb = self.client.DEFAULTS[self.chain_id]["WBNB"]
        except Exception:
            wbnb = None
        try:
            usdc = self._resolve("USDC")
        except Exception:
            usdc = None
        for mid in [wbnb, usdc]:
            if mid and mid not in (base, quote):
                try:
                    q = self.client.quote_v3_exact_input_path([base, mid, quote], [500, 500], int(one_base), slippage_bps=0)
                    if q.amount_out > 0:
                        return self.client.from_wei(quote, q.amount_out)
                except Exception:
                    pass
        # full
        return self.get_price(base_symbol, quote_symbol)

    def get_balance(self, symbol: str) -> float:
        token = self._resolve(symbol)
        bal_wei = self.client.get_balance(token)
        return self.client.from_wei(token, bal_wei)

    def approve(self, symbol: str, amount: float) -> str:
        token = self._resolve(symbol)
        amount_q = self.quantize_amount(symbol, amount)
        amount_wei = self.client.to_wei(token, amount_q)
        return self.client.approve(token, int(amount_wei))

    def approve_unlimited(self, symbol: str) -> str:
        token = self._resolve(symbol)
        max_uint = (1 << 256) - 1
        return self.client.approve(token, max_uint)

    def get_allowance(self, symbol: str) -> int:
        token = self._resolve(symbol)
        return int(self.client.get_allowance(token))

    def quantize_amount(self, symbol: str, amount: float) -> float:
        # Round down to token decimals to avoid overspending
        getcontext().prec = 50
        decimals = self.get_token_decimals(symbol)
        q = (Decimal(str(amount)) * (Decimal(10) ** Decimal(decimals))).to_integral_value(rounding=ROUND_DOWN)
        return float(q / (Decimal(10) ** Decimal(decimals)))

    def get_token_decimals(self, symbol: str) -> int:
        token = self._resolve(symbol)
        return int(self.client.get_decimals(token))

    def market_swap(self, base_symbol: str, quote_symbol: str, amount: float, amount_is_base: bool, slippage_bps: int = 50, side: Optional[str] = None) -> str:
        base = self._resolve(base_symbol)
        quote = self._resolve(quote_symbol)
        # Determine direction: 'side' takes precedence if provided
        if side is not None:
            if side not in ("sell", "buy"):
                raise ValueError("side must be 'sell' or 'buy'")
            spend_is_base = True if side == "sell" else False
        else:
            spend_is_base = bool(amount_is_base)
        # If spending base: spend base to get quote. Otherwise spend quote to get base.
        token_in_symbol = base_symbol if spend_is_base else quote_symbol
        token_in = base if spend_is_base else quote
        token_out = quote if spend_is_base else base
        amount_q = self.quantize_amount(token_in_symbol, amount)
        amount_in_wei = self.client.to_wei(token_in, amount_q)

        # Ensure sufficient balance pre-check to avoid revert
        bal_wei = self.client.get_balance(token_in)
        if bal_wei < amount_in_wei:
            raise RuntimeError("Insufficient token balance for swap")
        # Ensure allowance
        allowance = self.client.get_allowance(token_in)
        if int(allowance) < int(amount_in_wei):
            self.client.approve(token_in, int(amount_in_wei))

        # Quote all candidates and pick best expected out
        fee_candidates = [100, self.default_fee_tier, 500, 2500, 10000]
        best_kind = None  # 'v3_single' | 'v3_path' | 'v2'
        best_value = 0
        best_data = None
        # V3 direct
        for fee in fee_candidates:
            try:
                q = self.client.quote_v3_exact_input_single(token_in, token_out, int(fee), int(amount_in_wei), slippage_bps=0)
                out_amt = int(q.amount_out)
                if out_amt > best_value:
                    best_value = out_amt
                    best_kind = 'v3_single'
                    best_data = {'fee': int(fee)}
            except Exception:
                continue
        # V3 limited paths
        for path_tokens in self._limited_paths(token_in, token_out):
            edges = len(path_tokens) - 1
            for fees in self._fee_sets(edges):
                try:
                    q = self.client.quote_v3_exact_input_path(path_tokens, list(fees), int(amount_in_wei), slippage_bps=0)
                    out_amt = int(q.amount_out)
                    if out_amt > best_value:
                        best_value = out_amt
                        best_kind = 'v3_path'
                        best_data = {'tokens': list(path_tokens), 'fees': list(fees)}
                except Exception:
                    continue
        # V2 limited paths
        v2_best = None
        for path_tokens in self._limited_paths(token_in, token_out):
            try:
                amounts = self.client.v2_get_amounts_out(path_tokens, int(amount_in_wei))
                out_amt = int(amounts[-1])
                if out_amt > best_value:
                    best_value = out_amt
                    best_kind = 'v2'
                    v2_best = list(path_tokens)
            except Exception:
                continue
        if best_kind is None or best_value <= 0:
            raise RuntimeError("No available route for swap")
        # Execute chosen route
        try:
            if best_kind == 'v3_single':
                fee = int(best_data['fee'])  # type: ignore[index]
                return self.client.swap_v3_exact_input_single(token_in, token_out, fee, int(amount_in_wei), slippage_bps=slippage_bps)
            if best_kind == 'v3_path':
                tokens = list(best_data['tokens'])  # type: ignore[index]
                fees = list(best_data['fees'])      # type: ignore[index]
                return self.client.swap_v3_exact_input_path(tokens, fees, int(amount_in_wei), slippage_bps=slippage_bps)
            # V2 path
            v2_router = self.client._v2_router_address
            if v2_router:
                current_allowance = self.client.get_allowance(token_in, spender=v2_router)
                if int(current_allowance) < int(amount_in_wei):
                    self.client.approve(token_in, int(amount_in_wei), spender=v2_router)
            amounts = self.client.v2_get_amounts_out(v2_best, int(amount_in_wei))  # type: ignore[arg-type]
            min_out = int(amounts[-1]) * (10_000 - int(slippage_bps)) // 10_000
            return self.client.v2_swap_exact_tokens_for_tokens(v2_best, int(amount_in_wei), int(min_out))  # type: ignore[arg-type]
        except Exception as e:
            raise RuntimeError(f"Swap failed: {e}")

    def tx_explorer_url(self, tx_hash: str) -> str:
        base = "https://bscscan.com/tx/" if self.chain_id == 56 else "https://testnet.bscscan.com/tx/"
        return f"{base}{tx_hash}"

    # ----------------------------
    # Quotes (best-effort using same order as market_swap)
    # ----------------------------
    def quote_best_out(self, token_in_symbol: str, token_out_symbol: str, amount_in: float) -> int:
        """Return best out amount (wei) using the same route order as market_swap.

        token symbols follow connector convention (e.g., "BTCB", "USDT").
        amount_in is in human units (not wei) for token_in_symbol.
        """
        token_in = self._resolve(token_in_symbol)
        token_out = self._resolve(token_out_symbol)
        amount_in_wei = self.client.to_wei(token_in, self.quantize_amount(token_in_symbol, float(amount_in)))

        # v3 direct
        for fee in [self.default_fee_tier, 500, 2500, 10000]:
            try:
                q = self.client.quote_v3_exact_input_single(token_in, token_out, int(fee), int(amount_in_wei), slippage_bps=0)
                if int(q.amount_out) > 0:
                    return int(q.amount_out)
            except Exception:
                continue
        # v3 limited paths
        for path_tokens in self._limited_paths(token_in, token_out):
            edges = len(path_tokens) - 1
            for fees in self._fee_sets(edges):
                try:
                    q = self.client.quote_v3_exact_input_path(path_tokens, list(fees), int(amount_in_wei), slippage_bps=0)
                    if int(q.amount_out) > 0:
                        return int(q.amount_out)
                except Exception:
                    continue
        # v2 limited paths
        for path_tokens in self._limited_paths(token_in, token_out):
            try:
                amounts = self.client.v2_get_amounts_out(path_tokens, int(amount_in_wei))
                out_amount = int(amounts[-1])
                if out_amount > 0:
                    return out_amount
            except Exception:
                continue
        return 0

    # ----------------------------
    # Exact-output helpers (target amount_out in wei)
    # ----------------------------
    def quote_best_in_for_exact_out(self, token_in_symbol: str, token_out_symbol: str, amount_out_wei: int) -> int:
        """Return required input amount (wei) to receive target amount_out (wei) via v3/v2 limited paths.

        Tries v3 direct/path quoteExactOutput first (including 0.01% fee), then falls back to v2 getAmountsIn.
        Returns 0 if no path.
        """
        token_in = self._resolve(token_in_symbol)
        token_out = self._resolve(token_out_symbol)
        best_in = 0
        # v3 direct exact output
        for fee in [100, self.default_fee_tier, 500, 2500, 10000]:
            try:
                amt_in, _, _, _ = self.client._v3_quoter.functions.quoteExactOutputSingle(
                    self.client.to_checksum(token_in),
                    self.client.to_checksum(token_out),
                    int(amount_out_wei),
                    int(fee),
                    0,
                ).call()
                amt_in = int(amt_in)
                if amt_in > 0 and (best_in == 0 or amt_in < best_in):
                    best_in = amt_in
            except Exception:
                continue
        # v3 path exact output (path must be reversed: tokenOut -> tokenIn)
        for path_tokens in self._limited_paths(token_in, token_out):
            edges = len(path_tokens) - 1
            for fees in self._fee_sets(edges):
                try:
                    # Reverse path and fees for exact-output
                    reversed_path = list(reversed(path_tokens))
                    reversed_fees = list(reversed(list(fees)))
                    path = self.client._encode_v3_path(reversed_path, reversed_fees)
                    amt_in, _, _, _ = self.client._v3_quoter.functions.quoteExactOutput(path, int(amount_out_wei)).call()
                    amt_in = int(amt_in)
                    if amt_in > 0 and (best_in == 0 or amt_in < best_in):
                        best_in = amt_in
                except Exception:
                    continue
        for path_tokens in self._limited_paths(token_in, token_out):
            try:
                amounts = self.client.v2_get_amounts_in(path_tokens, int(amount_out_wei))
                amt_in = int(amounts[0])
                if amt_in > 0 and (best_in == 0 or amt_in < best_in):
                    best_in = amt_in
            except Exception:
                continue
        return best_in

    def estimate_in_for_exact_out(self, token_in_symbol: str, token_out_symbol: str, amount_out_human: float) -> float:
        """Return estimated input amount in human units to receive target output amount (human units).

        Uses v3/v2 quoter helpers. Returns 0.0 if no path.
        """
        token_out = self._resolve(token_out_symbol)
        out_wei = self.client.to_wei(token_out, self.quantize_amount(token_out_symbol, float(amount_out_human)))
        req_in_wei = self.quote_best_in_for_exact_out(token_in_symbol, token_out_symbol, int(out_wei))
        if req_in_wei <= 0:
            return 0.0
        token_in = self._resolve(token_in_symbol)
        return self.client.from_wei(token_in, int(req_in_wei))

    def swap_exact_out(self, token_in_symbol: str, token_out_symbol: str, target_out_amount: float, slippage_bps: int = 50) -> str:
        """Swap to receive an exact target amount_out in token_out_symbol.

        Uses v2 limited paths with getAmountsIn + swapTokensForExactTokens.
        amount_in_max is padded by slippage_bps.
        """
        token_in = self._resolve(token_in_symbol)
        token_out = self._resolve(token_out_symbol)
        amount_out_wei = self.client.to_wei(token_out, self.quantize_amount(token_out_symbol, float(target_out_amount)))
        required_in = self.quote_best_in_for_exact_out(token_in_symbol, token_out_symbol, int(amount_out_wei))
        if required_in <= 0:
            # Fallback: estimate via regular price (simpler and more reliable)
            try:
                # Get price and calculate estimated input
                qpb = self.get_price(token_in_symbol, token_out_symbol)
                if qpb <= 0:
                    raise RuntimeError(f"Cannot get valid price for {token_in_symbol}/{token_out_symbol}")
                
                # Convert output amount to human units and calculate input
                amount_out_human = self.client.from_wei(token_out, int(amount_out_wei))
                est_in_human = amount_out_human / float(qpb)
                
                # Convert back to wei
                required_in = self.client.to_wei(token_in, self.quantize_amount(token_in_symbol, float(est_in_human)))
            except Exception as e:
                raise RuntimeError(f"Cannot estimate input for exact-output swap: {e}")
        amount_in_max = int(required_in) * (10_000 + int(slippage_bps) + 50) // 10_000
        # Ensure allowance to v3 router (for v3 exactOutputSingle), and to v2 router (for v2 fallback)
        try:
            v3_router = self.client._v3_swap_router_address
            if v3_router:
                current_allowance_v3 = self.client.get_allowance(self._resolve(token_in_symbol), spender=v3_router)
                if int(current_allowance_v3) < int(amount_in_max):
                    self.client.approve(self._resolve(token_in_symbol), int(amount_in_max), spender=v3_router)
        except Exception:
            pass
        # Ensure allowance to v2 router
        v2_router = self.client._v2_router_address
        current_allowance = self.client.get_allowance(token_in, spender=v2_router)
        if int(current_allowance) < int(amount_in_max):
            self.client.approve(token_in, int(amount_in_max), spender=v2_router)
        # Try v3 exactOutputSingle with best fees first
        for fee in [100, self.default_fee_tier, 500, 2500, 10000]:
            try:
                if self.client._v3_router is not None:
                    to_addr = self.client.to_checksum(self.client.address)
                    # MEV Protection: Use shorter deadline (60s vs 90s default)
                    # 90s provides buffer for typical 70s swap time + network congestion
                    # 60s with MEV protection reduces mempool exposure
                    deadline_duration = 60 if self.use_mev_protection else 90
                    deadline = int(time.time()) + deadline_duration
                    params = (token_in, token_out, int(fee), to_addr, int(deadline), int(amount_out_wei), int(amount_in_max), 0)
                    tx = self.client._v3_router.functions.exactOutputSingle(params).build_transaction(self.client._default_tx_params())
                    gas_limit = int(self.client.web3.eth.estimate_gas(tx))
                    tx["gas"] = gas_limit
                    tx_hash = self.client._sign_and_send(tx)
                    return tx_hash
            except Exception:
                continue
        # Try v3 exactOutput via limited multi-hop paths (path must be reversed: tokenOut -> tokenIn)
        for path_tokens in self._limited_paths(token_in, token_out):
            edges = len(path_tokens) - 1
            for fees in self._fee_sets(edges):
                try:
                    if self.client._v3_router is not None:
                        # Reverse path and fees for exact-output
                        reversed_path = list(reversed(path_tokens))
                        reversed_fees = list(reversed(list(fees)))
                        path = self.client._encode_v3_path(reversed_path, reversed_fees)
                        to_addr = self.client.to_checksum(self.client.address)
                        # MEV Protection: Use shorter deadline (60s vs 90s default)
                        # 90s provides buffer for typical 70s swap time + network congestion
                        # 60s with MEV protection reduces mempool exposure
                        deadline_duration = 60 if self.use_mev_protection else 90
                        deadline = int(time.time()) + deadline_duration
                        params = (path, to_addr, int(deadline), int(amount_out_wei), int(amount_in_max))
                        tx = self.client._v3_router.functions.exactOutput(params).build_transaction(self.client._default_tx_params())
                        gas_limit = int(self.client.web3.eth.estimate_gas(tx))
                        tx["gas"] = gas_limit
                        tx_hash = self.client._sign_and_send(tx)
                        return tx_hash
                except Exception:
                    continue
        # Execute on best first limited v2 path where required_in matches
        for path_tokens in self._limited_paths(token_in, token_out):
            try:
                amounts = self.client.v2_get_amounts_in(path_tokens, int(amount_out_wei))
                if int(amounts[0]) == int(required_in):
                    return self.client.v2_swap_tokens_for_exact_tokens(path_tokens, int(amount_out_wei), int(amount_in_max))
            except Exception:
                continue
        # Fallback on any path yielding same out
        for path_tokens in self._limited_paths(token_in, token_out):
            try:
                return self.client.v2_swap_tokens_for_exact_tokens(path_tokens, int(amount_out_wei), int(amount_in_max))
            except Exception:
                continue
        raise RuntimeError("Exact-output swap failed on all limited v2 paths")


