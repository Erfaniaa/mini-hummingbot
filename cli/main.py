from __future__ import annotations

import getpass
import os
from typing import Optional

from core.keystore import Keystore
from core.token_registry import TokenRegistry
from strategies.dex_simple_swap import DexSimpleSwap, DexSimpleSwapConfig
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig
from strategies.dex_pure_market_making import DexPureMarketMaking, DexPureMMConfig
from strategies.dex_dca import DexDCA, DexDCAConfig
from connectors.dex.pancakeswap import PancakeSwapConnector


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


def menu_token_approvals(ks: Keystore) -> None:
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
    symbol = prompt("Token symbol to approve (e.g., USDT or BTCB): ").strip().upper()
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


def run_dex_batch_swap(ks: Keystore) -> None:
    print("\nDex Batch Swap - Ladder of one-sided simulated limit orders on PancakeSwap")
    # Network
    chain_str = prompt("Chain (56 mainnet / 97 testnet) [56]: ").strip() or "56"
    try:
        chain_id = int(chain_str)
    except ValueError:
        print("Invalid chain id.")
        return
    rpc_url = "https://bsc-dataseed.binance.org/" if chain_id == 56 else "https://bsc-testnet.publicnode.com"
    # Wallet selection (multi)
    ks.load()
    wallets = ks.list_wallets()
    if not wallets:
        print("No wallets saved. Add one first in Wallet management.")
        return
    print("Select wallets (comma separated indices, empty=all):")
    for i, w in enumerate(wallets, start=1):
        print(f"  {i}) {w.name} ({w.address[:10]}...)")
    sel = prompt("Enter indices: ").strip()
    selected = []
    if sel == "":
        selected = list(range(1, len(wallets) + 1))
    else:
        try:
            selected = [int(x) for x in sel.split(",")]
            if any(i < 1 or i > len(wallets) for i in selected):
                raise ValueError
        except ValueError:
            print("Invalid selection.")
            return
    pw = getpass.getpass("Keystore passphrase: ")
    private_keys = []
    try:
        for i in selected:
            private_keys.append(ks.get_private_key(wallets[i - 1].name, pw))
    except Exception as e:
        print(f"Error unlocking wallet(s): {e}")
        return
    # Symbols
    base = prompt("Base symbol (e.g., USDT): ").strip().upper()
    quote = prompt("Quote symbol (e.g., BTCB): ").strip().upper()
    if not base or not quote:
        print("Base and Quote are required.")
        return
    # Direction and amounts
    print("Amount basis: 1) base  2) quote")
    ab = prompt("Choose 1 or 2: ").strip()
    if ab not in {"1", "2"}:
        print("Invalid selection.")
        return
    amount_is_base = ab == "1"
    total_amount: Optional[float] = None
    while total_amount is None:
        total_amount = input_float("Enter total amount to distribute: ")
    # Price range
    min_p: Optional[float] = None
    max_p: Optional[float] = None
    while min_p is None:
        min_p = input_float("Min trigger price (quote per base): ")
    while max_p is None:
        max_p = input_float("Max trigger price (quote per base): ")
    if min_p >= max_p:
        print("Min price must be less than max price.")
        return
    # Count and distribution
    num_str = prompt("Number of orders: ").strip()
    try:
        num_orders = int(num_str)
        if num_orders <= 0:
            raise ValueError
    except ValueError:
        print("Invalid number of orders.")
        return
    print("Distribution: 1) uniform  2) bell")
    dsel = prompt("Choose 1 or 2: ").strip()
    if dsel not in {"1", "2"}:
        print("Invalid distribution.")
        return
    distribution = "uniform" if dsel == "1" else "bell"
    # Interval and slippage
    iv_str = prompt("Tick interval seconds [1]: ").strip() or "1"
    sl_str = prompt("Slippage bps [50]: ").strip() or "50"
    try:
        interval_sec = float(iv_str)
        sl_bps = int(sl_str)
    except ValueError:
        print("Invalid interval/slippage.")
        return
    # Confirm
    print(f"Ladder: {num_orders} orders from {min_p} to {max_p}, dist={distribution}, total={total_amount} ({'base' if amount_is_base else 'quote'}) across {len(private_keys)} wallet(s)")
    go = prompt("Start now? (yes/no): ").strip().lower()
    if go not in {"y", "yes"}:
        print("Cancelled.")
        return
    # Start strategy loop
    try:
        cfg = DexBatchSwapConfig(
            rpc_url=rpc_url,
            private_keys=private_keys,
            chain_id=chain_id,
            base_symbol=base,
            quote_symbol=quote,
            total_amount=total_amount,
            amount_is_base=amount_is_base,
            min_price=min_p,
            max_price=max_p,
            num_orders=num_orders,
            distribution=distribution,
            interval_seconds=interval_sec,
            slippage_bps=sl_bps,
        )
        strat = DexBatchSwap(cfg)
        print("Running... Type Ctrl+C to stop.")
        strat.start()
        try:
            while True:
                pass
        except KeyboardInterrupt:
            print("Stopping...")
            strat.stop()
    except Exception as e:
        print(f"Error: {e}")


