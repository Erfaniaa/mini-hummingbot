from pancakeswap_client import PancakeSwapClient
from web3.exceptions import ContractLogicError
from credentials import PRIVATE_KEY

RPC_URL = "https://bsc-dataseed.binance.org/"
CHAIN_ID = 56  # 56 = BSC mainnet

LINK = "0xF8A0BF9cF54Bb92F17374d9e9A321E6a111a51bD"   # LINK on BSC
USDT = "0x55d398326f99059fF775485246999027B3197955"  # USDT on BSC
FEE_TIER = 2500   # default preference; will fall back if pool unavailable
SLIPPAGE_BPS = 50 # 0.5%

client = PancakeSwapClient(
    rpc_url=RPC_URL,
    private_key=PRIVATE_KEY,
    chain_id=CHAIN_ID,
)

# انتخاب گس‌پرایس محافظه‌کارانه بر اساس نود (کمینه 1)
try:
    base_gwei = int(client.web3.eth.gas_price // (10 ** 9))
except Exception:
    base_gwei = 1
GAS_PRICE_GWEI = max(1, base_gwei)

# هدف: دریافت 10 USDT
target_usdt_out_wei = client.to_wei(USDT, 10.0)

# 1) برآورد مقدار LINK لازم: با یک کوئوت اولیه مقیاس می‌کنیم
one_link_wei = 10 ** client.get_decimals(LINK)

# Try multiple v3 fee tiers to avoid Quoter reverts when the desired pool is unavailable
fee_candidates = []
for ft in [FEE_TIER, 500, 2500, 10000]:
    if ft not in fee_candidates:
        fee_candidates.append(ft)

q_probe = None
selected_fee = None
for fee in fee_candidates:
    try:
        qp = client.quote_v3_exact_input_single(LINK, USDT, fee, one_link_wei, slippage_bps=0)
        if qp.amount_out and qp.amount_out > 0:
            q_probe = qp
            selected_fee = fee
            break
    except ContractLogicError:
        continue

if q_probe is None:
    # Fall back to multi-hop via WBNB (common routing asset)
    WBNB = client.DEFAULTS[client.chain_id]["WBNB"]
    # choose candidate fees for each hop
    path_fees_candidates = [
        ([500, 500], "0.05%+0.05%"),
        ([500, 2500], "0.05%+0.25%"),
        ([2500, 500], "0.25%+0.05%"),
        ([2500, 2500], "0.25%+0.25%"),
        ([10000, 500], "1%+0.05%"),
        ([500, 10000], "0.05%+1%"),
    ]
    q_probe = None
    selected_path_fees = None
    for fees_2hop, _desc in path_fees_candidates:
        try:
            qp = client.quote_v3_exact_input_path([LINK, WBNB, USDT], fees_2hop, one_link_wei, slippage_bps=0)
            if qp.amount_out and qp.amount_out > 0:
                q_probe = qp
                selected_path_fees = fees_2hop
                break
        except ContractLogicError:
            continue
    if q_probe is None:
        raise RuntimeError("No available v3 route for LINK->USDT (direct or via WBNB).")
# تخمین اولیه مقدار ورودی LINK
estimated_link_in = (target_usdt_out_wei * one_link_wei) // q_probe.amount_out
# کمی مارجین برای منحنی قیمت
estimated_link_in = int(estimated_link_in * 1.01)

# 2) کوئوت نهایی با اسلیپیج برای minOut
if q_probe.token_in == client.to_checksum(LINK) and q_probe.token_out == client.to_checksum(USDT) and selected_fee is not None:
    q_final = client.quote_v3_exact_input_single(LINK, USDT, selected_fee, estimated_link_in, slippage_bps=SLIPPAGE_BPS)
    min_out_usdt = q_final.min_amount_out
else:
    # multi-hop path via WBNB
    WBNB = client.DEFAULTS[client.chain_id]["WBNB"]
    q_final = client.quote_v3_exact_input_path([LINK, WBNB, USDT], selected_path_fees, estimated_link_in, slippage_bps=SLIPPAGE_BPS)
    min_out_usdt = q_final.min_amount_out

# 3) مانده قبل از سواپ (برای راستی‌آزمایی)
pre_usdt = client.get_balance(USDT)

# 3.5) بررسی مانده LINK و محدود کردن ورودی در صورت کمبود
link_balance = client.get_balance(LINK)
if link_balance <= 0:
    raise RuntimeError("LINK balance is zero; cannot proceed with swap")
if estimated_link_in > link_balance:
    estimated_link_in = link_balance

# 4) اجازه خرج LINK به روتر v3 (در صورت نیاز یک بار)
try:
    allowance = client.get_allowance(LINK)
except Exception:
    allowance = 0
MAX_UINT256 = (1 << 256) - 1
if allowance < estimated_link_in:
    # Try single-step unlimited approve
    approve_tx = client.approve(LINK, MAX_UINT256, gas_price_gwei=GAS_PRICE_GWEI)
    approve_receipt = client.web3.eth.wait_for_transaction_receipt(approve_tx, timeout=180)
    if approve_receipt.status != 1:
        # Fallback to two-step: reset to 0, then set unlimited (some ERC20s require this)
        reset_tx = client.approve(LINK, 0, gas_price_gwei=GAS_PRICE_GWEI)
        client.web3.eth.wait_for_transaction_receipt(reset_tx, timeout=180)
        approve_tx = client.approve(LINK, MAX_UINT256, gas_price_gwei=GAS_PRICE_GWEI)
        client.web3.eth.wait_for_transaction_receipt(approve_tx, timeout=180)
    # re-check
    allowance = client.get_allowance(LINK)
    if allowance < estimated_link_in:
        raise RuntimeError("Allowance after approval is still insufficient")

# 5) انجام سواپ v3
if selected_fee is not None:
    tx_hash = client.swap_v3_exact_input_single(
        LINK, USDT, selected_fee, estimated_link_in,
        slippage_bps=SLIPPAGE_BPS,
        gas_price_gwei=GAS_PRICE_GWEI
    )
else:
    WBNB = client.DEFAULTS[client.chain_id]["WBNB"]
    tx_hash = client.swap_v3_exact_input_path(
        [LINK, WBNB, USDT], selected_path_fees, estimated_link_in,
        slippage_bps=SLIPPAGE_BPS,
        gas_price_gwei=GAS_PRICE_GWEI
    )
print("swap tx hash:", tx_hash)

# 6) پیگیری و بررسی نتیجه تراکنش
receipt = client.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
if receipt.status != 1:
    raise RuntimeError("Swap failed on-chain")

# 7) راستی‌آزمایی با مانده USDT بعد از سواپ
post_usdt = client.get_balance(USDT)
print("USDT gained (wei):", post_usdt - pre_usdt)
print("Min expected out (wei):", min_out_usdt)

# در صورت نیاز: لینک بررسی تراکنش روی BscScan
print(f"https://bscscan.com/tx/{tx_hash}")
