from __future__ import annotations

import getpass
import os
from typing import Optional

from ..core.keystore import Keystore
from ..core.token_registry import TokenRegistry
from ..strategies.dex_simple_swap import DexSimpleSwap, DexSimpleSwapConfig


KEYSTORE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "keystore", "keystore.json"))


def prompt(prompt_text: str) -> str:
    try:
        return input(prompt_text)
    except EOFError:
        return ""


def ensure_keystore() -> Keystore:
    ks = Keystore(KEYSTORE_PATH)
    if not ks.exists():
        print("No keystore found. Let's create one.")
        pw1 = getpass.getpass("Create keystore passphrase: ")
        pw2 = getpass.getpass("Confirm passphrase: ")
        if not pw1 or pw1 != pw2:
            print("Passphrases do not match. Aborting.")
            raise SystemExit(1)
        ks.initialize(pw1)
        print("Keystore created.")
    return ks


def menu_wallets(ks: Keystore) -> None:
    while True:
        print("\nWallets:")
        print("  1) List wallets")
        print("  2) Add wallet")
        print("  3) Remove wallet")
        print("  0) Back")
        choice = prompt("Select: ")
        if choice == "1":
            try:
                ks.load()
                wallets = ks.list_wallets()
                if not wallets:
                    print("No wallets saved.")
                else:
                    for w in wallets:
                        print(f"- {w.name} ({w.address})")
            except Exception as e:
                print(f"Error: {e}")
        elif choice == "2":
            name = prompt("Enter wallet name: ").strip()
            if not name:
                print("Name is required.")
                continue
            priv = getpass.getpass("Paste private key (0x...): ").strip()
            if not priv:
                print("Private key is required.")
                continue
            pw = getpass.getpass("Keystore passphrase: ")
            try:
                ks.load()
                rec = ks.add_wallet(name=name, private_key=priv, password=pw)
                print(f"Added wallet '{rec.name}' with address {rec.address}")
            except Exception as e:
                print(f"Error: {e}")
        elif choice == "3":
            name = prompt("Enter wallet name to remove: ")
            try:
                ks.load()
                ok = ks.remove_wallet(name)
                print("Removed." if ok else "No such wallet.")
            except Exception as e:
                print(f"Error: {e}")
        elif choice == "0":
            return
        else:
            print("Invalid selection.")


def input_float(prompt_text: str) -> Optional[float]:
    val = prompt(prompt_text).strip()
    try:
        if val == "":
            return None
        return float(val)
    except ValueError:
        print("Invalid number.")
        return None


def run_dex_simple_swap(ks: Keystore) -> None:
    print("\nDex Simple Swap - One-time market swap on PancakeSwap")
    # Network
    chain_str = prompt("Chain (56 mainnet / 97 testnet) [56]: ").strip() or "56"
    try:
        chain_id = int(chain_str)
    except ValueError:
        print("Invalid chain id.")
        return
    rpc_url = "https://bsc-dataseed.binance.org/" if chain_id == 56 else "https://bsc-testnet.publicnode.com"
    # Wallet selection
    ks.load()
    wallets = ks.list_wallets()
    if not wallets:
        print("No wallets saved. Add one first in Wallet management.")
        return
    print("Select wallet to use:")
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
    wallet = wallets[idx - 1]
    pw = getpass.getpass("Keystore passphrase: ")
    try:
        private_key = ks.get_private_key(wallet.name, pw)
    except Exception as e:
        print(f"Error unlocking wallet: {e}")
        return
    # Symbols
    base = prompt("Base symbol (e.g., USDT): ").strip().upper()
    quote = prompt("Quote symbol (e.g., BTCB): ").strip().upper()
    if not base or not quote:
        print("Base and Quote are required.")
        return
    # Amount
    print("Amount basis: 1) base  2) quote")
    ab = prompt("Choose 1 or 2: ").strip()
    if ab not in {"1", "2"}:
        print("Invalid selection.")
        return
    amount_is_base = ab == "1"
    amount: Optional[float] = None
    while amount is None:
        amount = input_float("Enter amount: ")
    # Slippage
    sl_str = prompt("Slippage bps [50]: ").strip() or "50"
    try:
        sl_bps = int(sl_str)
    except ValueError:
        print("Invalid slippage.")
        return
    # Confirm
    print(f"You will swap {'BASE->QUOTE' if amount_is_base else 'QUOTE->BASE'}: {base} <-> {quote}, amount={amount} ({'base' if amount_is_base else 'quote'}), slippage={sl_bps} bps")
    go = prompt("Proceed? (yes/no): ").strip().lower()
    if go not in {"y", "yes"}:
        print("Cancelled.")
        return
    # Execute
    try:
        cfg = DexSimpleSwapConfig(
            rpc_url=rpc_url,
            private_key=private_key,
            chain_id=chain_id,
            base_symbol=base,
            quote_symbol=quote,
            amount=amount,
            amount_is_base=amount_is_base,
            slippage_bps=sl_bps,
        )
        strat = DexSimpleSwap(cfg)
        tx_hash = strat.run()
        url = "https://bscscan.com/tx/" + tx_hash if chain_id == 56 else "https://testnet.bscscan.com/tx/" + tx_hash
        print("Swap submitted:", tx_hash)
        print("Explorer:", url)
    except Exception as e:
        print(f"Error: {e}")


def main() -> None:
    print("Mini-Hummingbot - CLI")
    ks = ensure_keystore()
    while True:
        print("\nMain Menu:")
        print("  1) Wallet management")
        print("  2) Run strategy")
        print("  0) Exit")
        choice = prompt("Select: ")
        if choice == "1":
            menu_wallets(ks)
        elif choice == "2":
            print("\nStrategies:")
            print("  1) dex_simple_swap - One-time market swap (PancakeSwap)")
            s = prompt("Select: ").strip()
            if s == "1":
                run_dex_simple_swap(ks)
            else:
                print("Invalid selection.")
        elif choice == "0":
            print("Goodbye.")
            break
        else:
            print("Invalid selection.")


if __name__ == "__main__":
    main()


