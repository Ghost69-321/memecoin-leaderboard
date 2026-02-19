"""
wallet.py – Ethereum wallet generation and private-key encryption helpers.

Private keys are encrypted with Fernet using a key that is derived from:
  HKDF-SHA256( BOT_MASTER_KEY, salt=str(user_id).encode() )

This gives every Telegram user a different encryption key so that a
compromise of one user's record does not expose others.
"""
import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from eth_account import Account

from config import BOT_MASTER_KEY


def _derive_user_key(user_id: int) -> bytes:
    """Return a 32-byte URL-safe base64-encoded Fernet key for *user_id*.

    Uses HKDF-SHA256 so the derivation is independent for each user ID and
    follows a proper KDF construction (key material, salt, info).
    """
    if not BOT_MASTER_KEY:
        raise RuntimeError("BOT_MASTER_KEY env var is not set")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=str(user_id).encode(),
        info=b"telegram-bump-bot-v1",
    )
    key_bytes = hkdf.derive(BOT_MASTER_KEY.encode())
    return base64.urlsafe_b64encode(key_bytes)


def generate_wallet() -> tuple[str, str]:
    """Create a fresh HD-less Ethereum account.

    Returns
    -------
    (address, private_key_hex)
        *address* is EIP-55 checksummed.
        *private_key_hex* starts with '0x'.
    """
    account = Account.create()
    # account.key is HexBytes; .to_0x_hex() gives the '0x'-prefixed hex string
    return account.address, account.key.to_0x_hex()


def encrypt_private_key(private_key_hex: str, user_id: int) -> str:
    """Encrypt *private_key_hex* using the user-specific Fernet key."""
    fernet = Fernet(_derive_user_key(user_id))
    return fernet.encrypt(private_key_hex.encode()).decode()


def decrypt_private_key(encrypted_key: str, user_id: int) -> str:
    """Decrypt an encrypted private key back to its hex form."""
    fernet = Fernet(_derive_user_key(user_id))
    return fernet.decrypt(encrypted_key.encode()).decode()
