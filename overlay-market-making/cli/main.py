from __future__ import annotations

import getpass
import os
from typing import Optional

from ..core.keystore import Keystore


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


def main() -> None:
    print("Mini-Hummingbot - CLI")
    ks = ensure_keystore()
    while True:
        print("\nMain Menu:")
        print("  1) Wallet management")
        print("  2) Run strategy (coming soon)")
        print("  0) Exit")
        choice = prompt("Select: ")
        if choice == "1":
            menu_wallets(ks)
        elif choice == "2":
            print("Strategies will be available in upcoming steps.")
        elif choice == "0":
            print("Goodbye.")
            break
        else:
            print("Invalid selection.")


if __name__ == "__main__":
    main()


