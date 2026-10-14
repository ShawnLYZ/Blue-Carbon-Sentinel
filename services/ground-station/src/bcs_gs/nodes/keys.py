"""Device keys (addendum A4, A8): 32 random bytes, base64url; only a PBKDF2 hash is ever stored."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ITERATIONS = 200_000
_SCHEME = "pbkdf2_sha256"


def new_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def _derive(key: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", key.encode("utf-8"), salt, iterations)


def hash_key(key: str) -> str:
    """``pbkdf2_sha256$200000$<salt_b64>$<hash_b64>`` with a random 16-byte salt."""
    salt = secrets.token_bytes(16)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return f"{_SCHEME}${ITERATIONS}${b64(salt)}${b64(_derive(key, salt, ITERATIONS))}"


def verify_key(key: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_b64, hash_b64 = stored.split("$")
        if scheme != _SCHEME:
            return False
        expected = base64.b64decode(hash_b64)
        actual = _derive(key, base64.b64decode(salt_b64), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)
