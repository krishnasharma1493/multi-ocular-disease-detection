from pydantic import BaseModel


class DiseaseCard(BaseModel):
    code: str
    disease: str
    threshold: float | None
    test_precision: float | None
    test_recall: float | None
    test_f1: float | None
    test_ap: float | None
    test_roc_auc: float | None
    test_positives: int | None
    odir_ap: float | None        # ODIR-only test images: everyday fundus photos, not specialist datasets
    odir_roc_auc: float | None


class SourceDataset(BaseModel):
    name: str
    images: int | None
    diseases: list[str]          # diseases with positives in this source, most first


class ModelCard(BaseModel):
    architecture: str
    model_name: str
    img_size: int | None
    live: bool                   # False = fixtures only (USE_MOCKS or load failure)
    device: str | None
    test_images: int | None
    checkpoint_sha256: str | None
    checkpoint_modified: str | None
    diseases: list[DiseaseCard]
    sources: list[SourceDataset]
    limitations: list[str]
