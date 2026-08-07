"""Encrypts/decrypts a global backup archive as a single opaque blob.

Password is optional (the caller is responsible for gating that choice
behind a risk-acknowledgment step before calling encrypt_archive with
password=None). When set: Scrypt derives a 256-bit key from the password
and a random salt, then AES-256-GCM encrypts with a random nonce. The
4-byte magic header lets decrypt_archive tell which case it's looking at
without the caller having to track it separately.
"""
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC_ENCRYPTED = b'QLBE'
MAGIC_PLAIN = b'QLBP'
SALT_LEN = 16
NONCE_LEN = 12
KEY_LEN = 32
# Interactive-but-infrequent action (a manual export click, not a login) —
# tuned for roughly sub-second derivation while staying well above
# PBKDF2-class costs.
SCRYPT_N = 2 ** 16
SCRYPT_R = 8
SCRYPT_P = 1


class BackupDecryptError(ValueError):
    """Raised for any archive the caller should treat as a 400: wrong
    password, corrupted bytes, or not a QLSM backup at all."""


def _derive_key(password, salt):
    kdf = Scrypt(salt=salt, length=KEY_LEN, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(password.encode('utf-8'))


def encrypt_archive(data, password):
    """Return the on-disk blob for `data`. `password` of None/'' skips
    encryption entirely (still prefixed so decrypt_archive can tell)."""
    if not password:
        return MAGIC_PLAIN + data
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = _derive_key(password, salt)
    ciphertext = AESGCM(key).encrypt(nonce, data, None)
    return MAGIC_ENCRYPTED + salt + nonce + ciphertext


def decrypt_archive(blob, password):
    """Return the original archive bytes, or raise BackupDecryptError."""
    if blob[:4] == MAGIC_PLAIN:
        return blob[4:]
    if blob[:4] == MAGIC_ENCRYPTED:
        if not password:
            raise BackupDecryptError('This backup is password-protected.')
        header_len = 4 + SALT_LEN + NONCE_LEN
        if len(blob) < header_len:
            raise BackupDecryptError('Backup file is truncated or corrupted.')
        salt = blob[4:4 + SALT_LEN]
        nonce = blob[4 + SALT_LEN:header_len]
        ciphertext = blob[header_len:]
        key = _derive_key(password, salt)
        try:
            return AESGCM(key).decrypt(nonce, ciphertext, None)
        except InvalidTag as e:
            raise BackupDecryptError('Incorrect password or corrupted backup file.') from e
    raise BackupDecryptError('Not a valid QLSM backup file.')