def run_dex_pure_mm(ks: Keystore) -> None:
    print("\nDex Pure Market Making - Symmetric simulated limit orders around mid price")
    # Network
    chain_str = prompt("Chain (56 mainnet / 97 testnet) [56]: ").strip() or "56"
    try:
        chain_id = int(chain_str)
    except ValueError:
        print("Invalid chain id.")
        return
    rpc_url = "https://bsc-dataseed.binance.org/" if chain_id == 56 else "https://bsc-testnet.publicnode.com"
    # Wallet selection (multi)
    ks.load()
    wallets = ks.list_wallets()
    if not wallets:
        print("No wallets saved. Add one first in Wallet management.")
        return
    print("Select wallets (comma separated indices, empty=all):")
    for i, w in enumerate(wallets, start=1):
        print(f"  {i}) {w.name} ({w.address[:10]}...)")
    sel = prompt("Enter indices: ").strip()
    selected = []
    if sel == "":
        selected = list(range(1, len(wallets) + 1))
    else:
        try:
            selected = [int(x) for x in sel.split(",")]
            if any(i < 1 or i > len(wallets) for i in selected):
                raise ValueError
        except ValueError:
            print("Invalid selection.")
            return
    pw = getpass.getpass("Keystore passphrase: ")
    private_keys = []
    try:
        for i in selected:
            private_keys.append(ks.get_private_key(wallets[i - 1].name, pw))
    except Exception as e:
        print(f"Error unlocking wallet(s): {e}")
        return
    # Symbols
    base = prompt("Base symbol (e.g., USDT): ").strip().upper()
    quote = prompt("Quote symbol (e.g., BTCB): ").strip().upper()
    if not base or not quote:
        print("Base and Quote are required.")
        return
    # Order amount and basis
    print("Amount basis for each order: 1) base  2) quote")
    ab = prompt("Choose 1 or 2: ").strip()
    if ab not in {"1", "2"}:
        print("Invalid selection.")
        return
    amount_is_base = ab == "1"
    order_amount: Optional[float] = None
    while order_amount is None:
        order_amount = input_float("Per-order amount: ")
    # Levels and refresh
    up = input_float("Upper step percent per level (e.g., 0.5): ")
    lo = input_float("Lower step percent per level (e.g., 0.5): ")
    if up is None or lo is None:
        print("Invalid level percents.")
        return
    lev_str = prompt("Levels each side: ").strip()
    try:
        levels_each_side = int(lev_str)
        if levels_each_side <= 0:
            raise ValueError
    except ValueError:
        print("Invalid number of levels.")
        return
    rf_str = prompt("Refresh seconds [60]: ").strip() or "60"
    ti_str = prompt("Tick interval seconds [1]: ").strip() or "1"
    sl_str = prompt("Slippage bps [50]: ").strip() or "50"
    try:
        refresh_seconds = float(rf_str)
        tick_interval = float(ti_str)
        sl_bps = int(sl_str)
    except ValueError:
        print("Invalid refresh/interval/slippage.")
        return
    print(f"Pure MM: {levels_each_side} lvls each side, steps +{up}%/-{lo}% per level, per-order={order_amount} ({'base' if amount_is_base else 'quote'})")
    go = prompt("Start now? (yes/no): ").strip().lower()
    if go not in {"y", "yes"}:
        print("Cancelled.")
        return
    try:
        cfg = DexPureMMConfig(
            rpc_url=rpc_url,
            private_keys=private_keys,
            chain_id=chain_id,
            base_symbol=base,
            quote_symbol=quote,
            upper_percent=float(up),
            lower_percent=float(lo),
            levels_each_side=levels_each_side,
            order_amount=float(order_amount),
            amount_is_base=amount_is_base,
            refresh_seconds=refresh_seconds,
            slippage_bps=sl_bps,
            tick_interval_seconds=tick_interval,
        )
        strat = DexPureMarketMaking(cfg)
        print("Running... Type Ctrl+C to stop.")
        strat.start()
        try:
            while True:
                pass
        except KeyboardInterrupt:
            print("Stopping...")
            strat.stop()
    except Exception as e:
        print(f"Error: {e}")


