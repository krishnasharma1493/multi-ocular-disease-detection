from datetime import datetime
from typing import Literal

from sqlmodel import Field, SQLModel

from app.modules.screenings.models import Eye, ScreeningBase, ScreeningStatus


class ScreeningCreate(SQLModel):
    patient_ref: str = Field(min_length=1, max_length=40)
    eye: Eye = Eye.unknown
    notes: str | None = Field(default=None, max_length=2000)


class ScreeningUpdate(SQLModel):
    patient_ref: str | None = Field(default=None, min_length=1, max_length=40)
    eye: Eye | None = None
    notes: str | None = Field(default=None, max_length=2000)
    status: ScreeningStatus | None = None


class Finding(SQLModel):
    code: str            # "M" | "C" | "G" | "D"
    disease: str         # "Myopia" | "Cataract" | "Glaucoma" | "Diabetic Retinopathy"
    probability: float   # sigmoid output, 0–1
    threshold: float     # tuned on the validation split, stored in the checkpoint
    positive: bool       # probability >= threshold


class AttentionMap(SQLModel):
    """Grad-CAM map for one positive disease, on the cropped square input the model saw."""
    disease: str
    method: Literal["Grad-CAM"] = "Grad-CAM"
    layer: str
    available: bool                          # False when Grad-CAM produced an empty map
    grid: list[list[float]] | None = None    # square grid, values 0–1, row 0 = top of the image


class ScreeningResult(SQLModel):
    screening_id: int
    overall: str         # "Possible: Glaucoma" | "No Myopia, Cataract, Glaucoma or Diabetic Retinopathy detected"
    any_positive: bool
    findings: list[Finding]
    maps: list[AttentionMap] = []
    source: Literal["live", "fixture"]
    latency_ms: int
    disclaimer: str


class ImageMeta(SQLModel):
    name: str
    width: int
    height: int
    type: str
    bytes: int
    sharpness: float | None = None


class ScreeningRead(ScreeningBase):
    id: int
    owner_id: int
    has_image: bool
    image: ImageMeta | None = None
    latest_review: str | None = None   # decision of the newest review: agree | disagree | unsure
    result: ScreeningResult | None = None
    analyzed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ScreeningStats(SQLModel):
    total: int
    by_status: dict[str, int]
    analyzed: int
    flagged: int                  # analyzed with at least one positive finding
    positives: dict[str, int]     # disease name → number of screenings positive for it
    recent: list[ScreeningRead]
