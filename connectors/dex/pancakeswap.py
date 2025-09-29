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
    ]

    DEFAULTS: Dict[int, Dict[str, str]] = {
        56: {
            "WBNB": "0xBB4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
            "V3_SMART_ORDER_ROUTER": "0x1b81D678ffb9C0263b24A97847620C99d213eB14",
            "V3_NFT_MANAGER": "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
            "V3_QUOTER_V2": "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997",
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

    def __init__(self, rpc_url: str, private_key: Optional[str] = None, chain_id: int = 56, v3_swap_router_address: Optional[str] = None, v3_quoter_address: Optional[str] = None) -> None:
        self.web3 = Web3(Web3.HTTPProvider(rpc_url))
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
        params = {"chainId": self.chain_id, "from": self.address, "nonce": self.web3.eth.get_transaction_count(self.address)}
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

    def swap_v3_exact_input_single(self, token_in: str, token_out: str, fee: int, amount_in: int, slippage_bps: int = 50, recipient: Optional[str] = None, deadline_seconds: int = 600, sqrt_price_limit_x96: int = 0, gas_price_gwei: Optional[int] = None, gas_limit: Optional[int] = None) -> str:
        self._require_account()
        if self._v3_router is None:
            raise RuntimeError("V3 SwapRouter not configured for this chain/network")
        token_in = self.to_checksum(token_in)
        token_out = self.to_checksum(token_out)
        q = self.quote_v3_exact_input_single(token_in, token_out, int(fee), int(amount_in), slippage_bps, sqrt_price_limit_x96)
        to_addr = self.to_checksum(recipient or self.address)
        deadline = int(time.time()) + int(deadline_seconds)
        params = (token_in, token_out, int(fee), to_addr, int(deadline), int(amount_in), int(q.min_amount_out), int(sqrt_price_limit_x96))
        tx = self._v3_router.functions.exactInputSingle(params).build_transaction(self._default_tx_params(gas_price_gwei, gas_limit))
        if gas_limit is None:
            gas_limit = int(self.web3.eth.estimate_gas(tx))
        tx["gas"] = gas_limit
        return self._sign_and_send(tx)

    def swap_v3_exact_input_path(self, tokens: List[str], fees: List[int], amount_in: int, slippage_bps: int = 50, recipient: Optional[str] = None, deadline_seconds: int = 600, gas_price_gwei: Optional[int] = None, gas_limit: Optional[int] = None) -> str:
        self._require_account()
        if self._v3_router is None:
            raise RuntimeError("V3 SwapRouter not configured for this chain/network")
        checksummed_tokens = [self.to_checksum(t) for t in tokens]
        path = self._encode_v3_path(checksummed_tokens, fees)
        q = self.quote_v3_exact_input_path(checksummed_tokens, fees, int(amount_in), slippage_bps)
        to_addr = self.to_checksum(recipient or self.address)
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
    ) -> None:
        self.registry = TokenRegistry("testnet" if chain_id == 97 else network)
        self.client = client or PancakeSwapClient(rpc_url=rpc_url, private_key=private_key, chain_id=chain_id)
        self.chain_id = chain_id
        self.default_fee_tier = default_fee_tier

    def _resolve(self, symbol: str) -> str:
        return self.registry.get(symbol).address

    def _fee_sets(self, edges: int) -> Iterable[List[int]]:
        tiers = [500, 2500, 10000]
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

    def _try_paths_quote(self, base: str, quote: str, one_base: int) -> Optional[float]:
        # Direct
        for fee in [self.default_fee_tier, 500, 2500, 10000]:
            try:
                q = self.client.quote_v3_exact_input_single(base, quote, fee, one_base, slippage_bps=0)
                if q.amount_out > 0:
                    return self.client.from_wei(quote, q.amount_out)
            except ContractLogicError:
                continue
        # Multi-hop via WBNB / USDC and combos
        tokens_to_try: List[List[str]] = []
        wbnb = self.client.DEFAULTS[self.chain_id]["WBNB"]
        tokens_to_try.append([base, wbnb, quote])
        # Try USDC if present in registry
        try:
            usdc = self._resolve("USDC")
            tokens_to_try.append([base, usdc, quote])
            tokens_to_try.append([base, wbnb, usdc, quote])
            tokens_to_try.append([base, usdc, wbnb, quote])
        except Exception:
            pass
        for path_tokens in tokens_to_try:
            edges = len(path_tokens) - 1
            for fees in self._fee_sets(edges):
                try:
                    q = self.client.quote_v3_exact_input_path(path_tokens, list(fees), one_base, slippage_bps=0)
                    if q.amount_out > 0:
                        return self.client.from_wei(path_tokens[-1], q.amount_out)
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
        raise RuntimeError(f"No route available for {base_symbol}/{quote_symbol}")

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

    def market_swap(self, base_symbol: str, quote_symbol: str, amount: float, amount_is_base: bool, slippage_bps: int = 50) -> str:
        base = self._resolve(base_symbol)
        quote = self._resolve(quote_symbol)
        # If amount_is_base: we spend base to get quote. Otherwise we spend quote to get base.
        token_in_symbol = base_symbol if amount_is_base else quote_symbol
        token_in = base if amount_is_base else quote
        token_out = quote if amount_is_base else base
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

        # Try direct path first; then multi-hop via WBNB/USDC; finally reverse
        fee_candidates = [self.default_fee_tier, 500, 2500, 10000]
        try:
            # Direct pools
            for fee in fee_candidates:
                try:
                    return self.client.swap_v3_exact_input_single(token_in, token_out, fee, int(amount_in_wei), slippage_bps=slippage_bps)
                except ContractLogicError:
                    continue
            # Multi-hop sequences
            wbnb = self.client.DEFAULTS[self.chain_id]["WBNB"]
            paths: List[List[str]] = [[token_in, wbnb, token_out]]
            # USDC paths if available
            try:
                usdc = self._resolve("USDC")
                paths.append([token_in, usdc, token_out])
                paths.append([token_in, wbnb, usdc, token_out])
                paths.append([token_in, usdc, wbnb, token_out])
            except Exception:
                pass
            for path_tokens in paths:
                edges = len(path_tokens) - 1
                for fees in self._fee_sets(edges):
                    try:
                        return self.client.swap_v3_exact_input_path(path_tokens, list(fees), int(amount_in_wei), slippage_bps=slippage_bps)
                    except ContractLogicError:
                        continue
            # Reverse fallback
            rev_in, rev_out = token_out, token_in
            for fee in fee_candidates:
                try:
                    return self.client.swap_v3_exact_input_single(rev_in, rev_out, fee, int(amount_in_wei), slippage_bps=slippage_bps)
                except ContractLogicError:
                    continue
            for path_tokens in ([[rev_in, wbnb, rev_out]]):
                edges = len(path_tokens) - 1
                for fees in self._fee_sets(edges):
                    try:
                        return self.client.swap_v3_exact_input_path(path_tokens, list(fees), int(amount_in_wei), slippage_bps=slippage_bps)
                    except ContractLogicError:
                        continue
        except Exception as e:
            raise RuntimeError(f"Swap failed: {e}")
        raise RuntimeError("No available route for swap")

    def tx_explorer_url(self, tx_hash: str) -> str:
        base = "https://bscscan.com/tx/" if self.chain_id == 56 else "https://testnet.bscscan.com/tx/"
        return f"{base}{tx_hash}"


