"""
Wallet management menu.
"""
import getpass
from core.keystore import Keystore
from cli.utils import prompt


def menu_wallets(ks: Keystore) -> None:
    """Wallet management menu."""
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
            priv = getpass.getpass("Paste private key (with or without 0x): ").strip()
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