def run_dex_dca(ks: Keystore) -> None:
    print("\nDex DCA - Periodically swap to complete total allocation over time")
    # Network
    chain_str = prompt("Chain (56 mainnet / 97 testnet) [56]: ").strip() or "56"
    try:
        chain_id = int(chain_str)
    except ValueError:
        print("Invalid chain id.")
        return
    rpc_url = "https://bsc-dataseed.binance.org/" if chain_id == 56 else "https://bsc-testnet.publicnode.com"
    # Wallet selection (multi)
    ks.load()
    wallets = ks.list_wallets()
    if not wallets:
        print("No wallets saved. Add one first in Wallet management.")
        return
    print("Select wallets (comma separated indices, empty=all):")
    for i, w in enumerate(wallets, start=1):
        print(f"  {i}) {w.name} ({w.address[:10]}...)")
    sel = prompt("Enter indices: ").strip()
    selected = []
    if sel == "":
        selected = list(range(1, len(wallets) + 1))
    else:
        try:
            selected = [int(x) for x in sel.split(",")]
            if any(i < 1 or i > len(wallets) for i in selected):
                raise ValueError
        except ValueError:
            print("Invalid selection.")
            return
    pw = getpass.getpass("Keystore passphrase: ")
    private_keys = []
    try:
        for i in selected:
            private_keys.append(ks.get_private_key(wallets[i - 1].name, pw))
    except Exception as e:
        print(f"Error unlocking wallet(s): {e}")
        return
    # Symbols
    base = prompt("Base symbol (e.g., USDT): ").strip().upper()
    quote = prompt("Quote symbol (e.g., BTCB): ").strip().upper()
    if not base or not quote:
        print("Base and Quote are required.")
        return
    # Direction and totals
    print("Total amount basis: 1) base  2) quote")
    ab = prompt("Choose 1 or 2: ").strip()
    if ab not in {"1", "2"}:
        print("Invalid selection.")
        return
    amount_is_base = ab == "1"
    total_amount: Optional[float] = None
    while total_amount is None:
        total_amount = input_float("Enter total amount: ")
    # Orders and interval
    num_str = prompt("Number of DCA orders: ").strip()
    try:
        num_orders = int(num_str)
        if num_orders <= 0:
            raise ValueError
    except ValueError:
        print("Invalid number of orders.")
        return
    iv_str = prompt("Interval seconds between orders [60]: ").strip() or "60"
    try:
        interval_seconds = float(iv_str)
    except ValueError:
        print("Invalid interval.")
        return
    # Distribution
    print("Distribution: 1) uniform  2) random_uniform")
    dsel = prompt("Choose 1 or 2: ").strip()
    if dsel not in {"1", "2"}:
        print("Invalid distribution.")
        return
    distribution = "uniform" if dsel == "1" else "random_uniform"
    # Slippage
    sl_str = prompt("Slippage bps [50]: ").strip() or "50"
    try:
        sl_bps = int(sl_str)
    except ValueError:
        print("Invalid slippage.")
        return
    print(f"DCA: total={total_amount} ({'base' if amount_is_base else 'quote'}), orders={num_orders}, interval={interval_seconds}s, dist={distribution}, wallets={len(private_keys)}")
    go = prompt("Start now? (yes/no): ").strip().lower()
    if go not in {"y", "yes"}:
        print("Cancelled.")
        return
    try:
        cfg = DexDCAConfig(
            rpc_url=rpc_url,
            private_keys=private_keys,
            chain_id=chain_id,
            base_symbol=base,
            quote_symbol=quote,
            total_amount=total_amount,
            amount_is_base=amount_is_base,
            interval_seconds=interval_seconds,
            num_orders=num_orders,
            distribution=distribution,
            slippage_bps=sl_bps,
        )
        strat = DexDCA(cfg)
        print("Running... Type Ctrl+C to stop.")
        strat.start()
        try:
            while True:
                pass
        except KeyboardInterrupt:
            print("Stopping...")
            strat.stop()
    except Exception as e:
        print(f"Error: {e}")


def main() -> None:
    print("Mini-Hummingbot - CLI")
    ks = ensure_keystore()
    while True:
        print("\nMain Menu:")
        print("  1) Wallet management")
        print("  2) Token approvals (PancakeSwap)")
        print("  3) Run strategy")
        print("  0) Exit")
        choice = prompt("Select: ")
        if choice == "1":
            menu_wallets(ks)
        elif choice == "2":
            menu_token_approvals(ks)
        elif choice == "3":
            print("\nStrategies:")
            print("  1) dex_simple_swap - One-time market swap (PancakeSwap)")
            print("  2) dex_batch_swap  - One-sided ladder of swaps (PancakeSwap)")
            print("  3) dex_pure_market_making - Symmetric ladder with periodic refresh (PancakeSwap)")
            print("  4) dex_dca - Dollar-cost averaging with intervals (PancakeSwap)")
            s = prompt("Select: ").strip()
            if s == "1":
                run_dex_simple_swap(ks)
            elif s == "2":
                run_dex_batch_swap(ks)
            elif s == "3":
                run_dex_pure_mm(ks)
            elif s == "4":
                run_dex_dca(ks)
            else:
                print("Invalid selection.")
        elif choice == "0":
            print("Goodbye.")
            break
        else:
            print("Invalid selection.")


if __name__ == "__main__":
    main()


