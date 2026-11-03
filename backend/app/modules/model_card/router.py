import hashlib
import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from fastapi import APIRouter

from app.core.config import settings
from app.core.deps import CurrentUser
from app.core.schemas import Envelope
from app.modules.model_card.schemas import DiseaseCard, ModelCard, SourceDataset
from app.modules.screenings import inference
from src.labels import DISEASES, LABELS

router = APIRouter(prefix="/model", tags=["model"])

LIMITATIONS = [
    "It screens only these four diseases.",
    "It may flag photos that show other conditions.",
    "The myopia class learned pathological myopia, so mild myopia can look normal.",
    "Glaucoma on everyday camp photos (ODIR) is its weakest area.",
    "It is not clinically validated; accuracy on other cameras and populations is unknown.",
]


def _num(value: Any) -> float | None:
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)


def _ci(value: Any) -> list[float] | None:
    if not value or any(_num(v) is None for v in value):
        return None
    return [float(v) for v in value]


@lru_cache(maxsize=1)
def _checkpoint_facts() -> tuple[str | None, str | None]:
    path = settings.model_checkpoint_path
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        return digest, modified
    except OSError:
        return None, None


@router.get("", response_model=Envelope[ModelCard], summary="Model card")
def read_model_card(_: CurrentUser):
    try:
        metrics = json.loads(settings.model_metrics_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        metrics = {}
    test = metrics.get("test", {})
    per_class, by_source = test.get("per_class", {}), test.get("by_source", {})
    odir_only = test.get("odir_only", {}).get("per_class", {})
    screener = None if settings.USE_MOCKS else inference.screener
    names = dict(zip(LABELS, DISEASES))
    codes = screener.labels if screener else LABELS
    diseases = []
    for i, code in enumerate(codes):
        name = names.get(code, code)
        m = per_class.get(name, {})
        odir = by_source.get(name, {}).get("ODIR", {})
        o = odir_only.get(name, {})
        diseases.append(DiseaseCard(
            code=code, disease=name,
            threshold=screener.thresholds[i] if screener else _num(m.get("threshold")),
            test_precision=_num(m.get("precision")), test_recall=_num(m.get("recall")), test_f1=_num(m.get("f1")),
            test_ap=_num(m.get("ap")), test_roc_auc=_num(m.get("roc_auc")), test_positives=m.get("support"),
            odir_ap=_num(odir.get("ap")), odir_roc_auc=_num(odir.get("roc_auc")),
            odir_recall=_num(o.get("recall")), odir_recall_ci=_ci(o.get("recall_ci")),
            odir_specificity=_num(o.get("specificity")), odir_specificity_ci=_ci(o.get("specificity_ci")),
            odir_positives=o.get("support"),
        ))
    sources = []
    for name, info in (metrics.get("dataset", {}).get("sources") or {}).items():
        pos = {d: n for d, n in (info.get("positives") or {}).items() if n}
        sources.append(SourceDataset(name=name, images=info.get("images"), diseases=sorted(pos, key=pos.get, reverse=True)))
    sha, modified = _checkpoint_facts()
    model_name = screener.checkpoint["model_name"] if screener else metrics.get("config", {}).get("model_name", "efficientnet_b0")
    return Envelope(data=ModelCard(
        architecture="EfficientNet-B0, ImageNet-pretrained, fine-tuned for 4-label screening",
        model_name=model_name,
        img_size=screener.checkpoint["img_size"] if screener else metrics.get("config", {}).get("img_size"),
        live=screener is not None, device=screener.device if screener else None,
        test_images=test.get("num_images"), checkpoint_sha256=sha, checkpoint_modified=modified,
        diseases=diseases, sources=sources, limitations=LIMITATIONS,
        run_id=(screener.checkpoint.get("meta") or {}).get("run_id") if screener else None,
    ))
