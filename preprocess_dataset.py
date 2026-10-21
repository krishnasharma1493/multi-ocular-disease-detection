"""Build data/labels.csv: one row per eye image with per-eye labels and a
patient-level train/val/test split (both eyes of a patient share a split).

Strictly targets 4 diseases:
1. Myopia (M)
2. Cataract (C)
3. Glaucoma (G)
4. Diabetic Retinopathy (D)

Any images with other ocular diseases (AMD, hypertensive retinopathy, drusen,
epiretinal membranes, etc.) are deleted/dropped and NOT used for training.
Clean normal fundus photos are retained as negative controls.
"""
import os
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from src.external_datasets import build_external_labels
from src.labels import LABELS, UNUSABLE, eye_labels

IMG_DIR = 'data/preprocessed_images'
OUT_CSV = 'data/labels.csv'
SEED = 42


def build_labels(full_df='data/full_df.csv', img_dir=IMG_DIR, out_csv=OUT_CSV, seed=SEED):
    df = pd.read_csv(full_df)
    rows, dropped = [], {'missing': 0, 'unusable': 0, 'ambiguous': 0, 'other_disease': 0}
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
        if other_disease:
            dropped['other_disease'] += 1
            continue
        rows.append({'source': 'ODIR', 'patient_id': row['ID'], 'eye': eye, 'filename': filename,
                     'path': os.path.join(img_dir, filename),
                     'age': row['Patient Age'], 'sex': row['Patient Sex'],
                     'keywords': keywords, **labels})
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

    print(f'ODIR images: {len(data)} (dropped: {dropped})')

    # External datasets
    ext_data = build_external_labels(seed=seed)
    if ext_data is None and os.path.exists(out_csv):
        # Preserve external data already preprocessed in labels.csv
        old_labels = pd.read_csv(out_csv)
        ext_data = old_labels[old_labels['source'] != 'ODIR'].copy()
        # Ensure all LABELS columns are present
        for l in LABELS:
            if l not in ext_data.columns:
                ext_data[l] = float('nan')
        cols = [c for c in data.columns if c in ext_data.columns]
        ext_data = ext_data[cols]

    if ext_data is not None and not ext_data.empty:
        data = pd.concat([data, ext_data], ignore_index=True)

    data.to_csv(out_csv, index=False)
    print(f'Wrote {len(data)} images to {out_csv}')
    print(data.groupby('split')[LABELS].sum().assign(images=data['split'].value_counts()))
    return data


if __name__ == '__main__':
    build_labels()
