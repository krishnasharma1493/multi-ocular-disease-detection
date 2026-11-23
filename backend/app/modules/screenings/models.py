from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class ScreeningStatus(str, Enum):
    pending = "pending"      # created, or a new image uploaded; not analyzed yet
    analyzed = "analyzed"    # AI result available
    reviewed = "reviewed"    # a person has recorded a read of the result


class Eye(str, Enum):
    left = "left"
    right = "right"
    unknown = "unknown"


class ImageSource(str, Enum):
    """Where the photo came from. Only clinic_fundus is a source the model has been evaluated on."""
    clinic_fundus = "clinic_fundus"  # a fundus photo from an eye clinic
    phone_20d = "phone_20d"          # a smartphone photo taken through a +20D lens (not validated)
    unknown = "unknown"              # not recorded (older screenings)


class ScreeningBase(SQLModel):
    patient_ref: str = Field(default="Me", min_length=1, max_length=40)  # patients never type one; camp use: "P-0147"
    eye: Eye = Eye.unknown
    image_source: ImageSource = ImageSource.unknown
    notes: str | None = Field(default=None, max_length=2000)
    status: ScreeningStatus = ScreeningStatus.pending


class Screening(ScreeningBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    image_filename: str | None = Field(default=None, max_length=80)  # random server-side name in UPLOAD_DIR
    image_meta: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # name, width, height, type, bytes
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # last ScreeningResult
    analyzed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
