from __future__ import annotations

import os
import tempfile

from core.keystore import Keystore


def test_keystore_lifecycle():
    with tempfile.TemporaryDirectory() as td:
        ks_path = os.path.join(td, "keystore.json")
        ks = Keystore(ks_path)
        password = "test-pass-123"
        ks.initialize(password)
        assert ks.exists()
        ks.load()
        assert ks.list_wallets() == []

        # random test private key (do not use on-chain)
        priv = "0x" + ("11" * 32)
        rec = ks.add_wallet("w1", priv, password)
        assert rec.name == "w1"
        assert rec.address.startswith("0x")

        wallets = ks.list_wallets()
        assert len(wallets) == 1

        got_pk = ks.get_private_key("w1", password)
        assert got_pk.lower() == priv.lower()

        ok = ks.remove_wallet("w1")
        assert ok is True
        assert ks.list_wallets() == []
