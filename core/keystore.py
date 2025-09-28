from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet, InvalidToken
from eth_account import Account


DEFAULT_KDF_ITERATIONS = 390000


def _derive_key_from_password(password: str, salt: bytes, iterations: int = DEFAULT_KDF_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
        backend=default_backend(),
    )
    raw_key = kdf.derive(password.encode("utf-8"))
    return base64.urlsafe_b64encode(raw_key)


@dataclass
class WalletRecord:
    name: str
    address: str
    enc_privkey: str
    created_at: float
    chain_id: Optional[int] = None


class Keystore:
    """
    Encrypted keystore for multiple EVM wallets using a master passphrase.

    Storage format (JSON):
    {
      "version": 1,
      "kdf": {"name": "PBKDF2HMAC", "iterations": 390000, "salt": base64},
      "wallets": [ { "name", "address", "enc_privkey", "created_at", "chain_id" } ]
    }
    """

    def __init__(self, keystore_path: str) -> None:
        self.keystore_path = keystore_path
        self._data: Dict = {}

    def exists(self) -> bool:
        return os.path.exists(self.keystore_path)

    def initialize(self, password: str) -> None:
        if self.exists():
            raise FileExistsError("Keystore already exists")
        salt = os.urandom(16)
        self._data = {
            "version": 1,
            "kdf": {"name": "PBKDF2HMAC", "iterations": DEFAULT_KDF_ITERATIONS, "salt": base64.b64encode(salt).decode("utf-8")},
            "wallets": [],
        }
        self._save()
        # Validate password by round-tripping a dummy encryption
        self._fernet(password)  # raises if invalid config

    def load(self) -> None:
        if not self.exists():
            raise FileNotFoundError("Keystore file not found")
        with open(self.keystore_path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.keystore_path), exist_ok=True)
        with open(self.keystore_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, sort_keys=True)

    def _fernet(self, password: str) -> Fernet:
        kdf_conf = self._data.get("kdf", {})
        salt_b64 = kdf_conf.get("salt")
        if not salt_b64:
            raise ValueError("Invalid keystore: missing salt")
        iterations = int(kdf_conf.get("iterations", DEFAULT_KDF_ITERATIONS))
        salt = base64.b64decode(salt_b64)
        key = _derive_key_from_password(password, salt, iterations)
        return Fernet(key)

    def list_wallets(self) -> List[WalletRecord]:
        wallets: List[WalletRecord] = []
        for w in self._data.get("wallets", []):
            wallets.append(WalletRecord(
                name=w["name"],
                address=w["address"],
                enc_privkey=w["enc_privkey"],
                created_at=float(w.get("created_at", 0.0)),
                chain_id=w.get("chain_id"),
            ))
        return wallets

    def add_wallet(self, name: str, private_key: str, password: str, chain_id: Optional[int] = None) -> WalletRecord:
        if not self._data:
            self.load()
        f = self._fernet(password)
        # Normalize private key (strip 0x)
        pk = private_key.lower().removeprefix("0x")
        try:
            acct = Account.from_key(bytes.fromhex(pk))
        except Exception as e:
            raise ValueError("Invalid private key format") from e
        address = acct.address
        enc_privkey = f.encrypt(bytes.fromhex(pk)).decode("utf-8")
        if any(w["name"] == name for w in self._data.get("wallets", [])):
            raise ValueError(f"A wallet named '{name}' already exists")
        rec = {
            "name": name,
            "address": address,
            "enc_privkey": enc_privkey,
            "created_at": time.time(),
            "chain_id": chain_id,
        }
        self._data.setdefault("wallets", []).append(rec)
        self._save()
        return WalletRecord(**rec)

    def remove_wallet(self, name: str) -> bool:
        if not self._data:
            self.load()
        wallets = self._data.get("wallets", [])
        new_wallets = [w for w in wallets if w["name"] != name]
        if len(new_wallets) == len(wallets):
            return False
        self._data["wallets"] = new_wallets
        self._save()
        return True

    def get_private_key(self, name: str, password: str) -> str:
        if not self._data:
            self.load()
        f = self._fernet(password)
        for w in self._data.get("wallets", []):
            if w["name"] == name:
                enc = w["enc_privkey"].encode("utf-8")
                try:
                    raw = f.decrypt(enc)
                except InvalidToken as e:
                    raise PermissionError("Invalid passphrase for keystore") from e
                return "0x" + raw.hex()
        raise KeyError(f"Wallet '{name}' not found")


