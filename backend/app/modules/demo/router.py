from fastapi import APIRouter

from app.core.deps import AdminUser
from app.core.schemas import Envelope
from app.seed import reset_and_seed

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/reset", response_model=Envelope[dict[str, str]], summary="Drop and reseed demo data (admin)")
def reset_demo(_: AdminUser):
    reset_and_seed()
    return Envelope(data={"status": "reset"})
