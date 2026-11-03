"""Build data/labels.csv: one row per eye image with per-eye labels and a
patient-level train/val/test split (both eyes of a patient share a split).

Strictly targets 4 diseases:
1. Myopia (M)
2. Cataract (C)
3. Glaucoma (G)
4. Diabetic Retinopathy (D)

By default, images with other ocular diseases (AMD, hypertensive retinopathy, drusen,
epiretinal membranes, etc.) are dropped. With other_disease_negatives=True they are kept
as negatives for all four diseases, so lookalikes (drusen vs DR exudates) are learnt as "not
DR". Eyes whose other finding mimics a target disease on a photo (refractive media opacity
looks like cataract) stay dropped. Clean normal fundus photos are always negative controls.

keep_splits_from=<existing labels.csv> keeps every patient already in that file in the same
split, so a model trained on it is never scored on its own training patients. New patients are
split 80/10/10 by a hash of their id.
"""
import hashlib
import os
import re
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from src.external_datasets import build_external_labels
from src.labels import LABELS, UNUSABLE, eye_labels

IMG_DIR = 'data/preprocessed_images'
OUT_CSV = 'data/labels.csv'
SEED = 42


# Other findings that look like a target disease on a fundus photo: never used as negatives
MIMICS = re.compile(r'refractive media opacity', re.I)


def _hash_split(patient_id):
    """Deterministic 80/10/10 split for a patient that has no split yet."""
    bucket = int(hashlib.sha256(str(patient_id).encode()).hexdigest(), 16) % 10
    return 'test' if bucket == 0 else 'val' if bucket == 1 else 'train'


def build_labels(full_df='data/full_df.csv', img_dir=IMG_DIR, out_csv=OUT_CSV, seed=SEED,
                 other_disease_negatives=False, keep_splits_from=None):
    df = pd.read_csv(full_df)
    rows, dropped = [], {'missing': 0, 'unusable': 0, 'ambiguous': 0, 'other_disease': 0, 'mimic': 0}
    for _, row in df.iterrows():
        filename = row['filename']
        eye = 'left' if filename.endswith('left.jpg') else 'right'
        keywords = row['Left-Diagnostic Keywords' if eye == 'left' else 'Right-Diagnostic Keywords']
        if not os.path.exists(os.path.join(img_dir, filename)):
            dropped['missing'] += 1
            continue
        if UNUSABLE.search(keywords):
            dropped['unusable'] += 1
            continue
        labels, ambiguous, other_disease = eye_labels(keywords)
        if ambiguous:
            dropped['ambiguous'] += 1
            continue
        if other_disease and (not other_disease_negatives or MIMICS.search(keywords)):
            dropped['mimic' if other_disease_negatives else 'other_disease'] += 1
            continue
        rows.append({'source': 'ODIR', 'patient_id': row['ID'], 'eye': eye, 'filename': filename,
                     'path': os.path.join(img_dir, filename),
                     'age': row['Patient Age'], 'sex': row['Patient Sex'],
                     'keywords': keywords, **labels, 'other_disease': bool(other_disease)})
    data = pd.DataFrame(rows)

    # Stratify on the rarest disease present so rare classes land in every split
    rarity = data[LABELS].sum().sort_values().index.tolist()
    strat = data[LABELS].apply(lambda r: next((l for l in rarity if r[l]), 'none'), axis=1)
    folds = StratifiedGroupKFold(n_splits=10, shuffle=True, random_state=seed)
    data['split'] = 'train'
    for fold, (_, idx) in enumerate(folds.split(data, strat, groups=data['patient_id'])):
        if fold == 0:
            data.loc[data.index[idx], 'split'] = 'test'
        elif fold == 1:
            data.loc[data.index[idx], 'split'] = 'val'

    old = pd.read_csv(keep_splits_from) if keep_splits_from else None
    if old is not None:
        # Same patients, same split as the file the current model was trained on; new patients by hash
        odir = old[old['source'] == 'ODIR']
        known_split = odir.groupby(odir['patient_id'].astype(str))['split'].first()  # ids are text in the CSV
        data['split'] = [known_split.get(str(pid), _hash_split(f'ODIR:{pid}')) for pid in data['patient_id']]

    print(f'ODIR images: {len(data)} (dropped: {dropped})')

    # External datasets in data/external/. If the raw datasets have been deleted to save space,
    # keep the external rows of the existing labels.csv: their preprocessed images and splits stay valid.
    reuse_from = keep_splits_from or out_csv
    ext_data = None if old is not None else build_external_labels(seed=seed)
    if ext_data is None and os.path.exists(reuse_from):
        # keep_splits_from: external rows are reused as they are, splits included
        ext_data = pd.read_csv(reuse_from)
        ext_data = ext_data[ext_data['source'] != 'ODIR']
        missing = ext_data[~ext_data['path'].map(os.path.exists)]
        if len(missing):
            raise FileNotFoundError(f'{len(missing)} external images in {reuse_from} no longer exist '
                                    f'(e.g. {missing["path"].iloc[0]}); restore data/external/ and rebuild.')
        if len(ext_data):
            print(f'Reusing {len(ext_data)} external images and their splits '
                  f'from {reuse_from} ({", ".join(sorted(ext_data["source"].unique()))}).')
    if ext_data is not None and len(ext_data):
        data = pd.concat([data, ext_data[[c for c in ext_data.columns if c in data.columns]]],
                         ignore_index=True)

    data.to_csv(out_csv, index=False)
    print(f'Wrote {len(data)} images to {out_csv}')
    print(data.groupby('split')[LABELS].sum().assign(images=data['split'].value_counts()))
    return data


if __name__ == '__main__':
    build_labels()
