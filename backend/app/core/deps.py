from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.security import decode_user_id
from app.modules.users.models import User

SessionDep = Annotated[Session, Depends(get_session)]
_bearer = HTTPBearer(auto_error=False)  # also adds the "Authorize" button to /docs


def get_current_user(
    session: SessionDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if settings.AUTH_DISABLED:  # emergency demo switch
        fallback = session.exec(select(User).order_by(col(User.id))).first()
        if fallback is not None:
            return fallback
    if creds is None:
        raise AppError(401, "UNAUTHORIZED", "Missing access token")
    try:
        user_id = decode_user_id(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise AppError(401, "UNAUTHORIZED", "Session expired — sign in again") from None
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise AppError(401, "UNAUTHORIZED", "Invalid access token") from None
    user = session.get(User, user_id)
    if user is None:
        raise AppError(401, "UNAUTHORIZED", "User no longer exists")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise AppError(403, "FORBIDDEN", "Admin only")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
