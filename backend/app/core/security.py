import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

ALGORITHM = "HS256"

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32

DUMMY_PASSWORD_HASH = f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${'00' * 16}${'00' * 32}"


def hash_password(plain: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        plain.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        parts = stored.split("$")
        if len(parts) != 6 or parts[0] != "scrypt":
            return False
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected = bytes.fromhex(parts[5])
        derived = hashlib.scrypt(
            plain.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
        return hmac.compare_digest(derived, expected)
    except Exception:
        return False


def check_demo_password(candidate: str) -> bool:
    return hmac.compare_digest(candidate.encode(), settings.DEMO_PASSWORD.encode())


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=settings.JWT_EXPIRES_MINUTES)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_user_id(token: str) -> int:
    """Raises jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError or ValueError on a bad token."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
    return int(payload["sub"])

