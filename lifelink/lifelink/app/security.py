"""Password hashing (PBKDF2-SHA256) and JWT helpers."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

import jwt

from .db import db_path

ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 12 * 3600
PBKDF2_ITERATIONS = 150_000


def _secret() -> str:
    env = os.environ.get("LIFELINK_SECRET")
    if env:
        return env
    path = db_path() + ".secret"
    if os.path.exists(path):
        with open(path) as fh:
            return fh.read().strip()
    value = secrets.token_hex(32)
    with open(path, "w") as fh:
        fh.write(value)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, digest)


def create_token(user_id: int, role: str) -> str:
    now = int(time.time())
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
