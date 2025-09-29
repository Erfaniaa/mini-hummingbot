from __future__ import annotations

import builtins

from cli import main as cli_main


def test_cli_strategies_menu_smoke(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_main, "KEYSTORE_PATH", str(tmp_path / "keystore.json"))
    seq = iter([
        # Main: choose strategies
        "3",
        # Strategies menu: invalid selection then back by returning to main (we'll just hit enter)
        "",
        # Back to main unknown -> just exit
        "0",
    ])
    monkeypatch.setattr(builtins, "input", lambda _: next(seq))
    monkeypatch.setattr(cli_main, "ensure_keystore", lambda: cli_main.Keystore(str(tmp_path / "keystore.json")))
    cli_main.main()
