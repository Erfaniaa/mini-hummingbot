"""
Token approval menu.
"""
import getpass
from core.keystore import Keystore
from connectors.dex.pancakeswap import PancakeSwapConnector
from cli.utils import prompt, input_float


def menu_token_approvals(ks: Keystore) -> None:
    """Token approval menu for PancakeSwap."""
    print("\nToken Approvals - Approve router to spend tokens on PancakeSwap")
    chain_str = prompt("Chain (56 mainnet / 97 testnet) [56]: ").strip() or "56"
    try:
        chain_id = int(chain_str)
    except ValueError:
        print("Invalid chain id.")
        return
    rpc_url = "https://bsc-dataseed.binance.org/" if chain_id == 56 else "https://bsc-testnet.publicnode.com"
    ks.load()
    wallets = ks.list_wallets()
    if not wallets:
        print("No wallets saved.")
        return
    print("Select wallet:")
    for i, w in enumerate(wallets, start=1):
        print(f"  {i}) {w.name} ({w.address[:10]}...)")
    idx_str = prompt("Enter number: ").strip()
    try:
        idx = int(idx_str)
        if idx < 1 or idx > len(wallets):
            raise ValueError
    except ValueError:
        print("Invalid selection.")
        return
    w = wallets[idx - 1]
    pw = getpass.getpass("Keystore passphrase: ")
    try:
        pk = ks.get_private_key(w.name, pw)
    except Exception as e:
        print(f"Error unlocking wallet: {e}")
        return
    symbol = prompt("Token symbol to approve (BTCB or USDT): ").strip().upper()
    if not symbol:
        print("Symbol required.")
        return
    conn = PancakeSwapConnector(rpc_url=rpc_url, private_key=pk, chain_id=chain_id)
    print("1) Approve unlimited  2) Approve specific amount  3) Check allowance  0) Back")
    sel = prompt("Select: ").strip()
    try:
        if sel == "1":
            tx = conn.approve_unlimited(symbol)
            url = ("https://bscscan.com/tx/" if chain_id == 56 else "https://testnet.bscscan.com/tx/") + tx
            print("Approve submitted:", tx)
            print("Explorer:", url)
        elif sel == "2":
            amt = input_float("Amount to approve: ")
            if amt is None or amt <= 0:
                print("Invalid amount.")
                return
            tx = conn.approve(symbol, float(amt))
            url = ("https://bscscan.com/tx/" if chain_id == 56 else "https://testnet.bscscan.com/tx/") + tx
            print("Approve submitted:", tx)
            print("Explorer:", url)
        elif sel == "3":
            alw = conn.get_allowance(symbol)
            print(f"Allowance (wei-like units): {alw}")
        else:
            return
    except Exception as e:
        print(f"Error: {e}")

