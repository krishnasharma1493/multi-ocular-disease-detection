import hmac
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

ALGORITHM = "HS256"


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
