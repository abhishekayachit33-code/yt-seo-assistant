"""Password hashing and JWT issuance/verification.

JWT, not server-side sessions: the frontend is a separate Next.js deployment
(likely a different origin/host from this API), so a cookie-session shared
between them is awkward. A bearer token the frontend stores (via NextAuth's
own session handling) and sends on every request avoids that coupling.
"""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

# Must be set in production -- a default here would mean anyone who reads
# this file could forge tokens for any user. Failing loudly beats a
# convenient default that becomes a real vulnerability if ever deployed
# without DOING the one required setup step.
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_MINUTES = 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    # bcrypt's algorithm silently ignores anything past 72 bytes rather than
    # erroring -- truncate ourselves so "loginworks123...(80 chars)" doesn't
    # quietly become a much weaker, shorter effective password.
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))


def create_access_token(user_id: int, email: str) -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not set")
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRES_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not set")
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
