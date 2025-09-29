from __future__ import annotations

import pytest

from core.token_registry import TokenRegistry


def test_registry_missing_symbol_raises(tmp_path, monkeypatch):
    # Point registry to empty tokens file
    (tmp_path / "tokens").mkdir()
    mainnet = tmp_path / "tokens" / "bep20_tokens_mainnet.json"
    mainnet.write_text("{\"tokens\": []}")

    import core.token_registry as tr
    tr.BEP20_MAINNET_FILE = str(mainnet)

    reg = TokenRegistry("mainnet")
    with pytest.raises(KeyError):
        reg.get("FOO")
