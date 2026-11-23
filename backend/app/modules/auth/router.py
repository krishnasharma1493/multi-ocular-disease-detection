from fastapi import APIRouter
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.deps import SessionDep
from app.core.errors import AppError
from app.core.schemas import Envelope
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    check_demo_password,
    create_access_token,
    hash_password,
    verify_password,
)
from app.modules.auth.schemas import LoginIn, LoginOut, RegisterIn
from app.modules.users.models import User
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Envelope[LoginOut], status_code=201, summary="Register user")
def register(body: RegisterIn, session: SessionDep):
    existing = session.exec(select(User).where(func.lower(User.email) == body.email)).first()
    if existing is not None:
        raise AppError(
            409,
            "CONFLICT",
            "An account with this email already exists",
            fields={"email": ["An account with this email already exists"]},
        )
    user = User(
        name=body.name,
        email=body.email,
        is_admin=False,
        password_hash=hash_password(body.password),
    )
    try:
        session.add(user)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise AppError(
            409,
            "CONFLICT",
            "An account with this email already exists",
            fields={"email": ["An account with this email already exists"]},
        ) from None
    session.refresh(user)
    if user.id is None:
        raise AppError(500, "INTERNAL_ERROR", "Failed to create user account")
    return Envelope(data=LoginOut(access_token=create_access_token(user.id), user=UserRead.model_validate(user)))


@router.post("/login", response_model=Envelope[LoginOut], summary="Demo login (JWT)")
def login(body: LoginIn, session: SessionDep):
    user = session.exec(select(User).where(func.lower(User.email) == body.email.strip().lower())).first()
    if user is not None:
        if user.password_hash is not None:
            password_ok = verify_password(body.password, user.password_hash)
        else:
            password_ok = check_demo_password(body.password)
    else:
        verify_password(body.password, DUMMY_PASSWORD_HASH)
        password_ok = False

    if user is None or user.id is None or not password_ok:
        raise AppError(401, "UNAUTHORIZED", "Email or password not recognised")  # one generic message
    return Envelope(data=LoginOut(access_token=create_access_token(user.id), user=UserRead.model_validate(user)))

