from pancakeswap_client import PancakeSwapClient
from credentials import PRIVATE_KEY

RPC_URL = "https://bsc-dataseed.binance.org/"
CHAIN_ID = 56  # 56 = BSC mainnet

LINK = "0xF8A0BF9cF54Bb92F17374d9e9A321E6a111a51bD"   # LINK on BSC
USDT = "0x55d398326f99059fF775485246999027B3197955"  # USDT on BSC
FEE_TIER = 2500   # 0.25%; در صورت نیاز 500 یا 10000 را تست کنید
SLIPPAGE_BPS = 50 # 0.5%

client = PancakeSwapClient(
    rpc_url=RPC_URL,
    private_key=PRIVATE_KEY,
    chain_id=CHAIN_ID,
)

# هدف: دریافت 10 USDT
target_usdt_out_wei = client.to_wei(USDT, 10.0)

# 1) برآورد مقدار LINK لازم: با یک کوئوت اولیه مقیاس می‌کنیم
one_link_wei = 10 ** client.get_decimals(LINK)
q_probe = client.quote_v3_exact_input_single(LINK, USDT, FEE_TIER, one_link_wei, slippage_bps=0)
if q_probe.amount_out == 0:
    raise RuntimeError("No v3 quote for LINK->USDT. Try a different fee tier.")
# تخمین اولیه مقدار ورودی LINK
estimated_link_in = (target_usdt_out_wei * one_link_wei) // q_probe.amount_out
# کمی مارجین برای منحنی قیمت
estimated_link_in = int(estimated_link_in * 1.01)

# 2) کوئوت نهایی با اسلیپیج برای minOut
q_final = client.quote_v3_exact_input_single(LINK, USDT, FEE_TIER, estimated_link_in, slippage_bps=SLIPPAGE_BPS)
min_out_usdt = q_final.min_amount_out

# 3) مانده قبل از سواپ (برای راستی‌آزمایی)
pre_usdt = client.get_balance(USDT)

# 4) اجازه خرج LINK به روتر v3 (در صورت نیاز یک بار)
client.approve(LINK, estimated_link_in)

# 5) انجام سواپ v3
tx_hash = client.swap_v3_exact_input_single(
    LINK, USDT, FEE_TIER, estimated_link_in,
    slippage_bps=SLIPPAGE_BPS
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
