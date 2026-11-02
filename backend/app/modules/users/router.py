from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.core.schemas import Envelope
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=Envelope[UserRead], summary="Current user")
def read_me(user: CurrentUser):
    return Envelope(data=UserRead.model_validate(user))
