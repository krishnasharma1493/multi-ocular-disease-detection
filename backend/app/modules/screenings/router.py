import io
import math
import secrets

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import func
from sqlmodel import col, select

from app.core.config import settings
from app.core.deps import CurrentUser, SessionDep
from app.core.errors import AppError
from app.core.schemas import Envelope, Page, Pagination
from app.modules.reviews.models import Review
from app.modules.screenings.models import Screening, ScreeningStatus
from app.modules.screenings.schemas import (ScreeningCreate, ScreeningRead, ScreeningResult, ScreeningStats,
                                            ScreeningUpdate)
from app.modules.screenings.service import MIN_SHARPNESS, image_quality, run_screening
from app.utils.ownership import get_owned_or_404
from app.utils.time import utcnow

router = APIRouter(prefix="/screenings", tags=["screenings"])
ALLOWED_TYPES = {"JPEG": (".jpg", "JPG"), "PNG": (".png", "PNG")}


def _mb(n: int) -> str:
    return f"{max(1, round(n / 1024))} KB" if n < 102400 else f"{n / 1024 / 1024:.1f} MB"


def _latest_reviews(session, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = session.exec(select(Review).where(col(Review.screening_id).in_(ids))
                        .order_by(col(Review.created_at), col(Review.id))).all()
    return {r.screening_id: r.decision.value for r in rows}  # later rows overwrite: newest wins


def to_read(screening: Screening, latest: dict[int, str] | None = None) -> ScreeningRead:
    return ScreeningRead.model_validate(screening, update={
        "has_image": screening.image_filename is not None, "image": screening.image_meta,
        "latest_review": (latest or {}).get(int(screening.id or 0))})


@router.get("", response_model=Page[ScreeningRead], summary="List own screenings")
def list_screenings(
    session: SessionDep,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=40),
    status: ScreeningStatus | None = None,
):
    stmt = select(Screening).where(Screening.owner_id == user.id)
    if q and q.strip():
        stmt = stmt.where(col(Screening.patient_ref).ilike(f"%{q.strip()}%"))
    if status:
        stmt = stmt.where(Screening.status == status)
    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    rows = session.exec(
        stmt.order_by(col(Screening.created_at).desc(), col(Screening.id).desc()).offset((page - 1) * limit).limit(limit)
    ).all()
    latest = _latest_reviews(session, [int(r.id) for r in rows])
    return Page(data=[to_read(r, latest) for r in rows],
                pagination=Pagination(total=total, page=page, limit=limit, total_pages=math.ceil(total / limit)))


# Declared before /{screening_id} so "stats" is never parsed as an id
@router.get("/stats", response_model=Envelope[ScreeningStats], summary="Ledger numbers")
def screening_stats(session: SessionDep, user: CurrentUser):
    rows = session.exec(
        select(Screening).where(Screening.owner_id == user.id)
        .order_by(col(Screening.created_at).desc(), col(Screening.id).desc())
    ).all()
    by_status = {s.value: 0 for s in ScreeningStatus}
    positives: dict[str, int] = {}
    analyzed = flagged = 0
    for row in rows:
        by_status[ScreeningStatus(row.status).value] += 1
        if row.result:
            analyzed += 1
            flagged += int(bool(row.result.get("any_positive")))
            for finding in row.result.get("findings", []):
                if finding["positive"]:
                    positives[finding["disease"]] = positives.get(finding["disease"], 0) + 1
    return Envelope(data=ScreeningStats(total=len(rows), by_status=by_status, analyzed=analyzed, flagged=flagged,
                                        positives=positives, recent=[to_read(r, _latest_reviews(session, [int(x.id) for x in rows[:5]])) for r in rows[:5]]))


@router.post("", response_model=Envelope[ScreeningRead], status_code=201, summary="Create a screening")
def create_screening(body: ScreeningCreate, session: SessionDep, user: CurrentUser):
    screening = Screening.model_validate(body, update={"owner_id": user.id, "patient_ref": body.patient_ref.strip()})
    session.add(screening)
    session.commit()
    session.refresh(screening)
    return Envelope(data=to_read(screening))


@router.get("/{screening_id}", response_model=Envelope[ScreeningRead], summary="Get one screening")
def get_screening(screening_id: int, session: SessionDep, user: CurrentUser):
    screening = get_owned_or_404(session, Screening, screening_id, user.id)
    return Envelope(data=to_read(screening, _latest_reviews(session, [screening_id])))


