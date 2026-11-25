"""Cut-offs for small photos: phone + 20D shots and pictures pasted from the web.

A small photo is enlarged to 512 px before the model sees it, and that blur looks like a cataract's haze.
With the trained cut-offs, 64% of healthy ODIR test eyes shrunk to 240 px were flagged "Possible: Cataract"
and diabetic retinopathy was found in only 24%. The model still ranks these photos well (cataract AUC 0.95),
so only the cut-offs change; the model itself is untouched.

SMALL_CUTOFFS were fitted on the ODIR validation eyes shrunk to 240 px and saved as JPEG quality 60, with
the rule the trained cut-offs use (src.calibration.target_thresholds). From 240 px up to FULL_SIZE_PX the
cut-off moves gradually, in log-odds, back to the trained one. For diabetic retinopathy it is back at
320 px, the choice that kept its specificity near the 0.85 floor on validation.
On the ODIR test eyes, averaged over 240/320/400/460 px (sensitivity/specificity, before -> after):
cataract 0.94/0.67 -> 0.80/0.94, glaucoma 0.56/0.96 -> 0.70/0.93, diabetic retinopathy 0.52/0.86 ->
0.58/0.82, myopia unchanged at 0.84/1.00. Photos 512 px and larger keep the trained cut-offs exactly.

The values belong to one checkpoint (RUN_ID); any other model uses its trained cut-offs unchanged.
Refit for a new checkpoint with `python -m src.small_photo_cutoffs` from the repository root.
"""
import math

RUN_ID = "20261103-1108-b0-512-ft"
SMALL_PX = 240                                  # the photo size SMALL_CUTOFFS were fitted at
SMALL_CUTOFFS = [0.9704, 0.9491, 0.0926, 0.1959]  # M, C, G, D
FULL_SIZE_PX = [512, 512, 512, 320]             # size from which each disease uses its trained cut-off
SMALL_PHOTO_PX = 400                            # below this the result says the photo is small


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


def cutoffs(trained: list[float], photo_px: int | None, run_id: str | None) -> list[float]:
    """The cut-off per disease for a photo whose retina is photo_px pixels across."""
    if run_id != RUN_ID or photo_px is None or len(trained) != len(SMALL_CUTOFFS):
        return list(trained)
    out = []
    for t, small, full in zip(trained, SMALL_CUTOFFS, FULL_SIZE_PX):
        w = min(1.0, max(0.0, (photo_px - SMALL_PX) / (full - SMALL_PX)))
        if w == 1.0:  # full size: the trained cut-off, exactly
            out.append(t)
            continue
        out.append(1 / (1 + math.exp(-((1 - w) * _logit(small) + w * _logit(t)))))
    return out
