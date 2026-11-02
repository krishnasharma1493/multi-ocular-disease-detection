from fastapi import APIRouter
from sqlmodel import select

from app.core.deps import SessionDep
from app.core.errors import AppError
from app.core.schemas import Envelope
from app.core.security import check_demo_password, create_access_token
from app.modules.auth.schemas import LoginIn, LoginOut
from app.modules.users.models import User
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Envelope[LoginOut], summary="Demo login (JWT)")
def login(body: LoginIn, session: SessionDep):
    user = session.exec(select(User).where(User.email == body.email.strip().lower())).first()
    password_ok = check_demo_password(body.password)  # checked even for unknown emails
    if user is None or user.id is None or not password_ok:
        raise AppError(401, "UNAUTHORIZED", "Email or password not recognised")  # one generic message
    return Envelope(data=LoginOut(access_token=create_access_token(user.id), user=UserRead.model_validate(user)))
