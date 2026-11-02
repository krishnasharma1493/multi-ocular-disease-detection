from fastapi import APIRouter
from sqlmodel import col, select

from app.core.deps import CurrentUser, SessionDep
from app.core.errors import AppError
from app.core.schemas import Envelope
from app.modules.reviews.models import Review
from app.modules.reviews.schemas import ReviewCreate, ReviewRead
from app.modules.screenings.models import Screening, ScreeningStatus
from app.utils.ownership import get_owned_or_404
from app.utils.time import utcnow

router = APIRouter(prefix="/screenings/{screening_id}/reviews", tags=["reviews"])


@router.get("", response_model=Envelope[list[ReviewRead]], summary="Reviews of one screening")
def list_reviews(screening_id: int, session: SessionDep, user: CurrentUser):
    get_owned_or_404(session, Screening, screening_id, user.id)
    rows = session.exec(
        select(Review).where(Review.screening_id == screening_id)
        .order_by(col(Review.created_at).desc(), col(Review.id).desc())
    ).all()
    return Envelope(data=[ReviewRead.model_validate(r) for r in rows])


@router.post("", response_model=Envelope[ReviewRead], status_code=201, summary="Record a human read of the result")
def create_review(screening_id: int, body: ReviewCreate, session: SessionDep, user: CurrentUser):
    screening = get_owned_or_404(session, Screening, screening_id, user.id)
    if screening.result is None or screening.status == ScreeningStatus.pending:
        raise AppError(409, "CONFLICT", "Analyze the screening before reviewing it")
    review = Review.model_validate(body, update={"owner_id": user.id, "screening_id": screening_id})
    screening.status = ScreeningStatus.reviewed
    screening.updated_at = utcnow()
    session.add(review)
    session.add(screening)
    session.commit()
    session.refresh(review)
    return Envelope(data=ReviewRead.model_validate(review))
