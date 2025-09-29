from __future__ import annotations

import getpass
import os
from typing import Optional
import threading

from core.keystore import Keystore
from core.token_registry import TokenRegistry
from core.settings_store import SettingsStore
from strategies.dex_simple_swap import DexSimpleSwap, DexSimpleSwapConfig
from strategies.dex_batch_swap import DexBatchSwap, DexBatchSwapConfig
from strategies.dex_pure_market_making import DexPureMarketMaking, DexPureMMConfig
from strategies.dex_dca import DexDCA, DexDCAConfig
from connectors.dex.pancakeswap import PancakeSwapConnector


KEYSTORE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "keystore", "keystore.json"))
SETTINGS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "settings"))
SETTINGS = SettingsStore(SETTINGS_DIR)


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
    # If file exists, verify it loads; if not, offer to recreate
    try:
        ks.load()
        return ks
    except Exception:
        print("Existing keystore appears empty or corrupted.")
        ans = prompt("Recreate keystore now? This will overwrite the file. (yes/no): ").strip().lower()
        if ans not in {"y", "yes"}:
            print("Cannot proceed without a valid keystore.")
            raise SystemExit(1)
        pw1 = getpass.getpass("Create keystore passphrase: ")
        pw2 = getpass.getpass("Confirm passphrase: ")
        if not pw1 or pw1 != pw2:
            print("Passphrases do not match. Aborting.")
            raise SystemExit(1)
        try:
            os.makedirs(os.path.dirname(KEYSTORE_PATH), exist_ok=True)
            # Remove invalid file before initialize
            if os.path.exists(KEYSTORE_PATH):
                os.remove(KEYSTORE_PATH)
        except Exception:
            pass
        ks.initialize(pw1)
        print("Keystore recreated.")
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


def _load_defaults(name: str) -> dict:
    return SETTINGS.load(name) or {}


def _save_defaults(name: str, data: dict) -> None:
    try:
        SETTINGS.save(name, data)
    except Exception:
        pass


