from __future__ import annotations

import builtins

from cli import main as cli_main


def test_cli_main_menu_smoke(monkeypatch):
    seq = iter(["0"])  # immediately exit
    monkeypatch.setattr(builtins, "input", lambda _: next(seq))
    cli_main.main()


def test_cli_wallet_list_empty(monkeypatch, tmp_path):
    # ensure keystore init path references a temp
    monkeypatch.setattr(cli_main, "KEYSTORE_PATH", str(tmp_path / "keystore.json"))
    # Create keystore by simulating create flow, then list wallets and back
    seq = iter([
        # Main menu -> wallet management
        "1",
        # Wallets menu -> list wallets (should be empty)
        "1",
        # Back
        "0",
        # Exit
        "0",
    ])
    monkeypatch.setattr(builtins, "input", lambda _: next(seq))
    # Avoid getpass usage during ensure_keystore when file doesn't exist
    monkeypatch.setattr(cli_main, "ensure_keystore", lambda: cli_main.Keystore(str(tmp_path / "keystore.json")))
    cli_main.main()