@router.patch("/{screening_id}", response_model=Envelope[ScreeningRead], summary="Update a screening")
def update_screening(screening_id: int, body: ScreeningUpdate, session: SessionDep, user: CurrentUser):
    screening = get_owned_or_404(session, Screening, screening_id, user.id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise AppError(400, "INVALID_REQUEST", "Nothing to update")
    screening.sqlmodel_update(changes)
    screening.updated_at = utcnow()
    session.add(screening)
    session.commit()
    session.refresh(screening)
    return Envelope(data=to_read(screening))


@router.delete("/{screening_id}", response_model=Envelope[dict[str, int]], summary="Delete a screening")
def delete_screening(screening_id: int, session: SessionDep, user: CurrentUser):
    screening = get_owned_or_404(session, Screening, screening_id, user.id)
    for review in session.exec(select(Review).where(Review.screening_id == screening_id)).all():
        session.delete(review)
    if screening.image_filename:
        (settings.upload_dir / screening.image_filename).unlink(missing_ok=True)
    session.delete(screening)
    session.commit()
    return Envelope(data={"id": screening_id})


@router.put("/{screening_id}/image", response_model=Envelope[ScreeningRead], summary="Upload or replace the fundus photo")
def upload_image(screening_id: int, session: SessionDep, user: CurrentUser,
                 file: UploadFile = File(..., description="JPEG or PNG fundus photo")):
    screening = get_owned_or_404(session, Screening, screening_id, user.id)
    name = (file.filename or "upload")[:120]
    data = file.file.read(settings.max_upload_bytes + 1)  # never reads more than the cap + 1 byte
    if len(data) > settings.max_upload_bytes:
        raise AppError(413, "PAYLOAD_TOO_LARGE", f"This photo is larger than {settings.MAX_UPLOAD_MB} MB",
                       {"file": [f"{name} · over {settings.MAX_UPLOAD_MB} MB"]})
    if not data:
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "The file is empty", {"file": [name]})
    try:
        with Image.open(io.BytesIO(data)) as probe:
            kind = probe.format
            probe.verify()  # rejects files that only claim to be images (and decompression bombs)
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        kind = None
    if kind not in ALLOWED_TYPES:
        ext = name.rsplit(".", 1)[-1].upper() if "." in name else "not an image"
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", f"This file is {ext}, not JPG or PNG",
                       {"file": [f"{name} · {_mb(len(data))}"]})
    sharpness, fundus = image_quality(image)
    if sharpness < MIN_SHARPNESS or not fundus:
        raise AppError(422, "IMAGE_QUALITY", "Too blurred to screen, or not a fundus photo",
                       {"file": [f"SHARPNESS {sharpness:.2f} · MINIMUM {MIN_SHARPNESS:.2f}" if fundus
                                 else "NO FUNDUS FOUND IN THE PHOTO"]})
    suffix, label = ALLOWED_TYPES[kind]
    if screening.image_filename:
        (settings.upload_dir / screening.image_filename).unlink(missing_ok=True)
    screening.image_filename = f"{secrets.token_hex(16)}{suffix}"  # random server-side name
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / screening.image_filename).write_bytes(data)
    screening.image_meta = {"name": name, "width": image.width, "height": image.height, "type": label,
                            "bytes": len(data), "sharpness": round(sharpness, 2)}
    screening.result, screening.analyzed_at = None, None  # an old result never describes a new photo
    screening.status = ScreeningStatus.pending
    screening.updated_at = utcnow()
    session.add(screening)
    session.commit()
    session.refresh(screening)
    return Envelope(data=to_read(screening))


@router.get("/{screening_id}/image", response_class=FileResponse, summary="Download the fundus photo")
def get_image(screening_id: int, session: SessionDep, user: CurrentUser):
    screening = get_owned_or_404(session, Screening, screening_id, user.id)
    path = settings.upload_dir / screening.image_filename if screening.image_filename else None
    if path is None or not path.is_file():
        raise AppError(404, "NOT_FOUND", "No image uploaded yet")
    return FileResponse(path, headers={"Cache-Control": "private, no-store"})


@router.post("/{screening_id}/analyze", response_model=Envelope[ScreeningResult], summary="Four-disease screening")
def analyze_screening(screening_id: int, session: SessionDep, user: CurrentUser):
    screening = get_owned_or_404(session, Screening, screening_id, user.id)
    if not screening.image_filename or not (settings.upload_dir / screening.image_filename).is_file():
        raise AppError(400, "NO_IMAGE", "Upload a fundus photo before analyzing")
    result = run_screening(screening)
    screening.result = result.model_dump(mode="json")
    screening.analyzed_at = utcnow()
    screening.updated_at = utcnow()
    if screening.status == ScreeningStatus.pending:
        screening.status = ScreeningStatus.analyzed
    session.add(screening)
    session.commit()
    return Envelope(data=result)
