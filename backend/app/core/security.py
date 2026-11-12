"""Cryptographic primitives: password hashing, session tokens, secret encryption."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

_hasher = PasswordHasher()  # argon2id with library defaults (OWASP-compliant)

# Verified against when the account doesn't exist, so response time doesn't
# reveal whether an email is registered.
_DUMMY_HASH = _hasher.hash("timing-equalisation-dummy-password")

MIN_PASSWORD_LENGTH = 10
_COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "1234567890",
        "12345678910",
        "qwertyuiop",
        "azertyuiop",
        "iloveyou12",
        "administrator",
        "admin12345",
        "welcome123",
        "hotel12345",
        "letmein123",
        "changeme123",
        "passw0rd12",
    }
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_policy_violation(password: str) -> str | None:
    """Return an error code if the password is unacceptable, else None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return "PASSWORD_TOO_SHORT"
    if password.lower() in _COMMON_PASSWORDS:
        return "PASSWORD_TOO_COMMON"
    if len(set(password)) < 4:
        return "PASSWORD_TOO_SIMPLE"
    return None


def new_token() -> str:
    """256-bit URL-safe random token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _fernet() -> Fernet:
    return Fernet(get_settings().data_key.encode())


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode()
    except InvalidToken as exc:  # wrong HMS_DATA_KEY or tampered data
        raise ValueError("Unable to decrypt secret: check HMS_DATA_KEY") from exc
