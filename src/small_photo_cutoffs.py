"""Fit the small-photo cut-offs the web app uses (backend/app/modules/screenings/cutoffs.py).

Each ODIR validation eye is shrunk to 240 px and saved as JPEG quality 60 (a phone + 20D shot or a
thumbnail from the web), prepared like an upload and scored with the checkpoint. The cut-offs then come
from the same rule as the trained ones (calibration.target_thresholds). No training: one pass over
about 600 photos.

    python -m src.small_photo_cutoffs [checkpoint]
"""
import io
import sys

import numpy as np
import pandas as pd
import torch
from PIL import Image

from .calibration import target_thresholds
from .dataset import val_transforms
from .labels import LABELS, UNKNOWN
from .model import calibrated_sigmoid, forward_logits, get_device, load_checkpoint
from .preprocessing import prepare_fundus

SMALL_PX, JPEG_QUALITY = 240, 60


def shrink(path, px=SMALL_PX, quality=JPEG_QUALITY):
    small = Image.open(path).convert('RGB').resize((px, px), Image.BILINEAR)
    buf = io.BytesIO()
    small.save(buf, 'JPEG', quality=quality)
    return Image.open(io.BytesIO(buf.getvalue())).convert('RGB')


def main(checkpoint='outputs/best_efficientnet_b0.pth'):
    device = get_device()
    model, ck = load_checkpoint(checkpoint, device)
    data = pd.read_csv(ck['meta']['labels_csv'])
    data = data[(data.split == 'val') & (data.source == 'ODIR')].reset_index(drop=True)
    tf = val_transforms(ck['img_size'])
    probs = []
    for i in range(0, len(data), 16):
        x = torch.stack([tf(image=prepare_fundus(shrink(p)))['image'] for p in data.path[i:i + 16]]).to(device)
        with torch.no_grad():
            probs.append(calibrated_sigmoid(forward_logits(model, x, ck['tta']), ck['temperature']).cpu().numpy())
    thresholds, report = target_thresholds(data[LABELS].fillna(UNKNOWN).values, np.concatenate(probs))
    print(f"run {ck['meta']['run_id']}: SMALL_CUTOFFS = {[round(t, 4) for t in thresholds]}")
    for code, r in report.items():
        print(f"  {code}: sensitivity {r['sensitivity']:.2f}, specificity {r['specificity']:.2f}")
    return thresholds


if __name__ == '__main__':
    main(*sys.argv[1:])
