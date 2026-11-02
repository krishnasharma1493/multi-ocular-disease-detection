from datetime import datetime

from app.modules.reviews.models import ReviewBase


class ReviewCreate(ReviewBase):
    pass


class ReviewRead(ReviewBase):
    id: int
    owner_id: int
    screening_id: int
    created_at: datetime