def run_dex_simple_swap(ks: Keystore) -> None:
    print("\nDex Simple Swap - One-time market swap on PancakeSwap")
    print("Amounts can be provided in base or quote; we convert under the hood. On PancakeSwap, selling base for quote may display the inverse of base/quote price.")
    defaults = _load_defaults("dex_simple_swap")
    # Network
    chain_str = prompt(f"Chain (56 mainnet / 97 testnet) [{defaults.get('chain_id','56')}]: ").strip() or str(defaults.get("chain_id", "56"))
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
    base = prompt(f"Base symbol (e.g., USDT) [{defaults.get('base','')}]: ").strip().upper() or defaults.get("base", "").upper()
    quote = prompt(f"Quote symbol (e.g., BTCB) [{defaults.get('quote','')}]: ").strip().upper() or defaults.get("quote", "").upper()
    if not base or not quote:
        print("Base and Quote are required.")
        return
    # Amount per wallet
    print("Amount basis: 1) base  2) quote")
    ab = prompt(f"Choose 1 or 2 [{ '1' if defaults.get('amount_is_base', True) else '2' }]: ").strip() or ("1" if defaults.get("amount_is_base", True) else "2")
    if ab not in {"1", "2"}:
        print("Invalid selection.")
        return
    amount_is_base = ab == "1"
    amount: Optional[float] = None
    while amount is None:
        adef = str(defaults.get("amount", ""))
        amount = input_float(f"Enter per-wallet amount [{adef}]: ")
        if amount is None and adef != "":
            try:
                amount = float(adef)
            except Exception:
                amount = None
    # Slippage (default 50 bps = 0.5%)
    sl_def = str(defaults.get("slippage_bps", 50))
    sl_str = prompt(f"Slippage bps [{sl_def}]: ").strip() or sl_def
    try:
        sl_bps = int(sl_str)
    except ValueError:
        print("Invalid slippage.")
        return
    # Confirm
    direction = f"{'spend ' + base if amount_is_base else 'spend ' + quote} -> {'receive ' + quote if amount_is_base else 'receive ' + base}"
    print(f"You will {direction} on {len(private_keys)} wallet(s): {base} <-> {quote}, per-wallet amount={amount} ({'base' if amount_is_base else 'quote'}), slippage={sl_bps} bps")
    use_prev = prompt("Save these as defaults? (yes/no) [yes]: ").strip().lower() or "yes"
    if use_prev in {"y", "yes"}:
        _save_defaults("dex_simple_swap", {"chain_id": chain_id, "base": base, "quote": quote, "amount": amount, "amount_is_base": amount_is_base, "slippage_bps": sl_bps})
    go = prompt("Proceed? (yes/no): ").strip().lower()
    if go not in {"y", "yes"}:
        print("Cancelled.")
        return
    # Execute concurrently per wallet
    def worker(pk: str) -> None:
        try:
            cfg = DexSimpleSwapConfig(
                rpc_url=rpc_url,
                private_key=pk,
                chain_id=chain_id,
                base_symbol=base,
                quote_symbol=quote,
                amount=amount,
                amount_is_base=amount_is_base,
                slippage_bps=sl_bps,
            )
            strat = DexSimpleSwap(cfg)
            tx_hash = strat.run()
            url = ("https://bscscan.com/tx/" if chain_id == 56 else "https://testnet.bscscan.com/tx/") + tx_hash
            print("Swap submitted:", tx_hash)
            print("Explorer:", url)
        except Exception as e:
            print(f"Error: {e}")

    threads = [threading.Thread(target=worker, args=(pk,), daemon=True) for pk in private_keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def run_dex_batch_swap(ks: Keystore) -> None:
    print("\nDex Batch Swap - Ladder of one-sided simulated limit orders on PancakeSwap")
    print("Hint: When selling base for quote, PancakeSwap may show the inverse of base/quote price.")
    defaults = _load_defaults("dex_batch_swap")
    # Network
    chain_str = prompt(f"Chain (56 mainnet / 97 testnet) [{defaults.get('chain_id','56')}]: ").strip() or str(defaults.get("chain_id", "56"))
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
    base = prompt(f"Base symbol (e.g., USDT) [{defaults.get('base','')}]: ").strip().upper() or defaults.get("base", "").upper()
    quote = prompt(f"Quote symbol (e.g., BTCB) [{defaults.get('quote','')}]: ").strip().upper() or defaults.get("quote", "").upper()
    if not base or not quote:
        print("Base and Quote are required.")
        return
    # Direction and amounts
    print("Amount basis: 1) base  2) quote")
    ab = prompt(f"Choose 1 or 2 [{ '1' if defaults.get('amount_is_base', True) else '2' }]: ").strip() or ("1" if defaults.get("amount_is_base", True) else "2")
    if ab not in {"1", "2"}:
        print("Invalid selection.")
        return
    amount_is_base = ab == "1"
    total_amount: Optional[float] = None
    while total_amount is None:
        adef = str(defaults.get("total_amount", ""))
        total_amount = input_float(f"Enter total amount to distribute [{adef}]: ")
        if total_amount is None and adef != "":
            try:
                total_amount = float(adef)
            except Exception:
                total_amount = None
    # Price range
    min_def = str(defaults.get("min_price", ""))
    max_def = str(defaults.get("max_price", ""))
    min_p: Optional[float] = input_float(f"Min trigger price (quote per base) [{min_def}]: ")
    if min_p is None and min_def != "":
        try:
            min_p = float(min_def)
        except Exception:
            pass
    max_p: Optional[float] = input_float(f"Max trigger price (quote per base) [{max_def}]: ")
    if max_p is None and max_def != "":
        try:
            max_p = float(max_def)
        except Exception:
            pass
    if min_p is None or max_p is None or min_p >= max_p:
        print("Invalid price range.")
        return
    # Count and distribution
    num_def = str(defaults.get("num_orders", ""))
    num_str = prompt(f"Number of orders [{num_def}]: ").strip() or num_def
    try:
        num_orders = int(num_str)
        if num_orders <= 0:
            raise ValueError
    except ValueError:
        print("Invalid number of orders.")
        return
    print("Distribution: 1) uniform  2) bell")
    dsel = prompt(f"Choose 1 or 2 [{'1' if defaults.get('distribution','uniform')=='uniform' else '2'}]: ").strip()
    if dsel not in {"1", "2", ""}:
        print("Invalid distribution.")
        return
    distribution = defaults.get("distribution", "uniform") if dsel == "" else ("uniform" if dsel == "1" else "bell")
    # Interval and slippage
    iv_def = str(defaults.get("interval_seconds", 1))
    sl_def = str(defaults.get("slippage_bps", 50))
    iv_str = prompt(f"Tick interval seconds [{iv_def}]: ").strip() or iv_def
    sl_str = prompt(f"Slippage bps [{sl_def}]: ").strip() or sl_def
    try:
        interval_sec = float(iv_str)
        sl_bps = int(sl_str)
    except ValueError:
        print("Invalid interval/slippage.")
        return
    # Confirm
    print(f"Ladder: {num_orders} orders from {min_p} to {max_p}, dist={distribution}, total={total_amount} ({'base' if amount_is_base else 'quote'}) across {len(private_keys)} wallet(s)")
    use_prev = prompt("Save these as defaults? (yes/no) [yes]: ").strip().lower() or "yes"
    if use_prev in {"y", "yes"}:
        _save_defaults("dex_batch_swap", {
            "chain_id": chain_id,
            "base": base,
            "quote": quote,
            "amount_is_base": amount_is_base,
            "total_amount": total_amount,
            "min_price": min_p,
            "max_price": max_p,
            "num_orders": num_orders,
            "distribution": distribution,
            "interval_seconds": interval_sec,
            "slippage_bps": sl_bps,
        })
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
    print("Hint: When selling base for quote, PancakeSwap may show the inverse of base/quote price.")
    defaults = _load_defaults("dex_pure_market_making")
    # Network
    chain_str = prompt(f"Chain (56 mainnet / 97 testnet) [{defaults.get('chain_id','56')}]: ").strip() or str(defaults.get("chain_id", "56"))
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
    base = prompt(f"Base symbol (e.g., USDT) [{defaults.get('base','')}]: ").strip().upper() or defaults.get("base", "").upper()
    quote = prompt(f"Quote symbol (e.g., BTCB) [{defaults.get('quote','')}]: ").strip().upper() or defaults.get("quote", "").upper()
    if not base or not quote:
        print("Base and Quote are required.")
        return
    # Order amount and basis
    print("Amount basis for each order: 1) base  2) quote")
    ab = prompt(f"Choose 1 or 2 [{ '1' if defaults.get('amount_is_base', True) else '2' }]: ").strip() or ("1" if defaults.get("amount_is_base", True) else "2")
    if ab not in {"1", "2"}:
        print("Invalid selection.")
        return
    amount_is_base = ab == "1"
    order_amount: Optional[float] = None
    while order_amount is None:
        adef = str(defaults.get("order_amount", ""))
        order_amount = input_float(f"Per-order amount [{adef}]: ")
        if order_amount is None and adef != "":
            try:
                order_amount = float(adef)
            except Exception:
                order_amount = None
    # Levels and refresh
    up_def = str(defaults.get("upper_percent", ""))
    lo_def = str(defaults.get("lower_percent", ""))
    up = input_float(f"Upper step percent per level (e.g., 0.5) [{up_def}]: ")
    if up is None and up_def != "":
        try:
            up = float(up_def)
        except Exception:
            pass
    lo = input_float(f"Lower step percent per level (e.g., 0.5) [{lo_def}]: ")
    if lo is None and lo_def != "":
        try:
            lo = float(lo_def)
        except Exception:
            pass
    if up is None or lo is None:
        print("Invalid level percents.")
        return
    lev_def = str(defaults.get("levels_each_side", ""))
    lev_str = prompt(f"Levels each side [{lev_def}]: ").strip() or lev_def
    try:
        levels_each_side = int(lev_str)
        if levels_each_side <= 0:
            raise ValueError
    except ValueError:
        print("Invalid number of levels.")
        return
    rf_str = prompt(f"Refresh seconds [{str(defaults.get('refresh_seconds', 60))}]: ").strip() or str(defaults.get("refresh_seconds", 60))
    ti_str = prompt(f"Tick interval seconds [{str(defaults.get('tick_interval_seconds', 1))}]: ").strip() or str(defaults.get("tick_interval_seconds", 1))
    sl_def = str(defaults.get("slippage_bps", 50))
    sl_str = prompt(f"Slippage bps [{sl_def}]: ").strip() or sl_def
    try:
        refresh_seconds = float(rf_str)
        tick_interval = float(ti_str)
        sl_bps = int(sl_str)
    except ValueError:
        print("Invalid refresh/interval/slippage.")
        return
    print(f"Pure MM: {levels_each_side} lvls each side, steps +{up}%/-{lo}% per level, per-order={order_amount} ({'base' if amount_is_base else 'quote'})")
    use_prev = prompt("Save these as defaults? (yes/no) [yes]: ").strip().lower() or "yes"
    if use_prev in {"y", "yes"}:
        _save_defaults("dex_pure_market_making", {
            "chain_id": chain_id,
            "base": base,
            "quote": quote,
            "amount_is_base": amount_is_base,
            "order_amount": order_amount,
            "upper_percent": up,
            "lower_percent": lo,
            "levels_each_side": levels_each_side,
            "refresh_seconds": refresh_seconds,
            "tick_interval_seconds": tick_interval,
            "slippage_bps": sl_bps,
        })
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
    print("Hint: When selling base for quote, PancakeSwap may show the inverse of base/quote price.")
    defaults = _load_defaults("dex_dca")
    # Network
    chain_str = prompt(f"Chain (56 mainnet / 97 testnet) [{defaults.get('chain_id','56')}]: ").strip() or str(defaults.get("chain_id", "56"))
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
    base = prompt(f"Base symbol (e.g., USDT) [{defaults.get('base','')}]: ").strip().upper() or defaults.get("base", "").upper()
    quote = prompt(f"Quote symbol (e.g., BTCB) [{defaults.get('quote','')}]: ").strip().upper() or defaults.get("quote", "").upper()
    if not base or not quote:
        print("Base and Quote are required.")
        return
    # Direction and totals
    print("Total amount basis: 1) base  2) quote")
    ab = prompt(f"Choose 1 or 2 [{ '1' if defaults.get('amount_is_base', True) else '2' }]: ").strip() or ("1" if defaults.get("amount_is_base", True) else "2")
    if ab not in {"1", "2"}:
        print("Invalid selection.")
        return
    amount_is_base = ab == "1"
    total_amount: Optional[float] = None
    while total_amount is None:
        adef = str(defaults.get("total_amount", ""))
        total_amount = input_float(f"Enter total amount [{adef}]: ")
        if total_amount is None and adef != "":
            try:
                total_amount = float(adef)
            except Exception:
                total_amount = None
    # Orders and interval
    num_def = str(defaults.get("num_orders", ""))
    num_str = prompt(f"Number of DCA orders [{num_def}]: ").strip() or num_def
    try:
        num_orders = int(num_str)
        if num_orders <= 0:
            raise ValueError
    except ValueError:
        print("Invalid number of orders.")
        return
    iv_def = str(defaults.get("interval_seconds", 60))
    iv_str = prompt(f"Interval seconds between orders [{iv_def}]: ").strip() or iv_def
    try:
        interval_seconds = float(iv_str)
    except ValueError:
        print("Invalid interval.")
        return
    # Distribution
    dist_def = defaults.get("distribution", "uniform")
    print("Distribution: 1) uniform  2) random_uniform")
    dsel = prompt(f"Choose 1 or 2 [{'1' if dist_def=='uniform' else '2'}]: ").strip()
    if dsel not in {"1", "2", ""}:
        print("Invalid distribution.")
        return
    distribution = dist_def if dsel == "" else ("uniform" if dsel == "1" else "random_uniform")
    # Slippage
    sl_def = str(defaults.get("slippage_bps", 50))
    sl_str = prompt(f"Slippage bps [{sl_def}]: ").strip() or sl_def
    try:
        sl_bps = int(sl_str)
    except ValueError:
        print("Invalid slippage.")
        return
    print(f"DCA: total={total_amount} ({'base' if amount_is_base else 'quote'}), orders={num_orders}, interval={interval_seconds}s, dist={distribution}, wallets={len(private_keys)}")
    use_prev = prompt("Save these as defaults? (yes/no) [yes]: ").strip().lower() or "yes"
    if use_prev in {"y", "yes"}:
        _save_defaults("dex_dca", {
            "chain_id": chain_id,
            "base": base,
            "quote": quote,
            "amount_is_base": amount_is_base,
            "total_amount": total_amount,
            "num_orders": num_orders,
            "interval_seconds": interval_seconds,
            "distribution": distribution,
            "slippage_bps": sl_bps,
        })
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


