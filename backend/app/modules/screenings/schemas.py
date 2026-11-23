from datetime import datetime
from typing import Literal

from pydantic import model_validator
from sqlmodel import Field, SQLModel

from app.modules.screenings.models import Eye, ImageSource, ScreeningBase, ScreeningStatus


class ScreeningCreate(SQLModel):
    patient_ref: str = Field(default="Me", min_length=1, max_length=40)
    eye: Eye = Eye.unknown
    image_source: ImageSource = ImageSource.unknown
    notes: str | None = Field(default=None, max_length=2000)


class ScreeningUpdate(SQLModel):
    patient_ref: str | None = Field(default=None, min_length=1, max_length=40)
    eye: Eye | None = None
    image_source: ImageSource | None = None  # changing it removes the uploaded photo and its result
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


class ModelInfo(SQLModel):
    """Which model produced a result, so every stored result can be traced to one checkpoint."""
    run_id: str | None = None             # training run id saved in the checkpoint; None for older checkpoints
    checkpoint_sha256: str | None = None  # hash of the checkpoint file
    model_name: str | None = None
    img_size: int | None = None
    labels: list[str] = []
    thresholds: list[float] = []          # the decision thresholds used for this result
    temperature: list[float] | None = None  # per-class calibration, None = uncalibrated
    tta: bool = False                     # predictions averaged over the photo and its mirror


class ScreeningResult(SQLModel):
    screening_id: int
    overall: str         # "Possible: Glaucoma" | "No Myopia, Cataract, Glaucoma or Diabetic Retinopathy detected"
    any_positive: bool
    findings: list[Finding]
    maps: list[AttentionMap] = []
    source: Literal["live", "fixture"]
    demo: bool = False   # True for a precomputed demo result (source "fixture"), never for a live run
    latency_ms: int
    disclaimer: str
    model: ModelInfo | None = None  # None only on results stored before model tracking existed

    @model_validator(mode="after")
    def _fixture_is_demo(self) -> "ScreeningResult":
        self.demo = self.source == "fixture"  # also labels results stored before this field existed
        return self


class ImageMeta(SQLModel):
    name: str
    width: int
    height: int
    type: str
    bytes: int
    sharpness: float | None = None


class SummaryQuality(SQLModel):
    ok: bool | None          # None when the photo's quality was not recorded
    label: str
    detail: str


class SummaryFinding(SQLModel):
    code: str
    disease: str
    flagged: bool
    plain: str
    borderline: bool         # the score is within 0.10 of the cut-off


class SummaryNextStep(SQLModel):
    urgency: Literal["none", "routine", "consider", "soon"]
    text: str


class PatientSummary(SQLModel):
    """Plain-language reading of one screening; built by `patient_summary` from the stored fields only."""
    state: Literal["no_photo", "waiting", "result", "experimental"]
    validated_source: bool        # only a clinic fundus photo is a source the model was evaluated on
    is_diagnosis: bool = False    # always false: a screening is not a diagnosis
    quality: SummaryQuality | None = None
    headline: str
    findings: list[SummaryFinding] = []
    uncertainty: list[str] = []
    next_step: SummaryNextStep
    urgent_care: str              # shown whatever the result is
    limits: list[str] = []


class ScreeningRead(ScreeningBase):
    id: int
    owner_id: int
    has_image: bool
    image: ImageMeta | None = None
    latest_review: str | None = None   # decision of the newest review: agree | disagree | unsure
    result: ScreeningResult | None = None
    summary: PatientSummary | None = None
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
